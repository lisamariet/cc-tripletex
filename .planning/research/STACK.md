# Stack Research

**Domain:** Tripletex AI Accounting Agent — NM i AI 2026 competition
**Researched:** 2026-03-21
**Confidence:** HIGH (production codebase analyzed directly; API docs verified from official endpoint list)

## Context: This Is a Brownfield Optimization, Not a Greenfield Build

The stack is already deployed and working. This research documents what to keep, what to add, and what patterns to use for Tier 3 optimization. The goal is not to change the stack — it is to use the existing stack better and fill specific gaps that affect scoring.

---

## Current Stack (Keep As-Is)

These choices are correct. Changing them wastes time.

### Core Technologies

| Technology | Version | Purpose | Why Correct |
|------------|---------|---------|-------------|
| Python 3.12 | 3.12-slim (Docker) | Primary runtime | Async-native, fast startup on Cloud Run, best httpx/asyncio support |
| FastAPI | 0.115.6 | `/solve` endpoint | Zero-overhead async request handling; 120s timeout fits within 5-min competition limit |
| httpx | 0.27.0+ | Async HTTP client | True asyncio support (unlike `requests`); single `AsyncClient` instance enables connection pooling across all Tripletex calls in one request |
| Gemini 2.5-flash | latest via Vertex AI | Task parser (default) | Multimodal — handles PDF/CSV files natively without separate extraction step; 8192 output tokens sufficient |
| Claude Haiku | claude-haiku-4-5-20251001 | Fallback parser | Reliable fallback; claude_sdk handles retries automatically |
| Vertex AI text-embedding-005 | via google-cloud-aiplatform | Embedding classifier | 768-dim cosine similarity; ~10ms first-pass filter before expensive LLM call |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pydantic | 2.0+ | ParsedTask / CallTracker models | Always — prevents silent field errors in API payloads |
| numpy | 1.24.0+ | Cosine similarity for embeddings | Always — faster than pure Python for 768-dim dot products |
| google-cloud-storage | 2.19.0 | GCS logging | Always — needed for error analysis between submissions |
| python-dotenv | 1.0.1 | `.env` loading | Local dev only; Cloud Run uses env vars directly |

---

## Gaps to Fill — What to Add for Tier 3 Scoring

These are the specific tools and patterns that affect score. Prioritized by impact.

### 1. asyncio.gather() for Parallel Reference Lookups

**Gap:** The codebase has NO asyncio parallelism. Every API call is sequential.
**Impact:** Efficiency bonus requires fewer calls and faster execution. Parallel independent GETs cut wall time.
**Confidence:** HIGH — httpx.AsyncClient is already in place, asyncio is already available.

**Pattern to implement:**

```python
import asyncio

# Instead of sequential:
account_id = await _lookup_account(client, 1920)
period_id = await _get_accounting_period(client)
vat_types = await _get_vat_types(client)

# Use parallel gather:
account_id, period_id, vat_types = await asyncio.gather(
    _lookup_account(client, 1920),
    _get_accounting_period(client),
    _get_vat_types(client),
)
```

**Where to apply first:**
- `bank_reconciliation` handler: account lookup + period lookup can run in parallel
- `year_end_closing` handler: period lookup + closeGroup lookup can run in parallel
- `create_voucher` with multiple postings: all `_lookup_account()` calls can be parallelized

**Constraint:** Keep within the single shared `AsyncClient` instance — httpx connection pooling handles concurrency safely. Do NOT create new `AsyncClient` instances per call.

### 2. `?fields=` Projection on All GET Calls

**Gap:** Most GET calls omit `?fields=`, causing Tripletex to return full objects with 20-40 fields when only 1-2 are needed.
**Impact:** Reduces response size, slightly faster, and avoids parsing overhead. More importantly: matches "minimal API calls" scoring.
**Confidence:** HIGH — documented in `docs/04-examples.md` ("Use `?fields=*` to see all available fields").

**Pattern:**

