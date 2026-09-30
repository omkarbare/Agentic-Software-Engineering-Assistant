"""Run deterministic checks; live judge metrics are deliberately opt-in."""

import os
import subprocess
import sys

if __name__ == "__main__":
    if os.getenv("RUN_LIVE_EVALS", "false").lower() == "true":
        print("Live DeepEval judges are not wired into this baseline workflow.")
    raise SystemExit(subprocess.call([sys.executable, "-m", "pytest", "evals", "tests"]))
