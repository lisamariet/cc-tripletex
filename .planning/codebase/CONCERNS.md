# Codebase Concerns

**Analysis Date:** 2026-03-21

## Tech Debt

**BETA Endpoint Exposure:**
- Issue: Several handlers reference BETA endpoints that return 403 Forbidden in production
- Files: `app/handlers/fallback.py` (line 54), `app/handlers/tier3.py` (line 521, 631, 669)
- Impact: Year-end closing's opening balance creation (`POST /ledger/voucher/openingBalance`) will fail in production; bank reconciliation may have fallbacks but are untested
- Fix approach: Document which endpoints are BETA-only, add detection for 403 responses with BETA warnings in result, or implement fallback flows that don't require BETA endpoints. Consider raising error instead of silently failing.

**Multiple 403 Errors in error_patterns.json:**
- Issue: Widespread 403 responses indicate many endpoints are BETA or permission-gated — error patterns database documents this but handlers may attempt calls anyway
- Files: `app/error_patterns.json` (70+ occurrences of 403 status)
- Impact: Handlers like `/customer`, `/employee`, `/department`, `/supplier`, `/ledger/account` GET endpoints are frequently 403, causing silent failures
- Fix approach: Create a "dangerous endpoints" set in `error_patterns.py`, skip them early or return explicit "endpoint unavailable" without making the call

**Handler Error Responses Inconsistent:**
- Issue: Handlers return `{"status": "completed", "note": "..."}` or `{"status": "error", ...}` inconsistently
- Files: `app/handlers/tier2_extra.py` (multiple lines 112, 128, 313, 318, 335), `app/handlers/tier3.py` (line 120, 415-419)
- Impact: Caller cannot reliably distinguish success from failure; main.py always returns 200 regardless
- Fix approach: Standardize response format to always include `"status"` with values `completed | error | partial`, always include `"message"` field

**Graceful Degradation with Silently Ignored Failures:**
- Issue: Many handlers silently skip operations if lookups fail (e.g., `_find_supplier`, `_find_customer` return None and handlers just note "not found")
- Files: `app/handlers/tier2_extra.py` (lines 18-35, 58-75, 78-102 for finder functions)
- Impact: If a customer lookup fails silently, invoice creation proceeds with missing customer, leading to failed API calls downstream
- Fix approach: Add strict mode flag; raise exceptions in validators instead of returning None; log at WARN level when critical lookups fail

**VAT Account Unlocking Has Silent Exception Handling:**
- Issue: Exception during VAT unlocking is caught and logged as warning, but execution continues
- Files: `app/handlers/tier2_extra.py` (lines 339-347)
- Impact: If VAT unlock fails due to permissions or API error, the subsequent posting with VAT type may fail for a different reason
- Fix approach: Decide whether VAT unlocking is critical (raise error) or optional (log and continue), document this clearly

---

## Known Bugs

**Year-End Closing Spiral (Partially Fixed):**
- Symptoms: If opening balance creation fails, no fallback exists; closing balance updates may silently fail (line 474)
- Files: `app/handlers/tier3.py` (lines 513-700, especially 631-669)
- Trigger: Call year_end_closing with `createOpeningBalance=true` on a BETA-only environment
- Workaround: Set `createOpeningBalance=false` in fields; manually create opening balance vouchers
- Root cause: BETA endpoint + error swallowed with warning-level logging
- Recent fix: Multi-error support added (commit 1644d90), but BETA endpoint issue remains

**Bank Reconciliation Fallback to Last Reconciliation:**
- Symptoms: If reconciliation creation fails (40x), handler uses "last reconciliation" as fallback without validation
- Files: `app/handlers/tier3.py` (lines 403-419)
- Trigger: Create reconciliation with invalid dates or permissions
- Current behavior: Returns last existing reconciliation ID instead of error, caller thinks operation succeeded
- Fix approach: Return explicit error on creation failure, don't fall back silently

