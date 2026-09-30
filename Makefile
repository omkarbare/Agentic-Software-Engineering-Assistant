.PHONY: install lint format typecheck test eval run docker-up sandbox-image
install:
	uv sync --locked --extra dev --extra mcp
lint:
	uv run ruff check src tests evals
format:
	uv run ruff format src tests evals
typecheck:
	uv run mypy src
test:
	uv run pytest
eval:
	uv run pytest evals/
run:
	uv run uvicorn coding_agent.api.app:app --app-dir src --reload
docker-up:
	docker compose up --build
sandbox-image:
	docker build -f Dockerfile.sandbox -t langgraph-agent-sandbox:latest .
