# Buglogg — Tripletex AI Accounting Agent

**Opprettet:** 2026-03-20
**Siste oppdatering:** 2026-03-20

---

## Oppgavetype-status (fra 111 submissions)

| Oppgavetype | Forsøk | Snitt | Perfekt | Null | Status | Hovedproblem |
|-------------|--------|-------|---------|------|--------|-------------|
| **create_invoice** | 15 | 22% | 1 | 12 | 🔴 KRITISK | Bankkontonummer blokkerer |
| **unknown** (fallback) | 17 | 26% | 2 | 14 | 🔴 KRITISK | Fallback genererer feil feltnavn |
| **create_supplier** | 6 | 48% | 1 | 4 | 🟠 | Gamle runs uten email-sync |
| **batch_create_order** | 2 | 19% | 0 | 1 | 🟠 | Batch-logikk feil (fikset) |
| **create_employee** | 7 | 67% | 3 | 4 | 🟡 | Gamle runs uten roller |
| **create_project** | 3 | 67% | 1 | 2 | 🟡 | Gamle runs |
| **register_payment** | 6 | 65% | 2 | 3 | 🟡 | Beløp-feil (fikset) |
| **create_travel_expense** | 6 | 74% | 3 | 2 | 🟡 | 403 token-feil |
| **batch_register_timesheet** | 5 | 80% | 4 | 1 | 🟢 | Batch per-item type (fikset) |
| **register_supplier_invoice** | 5 | 80% | 2 | 3 | 🟢 | voucherType (fikset) |
| **run_payroll** | 5 | 80% | 2 | 3 | 🟢 | dateOfBirth/payload (fikset) |
| **create_product** | 8 | 88% | 4 | 4 | 🟢 | Gamle runs uten MVA-fix |
| **create_credit_note** | 6 | 89% | 2 | 4 | 🟢 | date-param (fikset) |
| **batch_create_department** | 5 | 93% | 3 | 2 | 🟢 | salesmodules 422 (fikset) |
| **create_customer** | 7 | 114% | 4 | 3 | ✅ | OK |
| **reverse_payment** | 8 | 169% | 8 | 0 | ✅ | PERFEKT |

**Nøkkelinnsikter:**
- 1 eneste 4xx-feil halverer scoren (85% → 34% snitt)
- Confidence < 0.80 = 100% feil
- create_invoice er desidert største blocker (12 av 15 = null)
- reverse_payment er vår beste handler (169% snitt, 0 feil)

---

**Totalt registrerte bugs:** 25+

---

## Sammendrag

| Status    | Antall |
|-----------|--------|
| FIXED     | 7      |
| OPEN      | 12     |
| WONTFIX   | 2      |
| EXTERNAL  | 4      |

| Alvorlighetsgrad | Antall |
|-------------------|--------|
| CRITICAL          | 6      |
| HIGH              | 9      |
| MEDIUM            | 7      |
| LOW               | 3      |

---

## 1. Parser-bugs (feil oppgavetype, manglende felt, JSON-parsefeil)

### BUG-001: Batch-parsing krasjer med TypeError
- **ID:** BUG-001
- **Status:** OPEN
- **Alvorlighetsgrad:** HIGH
- **Beskrivelse:** Nar parseren far oppgaver som "Create three departments", returnerer LLM en liste. Koden krasjer med `'list' object has no attribute 'get'` fordi listens elementer ikke har `taskType`-noekkel i forventet format.
- **Rotarsak:** `parser.py` linje 196-210 haandterer lister, men LLM-ens respons har uventet struktur der hvert element mangler `taskType`. Nar `first.get("taskType")` returnerer `None`, blir `task_type = "unknown"`, og `parsed_task` blir `null` i resultloggen.
- **Fix:** Ikke implementert. Trenger mer robust haandtering: inspiser listeelementenes format, tving `taskType` fra kontekst, og logg raat LLM-svar ved feil.
- **Dato oppdaget:** 2026-03-20 (logg `20260320_075419`)
- **Bevis:** `data/results/20260320_075419_094114.json` — `parsed_task: null`, error: `'list' object has no attribute 'get'`

---