**Multiple Error Lookups Fail Silently:**
- Symptoms: Handlers call `_find_*()` helpers that return None, then proceed with empty IDs
- Files: `app/handlers/tier2_extra.py` (lines 111-121 update_supplier, 125-143 update_product, 302-318 register_supplier_invoice)
- Trigger: Search for non-existent supplier/product/customer
- Result: API call to PUT/POST with None/missing IDs leads to 400-422 errors
- Fix: Check if finder returned None BEFORE attempting update/create; raise or return early

**Parser Fallback Chain May Miss Tasks:**
- Symptoms: If Gemini fails and keyword matching fails, parser falls back to Claude Haiku with low confidence
- Files: `app/parser.py` (lines 400-410, 564-574)
- Trigger: Complex task in language other than Norwegian/English that doesn't match keywords
- Impact: Task parsed as "unknown", falls to fallback handler which may generate incorrect API calls
- Fix: Add more keyword patterns, improve prompt augmentation, log low-confidence parses for analysis

---

## Security Considerations

**Session Token Exposure in Logs:**
- Risk: Tripletex session token is logged in full request bodies (saved to GCS), could leak in Cloud Run logs
- Files: `app/main.py` (lines 48-64, 99-116 save_to_gcs), `app/tripletex.py` (line 58 debug mode)
- Current mitigation: .env file not committed, but session_token saved in GCS with request
- Recommendations: Redact session tokens from saved request/response, use separate audit logs with redacted values, enable encryption at rest for GCS

**API Key Validation is Weak:**
- Risk: Bearer token check is simple string comparison, no rate limiting
- Files: `app/main.py` (lines 29-33)
- Current mitigation: None; if API_KEY is set, basic auth check, but no CORS, no rate limit
- Recommendations: Add request signing, implement rate limiting, consider API Gateway authentication layer

**Error Messages Include Sensitive Data:**
- Risk: Validation error messages may include field names or account details
- Files: `app/api_validator.py`, `app/handlers/tier2_extra.py` (line 313, 420)
- Impact: If error response is exposed, attacker learns field names and API structure
- Recommendations: Sanitize error messages in production, log full details internally only

---

## Performance Bottlenecks

**Large Handler Files (1400+ lines):**
- Problem: `app/handlers/tier3.py` (1413 lines) and `app/handlers/tier2_extra.py` (1205 lines) are monolithic
- Files: `app/handlers/tier3.py`, `app/handlers/tier2_extra.py`
- Cause: All voucher/closing/payroll logic in single file; difficult to reason about control flow
- Improvement path: Split by domain (voucher handlers, closing handlers, payroll handlers) into separate modules; reduce cyclomatic complexity

**Helper Functions Duplicated Across Modules:**
- Problem: `_lookup_account()` defined in tier3.py, imported by tier2_extra.py; other lookups like `_find_supplier()` duplicated logic
- Files: `app/handlers/tier3.py` (line 13), `app/handlers/tier2_extra.py` (lines 18-102)
- Impact: Code maintenance burden, risk of inconsistency
- Improvement: Consolidate all lookup helpers into `app/handlers/_lookups.py`

**Caching Strategy Naive:**
- Problem: `TripletexClient.get_cached()` uses simple path+params string as cache key (line 62 in tripletex.py)
- Files: `app/tripletex.py` (lines 60-68)
- Impact: Cache hit rate poor because params ordering matters; no TTL, stale data possible; cache not cleared between requests
- Improvement: Use stable cache key generation (sorted params), implement TTL, clear cache per request lifecycle

**API Validation on Every Call:**
- Problem: `_warn_invalid_fields()` and `_preflight_correct()` call `validate_payload()` on every POST/PUT, which loads and parses OpenAPI spec
- Files: `app/tripletex.py` (lines 79-80, 84-85)
- Impact: Spec loading/parsing happens multiple times per request in worst case (multiple POST/PUT calls)
- Improvement: Load spec once at module init, cache schema lookups

**Embedding Index Not Pruned:**
- Problem: `app/embeddings_index.json` grows unbounded as parser learns new prompts
- Files: `app/embeddings_index.json`, `app/embeddings.py`
- Impact: Cold start time increases, vector search becomes slower
- Improvement: Implement index pruning (remove oldest/lowest-confidence entries), use more efficient vector store (FAISS, Pinecone)

