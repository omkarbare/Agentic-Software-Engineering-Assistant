FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN useradd --create-home --uid 10001 agent
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY config ./config
COPY mcp_servers ./mcp_servers
RUN pip install --no-cache-dir .
USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "coding_agent.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--app-dir", "src"]