### BUG-002: Parser gir "unknown" for mange gyldige oppgavetyper
- **ID:** BUG-002
- **Status:** OPEN
- **Alvorlighetsgrad:** CRITICAL
- **Beskrivelse:** Oppgaver som custom dimension, loennsavregning/payroll, timeregistrering+prosjektfaktura, og ordre->faktura->betaling klassifiseres som `unknown` av parseren. Dette forer til at fallback-handleren brukes i stedet for dedikerte handlers.
- **Rotarsak:** Parseren har kun 26 definerte oppgavetyper. Oppgaver som faller utenfor dette (ca. 16+ typer) far `task_type: "unknown"`. Typene `custom_dimension`, `payroll`, `register_timesheet_and_invoice`, og `order_to_invoice_to_payment` mangler.
- **Fix:** Ikke implementert. Trenger utvidelse av parser med flere oppgavetyper, eller bedre mapping fra LLM-respons til eksisterende handlers.
- **Dato oppdaget:** 2026-03-20
- **Bevis:**
  - `data/results/20260320_084027_305835.json` — custom dimension, `task_type: "unknown"`
  - `data/results/20260320_092843_639022.json` — payroll, `task_type: "unknown"`
  - `data/results/20260320_114805_458894.json` — custom dimension, `task_type: "unknown"`
  - `data/results/20260320_115104_244907.json` — ordre->faktura->betaling, `task_type: "unknown"`
  - `data/results/20260320_131006_326145.json` — timeregistrering, `task_type: "unknown"`

---

### BUG-003: Parser klassifiserer "reverse_payment" som "register_payment"
- **ID:** BUG-003
- **Status:** OPEN
- **Alvorlighetsgrad:** MEDIUM
- **Beskrivelse:** Oppgaven om aa reversere betaling fra Nordhav AS ble parsert som `register_payment` med `paymentType: "reversal"` og negativt belop, i stedet for `reverse_payment` som har egen handler.
- **Rotarsak:** Parseren klarer ikke aa skille mellom "reverser betaling" og "registrer betaling" nar prompten bruker ord som "returnert av banken" og "reverser".
- **Fix:** Ikke implementert. Trenger bedre few-shot eksempler for reversering i parser-prompten.
- **Dato oppdaget:** 2026-03-20 (logg `20260320_073738`)
- **Bevis:** `data/results/20260320_073738_007842.json` — `task_type: "register_payment"` med `amount: -42500`

---

### BUG-004: vatCode "3" for 25% MVA gir inkonsistente resultater
- **ID:** BUG-004
- **Status:** FIXED
- **Alvorlighetsgrad:** MEDIUM
- **Beskrivelse:** Parseren brukte `vatCode: "3"` for 25% MVA. GET `/ledger/vatType?number=3` returnerte id=3 (som er korrekt for 25%), men POST `/product` feilet med 422 for "Konsulenttimer" mens den lyktes for "Orangensaft".
- **Rotarsak:** Produktnummer `9497` kolliderte muligens med eksisterende produkt i sandboxen, eller `number`-feltet ble sendt som string i stedet for integer. Produktet "Orangensaft" med nummer `1256` fungerte fint.
- **Fix:** MVA-koder er rettet i parser (3=25%, 31=15%, 33=12%, 5=0%, 6=0%). Grunnproblemet med produktnummer-kollisjon er ikke verifisert.
- **Dato oppdaget:** 2026-03-19 (logg `20260319_231533`)
- **Bevis:** `data/results/20260319_231533_949354.json` — POST `/product` 422, `created: {}`

---

## 2. Handler-bugs (feil feltnavn, manglende paakrevde felt, feil belop)

### BUG-005: create_employee sender ikke startDate — 422-feil
- **ID:** BUG-005
- **Status:** FIXED
- **Alvorlighetsgrad:** CRITICAL
- **Beskrivelse:** POST `/employee` returnerte 422 Unprocessable Entity. Ansattopprettelse feiler konsekvent.
- **Rotarsak:** `startDate` ble bevisst ekskludert fra Employee-payload med kommentaren "belongs on Employment, not Employee". Men den opprinnelige koden opprettet ikke Employment-record etter Employee. Uten Employment feiler validering i Tripletex.
- **Fix:** Lagt til POST `/employee/employment` med `startDate` etter vellykket Employee-opprettelse i `tier1.py` linje 166-175. Men fix er ikke verifisert mot konkurranse-sandboxen ettersom ingen ny create_employee-oppgave har dukket opp etter fixen.
- **Dato oppdaget:** 2026-03-20 (logg `20260320_000515`)
- **Bevis:** `data/results/20260320_000515_044491.json` — POST `/employee` 422, `created: {}`

