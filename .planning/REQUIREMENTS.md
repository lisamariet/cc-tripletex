# Requirements: Tripletex AI Accounting Agent — Score Optimization

**Defined:** 2026-03-21
**Core Value:** Maks poengscore på alle 30 oppgavetyper — perfekt korrekthet + effektivitetsbonus

## v1 Requirements

### Nullscore-diagnose og -fiks

- [ ] **NULL-01**: Identifiser task_type for task 09, 11, 12, 17 via GCS-logger/submissions
- [x] **NULL-02**: Fiks parser-klassifisering for alle 4 nullscore-tasks
- [x] **NULL-03**: Fiks/opprett manglende handlers for nullscore-tasks
- [ ] **NULL-04**: Verifiser nullscore-fixer mot sandbox E2E

### Lav-score korrekthet

- [x] **CORR-01**: Fiks felt-mapping på task 04 (T1, score 0.86 → 1.0)
- [x] **CORR-02**: Fiks felt-mapping på task 06 (T1, score 0.86 → 1.0)
- [x] **CORR-03**: Forbedre task 10 (T2, score 1.63 → 3.7+)
- [x] **CORR-04**: Forbedre task 13 (T2, score 1.38 → 3.1+)
- [x] **CORR-05**: Forbedre task 15 (T2, score 0.50 → 4.0)
- [x] **CORR-06**: Forbedre task 16 (T2, score 1.00 → 3.8)
- [x] **CORR-07**: Forbedre task 18 (T2, score 1.50 → 3.3+)

### Tier 3 optimalisering

- [x] **T3-01**: Test og tune bank_reconciliation mot T3-scoring
- [x] **T3-02**: Test og tune year_end_closing mot T3-scoring
- [x] **T3-03**: Test og tune correct_ledger_error mot T3-scoring
- [x] **T3-04**: Test og tune monthly_closing mot T3-scoring
- [x] **T3-05**: Identifiser og implementer eventuelle nye T3-oppgavetyper
- [x] **T3-06**: Fjern alle BETA-endpoint-kall fra T3-handlers

### Effektivitet

- [ ] **EFF-01**: Eliminer 4xx-feil fra alle handler-sekvenser
- [ ] **EFF-02**: Bruk get_cached() konsekvent for vatType/paymentType/costCategory
- [ ] **EFF-03**: Legg til ?fields= projeksjon på alle GET-kall
- [ ] **EFF-04**: Fjern unødvendige GET-before-POST i fersk sandbox
- [ ] **EFF-05**: Implementer asyncio.gather() for parallelle uavhengige kall i T3

## v2 Requirements

### Avansert optimalisering (kun hvis tid)

- **ADV-01**: Self-verifikasjon i T3-handlers (GET etter POST for felt-validering)
- **ADV-02**: Cache-invalidering for intra-request entity-opprettelser
- **ADV-03**: Lokal scoring-verifikator som speiler felt-for-felt-sjekk

## Out of Scope

| Feature | Reason |
|---------|--------|
| Generisk LLM-basert handler | Ikke-deterministisk, treg, token-krevende |
| Full asyncio refaktor (to_thread) | Marginal gevinst vs risiko for regresjon |
| UI/dashboard | Null score-impact |
| ML retraining (embeddings, RAG) | 30+ min, marginal parser-forbedring |
| Dynamic Tripletex module activation | 422 i sandboxes, koster 4xx |
| BETA endpoints | 403 = sløst kall + 4xx-straff |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| CORR-01 | Phase 1 | Complete |
| CORR-02 | Phase 1 | Complete |
| CORR-03 | Phase 1 | Complete |
| CORR-04 | Phase 1 | Complete |
| CORR-05 | Phase 1 | Complete |
| CORR-06 | Phase 1 | Complete |
| CORR-07 | Phase 1 | Complete |
| T3-01 | Phase 1 | Complete |
| T3-02 | Phase 1 | Complete |
| T3-03 | Phase 1 | Complete |
| T3-04 | Phase 1 | Complete |
| T3-05 | Phase 1 | Complete |
| T3-06 | Phase 1 | Complete |
| NULL-01 | Phase 2 | Pending |
| NULL-02 | Phase 2 | Complete |
| NULL-03 | Phase 2 | Complete |
| NULL-04 | Phase 2 | Pending |
| EFF-01 | Phase 3 | Pending |
| EFF-02 | Phase 3 | Pending |
| EFF-03 | Phase 3 | Pending |
| EFF-04 | Phase 3 | Pending |
| EFF-05 | Phase 3 | Pending |

**Coverage:**
- v1 requirements: 22 total
- Mapped to phases: 22
- Unmapped: 0 ✓
- Phase 4 (T3 Robusthet): Ingen egne v1-krav — leverer robusthet-gevinst fra T3/EFF-arbeidet i Phase 1+3

---
*Requirements defined: 2026-03-21*
*Last updated: 2026-03-21 — Phase-rekkefølge snudd: T3+CORR → Phase 1, NULL → Phase 2 (Tier 3 åpner i dag)*
