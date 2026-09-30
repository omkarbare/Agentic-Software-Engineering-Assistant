"""Deterministic policy checks for filesystem access, patches, and commands."""

from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass
from pathlib import Path

from coding_agent.utils.redaction import redact


class PolicyDenied(ValueError):
    """Raised when an action violates the configured workspace policy."""


@dataclass(frozen=True)
class Decision:
    allowed: bool
    approval_required: bool = False
    reason: str = "allowed"


class PolicyEngine:
    def __init__(
        self,
        workspace: Path,
        max_file_bytes: int = 1_000_000,
        max_patch_bytes: int = 100_000,
        denied_paths: set[str] | None = None,
    ):
        self.workspace = workspace.resolve(strict=True)
        self.max_file_bytes = max_file_bytes
        self.max_patch_bytes = max_patch_bytes
        self.denied_paths = {item.lower() for item in (denied_paths or set())} | {
            ".git",
            ".ssh",
            ".aws",
            ".azure",
            ".config",
            "id_rsa",
            "id_ed25519",
            "credentials",
        }

    def resolve_path(self, raw_path: str, *, write: bool = False) -> Path:
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = self.workspace / candidate
        resolved = candidate.resolve(strict=False)
        if not resolved.is_relative_to(self.workspace):
            raise PolicyDenied("path escapes the selected workspace")
        if not write:
            resolved = resolved.resolve(strict=True)
        parts = {part.lower() for part in resolved.relative_to(self.workspace).parts}
        if parts & self.denied_paths or any(part.endswith((".pem", ".key")) for part in parts):
            raise PolicyDenied("sensitive paths are not accessible")
        if any(part == ".env" or part.startswith(".env.") for part in parts):
            raise PolicyDenied("environment files are not accessible")
        return resolved

    def check_read(self, raw_path: str) -> Path:
        path = self.resolve_path(raw_path)
        if not path.is_file():
            raise PolicyDenied("read target must be a regular file")
        if path.stat().st_size > self.max_file_bytes:
            raise PolicyDenied("file exceeds the configured read limit")
        return path

    def check_write(self, raw_path: str) -> Path:
        path = self.resolve_path(raw_path, write=True)
        if path.name.lower() in {".env", ".env.local", ".env.production"}:
            raise PolicyDenied("writes to environment files are denied")
        return path

    def check_patch(self, diff: str) -> Decision:
        if len(diff.encode()) > self.max_patch_bytes:
            raise PolicyDenied("patch exceeds the configured size limit")
        if not diff.startswith("--- ") or "+++ " not in diff:
            raise PolicyDenied("a unified diff with file headers is required")
        if redact(diff) != diff:
            raise PolicyDenied("patch appears to contain a secret value")
        names = re.findall(r"^(?:\+\+\+|---) [ab]/(.+)$", diff, re.MULTILINE)
        if not names or len(set(names)) * 2 != len(names):
            raise PolicyDenied("malformed or multi-workspace patch")
        for name in set(names):
            self.check_write(name)
        return Decision(True, approval_required=True, reason="all file edits require approval")

    def check_command(self, argv: list[str]) -> Decision:
        if not argv or any(not isinstance(arg, str) for arg in argv):
            raise PolicyDenied("argv must be a non-empty list of strings")
        if any(
            token in arg for arg in argv for token in (";", "&&", "||", "|", "`", "$(", ">", "<")
        ):
            raise PolicyDenied("shell operators and redirection are not allowed")
        executable = Path(argv[0]).name
        if executable not in {"pytest", "ruff", "mypy", "rg", "git", "python", "uv", "npm", "pnpm"}:
            raise PolicyDenied(f"executable is not allowlisted: {executable}")
        joined = " ".join(argv).lower()
        denied = (
            "sudo",
            "curl",
            "wget",
            "ssh",
            "scp",
            "docker",
            "rm ",
            "git push",
            "git reset",
            "git clean",
            "git checkout",
            "git commit",
        )
        if any(item in joined for item in denied):
            raise PolicyDenied("command is denied by policy")
        if executable == "git" and (len(argv) < 2 or argv[1] not in {"status", "diff", "grep"}):
            raise PolicyDenied("git subcommand is not allowlisted")
        if executable == "python" and argv[1:] not in (
            ["-m", "pytest"],
            ["-m", "pytest", "-q"],
            ["-m", "ruff", "check"],
            ["-m", "mypy"],
        ):
            raise PolicyDenied("python may only invoke approved test and analysis modules")
        if executable == "uv" and (
            len(argv) < 3 or argv[1] != "run" or argv[2] not in {"pytest", "ruff", "mypy", "python"}
        ):
            raise PolicyDenied("uv may only run approved test and analysis commands")
        if (
            executable == "uv"
            and argv[2] == "python"
            and argv[3:] not in (["-m", "pytest"], ["-m", "pytest", "-q"])
        ):
            raise PolicyDenied("uv may only run the approved Python test module")
        if executable in {"npm", "pnpm"}:
            safe_direct = len(argv) == 2 and argv[1] == "test"
            safe_script = (
                len(argv) == 3 and argv[1] == "run" and argv[2] in {"lint", "typecheck", "test"}
            )
            if not (safe_direct or safe_script):
                raise PolicyDenied("package command is not allowlisted")
        return Decision(True, approval_required=True, reason="command execution requires approval")


def parse_command(value: str) -> list[str]:
    """Parse a display command without invoking a shell."""
    return shlex.split(value, posix=os.name != "nt")
