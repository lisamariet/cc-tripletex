# Feature Landscape

**Domain:** Competition AI accounting agent — Tripletex NM i AI 2026
**Researched:** 2026-03-21
**Milestone:** Tier 3 opens today. Current score 21.65/52. Target: full score.

---

## Scoring formula recap

```
score = correctness × tier_multiplier × (1 + efficiency_bonus_if_perfect)
```

- Tier 1: ×1, max 2.0 per task
- Tier 2: ×2, max 4.0 per task
- Tier 3: ×3, max 6.0 per task
- Efficiency bonus only activates at correctness = 1.0 (perfect). Can double the score.
- 4xx errors and excess API calls both reduce the efficiency bonus.
- Best score per task is kept forever — a bad run never lowers a locked score.
- Benchmarks recalculate every 12 hours, so efficiency must keep up with other teams.

---

## Table Stakes

Features the agent MUST have to avoid scoring zero or very low. Missing any of these
leaves points permanently on the table.

| Feature | Why Required | Est. point value | Current status |
|---------|--------------|-----------------|----------------|
| Correct handler for every known task type | Null score = 0 points | +8-12 pts (4 null-score tasks) | 4 null-score tasks (09, 11, 12, 17) |
| Parser correctly identifies task type from prompt in all 7 languages | Wrong task type = wrong handler = 0 | Up to total score | Working but misclassifies some |
| Zero 4xx API errors on happy path | Each 4xx reduces efficiency bonus | Up to 2× on perfect tasks | Several handlers still produce 4xx |
| Correct field extraction by parser | Wrong fields = wrong payload = low correctness | Per-field scoring | Some fields under-extracted |
| Handle fresh sandbox: create prerequisites | Sandbox starts empty — no customer/invoice exists | Required for all T2/T3 | Mostly done; gaps in T2 |
| Correct Norwegian VAT codes (3/31/33/5/6) | Field-level scoring on vatType | ~0.5-1.0 per invoice task | Hardcoded mapping in place |
| Employee role assignment (entitlements) | 5/10 points on create_employee | Up to 1.0 per task | Done for known roles |
| Invoice bank account setup | Invoices fail without bank account ready | Required for all invoice tasks | Multi-strategy in place |
| Correct amount: incl-VAT for payments | Payment fails or scores 0 if wrong amount | Required for register_payment | Fixed |
| Tier 3 handler correctness (bank_reconciliation, year_end_closing, correct_ledger_error, monthly_closing) | ×3 multiplier = 6 pts max each | Up to 24 pts | Handlers exist, quality unknown |

### Null-score tasks — highest urgency

Tasks 09, 11, 12, 17 currently score 0. These are the single highest-value fixes.

