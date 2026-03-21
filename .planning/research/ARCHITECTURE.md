# Architecture Research

**Domain:** AI accounting agent — Tripletex API, competition scoring optimization
**Researched:** 2026-03-21
**Confidence:** HIGH (based on direct codebase analysis)

## Standard Architecture

### System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                      HTTP Layer (FastAPI)                        │
│   POST /solve                              GET /health           │
└───────────────────────────┬─────────────────────────────────────┘
                            │ prompt + files + credentials
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Parsing Layer                               │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────────┐  │
│  │ Gemini/Haiku │→ │ Embedding    │→ │ Keyword fallback      │  │
│  │ LLM parser   │  │ similarity   │  │ regex rules (7 langs) │  │
│  └──────────────┘  └──────────────┘  └───────────────────────┘  │
│                     ParsedTask{task_type, fields, confidence}    │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Handler Registry                              │
│  HANDLER_REGISTRY dict — 33 task_type → async function          │
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────────┐    │
│  │ tier1  │ │tier2_* │ │ tier3  │ │ batch_ │ │  fallback  │    │
│  │ 5 hdlr │ │20 hdlr │ │ 8 hdlr │ │ router │ │ LLM escape │    │
│  └────────┘ └────────┘ └────────┘ └────────┘ └────────────┘    │
└───────────────────────────┬─────────────────────────────────────┘
                            │ (client, fields)
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                  TripletexClient Layer                           │
│  ┌───────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │ get_cached()  │  │ post/put     │  │ _preflight_correct() │  │
│  │ in-memory     │  │ _with_retry  │  │ _apply_known_fixes() │  │
│  │ per-request   │  │ 422 fix+1x   │  │ error pattern learn  │  │
│  └───────────────┘  └──────────────┘  └──────────────────────┘  │
│  CallTracker — records every call for scoring analysis           │
└───────────────────────────┬─────────────────────────────────────┘
                            │ httpx async
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│               Tripletex REST API (via proxy)                     │
│   /supplier  /customer  /ledger/voucher  /bank/reconciliation    │
└─────────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│               Persistence / Observability                        │
│  ┌────────────────┐  ┌───────────────┐  ┌──────────────────┐   │
│  │  GCS storage   │  │error_patterns │  │  api_rag (RAG)   │   │
│  │  requests/     │  │.json (112)    │  │  751 doc chunks  │   │
│  │  results/      │  │ atexit flush  │  │  422 fix hints   │   │
│  └────────────────┘  └───────────────┘  └──────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Boundary |
|-----------|----------------|----------|
| `app/main.py` | Request orchestration, always-200 contract | Never let exceptions propagate as HTTP errors |
| `app/parser.py` | task_type + fields extraction from natural language | Outputs ParsedTask only; no API calls |
| `app/handlers/` | Task-specific business logic | Receives (client, fields); returns dict; never writes to GCS |
| `app/tripletex.py` | HTTP + retry + caching + error learning | All Tripletex API calls go through here; no direct httpx elsewhere |
| `app/error_patterns.py` | Persistent pattern memory across deployments | JSON file; loaded once, flushed on atexit |
| `app/call_planner.py` | Documentation of optimal call sequences | Informational only; not enforced at runtime |
| `app/storage.py` | GCS persistence for audit + post-mortem | Fire-and-forget; never blocks response |

---

## Data Flow

### Request Flow

```
POST /solve {prompt, files, credentials}
    │
    ▼
file_processor.py  →  images/PDFs/CSVs → LLM content blocks
    │
    ▼
parser.py  →  Gemini/Haiku LLM call → ParsedTask{task_type, fields, confidence}
    │              if confidence low → keyword fallback rules (7 langs)
    │
    ▼
handlers/__init__.py:execute_task(task_type, client, fields, prompt)
    │   batch_* prefix → loop over items
    │   unknown → fallback handler
    │
    ▼
tier-specific handler(client, fields)
    │   lookup helpers (_lookup_account, _lookup_vat_type)
    │   idempotent checks (GET before POST if entity may exist)
    │   multi-step with budget cap (MAX_API_CALLS guard)
    │
    ▼
TripletexClient.post_with_retry / put_with_retry / get_cached
    │   preflight: remove known-bad fields from error_patterns.json
    │   422 → _apply_known_fixes → 1 retry
    │   record to CallTracker (method, path, status, duration_ms)
    │
    ▼
HTTP 200 {"status": "completed", ...result...}
    │
    ▼
storage.py → GCS results/{timestamp}.json  (non-blocking)
```