```python
# Instead of:
resp = await client.get("/ledger/account", params={"number": str(account_number)})

# Use:
resp = await client.get("/ledger/account", params={
    "number": str(account_number),
    "fields": "id,number,name",
})
```

**Apply to all reference-data GETs:** vatType, paymentType, costCategory, department, accountingPeriod, employee, customer, supplier.

### 3. In-Memory Cache for Reference Data (Already Exists — Expand Usage)

**Gap:** `TripletexClient._cache` and `get_cached()` exist but are not used consistently. Handlers call `client.get()` directly for reference data instead of `client.get_cached()`.
**Impact:** Every extra GET on a reference endpoint that was already fetched = wasted efficiency score.
**Confidence:** HIGH — `get_cached()` is implemented and correct; just not called from all handlers.

**Reference endpoints that MUST use `get_cached()`:**
- `GET /ledger/vatType` — fetched multiple times per voucher with multiple postings
- `GET /travelExpense/paymentType` — same payment type used for all expenses
- `GET /travelExpense/costCategory` — same categories referenced across cost lines
- `GET /bank/reconciliation/paymentType` — reconciliation type lookup
- `GET /ledger/account` (by number) — account 1920 looked up in both reconciliation and voucher handlers
- `GET /ledger/accountingPeriod` — fetched in reconciliation and year-end closing

### 4. CSV Parsing for Bank Statement Import

**Gap:** `file_processor.py` parses CSV with stdlib `csv` module into text and passes it to the LLM. For Tier 3 bank reconciliation, the CSV needs to be parsed into structured transaction objects — not LLM-interpreted text.
**Confidence:** HIGH — stdlib `csv` is already imported and correct for simple parsing. No new library needed.

**What is needed is a parser function, not a new library:**

```python
import csv
import io
import base64

def parse_bank_statement_csv(content_b64: str) -> list[dict]:
    """Parse bank statement CSV into transaction dicts.

    Handles common Norwegian bank CSV formats:
    - Column order variants (date, description, amount / date, amount, description)
    - Semicolon and comma delimiters
    - Norwegian decimal comma (1.234,56 -> 1234.56)
    - Negative amounts for debits
    """
    raw = base64.b64decode(content_b64).decode("utf-8-sig")  # utf-8-sig strips BOM

    # Detect delimiter
    delimiter = ";" if raw.count(";") > raw.count(",") else ","

    reader = csv.DictReader(io.StringIO(raw), delimiter=delimiter)
    transactions = []
    for row in reader:
        # Normalize field names (case-insensitive)
        normalized = {k.lower().strip(): v.strip() for k, v in row.items()}

        # Extract date, description, amount with Norwegian number format handling
        amount_str = (
            normalized.get("beløp") or normalized.get("amount") or
            normalized.get("belop") or "0"
        )
        # Norwegian decimal: "1.234,56" -> "1234.56"
        amount_str = amount_str.replace(".", "").replace(",", ".")

        transactions.append({
            "date": normalized.get("dato") or normalized.get("date", ""),
            "description": normalized.get("beskrivelse") or normalized.get("description", ""),
            "amount": float(amount_str) if amount_str else 0.0,
        })
    return transactions
```

**Do NOT add pandas** — pandas adds 50MB+ to the Docker image for a use case that stdlib `csv` handles correctly.

### 5. PDF Extraction for Supplier Invoice Handling

**Gap:** Current approach sends PDF as base64 directly to Gemini (multimodal). This works but depends on LLM accuracy for field extraction.
**Confidence:** MEDIUM — Gemini 2.5-flash multimodal is reliable for structured invoice PDFs. Stdlib approach is correct.

**Decision: Keep using Gemini multimodal for PDF.** Rationale:
- `POST /ledger/voucher/importDocument` exists (non-BETA) — can upload PDF directly to Tripletex and let Tripletex parse it. This is worth testing for supplier invoices.
- For `create_invoice_from_pdf`: Gemini extraction + handler is already working.
- Adding `pdfplumber` or `pypdf2` would add dependencies and complexity without guaranteed improvement over Gemini multimodal.

