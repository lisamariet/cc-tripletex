from __future__ import annotations

import copy
import json as _json
import logging
import os
import re
import time
from typing import Any

import httpx

from app.api_validator import validate_payload
from app.models import CallTracker

# Graceful imports — RAG and error patterns are optional enhancements
try:
    from app.error_patterns import check_payload as _ep_check_payload
    from app.error_patterns import get_known_errors as _ep_get_known_errors
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

# ---------------------------------------------------------------------------
# Default values for known required fields (used by _apply_known_fixes)
# ---------------------------------------------------------------------------
_REQUIRED_FIELD_DEFAULTS: dict[str, Any] = {
    "name": "Default",
    "invoiceDate": "2026-01-01",
    "orderDate": "2026-01-01",
    "deliveryDate": "2026-01-01",
    "date": "2026-01-01",
    "description": "Auto-generated",
    "currency": {"id": 1},
}


class TripletexClient:
    """Thin async wrapper around the Tripletex REST API with call tracking."""

    def __init__(self, base_url: str, session_token: str, debug: bool = False) -> None:
        self.base_url = base_url.rstrip("/")
        self.auth = httpx.BasicAuth(username="0", password=session_token)
        self.debug = debug or os.getenv("TRIPLETEX_DEBUG", "").lower() in ("1", "true", "yes")
        self.tracker = CallTracker(debug=self.debug)
        self._client = httpx.AsyncClient(timeout=30.0, auth=self.auth)
        self._cache: dict[str, httpx.Response] = {}
        if self.debug:
            logger.info("TripletexClient DEBUG MODE enabled — logging full request/response bodies")

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
        payload = self._preflight_correct("POST", path, payload)
        return await self._request("POST", path, json_body=payload, params=params)

    async def put(self, path: str, payload: dict[str, Any] | None = None, params: dict[str, Any] | None = None) -> httpx.Response:
        self._warn_invalid_fields("PUT", path, payload)
        payload = self._preflight_correct("PUT", path, payload)
        return await self._request("PUT", path, json_body=payload, params=params)

    async def delete(self, path: str) -> httpx.Response:
        return await self._request("DELETE", path)

    async def post_multipart(
        self,
        path: str,
        file_bytes: bytes,
        filename: str,
        mime_type: str = "text/csv",
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """POST a file as multipart/form-data (e.g. POST /bank/statement/import)."""
        url = f"{self.base_url}{path}"
        logger.info(f"Tripletex POST (multipart) {url} file={filename}")
        if params:
            logger.info(f"Params: {params}")
        t0 = time.monotonic()
        try:
            resp = await self._client.post(
                url,
                files={"file": (filename, file_bytes, mime_type)},
                params=params,
            )
        except Exception as exc:
            duration = (time.monotonic() - t0) * 1000
            self.tracker.record("POST", path, 0, duration, error=str(exc), url=url, query_params=params)
            raise

        duration = (time.monotonic() - t0) * 1000
        error_body = resp.text[:500] if 400 <= resp.status_code < 500 else None
        self.tracker.record(
            "POST", path, resp.status_code, duration, error=error_body,
            url=url, query_params=params,
            response_body=resp.text[:2000] if self.debug else None,
        )
        logger.info(f"Response {resp.status_code} ({duration:.0f}ms): {resp.text[:500]}")
        return resp

    # -- smart retry methods -------------------------------------------------

    async def post_with_retry(
        self,
        path: str,
        payload: dict[str, Any],
        params: dict[str, Any] | None = None,
        max_retries: int = 1,
    ) -> httpx.Response:
        """POST with smart retry on 422 — applies rule-based fixes and retries once.

        NEVER retries 403 (token/permission errors).
        """
        resp = await self.post(path, payload, params=params)

        if resp.status_code != 422 or max_retries < 1:
            return resp

        # Parse validation messages and attempt fix
        try:
            corrected = await self._apply_known_fixes(
                "POST", path, payload, resp,
            )
            if corrected is not None:
                logger.info(f"[SmartRetry] Retrying POST {path} with corrected payload")
                resp = await self.post(path, corrected, params=params)
        except Exception as exc:
            logger.debug(f"[SmartRetry] Fix attempt failed (non-fatal): {exc}")

        return resp

    async def put_with_retry(
        self,
        path: str,
        payload: dict[str, Any],
        params: dict[str, Any] | None = None,
        max_retries: int = 1,
    ) -> httpx.Response:
        """PUT with smart retry on 422 — applies rule-based fixes and retries once.

        NEVER retries 403 (token/permission errors).
        """
        resp = await self.put(path, payload, params=params)

        if resp.status_code != 422 or max_retries < 1:
            return resp

        # Parse validation messages and attempt fix
        try:
            corrected = await self._apply_known_fixes(
                "PUT", path, payload, resp,
            )
            if corrected is not None:
                logger.info(f"[SmartRetry] Retrying PUT {path} with corrected payload")
                resp = await self.put(path, corrected, params=params)
        except Exception as exc:
            logger.debug(f"[SmartRetry] Fix attempt failed (non-fatal): {exc}")

        return resp

    # -- rule-based 422 fix --------------------------------------------------

    async def _apply_known_fixes(
        self,
        method: str,
        path: str,
        payload: dict[str, Any],
        resp: httpx.Response,
    ) -> dict[str, Any] | None:
        """Parse 422 validationMessages and apply rule-based corrections.

        Returns a corrected payload copy, or None if no fix was applied.
        """
        try:
            err_data = _json.loads(resp.text[:4000])
        except (ValueError, TypeError):
            return None

        validation_msgs = err_data.get("validationMessages") or []
        if not validation_msgs:
            # Try top-level message
            msg = err_data.get("message", "")
            if msg:
                validation_msgs = [{"field": "", "message": msg}]
            else:
                return None

        fixed = copy.deepcopy(payload)
        any_fix = False

        for vm in validation_msgs:
            field = vm.get("field", "")
            msg = vm.get("message", "")
            msg_lower = msg.lower()

            # Rule 1: "allerede i bruk" + field="number" → entity already exists
            if ("allerede i bruk" in msg_lower or "already in use" in msg_lower) and "number" in field.lower():
                # Try to find existing entity via GET and return its ID
                existing = await self._find_existing_by_number(path, fixed)
                if existing is not None:
                    logger.info(f"[SmartRetry] Entity already exists on {path}, found id={existing}")
                    # Can't really fix the payload — the caller needs the existing entity
                    # Return None so the caller handles it
                    return None

            # Rule 2: "eksisterer ikke i objektet" / "does not exist" → remove field
            if "eksisterer ikke" in msg_lower or "does not exist in the object" in msg_lower:
                if field and self._remove_field(fixed, field):
                    logger.info(f"[SmartRetry] Removed invalid field '{field}' from payload")
                    any_fix = True

            # Rule 3: "Kan ikke opprette subelement" → convert vatType from number to id
            if "kan ikke opprette subelement" in msg_lower or "cannot create sub-element" in msg_lower:
                if self._fix_subelement_refs(fixed):
                    logger.info(f"[SmartRetry] Converted subelement references (number→id) in payload")
                    any_fix = True

            # Rule 4: "må fylles ut" / "required" → add defaults
            if "må fylles ut" in msg_lower or "required" in msg_lower:
                if field:
                    # Extract the simple field name (last part of dotted path)
                    simple_field = field.split(".")[-1]
                    if simple_field in _REQUIRED_FIELD_DEFAULTS and simple_field not in fixed:
                        fixed[simple_field] = copy.deepcopy(_REQUIRED_FIELD_DEFAULTS[simple_field])
                        logger.info(f"[SmartRetry] Added default for required field '{simple_field}'")
                        any_fix = True

        return fixed if any_fix else None

    async def _find_existing_by_number(self, path: str, payload: dict[str, Any]) -> int | None:
        """Try to find an existing entity by its 'number' field via GET.

        Returns the entity ID if found, None otherwise.
        """
        number = payload.get("number")
        if not number:
            return None

        # Derive the list endpoint from the POST path
        # e.g. /product → GET /product?number=X
        try:
            resp = await self.get(path, params={"number": str(number), "fields": "id,number"})
            if resp.status_code == 200:
                values = resp.json().get("values", [])
                if values:
                    return values[0].get("id")
        except Exception:
            pass
        return None

    @staticmethod
    def _remove_field(payload: dict[str, Any], field_path: str) -> bool:
        """Remove a field from payload by dotted path. Returns True if removed."""
        parts = field_path.split(".")
        current = payload
        for part in parts[:-1]:
            if isinstance(current, dict) and part in current:
                current = current[part]
            elif isinstance(current, list):
                # Try to find the field in list items
                for item in current:
                    if isinstance(item, dict) and part in item:
                        current = item[part]
                        break
                else:
                    return False
            else:
                return False

        target_key = parts[-1]
        if isinstance(current, dict) and target_key in current:
            del current[target_key]
            return True
        elif isinstance(current, list):
            removed = False
            for item in current:
                if isinstance(item, dict) and target_key in item:
                    del item[target_key]
                    removed = True
            return removed
        return False

    @staticmethod
    def _fix_subelement_refs(payload: dict[str, Any]) -> bool:
        """Convert vatType references from {"number": "3"} to {"id": <int>}.

        Also handles nested structures like orderLines[].vatType.
        Returns True if any fix was applied.
        """
        fixed = False

        def _fix_vat_in_dict(d: dict) -> bool:
            nonlocal fixed
            vat = d.get("vatType")
            if isinstance(vat, dict) and "number" in vat and "id" not in vat:
                # Convert number-based ref to id-based — use number as id (heuristic)
                num = vat["number"]
                try:
                    d["vatType"] = {"id": int(num)}
                    fixed = True
                except (ValueError, TypeError):
                    pass
            return fixed

        _fix_vat_in_dict(payload)

        # Check nested lists (orderLines, postings, etc.)
        for key, value in payload.items():
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        _fix_vat_in_dict(item)
            elif isinstance(value, dict):
                _fix_vat_in_dict(value)

        return fixed

    # -- active pre-flight correction ----------------------------------------

    @staticmethod
    def _preflight_correct(method: str, path: str, payload: dict[str, Any] | None) -> dict[str, Any] | None:
        """Run pre-flight correction against known error patterns.

        Instead of just logging warnings, actively removes fields that have
        historically caused 'eksisterer ikke' errors. Returns the (possibly
        modified) payload.
        """
        if not _HAS_ERROR_PATTERNS or not payload:
            return payload

        try:
            known = _ep_get_known_errors(path, method)
            if not known:
                return payload

            corrected = False
            for pattern in known:
                field = pattern.get("field", "")
                error_type = pattern.get("error_type", "")
                error_msg = pattern.get("error_message", "")

                # Remove fields that historically caused "eksisterer ikke"
                if error_type == "invalid_field" and field:
                    parts = field.split(".")
                    current = payload
                    removable = True
                    for part in parts[:-1]:
                        if isinstance(current, dict) and part in current:
                            current = current[part]
                        else:
                            removable = False
                            break
                    if removable and isinstance(current, dict):
                        target = parts[-1]
                        if target in current:
                            del current[target]
                            logger.info(
                                f"[PreFlight] Removed '{field}' from {method} {path} "
                                f"(known error: {error_msg})"
                            )
                            corrected = True

            # Also run the check_payload for warnings (non-blocking)
            try:
                warnings = _ep_check_payload(path, method, payload)
                for w in warnings:
                    logger.warning(f"[Error Patterns] {w}")
            except Exception:
                pass

            return payload

        except Exception as exc:
            logger.debug(f"Pre-flight correction failed (non-fatal): {exc}")
            return payload

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
        if params:
            logger.info(f"Params: {params}")

        t0 = time.monotonic()
        try:
            resp = await self._client.request(method, url, json=json_body, params=params)
        except Exception as exc:
            duration = (time.monotonic() - t0) * 1000
            self.tracker.record(method, path, 0, duration, error=str(exc),
                                url=url, query_params=params, request_body=json_body)
            raise

        duration = (time.monotonic() - t0) * 1000
        error_body = None
        if 400 <= resp.status_code < 500:
            error_body = resp.text[:500]
        self.tracker.record(
            method, path, resp.status_code, duration, error=error_body,
            url=url, query_params=params, request_body=json_body,
            response_body=resp.text[:2000] if self.debug else None,
        )
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