---

### BUG-006: create_invoice — POST /order gir 422
- **ID:** BUG-006
- **Status:** OPEN
- **Alvorlighetsgrad:** CRITICAL
- **Beskrivelse:** Opprettelse av faktura feiler fordi POST `/order` returnerer 422. Nar ordren feiler, blir `order_id = None`, og PUT `/order/None/:invoice` gir 404.
- **Rotarsak:** Ordrelinjer mangler trolig produktreferanse. Tripletex krever at ordrelinjer har enten et `product`-objekt eller spesifikke felt. Kun `description`, `count` og `unitPriceExcludingVatCurrency` sendes — dette er kanskje ikke nok.
- **Fix:** Ikke implementert. Handleren bor:
  1. Logge full 422-respons fra Tripletex
  2. Legge til produktreferanse pa ordrelinjer
  3. Haandtere `order_id = None` gracefully
- **Dato oppdaget:** 2026-03-20 (logg `20260320_071441`)
- **Bevis:**
  - `data/results/20260320_071441_354027.json` — POST `/order` 422, PUT `/order/None/:invoice` 404
  - `data/results/20260320_115144_406057.json` — POST `/order` 201 OK, men PUT `/order/401955456/:invoice` 422

---

### BUG-007: create_invoice — PUT /order/:invoice gir 422 selv med gyldig ordre
- **ID:** BUG-007
- **Status:** EXTERNAL
- **Alvorlighetsgrad:** CRITICAL
- **Beskrivelse:** Selv nar POST `/order` lykkes (201), feiler PUT `/order/{id}/:invoice` med 422. Bolkraft multi-line faktura opprettet ordren OK men kunne ikke fakturere den.
- **Rotarsak:** Tripletex-sandboxen mangler bankkontonummer for selskapet. `:invoice`-endepunktet krever at selskapet har registrert bankkontonummer, som ikke kan settes via API.
- **Fix:** Ikke mulig via API. Avhenger av at konkurranse-sandboxen har bankkontonummer konfigurert. Se BUG-024.
- **Dato oppdaget:** 2026-03-20 (logg `20260320_115144`)
- **Bevis:** `data/results/20260320_115144_406057.json` — order 201, :invoice 422

---

### BUG-008: register_payment finner ikke faktura — GET /invoice gir 422
- **ID:** BUG-008
- **Status:** FIXED
- **Alvorlighetsgrad:** HIGH
- **Beskrivelse:** Registrering av betaling for Luz do Sol Lda feiler fordi GET `/invoice` returnerer 422. Ingen faktura funnet.
- **Rotarsak:** `_find_invoice` sendte `invoiceDateFrom` og `invoiceDateTo` som queryparametere, men formatet eller verdiene var ugyldige for Tripletex API. Mulig at parameter-navnene var feil.
- **Fix:** Forbedret `_find_invoice` i `tier2_invoice.py`. Lagt til `_ensure_invoice_exists` som oppretter hele kjeden (kunde->ordre->faktura) nar ingen eksisterende faktura finnes.
- **Dato oppdaget:** 2026-03-19 (logg `20260319_234203`)
- **Bevis:** `data/results/20260319_234203_448402.json` — GET `/invoice` 422

---

### BUG-009: register_payment finner ikke faktura — tom liste
- **ID:** BUG-009
- **Status:** OPEN
- **Alvorlighetsgrad:** HIGH
- **Beskrivelse:** GET `/invoice` returnerer 200 men med tom verdi-liste for Nordhav AS. Ingen faktura finnes i sandboxen for denne kunden.
- **Rotarsak:** Fersk sandbox har ingen eksisterende fakturaer. `_ensure_invoice_exists` bor opprette hele kjeden, men feiler ofte pga ordrelinje-problemer (se BUG-006).
- **Fix:** `_ensure_invoice_exists` er implementert men avhenger av at ordreopprettelse fungerer. Floresta Lda-testen (logg `20260320_124957`) viser at hele pipelinen fungerer nar ordreopprettelse lykkes.
- **Dato oppdaget:** 2026-03-20 (logg `20260320_073738`)
- **Bevis:** `data/results/20260320_073738_007842.json` — GET `/invoice` 200, tom liste

