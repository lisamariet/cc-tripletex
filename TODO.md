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

**Totalt: 26 registrerte handlers + 1 fallback**

---

# Backlog — prioritert etter poenggevinst

## KRITISK 🔴 (forventet +10-20 poeng)

### 1. Bank reconciliation (Tier 3 — åpner i morgen)
- [ ] POST /bank/statement/import (multipart CSV-upload)
- [ ] POST /bank/reconciliation + match
**Impact: Tier 3 × 3 = opptil 6 poeng**

### 2. POST /employee/employment med startDate
- [ ] Etter POST /employee, opprett employment med startDate
- [ ] Parser ekstrakter allerede startDate men det sendes ikke til API
**Impact: 1-2 poeng per employee-oppgave**

### 3. Invoice bankkontonummer-problemet
- [ ] PUT /order/:invoice feiler med "selskapet har ikke registrert bankkontonummer"
- [ ] Kan ikke settes via API — undersøk om det finnes en workaround
- [ ] Eller: test om konkurransen alltid har det konfigurert (kanskje vi var uheldige)
**Impact: create_invoice gir alltid 0 poeng uten dette**

## HØY PRIORITET 🟠 (forventet +5-10 poeng)

### 4. Flere few-shot examples i parser
- [ ] Utvid fra 3 til 5-8 eksempler
- [ ] Legg til eksempler for: timesheet, voucher, batch, credit note
**Impact: bedre parsing-presisjon**

### 5. Effektivitetsoptimalisering (dobler score ved perfekt)
- [ ] Cache vatType, paymentType, costCategory per request
- [ ] I fersk sandbox: POST customer direkte, ikke søk først
- [ ] Parallelliser uavhengige kall med asyncio.gather()
- [ ] Legg til ?fields=id,name på GET-kall
**Impact: dobler score på perfekte oppgaver**

### 6. create_invoice_from_pdf
- [ ] Parse PDF-vedlegg for fakturadata
- [ ] Bruk file_processor.py (allerede støtter PDF)
**Impact: 1 ny oppgavetype**

## MEDIUM PRIORITET 🟡

### 7. E2E test-suite med verifikasjons-GET
- [ ] Test hele flyten: prompt → parse → execute → GET-verifiser
- [ ] Bruk ekte prompts fra data/requests/
- [ ] Verifiser at felt faktisk lagres korrekt (ikke bare 2xx)

### 8. Self-verifikasjon i handlers
- [ ] GET etter POST for å sjekke at felt ble lagret
- [ ] Korrigerende PUT ved avvik

### 9. Lokal scoring-verifikator
- [ ] Speiler konkurranse-scoring felt-for-felt

### 10. Kjør batch submissions for å treffe flere oppgavetyper
- [ ] Vi har 180/dag, bare brukt ~20
- [ ] Mål: treffe alle 30 oppgavetyper
- [ ] Analyser resultater og fiks

### 11. Pakk synkrone kall i asyncio.to_thread
- [ ] GCS-kall (save_to_gcs) — blokkerer FastAPI worker
- [ ] Anthropic API-kall (parse_task) — blokkerer

## LAV PRIORITET 🟢
- [ ] Flytt datetime-import til topp av filer
- [ ] Validér ANTHROPIC_API_KEY ved oppstart
- [ ] .gitignore for __pycache__
