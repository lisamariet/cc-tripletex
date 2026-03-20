from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from app.api_validator import validate_payload
from app.models import CallTracker

# Graceful imports — RAG and error patterns are optional enhancements
try:
    from app.error_patterns import check_payload as _ep_check_payload
    from app.error_patterns import record_error as _ep_record_error
    _HAS_ERROR_PATTERNS = True
except Exception:  # pragma: no cover
    _HAS_ERROR_PATTERNS = False

try:
    from app.api_rag import suggest_fix as _rag_suggest_fix
    _HAS_RAG = True
except Exception:  # pragma: no cover
    _HAS_RAG = False

logger = logging.getLogger(__name__)


class TripletexClient:
    """Thin async wrapper around the Tripletex REST API with call tracking."""

    def __init__(self, base_url: str, session_token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.auth = httpx.BasicAuth(username="0", password=session_token)
        self.tracker = CallTracker()
        self._client = httpx.AsyncClient(timeout=30.0, auth=self.auth)
        self._cache: dict[str, httpx.Response] = {}

    async def get_cached(self, path: str, params: dict[str, Any] | None = None) -> httpx.Response:
        """GET with caching — use for reference-data lookups (vatType, paymentType, costCategory, department)."""
        cache_key = f"{path}?{sorted(params.items()) if params else ''}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        resp = await self.get(path, params=params)
        if resp.status_code == 200:
            self._cache[cache_key] = resp
        return resp

    async def close(self) -> None:
        await self._client.aclose()

    # -- generic HTTP verbs --------------------------------------------------

    async def get(self, path: str, params: dict[str, Any] | None = None) -> httpx.Response:
        return await self._request("GET", path, params=params)

    async def post(self, path: str, payload: dict[str, Any] | None = None, params: dict[str, Any] | None = None) -> httpx.Response:
        self._warn_invalid_fields("POST", path, payload)
        self._check_error_patterns("POST", path, payload)
        return await self._request("POST", path, json_body=payload, params=params)

    async def put(self, path: str, payload: dict[str, Any] | None = None, params: dict[str, Any] | None = None) -> httpx.Response:
        self._warn_invalid_fields("PUT", path, payload)
        self._check_error_patterns("PUT", path, payload)
        return await self._request("PUT", path, json_body=payload, params=params)

    async def delete(self, path: str) -> httpx.Response:
        return await self._request("DELETE", path)

    # -- error pattern pre-flight ---------------------------------------------

    @staticmethod
    def _check_error_patterns(method: str, path: str, payload: dict[str, Any] | None) -> None:
        """Run pre-flight check against known error patterns (non-blocking)."""
        if not _HAS_ERROR_PATTERNS or not payload:
            return
        try:
            warnings = _ep_check_payload(path, method, payload)
            for w in warnings:
                logger.warning(f"[Error Patterns] {w}")
        except Exception as exc:
            logger.debug(f"Error pattern check failed (non-fatal): {exc}")

    # -- payload validation ---------------------------------------------------

    @staticmethod
    def _warn_invalid_fields(method: str, path: str, payload: dict[str, Any] | None) -> None:
        """Validate payload fields against OpenAPI spec and log warnings."""
        if not payload:
            return
        try:
            errors = validate_payload(method, path, payload)
            for err in errors:
                logger.warning(f"[API Validator] {method} {path}: {err}")
        except Exception as exc:
            # Never let validation break the actual request
            logger.debug(f"Payload validation error (non-fatal): {exc}")

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

        # --- Error pattern recording (4xx) ---
        if error_body and _HAS_ERROR_PATTERNS:
            try:
                _ep_record_error(path, method, resp.status_code, error_body, json_body)
            except Exception as exc:
                logger.debug(f"Error pattern recording failed (non-fatal): {exc}")

        # --- RAG suggest_fix logging (422 on POST/PUT) ---
        if resp.status_code == 422 and method in ("POST", "PUT") and _HAS_RAG:
            try:
                import json as _json
                try:
                    err_parsed = _json.loads(resp.text[:2000])
                except (ValueError, TypeError):
                    err_parsed = resp.text[:500]
                suggestion = _rag_suggest_fix(path, method, err_parsed)
                if suggestion:
                    logger.info(
                        f"[RAG] Fix suggestion for {method} {path}: "
                        f"{suggestion.get('suggestion', '')}"
                    )
            except Exception as exc:
                logger.debug(f"RAG suggest_fix failed (non-fatal): {exc}")

        return resp