### Scoring-Relevant Data Flow

The competition API scores based on:
1. **Correctness** — did the right entities get created/modified?
2. **Efficiency** — fewer API calls = higher bonus (formula: 1 + efficiency_bonus)
3. **Zero 4xx** — each 4xx subtracts from efficiency

```
Score = correctness_factor × tier_multiplier × (1 + efficiency_bonus)

efficiency_bonus = max(0, 1 - (actual_calls / optimal_calls))

Each 4xx error costs: -1 from call count (treated as wasted call)
```

Every path through the system that adds unnecessary GET calls or triggers 422+retry reduces the efficiency bonus.

---

## Architectural Patterns

### Pattern 1: Idempotent-First Handler

**What:** Before creating an entity, check if it already exists. Return the existing ID rather than failing or duplicating.

**When to use:** All Tier 1 and Tier 2 handlers where the sandbox state is unknown. Especially entity types with unique constraints (supplier number, customer number, employee number).

**Trade-offs:** Costs 1 extra GET; saves 1 failed POST + 1 retry POST. Net: -1 call if entity doesn't exist, break-even if it does. The GET should use `get_cached()` to amortize cost across multi-step workflows.

**Example:**
```python
# Instead of: POST → 422 "already in use" → SmartRetry
# Do this:
resp = await client.get_cached("/supplier", params={"organizationNumber": org_nr, "fields": "id"})
values = resp.json().get("values", [])
if values:
    return {"status": "completed", "supplierId": values[0]["id"], "note": "already existed"}
# Now POST without risk of 422
resp = await client.post("/supplier", payload)
```

### Pattern 2: Self-Verification GET

**What:** After a critical POST/PUT, fetch the created/updated entity and verify key fields match what was requested.

**When to use:** Tier 2 and Tier 3 handlers where scoring checks specific field values (invoice amounts, voucher postings, reconciliation state). Do NOT add verification GETs to Tier 1 simple creates — the cost is not worth it.

**Trade-offs:** Costs 1 GET; surfaces field mapping bugs before submission. Adds ~100ms. Only use when the scoring criteria are known to check specific returned values.

**Example:**
```python
resp = await client.post("/ledger/voucher", payload)
voucher = resp.json().get("value", {})
voucher_id = voucher.get("id")

# Self-verify: fetch back and confirm postings balance
verify_resp = await client.get(f"/ledger/voucher/{voucher_id}", params={"fields": "id,postings"})
verify = verify_resp.json().get("value", {})
postings_sum = sum(p.get("amountGross", 0) for p in verify.get("postings", []))
if abs(postings_sum) > 0.01:
    logger.warning(f"Voucher {voucher_id} postings do not balance: sum={postings_sum}")
```

### Pattern 3: Request-Scoped Reference Cache

**What:** Use `client.get_cached()` for all reference data lookups (account IDs, vatType IDs, paymentType IDs, department IDs, period IDs). The cache key is `path?sorted(params)` and lives for the entire request.

**When to use:** Any lookup that may be called multiple times within one handler or across nested helper calls (`_lookup_account`, `_lookup_vat_type`). This is already implemented; the pattern is to consistently use `get_cached` instead of `get`.

**Trade-offs:** Zero cost after first call. Risk: stale data if the entity is created earlier in the same request (e.g., create department then look it up). Solution: invalidate specific cache keys after creates by calling `client._cache.pop(key, None)`.

**Example:**
```python
# _lookup_account already uses get_cached — this is the pattern:
async def _lookup_account(client, account_number):
    resp = await client.get_cached("/ledger/account", params={"number": str(account_number)})
    return resp.json()["values"][0]["id"]

# For vatType (called per posting row in create_voucher):
vat_resp = await client.get_cached("/ledger/vatType", params={"number": "3"})
```

### Pattern 4: Budget-Capped Multi-Step Workflow

**What:** Tier 3 handlers that involve loops (e.g., iterating postings to close) use an explicit API call counter and raise RuntimeError when the budget is exceeded. The handler catches this and returns partial results with `status: "completed"`.

