"""FastAPI service for local coding-agent runs."""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import structlog
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from langgraph.types import Command

from coding_agent.core.models import RunRequest, new_run_id
from coding_agent.graph.workflow import build_graph
from coding_agent.mcp.registry import MCPRegistry
from coding_agent.observability.logging import configure_logging
from coding_agent.observability.metrics import metrics
from coding_agent.persistence.store import RunStore
from coding_agent.utils.redaction import redact

load_dotenv()
configure_logging()
logger = structlog.get_logger(__name__)


def _redacted(value: Any) -> Any:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, list):
        return [_redacted(item) for item in value]
    if isinstance(value, dict):
        return {key: _redacted(item) for key, item in value.items()}
    return value


app = FastAPI(title="LangGraph Coding Agent", version="0.1.0")
store = RunStore(os.getenv("DATABASE_PATH", "data/agent.sqlite3"))
checkpointer: Any
checkpointer_connection: Any
backend = os.getenv("CHECKPOINTER_BACKEND", "sqlite").lower()
if backend == "postgres":
    import psycopg
    from langgraph.checkpoint.postgres import PostgresSaver
    from psycopg.rows import dict_row

    checkpointer_connection = psycopg.connect(
        os.environ["DATABASE_URL"], row_factory=dict_row, autocommit=True
    )
    checkpointer = PostgresSaver(checkpointer_connection)
elif backend == "sqlite":
    from langgraph.checkpoint.sqlite import SqliteSaver

    checkpointer_connection = sqlite3.connect(
        os.getenv("CHECKPOINT_DATABASE_PATH", os.getenv("DATABASE_PATH", "data/agent.sqlite3")),
        check_same_thread=False,
    )
    checkpointer = SqliteSaver(checkpointer_connection)
else:
    raise RuntimeError("CHECKPOINTER_BACKEND must be sqlite or postgres")
checkpointer.setup()
mcp_path = Path(
    os.getenv(
        "MCP_CONFIG_PATH", str(Path(__file__).resolve().parents[3] / "config" / "mcp_servers.yaml")
    )
)
mcp_registry = MCPRegistry.from_yaml(mcp_path) if mcp_path.is_file() else None
graph = build_graph(
    checkpointer=checkpointer,
    executor_mode=os.getenv("EXECUTOR_MODE", "disabled"),
    mcp_registry=mcp_registry,
)
tasks: dict[str, asyncio.Task[None]] = {}


async def _run(run_id: str, thread_id: str, request: RunRequest) -> None:
    metrics.increment("runs_started")
    store.put_run(
        run_id,
        "running",
        {"thread_id": thread_id, "workspace": str(Path(request.workspace).resolve())},
    )
    try:
        initial = {
            "run_id": run_id,
            "thread_id": thread_id,
            "user_request": request.task,
            "workspace_path": request.workspace,
            "allowed_roots": [str(Path(request.workspace).resolve())],
            "budget": request.budgets.model_dump(),
        }
        result = await graph.ainvoke(initial, {"configurable": {"thread_id": thread_id}})
        pending = result.get("__interrupt__", [])
        if pending:
            payload = pending[0].value if hasattr(pending[0], "value") else str(pending[0])
            store.put_run(
                run_id,
                "approval_required",
                {
                    "thread_id": thread_id,
                    "approval": _redacted(payload),
                    "plan": result.get("plan", []),
                    "workspace": str(Path(request.workspace).resolve()),
                },
            )
            store.event(
                run_id, json.dumps({"type": "approval_requested", "approval": _redacted(payload)})
            )
            metrics.increment("approvals_requested")
            return
        summary: dict[str, Any] = _safe_summary(thread_id, result)
        state = result.get("status", "completed")
        if state == "running":
            state = "completed"
        if result.get("error") and state == "completed":
            state = "failed"
        store.put_run(run_id, state, summary)
        metrics.increment("runs_failed" if result.get("error") else "runs_completed")
        for event in result.get("events", []):
            store.event(run_id, str(event))
        store.event(run_id, json.dumps({"type": state}))
    except Exception as exc:
        logger.exception(
            "run_failed", run_id=run_id, thread_id=thread_id, error_type=type(exc).__name__
        )
        metrics.increment("runs_failed")
        store.put_run(
            run_id,
            "failed",
            {
                "thread_id": thread_id,
                "answer": "Run failed; inspect the service log using the run ID.",
            },
        )
        store.event(run_id, json.dumps({"type": "failed", "reason": type(exc).__name__}))


