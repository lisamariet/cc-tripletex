"""Gemini 2.0 Flash parser — drop-in replacement for Anthropic-based parse_task().

Uses Vertex AI Gemini 2.0 Flash for task classification and field extraction.
Same interface and return format as parse_task() in parser.py.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from app.models import ParsedTask
from app.parser import (
    SYSTEM_PROMPT,
    VALID_TASK_TYPES,
    _infer_task_type_from_keywords,
    _parse_json_response,
)

logger = logging.getLogger(__name__)

# Vertex AI config
_GCP_PROJECT = os.getenv("GCP_PROJECT", "ai-nm26osl-1771")
_GCP_LOCATION = os.getenv("GCP_LOCATION", "europe-west1")
_GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

_vertexai_initialized = False


def _ensure_vertexai() -> None:
    """Lazy-init Vertex AI SDK (only once)."""
    global _vertexai_initialized
    if _vertexai_initialized:
        return
    import vertexai

    vertexai.init(project=_GCP_PROJECT, location=_GCP_LOCATION)
    _vertexai_initialized = True
    logger.info(f"Vertex AI initialized: project={_GCP_PROJECT}, location={_GCP_LOCATION}")


def parse_task_gemini(
    prompt: str, files: list[dict[str, Any]] | None = None
) -> ParsedTask:
    """Parse a task prompt using Vertex AI Gemini 2.0 Flash.

    Same signature and return format as parse_task() in parser.py.
    """
    logger.info(f"[Gemini] Parsing task: {prompt[:200]}")

    try:
        _ensure_vertexai()
        from vertexai.generative_models import GenerativeModel, GenerationConfig

        model = GenerativeModel(
            _GEMINI_MODEL,
            system_instruction=SYSTEM_PROMPT,
        )

        generation_config = GenerationConfig(
            temperature=0.0,
            max_output_tokens=1024,
        )

        # Build prompt content — for now text only
        # (file/image support can be added later via vertexai Part objects)
        user_text = prompt
        if files:
            # Append file metadata as context (binary content not sent to Gemini yet)
            file_descriptions = []
            for f in files:
                name = f.get("name", f.get("filename", "unknown"))
                file_descriptions.append(f"[Attached file: {name}]")
            if file_descriptions:
                user_text = user_text + "\n\n" + "\n".join(file_descriptions)

        response = model.generate_content(
            user_text,
            generation_config=generation_config,
        )

        raw_text = response.text
        logger.info(f"[Gemini] Response: {raw_text}")

    except Exception as e:
        logger.error(f"[Gemini] API call failed: {e}")
        # Keyword fallback
        inferred = _infer_task_type_from_keywords(prompt)
        if inferred:
            logger.info(f"[Gemini] Keyword fallback resolved: {inferred}")
            return ParsedTask(
                task_type=inferred,
                fields={},
                confidence=0.5,
                reasoning=f"Gemini API failed ({e}), keyword-inferred: {inferred}",
            )
        return ParsedTask(
            task_type="unknown",
            fields={},
            confidence=0.0,
            reasoning=f"Gemini API failed: {e}",
        )

    # Parse JSON response
    try:
        parsed = _parse_json_response(raw_text)
    except (json.JSONDecodeError, ValueError) as e:
        logger.error(f"[Gemini] Failed to parse JSON: {e}")
        # Keyword fallback
        inferred = _infer_task_type_from_keywords(prompt)
        if inferred:
            return ParsedTask(
                task_type=inferred,
                fields={},
                confidence=0.5,
                reasoning=f"Gemini JSON parse error, keyword-inferred: {inferred}",
            )
        return ParsedTask(
            task_type="unknown",
            fields={},
            reasoning=f"JSON parse error: {e}",
        )

    # Handle list (batch) responses
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
        logger.error(f"[Gemini] Unexpected parse result type: {type(parsed)}")
        return ParsedTask(
            task_type="unknown", fields={}, reasoning="Unexpected response format"
        )

    task = ParsedTask(
        task_type=parsed.get("taskType", "unknown"),
        fields=parsed.get("fields", {}),
        confidence=parsed.get("confidence", 0.0),
        reasoning=parsed.get("reasoning", ""),
    )
    logger.info(f"[Gemini] Parsed: type={task.task_type}, confidence={task.confidence}")

    # Validate task_type
    if task.task_type not in VALID_TASK_TYPES and task.task_type != "unknown":
        logger.warning(f"[Gemini] Unrecognized task type: {task.task_type}")
        task.task_type = "unknown"

    # Keyword fallback if still unknown
    if task.task_type == "unknown":
        inferred = _infer_task_type_from_keywords(prompt)
        if inferred:
            logger.info(f"[Gemini] Keyword inference resolved unknown -> {inferred}")
            task.task_type = inferred
            task.reasoning = f"Keyword-inferred: {inferred}. Original: {task.reasoning}"

    return task
