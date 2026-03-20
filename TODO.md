# Plan: Tripletex AI Accounting Agent

## Ferdig ✅
- [x] Infrastruktur-refaktor (config, models, tripletex client, parser, storage, handlers)
- [x] Tier 1 handlers: supplier, customer, employee, product, department
- [x] Tier 2 handlers: invoice, payment, credit note, travel expense, project, updates
- [x] Parser med 18 oppgavetyper, Haiku + Sonnet fallback, 30s timeout
- [x] Deploy pipeline (Cloud Run europe-west1, API key, GCS logging)
- [x] CLI: status, show, insights, poll kommandoer
- [x] Pre-deploy test suite (10 tester)
- [x] Code review fikser (query params, None-sjekk, dueDate, JSON fallback)
- [x] MVA-koder i parser (3=25%, 31=15%, 33=12%)
- [x] Batch-oppgaver (parser + handler for "create 3 departments")
- [x] reverse_payment handler
- [x] Adresse-støtte på customer/supplier
- [x] Email-sync (_sync_email: sett begge email + invoiceEmail)
- [x] register_payment/credit_note/reverse_payment oppretter forutsetninger i tom sandbox
- [x] Employee roller/entitlements (PUT /employee/entitlement/:grantEntitlementsByTemplate)
- [x] LLM fallback-agent for ukjente oppgavetyper (app/handlers/fallback.py)
- [x] Tier 3 voucher handlers: create_voucher, reverse_voucher, delete_voucher
- [x] Systemdokumentasjon (SYSTEMDOKUMENTASJON.md, SYSTEMSTATUS.md)
- [x] Show oversetter automatisk ikke-norske/engelske prompts

---

# Backlog — prioritert etter poenggevinst

## KRITISK 🔴 (forventet +10-20 poeng)

### 1. ~~register_payment/credit_note forutsetninger~~ ✅ FERDIG
### 2. ~~Employee roller/entitlements~~ ✅ FERDIG
### 3. ~~LLM fallback-agent~~ ✅ FERDIG
### 4. ~~Tier 3 voucher handlers~~ ✅ FERDIG (mangler bank reconciliation)

### 5. Bank reconciliation (Tier 3)
- [ ] POST /bank/statement/import (multipart CSV-upload)
- [ ] POST /bank/reconciliation + match
**Impact: Tier 3 × 3 = opptil 6 poeng**

### 6. POST /employee/employment med startDate
- [ ] Etter POST /employee, opprett employment med startDate
- [ ] Parser ekstrakter allerede startDate men det sendes ikke
**Impact: 1-2 poeng per employee-oppgave**

## HØY PRIORITET 🟠 (forventet +5-10 poeng)

### 7. Few-shot examples i parser
- [ ] Legg til 2-3 eksempler per task_type fra loggede prompts
- [ ] Prioriter oppgaver som har feilet
- [ ] Hold under 3000 tokens totalt

### 8. Konfidensbasert Sonnet-fallback
- [ ] Etter Haiku-parse, sjekk confidence
- [ ] Confidence < 0.85 → re-parse med Sonnet

### 9. Nye handler-typer vi mangler
- [ ] `update_supplier` — GET /supplier → PUT
- [ ] `update_product` — GET /product → PUT
- [ ] `create_order` — POST /order (uten fakturering)
- [ ] `register_supplier_invoice` — leverandørfaktura
- [ ] `delete_employee` / `deactivate_employee`
- [ ] `delete_customer` / `delete_supplier`
- [ ] `create_invoice_from_pdf` — parse PDF-vedlegg

### 10. Effektivitetsoptimalisering (dobler score ved perfekt)
- [ ] Cache vatType, paymentType, costCategory
- [ ] Dropp GET /department for employee
- [ ] I fersk sandbox: POST customer direkte, ikke søk først
- [ ] Parallelliser uavhengige kall med asyncio.gather()
- [ ] Legg til ?fields=id,name på GET-kall

## MEDIUM PRIORITET 🟡

### 11. E2E test-suite
- [ ] Test hele flyten: prompt → parse → execute → verify-GET
- [ ] Bruk ekte prompts fra data/requests/
- [ ] Verifiser at felt faktisk lagres korrekt
- [ ] Regresjonstester fra feilede submissions

### 12. Self-verifikasjon i handlers
- [ ] GET etter POST for å sjekke at felt ble lagret
- [ ] Korrigerende PUT ved avvik

### 13. Lokal scoring-verifikator
- [ ] Speiler konkurranse-scoring felt-for-felt

### 14. Pakk synkrone kall i asyncio.to_thread
- [ ] GCS-kall (save_to_gcs)
- [ ] Anthropic API-kall (parse_task)

## LAV PRIORITET 🟢
- [ ] Flytt datetime-import til topp av filer
- [ ] Validér ANTHROPIC_API_KEY ved oppstart
- [ ] .gitignore for __pycache__
