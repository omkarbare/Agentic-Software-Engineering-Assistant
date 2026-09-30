"""Validated data contracts shared by the API, graph, and tools."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class Budget(BaseModel):
    max_iterations: int = Field(default=12, ge=1, le=100)
    max_commands: int = Field(default=8, ge=0, le=100)
    max_wall_seconds: int = Field(default=600, ge=1, le=3600)
    max_patch_bytes: int = Field(default=100_000, ge=1, le=1_000_000)
    max_tokens: int = Field(default=40_000, ge=100, le=1_000_000)
    max_cost_usd: float = Field(default=2.0, ge=0, le=1000)


class RunRequest(BaseModel):
    task: str = Field(min_length=1, max_length=20_000)
    workspace: str = Field(min_length=1, max_length=4096)
    model: str | None = None
    mcp_profile: str | None = None
    budgets: Budget = Field(default_factory=Budget)
    dry_run: bool = False


class Approval(BaseModel):
    action: str
    arguments: dict[str, Any]
    risk: Literal["low", "medium", "high"]
    rationale: str
    preview: str


class AuditEvent(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    run_id: str
    event: str
    details: dict[str, Any] = Field(default_factory=dict)


def new_run_id() -> str:
    return str(uuid4())
