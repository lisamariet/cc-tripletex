"""Gemini parser — uses Vertex AI REST API (works both locally and in Cloud Run).

Falls back to gcloud CLI token when Application Default Credentials are unavailable.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from typing import Any

import httpx

from app.models import ParsedTask
from app.parser import (
    SYSTEM_PROMPT,
    VALID_TASK_TYPES,
    _infer_task_type_from_keywords,
    _parse_json_response,
)

logger = logging.getLogger(__name__)

_GCP_PROJECT = os.getenv("GCP_PROJECT", "ai-nm26osl-1771")
_GCP_LOCATION = os.getenv("GCP_LOCATION", "europe-west1")
_GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

_cached_token: str | None = None


def _get_access_token() -> str:
    """Get access token — ADC first, gcloud CLI fallback."""
    global _cached_token
    if _cached_token:
        return _cached_token

    # Try google.auth (works in Cloud Run)
    try:
        import google.auth
        import google.auth.transport.requests
        creds, _ = google.auth.default()
        creds.refresh(google.auth.transport.requests.Request())
        _cached_token = creds.token
        return _cached_token
    except Exception:
        pass

    # Fallback: gcloud CLI (works locally)
    try:
        result = subprocess.run(
            ["gcloud", "auth", "print-access-token"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            _cached_token = result.stdout.strip()
            return _cached_token
    except Exception:
        pass

    raise RuntimeError("Cannot get GCP access token — neither ADC nor gcloud available")


def _call_gemini(prompt: str, system_prompt: str, files: list[dict[str, Any]] | None = None) -> str:
    """Call Gemini via Vertex AI REST API. Supports inline files (PDF, images)."""
    token = _get_access_token()
    url = (
        f"https://{_GCP_LOCATION}-aiplatform.googleapis.com/v1/"
        f"projects/{_GCP_PROJECT}/locations/{_GCP_LOCATION}/"
        f"publishers/google/models/{_GEMINI_MODEL}:generateContent"
    )

    # Build parts: files first (so Gemini sees them before the text prompt)
    parts: list[dict[str, Any]] = []
    if files:
        for f in files:
            content_b64 = f.get("content_base64", "")
            mime_type = f.get("mime_type", "application/pdf")
            if content_b64:
                parts.append({"inlineData": {"mimeType": mime_type, "data": content_b64}})
                logger.info(f"[Gemini] Attached file: {f.get('filename', '?')} ({mime_type}, {len(content_b64)} chars b64)")
    parts.append({"text": prompt})

    payload = {
        "contents": [{"role": "user", "parts": parts}],
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "generationConfig": {"temperature": 0, "maxOutputTokens": 8192},
    }
    resp = httpx.post(url, json=payload, headers={"Authorization": f"Bearer {token}"}, timeout=30.0)

    if resp.status_code == 401:
        global _cached_token
        _cached_token = None
        token = _get_access_token()
        resp = httpx.post(url, json=payload, headers={"Authorization": f"Bearer {token}"}, timeout=30.0)

    resp.raise_for_status()
    data = resp.json()
    candidates = data.get("candidates", [])
    if not candidates:
        raise ValueError(f"No candidates in Gemini response: {data}")
    return candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")


def parse_task_gemini(
    prompt: str, files: list[dict[str, Any]] | None = None
) -> ParsedTask:
    """Parse a task prompt using Gemini via REST API.

    Strategy: keyword pre-classification FIRST (deterministic, tested),
    then Gemini for field extraction. Gemini only decides task_type
    when keywords don't match.
    """
    logger.info(f"[Gemini] Parsing task: {prompt[:200]}")

    # Step 0: Keyword pre-classification — deterministic, always wins
    keyword_type = _infer_task_type_from_keywords(prompt)
    if keyword_type:
        logger.info(f"[Gemini] Keyword pre-match: {keyword_type} — using Gemini for field extraction only")

    try:
        raw_text = _call_gemini(prompt, SYSTEM_PROMPT, files=files)
        logger.info(f"[Gemini] Response: {raw_text[:500]}")

    except Exception as e:
        logger.error(f"[Gemini] API call failed: {e}")
        inferred = _infer_task_type_from_keywords(prompt)
        if inferred:
            return ParsedTask(task_type=inferred, fields={}, confidence=0.5,
                              reasoning=f"Gemini failed ({e}), keyword-inferred: {inferred}")
        return ParsedTask(task_type="unknown", fields={}, confidence=0.0,
                          reasoning=f"Gemini failed: {e}")

    # Parse JSON response
    try:
        parsed = _parse_json_response(raw_text)
    except (json.JSONDecodeError, ValueError) as e:
        logger.error(f"[Gemini] JSON parse error: {e}")
        inferred = _infer_task_type_from_keywords(prompt)
        if inferred:
            return ParsedTask(task_type=inferred, fields={}, confidence=0.5,
                              reasoning=f"Gemini JSON error, keyword: {inferred}")
        return ParsedTask(task_type="unknown", fields={}, reasoning=f"JSON error: {e}")

    # Handle list (batch)
    if isinstance(parsed, list):
        if len(parsed) == 1:
            parsed = parsed[0]
        elif len(parsed) > 1:
            first = parsed[0] if isinstance(parsed[0], dict) else {}
            task_type = first.get("taskType", "unknown")
            return ParsedTask(
                task_type=f"batch_{task_type}" if task_type != "unknown" else "unknown",
                fields={"items": parsed},
                confidence=first.get("confidence", 0.5),
                reasoning=f"Batch of {len(parsed)} items",
            )

    if not isinstance(parsed, dict):
        return ParsedTask(task_type="unknown", fields={}, reasoning="Unexpected format")

    gemini_type = parsed.get("taskType", "unknown")
    if gemini_type not in VALID_TASK_TYPES and gemini_type != "unknown":
        gemini_type = "unknown"

    # Keyword pre-classification WINS over Gemini for task_type
    # Gemini is only used for field extraction (it's better at parsing fields from PDF/images)
    if keyword_type and keyword_type in VALID_TASK_TYPES:
        final_type = keyword_type
        if gemini_type != keyword_type and gemini_type != "unknown":
            logger.info(f"[Gemini] Keyword override: Gemini said '{gemini_type}' but keywords say '{keyword_type}' — using keywords")
    elif gemini_type != "unknown":
        final_type = gemini_type
    else:
        final_type = "unknown"

    task = ParsedTask(
        task_type=final_type,
        fields=parsed.get("fields", {}),
        confidence=parsed.get("confidence", 0.0),
        reasoning=parsed.get("reasoning", ""),
    )

    logger.info(f"[Gemini] Parsed: type={task.task_type} (gemini={gemini_type}, keyword={keyword_type}), confidence={task.confidence}")
    return task
