import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import API_KEY
from app.parser import parse_task
from app.storage import save_to_gcs
from app.tripletex import TripletexClient
from app.handlers import execute_task

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Cloud Run revision — set automatically by Cloud Run (e.g. "tripletex-agent-00125-jvn")
REVISION = os.getenv("K_REVISION", "local")

app = FastAPI(title="Tripletex AI Accounting Agent")


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.post("/solve")
async def solve(request: Request):
    # API key verification — if API_KEY is set, require Bearer token
    if API_KEY:
        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Bearer ") or auth_header[7:] != API_KEY:
            logger.warning("Unauthorized request — invalid or missing API key")
            return JSONResponse({"status": "completed"}, status_code=200)

    t0 = time.monotonic()
    body = await request.json()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")

    prompt = body.get("prompt", "")
    files = body.get("files", [])
    creds = body.get("tripletex_credentials", {})
    base_url = creds.get("base_url", "")
    session_token = creds.get("session_token", "")

    # Capture any extra fields from the competition API (e.g. submission_id, task_id)
    extra_fields = {k: v for k, v in body.items()
                    if k not in ("prompt", "files", "tripletex_credentials")}
    if extra_fields:
        logger.info(f"Extra request fields: {list(extra_fields.keys())}")

    logger.info(f"Received task: {prompt[:100]}...")
    logger.info(f"Files: {len(files)}, Base URL: {base_url}")

    # Save full request to GCS (with full session token)
    save_to_gcs(
        {
            "timestamp": timestamp,
            "revision": REVISION,
            **extra_fields,
            "prompt": prompt,
            "files": [
                {"filename": f.get("filename"), "mime_type": f.get("mime_type"),
                 "content_base64": f.get("content_base64")}
                for f in files
            ],
            "tripletex_credentials": {
                "base_url": base_url,
                "session_token": session_token,
            },
        },
        f"requests/{timestamp}.json",
    )

    # --- Orchestration: parse → execute → respond ---
    # ALWAYS return 200 with {"status": "completed"}
    parsed_task = None
    result = {"status": "completed"}
    client = None

    try:
        # Step 1: Parse with LLM
        parsed_task = parse_task(prompt, files)

        # Step 2: Execute deterministic handler
        if not base_url or not session_token:
            logger.error("Missing Tripletex credentials")
            result["note"] = "Missing credentials"
        else:
            client = TripletexClient(base_url, session_token, debug=True)
            # Inject raw files into fields so handlers can access attachments directly
            if files:
                parsed_task.fields["_raw_files"] = files
            try:
                result = await asyncio.wait_for(
                    execute_task(parsed_task.task_type, client, parsed_task.fields, prompt=prompt),
                    timeout=240.0
                )
            except asyncio.TimeoutError:
                logger.warning(f"Handler timed out after 90s: {parsed_task.task_type}")
                result = {"status": "completed", "note": "Handler timed out — partial result"}
            # Ensure status is always "completed"
            result["status"] = "completed"

    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        result = {"status": "completed", "error": str(e)}

    finally:
        if client:
            tracker_data = client.tracker.to_dict()
            await client.close()
        else:
            tracker_data = []

    total_ms = (time.monotonic() - t0) * 1000

    # Save result + call tracking to GCS
    save_to_gcs(
        {
            "timestamp": timestamp,
            "revision": REVISION,
            "prompt": prompt,
            "parsed_task": {
                "task_type": parsed_task.task_type,
                "fields": parsed_task.fields,
                "confidence": parsed_task.confidence,
            } if parsed_task else None,
            "api_calls": tracker_data,
            "total_calls": len(tracker_data),
            "error_count_4xx": sum(1 for c in tracker_data if 400 <= c.get("status", 0) < 500),
            "total_duration_ms": round(total_ms, 1),
            "result": result,
        },
        f"results/{timestamp}.json",
    )

    # Include revision in response for traceability
    result["revision"] = REVISION

    logger.info(f"Done in {total_ms:.0f}ms: {json.dumps(result, ensure_ascii=False)[:500]}")
    return JSONResponse(result, status_code=200)
