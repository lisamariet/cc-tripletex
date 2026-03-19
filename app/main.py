import json
import logging
import os
from datetime import datetime, timezone

import anthropic
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from google.cloud import storage

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Tripletex AI Accounting Agent")

BUCKET_NAME = os.getenv("GCS_BUCKET", "tripletex-agent-requests")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# System prompt for task parsing
TASK_PARSE_SYSTEM_PROMPT = """You are an accounting task parser for Tripletex (Norwegian accounting software).
You receive a task prompt in one of these languages: Norwegian Bokmål, Norwegian Nynorsk, English, Spanish, Portuguese, German, or French.

Your job is to extract the task type and relevant fields from the prompt and return structured JSON.

Supported task types and their fields:

1. "create_supplier" — Register a new supplier
   Fields: name (string, required), organizationNumber (string), email (string), invoiceEmail (string), phoneNumber (string), isPrivateIndividual (boolean), description (string)

2. "create_customer" — Register a new customer
   Fields: name (string, required), organizationNumber (string), email (string), invoiceEmail (string), phoneNumber (string), isPrivateIndividual (boolean), description (string)

3. "create_employee" — Register a new employee
   Fields: firstName (string, required), lastName (string, required), email (string), phoneNumberMobile (string)

4. "create_product" — Register a new product
   Fields: name (string, required), number (string), priceExcludingVat (number), description (string)

5. "create_invoice" — Create an invoice
   Fields: customerId (int), invoiceDate (string YYYY-MM-DD), dueDate (string YYYY-MM-DD), lines (array of {product, quantity, unitPrice})

6. "unknown" — If you cannot determine the task type

IMPORTANT:
- Extract ALL fields mentioned in the prompt.
- Organization numbers should be strings (preserve leading zeros).
- Return ONLY valid JSON, no explanation text.

Output format:
{
  "taskType": "create_supplier",
  "fields": {
    "name": "...",
    "organizationNumber": "...",
    "email": "..."
  },
  "confidence": 0.95,
  "reasoning": "Brief explanation of what was extracted"
}"""


def save_to_gcs(data: dict, filename: str) -> None:
    try:
        client = storage.Client()
        bucket = client.bucket(BUCKET_NAME)
        blob = bucket.blob(filename)
        blob.upload_from_string(
            json.dumps(data, ensure_ascii=False, indent=2),
            content_type="application/json",
        )
        logger.info(f"Saved request to gs://{BUCKET_NAME}/{filename}")
    except Exception as e:
        logger.error(f"Failed to save to GCS: {e}")


# ---------------------------------------------------------------------------
# Tripletex API helpers
# ---------------------------------------------------------------------------

class TripletexClient:
    """Thin wrapper around the Tripletex REST API."""

    def __init__(self, base_url: str, session_token: str):
        self.base_url = base_url.rstrip("/")
        self.auth = httpx.BasicAuth(username="0", password=session_token)

    async def _request(
        self, method: str, path: str, payload: dict | None = None
    ) -> dict:
        url = f"{self.base_url}{path}"
        logger.info(f"Tripletex API {method} {url}")
        if payload:
            logger.info(f"Payload: {json.dumps(payload, ensure_ascii=False)}")

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(
                method, url, json=payload, auth=self.auth
            )
            logger.info(f"Response status: {response.status_code}")
            logger.info(f"Response body: {response.text[:2000]}")
            response.raise_for_status()
            return response.json()

    async def create_supplier(self, fields: dict) -> dict:
        """POST /supplier — create a new supplier."""
        payload = {"name": fields["name"]}
        if fields.get("organizationNumber"):
            payload["organizationNumber"] = fields["organizationNumber"]
        if fields.get("email"):
            payload["email"] = fields["email"]
        if fields.get("invoiceEmail"):
            payload["invoiceEmail"] = fields["invoiceEmail"]
        if fields.get("phoneNumber"):
            payload["phoneNumber"] = fields["phoneNumber"]
        if fields.get("description"):
            payload["description"] = fields["description"]
        if fields.get("isPrivateIndividual") is not None:
            payload["isPrivateIndividual"] = fields["isPrivateIndividual"]

        result = await self._request("POST", "/supplier", payload)
        return result

    async def get_supplier(self, supplier_id: int) -> dict:
        """GET /supplier/{id} — retrieve supplier by ID."""
        return await self._request("GET", f"/supplier/{supplier_id}")

    async def search_suppliers(self, **params) -> dict:
        """GET /supplier — search suppliers."""
        query = "&".join(f"{k}={v}" for k, v in params.items() if v)
        path = f"/supplier?{query}" if query else "/supplier"
        return await self._request("GET", path)

    async def create_customer(self, fields: dict) -> dict:
        """POST /customer — create a new customer."""
        payload = {"name": fields["name"]}
        if fields.get("organizationNumber"):
            payload["organizationNumber"] = fields["organizationNumber"]
        if fields.get("email"):
            payload["email"] = fields["email"]
        if fields.get("invoiceEmail"):
            payload["invoiceEmail"] = fields["invoiceEmail"]
        if fields.get("phoneNumber"):
            payload["phoneNumber"] = fields["phoneNumber"]
        if fields.get("isPrivateIndividual") is not None:
            payload["isPrivateIndividual"] = fields["isPrivateIndividual"]

        return await self._request("POST", "/customer", payload)

    async def create_product(self, fields: dict) -> dict:
        """POST /product — create a new product."""
        payload = {"name": fields["name"]}
        if fields.get("number"):
            payload["number"] = fields["number"]
        if fields.get("priceExcludingVat") is not None:
            payload["priceExcludingVat"] = fields["priceExcludingVat"]
        if fields.get("description"):
            payload["description"] = fields["description"]

        return await self._request("POST", "/product", payload)


