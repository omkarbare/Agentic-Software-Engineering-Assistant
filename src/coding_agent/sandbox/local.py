"""Development-only bounded subprocess adapter; it does not provide isolation."""

from __future__ import annotations

import os
import subprocess
import threading
import time
from typing import Any

from coding_agent.policy.engine import PolicyEngine
from coding_agent.utils.redaction import redact


class LocalExecutor:
    def __init__(self, policy: PolicyEngine, enabled: bool = False):
        self.policy = policy
        self.enabled = enabled

    def run(self, argv: list[str], cwd: str = ".", timeout_seconds: int = 60) -> dict[str, object]:
        decision = self.policy.check_command(argv)
        if not decision.allowed:
            raise PermissionError(decision.reason)
        if not self.enabled:
            raise RuntimeError("local executor is disabled; it is unsafe outside a container")
        workdir = self.policy.resolve_path(cwd)
        timeout = min(max(timeout_seconds, 1), 300)
        output_limit = 20_000
        env = {
            key: os.environ[key]
            for key in ("PATH", "LANG", "LC_ALL", "PYTHONPATH")
            if key in os.environ
        }
        process = subprocess.Popen(
            argv, cwd=workdir, env=env, shell=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        captured: dict[str, bytearray] = {"stdout": bytearray(), "stderr": bytearray()}
        started = time.monotonic()

        def drain(name: str, stream: Any) -> None:
            while chunk := stream.read(8192):
                remaining = output_limit - len(captured[name])
                if remaining > 0:
                    captured[name].extend(chunk[:remaining])

        readers = [
            threading.Thread(target=drain, args=(name, pipe), daemon=True)
            for name, pipe in (("stdout", process.stdout), ("stderr", process.stderr))
            if pipe is not None
        ]
        for reader in readers:
            reader.start()
        try:
            try:
                status = process.wait(timeout=timeout)
                timed_out = False
            except subprocess.TimeoutExpired:
                process.kill()
                status = None
                timed_out = True
            for reader in readers:
                reader.join(timeout=2)
            return {
                "exit_code": status,
                "stdout": redact(captured["stdout"].decode("utf-8", errors="replace")),
                "stderr": redact(captured["stderr"].decode("utf-8", errors="replace")),
                "timed_out": timed_out,
                "duration_ms": round((time.monotonic() - started) * 1000),
            }
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
