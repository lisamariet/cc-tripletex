from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from app.models import CallTracker

logger = logging.getLogger(__name__)


class TripletexClient:
    """Thin async wrapper around the Tripletex REST API with call tracking."""

    def __init__(self, base_url: str, session_token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.auth = httpx.BasicAuth(username="0", password=session_token)
        self.tracker = CallTracker()
        self._client = httpx.AsyncClient(timeout=30.0, auth=self.auth)

    async def close(self) -> None:
        await self._client.aclose()

    # -- generic HTTP verbs --------------------------------------------------

    async def get(self, path: str, params: dict[str, Any] | None = None) -> httpx.Response:
        return await self._request("GET", path, params=params)

    async def post(self, path: str, payload: dict[str, Any] | None = None) -> httpx.Response:
        return await self._request("POST", path, json_body=payload)

    async def put(self, path: str, payload: dict[str, Any] | None = None, params: dict[str, Any] | None = None) -> httpx.Response:
        return await self._request("PUT", path, json_body=payload, params=params)

    async def delete(self, path: str) -> httpx.Response:
        return await self._request("DELETE", path)

    # -- internal -------------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        url = f"{self.base_url}{path}"
        logger.info(f"Tripletex {method} {url}")
        if json_body:
            logger.info(f"Payload: {json_body}")

        t0 = time.monotonic()
        try:
            resp = await self._client.request(method, url, json=json_body, params=params)
        except Exception as exc:
            duration = (time.monotonic() - t0) * 1000
            self.tracker.record(method, path, 0, duration, error=str(exc))
            raise

        duration = (time.monotonic() - t0) * 1000
        error_body = None
        if 400 <= resp.status_code < 500:
            error_body = resp.text[:500]
        self.tracker.record(method, path, resp.status_code, duration, error=error_body)
        logger.info(f"Response {resp.status_code} ({duration:.0f}ms): {resp.text[:500]}")
        return resp
