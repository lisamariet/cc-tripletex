from __future__ import annotations

import base64
import csv
import io
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Mime types we pass as native image/document content to the LLM
IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
PDF_TYPE = "application/pdf"


def process_files(files: list[dict[str, Any]]) -> list[dict]:
    """Convert incoming file dicts into LLM content blocks.

    Each file dict has: filename, mime_type, content_base64.
    Returns a list of Anthropic message content blocks.
    """
    blocks: list[dict] = []
    for f in files:
        mime = f.get("mime_type", "")
        b64 = f.get("content_base64", "")
        filename = f.get("filename", "unknown")

        if not b64:
            continue

        if mime in IMAGE_TYPES:
            blocks.append({
                "type": "image",
                "source": {"type": "base64", "media_type": mime, "data": b64},
            })
        elif mime == PDF_TYPE:
            blocks.append({
                "type": "document",
                "source": {"type": "base64", "media_type": "application/pdf", "data": b64},
            })
        elif mime == "text/csv" or filename.endswith(".csv"):
            # Parse CSV and include as text
            try:
                raw = base64.b64decode(b64).decode("utf-8")
                reader = csv.reader(io.StringIO(raw))
                rows = list(reader)
                text = f"CSV file '{filename}':\n"
                for row in rows[:200]:  # cap rows
                    text += " | ".join(row) + "\n"
                blocks.append({"type": "text", "text": text})
            except Exception as e:
                logger.warning(f"Failed to parse CSV {filename}: {e}")
                blocks.append({"type": "text", "text": f"[CSV file: {filename} — parse error]"})
        else:
            # Fallback: try to decode as text
            try:
                raw = base64.b64decode(b64).decode("utf-8")
                blocks.append({"type": "text", "text": f"File '{filename}':\n{raw[:5000]}"})
            except Exception:
                blocks.append({"type": "text", "text": f"[Binary file: {filename}, type: {mime}]"})

    return blocks
