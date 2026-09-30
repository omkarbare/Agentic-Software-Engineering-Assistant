"""In-process metric counters suitable for a Prometheus exporter."""

from __future__ import annotations

from collections import Counter
from threading import Lock


class Metrics:
    def __init__(self) -> None:
        self._counters: Counter[str] = Counter()
        self._lock = Lock()

    def increment(self, name: str, amount: int = 1, **labels: str) -> None:
        key = (
            name
            + "{"
            + ",".join(f"{label}={value}" for label, value in sorted(labels.items()))
            + "}"
        )
        with self._lock:
            self._counters[key] += amount

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self._counters)


metrics = Metrics()