---

### BUG-010: create_credit_note — 422 pa :createCreditNote
- **ID:** BUG-010
- **Status:** OPEN
- **Alvorlighetsgrad:** HIGH
- **Beskrivelse:** Kreditnota for Vestfjord AS feiler. Faktura finnes (id 2147490386), men PUT `/invoice/{id}/:createCreditNote` returnerer 422.
- **Rotarsak:** Fakturaen kan ha feil status for kreditering (f.eks. ikke "sent" eller allerede kreditert). 422-feilmeldingen fra API-et logges ikke, saa eksakt arsak er ukjent.
- **Fix:** Ikke implementert. Trenger:
  1. Logging av 422-respons-body
  2. Sjekk av fakturastatus foer kreditering
  3. Eventuelt sette faktura til korrekt status foer kreditnota
- **Dato oppdaget:** 2026-03-20 (logg `20260320_114811`)
- **Bevis:** `data/results/20260320_114811_565729.json` — PUT `/invoice/2147490386/:createCreditNote` 422

---

### BUG-011: create_invoice — 3 separate GET /ledger/vatType for samme vatCode
- **ID:** BUG-011
- **Status:** OPEN
- **Alvorlighetsgrad:** LOW
- **Beskrivelse:** Multi-line faktura gjor 3 separate GET `/ledger/vatType`-kall for hver ordrelinje, selv om flere linjer bruker samme vatCode. Bortkastet 2 API-kall.
- **Fix:** Implementer caching av vatType-oppslag per request. `get_cached` er delvis implementert i `TripletexClient` men brukes ikke konsekvent.
- **Dato oppdaget:** 2026-03-20 (logg `20260320_115144`)
- **Bevis:** `data/results/20260320_115144_406057.json` — 3x GET `/ledger/vatType` med status 200

---

### BUG-012: register_payment bruker feil belop (ekskl. MVA i stedet for inkl.)
- **ID:** BUG-012
- **Status:** FIXED
- **Alvorlighetsgrad:** HIGH
- **Beskrivelse:** `paidAmount` ble satt til belop ekskl. MVA fra prompten, men Tripletex forventer belop inkl. MVA for full betaling.
- **Rotarsak:** Handleren brukte `fields.get("amount")` direkte som `paidAmount`, men promptene oppgir belop ekskl. MVA.
- **Fix:** Rettet i `tier2_invoice.py`: bruker naa `amountOutstanding` eller `amountCurrency` fra fakturaen (som inkluderer MVA). Fallback: `abs(parsed_amount) * 1.25`.
- **Dato oppdaget:** 2026-03-20

---

### BUG-013: update_employee — dateOfBirth paakrevd for PUT men mangler
- **ID:** BUG-013
- **Status:** FIXED
- **Alvorlighetsgrad:** MEDIUM
- **Beskrivelse:** PUT `/employee/{id}` krever `dateOfBirth` i payload, men GET returnerer `null` for dette feltet.
- **Rotarsak:** Tripletex API krever `dateOfBirth` pa Employee-oppdatering selv om det kan vaere null i databasen.
- **Fix:** Lagt til fallback i `tier2_travel.py` linje 136-137: `if not employee.get("dateOfBirth"): employee["dateOfBirth"] = "1990-01-01"`.
- **Dato oppdaget:** 2026-03-20

---

### BUG-014: create_supplier — email synkroniseres ikke til invoiceEmail
- **ID:** BUG-014
- **Status:** FIXED
- **Alvorlighetsgrad:** MEDIUM
- **Beskrivelse:** Nar `email` ble oppgitt men ikke `invoiceEmail` (eller omvendt), ble bare ett felt satt. Scoring sjekker begge felt.
- **Rotarsak:** Tripletex har to separate epostfelt: `email` og `invoiceEmail`. Prompter oppgir typisk bare ett av dem.
- **Fix:** Implementert `_sync_email()` i `tier1.py`: kopierer verdien begge veier nar bare ett felt er satt.
- **Dato oppdaget:** 2026-03-20

