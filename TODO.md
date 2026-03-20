# Plan: Tripletex AI Accounting Agent

## Ferdig

- [x] Infrastruktur-refaktor (config, models, tripletex client, parser, storage, handlers)
- [x] Tier 1 handlers: supplier, customer, employee, product, department (5 handlers)
- [x] Tier 2 handlers: invoice, payment, credit note, travel expense, project, updates (10 handlers)
- [x] Tier 2 extra: update_supplier, update_product, delete_employee, delete_customer, delete_supplier, create_order, register_supplier_invoice (7 handlers)
- [x] Tier 3 voucher handlers: create_voucher, reverse_voucher, delete_voucher (3 handlers)
- [x] LLM fallback-agent for ukjente oppgavetyper (app/handlers/fallback.py)
- [x] Parser med 25 oppgavetyper, Haiku + Sonnet fallback, 30s timeout
- [x] MVA-koder i parser (3=25%, 31=15%, 33=12%, 5=0%, 6=0%)
- [x] Konfidensbasert Sonnet-fallback (confidence < 0.80 -> re-parse med Sonnet)
- [x] Few-shot examples i parser (3 eksempler: spansk supplier, fransk payment, fransk employee)
- [x] Batch-oppgaver (parser + handler for "create 3 departments")
- [x] reverse_payment handler
- [x] Adresse-stotte pa customer/supplier
- [x] Email-sync (_sync_email: sett begge email + invoiceEmail)
- [x] register_payment/credit_note/reverse_payment oppretter forutsetninger i tom sandbox
- [x] Employee roller/entitlements (PUT /employee/entitlement/:grantEntitlementsByTemplate)
- [x] Deploy pipeline (Cloud Run europe-west1, API key, GCS logging)
- [x] CLI: status, show, insights, poll, submit kommandoer (5 kommandoer)
- [x] Pre-deploy test suite (10 tester)
- [x] Code review fikser (query params, None-sjekk, dueDate, JSON fallback)
- [x] Systemdokumentasjon (SYSTEMDOKUMENTASJON.md, SYSTEMSTATUS.md)
- [x] Show oversetter automatisk ikke-norske/engelske prompts

**Totalt: 26 registrerte handlers + 1 fallback**

---

# Backlog — prioritert etter poenggevinst

## KRITISK (forventet +10-20 poeng)

### 1. Bank reconciliation (Tier 3)
- [ ] POST /bank/statement/import (multipart CSV-upload)
- [ ] POST /bank/reconciliation + match
**Impact: Tier 3 x 3 = opptil 6 poeng**

### 2. POST /employee/employment med startDate
- [ ] Etter POST /employee, opprett employment med startDate
- [ ] Parser ekstrakter allerede startDate men det sendes ikke
**Impact: 1-2 poeng per employee-oppgave**

## HOY PRIORITET (forventet +5-10 poeng)

### 3. Flere few-shot examples i parser
- [ ] Utvid fra 3 til 5-8 eksempler, prioriter oppgaver som har feilet
- [ ] Hold under 3000 tokens totalt
**Impact: bedre parsing-presisjon, faerre feil**

### 4. Nye handler-typer vi mangler
- [ ] `create_invoice_from_pdf` — parse PDF-vedlegg
**Impact: 1 ny oppgavetype**

### 5. Effektivitetsoptimalisering (dobler score ved perfekt)
- [ ] Cache vatType, paymentType, costCategory
- [ ] Dropp GET /department for employee
- [ ] I fersk sandbox: POST customer direkte, ikke sok forst
- [ ] Parallelliser uavhengige kall med asyncio.gather()
- [ ] Legg til ?fields=id,name pa GET-kall
**Impact: hoyere efficiency-score pa alle oppgaver**

## MEDIUM PRIORITET

### 6. E2E test-suite
- [ ] Test hele flyten: prompt -> parse -> execute -> verify-GET
- [ ] Bruk ekte prompts fra data/requests/
- [ ] Verifiser at felt faktisk lagres korrekt
- [ ] Regresjonstester fra feilede submissions

### 7. Self-verifikasjon i handlers
- [ ] GET etter POST for a sjekke at felt ble lagret
- [ ] Korrigerende PUT ved avvik

### 8. Lokal scoring-verifikator
- [ ] Speiler konkurranse-scoring felt-for-felt

### 9. Pakk synkrone kall i asyncio.to_thread
- [ ] GCS-kall (save_to_gcs)
- [ ] Anthropic API-kall (parse_task)

## LAV PRIORITET

- [ ] Flytt datetime-import til topp av filer
- [ ] Valider ANTHROPIC_API_KEY ved oppstart
- [ ] .gitignore for __pycache__
