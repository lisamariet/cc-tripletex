from __future__ import annotations

import json
import logging

from google.cloud import storage

from app.config import GCS_BUCKET

logger = logging.getLogger(__name__)


def save_to_gcs(data: dict, filename: str) -> None:
    try:
        client = storage.Client()
        bucket = client.bucket(GCS_BUCKET)
        blob = bucket.blob(filename)
        blob.upload_from_string(
            json.dumps(data, ensure_ascii=False, indent=2),
            content_type="application/json",
        )
        logger.info(f"Saved to gs://{GCS_BUCKET}/{filename}")
    except Exception as e:
        logger.error(f"Failed to save to GCS: {e}")
