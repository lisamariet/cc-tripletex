# Pitfalls Research

**Domain:** Tripletex AI Accounting Agent — NM i AI 2026 competition scoring optimization
**Researched:** 2026-03-21
**Confidence:** HIGH — derived directly from live score data, error_patterns.json (112 patterns), CONCERNS.md, and observed behavior in 114 submissions

---

## Critical Pitfalls

### Pitfall 1: Silent Null Score From BETA Endpoint 403s

**What goes wrong:**
A handler calls a BETA-marked endpoint (e.g., `POST /ledger/voucher/openingBalance`, `POST /company/salesmodules`), receives 403, silently swallows the error, returns `{"status": "completed"}`, and the task scores 0. The competition scorer sees no entity created and awards nothing.

**Why it happens:**
403 looks like an authentication error, not a "this endpoint doesn't exist in your sandbox" error. Handlers catch HTTPError broadly and return `completed` to avoid crashing the whole request. The system was built with graceful degradation as a priority, but graceful degradation here means silent failure.

**How to avoid:**
- Maintain an explicit blocklist of known BETA endpoints. Before any call, check against it and fail fast with a clear error.
- Treat 403 from BETA endpoints differently from 403 from permission errors: log at ERROR, do not return `completed`.
- In `app/handlers/tier3.py` lines 521, 631, 669 and `app/handlers/fallback.py` line 54 — these are the documented BETA callers. Remove or bypass them.

**Warning signs:**
- `error_patterns.json` has 403 entries for `GET /customer`, `GET /department`, `GET /employee`, `GET /supplier`, `GET /ledger/account`, `POST /customer`, `POST /department` — all produce 403 silently.
- Any task that was previously working in a local test but scores 0 in competition submission.
- Year-end closing score is 0 despite E2E test passing (E2E may not trigger the BETA branch).

**Phase to address:**
Nullscore fix phase (immediate). Identify each BETA call in tier3.py opening balance path, replace or skip.

---

### Pitfall 2: Efficiency Bonus Gated on Perfect Correctness — 99% Is Worthless

**What goes wrong:**
The efficiency bonus (which can double the score) only activates when `correctness == 1.0`. A task that is 90% correct scores `0.9 × tier`, with zero efficiency bonus. A task that is 100% correct with 20 extra API calls can still score `~1.05× tier`. This means partially-correct solutions score dramatically less than the table suggests.

**Why it happens:**
Teams optimize for "getting the right answer mostly" rather than "getting every checked field exactly right." They accept partial correctness as good enough, not realizing the bonus cliff at 1.0.

**How to avoid:**
- For every task type, know exactly which fields the competition scorer checks. From `docs/03-scoring.md`: each task has specific check fields worth specific points. A single missing field (e.g., administrator role not assigned to employee) blocks the efficiency bonus on an otherwise correct submission.
- Add self-verification GET after every POST: fetch the created entity and compare scored fields against what was sent.
- Prioritize field completeness over reducing API call count. One extra GET to verify is worth it if it catches a missing field.

**Warning signs:**
- Tasks 04 and 06 score 0.8571 consistently — this is exactly 6/7 points. One field is always missing.
- Task 05 scores 1.3333 — this is a Tier 1 task at 2/3 correctness. Only 2 of 3 checked fields match.
- Any task stuck at a non-round score fraction suggests a specific field is systematically wrong.

**Phase to address:**
Low-score fix phase. Identify the specific missing field per task type, fix the handler to always set it.

---

### Pitfall 3: Fresh Sandbox Prerequisite Assumption

**What goes wrong:**
Each competition submission receives a completely empty Tripletex sandbox. Handlers that assume entities exist (e.g., looking up a customer before creating one, searching for a supplier before registering an invoice) fail silently when the search returns empty, proceed with `None` IDs, and produce 400/422 errors on the subsequent POST.

**Why it happens:**
Handlers for "update" and "register" operations reasonably assume the entity exists in production. In competition, every sandbox is born empty. The finder functions (`_find_supplier`, `_find_customer`, `_find_product`) return `None` for empty sandboxes, and the None propagates to the API call body.

