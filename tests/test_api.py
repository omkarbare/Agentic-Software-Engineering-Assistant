from pathlib import Path
from time import sleep

from fastapi.testclient import TestClient

from coding_agent.api import app as api


def client_for(tmp_path: Path, monkeypatch) -> TestClient:
    root = tmp_path / "workspaces"
    root.mkdir()
    monkeypatch.setenv("WORKSPACE_ROOT", str(root))
    monkeypatch.setattr(api, "store", api.RunStore(str(tmp_path / "runs.sqlite3")))
    monkeypatch.setattr(api, "graph", api.build_graph())
    return TestClient(api.app)


def test_health_and_workspace_boundary(tmp_path: Path, monkeypatch) -> None:
    client = client_for(tmp_path, monkeypatch)
    assert client.get("/healthz").json() == {"status": "ok"}
    outside = tmp_path / "outside"
    outside.mkdir()
    response = client.post("/runs", json={"workspace": str(outside), "task": "inspect files"})
    assert response.status_code == 400


def test_create_run_returns_persisted_safe_summary(tmp_path: Path, monkeypatch) -> None:
    client = client_for(tmp_path, monkeypatch)
    workspace = tmp_path / "workspaces" / "sample"
    workspace.mkdir()
    with client:
        response = client.post("/runs", json={"workspace": "sample", "task": "inspect files"})
        assert response.status_code == 202
        run_id = response.json()["run_id"]
        record = client.get(f"/runs/{run_id}").json()
        for _ in range(20):
            if record["state"] != "running":
                break
            sleep(0.01)
            record = client.get(f"/runs/{run_id}").json()
    assert record["state"] == "completed"
    assert "no edits or commands were run" in record["answer"]
    assert (
        client.get(f"/runs/{run_id}/events").headers["content-type"].startswith("text/event-stream")
    )


def test_unknown_run_is_not_found(tmp_path: Path, monkeypatch) -> None:
    client = client_for(tmp_path, monkeypatch)
    assert client.get("/runs/missing").status_code == 404
