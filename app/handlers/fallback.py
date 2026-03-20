"""Fallback handler: uses an LLM to generate Tripletex API calls for unknown task types."""
from __future__ import annotations

import json
import logging
import re
from typing import Any

import anthropic

from app.config import ANTHROPIC_API_KEY
from app.handlers import register_handler
from app.tripletex import TripletexClient

logger = logging.getLogger(__name__)

FALLBACK_MODEL = "claude-haiku-4-5-20251001"
MAX_API_CALLS = 10

FALLBACK_SYSTEM_PROMPT = """\
You are a Tripletex API assistant. Given a user's accounting task (in Norwegian or other languages),
generate the exact sequence of Tripletex REST API calls needed to complete the task.

Authentication is already handled — just specify the calls.

Available Tripletex v2 endpoints (all via proxy base URL):

| Endpoint | Methods | Description |
|----------|---------|-------------|
| /employee | GET, POST, PUT | Manage employees |
| /customer | GET, POST, PUT | Manage customers |
| /supplier | GET, POST, PUT | Manage suppliers |
| /product | GET, POST | Manage products |
| /invoice | GET, POST | Create and query invoices |
| /invoice/{id}/:createCreditNote | PUT | Create credit note for invoice |
| /invoice/{id}/:payment | PUT | Register payment on invoice |
| /order | GET, POST, PUT | Manage orders |
| /order/orderline | GET, POST, PUT | Manage order lines |
| /travelExpense | GET, POST, PUT, DELETE | Travel expense reports |
| /travelExpense/cost | GET, POST, PUT, DELETE | Travel expense cost items |
| /project | GET, POST, PUT | Manage projects |
| /department | GET, POST | Manage departments |
| /ledger/account | GET | Query chart of accounts |
| /ledger/posting | GET | Query ledger postings |
| /ledger/voucher | GET, POST, PUT, DELETE | Manage vouchers |
| /salary/type | GET | Salary types |
| /salary/transaction | GET, POST | Salary transactions |
| /salary/payslip | GET, POST | Payslips |
| /salary/settings | GET, PUT | Salary settings |
| /employee/employment | GET, POST, PUT | Employment records (startDate, etc.) |
| /employee/entitlement/:grantEntitlementsByTemplate | PUT | Grant roles (params: employeeId, template=ALL_PRIVILEGES) |
| /currency | GET | Currency codes |
| /activity | GET, POST | Activities |
| /contact | GET, POST, PUT | Contact persons |
| /address | GET, PUT | Addresses |
| /company/salesmodules | POST | Enable modules (e.g. department) |
| /ledger/vatType | GET | VAT type lookup (params: number) |
| /invoice/paymentType | GET | Payment types for invoices |

Key patterns:
- List responses: {"fullResultSize": N, "values": [...]}
- Single entity responses: {"value": {...}}
- Search with query params: GET /customer?name=Acme&fields=id,name
- Create: POST /endpoint with JSON body
- Update: PUT /endpoint/{id} with JSON body
- Action endpoints (with :): use query params, e.g. PUT /invoice/123/:payment?paymentDate=2026-01-01&paymentAmount=1000
- For vouchers, use postings with debit/credit accounts. Look up account IDs: GET /ledger/account?number=1920&fields=id,number
- For invoices: create order first (POST /order with customer id and order lines), then POST /invoice with that order
- Order lines need a product or at least a description and count/unitPriceExcludingVatCurrency
- Employee POST body: {"firstName": "...", "lastName": "...", "email": "..."}
- Customer POST body: {"name": "...", "email": "...", "isCustomer": true}
- Supplier POST body: {"name": "...", "email": "...", "isSupplier": true}
- Department POST body: {"name": "...", "departmentNumber": N}
- Product POST body: {"name": "...", "number": N, "priceExcludingVat": N}
- For travel expenses: POST /travelExpense with {"employee": {"id": EMP_ID}, "title": "...", "date": "YYYY-MM-DD"} then POST /travelExpense/cost
- For salary/payroll: POST /salary/transaction with {"year": YYYY, "month": M, "payslips": [{"employee": {"id": EMP_ID}, "specifications": [{"salaryType": {"id": TYPE_ID}, "rate": AMOUNT, "count": 1, "amount": AMOUNT}]}]}
  - Salary type 2000 = Fastlønn (base salary), 2002 = Bonus. Look up IDs via GET /salary/type?number=2000
  - Employee MUST have an employment record with a division. Check GET /employee/employment?employeeId=ID, create if missing.
  - Do NOT put "date", "year", "month", or "employee" inside payslip or specification — only at the transaction top level (year, month) and payslip (employee).
- Use ?fields=id,name,* to get all fields when searching

Return ONLY a valid JSON array of API calls. Each call is an object:
{"method": "GET|POST|PUT|DELETE", "path": "/endpoint", "body": {...}, "params": {...}, "description": "what this does"}

body and params are optional. Use "params" for query parameters.

If a call depends on a previous call's result, use the placeholder $PREV_N where N is the 0-based
index of the previous call. For example, if call 0 creates a customer and call 1 needs the customer ID:
{"method": "POST", "path": "/order", "body": {"customer": {"id": "$PREV_0.value.id"}, ...}}

Keep it minimal — fewer calls is better. Maximum 10 calls.
"""