**How to avoid:**
- For update/register tasks: check if the finder returned None and immediately create the prerequisite, rather than proceeding.
- For known fresh-sandbox patterns (e.g., `register_supplier_invoice` needs supplier, `register_payment` needs customer + invoice), build a "prerequisite creation" step at the top of each handler.
- The `register_payment` handler already does this correctly — use it as the reference pattern.
- In `app/handlers/tier2_extra.py` lines 111-121 (`update_supplier`), 125-143 (`update_product`), 302-318 (`register_supplier_invoice`): add None-check and early return or prerequisite creation.

**Warning signs:**
- Handler returns `{"status": "error", "message": "Supplier not found"}` or similar in Cloud Run logs.
- Task scores 0 or near-0 on first attempt but you believe the handler is correct — the finder returned empty.
- `error_patterns.json` shows 400/422 errors on PUT/POST endpoints where the entity ID is probably None.

**Phase to address:**
Nullscore fix phase (tasks 09, 11, 12, 17 are prime suspects for this pattern).

---

### Pitfall 4: Parser Misclassification Sending Task to Wrong Handler

**What goes wrong:**
The parser classifies a task as `unknown` or as the wrong task type. The fallback LLM handler runs and generates plausible-looking but incorrect API calls. The result is 0 score or very low score. With 5 attempts per task per day, wasting attempts on misclassified tasks is especially costly.

**Why it happens:**
Tasks 09, 11, 12, and 17 score 0 across 5-7 attempts each — this strongly suggests the parser never correctly identifies the task type, so the correct handler never runs. The embedding classifier was trained on 128 prompts covering 17 types, leaving unknown task types with no direct coverage. 7 languages and 8 data variants per task = 56 prompt forms per task type.

**How to avoid:**
- For any task scoring 0 across multiple attempts: log the raw prompt and check which task type the parser returned. If it is `unknown`, the handler is correct but unreachable.
- Add keyword rules for the suspected task type in `_KEYWORD_RULES` (app/parser.py line 39). These bypass LLM classification failures.
- After each failed submission, check GCS logs for `"task_type": "unknown"` or unexpected task type for the zero-scored tasks.
- Rebuild embeddings index when new prompt examples are added (`build_embeddings.py`).

**Warning signs:**
- Task scores 0 on every attempt, not just the first.
- Cloud Run logs show `task_type: unknown` or incorrect type for that task ID.
- `#1 websecured` scores on task 11 (0.25) and task 12 (1.00) confirm the task is solvable — our 0 means we are not even running the right handler.

**Phase to address:**
Nullscore fix phase. Run a test submission, capture the GCS log, find what task type the parser assigned, fix parser or add handler.

---

### Pitfall 5: 4xx Errors Bleeding the Efficiency Bonus

**What goes wrong:**
Even when a task achieves perfect correctness (1.0), every 4xx error in the request log reduces the efficiency bonus. A handler that does a GET lookup returning 403, then recovers and creates correctly, pays a penalty. The competition scorer counts all 4xx responses in the submission log, not just fatal ones.

**Why it happens:**
The current codebase makes exploratory GET calls (looking up vatType, paymentType, department, etc.) that frequently return 403 or 400 with invalid field filters. These are "recovery" calls but they count against the score. Example: `GET /customer` → 403, handler switches to POST directly → correct result, but the 403 is logged.

**How to avoid:**
- Hardcode all lookup results that are stable across sandboxes: vatType IDs (already done for codes 3, 5, 6, 31, 33), paymentType IDs, default department ID.
- For a fresh sandbox: do not attempt GET lookups for entities that cannot exist yet. Go straight to POST.
- Remove all calls to known-403 endpoints: `GET /customer`, `GET /department`, `GET /employee`, `GET /supplier`, `GET /ledger/account` as standalone lookups — use `?fields=id,name` variants only when absolutely necessary and they are known to succeed.
- Audit `error_patterns.json` to identify which endpoints consistently produce 4xx. Eliminate those calls from handlers.

**Warning signs:**
- Task achieves perfect correctness but scores ~2.1 instead of 4.0 on a Tier 2 task — efficiency penalty from 4xx calls.
- Cloud Run logs show 403 errors before a successful creation.
- Efficiency bonus below 0.5 on a clean task = multiple 4xx errors happening.

