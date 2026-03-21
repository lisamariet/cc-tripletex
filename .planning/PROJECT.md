# Tripletex AI Accounting Agent — NM i AI 2026

## What This Is

En AI-agent som løser regnskapsoppgaver i Tripletex for NM i AI 2026-konkurransen. Agenten mottar et prompt (på 7 språk), bruker Tripletex API via proxy for å utføre oppgaven, og scores på korrekthet og effektivitet. Deployert på Cloud Run, med embedding-basert parser, 33 handlers, og E2E-testsuite.

## Core Value

Maks poengscore på alle 30 oppgavetyper — perfekt korrekthet + minimal API-kall + null 4xx-feil = opptil 6.0 per Tier 3-task.

## Requirements

### Validated

- ✓ `/solve` endpoint med FastAPI — existing
- ✓ Embedding-parser (Vertex AI) + LLM (Haiku/Gemini) + keyword-fallback — existing
- ✓ 33 handlers for alle kjente oppgavetyper — existing
- ✓ E2E testsuite (32 tester, alle grønne) — existing
- ✓ Deploy pipeline Cloud Run europe-west1 — existing
- ✓ CLI-verktøy (status, show, submit, poll, errors) — existing
- ✓ RAG for Tripletex API-docs (751 chunks) — existing
- ✓ Error pattern learning (112 mønstre) — existing
- ✓ Tier 1 handlers: create_supplier, create_customer, create_employee, create_product, create_department — existing
- ✓ Tier 2 handlers: invoice, payment, credit note, travel expense, project, updates — existing
- ✓ Tier 3 handlers: voucher ops, bank_reconciliation, year_end_closing, correct_ledger_error, monthly_closing, custom_dimension — existing

### Active

- [ ] Fiks 4 nullscore-tasks (09, 11, 12, 17) — identifiser og fiks handlers
- [ ] Forbedre lav-score tasks (04, 06, 10, 13, 15, 16, 18) — feilanalyse + handler-forbedring
- [ ] Tier 3 optimalisering — bank_reconciliation, year_end_closing, correct_ledger_error, monthly_closing
- [ ] Effektivitetsoptimalisering — reduser API-kall, eliminer 4xx-feil, cache vatType/paymentType
- [ ] Self-verifikasjon i handlers — GET etter POST for å validere felt
- [ ] Nye Tier 3 oppgavetyper — identifiser og implementer eventuelle ukjente T3-tasks

### Out of Scope

- UI/dashboard — ikke relevant for score
- Lokal scoring-verifikator — nice to have, men tid er knapp
- Asyncio refaktor (to_thread) — marginal gevinst vs. risiko

## Context

- **Konkurranse:** NM i AI 2026, kategori "Tripletex AI Accounting Agent"
- **Tier 3 åpnet:** 2026-03-21 (i dag) — opptil 12 nye oppgavetyper med ×3 multiplier
- **Deadline:** 2026-03-22 (i morgen)
- **Nåværende score:** 21.65 / 52 mulig (Tier 1+2). #1 har 44.41
- **Nullscore-tasks:** 09 (T2), 11 (T1), 12 (T1), 17 (T2) — ukjent hva disse er
- **Scoring:** korrekthet × tier × (1 + effektivitetsbonus). Perfekt = opptil 2× tier
- **Brownfield:** Moden kodebase med 33 handlers, E2E-tester, ML-pipeline
- **Sandbox-token utløper:** 2026-03-31
- **Rate limits:** 3 samtidige submissions, 5 per task per dag (verifisert team)
- **BETA-endpoints:** Unngå — gir 403. Ny token per submit. 120s timeout

## Constraints

- **Tidsfrist**: 24 timer igjen — alt arbeid må ha direkte poengeffekt
- **Rate limits**: 5 forsøk per task per dag — kan ikke brute-force
- **Timeout**: 5 min per submission — agent må være effektiv
- **Fersk sandbox**: Hver submission starter med tom konto — forutsetninger må opprettes
- **7 språk**: Prompts på nb, en, es, pt, nn, de, fr — parser må håndtere alle
- **Deploy**: Cloud Run europe-west1 — alltid test mot sandbox med E2E før deploy
- **Ingen submit uten tillatelse**: Brukeren må godkjenne før vi submitter

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Embedding-parser + LLM + keyword-fallback | Tre-lags parsing gir best dekning | ✓ Good |
| Claude Haiku som default parser | Raskere + billigere enn Sonnet, god nok accuracy | ✓ Good |
| Handler-per-task arkitektur | Deterministisk, testbar, ingen LLM-variasjon i utførelse | ✓ Good |
| Prioriter nullscore + lav-score først | Størst poenggevinst per tid investert | — Pending |
| Tier 3 focus i dag | T3 åpner i dag, ×3 multiplier = høyest poengverdi | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd:transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd:complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-03-21 after initialization*