**When to use:** Any handler with variable-length iteration (year_end_closing, correct_ledger_error with multiple errors). Prevents 120s timeout.

**Trade-offs:** May produce partial results. Better than timeout (which scores 0) or uncapped loops.

**Example (already in year_end_closing):**
```python
MAX_API_CALLS = 30
api_calls = 0

def _check_budget():
    nonlocal api_calls
    api_calls += 1
    if api_calls > MAX_API_CALLS:
        raise RuntimeError(f"Exceeded API call budget ({MAX_API_CALLS})")

# Use before every client call in the handler
_check_budget()
resp = await client.get(...)
```

### Pattern 5: Structured Step Results

**What:** Complex handlers append structured dicts to a `result["steps"]` list as they execute. Each step has `{"step": "name", "status": "completed|error|skipped", ...details}`.

**When to use:** All Tier 3 handlers. Enables post-mortem analysis by reading GCS results JSON to understand which step failed.

**Trade-offs:** Minor overhead in building the list. Invaluable for debugging why a task scored 0.

---

## Anti-Patterns

### Anti-Pattern 1: Unconditional GET Before Every POST

**What people do:** Always fetch the existing entity list before creating, even for Tier 1 simple creates.

**Why it's wrong:** Doubles the call count for the common case (empty sandbox). Tier 1 scoring formula: 1 optimal call → any extra GET halves efficiency bonus.

**Do this instead:** Only add pre-check GETs when:
- The handler has previously failed with "already in use" (check error_patterns.json)
- The task description implies idempotency ("ensure X exists")
- You are in a multi-step T3 workflow where the entity was created earlier in the same run

### Anti-Pattern 2: Ignoring the 422 Retry in Efficiency Count

**What people do:** Write a handler that intentionally sends an incomplete payload, expecting SmartRetry to fix it.

**Why it's wrong:** `post_with_retry` counts as 2 API calls: the failing POST + the retry POST. Each 422 response is also recorded as an error in CallTracker. Relying on retry is a design smell — it means the handler has incorrect field mapping.

**Do this instead:** Fix the field mapping in the handler directly. Use error_patterns.json as a signal (if a field consistently causes 422, remove it from the payload statically). The retry mechanism is a safety net, not a design tool.

### Anti-Pattern 3: Using BETA Endpoints in Production Handlers

**What people do:** See an endpoint in docs or RAG, use it because it looks relevant.

**Why it's wrong:** BETA endpoints return 403 in the competition sandbox. A 403 wastes a call and scores negatively.

**Do this instead:** Before using any new endpoint, check error_patterns.json for 403 entries. Known BETA: `/ledger/voucher/openingBalance` (used by year_end_closing with known risk, flagged in comments). When a BETA endpoint is necessary, wrap it in a conditional block and handle 403 gracefully without retrying.

### Anti-Pattern 4: LLM Call Inside a Handler

**What people do:** Use an LLM within a handler to decide field values or resolve ambiguities.

**Why it's wrong:** Adds 500-2000ms latency per handler, is non-deterministic, and counts against the 120s timeout. The fallback handler does this intentionally, but only as a last resort.

**Do this instead:** All field resolution logic belongs in the parser. If a handler receives `fields` that are ambiguous, return a structured error with a specific message. Improve the parser's prompt or keyword rules to extract the field correctly before the handler runs.

### Anti-Pattern 5: Swallowing the Error Body

**What people do:** On 4xx, log `resp.status_code` and continue silently.

**Why it's wrong:** The error body (validationMessages, message field) contains the exact field name and reason for failure. Without it, debugging a zero-score submission requires re-running the task in debug mode.

**Do this instead:** Always parse and log the full error body on 4xx. Include it in the handler's return dict under `"validationMessages"` or `"errorMessage"`. This data surfaces in GCS results and the `gsd errors` CLI tool.

---

## How to Add Self-Verification Without Blowing the Call Budget

The key constraint: each verification GET costs 1 call and reduces efficiency bonus if the optimal sequence does not include it.

**Decision rule:**
- Add verification GET only if the scoring system verifies a non-trivial derived field (e.g., posting balance, reconciliation match count, closing balance after update)
- Do NOT add verification GET for Tier 1 creates (POST → return; the POST response body already contains the created entity)
- For Tier 2 invoice: the response from `POST /invoice` contains the full invoice object. Use `resp.json().get("value", {})` directly — no extra GET needed
- For Tier 3 voucher: the `POST /ledger/voucher` response contains the voucher with postings. Read it from the POST response, not a subsequent GET

