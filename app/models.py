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
    # Debug fields (populated when DEBUG_MODE is on)
    url: str | None = None
    query_params: dict | None = None
    request_body: dict | None = None
    response_body: str | None = None


@dataclass
class CallTracker:
    api_calls: list[APICallRecord] = field(default_factory=list)
    debug: bool = field(default=False)

    @property
    def total_calls(self) -> int:
        return len(self.api_calls)

    @property
    def error_count_4xx(self) -> int:
        return sum(1 for c in self.api_calls if 400 <= c.status < 500)

    def record(
        self,
        method: str,
        path: str,
        status: int,
        duration_ms: float,
        error: str | None = None,
        url: str | None = None,
        query_params: dict | None = None,
        request_body: dict | None = None,
        response_body: str | None = None,
    ) -> None:
        self.api_calls.append(APICallRecord(
            method=method, path=path, status=status, duration_ms=duration_ms,
            error=error,
            url=url if self.debug else None,
            query_params=query_params if self.debug else None,
            request_body=request_body if self.debug else None,
            response_body=response_body if self.debug else None,
        ))

    def to_dict(self) -> list[dict]:
        result = []
        for c in self.api_calls:
            d: dict[str, Any] = {
                "method": c.method, "path": c.path, "status": c.status,
                "duration_ms": round(c.duration_ms, 1), "error": c.error,
            }
            if c.url:
                d["url"] = c.url
            if c.query_params:
                d["query_params"] = c.query_params
            if c.request_body is not None:
                d["request_body"] = c.request_body
            if c.response_body is not None:
                d["response_body"] = c.response_body[:2000]
            result.append(d)
        return result
