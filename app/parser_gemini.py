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


def _call_gemini(prompt: str, system_prompt: str) -> str:
    """Call Gemini via Vertex AI REST API."""
    token = _get_access_token()
    url = (
        f"https://{_GCP_LOCATION}-aiplatform.googleapis.com/v1/"
        f"projects/{_GCP_PROJECT}/locations/{_GCP_LOCATION}/"
        f"publishers/google/models/{_GEMINI_MODEL}:generateContent"
    )
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "generationConfig": {"temperature": 0, "maxOutputTokens": 2048},
    }
    resp = httpx.post(url, json=payload, headers={"Authorization": f"Bearer {token}"}, timeout=30.0)

    if resp.status_code == 401:
        # Token expired, clear cache and retry once
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
    """Parse a task prompt using Gemini via REST API."""
    logger.info(f"[Gemini] Parsing task: {prompt[:200]}")

    try:
        user_text = prompt
        if files:
            file_descriptions = [f"[Attached file: {f.get('name', f.get('filename', 'unknown'))}]" for f in files]
            if file_descriptions:
                user_text = user_text + "\n\n" + "\n".join(file_descriptions)

        raw_text = _call_gemini(user_text, SYSTEM_PROMPT)
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

    task = ParsedTask(
        task_type=parsed.get("taskType", "unknown"),
        fields=parsed.get("fields", {}),
        confidence=parsed.get("confidence", 0.0),
        reasoning=parsed.get("reasoning", ""),
    )

    if task.task_type not in VALID_TASK_TYPES and task.task_type != "unknown":
        task.task_type = "unknown"

    if task.task_type == "unknown":
        inferred = _infer_task_type_from_keywords(prompt)
        if inferred:
            task.task_type = inferred
            task.reasoning = f"Keyword: {inferred}. {task.reasoning}"

    logger.info(f"[Gemini] Parsed: type={task.task_type}, confidence={task.confidence}")
    return task