@app.post("/runs", status_code=202)
async def create_run(request: RunRequest) -> dict[str, str]:
    configured_root = Path(os.getenv("WORKSPACE_ROOT", "./workspaces")).resolve()
    configured_root.mkdir(parents=True, exist_ok=True)
    requested = Path(request.workspace)
    workspace = (requested if requested.is_absolute() else configured_root / requested).resolve()
    if not workspace.is_dir() or not workspace.is_relative_to(configured_root):
        raise HTTPException(
            status_code=400, detail="workspace must be an existing directory under WORKSPACE_ROOT"
        )
    request = request.model_copy(update={"workspace": str(workspace)})
    run_id = new_run_id()
    thread_id = run_id
    store.put_run(run_id, "queued", {"thread_id": thread_id})
    tasks[run_id] = asyncio.create_task(_run(run_id, thread_id, request))
    metrics.increment("runs_queued")
    return {"run_id": run_id, "thread_id": thread_id, "status": "queued"}


def _safe_summary(thread_id: str, result: dict[str, Any]) -> dict[str, Any]:
    changed = sorted(
        {
            name
            for row in result.get("tool_results", [])
            if isinstance(row.get("result"), dict)
            for name in row["result"].get("files_changed", [])
        }
    )
    return {
        "thread_id": thread_id,
        "answer": redact(str(result.get("final_answer", ""))),
        "plan": result.get("plan", []),
        "status": result.get("status", "completed"),
        "events": result.get("events", []),
        "changed_files": changed,
        "commands": [
            {
                "argv": [redact(str(arg)) for arg in row.get("argv", [])],
                "exit_code": row.get("exit_code"),
                "timed_out": row.get("timed_out", False),
                "duration_ms": row.get("duration_ms"),
            }
            for row in result.get("command_history", [])
        ],
    }


async def _resume(run_id: str, approved: bool) -> dict[str, str]:
    record = store.get_run(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="run not found")
    if record.get("state") != "approval_required":
        raise HTTPException(status_code=409, detail="run has no pending approval")
    thread_id = record["thread_id"]
    result = await graph.ainvoke(
        Command(resume={"approved": approved}), {"configurable": {"thread_id": thread_id}}
    )
    pending = result.get("__interrupt__", [])
    if pending:
        payload = pending[0].value if hasattr(pending[0], "value") else str(pending[0])
        store.put_run(
            run_id,
            "approval_required",
            {
                "thread_id": thread_id,
                "approval": _redacted(payload),
                "workspace": record.get("workspace", ""),
            },
        )
        store.event(
            run_id, json.dumps({"type": "approval_requested", "approval": _redacted(payload)})
        )
        metrics.increment("approvals_requested")
        return {"run_id": run_id, "status": "approval_required"}
    state = result.get("status", "completed")
    store.put_run(
        run_id, "completed" if state == "running" else state, _safe_summary(thread_id, result)
    )
    store.event(
        run_id, json.dumps({"type": "approval_granted" if approved else "approval_rejected"})
    )
    for event in result.get("events", []):
        store.event(run_id, json.dumps(event, default=str))
    return {"run_id": run_id, "status": "completed" if state == "running" else state}


@app.get("/runs/{run_id}")
async def get_run(run_id: str) -> dict[str, Any]:
    record = store.get_run(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="run not found")
    return record


@app.get("/runs/{run_id}/events")
async def run_events(run_id: str) -> StreamingResponse:
    if store.get_run(run_id) is None:
        raise HTTPException(status_code=404, detail="run not found")

    async def stream() -> AsyncIterator[str]:
        previous = 0
        while True:
            items = store.events(run_id)
            for item in items[previous:]:
                yield f"data: {item}\n\n"
            previous = len(items)
            record = store.get_run(run_id)
            if record and record["state"] in {
                "completed",
                "failed",
                "rejected",
                "budget_exhausted",
            }:
                break
            await asyncio.sleep(0.5)

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.post("/runs/{run_id}/approve")
async def approve_run(run_id: str) -> dict[str, str]:
    result = await _resume(run_id, True)
    metrics.increment("approvals_granted")
    return result


@app.post("/runs/{run_id}/reject")
async def reject_run(run_id: str) -> dict[str, str]:
    result = await _resume(run_id, False)
    metrics.increment("approvals_rejected")
    return result


@app.get("/healthz")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics")
async def get_metrics() -> dict[str, int]:
    return metrics.snapshot()


@app.middleware("http")
async def request_context(request: Request, call_next: Any) -> Any:
    request_id = request.headers.get("x-request-id", str(uuid4()))[:128]
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id)
    response = await call_next(request)
    response.headers["x-request-id"] = request_id
    return response
