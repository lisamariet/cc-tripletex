# Systemstatus — Tripletex AI Accounting Agent

Oppdatert: 2026-03-20

## Score
- **Total: 5.6 poeng** (nettsiden)
- **9 av 30 oppgavetyper løst**
- **2 perfekte** (create_customer 200%, create_project 200%)

## Implementert (14 handlers)

| Tier | Handler | API-kall | Status |
|------|---------|----------|--------|
| 1 | create_supplier | 1 (POST) | ✅ Email-sync fikset |
| 1 | create_customer | 1 (POST) | ✅ Perfekt 200% |
| 1 | create_employee | 2-3 (GET dept + POST + PUT entitlement) | ✅ Med roller |
| 1 | create_product | 1-2 (GET vatType + POST) | ✅ MVA-koder fikset |
| 1 | create_department | 1-2 (POST salesmodules + POST) | ✅ Inkl. batch |
| 2 | create_invoice | 3-5 (POST customer + GET vat + POST order + PUT :invoice) | ✅ |
| 2 | register_payment | 5-7 (opprett kjede + PUT :payment) | ✅ Oppretter forutsetninger |
| 2 | reverse_payment | 6-8 (opprett kjede + betaling + reversering) | ✅ Ny |
| 2 | create_credit_note | 5-6 (opprett kjede + PUT :createCreditNote) | ✅ |
| 2 | create_travel_expense | 4+ (GET emp + POST te + GET cat/pt + POST cost) | ✅ |
| 2 | delete_travel_expense | 2-3 (GET + DELETE) | ✅ |
| 2 | create_project | 2-3 (GET emp + GET/POST customer + POST project) | ✅ Perfekt 200% |
| 2 | update_employee | 2-3 (GET + PUT) | ✅ dateOfBirth fallback |
| 2 | update_customer | 2 (GET + PUT) | ✅ |

## Mangler (16+ oppgavetyper)

| Prioritet | Oppgavetype | Kommentar |
|-----------|-------------|-----------|
| 🔴 KRITISK | LLM fallback for "unknown" | 16+ typer gir 0p — trenger agentic fallback |
| 🔴 | create_voucher | Tier 3, parser kjenner den, ingen handler |
| 🔴 | reverse_voucher | Tier 3 |
| 🔴 | delete_voucher | Tier 3 |
| 🔴 | custom_dimension + voucher | Sett i submission — 0/13 |
| 🟠 | bank_reconciliation | Tier 3, CSV-import |
| 🟠 | update_supplier | Enkel, ligner update_customer |
| 🟠 | update_product | Enkel |
| 🟠 | register_supplier_invoice | Leverandørfaktura |
| 🟠 | create_order | Ordre uten fakturering |
| 🟠 | delete_employee/customer | DELETE-operasjoner |
| 🟠 | create_invoice_from_pdf | Fil-parsing |
| 🟡 | year_end_closing | Tier 3, kompleks |

## Kjente problemer
- Parser gir "unknown" for oppgaver vi ikke har definert → 0 poeng
- Ingen verifikasjons-GET etter POST (vet ikke om felt ble lagret)
- Tester sjekker bare at handler ikke krasjer, ikke at data er korrekt
- Oversettelse i CLI krever ANTHROPIC_API_KEY lokalt
- Sandbox mangler bankkontonummer → kan ikke teste invoice-flyt fullstendig

## Tier-tidslinje
- **Tier 1** — tilgjengelig fra start
- **Tier 2** — åpnet fredag 2026-03-20
- **Tier 3** — åpner lørdag 2026-03-21