**Verification that IS worth the call:**
- bank_reconciliation: GET `/bank/reconciliation/match/count` after suggest — counts matches (already implemented, and the count is the scoreable outcome)
- year_end_closing: GET `/ledger/annualAccount` at end — verifies the close registered correctly
- correct_ledger_error: GET `/ledger/voucher/{id}` to confirm reversal succeeded before re-posting

---

## Caching Architecture

### Current State

`TripletexClient._cache` is a `dict[str, httpx.Response]` populated by `get_cached()`. Cache key is `f"{path}?{sorted(params.items())}"`. Lifetime: one request (client instance is created per `/solve` call).

### What Should Be Cached

| Lookup | Cache key | Why cached |
|--------|-----------|------------|
| Account ID by number | `/ledger/account?number=1920` | Called per posting row in voucher handlers |
| VAT type ID | `/ledger/vatType?number=3` | Called per revenue posting in create_voucher |
| Accounting period | `/ledger/accountingPeriod?...` | Called once per T3 handler, but same result |
| Department ID | `/department?count=1` | Used in create_employee lookup |
| Currency ID | `/currency?code=NOK` | Used by invoice handlers |

### What Should NOT Be Cached

| Lookup | Reason |
|--------|--------|
| Entity lists after creates | Cache will be stale if the entity was just created |
| Reconciliation state | Mutable within the same request (match count changes after suggest) |
| Voucher data | May be reversed/deleted within the same request |

### Proposed Extension: Cache Invalidation Helper

The current cache has no invalidation. Add a helper to TripletexClient:

```python
def invalidate_cache(self, path_prefix: str) -> int:
    """Remove all cache entries whose key starts with path_prefix. Returns count removed."""
    keys_to_remove = [k for k in self._cache if k.startswith(path_prefix)]
    for k in keys_to_remove:
        del self._cache[k]
    return len(keys_to_remove)
```

Call after creating an entity that will be looked up in the same request (e.g., after creating a department, invalidate `/department`).

---

## Error Recovery Patterns for Tier 3 Multi-Step Workflows

### Current Recovery Architecture

```
Step N fails
    │
    ├─ 422 → TripletexClient._apply_known_fixes() → 1 retry
    │         Still fails → log warning, continue to Step N+1
    │
    ├─ 403 → NOT retried (explicit check in post_with_retry)
    │         Log and continue
    │
    ├─ Budget exceeded → raise RuntimeError
    │         Caught by handler, result["status"] = "completed" with partial steps
    │
    └─ Exception → caught at main.py level, return {"status": "completed", "error": "..."}
```

### Recommended Pattern: Step-Result Accumulation With Fallback Escalation

For Tier 3 handlers, the current architecture is sound. The key improvement is making recovery decisions explicit instead of always continuing:

```python
# Pattern: escalating fallback strategy per step
step_result = await _try_primary_approach(client, ...)
if step_result["status"] == "error":
    step_result = await _try_fallback_approach(client, ...)
    if step_result["status"] == "error":
        result["steps"].append({**step_result, "note": "all strategies failed, skipping"})
        # Continue to next step — partial is better than 0
    else:
        result["steps"].append({**step_result, "note": "fallback succeeded"})
else:
    result["steps"].append(step_result)
```

This pattern is partially implemented in bank_reconciliation (tries `/bank/reconciliation` then falls back to `/>last`). It should be standardized.

### Recovery Table by Handler

| Handler | Current Recovery | Gap |
|---------|-----------------|-----|
| create_voucher | None — fails on first bad posting | Add: skip invalid postings, post rest |
| bank_reconciliation | Falls back to `/>last` if POST fails | Good — but match/count may 404; handle gracefully |
| year_end_closing | Budget cap + RuntimeError catch | BETA opening balance endpoint 403 is handled; good |
| correct_ledger_error | Per-error try/except; continues on failure | Good structure |
| monthly_closing | Depends on implementation | Verify step-by-step accumulation exists |

---

## Submission Log Analysis Architecture

### How to Find Why a Task Scored 0

