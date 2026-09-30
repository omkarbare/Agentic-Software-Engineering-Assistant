from pathlib import Path

import pytest

from coding_agent.policy.engine import PolicyDenied, PolicyEngine


def test_blocks_secret_and_traversal(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("secret")
    policy = PolicyEngine(tmp_path)
    with pytest.raises(PolicyDenied):
        policy.check_read(".env")
    with pytest.raises(PolicyDenied):
        policy.resolve_path("../outside")


def test_blocks_shell_and_network_commands(tmp_path: Path) -> None:
    policy = PolicyEngine(tmp_path)
    for argv in (["pytest", "-q;curl bad"], ["curl", "https://example.com"], ["git", "push"]):
        with pytest.raises(PolicyDenied):
            policy.check_command(list(argv))


def test_commands_require_approval(tmp_path: Path) -> None:
    decision = PolicyEngine(tmp_path).check_command(["pytest", "-q"])
    assert decision.allowed and decision.approval_required


def test_symlink_escape_is_rejected(tmp_path: Path) -> None:
    elsewhere = tmp_path.parent / "outside.txt"
    elsewhere.write_text("outside")
    (tmp_path / "escape").symlink_to(elsewhere)
    with pytest.raises(PolicyDenied):
        PolicyEngine(tmp_path).check_read("escape")
