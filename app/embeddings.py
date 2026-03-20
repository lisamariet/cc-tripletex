"""Embedding-based prompt classifier using Vertex AI text-embedding-005.

This module provides fast task-type classification by comparing incoming prompts
against a pre-built index of known prompts with their task types. Uses cosine
similarity on Vertex AI embeddings (~10ms) as a first-pass classifier before
the more expensive LLM parsing.

Authentication: Uses google.auth.default() which works with:
- Cloud Run (service account)
- Local development with `gcloud auth application-default login`
- gcloud auth (via subprocess fallback)
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

import httpx
import numpy as np

logger = logging.getLogger(__name__)

_GCP_PROJECT = "ai-nm26osl-1771"
_GCP_REGION = "europe-west1"
_EMBEDDING_MODEL = "text-embedding-005"
_INDEX_PATH = Path(__file__).parent / "embeddings_index.json"

# Cached index: list of {prompt, task_type, embedding}
_index: list[dict[str, Any]] | None = None
_index_matrix: np.ndarray | None = None
_index_types: list[str] | None = None


def _get_access_token() -> str:
    """Get an access token for Vertex AI API calls.

    Tries google.auth.default() first, falls back to gcloud CLI.
    """
    try:
        import google.auth
        import google.auth.transport.requests

        credentials, project = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        credentials.refresh(google.auth.transport.requests.Request())
        return credentials.token
    except Exception:
        pass

    # Fallback: use gcloud CLI
    try:
        result = subprocess.run(
            ["gcloud", "auth", "print-access-token"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass

    raise RuntimeError("Could not obtain GCP access token")


def _call_vertex_embeddings(texts: list[str]) -> list[list[float]]:
    """Call Vertex AI embedding API via REST.

    Uses the predict endpoint directly, which works with any auth method.
    """
    token = _get_access_token()
    url = (
        f"https://{_GCP_REGION}-aiplatform.googleapis.com/v1/"
        f"projects/{_GCP_PROJECT}/locations/{_GCP_REGION}/"
        f"publishers/google/models/{_EMBEDDING_MODEL}:predict"
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "instances": [{"content": t} for t in texts],
    }

    response = httpx.post(url, json=payload, headers=headers, timeout=30.0)
    response.raise_for_status()
    data = response.json()

    return [pred["embeddings"]["values"] for pred in data["predictions"]]


def embed_text(text: str) -> list[float]:
    """Embed a single text string using Vertex AI text-embedding-005.

    Returns a list of floats (the embedding vector).
    """
    return _call_vertex_embeddings([text])[0]


def embed_texts_batch(texts: list[str], batch_size: int = 50) -> list[list[float]]:
    """Embed multiple texts in batches using Vertex AI.

    Vertex AI supports up to 250 texts per request, but we use smaller batches
    for reliability.
    """
    all_embeddings: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        logger.info(f"Embedding batch {i // batch_size + 1} ({len(batch)} texts)")
        embeddings = _call_vertex_embeddings(batch)
        all_embeddings.extend(embeddings)

    return all_embeddings


def _load_index() -> None:
    """Load the embedding index from disk into memory."""
    global _index, _index_matrix, _index_types

    if not _INDEX_PATH.exists():
        logger.warning(f"Embedding index not found at {_INDEX_PATH}")
        _index = []
        _index_matrix = np.array([])
        _index_types = []
        return

    with open(_INDEX_PATH) as f:
        _index = json.load(f)

    if not _index:
        _index_matrix = np.array([])
        _index_types = []
        return

    # Build numpy matrix for fast cosine similarity
    _index_matrix = np.array([entry["embedding"] for entry in _index], dtype=np.float32)
    _index_types = [entry["task_type"] for entry in _index]

    # Pre-normalize for faster cosine similarity
    norms = np.linalg.norm(_index_matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0  # avoid division by zero
    _index_matrix = _index_matrix / norms

    logger.info(f"Loaded embedding index: {len(_index)} entries, {len(set(_index_types))} task types")


def classify_prompt(text: str) -> tuple[str, float]:
    """Classify a prompt using embedding similarity.

    Returns (task_type, confidence) where confidence is the cosine similarity
    to the nearest neighbor in the index.

    If the index is empty or embedding fails, returns ("unknown", 0.0).
    """
    global _index, _index_matrix, _index_types

    # Lazy-load index
    if _index is None:
        _load_index()

    if not _index or _index_matrix is None or _index_matrix.size == 0:
        logger.warning("Empty embedding index, skipping classification")
        return ("unknown", 0.0)

    try:
        query_embedding = np.array(embed_text(text), dtype=np.float32)
    except Exception as e:
        logger.warning(f"Embedding failed, skipping classification: {e}")
        return ("unknown", 0.0)

    # Normalize query
    query_norm = np.linalg.norm(query_embedding)
    if query_norm == 0:
        return ("unknown", 0.0)
    query_normalized = query_embedding / query_norm

    # Cosine similarity = dot product of normalized vectors
    similarities = _index_matrix @ query_normalized

    # Find best match
    best_idx = int(np.argmax(similarities))
    best_similarity = float(similarities[best_idx])
    best_type = _index_types[best_idx]

    logger.info(
        f"Embedding classification: type={best_type}, "
        f"similarity={best_similarity:.4f}, "
        f"prompt='{_index[best_idx]['prompt'][:80]}...'"
    )

    return (best_type, best_similarity)


def get_similar_examples(prompt: str, task_type: str, top_k: int = 3) -> list[dict]:
    """Find the top_k most similar prompts of the SAME task_type from the index.

    Returns a list of {"prompt": ..., "fields": ...} dicts suitable for few-shot
    injection. Returns an empty list if the index is unavailable or embedding fails.
    """
    global _index, _index_matrix, _index_types

    # Lazy-load index
    if _index is None:
        _load_index()

    if not _index or _index_matrix is None or _index_matrix.size == 0:
        return []

    try:
        query_embedding = np.array(embed_text(prompt), dtype=np.float32)
    except Exception as e:
        logger.warning(f"Embedding failed in get_similar_examples: {e}")
        return []

    # Normalize query
    query_norm = np.linalg.norm(query_embedding)
    if query_norm == 0:
        return []
    query_normalized = query_embedding / query_norm

    # Cosine similarity against all entries
    similarities = _index_matrix @ query_normalized

    # Filter to same task_type and sort by similarity (descending)
    candidates = []
    for i, (sim, entry) in enumerate(zip(similarities, _index)):
        if entry["task_type"] == task_type:
            candidates.append((float(sim), i))

    if not candidates:
        return []

    # Sort descending by similarity, take top_k
    candidates.sort(key=lambda x: -x[0])
    results = []
    for sim, idx in candidates[:top_k]:
        entry = _index[idx]
        # Skip if this is the exact same prompt
        if entry["prompt"].strip() == prompt.strip():
            continue
        results.append({
            "prompt": entry["prompt"],
            "fields": entry.get("fields", {}),
        })

    logger.info(f"Found {len(results)} similar examples for task_type={task_type}")
    return results


def build_index() -> list[dict[str, Any]]:
    """Build the embedding index from data/results/ and data/requests/.

    Reads all result files, extracts prompts and task types, embeds them,
    and returns the index entries.
    """
    import re
    from app.parser import _KEYWORD_RULES

    data_dir = Path(__file__).parent.parent / "data"
    results_dir = data_dir / "results"

    entries: list[dict[str, str]] = []  # {prompt, task_type}

    # Read results files (they have parsed_task with task_type)
    for result_file in sorted(results_dir.glob("*.json")):
        try:
            with open(result_file) as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Skipping {result_file.name}: {e}")
            continue

        prompt = data.get("prompt", "").strip()
        if not prompt:
            continue

        # Filter out test prompts
        if _is_test_prompt(prompt):
            logger.debug(f"Skipping test prompt: {prompt[:60]}")
            continue

        parsed_task = data.get("parsed_task")
        if parsed_task is None:
            continue

        task_type = parsed_task.get("task_type", "unknown")

        # Handle batch types — extract the base type
        if task_type.startswith("batch_"):
            task_type = task_type[len("batch_"):]

        # If unknown, try to infer from keywords
        if task_type == "unknown":
            inferred = _infer_type_from_keywords(prompt, _KEYWORD_RULES)
            if inferred:
                task_type = inferred
                logger.info(f"Inferred {task_type} for: {prompt[:60]}")
            else:
                logger.info(f"Skipping unknown-type prompt (no inference): {prompt[:60]}")
                continue

        # Extract fields for few-shot retrieval
        fields = parsed_task.get("fields", {})
        entries.append({"prompt": prompt, "task_type": task_type, "fields": fields})

    logger.info(f"Collected {len(entries)} prompts for embedding")

    if not entries:
        return []

    # Embed all prompts
    prompts = [e["prompt"] for e in entries]
    embeddings = embed_texts_batch(prompts)

    index = []
    for entry, embedding in zip(entries, embeddings):
        index.append({
            "prompt": entry["prompt"],
            "task_type": entry["task_type"],
            "fields": entry.get("fields", {}),
            "embedding": embedding,
        })

    return index


def save_index(index: list[dict[str, Any]], path: Path | None = None) -> None:
    """Save the embedding index to disk."""
    target = path or _INDEX_PATH
    with open(target, "w") as f:
        json.dump(index, f, ensure_ascii=False)
    logger.info(f"Saved embedding index ({len(index)} entries) to {target}")


def _is_test_prompt(prompt: str) -> bool:
    """Check if a prompt is a test prompt that should be filtered out."""
    prompt_lower = prompt.lower().strip()
    # Filter very short prompts or obvious test strings
    if len(prompt_lower) < 10:
        return True
    if prompt_lower in ("test", "test oppgave", "test task", "hello", "ping"):
        return True
    return False


def _infer_type_from_keywords(
    prompt: str, keyword_rules: list[tuple[str, list[str]]]
) -> str | None:
    """Infer task type from keyword patterns (reuses parser rules)."""
    import re

    prompt_lower = prompt.lower()
    for task_type, patterns in keyword_rules:
        for pattern in patterns:
            if re.search(pattern, prompt_lower, re.IGNORECASE):
                return task_type
    return None
