"""Workspace tools expose bounded reads and approval-gated patch application."""

from __future__ import annotations

import os
import re
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from coding_agent.policy.engine import PolicyEngine
from coding_agent.utils.redaction import redact


def list_directory(
    policy: PolicyEngine, path: str = ".", max_depth: int = 2, include_hidden: bool = False
) -> list[str]:
    if not 0 <= max_depth <= 5:
        raise ValueError("max_depth must be between 0 and 5")
    root = policy.resolve_path(path)
    if not root.is_dir():
        raise ValueError("directory path required")
    rows: list[str] = []
    for current, dirs, files in os.walk(root):
        depth = len(Path(current).relative_to(root).parts)
        dirs[:] = sorted(
            d
            for d in dirs
            if (include_hidden or not d.startswith("."))
            and d not in {".git", ".venv", "node_modules"}
        )
        if depth >= max_depth:
            dirs.clear()
        rows.extend(
            str(Path(current, name).relative_to(policy.workspace))
            for name in sorted(files)
            if include_hidden or not name.startswith(".")
        )
    return rows[:2000]


def read_file(
    policy: PolicyEngine,
    path: str,
    start_line: int | None = None,
    end_line: int | None = None,
    max_bytes: int = 100_000,
) -> str:
    target = policy.check_read(path)
    if max_bytes < 1 or max_bytes > policy.max_file_bytes:
        raise ValueError("max_bytes is outside policy limits")
    raw = target.read_bytes()[:max_bytes]
    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()
    if start_line is not None or end_line is not None:
        first = max((start_line or 1) - 1, 0)
        last = end_line if end_line is not None else len(lines)
        if last < first:
            raise ValueError("end_line precedes start_line")
        text = "\n".join(lines[first:last])
    return redact(text)


def search_code(
    policy: PolicyEngine,
    query: str,
    path: str = ".",
    glob: str | None = None,
    max_results: int = 100,
) -> list[dict[str, Any]]:
    if not query or max_results < 1 or max_results > 500:
        raise ValueError("query and result limit are required")
    root = policy.resolve_path(path)
    args = [
        "rg",
        "--line-number",
        "--no-heading",
        "--color",
        "never",
        "--max-count",
        str(max_results),
        "--",
        query,
        str(root),
    ]
    if glob:
        args[1:1] = ["--glob", glob]
    policy.check_command(args)
    result = subprocess.run(
        args, cwd=policy.workspace, capture_output=True, text=True, timeout=10, check=False
    )
    if result.returncode not in (0, 1):
        raise RuntimeError("code search failed")
    rows: list[dict[str, Any]] = []
    for line in result.stdout.splitlines()[:max_results]:
        match = re.match(r"(.+?):(\d+):(.*)", line)
        if match:
            rows.append(
                {
                    "path": str(Path(match.group(1)).resolve().relative_to(policy.workspace)),
                    "line": int(match.group(2)),
                    "text": redact(match.group(3))[:500],
                }
            )
    return rows


def get_git_status(policy: PolicyEngine) -> str:
    policy.check_command(["git", "status", "--short"])
    result = subprocess.run(
        ["git", "status", "--short"],
        cwd=policy.workspace,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if result.returncode:
        return "Workspace is not a git repository or git status failed."
    return redact(result.stdout[:20_000])


def get_git_diff(policy: PolicyEngine) -> str:
    policy.check_command(["git", "diff", "--no-ext-diff", "--", "."])
    result = subprocess.run(
        ["git", "diff", "--no-ext-diff", "--", "."],
        cwd=policy.workspace,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if result.returncode:
        return "git diff failed."
    sections: list[str] = []
    current: list[str] = []
    sensitive = False
    for line in result.stdout.splitlines(keepends=True):
        if line.startswith("diff --git "):
            if current and not sensitive:
                sections.extend(current)
            current = [line]
            sensitive = False
        else:
            current.append(line)
            if line.startswith(("--- a/", "+++ b/")):
                raw_path = line[6:].strip()
                if raw_path != "/dev/null":
                    try:
                        policy.resolve_path(raw_path)
                    except (ValueError, OSError):
                        sensitive = True
    if current and not sensitive:
        sections.extend(current)
    return redact("".join(sections)[:50_000])


def apply_unified_diff(
    policy: PolicyEngine, diff: str, *, approved: bool = False
) -> dict[str, Any]:
    decision = policy.check_patch(diff)
    if decision.approval_required and not approved:
        raise PermissionError("patch requires explicit approval")
    lines = diff.splitlines()
    files: list[tuple[str, list[str]]] = []
    i = 0
    while i < len(lines):
        if not lines[i].startswith("--- "):
            raise ValueError("expected unified diff file header")
        old = lines[i][6:]
        i += 1
        if i >= len(lines) or not lines[i].startswith("+++ "):
            raise ValueError("missing new file header")
        new = lines[i][6:]
        if old.removeprefix("a/") != new.removeprefix("b/"):
            raise ValueError("renames and multi-path patches are not supported")
        target = policy.check_write(new.removeprefix("b/"))
        source = (
            target.read_text(encoding="utf-8").splitlines(keepends=True) if target.exists() else []
        )
        output: list[str] = []
        source_index = 0
        saw_hunk = False
        i += 1
        while i < len(lines) and not lines[i].startswith("--- "):
            header = lines[i]
            match = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", header)
            if not match:
                raise ValueError("invalid unified diff hunk")
            old_start = max(int(match.group(1)) - 1, 0)
            new_start = max(int(match.group(3)) - 1, 0)
            expected_old = int(match.group(2) or 1)
            expected_new = int(match.group(4) or 1)
            if old_start < source_index:
                raise ValueError("patch hunks overlap or are out of order")
            output.extend(source[source_index:old_start])
            source_index = old_start
            if len(output) != new_start:
                raise ValueError("patch new-file position does not match the hunk")
            saw_hunk = True
            seen_old = 0
            seen_new = 0
            i += 1
            while i < len(lines) and not lines[i].startswith(("@@", "--- ")):
                entry = lines[i]
                if entry.startswith((" ", "-")):
                    if (
                        source_index >= len(source)
                        or source[source_index].rstrip("\n") != entry[1:]
                    ):
                        raise ValueError("patch context does not match workspace")
                    if entry.startswith(" "):
                        output.append(source[source_index])
                        seen_new += 1
                    seen_old += 1
                    source_index += 1
                elif entry.startswith("+"):
                    output.append(entry[1:] + "\n")
                    seen_new += 1
                elif entry != "\\ No newline at end of file":
                    raise ValueError("invalid patch line")
                i += 1
            if (seen_old, seen_new) != (expected_old, expected_new):
                raise ValueError("patch hunk line counts do not match its header")
        output.extend(source[source_index:])
        if not saw_hunk:
            raise ValueError("patch file contains no hunks")
        files.append((str(target), output))
    staged: list[tuple[Path, Path]] = []
    try:
        for target_name, content in files:
            target = Path(target_name)
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".agent-tmp",
                delete=False,
            ) as stream:
                stream.write("".join(content))
                temporary = Path(stream.name)
            if target.exists():
                os.chmod(temporary, stat.S_IMODE(target.stat().st_mode))
            staged.append((temporary, target))
        for temporary, target in staged:
            temporary.replace(target)
    finally:
        for temporary, _ in staged:
            temporary.unlink(missing_ok=True)
    return {
        "files_changed": [
            Path(target).relative_to(policy.workspace).as_posix() for target, _ in files
        ],
        "patch_bytes": len(diff.encode()),
    }