| Task | Tier | Max pts | Gap vs #1 | Likely cause |
|------|------|---------|-----------|--------------|
| 09   | T2   | 4.0     | +3.67     | Unknown task type — handler missing or parser misroutes |
| 11   | T1   | 2.0     | +0.25     | Unknown task type — even #1 scores low, likely novel type |
| 12   | T1   | 2.0     | +1.00     | Parser misclassifies or handler bug |
| 17   | T2   | 4.0     | +4.00     | Unknown task type — handler missing (#1 gets full score) |

Fixing tasks 09 and 17 alone is worth ~+7.67 points if matched to #1 level.

---

## Differentiators

Features that produce the efficiency bonus — turning a 2.0 into a 4.0, or 3.0 into 6.0.

| Feature | Value Proposition | Est. point gain | Complexity | Current status |
|---------|-------------------|----------------|------------|----------------|
| Zero 4xx on all handlers | Efficiency bonus requires clean run | +0.5-2.0 per perfect task | Low-Med | Multiple known 4xx still occurring |
| Minimize API call count | Call count compared to best-known solution | +0.5-1.5 per task | Med | Some handlers do unnecessary GETs |
| Create-directly (no search-then-create) in fresh sandbox | Saves 1 GET call per entity | +0.2-0.5 per affected task | Low | Invoice does this; others still search first |
| `?fields=id,name` on GET calls | Reduces payload; may reduce call time | Minor | Low | Not consistently applied |
| Cache vatType/paymentType per request | Avoids repeated GET /ledger/vatType | +1 call saved per invoice line | Low | get_cached() exists; coverage incomplete |
| Self-verify after POST (GET-after-POST) | Catches silent failures before scoring | Correctness insurance | Med | Not implemented |
| Parallel independent API calls (asyncio.gather) | Reduces wall-clock time; avoids timeout | Risk mitigation for T3 | High | Not implemented |
| Tier 3 perfect correctness | ×3 multiplier means 6 pts vs 4 pts at T2 | +2 per task vs T2 equivalent | High | Unknown scoring accuracy |

### Efficiency opportunity sizing

Current scores on non-zero tasks show most are 40-80% of max. The gap has two causes:
1. Correctness < 1.0 (wrong or missing fields)
2. No efficiency bonus (correctness not perfect)

For tasks where we already score ~80%+, fixing correctness to 100% then unlocks the
efficiency bonus — potentially doubling the score. This is highest ROI for T1 tasks
where we are at 0.857 (tasks 04, 06).

---

## Anti-Features

Features to deliberately NOT build given the 24-hour constraint.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| Generic LLM-based handler execution | Non-deterministic, slow, uses tokens per call | Keep deterministic handler-per-task architecture |
| Full asyncio refactor (to_thread) | Marginal gain, high risk of regressions | Accept synchronous slowness; stay under 120s timeout |
| Local scoring verifier | Nice-to-have, but takes time to build correctly | Use submissions + poll to verify directly |
| Dynamic Tripletex module activation | Always 422 in competition sandboxes, costs a 4xx | Remove all salesmodules POST calls |
| Retry loops without cap | Can hit 120s timeout and waste 5 attempts/day budget | Keep MAX_API_CALLS guards as in year_end_closing |
| UI/dashboard | Zero score impact | Do not build |
| Multi-file batch ingestion redesign | Current batch handler works | Only fix bugs, don't redesign |
| Exploration of unknown T3 task types via trial-and-error | 5 attempts per task per day max | Research task types from docs/other signals first |
| Heavy ML retraining (rebuild embeddings, RAG) | Takes 30+ min, marginal parser improvement | Tune parser prompts/few-shot examples instead |
| BETA endpoints | 403 = wasted call + 4xx penalty | Avoid /ledger/voucher/openingBalance and others marked BETA |

---

## Feature Dependencies

```
Null-score fix (09, 11, 12, 17)
  └── Requires: identify task type from submission log
  └── Requires: implement or fix handler
  └── Requires: parser recognizes new task type keyword/embedding

Efficiency bonus (any task)
  └── Requires: correctness = 1.0 first
  └── Requires: zero 4xx on that run
  └── Requires: API call count <= benchmark

Tier 3 full score
  └── Requires: correct handler output (correctness = 1.0)
  └── Requires: efficiency (few calls, zero 4xx)
  └── bank_reconciliation: needs correct reconciliation + match
  └── year_end_closing: needs close_postings + opening balance (non-BETA path)
  └── correct_ledger_error: needs correct voucher find + reverse + re-post
  └── monthly_closing: handler exists but scoring unknown

T2 low-score tasks (10, 13, 15, 16, 18)
  └── Requires: identify which field checks are failing (analyse submission detail)
  └── Requires: fix parser extraction for those fields
  └── Requires: fix handler for those edge cases
```

---

## MVP Recommendation — priority order for 24h window

Given deadline tomorrow and 5 attempts/task/day limit, the recommended priority:

### P0 — Must do (null to non-zero = guaranteed points)

1. **Identify tasks 09 and 17** — Submit one test each to see what task type is assigned.
   Task 09 is T2 (up to 4 pts), task 17 is T2 (up to 4 pts, #1 gets full score).
   Likely these are task types already in VALID_TASK_TYPES but with a parser misrouting,
   OR they are entirely new task types not yet handled.
   Gain: up to +7.67 points if fixed.

2. **Identify tasks 11 and 12** — T1 tasks. Task 11 has only +0.25 gap to #1 (novel type),
   task 12 has +1.0 gap. Likely parser misroute or missing field in handler.
   Gain: up to +3.0 points.

### P1 — High value (T3 correctness)

3. **Test and fix bank_reconciliation T3** — 6 pts max. Handler exists but real-world
   scoring unknown. Run one E2E test against sandbox, check what scoring checks for.
   Fix any obvious bugs before submitting.

4. **Test and fix year_end_closing T3** — 6 pts max. Opening balance step uses BETA endpoint
   (`/ledger/voucher/openingBalance`) which returns 403 in competition sandboxes. Need
   alternative path or graceful skip of that step without taking a 4xx penalty.

5. **Test and fix correct_ledger_error T3** — 6 pts max. Multi-error mode implemented.
   Key risk: voucher search logic may fail to find the voucher the scorer set up.

6. **Test and fix monthly_closing T3** — 6 pts max. Handler exists. Scoring criteria unknown.

### P2 — Efficiency wins (only after P0/P1 correctness locked)

7. **Eliminate 4xx errors on T1 tasks 04, 06** — Both at 0.857; once at 1.0 correctness,
   efficiency bonus kicks in. Check what field checks fail.

8. **Reduce API calls on create_invoice + register_payment** — These run in fresh sandbox
   and do multiple GETs. `_create_customer_directly` already skips search; check if other
   intermediate GETs can be eliminated.

9. **Cache paymentType per request** — `get_bank_payment_type_id` calls `get_cached`
   but check that the cache key is per-client, not per-call.

### P3 — Nice to have (defer if time-constrained)

10. Self-verification GET-after-POST on critical T1 creates.
11. `?fields=id,name` on all search GETs.
12. Asyncio parallelization for independent prerequisite creation.

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Scoring formula | HIGH | Official docs confirm field-by-field + tier + efficiency bonus |
| Null-score cause analysis | MEDIUM | Hypotheses based on code review; actual cause requires submission log inspection |
| T3 handler correctness | LOW | Handlers exist but never scored — actual scoring criteria unknown until submission |
| Efficiency benchmark values | LOW | Competition does not publish benchmarks; only known from own best scores |
| BETA endpoint availability | HIGH | MEMORY confirms 403 = BETA, do not use |
| T2 low-score root cause | MEDIUM | Gap could be parser extraction, handler logic, or edge-case fields |

---

## Sources

- `docs/03-scoring.md` — Official scoring documentation (field-by-field, tier, efficiency)
- `docs/SYSTEMSTATUS.md` — Per-task score table, gap analysis
- `docs/TODO.md` — Backlog with existing prioritization
- `.planning/PROJECT.md` — Project context, constraints, key decisions
- `app/handlers/tier1.py` — T1 handler implementation review
- `app/handlers/tier2_invoice.py` — T2 invoice/payment handler review
- `app/handlers/tier3.py` — T3 handler implementation review (full file)
- `app/parser.py` — Task type list and keyword rules
- `app/error_patterns.json` — Known 4xx patterns per endpoint
