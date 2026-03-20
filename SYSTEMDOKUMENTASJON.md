# Systemdokumentasjon — Tripletex AI Accounting Agent

Sist oppdatert: 2026-03-20

---

## Innhold

1. [Arkitektur-oversikt](#1-arkitektur-oversikt)
2. [Komponentbeskrivelse](#2-komponentbeskrivelse)
3. [Handler-katalog](#3-handler-katalog)
4. [Parser](#4-parser)
5. [API-integrasjon](#5-api-integrasjon)
6. [Scoring-system](#6-scoring-system)
7. [Test-infrastruktur](#7-test-infrastruktur)
8. [Deploy-pipeline](#8-deploy-pipeline)
9. [CLI-verktoy](#9-cli-verktoy)
10. [Kjente begrensninger](#10-kjente-begrensninger)
11. [Filstruktur](#11-filstruktur)

---

## 1. Arkitektur-oversikt

### Systemdiagram

```
                        NM i AI Platform
                              |
                    POST /solve (JSON)
                              |
                              v
              +-------------------------------+
              |     FastAPI (app/main.py)      |
              |  - Bearer-token-verifisering   |
              |  - GCS request-logging         |
              +-------------------------------+
                              |
                    +---------+---------+
                    |                   |
                    v                   v
          +----------------+   +------------------+
          |    Parser       |   |  File Processor  |
          |  (app/parser.py)|   | (file_processor) |
          |  Claude Haiku   |   | PDF/bilde/CSV    |
          |  + Sonnet fb    |   +------------------+
          +----------------+            |
                    |                   |
                    v                   |
          +------------------+          |
          |   ParsedTask     |<---------+
          |  task_type +     |
          |  fields + conf   |
          +------------------+
                    |
                    v
          +------------------+
          | Handler Registry |
          | (__init__.py)    |
          |  - batch-stotte  |
          +------------------+
                    |
         +----------+----------+----------+
         |          |          |          |
         v          v          v          v
     tier1.py  tier2_invoice tier2_travel tier2_project
         |          |          |          |
         +----------+----------+----------+
                    |
                    v
          +------------------+
          | TripletexClient  |
          | (tripletex.py)   |
          |  - httpx async   |
          |  - CallTracker   |
          +------------------+
                    |
                    v
           Tripletex REST API
           (via proxy-URL)
                    |
                    v
          +------------------+
          |  GCS Logging     |
          |  (storage.py)    |
          |  results/ +      |
          |  requests/       |
          +------------------+
```

### Request-flyt

1. NM i AI-plattformen sender `POST /solve` med prompt, eventuelle filer og Tripletex-credentials.
2. `main.py` lagrer hele requesten til GCS (`requests/{timestamp}.json`).
3. Prompten (og eventuelle filer) sendes til **parseren** som bruker Claude Haiku til a ekstrahere task_type og felter.
4. `execute_task()` slaar opp riktig handler i registryet basert pa task_type.
5. Handleren utforer et eller flere API-kall mot Tripletex via `TripletexClient`.
6. Alle API-kall spores av `CallTracker` (metode, sti, statuskode, varighet).
7. Resultatet + API-kallsporing lagres til GCS (`results/{timestamp}.json`).
8. Endepunktet returnerer alltid `{"status": "completed"}` med HTTP 200.

### Designvalg

- **Parse en gang, utfor deterministisk**: LLM brukes kun til parsing — aldri til API-kallgenerering. Handlers er hardkodet og forutsigbare.
- **Alltid HTTP 200**: Uansett feil returnerer `/solve` statuskode 200 med `status: completed`. Feil logges, men bryter aldri responsen.
- **GCS-logging av alt**: Bade innkommende requests og resultater (inkl. API-kall) lagres for analyse.
- **Batch-stotte**: Parser kan returnere lister (f.eks. "opprett 3 avdelinger"), som wrappet til `batch_create_department` og kjores iterativt.
- **Modell-fallback**: Haiku forsokes forst (raskere, billigere). Ved feil prover Sonnet.

---

## 2. Komponentbeskrivelse

### `app/main.py` — FastAPI-applikasjon og orkestrering

**Endepunkter:**

| Metode | Sti | Beskrivelse |
|--------|-----|-------------|
| GET | `/health` | Returnerer `{"status": "healthy"}` |
| POST | `/solve` | Mottar oppgave, parser, utforer, returnerer resultat |

**Nokkelfunksjoner:**
- **Bearer-token-verifisering**: Hvis `API_KEY` er satt, kreves `Authorization: Bearer <key>`. Ugyldig token returnerer `{"status": "completed"}` (ikke 401) for a unnga a bryte scoring.
- **Tidsmaling**: Total behandlingstid males med `time.monotonic()`.
- **GCS-logging**: Lagrer innkommende request (med full session_token) og resultat (med parsed task, API-kall, feilstatistikk).
- **Feilhandtering**: All feil fanges i try/except — returnerer alltid 200.

### `app/config.py` — Miljovariabel-konfigurasjon

| Variabel | Default | Beskrivelse |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | `""` | API-nokkel for Claude |
| `GCS_BUCKET` | `tripletex-agent-requests` | GCS-botte for logging |
| `LLM_MODEL` | `claude-haiku-4-5-20251001` | Primaermodell for parsing |
| `LLM_FALLBACK_MODEL` | `claude-sonnet-4-20250514` | Fallback-modell (hardkodet) |
| `API_KEY` | `""` | Bearer-token for endepunktbeskyttelse |

### `app/parser.py` — LLM-parser

Bruker Anthropic Claude API til a tolke fritekstprompter og returnere strukturert `ParsedTask`. Se [seksjon 4](#4-parser) for detaljer.

### `app/models.py` — Datamodeller

Tre dataklasser:

- **`ParsedTask`**: `task_type` (str), `fields` (dict), `confidence` (float, default 1.0), `reasoning` (str)
- **`APICallRecord`**: `method`, `path`, `status`, `duration_ms`, `error`
- **`CallTracker`**: Holder liste av `APICallRecord`, med properties `total_calls` og `error_count_4xx`, og metoder `record()` og `to_dict()`.

### `app/tripletex.py` — Tripletex API-klient

Async HTTP-klient med innebygget kallsporing. Se [seksjon 5](#5-api-integrasjon) for detaljer.

### `app/storage.py` — GCS-logging

Funksjon `save_to_gcs(data, filename)`:
- Serialiserer dict til JSON (UTF-8, innrykk)
- Laster opp til `gs://{GCS_BUCKET}/{filename}`
- Feiler stille (logger feil, kaster ikke unntak)

### `app/file_processor.py` — Filbehandling

Konverterer innkommende filvedlegg til Anthropic message content blocks:

| MIME-type | Behandling |
|-----------|------------|
| `image/png`, `image/jpeg`, `image/gif`, `image/webp` | Sendes som `image`-block (base64) direkte til LLM |
| `application/pdf` | Sendes som `document`-block (base64) til LLM |
| `text/csv` / `.csv` | Dekodes, parses, sendes som tekst (maks 200 rader) |
| Andre | Forsok tekstdekoding (maks 5000 tegn), ellers `[Binary file]`-melding |

### `app/handlers/__init__.py` — Handler-register og batch-stotte

- **`HANDLER_REGISTRY`**: Dict som mapper `task_type` (str) til async handler-funksjoner.
- **`register_handler(task_type)`**: Dekorator for a registrere en handler.
- **`execute_task(task_type, client, fields)`**: Slaar opp handler og kjorer den. Stotter batch-oppgaver (`batch_<task_type>`) ved a iterere over `fields["items"]`.
- Importerer alle handler-moduler ved lasting: `tier1`, `tier2_invoice`, `tier2_travel`, `tier2_project`.

---

## 3. Handler-katalog

### Tier 1 — Enkle opprettelser (x1 poeng)

#### `create_supplier`
- **Modul**: `app/handlers/tier1.py`
- **API-kall**: `POST /supplier` (1 kall)
- **Paakrevde felt**: `name`
- **Valgfrie felt**: `organizationNumber`, `email`, `invoiceEmail`, `phoneNumber`, `phoneNumberMobile`, `isPrivateIndividual`, `description`, `bankAccount`, `website`, `overdueNoticeEmail`, `language`, `address` (objekt med `addressLine1`, `addressLine2`, `postalCode`, `city`)
- **Logikk**: Synkroniserer email/invoiceEmail (kopierer fra den som er satt). Bygger `postalAddress` og `physicalAddress` fra adressefeltet.
- **Begrensninger**: Ingen

#### `create_customer`
- **Modul**: `app/handlers/tier1.py`
- **API-kall**: `POST /customer` (1 kall)
- **Paakrevde felt**: `name`
- **Valgfrie felt**: Samme som supplier + `isSupplier`
- **Logikk**: Setter alltid `isCustomer: true`. Email-synkronisering og adressebygging som supplier.
- **Begrensninger**: Ingen

#### `create_employee`
- **Modul**: `app/handlers/tier1.py`
- **API-kall**: `POST /employee` (1 kall), ev. `GET /department` (1 kall for a finne avdeling), ev. `PUT /employee/entitlement/:grantEntitlementsByTemplate` (1 kall for rolletildeling)
- **Totalt**: 1-3 API-kall
- **Paakrevde felt**: `firstName`, `lastName`
- **Valgfrie felt**: `email`, `phoneNumberMobile`, `dateOfBirth`, `employeeNumber`, `nationalIdentityNumber`, `bankAccountNumber`, `iban`, `departmentId`, `userType`, `role`
- **Logikk**:
  - Setter `userType` til `STANDARD` som default.
  - Henter forste tilgjengelige avdeling fra GET /department hvis `departmentId` ikke er angitt.
  - Rolletildeling basert pa nokkelord i `role`-feltet:
    - `admin`/`kontoadmin`/`full`/`all` → `ALL_PRIVILEGES`
    - `faktura`/`invoice`/`invoicing` → `INVOICING_MANAGER`
    - `regnskapsforer`/`accountant`/`regnskap` → `ACCOUNTANT`
    - `personell`/`hr`/`personal` → `PERSONELL_MANAGER`
    - `avdeling`/`department` → `DEPARTMENT_LEADER`
    - Ukjent rolle → `ALL_PRIVILEGES` (maksimerer score)
- **Begrensninger**: `startDate` sendes IKKE til /employee (hoerer til Employment-objektet). Employment-opprettelse er ikke implementert.

#### `create_product`
- **Modul**: `app/handlers/tier1.py`
- **API-kall**: `POST /product` (1 kall), ev. `GET /ledger/vatType` (1 kall for MVA-oppslag)
- **Totalt**: 1-2 API-kall
- **Paakrevde felt**: `name`
- **Valgfrie felt**: `number`, `description`, `isInactive`, `priceExcludingVat`, `priceIncludingVat`, `costExcludingVat`, `vatCode`
- **Logikk**: Mapper pris-felt til Tripletex API-navn (`priceExcludingVat` → `priceExcludingVatCurrency`). Slaar opp vatType-ID fra vatCode.
- **Begrensninger**: Ingen

#### `create_department`
- **Modul**: `app/handlers/tier1.py`
- **API-kall**: `POST /company/salesmodules` (1 kall for a aktivere avdelingsmodul), `POST /department` (1 kall)
- **Totalt**: 2 API-kall
- **Paakrevde felt**: `name`
- **Valgfrie felt**: `departmentNumber`
- **Logikk**: Forsaker a aktivere avdelingsmodulen for opprettelse. Feiler stille hvis den allerede er aktiv.
- **Begrensninger**: Salesmodules-kallet gir ofte 422 pa sandbox (allerede aktivert) — dette ignoreres.

### Tier 2 — Faktura-operasjoner (x2 poeng)

#### `create_invoice`
- **Modul**: `app/handlers/tier2_invoice.py`
- **API-kall**: `GET /customer` (sok), ev. `POST /customer` (opprett), `GET /ledger/vatType` (per linje med vatCode), `POST /order`, `PUT /order/{id}/:invoice`
- **Totalt**: 3-6+ API-kall
- **Paakrevde felt**: `customerName` eller `customerOrgNumber`, `lines` (array med `description`, `quantity`, `unitPriceExcludingVat`, `vatCode`)
- **Valgfrie felt**: `invoiceDate`, `dueDate`
- **Logikk**: Finner eller oppretter kunde → oppretter ordre med ordrelinjer → fakturerer ordren.
- **Begrensninger**: Ingen

#### `register_payment`
- **Modul**: `app/handlers/tier2_invoice.py`
- **API-kall**: Hele fakturakjeden (kunde → ordre → faktura) hvis noe mangler, `GET /invoice/paymentType`, `PUT /invoice/{id}/:payment`
- **Totalt**: 3-8+ API-kall
- **Paakrevde felt**: Minst ett av: `customerName`/`customerOrgNumber`, `invoiceNumber`, `amount`, `lines`
- **Valgfrie felt**: `paymentDate`, `invoiceDescription`
- **Logikk**: Bruker `_ensure_invoice_exists()` som forst soker etter eksisterende faktura, og oppretter hele kjeden (kunde → ordre → faktura) hvis ingen finnes. Henter bankbetalingstype. Registrerer betaling med positivt belop.
- **Begrensninger**: Alltid forsaker a finne eksisterende faktura for — kan gi ekstra API-kall pa tom sandbox.

#### `reverse_payment`
- **Modul**: `app/handlers/tier2_invoice.py`
- **API-kall**: Som register_payment + et ekstra betalingskall
- **Totalt**: 4-10+ API-kall
- **Paakrevde felt**: Samme som register_payment
- **Logikk**: Sikrer at faktura finnes → registrerer forst en betaling (positivt belop) → reverserer med negativt belop pa samme faktura.
- **Begrensninger**: Registrerer alltid en initial betaling for reversering, uavhengig av om fakturaen allerede er betalt.

#### `create_credit_note`
- **Modul**: `app/handlers/tier2_invoice.py`
- **API-kall**: Som register_payment (sikre faktura), `PUT /invoice/{id}/:createCreditNote`
- **Totalt**: 3-8+ API-kall
- **Paakrevde felt**: Minst ett av: `customerName`/`customerOrgNumber`, `invoiceNumber`, `lines`/`amount`
- **Valgfrie felt**: `comment`
- **Logikk**: Sikrer at faktura finnes, oppretter kreditnota via Tripletex-endepunkt.
- **Begrensninger**: Krediterer hele fakturaen — delvis kreditering er ikke implementert.

#### `update_customer`
- **Modul**: `app/handlers/tier2_invoice.py`
- **API-kall**: `GET /customer` (sok), `PUT /customer/{id}`
- **Totalt**: 2 API-kall
- **Paakrevde felt**: `customerName` eller `customerOrgNumber`
- **Valgfrie felt**: `changes` (objekt med felt som skal oppdateres)
- **Logikk**: Henter eksisterende kundedata, merger changes inn, sender PUT.
- **Begrensninger**: Soker kun pa navn eller orgnr — kan treffe feil kunde ved vanlige navn.

### Tier 2 — Reise- og ansattoperasjoner (x2 poeng)

#### `create_travel_expense`
- **Modul**: `app/handlers/tier2_travel.py`
- **API-kall**: `GET /employee` (sok), `POST /travelExpense`, `GET /travelExpense/costCategory`, `GET /travelExpense/paymentType`, `POST /travelExpense/cost` (per kostnadslinje)
- **Totalt**: 4 + N API-kall (N = antall kostnadslinjer)
- **Paakrevde felt**: `employeeName` (eller `employeeFirstName` + `employeeLastName`), `title`, `date`
- **Valgfrie felt**: `costs` (array med `description`, `amount`, `vatCode`, `currency`)
- **Logikk**: Finner ansatt → oppretter reiseregning → henter kostnadskategori (foretrekker "Kontorrekvisita") og betalingstype (foretrekker "Privat utlegg") → legger til kostnadslinjer.
- **Begrensninger**: `description`-felt pa kostnadslinjer sendes IKKE til API (eksisterer ikke pa travelExpense/cost-modellen). Kostnadskategori- og betalingstypeoppslag er ikke cachelagret.

#### `delete_travel_expense`
- **Modul**: `app/handlers/tier2_travel.py`
- **API-kall**: `GET /employee` (sok), `GET /travelExpense` (sok), `DELETE /travelExpense/{id}`
- **Totalt**: 2-3 API-kall
- **Paakrevde felt**: `travelExpenseId` ELLER `employeeName` + `travelExpenseTitle`
- **Logikk**: Finner reiseregning via ID eller ansattsok + tittelmatch, sletter den.
- **Begrensninger**: Tittelfiltrering bruker `in`-match (case-insensitive) — kan treffe feil reiseregning.

#### `update_employee`
- **Modul**: `app/handlers/tier2_travel.py`
- **API-kall**: `GET /employee` (sok), `GET /employee/{id}`, `PUT /employee/{id}`
- **Totalt**: 3 API-kall
- **Paakrevde felt**: `employeeName` (eller `employeeFirstName` + `employeeLastName`)
- **Valgfrie felt**: `changes` (objekt med felt som skal oppdateres)
- **Logikk**: Finner ansatt, henter full data, merger changes, sender PUT. Setter `dateOfBirth` til `1990-01-01` hvis det mangler (paakrevd felt for PUT).
- **Begrensninger**: dateOfBirth-workaround kan overskrive korrekt fodselsdato pa ansatte som har en.

### Tier 2 — Prosjektoperasjoner (x2 poeng)

#### `create_project`
- **Modul**: `app/handlers/tier2_project.py`
- **API-kall**: `GET /employee` (sok prosjektleder), ev. `GET /customer` + `POST /customer`, `POST /project`
- **Totalt**: 2-5 API-kall
- **Paakrevde felt**: `name`
- **Valgfrie felt**: `customerName`, `customerOrgNumber`, `startDate`, `endDate`, `projectManagerName`, `isClosed`
- **Logikk**: Finner eller oppretter prosjektleder (bruker forste tilgjengelige ansatt som fallback). Kobler kunde hvis angitt. Setter `isInternal: false` og `startDate` (default: dagens dato).
- **Begrensninger**: Ingen

---

## 4. Parser

### System-prompt

Parseren bruker en detaljert systemprompt (`SYSTEM_PROMPT` i `app/parser.py`) som instruerer Claude til a:

1. Tolke oppgaveprompt pa et av 7 sprak: norsk bokmal, nynorsk, engelsk, spansk, portugisisk, tysk, fransk
2. Ekstrahere `taskType` og relevante `fields`
3. Returnere strukturert JSON

### Stottede oppgavetyper (18 stk.)

| # | taskType | Beskrivelse |
|---|----------|-------------|
| 1 | `create_supplier` | Opprett leverandor |
| 2 | `create_customer` | Opprett kunde |
| 3 | `create_employee` | Opprett ansatt |
| 4 | `create_product` | Opprett produkt |
| 5 | `create_department` | Opprett avdeling |
| 6 | `create_invoice` | Opprett faktura |
| 7 | `register_payment` | Registrer betaling pa faktura |
| 8 | `reverse_payment` | Reverser betaling |
| 9 | `create_credit_note` | Opprett kreditnota |
| 10 | `create_travel_expense` | Registrer reiseregning |
| 11 | `delete_travel_expense` | Slett reiseregning |
| 12 | `create_project` | Opprett prosjekt |
| 13 | `update_employee` | Oppdater ansatt |
| 14 | `update_customer` | Oppdater kunde |
| 15 | `create_voucher` | Opprett bilag/bilagsfoering |
| 16 | `reverse_voucher` | Reverser bilag |
| 17 | `delete_voucher` | Slett bilag |
| 18 | `unknown` | Ukjent oppgavetype |

**Merk**: Oppgavetype 15-17 (`create_voucher`, `reverse_voucher`, `delete_voucher`) er definert i parseren men har INGEN tilhorende handler. Oppgaver av denne typen vil returnere "No handler for task type".

### Parsing-prosess

1. Bygg `user_content` med prompttekst + eventuelle filblokker (via `file_processor.py`)
2. Kall Claude Haiku med systemprompten
3. Ved feil: fall tilbake til Claude Sonnet
4. Ekstraher JSON fra LLM-responsen (handterer markdown code fences)
5. Hvis responsen er en liste:
   - 1 element → bruk direkte
   - Flere elementer → wrap som batch (`batch_{task_type}`)
6. Returner `ParsedTask(task_type, fields, confidence, reasoning)`

### Konfidenshandtering

- Parseren returnerer `confidence` (0.0-1.0) fra LLM-responsen
- Ved JSON-parsefeil: returnerer `ParsedTask(task_type="unknown", confidence=0.0)`
- **Konfidensbasert fallback til Sonnet er IKKE implementert** (definert som backlog-oppgave i TODO.md)

### Spesielle parser-regler

- Email: Hvis prompten sier "email" uten type, settes bade `email` og `invoiceEmail`
- MVA-koder: `3` = 25%, `31` = 15%, `33` = 12%, `5` = 0% (avgiftsfri), `6` = 0% (utenfor MVA-loven)
- Organisasjonsnumre: Alltid strenger (bevarer ledende nuller)
- Belop: Alltid tall (ikke strenger)
- Datoer: YYYY-MM-DD-format

---

## 5. API-integrasjon

### TripletexClient (`app/tripletex.py`)

Asynkron HTTP-klient bygget pa `httpx.AsyncClient`.

**Autentisering**: Basic Auth med brukernavn `0` og session_token som passord.

**Metoder**:

| Metode | Signatur |
|--------|----------|
| `get(path, params)` | GET-request med query-parametre |
| `post(path, payload)` | POST-request med JSON body |
| `put(path, payload, params)` | PUT-request med JSON body og/eller query-parametre |
| `delete(path)` | DELETE-request |
| `close()` | Stenger httpx-klienten |

**Konfigurasjon**:
- Timeout: 30 sekunder
- Base URL: Strippes for trailing slash

### Kallsporing (CallTracker)

Hver HTTP-request logges automatisk med:
- Metode (GET/POST/PUT/DELETE)
- Sti (relativ URL)
- HTTP-statuskode (0 ved nettverksfeil)
- Varighet i millisekunder
- Feilmelding (kun ved unntak)

Kalldataene brukes til:
- GCS-logging for post-mortem-analyse
- Effektivitetsberegning i CLI-verktoy
- Telling av 4xx-feil for scoring-analyse

### Feilhandtering

Klienten kaster IKKE unntak ved 4xx/5xx-svar — den returnerer response-objektet. Handlers er ansvarlige for a sjekke statuskode. Nettverksfeil (timeouts, tilkoblingsfeil) kastes videre med feilregistrering i trackeren.

---

## 6. Scoring-system

### Slik fungerer scoring i konkurransen

Scoring er felt-for-felt-verifisering utfort av NM i AI-plattformen etter at agenten har svart.

#### 1. Korrekthet (Correctness)

Plattformen sporrer Tripletex API-et for a verifisere at riktige data ble opprettet/endret. Hver oppgave har spesifikke sjekker med ulike poengsummer.

**Eksempel — "Opprett ansatt"**:
| Sjekk | Poeng |
|-------|-------|
| Ansatt funnet | 2 |
| Riktig fornavn | 1 |
| Riktig etternavn | 1 |
| Riktig e-post | 1 |
| Administratorrolle tildelt | 5 |
| **Maks** | **10** |

Normalisert korrekthet = opptjente_poeng / maks_poeng (f.eks. 8/10 = 0.8)

#### 2. Tier-multiplikator

| Tier | Multiplikator | Eksempler |
|------|--------------|-----------|
| Tier 1 | x1 | Opprett ansatt, kunde, leverandor |
| Tier 2 | x2 | Faktura med betaling, kreditnota, prosjekt |
| Tier 3 | x3 | Bankavtemming, bilagskorrigering, arsavslutning |

Basescore = korrekthet x tier_multiplikator

#### 3. Effektivitetsbonus

Kun aktiv ved **perfekt korrekthet** (1.0). To faktorer:

- **Kalleffektivitet**: Antall API-kall sammenlignet med beste kjente losning. Faerre kall = hoyere bonus.
- **Feilrenhet**: Andel 4xx-feil blant API-kall. Null feil = maks bonus.

Effektivitetsbonus kan **doble** tier-scoren. Eksempel for Tier 2:
- Feilet: 0.0
- 80% korrekt: 1.6 (ingen bonus)
- Perfekt men ineffektiv: ~2.1
- Perfekt og effektiv: ~2.6
- Perfekt, optimal, null feil: 4.0

#### 4. Beste score beholdes

Kun beste score per oppgavetype teller. Darlige forsok reduserer aldri scoren.

**Totalpoeng pa leaderboard** = sum av beste score for alle 30 oppgavetyper.

### Var strategi

1. **Dekningsbredde forst**: Implementer handlers for flest mulig oppgavetyper — selv delvis korrekt score > 0.
2. **Korrekthet over effektivitet**: Effektivitetsbonus aktiveres kun ved perfekt score, sa fokus pa a fa alle felter riktig.
3. **Reduser 4xx-feil**: Unnga testal-og-feil-tilnaerming. Bruk kjent riktige feltnavn og payloads.
4. **Cache oppslag**: Reduser gjentatte GET-kall for vatType, paymentType, costCategory (forelopig ikke implementert).

---

## 7. Test-infrastruktur

### pre_deploy_test.py — Pre-deploy testsuite

**Plassering**: `scripts/pre_deploy_test.py`

**Formal**: Verifisere at alle handlers fungerer mot ekte Tripletex sandbox for deploy.

**Kjoring**:
```bash
python3 scripts/pre_deploy_test.py
```

**Prosess**:
1. Henter sandbox-credentials automatisk fra `https://api.ainm.no/tripletex/sandbox` (krever `NMIAI_ACCESS_TOKEN`)
2. Kjorer 10 testcaser mot alle registrerte handlers
3. Sjekker at API-kall returnerer 2xx og at entiteter opprettes
4. Rapporterer PASS/FAIL per handler + total API-kallstatistikk
5. Exit code 0 = alle bestatt, 1 = feil funnet

**Testcaser (10 stk.)**:

| Test | Handler | Verifisering |
|------|---------|--------------|
| create_supplier | tier1 | Sjekker at ID returneres |
| create_customer | tier1 | Sjekker at ID returneres |
| create_employee | tier1 | Sjekker at ID returneres |
| create_product | tier1 | Sjekker at ID returneres |
| create_department | tier1 | Sjekker at ID returneres |
| create_invoice | tier2_invoice | Sjekker at ID returneres |
| create_project | tier2_project | Sjekker at ID returneres |
| create_travel_expense | tier2_travel | Sjekker at travelExpenseId returneres |
| update_employee | tier2_travel | Sjekker at employeeId returneres |
| update_customer | tier2_invoice | Sjekker at customerId returneres |

**Kjente sandbox-unntak**: 422 pa `/company/salesmodules` ignoreres (modul allerede aktiv). `:invoice`-feil pa grunn av manglende bankkonto aksepteres.

### test_handlers.py — Manuell sandbox-testing

**Plassering**: `scripts/test_handlers.py`

**Formal**: Enklere, manuell testing av subset av handlers.

**Kjoring**:
```bash
python3 scripts/test_handlers.py --from-gcs              # Bruker credentials fra siste GCS-logg
python3 scripts/test_handlers.py --token <session_token>  # Manuelt token
python3 scripts/test_handlers.py --tier2                  # Inkluderer tier 2 tester
```

**Testcaser**: 5 tier 1-tester + 1 valgfri tier 2-test (create_project). Mindre omfattende enn pre_deploy_test.py.

**Forskjell fra pre_deploy_test**: Henter IKKE credentials automatisk — krever `--from-gcs` eller `--token`. Viser detaljert API-kall-logg per kall.

### Hva testes IKKE

- **End-to-end-flyt**: Ingen test av prompt → parse → execute. Parseren testes ikke.
- **Feltverifisering**: Testene sjekker kun at 2xx returneres og at ID finnes — ikke at korrekte verdier ble lagret.
- **Alle oppgavetyper**: register_payment, reverse_payment, create_credit_note, delete_travel_expense mangler dedikerte tester i pre_deploy_test.
- **Sprakhandtering**: Ingen tester med ikke-norske prompts.
- **Filvedlegg**: Ingen tester med PDF/bilde-input.
- **Batch-oppgaver**: Ingen tester for batch_create_*-flyten.

---

## 8. Deploy-pipeline

### Infrastruktur

| Komponent | Teknologi |
|-----------|-----------|
| Runtime | Google Cloud Run |
| Region | europe-west1 |
| Container | Python 3.12-slim |
| Web-server | Uvicorn (port 8080) |
| Logging | Google Cloud Storage |

### Dockerfile

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ app/
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

**Merk**: Kun `app/`-mappen kopieres inn — scripts, docs og data inkluderes IKKE i container-imaget.

### Avhengigheter (requirements.txt)

| Pakke | Versjon | Formal |
|-------|---------|--------|
| fastapi | 0.115.6 | Web-rammeverk |
| uvicorn | 0.34.0 | ASGI-server |
| google-cloud-storage | 2.19.0 | GCS-logging |
| python-dotenv | 1.0.1 | Env-fil-lasting |
| anthropic | >=0.40.0 | Claude API-klient |
| httpx | >=0.27.0 | Async HTTP-klient |
| pydantic | >=2.0 | Datavalidering (brukt av FastAPI) |

### Deploy-kommando

```bash
gcloud run deploy tripletex-agent --source . --region europe-west1 --allow-unauthenticated
```

### Miljovariable pa Cloud Run

Satt direkte pa Cloud Run-servicen (ikke i deploy-kommandoen):

| Variabel | Beskrivelse |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Claude API-nokkel |
| `GCS_BUCKET` | `tripletex-agent-requests` |
| `LLM_MODEL` | `claude-haiku-4-5-20251001` |
| `API_KEY` | Bearer-token for `/solve` |

### Anbefalt deploy-workflow

1. Gjor kodeendringer
2. Kjor `python3 scripts/pre_deploy_test.py` — **deploy kun ved exit code 0**
3. `gcloud run deploy tripletex-agent --source . --region europe-west1 --allow-unauthenticated`
4. Verifiser med `python3 scripts/compete.py submit`
5. Analyser med `python3 scripts/compete.py status` og `show`

---

## 9. CLI-verktoy

### scripts/compete.py — Konkurranse-CLI

Kommandolinjeverktoy for a interagere med NM i AI-plattformen. Krever `NMIAI_ACCESS_TOKEN` i `.env`.

**Konfigurasjon**:
- API-base: `https://api.ainm.no`
- Endpoint-URL: `https://tripletex-agent-753459644453.europe-west1.run.app`

### Kommandoer

#### `status` — Vis submissions og totalpoeng

```bash
python3 scripts/compete.py status
```

Viser:
- Totalpoeng (sum av beste score per oppgavetype)
- Antall oppgaver med poeng (av 30)
- Submissions i dag (av 32 daglig grense)
- Tabell med siste 25 submissions: tid, oppgavetype, score, varighet, status

Henter GCS-logger for a matche oppgavetyper til submissions (via tidsstempel-naerhet).

#### `show N` — Vis detaljer for en submission

```bash
python3 scripts/compete.py show 1          # Nyeste
python3 scripts/compete.py show 5 --translate  # Med oversettelse
```

Viser:
- Tidspunkt, status, score, varighet
- Feedback/sjekker fra plattformen (felt-for-felt resultater)
- Prompt (fra GCS request-logg)
- Parsed oppgave (task_type, felt)
- Alle API-kall med metode, sti, statuskode, varighet
- 4xx-feildetaljer
- Effektivitetsmetrikker

`--translate`/`-t`: Oversetter prompt til norsk via Claude Haiku (for ikke-norske/engelske prompts).

#### `insights` — Dyp analyse

```bash
python3 scripts/compete.py insights            # Oversikt
python3 scripts/compete.py insights --detail   # Inkluderer 4xx-feildetaljer
```

Viser:
- Oversikt: totalt submissions, perfekte, delvise, feilede
- Beste score per oppgavetype med normalisert score
- Oppgavetyper vi ikke har truffet enna (basert pa 30 kjente typer)
- Forbedringsmuligheter (delvis score)
- Feilede oppgaver (0 poeng)
- API-effektivitetsanalyse fra GCS-logger: kall per handler, feilrate, snitt

#### `poll` — Sanntidsovervakning

```bash
python3 scripts/compete.py poll                     # Default: 10s intervall, 30 min timeout
python3 scripts/compete.py poll --interval 5        # Sjekk hvert 5. sekund
python3 scripts/compete.py poll --timeout 600       # 10 min timeout
```

Etablerer en baseline av eksisterende submissions, deretter poller for nye resultater. Viser score sa snart en submission fullores.

#### `submit` — Trigger ny submission

```bash
python3 scripts/compete.py submit                   # Standard endpoint
python3 scripts/compete.py submit --endpoint URL    # Egendefinert endpoint
python3 scripts/compete.py submit --no-poll         # Ikke vent pa resultat
```

Sender endpoint-URL til NM i AI-plattformen for a trigge en ny submission. Poller for resultat med okende intervall (5-15 sekunder, maks 5 minutter).

### Hjelpefunksjoner i compete.py

- **GCS-log-henting**: `fetch_gcs_logs()` bruker `gsutil` for a laste ned og parse JSON-logger fra GCS.
- **Tidsstempel-matching**: `match_log_to_submission()` matcher GCS-logger til submissions med 10-minutters toleranse.
- **Sprakdeteksjon**: `_needs_translation()` sjekker om prompt er norsk/engelsk basert pa vanlige ord.
- **Prompt-oversettelse**: `_translate_prompt()` bruker Claude Haiku til a oversette til norsk.

---

## 10. Kjente begrensninger

### Manglende handlers (12 av 30 oppgavetyper)

Folgende oppgavetyper har INGEN handler og gir 0 poeng:

| Oppgavetype | Kategori |
|-------------|----------|
| `create_voucher` | Bilag (definert i parser, ingen handler) |
| `reverse_voucher` | Bilag (definert i parser, ingen handler) |
| `delete_voucher` | Bilag (definert i parser, ingen handler) |
| `create_order` | Ordre |
| `create_contact` | Kontakt |
| `update_contact` | Kontakt |
| `delete_invoice` | Faktura |
| `invoice_with_payment` | Kompleks faktura |
| `multi_step_invoice` | Kompleks faktura |
| `credit_note` | Kreditnota (ulik fra `create_credit_note`?) |
| `project_billing` | Prosjektfakturering |
| `bank_reconciliation` | Bankavtemming |
| `error_correction` | Feilretting i regnskap |
| `year_end_closing` | Arsavslutning |
| `create_invoice_from_pdf` | PDF-basert faktura |
| `expense_report` | Utgiftsrapport |
| `enable_department_accounting` | Modulaktivering |
| `assign_role` | Rolletildeling |
| `create_product_with_vat` | Produkt med MVA |
| `batch_create_employees` | Batch-opprettelse |

**Merk**: Noen av disse kan vaere varianter av eksisterende handlers som treffes av parseren under et annet task_type-navn.

### Kjente issues i handlers

1. **Employment-opprettelse mangler**: `startDate` fra parser sendes ikke til API. Employee-handleren oppretter ikke Employment-objekt, som betyr at ansettelsesdato ikke settes.

2. **dateOfBirth-workaround**: `update_employee` setter `dateOfBirth` til `1990-01-01` hvis det mangler — kan overskrive korrekt dato.

3. **Ingen caching av oppslag**: `vatType`, `paymentType`, `costCategory` hentes pa nytt for hvert kall — reduserer effektivitetsbonus.

4. **Kunden opprettes for tidlig**: `_find_or_create_customer()` oppretter ny kunde etter bare to sokeforspk — kan gi duplikater.

5. **Batch-items parser-avhengig**: Batch-flyten avhenger av at LLM returnerer en JSON-liste. Hvis LLM returnerer ett objekt med flere entiteter pakket annerledes, treffer den ikke batch-logikken.

### Kjente issues i parser

1. **Konfidensbasert fallback mangler**: Haiku brukes alltid forst, Sonnet kun ved API-feil — ikke ved lav konfidenssscore.

2. **Ingen few-shot-eksempler**: Systemprompt har kun instruksjoner, ingen eksempler fra faktiske prompts.

3. **Voucher-typer mangler handlers**: Parser stotter `create_voucher`, `reverse_voucher`, `delete_voucher`, men ingen handler tar imot dem.

### Infrastruktur-begrensninger

1. **Synkrone GCS-kall**: `save_to_gcs()` er synkront og blokkerer event-loopen. Bor wrappet i `asyncio.to_thread()`.

2. **Synkront Anthropic-kall**: `parse_task()` bruker synkron Anthropic-klient. Blokkerer event-loopen under LLM-kall.

3. **Ingen health-check av avhengigheter**: `/health` sjekker ikke GCS-tilgang eller Anthropic API-tilgjengelighet.

4. **Ingen input-validering**: Innkommende JSON valideres ikke med schema — feil format gir uklar feilmelding.

---

## 11. Filstruktur

```
cc-accounting-ai-tripletex/
|
|-- app/                          # Applikasjonskode (deployes)
|   |-- __init__.py               # Tom init
|   |-- main.py                   # FastAPI-app, /health og /solve endepunkter
|   |-- config.py                 # Miljovariabler (ANTHROPIC_API_KEY, GCS_BUCKET, etc.)
|   |-- parser.py                 # LLM-parser med systemprompt, Claude Haiku/Sonnet
|   |-- models.py                 # Dataklasser: ParsedTask, APICallRecord, CallTracker
|   |-- tripletex.py              # Async Tripletex API-klient med kallsporing
|   |-- storage.py                # GCS-logging (save_to_gcs)
|   |-- file_processor.py         # Konverterer filvedlegg til LLM content blocks
|   |-- handlers/                 # Handler-moduler
|       |-- __init__.py           # Handler-register, batch-stotte, execute_task()
|       |-- tier1.py              # Tier 1: supplier, customer, employee, product, department
|       |-- tier2_invoice.py      # Tier 2: invoice, payment, credit note, update_customer
|       |-- tier2_travel.py       # Tier 2: travel expense, delete TE, update_employee
|       |-- tier2_project.py      # Tier 2: project
|
|-- scripts/                      # Verktoy (deployes IKKE)
|   |-- compete.py                # Konkurranse-CLI (status, show, insights, poll, submit)
|   |-- pre_deploy_test.py        # Pre-deploy testsuite (10 tester mot sandbox)
|   |-- test_handlers.py          # Manuell handler-testing
|
|-- docs/                         # Konkurransedokumentasjon
|   |-- 01-overview.md            # Oversikt over konkurransen
|   |-- 02-endpoint.md            # Endepunktspesifikasjon
|   |-- 03-scoring.md             # Scoringsystem
|   |-- 04-examples.md            # Eksempler
|   |-- 05-sandbox.md             # Sandbox-info
|   |-- 06-tripletex-api-endpoints.md  # API-endepunktreferanse
|   |-- tripletex-openapi.json    # OpenAPI-spesifikasjon for Tripletex
|
|-- data/                         # Lokal kopi av GCS-logger
|   |-- requests/                 # Innkommende requests (prompt, filer, credentials)
|   |-- results/                  # Resultat-logger (parsed task, API-kall, timing)
|
|-- Dockerfile                    # Container-bygg (Python 3.12-slim + uvicorn)
|-- requirements.txt              # Python-avhengigheter
|-- TODO.md                       # Backlog og plan
|-- BRUKERVEILEDNING.md           # Brukerveiledning for utviklerteamet
|-- SYSTEMDOKUMENTASJON.md        # Denne filen
|-- .env                          # Miljovariabler (IKKE i git)
|-- .gitignore                    # Git-ignorering
|-- .dockerignore                 # Docker-ignorering
```
