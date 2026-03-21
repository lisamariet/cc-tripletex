# Roadmap: Tripletex AI Accounting Agent — Score Optimization

## Overview

Agenten er allerede deployert og funksjonell med 21.65/52 poeng. Roadmapen driver maksimering av poengscoren innen 24-timers deadline (2026-03-22). Tier 3 åpner i dag (2026-03-21) med ×3-multiplier — T3-tuning og T1/T2-korrekthet prioriteres FØRST for å begynne å hente inn scored data umiddelbart. Nullscore-diagnose krever GCS-logg-analyse og tar lenger tid, og gjøres i Phase 2. Effektivitetsbonus aktiveres etter korrekthet er låst.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Korrekthet & Tier 3** - T1/T2 lav-score til 1.0 + T3 handlers tunet for ×3-poeng (completed 2026-03-21)
- [ ] **Phase 2: Nullscore Fix** - Diagnostiser og fiks de 4 taskene som scorer 0 (09, 11, 12, 17)
- [ ] **Phase 3: Effektivitet** - Eliminer 4xx + reduser kall-antall for å aktivere effektivitetsbonus
- [ ] **Phase 4: T3 Robusthet** - Timeout-sikring og stabilisering av T3-handlers

## Phase Details

### Phase 1: Korrekthet & Tier 3
**Goal**: T1/T2 lav-score tasks når 1.0 korrekthet + T3-handlers er tunet for maksimal ×3-score
**Depends on**: Nothing (first phase)
**Requirements**: CORR-01, CORR-02, CORR-03, CORR-04, CORR-05, CORR-06, CORR-07, T3-01, T3-02, T3-03, T3-04, T3-05, T3-06
**Success Criteria** (what must be TRUE):
  1. Task 04 og 06 scorer 1.0 korrekthet (alle felt korrekte, 0.857 → 1.0)
  2. Task 10, 13, 15, 16, 18 scorer høyere korrekthet enn nåværende (dokumentert forbedring)
  3. Bank_reconciliation og year_end_closing gir poeng > 0 ved T3-innsending
  4. Correct_ledger_error og monthly_closing gir poeng > 0 ved T3-innsending
  5. Ingen BETA-endpoint-kall i T3-handlers (null 403 fra BETA på T3-oppgaver)
**Plans:** 4/4 plans complete

Plans:
- [x] 01-01-PLAN.md — Fiks felt-mapping for task 04 og 06 (T1, CORR-01/02)
- [x] 01-02-PLAN.md — Diagnostiser og fiks T2 lav-score tasks 10, 13, 15, 16, 18 (CORR-03-07)
- [x] 01-03-PLAN.md — Fjern BETA-kall + tune bank_reconciliation og year_end_closing (T3-01/02/06)
- [x] 01-04-PLAN.md — Tune correct_ledger_error + monthly_closing + identifiser T3-typer (T3-03/04/05)

### Phase 2: Nullscore Fix
**Goal**: Alle fire nullscore-tasks (09, 11, 12, 17) leverer ikke-null score ved neste innsending
**Depends on**: Phase 1
**Requirements**: NULL-01, NULL-02, NULL-03, NULL-04
**Success Criteria** (what must be TRUE):
  1. GCS-logger viser korrekt task_type for task 09, 11, 12 og 17 — ikke "unknown" eller feil type
  2. E2E-tester for alle fire tasks passerer mot sandbox uten feil
  3. Submit av task 09 og/eller 17 (T2) gir score > 0 på leaderboard
  4. Submit av task 11 og/eller 12 (T1) gir score > 0 på leaderboard
**Plans:** 2/3 plans executed

Plans:
- [x] 02-01-PLAN.md — Deploy Cloud Run + fiks compete.py tooling (score-beregning, submit-throttling)
- [x] 02-02-PLAN.md — Fiks parser-disambiguering og handler-robusthet for nullscore-tasks
- [x] 02-03-PLAN.md — E2E-verifiser nullscore-fikser mot sandbox og deploy

### Phase 3: Effektivitet
**Goal**: Alle handlers med 1.0 korrekthet utløser effektivitetsbonus ved å minimere API-kall og eliminere 4xx
**Depends on**: Phase 2
**Requirements**: EFF-01, EFF-02, EFF-03, EFF-04, EFF-05
**Success Criteria** (what must be TRUE):
  1. Null 4xx-feil på happy path for alle ferdig-rettede handlers (verifisert i E2E)
  2. get_cached() brukes konsekvent for vatType, paymentType og costCategory i alle handlers
  3. Alle GET-kall har ?fields=-projeksjon (bekreftet i kode-review)
  4. Minst én handler som tidligere hadde effektivitetsbonus < 1.0 viser forbedret bonus etter submit
**Plans**: TBD

Plans:
- [ ] 03-01: Eliminer 4xx-feil + konsistentiser get_cached() på tvers av handlers
- [ ] 03-02: Legg til ?fields=-projeksjon + fjern unødvendige GET-before-POST + asyncio.gather()

### Phase 4: T3 Robusthet
**Goal**: T3-handlers fullfører innen 90 sekunder uten timeout eller MAX_API_CALLS-feil uansett prompt-variant
**Depends on**: Phase 3
**Requirements**: (ingen egne v1-krav — robusthet-gevinst fra T3-01 til T3-06 + EFF-05)
**Success Criteria** (what must be TRUE):
  1. Year_end_closing trigger ikke RuntimeError fra MAX_API_CALLS-grense i noen E2E-variant
  2. Bank_reconciliation fullfører innen 90s på alle sandboxkjøringer
  3. T3-handlers E2E-suite er 100% grønn etter alle timeout-/robusthet-fikser
**Plans**: TBD

Plans:
- [ ] 04-01: Profiler T3 E2E execution time + fiks timeout-risiko i year_end_closing og bank_reconciliation

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Korrekthet & Tier 3 | 4/4 | Complete   | 2026-03-21 |
| 2. Nullscore Fix | 2/3 | In Progress|  |
| 3. Effektivitet | 0/2 | Not started | - |
| 4. T3 Robusthet | 0/1 | Not started | - |
