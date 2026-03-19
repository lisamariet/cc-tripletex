from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ParsedTask:
    task_type: str
    fields: dict[str, Any]
    confidence: float = 1.0
    reasoning: str = ""


@dataclass
class APICallRecord:
    method: str
    path: str
    status: int
    duration_ms: float
    error: str | None = None


@dataclass
class CallTracker:
    api_calls: list[APICallRecord] = field(default_factory=list)

    @property
    def total_calls(self) -> int:
        return len(self.api_calls)

    @property
    def error_count_4xx(self) -> int:
        return sum(1 for c in self.api_calls if 400 <= c.status < 500)

    def record(self, method: str, path: str, status: int, duration_ms: float, error: str | None = None) -> None:
        self.api_calls.append(APICallRecord(method=method, path=path, status=status, duration_ms=duration_ms, error=error))

    def to_dict(self) -> list[dict]:
        return [
            {"method": c.method, "path": c.path, "status": c.status, "duration_ms": round(c.duration_ms, 1), "error": c.error}
            for c in self.api_calls
        ]
