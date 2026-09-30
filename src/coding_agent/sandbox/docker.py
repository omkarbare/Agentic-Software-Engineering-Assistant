"""Container-backed command execution with no network and a read-only root filesystem."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

from requests.exceptions import Timeout as RequestsTimeout

from coding_agent.policy.engine import PolicyEngine
from coding_agent.utils.redaction import redact


class DockerExecutor:
    def __init__(
        self,
        policy: PolicyEngine,
        image: str = "python:3.12-slim",
        memory_limit: str = "1g",
        cpu_count: int = 1,
    ):
        self.policy = policy
        self.image = image
        self.memory_limit = memory_limit
        self.cpu_count = cpu_count

    def run(self, argv: list[str], cwd: str = ".", timeout_seconds: int = 60) -> dict[str, Any]:
        self.policy.check_command(argv)
        workdir = self.policy.resolve_path(cwd)
        try:
            import docker
        except ImportError as exc:
            raise RuntimeError(
                "Install the docker optional dependency to run container commands"
            ) from exc
        client = docker.from_env()
        with tempfile.TemporaryDirectory(prefix="agent-mask-") as mask_root:
            mask = self._secret_overlays(mask_root)
            volumes: dict[str, Any] = {
                str(self.policy.workspace): {"bind": "/workspace", "mode": "rw"}
            }
            volumes.update(mask)
            container = client.containers.run(
                self.image,
                command=argv,
                detach=True,
                network_disabled=True,
                read_only=True,
                user=f"{os.getuid()}:{os.getgid()}",
                cap_drop=["ALL"],
                security_opt=["no-new-privileges:true"],
                mem_limit=self.memory_limit,
                nano_cpus=self.cpu_count * 1_000_000_000,
                pids_limit=128,
                tmpfs={"/tmp": "rw,noexec,nosuid,size=64m"},
                environment={"GIT_OPTIONAL_LOCKS": "0"},
                working_dir=f"/workspace/{workdir.relative_to(self.policy.workspace).as_posix()}".rstrip(
                    "/"
                ),
                volumes=volumes,
                auto_remove=False,
            )
            try:
                try:
                    status = container.wait(timeout=min(max(timeout_seconds, 1), 300))["StatusCode"]
                    timed_out = False
                except (TimeoutError, RequestsTimeout):
                    container.kill()
                    status = None
                    timed_out = True
                stdout = redact(
                    container.logs(stdout=True, stderr=False, tail=1000).decode(
                        "utf-8", errors="replace"
                    )[-20_000:]
                )
                stderr = redact(
                    container.logs(stdout=False, stderr=True, tail=1000).decode(
                        "utf-8", errors="replace"
                    )[-20_000:]
                )
                return {
                    "exit_code": status,
                    "stdout": stdout,
                    "stderr": stderr,
                    "timed_out": timed_out,
                }
            finally:
                container.remove(force=True)
                client.close()

    def _secret_overlays(self, root: str) -> dict[str, Any]:
        overlays: dict[str, Any] = {}
        for current, dirs, files in os.walk(self.policy.workspace, followlinks=False):
            for name in list(dirs) + files:
                relative = (Path(current) / name).relative_to(self.policy.workspace)
                low_name = name.lower()
                if (
                    low_name != ".git"
                    and low_name not in {".ssh", ".aws", ".azure", ".config"}
                    and not (low_name == ".env" or low_name.startswith(".env."))
                ):
                    continue
                source = Path(current) / name
                placeholder = Path(root) / str(len(overlays))
                if source.is_dir() and not source.is_symlink():
                    placeholder.mkdir()
                    dirs.remove(name)
                else:
                    placeholder.touch()
                mount_mode = "ro"
                overlays[str(placeholder)] = {
                    "bind": f"/workspace/{relative.as_posix()}",
                    "mode": mount_mode,
                }
        return overlays