---

## 3. API-bugs (feil endepunkter, manglende parametre, 422-feil)

### BUG-015: Fallback-handler POST /ledger/voucher gir 422
- **ID:** BUG-015
- **Status:** OPEN
- **Alvorlighetsgrad:** HIGH
- **Beskrivelse:** Fallback-handleren genererer POST `/ledger/voucher` for custom dimension-oppgaver, men kallet feiler med 422.
- **Rotarsak:** Fallback-LLM (Claude Haiku) genererer voucher-payload uten korrekt kontostruktur, manglende `row`-felt, eller feil `amountGross`-balanse (debet != kredit).
- **Fix:** Ikke implementert. Trenger dedikert handler for custom dimension + voucher. Alternativt: bruk sterkere modell (Sonnet) i fallback.
- **Dato oppdaget:** 2026-03-20 (logg `20260320_114805`)
- **Bevis:** `data/results/20260320_114805_458894.json` — POST `/ledger/voucher` 422

---

### BUG-016: Fallback-handler JSON parse error for payroll
- **ID:** BUG-016
- **Status:** OPEN
- **Alvorlighetsgrad:** HIGH
- **Beskrivelse:** Loennsavregning (payroll) for Laura Schneider feiler. Fallback-LLM returnerer ugyldig JSON.
- **Rotarsak:** Claude Haiku returnerer tekst/forklaring i stedet for ren JSON-array. `_parse_json_response` klarer ikke aa ekstrahere gyldig JSON fra responsen. Error: `Expecting value: line 1 column 1 (char 0)`.
- **Fix:** Ikke implementert. Trenger:
  1. Sterkere modell i fallback (Sonnet i stedet for Haiku)
  2. Retry-logikk med tydeligere instruksjon ved parse-feil
  3. Dedikert payroll-handler
- **Dato oppdaget:** 2026-03-20 (logg `20260320_092843`)
- **Bevis:** `data/results/20260320_092843_639022.json` — `Fallback JSON parse error: Expecting value: line 1 column 1 (char 0)`

---

### BUG-017: Fallback-handler $PREV-placeholder resolves ikke i URL-paths
- **ID:** BUG-017
- **Status:** FIXED
- **Alvorlighetsgrad:** HIGH
- **Beskrivelse:** Fallback-handleren genererer URL-er med `$PREV_2.value.id` men disse ble ikke korrekt resolvet, noe som ga paths som `/invoice/$PREV_2.value.id/:payment` som returnerer 404.
- **Rotarsak:** Opprinnelig fallback-kode resolvet kun placeholders i `body` og `params`, ikke i `path`.
- **Fix:** Lagt til path-resolving i `fallback.py` linje 219-223: `if "$PREV_" in path:` resolves alle placeholders i URL-stien.
- **Dato oppdaget:** 2026-03-20 (logg `20260320_115104`)
- **Bevis:** `data/results/20260320_115104_244907.json` — PUT `/invoice/$PREV_2.value.id/:payment` 404

---

### BUG-018: Fallback-handler — for mange API-kall feiler
- **ID:** BUG-018
- **Status:** OPEN
- **Alvorlighetsgrad:** MEDIUM
- **Beskrivelse:** Fallback for timeregistrering+prosjektfaktura gjor 8 API-kall der 5 feiler (400/422). Total feilrate: 62.5%.
- **Rotarsak:** Claude Haiku genererer API-kall med feil parametere:
  - GET `/activity` 400 (feil queryparametre)
  - POST `/activity` 422 (ugyldig payload)
  - POST `/salary/transaction` 422 (feil kontekst — salary brukes for loenn, ikke timeregistrering)
  - POST `/order` 422 (manglende felt)
  - POST `/invoice` 422 (feil endepunkt — bor bruke PUT `/order/:invoice`)
