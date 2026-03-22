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
_GCS_EMBEDDING_INDEX = "indexes/embeddings_index.json"

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


def _download_from_gcs(gcs_key: str) -> list[dict[str, Any]] | None:
    """Try downloading index from GCS. Returns parsed JSON or None."""
    try:
        from google.cloud import storage as gcs
        from app.config import GCS_BUCKET

        client = gcs.Client()
        blob = client.bucket(GCS_BUCKET).blob(gcs_key)
        if not blob.exists():
            return None
        data = json.loads(blob.download_as_text())
        logger.info(f"Loaded index from gs://{GCS_BUCKET}/{gcs_key} ({len(data)} entries)")
        return data
    except Exception as e:
        logger.debug(f"GCS download failed for {gcs_key}: {e}")
        return None


def _load_index() -> None:
    """Load the embedding index from GCS (preferred) or local disk (fallback)."""
    global _index, _index_matrix, _index_types

    # Try GCS first
    _index = _download_from_gcs(_GCS_EMBEDDING_INDEX)

    # Fallback to local file
    if _index is None:
        if not _INDEX_PATH.exists():
            logger.warning(f"Embedding index not found locally or in GCS")
            _index = []
            _index_matrix = np.array([])
            _index_types = []
            return
        with open(_INDEX_PATH) as f:
            _index = json.load(f)
        logger.info(f"Loaded embedding index from local file ({len(_index)} entries)")

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
    """Classify a prompt using embedding similarity with 3-tier confidence routing.

    Returns (task_type, confidence) where confidence is the cosine similarity
    to the nearest neighbor in the index.

    Confidence tiers:
    - >= 0.85: High confidence — use embedding result directly (skip LLM)
    - 0.70–0.85: Medium confidence — use as hint for LLM (top-3 matches)
    - < 0.70: Low confidence — fall back to pure LLM classification

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

    # Find top-3 for logging and hint context
    top_k = min(3, len(similarities))
    top_indices = np.argsort(similarities)[-top_k:][::-1]
    top_matches = [
        (float(similarities[i]), _index_types[i], _index[i]["prompt"][:60])
        for i in top_indices
    ]

    # Determine routing tier
    if best_similarity >= 0.85:
        routing = "HIGH_CONFIDENCE_DIRECT"
    elif best_similarity >= 0.70:
        routing = "MEDIUM_CONFIDENCE_HINT"
    else:
        routing = "LOW_CONFIDENCE_FALLBACK"

    logger.info(
        f"Embedding classification: type={best_type}, "
        f"similarity={best_similarity:.4f}, "
        f"routing={routing}, "
        f"top3={[(f'{s:.3f}', t) for s, t, _ in top_matches]}"
    )

    return (best_type, best_similarity)


def get_top_matches(text: str, top_k: int = 3) -> list[dict[str, Any]]:
    """Get top-k embedding matches with similarity scores.

    Returns list of {task_type, similarity, prompt} dicts for use as LLM hints
    in the medium-confidence tier (0.70-0.85).
    """
    global _index, _index_matrix, _index_types

    if _index is None:
        _load_index()

    if not _index or _index_matrix is None or _index_matrix.size == 0:
        return []

    try:
        query_embedding = np.array(embed_text(text), dtype=np.float32)
    except Exception:
        return []

    query_norm = np.linalg.norm(query_embedding)
    if query_norm == 0:
        return []
    query_normalized = query_embedding / query_norm

    similarities = _index_matrix @ query_normalized
    k = min(top_k, len(similarities))
    top_indices = np.argsort(similarities)[-k:][::-1]

    return [
        {
            "task_type": _index_types[i],
            "similarity": float(similarities[i]),
            "prompt": _index[i]["prompt"][:200],
        }
        for i in top_indices
    ]


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