**Phase to address:**
Efficiency optimization phase (after nullscores are fixed). Reduce 4xx rate from ~20% to near 0.

---

### Pitfall 6: Handler Timeout Burning All Daily Attempts

**What goes wrong:**
A handler exceeds the 120-second timeout. The submission times out, scores 0, and consumes one of the 5 daily attempts for that task type. With complex Tier 3 tasks taking 20-30 API calls, a single slow LLM fallback call or cascading retry chain can exhaust the timeout.

**Why it happens:**
The fallback handler uses LLM to generate API calls iteratively — each LLM call takes 5-15 seconds, and a complex task might need 5-10 LLM iterations. Sequential API calls with error-triggered retries compound this. The `year_end_closing` handler has `MAX_API_CALLS = 30` hardcoded, and hitting that limit mid-operation raises a RuntimeError rather than gracefully completing partial work.

**How to avoid:**
- Monitor actual execution time in GCS logs for complex task types.
- Add per-handler timeout budgets: allocate max 90 seconds to handler execution, leaving 30 seconds margin.
- LLM calls in fallback handler should be pre-planned (one LLM call to plan all steps), not iterative (one LLM call per step).
- Eliminate LLM calls from hot paths in known handlers — use only for unknown task types via fallback.

**Warning signs:**
- Submission shows no result in competition portal after > 120 seconds.
- Cloud Run logs cut off mid-execution.
- Task 09 scores 0 with 5 attempts — if the handler is running but timing out, this is the signature.

**Phase to address:**
Efficiency optimization phase. Profile T3 handler execution time in sandbox E2E.

---

### Pitfall 7: Spending Attempts Before Understanding Root Cause

**What goes wrong:**
With 5 attempts per task per day, deploying a speculative fix and immediately submitting burns an attempt. If the fix was wrong (e.g., fixed parser but handler was also broken), the attempt is wasted and the root cause is still unknown.

**Why it happens:**
Time pressure (24-hour deadline) encourages "try it and see." But 5 attempts on 18+ task types means 90 total attempts per day — depleted quickly if fixes are untested. Tasks 09, 11, 12, 17 already have 5-7 attempts exhausted with 0 score.

**How to avoid:**
- Before any submission: reproduce the failure locally in E2E test with the specific task type. Confirm the fix works in sandbox before submitting.
- For nullscore tasks: check GCS logs from past submissions first. The root cause is there.
- Use the `scripts/test_e2e.py` suite — run the specific test for the failing task type after each code change.
- Never submit to competition without running E2E tests first (project constraint already documented).

**Warning signs:**
- Attempting the same task type multiple days in a row with 0 score = root cause unknown.
- Score on a task does not improve after a fix = wrong root cause identified.

**Phase to address:**
All phases. Rule: diagnose from logs, fix, validate in E2E, then submit. Never speculate with competition attempts.

---

### Pitfall 8: Efficiency Benchmark Recalculation Lowering Existing Scores

**What goes wrong:**
The competition recalculates efficiency benchmarks every 12 hours based on the best-known solution across all teams. If a competitor submits a more efficient solution, the benchmark rises and your efficiency bonus for an already-submitted task is retroactively reduced. A score of 3.5 today can become 2.8 tomorrow without any change on your side.

