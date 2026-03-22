---
phase: 05-score-maksimering-og-stabilisering
plan: 01
subsystem: api
tags: [tripletex, fields-projection, 400-errors, handlers, e2e]

# Dependency graph
requires:
  - phase: 03-effektivitet
    provides: "fields= projections added to GET-calls for efficiency"
  - phase: 04-t3-robusthet
    provides: "Robust T3 handler implementations"
provides:
  - "Validated fields= projections in all handler GET-calls — no 400 errors from invalid field names"
  - "E2E-verified (72 tests, 0 failures) after field projection fixes"
affects: [05-02, 05-03]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Only use confirmed-valid fields in Tripletex fields= projections"
    - "For /ledger/annualAccount: isClosed is not in AnnualAccountDTO — use id,year only"
    - "For /invoice: amountRemainingCurrency and amountOutstandingCurrency are not in InvoiceDTO — use amountOutstanding"

key-files:
  created: []
  modified:
    - app/handlers/tier3.py

key-decisions:
  - "/ledger/annualAccount: remove isClosed from fields= — confirmed invalid via error_patterns.json (400 with specific field message)"
  - "/invoice bank_reconciliation: replace amountRemainingCurrency with amountOutstanding — amountRemainingCurrency is not in InvoiceDTO"
  - "/supplierInvoice bank_reconciliation: same fix as /invoice — use amountOutstanding for consistency and safety"
  - "GET /activity fields=id,name,version kept as-is — error_patterns 400 was unspecified (not field-related), basic fields are safe"

patterns-established:
  - "Verify all fields= projections against error_patterns.json before adding"
  - "When field validity is uncertain, use amountOutstanding not amountRemainingCurrency/amountOutstandingCurrency"

requirements-completed: []

# Metrics
duration: 15min
completed: 2026-03-22
---

# Phase 5 Plan 1: Fields Projection Audit Summary

**Removed 3 invalid fields= parameter values causing 400 errors in bank_reconciliation and year_end_closing handlers**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-03-22T02:00:00Z
- **Completed:** 2026-03-22T02:15:00Z
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments

- Audited all `fields=` projections across 6 handler files using grep + error_patterns.json cross-reference
- Fixed 3 confirmed-invalid field names in tier3.py causing 400 errors
- E2E suite ran 72 tests, all passed, 0 failures, 383 API calls total

## Task Commits

1. **Task 1: Audit og fiks fields= projeksjoner i alle handler-filer** - `7bd42f2` (fix)
2. **Task 2: E2E-verifiser at alle handlers kjorer uten 400-feil** - E2E passed, no code changes needed

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `app/handlers/tier3.py` - Removed 3 invalid field names from fields= projections in bank_reconciliation and year_end_closing handlers

## Decisions Made

- Kept `GET /activity` with `fields=id,name,version` — the 400 in error_patterns was unspecified (no field listed), basic fields are standard and safe
- Used `amountOutstanding` as the safe replacement for `amountRemainingCurrency` in both `/invoice` and `/supplierInvoice` calls — it's the confirmed valid field per InvoiceDTO

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None — all 3 confirmed-invalid fields were cleanly identified from error_patterns.json and fixed without ambiguity.

## Known Stubs

None.

## Next Phase Readiness

- All handler GET-calls now use validated fields= projections
- E2E suite confirms no regressions (72/72 green)
- Ready for Phase 05-02 (score optimization)

## Self-Check: PASSED

- `app/handlers/tier3.py` — confirmed modified (git commit 7bd42f2)
- E2E: 72 passed, 0 failed

---
*Phase: 05-score-maksimering-og-stabilisering*
*Completed: 2026-03-22*
