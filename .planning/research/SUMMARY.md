# Project Research Summary

**Project:** Tripletex AI Accounting Agent — NM i AI 2026
**Domain:** Competition AI scoring optimization (brownfield, Tier 3 opens today)
**Researched:** 2026-03-21
**Confidence:** HIGH

## Executive Summary

Dette er ikke et greenfield-prosjekt — agenten er allerede deployert og funksjonell med 21.65/52 poeng. Dagens prioritet er å gå fra nåværende score til maksimal score innen 24 timer. Tier 3 åpner nå (lørdag 2026-03-21), noe som betyr at ×3-multiplikatoren på 4 handlers (bank_reconciliation, year_end_closing, correct_ledger_error, monthly_closing) er aktivert, med potensielt 24 poeng tilgjengelig bare fra disse. I tillegg er det 4 nullscore-oppgaver (09, 11, 12, 17) som alene representerer opptil ~10 tapte poeng.

Scoringformelen har en kritisk ikke-linearitet: effektivitetsbonus aktiveres **kun ved correctness = 1.0**. En oppgave som er 90% korrekt scorer `0.9 × tier` uten effektivitetsbonus; en som er 100% korrekt med 20 ekstra API-kall kan scorer `~2.0 × tier`. Dette betyr at rekkefølgen er ikke valgfri: **nullscore → korrekthet → effektivitet** er den eneste riktige prioriteringsordenen. Å optimalisere kall-antallet på en handler som fremdeles har feil felt er meningsløst.

Systemarkitekturen er solid (FastAPI, asyncio, httpx, Gemini+Haiku parser, TripletexClient med caching og SmartRetry). De viktigste tekniske gapene er: 1) ingen `asyncio.gather()` — alle API-kall er sekvensielle, 2) `get_cached()` finnes men brukes ikke konsekvent i alle handlers, 3) `?fields=`-projeksjon mangler på de fleste GET-kall, og 4) parser-klassifiseringen svikter for oppgave 09, 11, 12, 17. Disse er alle lavrisiko-fikser med høy score-impact.

---

## Key Findings

### Recommended Stack

Stacken er riktig og skal ikke endres. Nøkkelteknologiene er Python 3.12 + FastAPI for async request-håndtering, httpx.AsyncClient for connection-pooling på tvers av Tripletex-kall, og Gemini 2.5-flash som primær parser med Claude Haiku som fallback. Vertex AI text-embedding-005 (768-dim) brukes som første filter i parser-pipelinen.

Det som skal **tillegges** (ikke endre eksisterende): `asyncio.gather()` på parallelle reference-oppslag, konsekvent `?fields=id,name,...` på alle GET-kall, og dedikert `parse_bank_statement_csv()` funksjon for strukturert CSV-parsing (stdlib `csv` — ikke pandas). `POST /ledger/voucher/importDocument` er verdt å teste for PDF-faktura-import som alternativ til LLM-ekstraksjon.

**Kjerneteknologier:**
- Python 3.12 + FastAPI 0.115.6 — async-nativ, 120s timeout håndteres korrekt
- httpx 0.27.0+ AsyncClient — single shared instance, connection pooling; ALDRI opprett ny per kall
- Gemini 2.5-flash (Vertex AI) — multimodal PDF/CSV, 8192 output tokens
- Claude Haiku fallback — pålitelig; SDK håndterer retries automatisk
- `asyncio.gather()` — IKKE implementert ennå; høyest prioritet for T3-ytelse
- stdlib `csv` — tilstrekkelig for norske bankutskrifter; pandas skal IKKE legges til (50MB+)

### Expected Features

**Må ha (table stakes) — mangler gir nullscore:**
- Korrekt handler for alle 33 kjente oppgavetyper — 4 nullscore-oppgaver (09, 11, 12, 17) mangler enten handler eller parser-routing
- Parser identifiserer riktig task_type på alle 7 språk — svikter for de 4 nullscore-oppgavene
- Null 4xx-feil på happy path — flere handlers gir fremdeles 4xx som reduserer effektivitetsbonus
- Korrekt feltekstraksjon — oppgavene 04 og 06 scorer 0.857 (6/7 felter korrekte)
- Tier 3 korrekthet (bank_reconciliation, year_end_closing, correct_ledger_error, monthly_closing) — handlers finnes men scoring-kvalitet er ukjent

