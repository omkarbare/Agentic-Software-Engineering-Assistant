"""Redact common credential formats before content enters model-visible output."""

from __future__ import annotations

import re

PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|token|password|secret)(\s*[:=]\s*)([^\s,;\"'}]+)"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
)


def redact(value: str) -> str:
    for pattern in PATTERNS:
        value = pattern.sub(
            lambda match: (
                f"{match.group(1)}{match.group(2)}[REDACTED]"
                if match.lastindex and match.lastindex >= 3
                else "[REDACTED]"
            ),
            value,
        )
    return value
