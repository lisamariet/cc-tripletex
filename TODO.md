# Plan: Tripletex AI Accounting Agent

## Fase 1: Infrastruktur-refaktor ✅
- [x] `app/config.py` — env vars
- [x] `app/models.py` — ParsedTask, APICallRecord, CallTracker
- [x] `app/tripletex.py` — TripletexClient med delt httpx, call tracking
- [x] `app/storage.py` — save_to_gcs()
- [x] `app/parser.py` — parse_task() med Haiku + Sonnet fallback
- [x] `app/file_processor.py` — base64 decode, bilde/PDF/CSV content blocks
- [x] `app/handlers/__init__.py` — HANDLER_REGISTRY + decorator
- [x] `app/main.py` — slanket til FastAPI + orchestration
- [x] Bugfiks: Alltid HTTP 200 + {"status": "completed"}
- [x] Bugfiks: Full session token i GCS
- [x] Bugfiks: Fjernet verifikasjons-GET

## Fase 2: Tier 1 handlers (×1 poeng) ✅
- [x] `create_supplier` — POST /supplier (1 kall) — verifisert mot sandbox
- [x] `create_customer` — POST /customer (1 kall) — verifisert mot sandbox
- [x] `create_employee` — GET /department + POST /employee (2 kall) — verifisert mot sandbox
- [x] `create_product` — GET /ledger/vatType + POST /product (1-2 kall) — verifisert mot sandbox
- [x] `create_department` — POST /company/salesmodules + POST /department (1-2 kall) — verifisert mot sandbox

## Fase 3: Parser-forbedring ✅
- [x] System prompt med alle 17 oppgavetyper
- [x] Claude Haiku som primærmodell, Sonnet som fallback
- [x] Støtte for filer: bilder, PDF, CSV
- [x] Alt i ett LLM-kall

## Fase 4: Tier 2 handlers (×2 poeng) ⚡ Implementert, ikke sandbox-testet
- [x] `create_invoice` — POST /customer → POST /order → PUT /order/:invoice (3 kall)
- [x] `register_payment` — GET /invoice → PUT /invoice/:payment (2 kall)
- [x] `create_credit_note` — GET /invoice → PUT /invoice/:createCreditNote (2 kall)
- [x] `create_travel_expense` — GET /employee → POST /travelExpense → POST /travelExpense/cost (3+ kall)
- [x] `delete_travel_expense` — GET /travelExpense → DELETE /travelExpense/{id} (2 kall)
- [x] `create_project` — GET /employee + POST /project (2 kall) — verifisert mot sandbox
- [x] `update_employee` — GET /employee → PUT /employee/{id} (2 kall)
- [x] `update_customer` — GET /customer → PUT /customer/{id} (2 kall)

## Fase 5: Tier 3 handlers (×3 poeng) ❌ Ikke startet
- [ ] `create_voucher` — POST /ledger/voucher med postings
- [ ] `reverse_voucher` — GET /ledger/voucher → PUT /:reverse
- [ ] `delete_voucher` — GET /ledger/voucher → DELETE
- [ ] Bank reconciliation — parse CSV + opprett vouchers
- [ ] Year-end closing

Tier 3 åpner lørdag — design basert på reelle oppgaver.

## Infrastruktur ✅
- [x] Deploy til Cloud Run (europe-west1)
- [x] ANTHROPIC_API_KEY satt som env var
- [x] GCS logging (requests + results)
- [x] CLI-script: `scripts/compete.py` (status + submit)
- [x] Test-script: `scripts/test_handlers.py` (sandbox-verifisering)

## Neste steg
- [x] **API key beskyttelse** — Bearer token auth på /solve (key: se .env eller Cloud Run env vars)
- [ ] **Insights dashboard** — Legg til analyse av API-kall: unødvendige kall, 4xx-feil, effektivitet per handler
- [ ] Sandbox-teste Tier 2 handlers (invoice, payment, travel expense)
- [ ] Kjøre submissions og analysere resultater
- [ ] Finjustere parser basert på feilede oppgaver
- [ ] Implementere Tier 3 når det åpner