**Bør ha (effektivitetsdifferensiatorer):**
- `asyncio.gather()` for parallelle reference-oppslag (ikke implementert)
- `get_cached()` konsekvent for vatType, paymentType, accountingPeriod, account (delvis implementert)
- `?fields=id,name` på alle GET-kall (ikke konsekvent)
- Direkte POST i fresh sandbox uten forutgående GET (delvis implementert)
- Self-verification GET etter kritiske POST-er på T2/T3 (ikke implementert)

**Utsett til etter konkurransen:**
- Lokal scoring-verifiserer/dashboard
- ML-retraining eller RAG-redesign
- asyncio TaskGroup (gather() er tilstrekkelig)
- Batch-redesign for multi-file (fungerer allerede)

### Architecture Approach

Arkitekturen følger en 5-lags pipeline: HTTP-lag (FastAPI) → Parsing-lag (Gemini/Haiku + embedding + keyword fallback) → Handler-registry (33 task_types → async functions) → TripletexClient-lag (get_cached, post_with_retry, error learning) → Persistens/observabilitet (GCS, error_patterns.json, api_rag). Grensene er tydelige: parseren gjør aldri API-kall, handlers kaller alltid via TripletexClient (aldri direkte httpx), og storage er fire-and-forget. Build-rekkefølgen er streng: parser-korrekthet → felt-ekstraksjon → handler-kall-sekvens → self-verification → cache-optimalisering.

**Hovedkomponenter:**
1. `app/parser.py` — task_type + fields-ekstraksjon; output kun ParsedTask; ingen API-kall
2. `app/handlers/` — oppgavespesifikk business-logikk; mottar (client, fields); returnerer dict
3. `app/tripletex.py` — ALL HTTP gjennom denne; get_cached, post_with_retry, error pattern learning
4. `app/error_patterns.py` — persistent feil-minne på tvers av deployments; 112 mønstre kjent
5. `app/storage.py` — GCS-persistens for revisjon og post-mortem; blokkerer aldri response

### Critical Pitfalls

1. **BETA endpoint 403 gir silent nullscore** — Handler returnerer `{"status": "completed"}` etter 403, scorer 0. Løsning: Vedlikehold eksplisitt blokksliste; behandle 403 fra BETA annerledes enn autentiseringsfeil. Kjente BETA-kallere i tier3.py: linjer 521, 631, 669.

2. **Effektivitetsbonus-klippen: 99% korrekthet = 0 bonus** — Scorer `0.9 × tier` uten bonus vs `~2.0 × tier` med bonus. Oppgavene 04 og 06 sitter fast på 0.857 (ett felt mangler). Løsning: identifiser nøyaktig hvilke felt scorer sjekker, legg til self-verification GET.

3. **Fresh sandbox forutsetnings-antagelse** — Sandkassen er tom per innsending. `_find_supplier()` returnerer None, None propageres til POST-body, gir 400. Løsning: legg til prerequisite-oppretting øverst i handlers; bruk `register_payment` som referansemønster.

4. **Parser misklassifisering sender til feil handler** — Oppgave 09, 11, 12, 17 scorer 0 på alle forsøk = parser sender aldri til riktig handler. Løsning: sjekk GCS-logger for `task_type`-felt, legg til keyword-regler i `_KEYWORD_RULES` for det korrekte task_type.

5. **5 forsøk/oppgave/dag begrenser spekulativ debugging** — Forsøk er allerede brukt på nullscore-oppgavene. Løsning: ALLTID diagnostiser fra GCS-logger, fiks, valider i E2E, så submit. Aldri spekulative innsendinger.

---

## Implications for Roadmap

Basert på kombinert forskning, anbefalt fasestruktur:

### Phase 1: Nullscore Fix (P0 — gjør dette FØRST)

**Rationale:** 4 oppgaver scorer 0 og forblir 0 uansett andre optimaliseringer. Oppgave 09 og 17 er T2 (4 pts maks), #1-team scorer fullt. Å fikse disse to alene = opp til +7.67 poeng.

**Delivers:** Nullscore-oppgavene går fra 0 til ikke-null score. Låst 0 vil aldri recalkulere — disse poengtapene er permanente om de ikke fikses nå.

**Addresses:** Tasks 09, 11, 12, 17 (FEATURES.md P0-liste)

**Avoids:**
- Pitfall 4 (parser misclassification) — inspiser GCS-logger, legg til keyword-regler
- Pitfall 3 (fresh sandbox prerequisites) — legg til prerequisite-oppretting
- Pitfall 1 (BETA endpoint silent failure) — sjekk om BETA-kall er årsaken