---

## Fragile Areas

**Year-End Closing with Budget Limits:**
- Files: `app/handlers/tier3.py` (lines 513-700)
- Why fragile: MAX_API_CALLS = 30 hardcoded; if closing requires more calls (large chart of accounts, many journals), budget exceeded and RuntimeError raised mid-operation
- Safe modification: Make MAX_API_CALLS configurable, implement chunked closing (per account range), add checkpoints to resume
- Test coverage: E2E test_e2e.py has one test for year_end_closing but only for small data; no stress test with large COA

**Payroll Handler Assumptions:**
- Files: `app/handlers/tier2_extra.py` (lines 1000-1160, run_payroll)
- Why fragile: Assumes specific account numbers (1920, 2600, 2770, 2940, 5000, 5020, 5400) exist; if company chart differs, lookups fail
- Safe modification: Allow account overrides in fields; validate all accounts exist before proceeding
- Test coverage: run_payroll tested against sandbox but only with default company setup

**Bank Reconciliation Endpoint Variation:**
- Files: `app/handlers/tier3.py` (lines 340-510)
- Why fragile: Uses multiple endpoints `/bank/reconciliation`, `/bank/reconciliation/match/:suggest`, `/bank/statement` which may not all exist in all Tripletex versions
- Safe modification: Detect 404 early, provide clear error message; document API version requirements
- Test coverage: test_e2e.py has bank_reconciliation test but against fixed sandbox setup

**Parser Prompt Augmentation with File Context:**
- Files: `app/parser.py` (lines 370-405, embedding augmentation)
- Why fragile: If file processing fails, augmented prompt becomes malformed; no validation that augmented_prompt is coherent
- Safe modification: Validate augmented prompt structure before sending to LLM; return original prompt if augmentation fails
- Test coverage: test_parser.py has limited coverage of prompt augmentation edge cases

---

## Scaling Limits

**Handler Registry Linear Search:**
- Current capacity: 30 handlers registered
- Limit: Handler dispatch uses linear dict lookup; scales fine to ~100 handlers but globals are not thread-safe
- Files: `app/handlers/__init__.py`
- Scaling path: Handler registry is small enough; scaling not a concern. If needed, use lazy loading with @register_handler decorator

**GCS Storage No Cleanup:**
- Current capacity: Grows by ~2 files per request (request + result JSON) = ~1.5MB/day
- Limit: GCS has no quota per project tier, but storage costs grow; no retention policy
- Files: `app/storage.py`
- Scaling path: Implement lifecycle policy (delete after 30 days), or move to Cloud Logging for structured logs

**RAG Index Size:**
- Current capacity: 751 chunks in `app/api_rag_index.json`
- Limit: RAG search time grows with corpus size; no pagination or filtering
- Files: `app/api_rag.py`, `app/api_rag_index.json`
- Scaling path: Migrate to Vertex AI Search or similar managed service, implement chunk filtering by endpoint

**Error Patterns Database:**
- Current capacity: 112 patterns recorded in `app/error_patterns.json`
- Limit: Grows linearly with failed API calls; no deduplication or prioritization
- Files: `app/error_patterns.py`, `app/error_patterns.json`
- Scaling path: Implement pattern scoring (by frequency), prune low-frequency patterns, export to SQL database

---

## Dependencies at Risk

**Anthropic Python SDK Version Pinned But Old:**
- Risk: SDK may have breaking changes; no auto-update mechanism
- Impact: If Anthropic deprecates Haiku or changes API, code breaks silently
- Current mitigation: Specified in requirements.txt (if present)
- Migration plan: Monitor deprecation notices, test against new versions in CI

**Gemini Backend Optional But Less Tested:**
- Risk: PARSER_BACKEND=gemini path not covered by E2E tests in default config
- Impact: Gemini fallback may regress undetected
- Current mitigation: Manual testing required, no CI job for Gemini
- Migration plan: Add Gemini tests to CI with separate secret

---

## Missing Critical Features

