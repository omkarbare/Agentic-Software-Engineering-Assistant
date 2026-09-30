"""Command-line entry point."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path
from typing import Annotated

import typer

from coding_agent.api.app import _resume, graph, store
from coding_agent.core.models import Budget, new_run_id

app = typer.Typer(no_args_is_help=True)


@app.command()
def run(
    workspace: Annotated[Path, typer.Option(...)],
    task: Annotated[str, typer.Option(...)],
) -> None:
    workspace = workspace.resolve()
    if not workspace.is_dir():
        raise typer.BadParameter("workspace must be an existing directory")
    run_id = new_run_id()
    store.put_run(run_id, "running", {"thread_id": run_id, "workspace": str(workspace)})
    result = asyncio.run(
        graph.ainvoke(
            {
                "run_id": run_id,
                "thread_id": run_id,
                "workspace_path": str(workspace),
                "user_request": task,
                "budget": Budget().model_dump(),
            },
            {"configurable": {"thread_id": run_id}},
        )
    )
    pending = result.get("__interrupt__", [])
    if pending:
        approval = pending[0].value if hasattr(pending[0], "value") else str(pending[0])
        store.put_run(
            run_id,
            "approval_required",
            {"thread_id": run_id, "workspace": str(workspace), "approval": approval},
        )
        typer.echo(
            json.dumps(
                {"run_id": run_id, "status": "approval_required", "approval": approval}, indent=2
            )
        )
    else:
        store.put_run(
            run_id,
            result.get("status", "completed"),
            {
                "thread_id": run_id,
                "answer": result.get("final_answer", ""),
                "plan": result.get("plan", []),
            },
        )
        typer.echo(
            json.dumps(
                {
                    "run_id": run_id,
                    "status": result.get("status", "completed"),
                    "answer": result.get("final_answer", ""),
                },
                indent=2,
            )
        )


@app.command()
def status(run_id: str = typer.Option(..., "--run-id")) -> None:
    try:
        result = store.get_run(run_id)
        if result is None:
            raise KeyError(run_id)
        typer.echo(json.dumps(result, indent=2))
    except Exception as exc:
        raise typer.Exit(code=1) from exc


@app.command()
def approve(run_id: str = typer.Option(..., "--run-id")) -> None:
    result = asyncio.run(_resume(run_id, True))
    typer.echo(json.dumps(result))


@app.command()
def reject(run_id: str = typer.Option(..., "--run-id")) -> None:
    result = asyncio.run(_resume(run_id, False))
    typer.echo(json.dumps(result))


@app.command()
def eval() -> None:
    result = subprocess.run([sys.executable, "-m", "pytest", "evals/"], check=False)
    raise typer.Exit(code=result.returncode)