**Stack requirements:** Ingen ny teknologi — parser.py keyword-regler + handler-implementasjon

**Build order:** Diagnostiser GCS-logger for task_type → skriv/fiks handler → E2E-test → submit

### Phase 2: Low-Score Correctness Fix (P1a — T3 + T1/T2 korrekthet)

**Rationale:** T3-multiplier (×3) aktivert i dag. Bank_reconciliation, year_end_closing, correct_ledger_error, monthly_closing er 6 pts maks hver = 24 pts potensial. Parallelt: oppgavene 04, 06 på 0.857 trenger ett ekstra felt for å nå 1.0 og utløse effektivitetsbonus.

**Delivers:** T3-handlers scorer ikke-null; T1/T2 lavscorere går mot 1.0 correctness.

**Addresses:**
- T3 correctness (FEATURES.md P1)
- T1/T2 felt-korrekthet (FEATURES.md P2 pre-requisite)

**Avoids:**
- Pitfall 2 (effektivitetsbonus-klippen) — correctness-fokus FØR effektivitets-optimalisering
- Pitfall 1 (BETA endpoint i year_end_closing) — `/ledger/voucher/openingBalance` er BETA; wrap i try/except eller bruk alternativ path
- Pitfall 7 (forsøk brent uten root cause) — E2E-test mot sandbox ALLTID før submit