**Exception:** If `POST /ledger/voucher/importDocument` is tested and returns a parsed voucher, use that endpoint. It accepts multipart form with PDF and returns voucher — avoids LLM extraction entirely.

---

## Tripletex API Patterns — What to Do and What Not to Do

### Correct Pattern: POST Without Preceding GET (Fresh Sandbox)

Every submission runs against a fresh empty sandbox. The most common source of wasted API calls is GETting entities before creating them.

**Wrong (2+ calls):**
```python
# Search for existing customer first
resp = await client.get("/customer", params={"name": customer_name})
customers = resp.json().get("values", [])
if not customers:
    resp = await client.post("/customer", {"name": customer_name, ...})
customer_id = resp.json()["value"]["id"]
```

**Correct (1 call):**
```python
# Fresh sandbox = always POST directly
resp = await client.post("/customer", {"name": customer_name, ...})
customer_id = resp.json()["value"]["id"]
```

**Exception:** Only GET first when the task prompt explicitly says to update/find an existing entity.

### Correct Pattern: Self-Verification After POST

The efficiency bonus applies when correctness = 1.0. After critical POSTs (employee with role, invoice with specific fields), do ONE GET to verify key fields were saved.

```python
resp = await client.post("/employee", payload)
employee_id = resp.json()["value"]["id"]

# Verify role was set correctly (roles are often silently dropped)
verify = await client.get(f"/employee/{employee_id}", params={"fields": "id,firstName,lastName"})
# If mismatch: PUT to correct
```

**Only verify fields the scoring system checks.** Do not verify every field — that wastes calls.

### Correct Pattern: `?count=` to Prevent Pagination Loops

Default Tripletex `count` is 10. Reference data fetches (vatType, paymentType) must use explicit count to avoid missing entries.

```python
resp = await client.get_cached("/ledger/vatType", params={
    "count": "100",  # Always explicit
    "fields": "id,number,name,percentage",
})
```

### Correct Pattern: Bank Statement CSV Upload via Multipart

For `bank_reconciliation` with a CSV file attachment:

```python
import httpx

async def upload_bank_statement(client: TripletexClient, account_id: int, csv_bytes: bytes) -> dict:
    """Upload CSV bank statement via multipart to /bank/statement/import."""
    url = f"{client.base_url}/bank/statement/import"
    files = {"file": ("statement.csv", csv_bytes, "text/csv")}
    data = {"accountId": str(account_id), "uploadDate": today}

    # Note: TripletexClient._client is the underlying httpx.AsyncClient
    resp = await client._client.post(
        url,
        files=files,
        data=data,
    )
    return resp.json()
```

**IMPORTANT:** `/bank/statement/import` accepts multipart, NOT JSON. The existing `client.post()` sends JSON. Use `client._client.post()` directly with `files=` parameter for this call.

### Correct Pattern: Year-End Closing API Sequence

Based on API endpoint analysis, the correct sequence for `year_end_closing` is:

1. `GET /ledger/accountingPeriod` — find periods for the year
2. `GET /ledger/closeGroup` — find close groups (equity accounts, result accounts)
3. `PUT /ledger/posting/:closePostings` — close open postings in batch (NOT per-posting)
4. `POST /ledger/voucher/openingBalance` [BETA — but needed] — create next year opening balance
5. `GET /ledger/annualAccount` — verify annual account state

**The openingBalance endpoint is marked BETA.** It has been observed to work in sandbox. Use it but wrap in try/except and fall back gracefully if it returns 403.

### Correct Pattern: Voucher Row Numbering

Tripletex voucher postings have a `row` field. Row 0 is system-reserved for VAT. Rows must be >= 1 and unique within the voucher.

```python
# Correct row assignment
for idx, posting in enumerate(postings):
    posting["row"] = idx + 1  # Start at 1, not 0
```

The current `create_voucher` handler already does this correctly. Preserve this logic.

---

