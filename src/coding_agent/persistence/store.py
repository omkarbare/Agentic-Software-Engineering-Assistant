"""SQLite metadata store for run summaries and policy audit records."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class RunStore:
    def __init__(self, database: str):
        self.path = Path(database)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY, state TEXT NOT NULL, "
                "summary TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, run_id TEXT NOT NULL, "
                "event TEXT NOT NULL)"
            )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    def put_run(self, run_id: str, state: str, summary: dict[str, Any]) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO runs VALUES (?, ?, ?)", (run_id, state, json.dumps(summary))
            )

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT run_id, state, summary FROM runs WHERE run_id=?", (run_id,)
            ).fetchone()
        return (
            {"run_id": row["run_id"], "state": row["state"], **json.loads(row["summary"])}
            if row
            else None
        )

    def event(self, run_id: str, event: str) -> None:
        with self._connect() as db:
            db.execute("INSERT INTO events (run_id, event) VALUES (?, ?)", (run_id, event))

    def events(self, run_id: str) -> list[str]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT event FROM events WHERE run_id=? ORDER BY id", (run_id,)
            ).fetchall()
        return [row["event"] for row in rows]
