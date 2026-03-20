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

---

# Backlog — prioritert etter poenggevinst

## KRITISK 🔴 (forventet +10-20 poeng)

### 1. register_payment/credit_note MÅ opprette forutsetninger først
Sandboxen er TOM for hver submission. Disse handlerene antar at det finnes faktura.
- [ ] register_payment: opprett kunde → ordre → faktura → registrer betaling
- [ ] create_credit_note: opprett kunde → ordre → faktura → kreditnota
- [ ] reverse_payment: opprett kunde → ordre → faktura → registrer betaling → reverser
**Impact: 3 oppgavetyper × Tier 2 (×2) = opptil 12 poeng**

### 2. Employee roller/entitlements (50% av employee-poengene!)
Scoring-eksempel: "Administrator role assigned" = 5 av 10 poeng.
- [ ] Legg til `role`/`userType` felt i parser
- [ ] Undersøk API: `/employee/{id}/entitlement` eller liknende
- [ ] Sett rolle etter opprettelse
- [ ] POST /employee/employment med startDate
**Impact: 5 poeng per employee-oppgave**

### 3. LLM fallback-agent for ukjente oppgavetyper
16 av 30 oppgavetyper har ingen handler. Vi returnerer "No handler" = 0 poeng.
- [ ] Når task_type er "unknown" eller ikke har handler: bruk LLM til å generere API-kall
- [ ] Send prompt + Tripletex API-docs til LLM, la den bestemme kall-sekvens
- [ ] Selv 30% correctness > 0 poeng
**Impact: opptil 16 nye oppgavetyper × 0.5-2.0 poeng = 8-32 poeng**

### 4. Implementer Tier 3 handlers (åpner lørdag 2026-03-21)
- [ ] `create_voucher` — POST /ledger/voucher med postings (bruk amountGross, row>=1)
- [ ] `reverse_voucher` — PUT /ledger/voucher/{id}/:reverse?date=
- [ ] `delete_voucher` — DELETE /ledger/voucher/{id} (kun siste i serien)
- [ ] Bank reconciliation — POST /bank/statement/import + match
**Impact: Tier 3 × 3 = opptil 6 poeng per oppgave**

## HØY PRIORITET 🟠 (forventet +5-10 poeng)

### 5. Few-shot examples i parser
- [ ] Legg til 2-3 eksempler per task_type fra loggede prompts
- [ ] Prioriter oppgaver som har feilet (register_payment, create_employee)
- [ ] Hold under 3000 tokens totalt

### 6. Konfidensbasert Sonnet-fallback
- [ ] Etter Haiku-parse, sjekk confidence
- [ ] Confidence < 0.85 → re-parse med Sonnet
- [ ] Koster ~1s ekstra men gir bedre resultat

### 7. Nye handler-typer vi mangler
- [ ] `update_supplier` — GET /supplier → PUT
- [ ] `update_product` — GET /product → PUT
- [ ] `create_order` — POST /order (uten fakturering)
- [ ] `register_supplier_invoice` — leverandørfaktura
- [ ] `delete_employee` / `deactivate_employee`
- [ ] `delete_customer` / `delete_supplier`
- [ ] `create_invoice_from_pdf` — parse PDF-vedlegg

### 8. Effektivitetsoptimalisering (dobler score ved perfekt)
- [ ] Cache vatType, paymentType, costCategory (ikke hent på nytt hver gang)
- [ ] Dropp GET /department for employee (bruk direkte POST)
- [ ] I fersk sandbox: POST customer direkte, ikke søk først
- [ ] Parallelliser uavhengige kall med asyncio.gather()
- [ ] Legg til ?fields=id,name på GET-kall

## MEDIUM PRIORITET 🟡

### 9. E2E test-suite
- [ ] Test hele flyten: prompt → parse → execute → verify-GET
- [ ] Bruk ekte prompts fra data/requests/ + genererte for alle 7 språk
- [ ] Verifiser at felt faktisk lagres korrekt (ikke bare at 2xx returneres)
- [ ] Regresjonstester fra feilede submissions

### 10. Self-verifikasjon i handlers
- [ ] GET etter POST for å sjekke at felt ble lagret
- [ ] Logg avvik mellom sendt og lagret data
- [ ] Korrigerende PUT ved avvik

### 11. Lokal scoring-verifikator
- [ ] Speiler konkurranse-scoring felt-for-felt
- [ ] Prediker score lokalt før submission

### 12. Pakk synkrone kall i asyncio.to_thread
- [ ] GCS-kall (save_to_gcs)
- [ ] Anthropic API-kall (parse_task)

## LAV PRIORITET 🟢
- [ ] Flytt datetime-import til topp av filer
- [ ] Validér ANTHROPIC_API_KEY ved oppstart
- [ ] .gitignore for __pycache__