**Stack requirements:**
- `asyncio.gather()` for T3 parallel lookups (STACK.md gap #1)
- `parse_bank_statement_csv()` funksjon for bank_reconciliation (STACK.md gap #4)
- `PUT /ledger/posting/:closePostings` i batch (ikke per-posting) for year_end_closing

**Build order:** E2E-test eksisterende T3-handler → identifiser feil → fiks → E2E igjen → submit

### Phase 3: Efficiency Optimization (P1b — etter korrekthet er låst)

**Rationale:** Effektivitetsbonus kan doble scoren, men aktiveres KUN ved 1.0 correctness. Etter Phase 1 og 2 er korrekthet maxet — nå er call-count og 4xx-eliminasjon det som teller. Benchmark recalkuleres hvert 12. time, så dette er en kontinuerlig prosess.

**Delivers:** Eksisterende høy-score oppgaver øker fra ~2× til ~4× (T2) og ~3× til ~6× (T3) via effektivitetsbonus.

**Uses:**
- `asyncio.gather()` implementert (STACK.md pattern A + B)
- `?fields=id,name,...` på ALLE GET-kall (STACK.md gap #2)
- `get_cached()` konsekvent for alle reference-data (STACK.md gap #3)
- Direkte POST i fresh sandbox uten forutgående GET (STACK.md "correct pattern")

**Avoids:**
- Pitfall 5 (4xx reduserer effektivitetsbonus) — eliminer alle exploratory GET-kall som returnerer 403
- Pitfall 8 (benchmark recalkulering) — push call-count til teoretisk minimum
- Anti-pattern 1 (unconditional GET before every POST) — ARCHITECTURE.md

**Build order:** Profiler call-count per handler i E2E → eliminer unødvendige GETs → parallelliser med gather() → bekreft 0 4xx → submit

### Phase 4: T3 Robustness & Timeout Prevention

**Rationale:** T3-handlers er multi-step og kan time ut (120s). Etter at korrekthet og effektivitet er optimalisert, er robusthet det siste som kan miste poeng — spesielt på year_end_closing som har `MAX_API_CALLS = 30` som kan trigge RuntimeError midt i operasjonen.

**Delivers:** T3-handlers fullfører innen 90s med korrekte resultater uansett prompt-variant.

**Addresses:** PITFALLS.md Pitfall 6 (handler timeout), ARCHITECTURE.md Pattern 4 (budget-capped workflow)

**Avoids:** `MAX_API_CALLS = 30` som trigger RuntimeError midt i year_end_closing

**Build order:** Profiler T3 E2E execution time → identifiser timeout-risiko → legg til checkpoint-pattern → test

---

### Phase Ordering Rationale

- **Nullscore FØR alt annet:** En låst 0-score recalkulerer aldri positivt. Disse poengtapene er permanente.
- **Korrekthet FØR effektivitet:** Effektivitetsbonus-kliffen ved 1.0 gjør det meningsløst å redusere kall-antall på en handler med feil felt.
- **T3 i Phase 2, ikke Phase 3:** ×3-multiplier betyr at T3-korrekthet er mer verdt per tidsenhet enn T1/T2-effektivitetsoptimalisering.
- **Effektivitet ETTER korrekthet er låst:** Ikke optimaliser det som fremdeles har bugs.
- **E2E-test er obligatorisk FØR submit i alle faser** (prosjektbegrensning, MEMORY.md).

### Research Flags

Faser som trenger dypere research under planlegging:
- **Phase 1:** Hvem er oppgave 09, 11, 12, 17? Krever GCS-logg-inspeksjon fra tidligere innsendinger for å finne task_type-feltet. Ingen mengde kode-analyse erstatter dette.
- **Phase 2:** T3 scoring-kriterier er ukjente inntil første scorede innsending. Scoring-systemet avslører hvilke felter som sjekkes, men dokumentasjonen er ufullstendig.

Faser med veldokumenterte mønstre (skip research-phase):
- **Phase 3:** asyncio.gather(), ?fields=, get_cached() er godt dokumenterte patterns. STACK.md har konkrete implementasjons-eksempler klar til bruk.
- **Phase 4:** Timeout-profilen måles enkelt via E2E-tester. Ingen ekstra research nødvendig.

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Produksjons-kodebase analysert direkte; alle patterns bekreftet mot offisielle docs og offisielle API-endepunkt-liste |
| Features | HIGH | Scoringformel fra offisiell docs; oppgavescorer fra live leaderboard; BETA-policy bekreftet i 112 error_patterns + MEMORY |
| Architecture | HIGH | Alle claims fra direkte kode-analyse (tripletex.py, handlers/, parser.py); ingen antagelser |
| Pitfalls | HIGH | 112 feil-mønstre fra live produksjons-data; 114 innsendinger med observert atferd; CONCERNS.md-dokumenterte kjente bugs |

**Overall confidence:** HIGH

### Gaps to Address

- **Task 09, 11, 12, 17 root cause:** Eksakt task_type som parser returnerer er ukjent uten GCS-logg-inspeksjon. Hypotese: parser-misklassifisering ELLER handler mangler helt. Bekreft via `gsd show {task_id}` før du implementerer noe.

- **T3 scoring-kriterier:** Hva sjekker competition-scorer på bank_reconciliation, year_end_closing, correct_ledger_error, monthly_closing? Dokumentasjon er ufullstendig. Første scorede innsending avslører hvilke felter som mangler.

- **Efficiency benchmark-verdier:** Konkurransen publiserer ikke optimal call-count. Kun kjent fra egne beste score vs #1-konkurrenten. Planen er å minimere call-count aggressivt og se om bonus forbedres.

- **`POST /ledger/voucher/importDocument` for PDF:** Testet i E2E er ikke bekreftet. Kan eliminere LLM-ekstraksjon for supplier-fakturaer helt. Verdt å teste i Phase 2.

---

## Sources

### Primary (HIGH confidence)

- `docs/03-scoring.md` — Offisiell scoringformel, felt-for-felt sjekk, effektivitetsbonus-formel
- `docs/06-tripletex-api-endpoints.md` — Komplett endepunkt-liste med BETA-markering
- `app/error_patterns.json` — 112 live produksjonsfeil med 403-mønstre
- `docs/SYSTEMSTATUS.md` — Live score-data per oppgave, gap vs #1-team
- `app/tripletex.py` — TripletexClient implementasjon; get_cached, post_with_retry bekreftet korrekt
- `app/handlers/tier3.py` — T3 handler-implementasjon; BETA-kallere på linjer 521, 631, 669
- `.planning/codebase/CONCERNS.md` — Dokumenterte kjente bugs: year_end_closing spiral, bank reconciliation silent fallback

### Secondary (MEDIUM confidence)

- `docs/TODO.md` — Eksisterende backlog med prioritering
- `docs/04-examples.md` — Tripletex API-brukseksempler; `?fields=`-tips
- `app/handlers/tier2_invoice.py` — T2 invoice/payment handler gjennomgang
- `app/parser.py` — VALID_TASK_TYPES, keyword-regler, embedding-pipeline

### Tertiary (LOW confidence)

- asyncio.gather() vs TaskGroup benchmark — Web-søk bekrefter gather() tilstrekkelig for 3-5 samtidige kall; TaskGroup gir ingen fordel i dette omfanget
- Efficiency benchmark-verdier for #1-team — Kun implisitt fra score-gap; konkrete optimal call-counts ukjente

---

*Research completed: 2026-03-21*
*Ready for roadmap: yes*
