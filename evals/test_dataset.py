from pathlib import Path

import pytest

from evals.dataset import GoldenTask, load_dataset


def test_golden_dataset_is_valid_and_unique() -> None:
    rows = load_dataset(Path(__file__).parent / "goldens" / "coding_agent_tasks.jsonl")
    assert len(rows) >= 3
    assert len({row.id for row in rows}) == len(rows)


def test_golden_fixture_cannot_escape_fixture_root() -> None:
    with pytest.raises(ValueError, match="relative fixture name"):
        GoldenTask(
            id="escape",
            task="inspect",
            fixture_workspace="../outside",
            expected_outcome="denied",
            approval_expectation="none",
        )