## BETA Endpoint Policy

| Endpoint | BETA? | Action |
|----------|-------|--------|
| `POST /ledger/voucher/openingBalance` | BETA | Use — necessary for year-end closing; wrap in try/except |
| `PUT /ledger/voucher/historical/:closePostings` | BETA | Avoid — standard `PUT /ledger/posting/:closePostings` is non-BETA |
| `GET /company/salesmodules` | BETA | Avoid — 403 in sandbox |
| `POST /customer/list` | BETA | Avoid — use single `POST /customer` instead |
| `DELETE /customer/{id}` | BETA | Avoid — 403 confirmed |
| `PUT /project/{id}` | BETA | Avoid — use with caution; test against sandbox first |
| `incomingInvoice/*` | BETA | Avoid — all endpoints BETA, 403 likely |
| `ledger/paymentTypeOut/*` | BETA | Avoid — use `invoice/paymentType` and `bank/reconciliation/paymentType` |

**Rule:** If an endpoint is marked [BETA] in `docs/06-tripletex-api-endpoints.md`, assume 403. Only use if sandbox E2E confirms it works.

---

## Alternatives Considered

| Recommended | Alternative | Why Not |
|-------------|-------------|---------|
| stdlib `csv` for bank CSVs | pandas | pandas adds 50MB+ Docker image bloat, 200ms import time; stdlib csv handles all needed formats |
| asyncio.gather() for parallel calls | trio / anyio TaskGroup | gather() is sufficient for 3-5 parallel calls; TaskGroup adds dependency with no benefit at this scale |
| Gemini multimodal for PDF | pdfplumber + text extraction | Gemini handles layout-aware extraction better for varied invoice formats; no added dependency |
| `client.get_cached()` for reference data | Redis / external cache | Fresh sandbox per submission means no cross-request caching needed; in-memory is optimal |
| Direct `POST` in fresh sandbox | `GET` then `POST` | Saves 1 API call per entity = direct efficiency score improvement |
| `POST /ledger/voucher/importDocument` for PDFs | Manual field mapping | Let Tripletex parse the PDF natively when possible — zero LLM extraction error risk |

---

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| `requests` library | Sync-only, blocks FastAPI worker thread | `httpx.AsyncClient` (already in use) |
| `asyncio.to_thread()` for Tripletex calls | Already async — wrapping in to_thread adds unnecessary overhead | Direct `await client.get/post/put()` |
| Multiple `AsyncClient` instances per request | Destroys connection pooling; each new client = new TCP handshake | Single shared `TripletexClient._client` passed through handlers |
| `asyncio.sleep()` for rate limiting | Wastes precious 120s timeout budget | Rely on httpx connection pooling; Tripletex sandbox has no rate limits |
| `?fields=*` in GET calls | Returns all fields including heavy nested objects | Specify only needed fields: `?fields=id,name,email` |
| Retrying 403 errors | 403 = token/permission/BETA endpoint, retry is futile | Log and return error immediately; never retry 403 |
| Catching all exceptions in handlers | Silent failures produce partial results that score lower than a clear error | Let exceptions propagate to handler wrapper, return structured error |

---

## asyncio Parallel Patterns — Concrete Implementation

### Pattern A: Parallel Reference Data Fetch (use in handlers)

```python
import asyncio

async def bank_reconciliation(client, fields):
    # These are independent — run in parallel
    account_id_task = _lookup_account(client, fields.get("accountNumber", 1920))
    period_task = _get_current_period(client)

    account_id, current_period_id = await asyncio.gather(
        account_id_task,
        period_task,
    )
    # Continue with both results...
```

### Pattern B: Parallel Account Lookups for Multi-Posting Vouchers

