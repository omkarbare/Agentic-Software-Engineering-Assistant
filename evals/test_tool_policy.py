from pathlib import Path

import pytest

from coding_agent.policy.engine import PolicyDenied, PolicyEngine


def test_unsafe_command_is_denied(tmp_path: Path) -> None:
    with pytest.raises(PolicyDenied):
        PolicyEngine(tmp_path).check_command(["rm", "-rf", "."])