# ---------------------------------------------------------------------------
# LLM task parser
# ---------------------------------------------------------------------------

async def parse_task_with_llm(prompt: str) -> dict:
    """Use Claude to parse an accounting task prompt into structured data."""
    logger.info(f"Parsing task with LLM: {prompt[:200]}")

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        system=TASK_PARSE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )

    raw_text = message.content[0].text
    logger.info(f"LLM raw response: {raw_text}")

    # Strip markdown code fences if present
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    parsed = json.loads(text)
    logger.info(f"Parsed task: {json.dumps(parsed, ensure_ascii=False)}")
    return parsed


# ---------------------------------------------------------------------------
# Task executor
# ---------------------------------------------------------------------------

async def execute_task(parsed: dict, tripletex: TripletexClient) -> dict:
    """Execute a parsed task against the Tripletex API."""
    task_type = parsed.get("taskType", "unknown")
    fields = parsed.get("fields", {})

    if task_type == "create_supplier":
        result = await tripletex.create_supplier(fields)
        supplier_data = result.get("value", {})
        supplier_id = supplier_data.get("id")

        # Verify by reading it back
        if supplier_id:
            verification = await tripletex.get_supplier(supplier_id)
            verified = verification.get("value", {})
            logger.info(
                f"Verified supplier: id={verified.get('id')}, "
                f"name={verified.get('name')}, "
                f"orgNr={verified.get('organizationNumber')}"
            )
            return {
                "status": "completed",
                "taskType": task_type,
                "created": supplier_data,
                "verified": True,
            }

        return {
            "status": "completed",
            "taskType": task_type,
            "created": supplier_data,
            "verified": False,
        }

    elif task_type == "create_customer":
        result = await tripletex.create_customer(fields)
        return {
            "status": "completed",
            "taskType": task_type,
            "created": result.get("value", {}),
        }

    elif task_type == "create_product":
        result = await tripletex.create_product(fields)
        return {
            "status": "completed",
            "taskType": task_type,
            "created": result.get("value", {}),
        }

    else:
        logger.warning(f"Unknown or unsupported task type: {task_type}")
        return {
            "status": "failed",
            "error": f"Unsupported task type: {task_type}",
            "parsed": parsed,
        }


# ---------------------------------------------------------------------------
# FastAPI endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.post("/solve")
async def solve(request: Request):
    body = await request.json()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")

    # Log request summary
    prompt = body.get("prompt", "")
    files = body.get("files", [])
    creds = body.get("tripletex_credentials", {})
    logger.info(f"Received task: {prompt[:100]}...")
    logger.info(f"Files: {len(files)}, Base URL: {creds.get('base_url', 'N/A')}")

    # Save full request to GCS
    log_entry = {
        "timestamp": timestamp,
        "prompt": prompt,
        "files": [
            {
                "filename": f.get("filename"),
                "mime_type": f.get("mime_type"),
                "content_base64": f.get("content_base64"),
            }
            for f in files
        ],
        "tripletex_credentials": {
            "base_url": creds.get("base_url"),
            "session_token": creds.get("session_token"),
        },
    }
    save_to_gcs(log_entry, f"requests/{timestamp}.json")

    # --- Agent logic ---
    try:
        # Step 1: Parse the task with LLM
        parsed = await parse_task_with_llm(prompt)

        # Step 2: Execute against Tripletex API
        base_url = creds.get("base_url", "")
        session_token = creds.get("session_token", "")

        if not base_url or not session_token:
            return JSONResponse(
                {"status": "failed", "error": "Missing Tripletex credentials"},
                status_code=400,
            )

        tripletex = TripletexClient(base_url, session_token)
        result = await execute_task(parsed, tripletex)

        # Save result to GCS
        save_to_gcs(
            {"timestamp": timestamp, "prompt": prompt, "parsed": parsed, "result": result},
            f"results/{timestamp}.json",
        )

        logger.info(f"Task completed: {json.dumps(result, ensure_ascii=False)[:500]}")
        return JSONResponse(result)

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse LLM response: {e}")
        return JSONResponse(
            {"status": "failed", "error": f"LLM response parse error: {str(e)}"},
            status_code=500,
        )
    except httpx.HTTPStatusError as e:
        logger.error(f"Tripletex API error: {e.response.status_code} — {e.response.text}")
        return JSONResponse(
            {
                "status": "failed",
                "error": f"Tripletex API error: {e.response.status_code}",
                "details": e.response.text[:1000],
            },
            status_code=502,
        )
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        return JSONResponse(
            {"status": "failed", "error": str(e)},
            status_code=500,
        )