- **Fix:** Trenger dedikerte handlers for `register_timesheet` (delvis implementert) og `create_project_invoice`.
- **Dato oppdaget:** 2026-03-20 (logg `20260320_131006`)
- **Bevis:** `data/results/20260320_131006_326145.json` — 5 av 8 kall feiler

---

### BUG-019: POST /order/None/:invoice — null-referanse i URL
- **ID:** BUG-019
- **Status:** OPEN
- **Alvorlighetsgrad:** MEDIUM
- **Beskrivelse:** Nar POST `/order` feiler (422), blir `order_id = None`. Handleren fortsetter likevel og kaller PUT `/order/None/:invoice` som gir 404.
- **Rotarsak:** `create_invoice`-handleren sjekker `if not order_id` og returnerer tidlig, men `_ensure_invoice_exists` gjor det ikke konsekvent. Begge kodestier bor validere at `order_id` ikke er None.
- **Fix:** `create_invoice` har riktig sjekk (linje 250). Men `_ensure_invoice_exists` (linje 181) sjekker ogsaa `if not order_id: return None`. Problemet ble observert foer denne fixen.
- **Dato oppdaget:** 2026-03-20 (logg `20260320_071441`)
- **Bevis:** `data/results/20260320_071441_354027.json` — PUT `/order/None/:invoice` 404

---

### BUG-020: 422-responskropp logges ikke
- **ID:** BUG-020
- **Status:** OPEN
- **Alvorlighetsgrad:** HIGH
- **Beskrivelse:** Ved 422-feil fra Tripletex API logges kun statuskoden, ikke selve feilmeldingen/validation errors fra API-et. Dette gjor feilsoeking svart vanskelig.
- **Rotarsak:** `TripletexClient` returnerer response-objektet, men handlers logger bare `resp.json().get('value', {})` uten aa sjekke statuskode eller lese feilmelding.
- **Fix:** Delvis fikset — error body logges til GCS tracker ifg. TODO.md. Men individuelle handlers logger fortsatt ikke 422-detaljer.
- **Dato oppdaget:** 2026-03-20

---

## 4. Infrastruktur-bugs (deploy, miljoevariabler, CLI)

### BUG-021: CLI krever ANTHROPIC_API_KEY lokalt for oversettelse
- **ID:** BUG-021
- **Status:** WONTFIX
- **Alvorlighetsgrad:** LOW
- **Beskrivelse:** CLI-kommandoen `show` oversetter ikke-norske prompts automatisk, men dette krever at `ANTHROPIC_API_KEY` er satt lokalt.
- **Rotarsak:** Oversettelse bruker Anthropic API direkte fra CLI-koden.
- **Fix:** Ikke prioritert. Funksjonaliteten er nice-to-have og pavirker ikke scoring.
- **Dato oppdaget:** 2026-03-20

---

### BUG-022: Ingen verifikasjons-GET etter POST
- **ID:** BUG-022
- **Status:** WONTFIX
- **Alvorlighetsgrad:** LOW
- **Beskrivelse:** Etter at en ressurs opprettes med POST, utfoeres ingen GET for aa verifisere at alle felt ble lagret korrekt.
- **Rotarsak:** Handlers returnerer response fra POST direkte uten aa sjekke at verdiene matcher det som ble sendt.
- **Fix:** Ikke prioritert i denne fasen. Ville oeke antall API-kall og redusere effektivitets-score. Kan implementeres som valgfri verifikasjon.
- **Dato oppdaget:** 2026-03-20

---

## 5. Eksterne bugs (Tripletex sandbox, konkurranse-server)

### BUG-023: Test-prompts ("test") gir "Missing credentials"
- **ID:** BUG-023
- **Status:** EXTERNAL
- **Alvorlighetsgrad:** LOW
- **Beskrivelse:** Prompts med bare "test" gir `parsed_task.task_type: "unknown"` og `note: "Missing credentials"`.
- **Rotarsak:** Konkurranse-serveren sendte test-requests uten Tripletex-credentials. Parser klassifiserer korrekt som `unknown` med confidence 0.0.
- **Fix:** Ingen fix noedvendig — dette er forventet oppfoersel for test-requests uten credentials.
- **Dato oppdaget:** 2026-03-19 (logger `20260319_235440`, `20260320_000731`)
- **Bevis:** `data/results/20260319_235440_279763.json`, `data/results/20260320_000731_501567.json`