The scoring system gives 0 when either:
1. The required entity was not created/modified at all
2. The created entity has wrong field values
3. The handler returned an error that prevented all useful API calls

**Diagnostic path using existing tooling:**

```
gsd errors                    →  Show 4xx errors from error_patterns.json
gsd show {task_id}            →  Show result JSON for specific submission
  result.json:
    .tracker.calls[]          →  Every API call: method, path, status, error_body
    .result.steps[]           →  Step-by-step T3 results
    .result.note              →  Parser inference note
    .parsed_task.task_type    →  Was the task correctly identified?
    .parsed_task.confidence   →  Parsing confidence (low = wrong handler)
```

**Common zero-score root causes to check first:**

| Symptom in result.json | Root cause | Fix location |
|------------------------|------------|--------------|
| `task_type: "unknown"` | Parser failed to identify | Add keyword rule in `parser.py:_KEYWORD_RULES` |
| `task_type: "wrong_type"` | Parser misidentified | Improve LLM prompt or embedding threshold |
| All calls return 4xx | Wrong endpoint or BETA | Remove endpoint from handler |
| POST returns 201 but scoring 0 | Wrong field value sent | Check field extraction in parser or handler |
| `steps[].status: "error"` | Step failed silently | Check `steps[].message` for exact API error |
| 0 API calls in tracker | Handler raised exception before first call | Check `result.error` field |

### Proposed: Zero-Score Analyzer Script

A `scripts/analyze_zero_scores.py` script that:
1. Reads all GCS results where score context indicates 0 (no competition score stored, but can infer from missing entities)
2. Groups by task_type and error pattern
3. Outputs a prioritized list of root causes

Not yet implemented. The quickest equivalent is: `gsd show {task_id}` + manual inspection of `tracker.calls`.

---

## Component Boundaries (Build Order Implications)

For the current optimization milestone, build order matters because some components depend on others being correct first:

```
1. Parser accuracy
   └─ Must be correct before handler fixes matter
   └─ Fix: add keyword rules, test with E2E before handler changes

2. Field extraction correctness
   └─ Parser outputs fields; handler uses them
   └─ If field is missing/wrong, no amount of handler logic helps

3. Handler call sequence
   └─ Depends on correct fields from step 2
   └─ Add idempotent checks, fix endpoint paths, correct field names

4. Self-verification GETs
   └─ Add only after handler is functionally correct
   └─ Verification adds value only if the entity was correctly created

5. Cache optimization
   └─ Add after handler is correct and verified
   └─ Pure efficiency improvement, does not affect correctness
```

**Do not optimize efficiency before correctness.** A handler that creates the wrong entity with 3 calls scores lower than one that creates the right entity with 6 calls.

---

## Integration Points

### External Services

| Service | Integration Pattern | Constraints |
|---------|---------------------|-------------|
| Tripletex REST API (via proxy) | httpx AsyncClient, BasicAuth(0, token) | 120s timeout, new token per submission, avoid 403 BETA |
| Vertex AI (Gemini parser) | REST API via `parser_gemini.py` | Gemini 2.0 Flash, max 8192 output tokens |
| Anthropic Claude (Haiku fallback) | `anthropic` SDK async | Used as parser fallback and fallback handler |
| Google Cloud Storage | `google-cloud-storage` SDK | Non-blocking uploads, fire-and-forget |

### Internal Boundaries

| Boundary | Communication | Constraint |
|----------|---------------|------------|
| parser → handler | `ParsedTask.fields` dict | No API calls allowed in parser |
| handler → TripletexClient | `(client, fields)` function args | All HTTP through client; no direct httpx |
| TripletexClient → error_patterns | Module-level import | Non-blocking; failure must not affect requests |
| main → storage | Async fire-and-forget | Never block response on GCS write |
| handlers → handlers | Not allowed | Handlers do not call other handlers; extract shared logic to `_helper` functions |

---

## Sources

- Direct codebase analysis: `app/tripletex.py`, `app/handlers/tier3.py`, `app/handlers/__init__.py`, `app/parser.py`, `app/call_planner.py`
- Project context: `.planning/PROJECT.md`
- Existing architecture doc: `.planning/codebase/ARCHITECTURE.md`
- Confidence: HIGH — all claims derived from code, not assumptions

---
*Architecture research for: Tripletex AI accounting agent optimization*
*Researched: 2026-03-21*