```python
async def create_voucher(client, fields):
    postings_input = fields.get("postings", [])

    # Collect all unique account numbers
    account_numbers = set()
    for p in postings_input:
        if p.get("debitAccount"):
            account_numbers.add(int(p["debitAccount"]))
        if p.get("creditAccount"):
            account_numbers.add(int(p["creditAccount"]))

    # Look up all accounts in parallel
    account_ids = await asyncio.gather(
        *[_lookup_account(client, n) for n in account_numbers]
    )
    account_map = dict(zip(account_numbers, account_ids))

    # Build postings using account_map instead of individual awaits
    postings = []
    for idx, p in enumerate(postings_input):
        if p.get("debitAccount"):
            postings.append({
                "account": {"id": account_map[int(p["debitAccount"])]},
                "amountGross": p["amount"],
                "amountGrossCurrency": p["amount"],
                "row": idx + 1,
            })
        # ...
```

**Speedup estimate:** 3 account lookups sequential = ~300ms. Parallel = ~100ms. On a 10-posting voucher with 20 unique accounts: saves ~1.9s within the 120s budget.

---

## Stack Patterns by Task Type

**Tier 3 — bank_reconciliation:**
- Parallel: account lookup + period lookup
- Use `get_cached()` for reconciliation paymentType
- Upload CSV via multipart to `/bank/statement/import` (not JSON)
- Run `/bank/reconciliation/match/:suggest` once — do not loop

**Tier 3 — year_end_closing:**
- Parallel: accountingPeriod lookup + annualAccount lookup
- Use `PUT /ledger/posting/:closePostings` in ONE batch call, not per-posting
- `POST /ledger/voucher/openingBalance` is BETA but works in sandbox — wrap in try/except

**Tier 3 — correct_ledger_error:**
- Fetch voucher with `?fields=id,date,postings,description`
- Correct via `PUT /ledger/voucher/{id}` (not DELETE + POST — preserves voucher number)
- Verify via GET after PUT — this task's scoring checks specific fields

**Tier 3 — monthly_closing:**
- Parallel: accountingPeriod + closeGroup fetch
- Close via `PUT /ledger/posting/:closePostings` scoped to month
- Do not attempt to close future periods — Tripletex rejects with 422

**Tier 2 — any task in fresh sandbox:**
- POST directly without preceding GET
- Exception: update/delete tasks where entity must be found first

---

## Version Compatibility

| Package | Pinned Version | Compatible With | Notes |
|---------|---------------|-----------------|-------|
| fastapi==0.115.6 | pydantic>=2.0 | Pydantic v1 would break | Do not downgrade pydantic |
| httpx>=0.27.0 | asyncio (Python 3.12) | Works with TaskGroup if ever needed | asyncio.gather() is sufficient |
| google-cloud-aiplatform>=1.38.0 | Python 3.12 | Known to work | No version constraints observed |
| anthropic>=0.40.0 | Python 3.12 | Works with claude-haiku-4-5-20251001 | Model IDs are separate from SDK version |

---

## Sources

- `/app/tripletex.py` — Existing `TripletexClient` implementation analyzed directly; `get_cached()` confirmed present and correct
- `/app/handlers/tier3.py` — Existing Tier 3 handlers; bank_reconciliation, year_end_closing patterns documented
- `/app/file_processor.py` — Current CSV/PDF handling via stdlib csv + Gemini multimodal
- `/docs/06-tripletex-api-endpoints.md` — Official endpoint list from competition; BETA markers documented per endpoint
- `/docs/03-scoring.md` — Scoring formula: correctness × tier × (1 + efficiency_bonus); efficiency requires 1.0 correctness
- `/docs/04-examples.md` — Official Tripletex API usage examples; `?fields=` tip confirmed
- WebSearch: [HTTPX async patterns](https://www.python-httpx.org/async/) — asyncio.gather() with shared AsyncClient confirmed correct
- WebSearch: [asyncio TaskGroup vs gather](https://dev.to/dentedlogic/what-modern-python-uses-for-async-api-calls-httpx-taskgroups-3e4e) — gather() sufficient for 3-5 concurrent calls (MEDIUM confidence)

---

*Stack research for: Tripletex AI Accounting Agent optimization (Tier 3 + efficiency)*
*Researched: 2026-03-21*