def _resolve_placeholder(value: Any, results: list[dict]) -> Any:
    """Resolve $PREV_N.path.to.field placeholders from previous API results."""
    if isinstance(value, str) and value.startswith("$PREV_"):
        try:
            parts = value[6:].split(".", 1)  # "0.value.id" -> ["0", "value.id"]
            idx = int(parts[0])
            if idx < 0 or idx >= len(results):
                logger.warning(f"Placeholder index out of range: {value}")
                return value
            obj = results[idx]
            if len(parts) > 1:
                for key in parts[1].split("."):
                    if isinstance(obj, dict):
                        obj = obj.get(key)
                    elif isinstance(obj, list) and key.isdigit():
                        obj = obj[int(key)]
                    else:
                        logger.warning(f"Cannot resolve path {parts[1]} in result {idx}")
                        return value
            return obj
        except (ValueError, IndexError, TypeError) as e:
            logger.warning(f"Failed to resolve placeholder {value}: {e}")
            return value
    elif isinstance(value, dict):
        return {k: _resolve_placeholder(v, results) for k, v in value.items()}
    elif isinstance(value, list):
        return [_resolve_placeholder(item, results) for item in value]
    return value


def _parse_json_response(raw: str) -> list[dict]:
    """Extract JSON array from LLM response, stripping markdown fences and text."""
    text = raw.strip()

    # Strip markdown fences
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    # Try direct parse first
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            parsed = [parsed]
        if isinstance(parsed, list):
            return parsed
    except json.JSONDecodeError:
        pass

    # Try to find JSON array in the text
    match = re.search(r'\[.*\]', text, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group())
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass

    # Try to find JSON object in the text
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group())
            if isinstance(parsed, dict):
                return [parsed]
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not extract JSON from response: {text[:200]}")


@register_handler("unknown")
async def handle_unknown(client: TripletexClient, fields: dict[str, Any], prompt: str = "") -> dict[str, Any]:
    """Fallback handler that uses an LLM to determine and execute API calls."""
    if not prompt:
        logger.warning("Fallback handler called without prompt, cannot proceed")
        return {"status": "completed", "note": "No prompt provided for fallback"}

    logger.info(f"Fallback handler invoked for prompt: {prompt[:200]}")

    # Step 1: Ask LLM for API call sequence
    try:
        llm_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, timeout=30.0)
        message = llm_client.messages.create(
            model=FALLBACK_MODEL,
            max_tokens=2048,
            system=FALLBACK_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"Task: {prompt}\n\nRespond with ONLY a JSON array. No explanation."}],
        )
        raw_text = message.content[0].text
        logger.info(f"Fallback LLM response: {raw_text[:1000]}")
    except Exception as e:
        logger.error(f"Fallback LLM call failed: {e}")
        return {"status": "completed", "note": f"Fallback LLM error: {e}"}

    # Step 2: Parse API calls
    try:
        api_calls = _parse_json_response(raw_text)
    except (json.JSONDecodeError, ValueError) as e:
        logger.error(f"Failed to parse fallback LLM response: {e}")
        return {"status": "completed", "note": f"Fallback JSON parse error: {e}"}

    if len(api_calls) > MAX_API_CALLS:
        logger.warning(f"LLM returned {len(api_calls)} calls, truncating to {MAX_API_CALLS}")
        api_calls = api_calls[:MAX_API_CALLS]

    # Step 3: Execute API calls sequentially
    results: list[dict] = []
    for i, call in enumerate(api_calls):
        method = call.get("method", "GET").upper()
        path = call.get("path", "")
        body = call.get("body")
        params = call.get("params")
        description = call.get("description", "")

        if not path:
            logger.warning(f"Call {i}: missing path, skipping")
            results.append({"error": "missing path"})
            continue

        # Resolve placeholders from previous results
        if body:
            body = _resolve_placeholder(body, results)
        if params:
            params = _resolve_placeholder(params, results)
        if "$PREV_" in path:
            for match in re.findall(r'\$PREV_\d+(?:\.\w+)*', path):
                resolved = _resolve_placeholder(match, results)
                if resolved is not match:
                    path = path.replace(match, str(resolved))

        logger.info(f"Fallback call {i}/{len(api_calls)}: {method} {path} — {description}")
        if body:
            logger.info(f"  Body: {json.dumps(body, ensure_ascii=False)[:500]}")
        if params:
            logger.info(f"  Params: {params}")

        try:
            if method == "GET":
                resp = await client.get(path, params=params)
            elif method == "POST":
                resp = await client.post(path, payload=body)
            elif method == "PUT":
                resp = await client.put(path, payload=body, params=params)
            elif method == "DELETE":
                resp = await client.delete(path)
            else:
                logger.warning(f"Call {i}: unsupported method {method}")
                results.append({"error": f"unsupported method: {method}"})
                continue

            try:
                resp_data = resp.json()
            except Exception:
                resp_data = {"text": resp.text[:500], "status_code": resp.status_code}

            results.append(resp_data)
            logger.info(f"  Result {i}: status={resp.status_code}")

        except Exception as e:
            logger.error(f"  Call {i} failed: {e}")
            results.append({"error": str(e)})

    return {"status": "completed", "fallback": True, "calls_made": len(results)}
