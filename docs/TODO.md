# Plan: Tripletex AI Accounting Agent

## Ferdig ✅

- [x] Infrastruktur-refaktor (config, models, tripletex client, parser, storage, handlers)
- [x] Tier 1 handlers: supplier, customer, employee, product, department (5 handlers)
- [x] Tier 2 handlers: invoice, payment, credit note, travel expense, project, updates (10 handlers)
- [x] Tier 2 extra: update/delete supplier/customer/product/employee, create_order, register_supplier_invoice (7 handlers)
- [x] Tier 3 voucher handlers: create_voucher, reverse_voucher, delete_voucher (3 handlers)
- [x] register_timesheet handler (timeregistrering)
- [x] LLM fallback-agent for ukjente oppgavetyper + placeholder-fix i paths
- [x] Parser med 26 oppgavetyper, Haiku + Sonnet fallback, 30s timeout
- [x] MVA-koder i parser (3=25%, 31=15%, 33=12%, 5=0%, 6=0%)
- [x] Konfidensbasert Sonnet-fallback (confidence < 0.80)
- [x] Few-shot examples i parser (3 eksempler)
- [x] Batch-oppgaver (parser + handler)
- [x] reverse_payment handler
- [x] Adresse-støtte på customer/supplier
- [x] Email-sync (_sync_email: sett begge email + invoiceEmail)
- [x] register_payment/credit_note/reverse_payment oppretter forutsetninger i tom sandbox
- [x] register_payment: bruker faktura inkl-MVA beløp (ikke ekskl-MVA)
- [x] create_credit_note: lagt til påkrevd date-param
- [x] Employee roller/entitlements (PUT /employee/entitlement/:grantEntitlementsByTemplate)
- [x] Deploy pipeline (Cloud Run europe-west1, API key, GCS logging)
- [x] CLI: status, show, insights, poll, submit, batch (6 kommandoer)
- [x] Automatisk submit via API (POST /tasks/{id}/submissions)
- [x] Pre-deploy test suite (10 tester)
- [x] Parser test-suite (26 ekte + 70 genererte prompts)
- [x] Error logging: 4xx response body lagres i GCS tracker
- [x] Systemdokumentasjon + analyse-rapport
- [x] Show oversetter automatisk ikke-norske prompts
- [x] Embedding-basert pre-klassifisering (Vertex AI text-embedding-005, 128 prompts, 17 typer)
- [x] Gemini 2.0 Flash parser-alternativ (PARSER_BACKEND=gemini)
- [x] RAG for Tripletex API-dokumentasjon (751 chunks)
- [x] Error pattern learning (112 mønstre)
- [x] API-kall-planlegging (call_planner.py)
- [x] 18 few-shot eksempler i parser
- [x] Keyword-fallback for custom_dimension, payroll, timesheet, etc.
- [x] E2E testsuite (32 tester, alle grønne, 132-138 API-kall)
- [x] Invoice bankkontonummer-fix (multi-strategi)
- [x] POST /employee/employment med startDate
- [x] create_invoice_from_pdf handler
- [x] set_project_fixed_price med delfakturering
- [x] create_custom_dimension handler
- [x] run_payroll handler
- [x] register_timesheet handler
- [x] Voucher handlers (create, reverse, delete)
- [x] CLI: errors-kommando (4xx-feilrapport)
- [x] build_embeddings.py, build_api_rag.py, build_error_patterns.py scripts

**Totalt: 30 registrerte handlers (inkl. unknown-fallback)**

---

# Backlog — prioritert etter poenggevinst

## KRITISK 🔴 (forventet +10-20 poeng)

### 1. Bank reconciliation (Tier 3 — åpner 2026-03-21)
- [ ] POST /bank/statement/import (multipart CSV-upload)
- [ ] POST /bank/reconciliation + match
**Impact: Tier 3 × 3 = opptil 6 poeng**

## HØY PRIORITET 🟠 (forventet +5-10 poeng)

### 2. Effektivitetsoptimalisering (dobler score ved perfekt)
- [ ] Cache vatType, paymentType, costCategory per request
- [ ] I fersk sandbox: POST customer direkte, ikke søk først
- [ ] Parallelliser uavhengige kall med asyncio.gather()
- [ ] Legg til ?fields=id,name på GET-kall
**Impact: dobler score på perfekte oppgaver**

### 3. Self-verifikasjon i handlers
- [ ] GET etter POST for å sjekke at felt ble lagret
- [ ] Korrigerende PUT ved avvik

## MEDIUM PRIORITET 🟡

### 4. Lokal scoring-verifikator
- [ ] Speiler konkurranse-scoring felt-for-felt

### 5. Pakk synkrone kall i asyncio.to_thread
- [ ] GCS-kall (save_to_gcs) — blokkerer FastAPI worker
- [ ] Anthropic API-kall (parse_task) — blokkerer

## LAV PRIORITET 🟢
- [ ] Validér ANTHROPIC_API_KEY ved oppstart