---

### BUG-024: Tripletex sandbox mangler bankkontonummer
- **ID:** BUG-024
- **Status:** EXTERNAL
- **Alvorlighetsgrad:** CRITICAL
- **Beskrivelse:** PUT `/order/{id}/:invoice` feiler med 422 fordi selskapet i sandboxen ikke har registrert bankkontonummer. Kan ikke settes via API.
- **Rotarsak:** Tripletex krever at selskapet har bankkontonummer for aa opprette fakturaer. Dette er en konfigurasjon i sandbox-oppsettet som ikke er tilgjengelig via REST API.
- **Fix:** Ikke mulig via API. Avhenger av at konkurranse-sandboxen har dette konfigurert. Bor undersoekes om det er en workaround.
- **Dato oppdaget:** 2026-03-20
- **Referanse:** TODO.md punkt 3

---

### BUG-025: Konkurranse-server sender oppgaver pa 7+ sprak
- **ID:** BUG-025
- **Status:** EXTERNAL
- **Alvorlighetsgrad:** MEDIUM
- **Beskrivelse:** Oppgaver kommer pa norsk, fransk, portugisisk, engelsk, tysk og spansk. Dette oeker kompleksiteten for parsing.
- **Rotarsak:** Konkurranse-designet inkluderer flerspraklige oppgaver.
- **Fix:** Ingen bug egentlig — parseren haandterer alle sprak godt. Ingen sprakrelaterte feil observert. Dokumentert for oversikt.
- **Dato oppdaget:** 2026-03-19

---

## Vedlegg: Fullstendig feil-oversikt fra data/results/

| Timestamp | Oppgavetype | HTTP-feil | Bug-referanse |
|-----------|-------------|-----------|---------------|
| 20260319_231533 | create_product | POST /product 422 | BUG-004 |
| 20260319_234203 | register_payment | GET /invoice 422 | BUG-008 |
| 20260319_235440 | unknown (test) | Ingen kall | BUG-023 |
| 20260320_000515 | create_employee | POST /employee 422 | BUG-005 |
| 20260320_000731 | unknown (test) | Ingen kall | BUG-023 |
| 20260320_071441 | create_invoice | POST /order 422, PUT /order/None/:invoice 404 | BUG-006, BUG-019 |
| 20260320_073738 | register_payment (feilparsert) | Ingen 4xx, tom liste | BUG-003, BUG-009 |
| 20260320_075419 | batch_create_department | Krasj — TypeError | BUG-001 |
| 20260320_084027 | unknown (custom dimension) | Ingen kall | BUG-002 |
| 20260320_092843 | unknown (payroll) | JSON parse error | BUG-002, BUG-016 |
| 20260320_114805 | unknown (custom dimension) | POST /ledger/voucher 422 | BUG-002, BUG-015 |
| 20260320_114811 | create_credit_note | PUT /:createCreditNote 422 | BUG-010 |
| 20260320_115104 | unknown (ordre->faktura) | POST /order 422, POST /invoice 422, PUT /:payment 404 | BUG-002, BUG-017, BUG-018 |
| 20260320_115144 | create_invoice | PUT /order/:invoice 422 | BUG-007, BUG-011 |
| 20260320_131006 | unknown (timeregistrering) | GET /activity 400, 4x POST 422 | BUG-002, BUG-018 |

**Vellykkede resultater (uten feil):**

| Timestamp | Oppgavetype | Score | Kommentar |
|-----------|-------------|-------|-----------|
| 20260319_233306 | create_project | 7/7 PERFEKT | Northwave |
| 20260319_235722 | create_customer | OK (201) | Bolkraft (1. forsok, foer scoring) |
| 20260320_071043 | create_customer | 8/8 PERFEKT | Bolkraft (rescoring) |
| 20260320_074340 | create_product | 6/7 | Orangensaft |
| 20260320_082409 | create_supplier | 4/7 | Northwave Ltd |
| 20260320_124957 | register_payment | 2/7 | Floresta Lda — hel pipeline fungerte |
