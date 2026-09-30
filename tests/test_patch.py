from pathlib import Path

import pytest

from coding_agent.policy.engine import PolicyDenied, PolicyEngine
from coding_agent.tools.workspace import apply_unified_diff


def test_patch_requires_approval_and_applies_exact_change(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text("value = 1\n")
    diff = "--- a/sample.py\n+++ b/sample.py\n@@ -1 +1 @@\n-value = 1\n+value = 2\n"
    policy = PolicyEngine(tmp_path)
    with pytest.raises(PermissionError):
        apply_unified_diff(policy, diff)
    result = apply_unified_diff(policy, diff, approved=True)
    assert result["files_changed"] == ["sample.py"]
    assert source.read_text() == "value = 2\n"


def test_patch_rejects_secrets(tmp_path: Path) -> None:
    diff = "--- a/.env\n+++ b/.env\n@@ -1 +1 @@\n-A=1\n+B=2\n"
    with pytest.raises(PolicyDenied):
        PolicyEngine(tmp_path).check_patch(diff)
