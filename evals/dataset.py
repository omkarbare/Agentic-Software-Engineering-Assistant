"""Validated golden-task records used by offline agent evaluations."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator


class GoldenTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    task: str = Field(min_length=1)
    fixture_workspace: str = Field(min_length=1)
    expected_files_changed: list[str] = []
    expected_tests: list[str] = []
    expected_tools: list[str] = []
    forbidden_tools: list[str] = []
    expected_outcome: str = Field(min_length=1)
    approval_expectation: str = Field(min_length=1)
    evaluation_tags: list[str] = []

    @field_validator("fixture_workspace")
    @classmethod
    def fixture_is_relative(cls, value: str) -> str:
        path = Path(value)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("fixture_workspace must be a relative fixture name")
        return value


def load_dataset(path: Path) -> list[GoldenTask]:
    """Load and validate the JSONL dataset, rejecting duplicate task IDs."""
    rows = [GoldenTask.model_validate_json(line) for line in path.read_text().splitlines() if line]
    ids = [row.id for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("golden task IDs must be unique")
    return rows


def write_dataset(path: Path, rows: list[GoldenTask]) -> None:
    """Write validated tasks as stable UTF-8 JSONL."""
    path.write_text(
        "".join(json.dumps(row.model_dump(), ensure_ascii=False) + "\n" for row in rows)
    )
