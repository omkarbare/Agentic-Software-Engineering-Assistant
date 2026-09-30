# LangGraph Coding Assistant

This is a local service that lets you ask an AI model to inspect and help change a codebase. It can read files, search code, propose a patch, and request approved checks. Before it changes a file, runs a command, or calls an external MCP tool, it pauses and asks you to approve that specific action.

The project includes an HTTP API, a terminal command, workspace and command safety rules, saved run/checkpoint state, optional Docker command execution, MCP integration, and automated tests. Without a configured model key, it can inspect a workspace and report that model-driven work is unavailable; it will not invent results.

## Requirements

- Python 3.12 or 3.13
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- An OpenAI API key for model-powered runs
- Docker Desktop or Docker Engine only if you want to build and use the command sandbox

## Install and configure

Run these commands from the repository root:

```sh
uv sync --locked --extra dev --extra mcp
test -f .env || cp .env.example .env
```

Edit `.env` and set `OPENAI_API_KEY`. `MODEL_NAME` defaults to `gpt-4o-mini`; `OPENAI_BASE_URL` is optional for an OpenAI-compatible endpoint. Keep `.env` out of workspaces given to the service.

Create a workspace directory and put a codebase in it. The API only accepts existing directories below `WORKSPACE_ROOT`, which defaults to `./workspaces`:

```sh
mkdir -p workspaces/my-repository
# Copy or clone the project you want to work on into that directory.
```

## Start the HTTP API

```sh
uv run uvicorn coding_agent.api.app:app --app-dir src --reload
```

The service listens on `http://127.0.0.1:8000`. Open [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) for interactive API documentation. Keep this terminal open while using the API.

In a second terminal, submit a task. The workspace value is a directory name under `workspaces/`:

```sh
curl -X POST http://127.0.0.1:8000/runs \
  -H 'content-type: application/json' \
  -d '{"workspace":"my-repository","task":"Explain the project structure and identify its test command."}'
```

The response contains a `run_id`. Use it to check progress and retrieve the result:

```sh
curl http://127.0.0.1:8000/runs/RUN_ID
```

To follow run events as they arrive:

```sh
curl -N http://127.0.0.1:8000/runs/RUN_ID/events
```

If the assistant proposes a patch, command, or MCP call, the run pauses in `approval_required`. Review the approval details returned by the status endpoint, then approve or reject:

```sh
curl -X POST http://127.0.0.1:8000/runs/RUN_ID/approve
curl -X POST http://127.0.0.1:8000/runs/RUN_ID/reject
```

The health endpoint is `GET /healthz`; basic counters are available at `GET /metrics`.

## Use the terminal command

The CLI can start a run against an existing directory. Unlike the HTTP API, the CLI accepts a workspace path directly:

```sh
uv run agent run --workspace ./workspaces/my-repository --task "Summarize the source tree"
```

The command prints a run ID and its status. Use that ID to inspect the saved run or respond to a pending approval:

```sh
uv run agent status --run-id RUN_ID
uv run agent approve --run-id RUN_ID
uv run agent reject --run-id RUN_ID
```

The CLI and API use the same local run database by default (`data/agent.sqlite3`).

## Run the checks and evaluations

Run the complete automated test suite, including deterministic policy and safety cases:

```sh
uv run pytest
```

Run just the evaluation cases:

```sh
uv run pytest evals/ -v
uv run agent eval
```

Run formatting, lint, and type checks:

```sh
uv run ruff format src tests evals
uv run ruff check src tests evals
uv run mypy src
```

The live, model-judged evaluation is skipped by default. It needs `OPENAI_API_KEY` and explicitly enabled live evals:

```sh
RUN_LIVE_EVALS=true uv run pytest evals/test_agent_e2e.py -v
```

That test sends model requests and evaluates task completion, tool use, plan adherence, and whether the final report accurately describes what ran.

## Run with Docker

To run the API in a container, with workspaces mounted from the local `workspaces/` directory:

```sh
docker compose up --build
```

The Compose API listens on `http://127.0.0.1:8000`. By default, command execution is disabled. To build the separate restricted runner image:

```sh
docker build -f Dockerfile.sandbox -t langgraph-agent-sandbox:latest .
```

The runner requires a working Docker daemon accessible to the API process. For a local API process, set `EXECUTOR_MODE=docker` and `SANDBOX_IMAGE=langgraph-agent-sandbox:latest` in `.env`, build the image above, and then start the API. The Compose setup does not mount the host Docker socket, so its command execution stays disabled. Review Docker daemon access before enabling command execution.

## MCP tools

MCP integrations are configured in `config/mcp_servers.yaml` and disabled by default. The included demo server can be started manually with:

```sh
uv run python -m mcp_servers.demo_server
```

To enable an MCP server, configure it in that YAML file, make sure the MCP extra is installed, and restart the API. MCP calls still require individual approval. Remote MCP servers must use HTTPS and an explicitly allowed host.

## How safety works

- The API limits each run to a workspace below `WORKSPACE_ROOT`.
- File reads and patches are checked against workspace boundaries and blocked sensitive paths.
- Proposed file changes, commands, and MCP calls require approval.
- Commands are passed as argument lists rather than through a shell, are allowlisted, and have time and output limits.
- The default executor is disabled. Docker execution disables network access inside the runner and limits its privileges and resources.
- The workflow has iteration, command, token, cost, patch-size, and time budgets.