**No Idempotency Keys:**
- Problem: If a handler request times out and retries, duplicate API calls occur (e.g., invoice created twice)
- Blocks: Reliable exactly-once semantics for financial transactions
- Impact: Can create duplicate vouchers, invoices, or payments if network fails
- Fix: Add idempotency key headers to all POST/PUT calls, implement tracking of created IDs

**No Audit Log:**
- Problem: All API calls are logged to GCS but no structured audit trail
- Blocks: Compliance, forensics, error investigation
- Impact: Hard to trace who did what and when
- Fix: Create separate audit table with transaction ID, timestamp, user (if available), action, status

**No Retry Strategy Beyond Smart Retry:**
- Problem: Only 422 responses get retry attempt; 429 (rate limit) and timeout errors fail immediately
- Blocks: Resilience to API throttling
- Impact: Competition task may timeout on 120s limit if too many retries needed
- Fix: Implement exponential backoff with jitter, respect Retry-After headers, circuit breaker pattern

**No Dry-Run or Validation Mode:**
- Problem: Parser and handlers always attempt to create real entities
- Blocks: Validation without side effects
- Impact: Test data pollutes production (sandbox)
- Fix: Add `dry_run=true` flag that validates payload but doesn't POST/PUT

---

## Test Coverage Gaps

**Untested Error Paths:**
- What's not tested: 403 BETA endpoint errors, validation message parsing from 422 responses, VAT account unlocking exceptions
- Files: `app/handlers/tier2_extra.py` (lines 339-347, 418-422), `app/tripletex.py` (lines 111-149)
- Risk: Error recovery code may be broken; find out during production failure
- Priority: **High** — error paths are executed when failures happen

**Limited Fixture Diversity:**
- What's not tested: Large chart of accounts (>100), multiple departments, project hierarchies, batch operations
- Files: `scripts/test_e2e.py`
- Risk: Handlers may break on real-world complex setups
- Priority: **Medium** — payroll and year-end closing may fail on large companies

**No Integration Tests Against Multiple Tripletex Versions:**
- What's not tested: API compatibility across Tripletex versions; BETA endpoint availability per version
- Files: CI/deployment scripts
- Risk: Deploy to customer with older Tripletex version that doesn't support newer endpoints
- Priority: **Medium** — depends on customer base requirements

**Parser Robustness Not Tested:**
- What's not tested: Malformed prompts, extremely long prompts, prompts in unsupported languages, prompts with embedded URLs/code
- Files: `scripts/test_parser.py`
- Risk: Parser may hang, OOM, or return malformed JSON
- Priority: **Low** — parser is Claude/Gemini, unlikely to crash, but input validation could improve

**Fallback Handler Untested:**
- What's not tested: Fallback LLM-generated API calls; placeholder resolution logic; error recovery when generated calls fail
- Files: `app/handlers/fallback.py`, `scripts/test_e2e.py` (no explicit fallback test)
- Risk: Unknown task types trigger fallback which may generate nonsensical API calls
- Priority: **Medium** — fallback used for tasks without explicit handler

**Concurrent Request Safety Not Tested:**
- What's not tested: Multiple concurrent requests to /solve endpoint; cache coherency under concurrency
- Files: `app/main.py`, `app/tripletex.py` (caching)
- Risk: Race conditions in cache, shared state mutations, httpx client reuse
- Priority: **Low** — Cloud Run handles concurrency via multiple workers, but worth stress testing

---

## Error Handling Strategy

**Current approach:** Try-except at top level in `main.py` catches all exceptions, returns `{"status": "completed", "error": str(e)}` with HTTP 200.

**Issues:**
1. All failures look like success to caller (HTTP 200)
2. Exception messages leak implementation details
3. No distinction between user error (bad prompt), API error (403), or system error (timeout)
4. Call tracking only partially populated on exception
5. Parser exceptions don't trigger fallback to keyword matching

**Recommendations:**
- Return HTTP 200 only for actual completion; use 400/500 for recoverable/unrecoverable errors
- Wrap domain-specific exceptions (APIError, ValidationError, NotFound) with standardized format
- Log exception tracebacks at ERROR level, user-facing messages at WARNING level
- Ensure call tracking populated even on exception, with error count recorded

---

*Concerns audit: 2026-03-21*