**Why it happens:**
The scoring system explicitly states: "Efficiency benchmarks are recalculated periodically. As teams find more efficient solutions, the bar rises for everyone." The best competitor (#1 at 44.41) has likely established very low API call counts on most T1/T2 tasks.

**How to avoid:**
- Do not treat current efficiency bonus scores as stable. Budget for them to decrease.
- Focus first on correctness (the stable component), then on efficiency reduction.
- For tasks where you already score perfectly: aggressively minimize API calls below current count, to stay ahead of benchmark recalculation.
- The correct priority order: fix nullscores first (locked-in 0 will not recalculate), then push perfect tasks toward minimum API calls.

**Warning signs:**
- Total leaderboard score drops between sessions without any new submissions.
- Efficiency bonus on a previously high-scoring task has decreased.

**Phase to address:**
Efficiency optimization phase. Hardcoded IDs, eliminated GETs, parallel calls = defense against benchmark rises.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Return `{"status": "completed"}` on all exceptions | Prevents HTTP 500, never crashes | Silent failure scores 0; impossible to diagnose from competition portal | Never — use explicit error status |
| Hardcode VAT type IDs instead of API lookup | Eliminates 1 GET call per request | Breaks if Tripletex changes IDs (unlikely for standard codes) | Acceptable — Norwegian tax codes are stable |
| `MAX_API_CALLS = 30` global budget in year_end_closing | Prevents infinite loops | Mid-operation budget exhaustion raises RuntimeError, task gets 0 | Never — make it configurable, checkpoint progress |
| Silent None propagation from `_find_*()` helpers | Avoids early return boilerplate | None ID in POST body → 400 error, task fails | Never — check None before proceeding |
| Cache not cleared between requests | Reduces API calls within a request | Stale data from previous request poisons next request in same worker | Never in competition context — clear per request |
| Gemini parser not tested in E2E CI | Saves CI complexity | Gemini regressions go undetected until competition submission | Acceptable as long as Haiku is primary and tested |

---

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| Tripletex BETA endpoints | Calling them expecting functionality | Check `docs/06-tripletex-api-endpoints.md` — `[BETA]` tag means 403 in sandbox. Never call them. |
| Tripletex `?fields=` filter | Including fields not in the DTO model | Always validate field names against DTO model. `amountOutstandingCurrency` not in `InvoiceDTO`, `fixedPrice` not in `ProjectDTO`, `name` not in `PaymentTypeDTO` — each generates a 400. |
| Tripletex fresh sandbox | Searching for existing entities | Sandbox is empty per submission. Don't search for entities before creating them. Create directly. |
| Tripletex auth | Using wrong auth format | Username must be `"0"` (string zero), password is the session token. Basic Auth, not Bearer. |
| Tripletex POST /employee | Missing `department.id` | If no department specified in prompt, create one first or use default. `department.id` is required on employee creation (documented in error_patterns.json). |
| Tripletex POST /employee/employment | Missing `division.id` | Employment requires division linkage. Same issue documented 4 times in error_patterns.json. |
| Competition proxy | 120s timeout is absolute | Cannot extend. Long-running operations must complete in under 90s (leaving buffer). |
| Competition scorer | Checks specific field names | Correctness is field-by-field. Returning the right entity with a slightly wrong field name (e.g., `phone` vs `phoneNumber`) scores 0 on that check. |

---

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Sequential lookup before every POST | High latency, timeout risk on T3 tasks | Cache known-stable IDs (vatType, paymentType); skip GET if entity cannot exist in fresh sandbox | Breaks when T3 tasks need 15+ API calls |
| LLM call per step in fallback handler | 5-15s per step, 10 steps = timeout | Pre-plan all steps with one LLM call, execute deterministically | Breaks on any task requiring > 5 iterative LLM steps |
| Cache not keyed by request lifecycle | Stale data from one task bleeds into next | Instantiate fresh `TripletexClient` per request; clear cache at request start | Breaks on Cloud Run instances handling concurrent requests |
| Embedding index cold start | First request slow, may contribute to timeout | Prune index, load at module startup (not per request) | Breaks if index grows past ~500 entries on cold start |
| OpenAPI spec loaded per call | Multiplies validation overhead | Load once at module init, cache schema lookups | Already a problem at current call volumes (10-30 calls per task) |

---

## "Looks Done But Isn't" Checklist

- [ ] **Handler implemented:** Verify the task type string in `@register_handler(...)` exactly matches what `VALID_TASK_TYPES` and the parser return. A mismatch means the handler never runs.
- [ ] **E2E test passes:** Run `scripts/test_e2e.py` against sandbox — a passing test with wrong data (e.g., wrong account number) still passes locally but scores 0 in competition.
- [ ] **Self-verification GET included:** After POST, fetch the created entity and confirm scored fields are present. The competition scorer checks what Tripletex actually stored, not what you sent.
- [ ] **No BETA endpoints called:** Grep the handler for all API paths. Cross-reference against `docs/06-tripletex-api-endpoints.md`. Any `[BETA]` endpoint = 403 in sandbox.
- [ ] **Prerequisites created in handler:** Fresh sandbox has no customers, suppliers, or departments. Handler must create what it needs, not assume it exists.
- [ ] **4xx error count is zero in test run:** Check Cloud Run / local logs after E2E. Even "recovered" 4xx errors reduce efficiency bonus.
- [ ] **Efficiency API call count is minimal:** Count the calls in E2E output. Compare against what the minimum would be. Every GET that can be replaced by a hardcoded ID should be.
- [ ] **All 7 languages handled by parser:** The parser's keyword rules and few-shot examples cover Norwegian best. German and French prompts are highest risk for `unknown` classification.

---

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| BETA endpoint producing 0 score | LOW | Identify BETA call in handler, remove or replace with non-BETA alternative, redeploy, run E2E |
| Parser misclassification (task scores 0) | LOW | Check GCS log for `task_type` field on failed submission, add keyword rule for correct type, rebuild embeddings if needed, redeploy |
| Missing prerequisite in fresh sandbox (0 score) | LOW | Add prerequisite creation block at handler top, E2E test confirms, redeploy |
| Missing field causing correctness < 1.0 | MEDIUM | Identify which field fraction maps to (e.g., 6/7 = one field missing), check competition task description for field list, add field to handler |
| Efficiency score degraded by 4xx | MEDIUM | Audit handler call sequence in E2E output, eliminate known-403 GET calls, hardcode stable IDs |
| Timeout (MAX_API_CALLS exceeded mid-T3 task) | HIGH | Increase budget, add checkpointing, reduce intermediate verification calls — requires handler redesign |

---

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| BETA endpoint 403 silent failure | Phase 1: Nullscore fixes | E2E passes with zero 403 errors in log |
| Parser misclassification | Phase 1: Nullscore fixes | GCS log shows correct `task_type` for tasks 09, 11, 12, 17 |
| Fresh sandbox prerequisite missing | Phase 1: Nullscore fixes | E2E test starts from empty sandbox, completes without 404/400 on lookup |
| Missing scored field (correctness < 1.0) | Phase 2: Low-score fixes | Score fraction improves to 1.0 (e.g., task 04/06 go from 0.857 to 1.0) |
| 4xx errors reducing efficiency bonus | Phase 3: Efficiency optimization | 4xx count in E2E output reaches 0 |
| Wasteful GET calls inflating API count | Phase 3: Efficiency optimization | API call count per task at or below #1 competitor benchmark |
| Benchmark recalculation eroding bonus | Phase 3: Efficiency optimization | API call count pushed to theoretical minimum (hardcoded IDs, no exploratory GETs) |
| Timeout on T3 tasks | Phase 4: T3 optimization | T3 E2E tests complete in < 90 seconds with correct result |
| Speculative submissions burning attempts | All phases | Rule enforced: E2E must pass before any competition submit |

---

## Sources

- `app/error_patterns.json` — 112 recorded failures, 70+ 403 patterns, documented endpoint behavior
- `docs/SYSTEMSTATUS.md` — Live score data: 4 nullscore tasks (09, 11, 12, 17), 7 low-score tasks
- `.planning/codebase/CONCERNS.md` — Documented known bugs: year_end_closing spiral, bank reconciliation silent fallback, None propagation in finders
- `docs/03-scoring.md` — Scoring mechanics: efficiency bonus only at 1.0 correctness, 4xx penalty, benchmark recalculation
- `app/handlers/tier3.py` — BETA endpoint calls at lines 521, 631, 669; MAX_API_CALLS = 30 budget
- `app/handlers/tier2_extra.py` — Silent None propagation in update/register handlers; finder functions returning None
- `docs/04-examples.md` — Competition guidance: "avoid trial-and-error," "every 4xx reduces efficiency bonus"
- `.planning/PROJECT.md` — Constraints: 5 attempts/task/day, fresh sandbox per submit, 120s timeout, 24h deadline

---
*Pitfalls research for: Tripletex AI Accounting Agent — NM i AI 2026 competition optimization*
*Researched: 2026-03-21*
