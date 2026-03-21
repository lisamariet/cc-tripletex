---
phase: 02-nullscore-fix
plan: 02
subsystem: parser
tags: [parser, classification, year_end_closing, monthly_closing, batch, handlers]

# Dependency graph
requires:
  - phase: 02-nullscore-fix
    provides: Nullscore-diagnose fra plan 01 — identifisert at feil task_type og manglende feilhåndtering er rootcause
provides:
  - Parser korrekt disambiguerer year_end_closing vs monthly_closing for alle 7 språkvarianter
  - create_department handler med eksplisitt feilhåndtering
  - Batch-mekanisme med logging av tomme resultater
affects: [alle handlers som bruker parser-output, batch_create_department, year_end_closing, monthly_closing]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "_YEAR_END_SIGNALS regex-override: year-end context overstyrer monthly_closing-signals"
    - "Toveis disambiguering: sjekker BEGGE veier (year_end → monthly, monthly → year_end)"

key-files:
  created: []
  modified:
    - app/parser.py
    - app/handlers/tier1.py
    - app/handlers/__init__.py

key-decisions:
  - "Toveis disambiguering: månedlige avskrivnings-regler matcher FØR year_end_closing-regler, så begge veier må håndteres"
  - "create_order har allerede korrekt orderLines-håndtering — ingen endring nødvendig"

patterns-established:
  - "Disambiguering-mønster: legg til _YEAR_END_SIGNALS check i BEGGE grener (year_end med monthly-signal, og monthly med year-end-signal)"

requirements-completed: [NULL-02, NULL-03]

# Metrics
duration: 15min
completed: 2026-03-21
---

# Phase 02 Plan 02: Parser + Handler Robusthet Summary

**Parser disambiguerer year_end_closing vs monthly_closing via toveis _YEAR_END_SIGNALS override, og create_department handler har eksplisitt feilhåndtering**

## Performance

- **Duration:** 15 min
- **Started:** 2026-03-21T15:05:00Z
- **Completed:** 2026-03-21T15:20:00Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- _YEAR_END_SIGNALS regex med støtte for alle 7 språk (nb, en, es, pt, nn, de, fr)
- Toveis disambiguering: year_end+monthly → year_end_closing, monthly+year_end → year_end_closing
- create_department: returnerer beskrivende feilmelding ved tomt API-resultat (ingen silent empty dict)
- Batch-mekanisme: logger warnings for items med tomt created-resultat for debugging

## Task Commits

1. **Task 1: Fiks parser year_end_closing vs monthly_closing disambiguering** - `a6935f2` (fix)
2. **Task 2: Fiks handler-robusthet for batch_create_department og create_order** - `182a0a3` (fix)

## Files Created/Modified
- `app/parser.py` - Lagt til _YEAR_END_SIGNALS, toveis disambiguering i _infer_task_type_from_keywords
- `app/handlers/tier1.py` - create_department: eksplisitt feilhåndtering ved tomt API-resultat
- `app/handlers/__init__.py` - Batch-mekanisme: logging av tomme created-resultater

## Decisions Made
- Toveis disambiguering var nødvendig fordi keyword-reglene evalueres top-down og monthly_closing-reglene (avskrivning/depreciation) matcher FØR year_end_closing-reglene rekker å returnere.
- create_order sender allerede orderLines korrekt i payload — ingen endring nødvendig.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Toveis disambiguering for monthly → year_end**
- **Found during:** Task 1 (parser-verifisering)
- **Issue:** Plan antok bare én vei (year_end + monthly → monthly_closing), men i praksis treffer "depreciación" monthly_closing-regelen FØR year_end_closing-regelen evalueres, så den omvendte sjekken var også nødvendig.
- **Fix:** La til sjekk: hvis task_type==monthly_closing AND _YEAR_END_SIGNALS i prompt → returner year_end_closing
- **Files modified:** app/parser.py
- **Verification:** Alle 4 tester passerer inkl. spansk "cierre anual simplificado"
- **Committed in:** a6935f2

---

**Total deviations:** 1 auto-fixed (Rule 1 - bug i planforutsetning om disambiguerings-retning)
**Impact on plan:** Nødvendig korreksjon for at alle 4 testvarianter skulle passere. Ingen scope-creep.

## Issues Encountered
- Spansk test "cierre anual simplificado de 2025: depreciación y provisión fiscal" feilet fordi "depreciación" matcher monthly_closing-keyword-regelen som evalueres før year_end_closing-regelen. Løst med toveis disambiguering.

## Next Phase Readiness
- Parser klassifiserer year_end_closing korrekt for alle 7 språkvarianter
- create_department er robust mot tomt API-svar
- Klar for E2E-testing og deploy for nullscore-fix

---
*Phase: 02-nullscore-fix*
*Completed: 2026-03-21*
