"""RAG (Retrieval-Augmented Generation) for Tripletex API documentation.

Provides lookup functions that find relevant API documentation chunks
based on endpoint, method, and error messages. Used to help handlers
auto-correct 422 errors by finding the correct payload format.

Authentication: Uses same Vertex AI setup as embeddings.py.
Graceful degradation: Returns empty string if RAG fails.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

_RAG_INDEX_PATH = Path(__file__).parent / "api_rag_index.json"

# Cached RAG index
_rag_index: list[dict[str, Any]] | None = None
_rag_matrix: np.ndarray | None = None
_rag_texts: list[str] | None = None


def _load_rag_index() -> None:
    """Load the RAG index from disk into memory."""
    global _rag_index, _rag_matrix, _rag_texts

    if not _RAG_INDEX_PATH.exists():
        logger.warning(f"RAG index not found at {_RAG_INDEX_PATH}")
        _rag_index = []
        _rag_matrix = np.array([])
        _rag_texts = []
        return

    with open(_RAG_INDEX_PATH) as f:
        _rag_index = json.load(f)

    if not _rag_index:
        _rag_matrix = np.array([])
        _rag_texts = []
        return

    _rag_matrix = np.array(
        [entry["embedding"] for entry in _rag_index], dtype=np.float32
    )
    _rag_texts = [entry["text"] for entry in _rag_index]

    # Pre-normalize for cosine similarity
    norms = np.linalg.norm(_rag_matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    _rag_matrix = _rag_matrix / norms

    logger.info(f"Loaded RAG index: {len(_rag_index)} chunks")


def lookup_api_docs(
    endpoint: str, method: str, error_message: str = "", top_k: int = 3
) -> str:
    """Look up relevant API documentation for a given endpoint and method.

    Args:
        endpoint: API path, e.g. "/customer" or "/project"
        method: HTTP method, e.g. "POST", "GET"
        error_message: Optional error message for more targeted lookup

    Returns:
        Context string with relevant API doc chunks, or empty string on failure.
    """
    global _rag_index, _rag_matrix, _rag_texts

    try:
        # Lazy-load index
        if _rag_index is None:
            _load_rag_index()

        if not _rag_index or _rag_matrix is None or _rag_matrix.size == 0:
            logger.warning("Empty RAG index, skipping lookup")
            return ""

        # Build query
        query_parts = [f"{method.upper()} {endpoint}"]
        if error_message:
            query_parts.append(error_message)
        query = " ".join(query_parts)

        # Embed query
        from app.embeddings import embed_text

        query_embedding = np.array(embed_text(query), dtype=np.float32)
        query_norm = np.linalg.norm(query_embedding)
        if query_norm == 0:
            return ""
        query_normalized = query_embedding / query_norm

        # Cosine similarity
        similarities = _rag_matrix @ query_normalized

        # Get top-k indices
        top_indices = np.argsort(similarities)[-top_k:][::-1]

        results = []
        for idx in top_indices:
            idx = int(idx)
            sim = float(similarities[idx])
            if sim > 0.3:  # minimum relevance threshold
                results.append(f"[Relevance: {sim:.2f}]\n{_rag_texts[idx]}")

        if not results:
            logger.info(f"No relevant RAG results for {method} {endpoint}")
            return ""

        context = "\n\n---\n\n".join(results)
        logger.info(
            f"RAG lookup for {method} {endpoint}: {len(results)} results"
        )
        return context

    except Exception as e:
        logger.warning(f"RAG lookup failed: {e}")
        return ""


def suggest_fix(
    endpoint: str, method: str, error_response: dict | str
) -> dict:
    """Suggest a fix for a failed API call based on RAG lookup.

    Args:
        endpoint: API path that returned an error
        method: HTTP method used
        error_response: Error response body (dict or string)

    Returns:
        Dict with keys:
            - context: Relevant API documentation
            - suggestion: Brief suggestion text
            - endpoint: The endpoint queried
            - method: The method queried
        Returns empty dict on failure.
    """
    try:
        # Extract error message
        if isinstance(error_response, dict):
            error_msg = error_response.get("message", "")
            if not error_msg:
                # Try nested structure
                error_msg = json.dumps(error_response)[:200]
        else:
            error_msg = str(error_response)[:200]

        context = lookup_api_docs(endpoint, method, error_msg)

        if not context:
            return {}

        return {
            "context": context,
            "suggestion": f"API documentation for {method} {endpoint} suggests checking required fields and format. See context for details.",
            "endpoint": endpoint,
            "method": method,
        }

    except Exception as e:
        logger.warning(f"suggest_fix failed: {e}")
        return {}
