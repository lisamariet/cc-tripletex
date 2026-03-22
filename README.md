# Tripletex AI Accounting Agent — NM i AI 2026

En AI-agent som løser regnskapsoppgaver i Tripletex for [NM i AI 2026](https://ainm.no)-konkurransen.

Agenten mottar et naturlig språk-prompt (på **7 språk**: nb, en, es, pt, nn, de, fr), parser oppgaven med embedding-klassifisering og LLM, og utfører de nødvendige API-kallene mot Tripletex REST API. Hver submission starter med en fersk sandbox-konto — agenten må opprette alle forutsetninger selv.

**Repo:** [github.com/lisamariet/cc-tripletex](https://github.com/lisamariet/cc-tripletex)

### Nøkkeltall

- **38 registrerte handlers** for 30 oppgavetyper (Tier 1–3)
- **78 E2E-tester** mot sandbox
- **Scoring: 72+ poeng** av ~120 mulig (maks 6.0 per Tier 3-oppgave)
- **Deploy:** Cloud Run europe-west1
- **Parser:** Vertex AI embeddings → Claude Haiku/Gemini → keyword-fallback

## Kom i gang

### Forutsetninger

- **Python 3.12+**
- **Google Cloud SDK** (`gcloud` CLI) — for autentisering og deploy
- **Anthropic API-nøkkel** — for Claude-basert parsing
- **NM i AI-tilgang** — `NMIAI_ACCESS_TOKEN` for sandbox-testing og submissions

### 1. Klon og installer

```bash
git clone https://github.com/lisamariet/cc-tripletex.git
cd cc-accounting-ai-tripletex
pip install -r requirements.txt
```

### 2. Sett opp miljøvariabler

Opprett en `.env`-fil i prosjektroten:

```env
NMIAI_ACCESS_TOKEN=din-nmiai-token
GCS_BUCKET=tripletex-agent-requests
PARSER_BACKEND=haiku
```

For Google Cloud-autentisering (Vertex AI, GCS):

```bash
gcloud auth application-default login
```

### 3. Kjør lokalt

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

Helsesjekk: `GET http://localhost:8080/health`

### 4. Test mot sandbox

```bash
# Pre-deploy test (obligatorisk før deploy)
python3 scripts/pre_deploy_test.py

# Full E2E-test
python3 scripts/test_e2e.py

# Test med ekte competition-prompts
python3 scripts/test_real_prompts.py --live
```

### 5. Deploy til Cloud Run

```bash
gcloud run deploy tripletex-agent --source . --region europe-west1 --allow-unauthenticated
```

Miljøvariabler er allerede konfigurert på Cloud Run-servicen.

### 6. Submit til konkurransen

```bash
python3 scripts/compete.py submit           # Trigger én submission
python3 scripts/compete.py status           # Se resultater
python3 scripts/compete.py tasks            # Status per oppgavetype
```

## Arkitektur

```
POST /solve
    |
    v
Parser Pipeline (Embedding → LLM → Keyword)
    |
    v
Handler Registry (38 handlers, Tier 1–3)
    |
    v
TripletexClient (async httpx, smart retry, call tracking)
    |
    v
Tripletex REST API (via proxy)
    |
    v
GCS Logging (requests + results)
```

- **Multi-stage parser**: Vertex AI embedding-klassifisering (10ms first-pass) → LLM (Haiku/Gemini) med few-shot → keyword-fallback. Konfigurerbar via `PARSER_BACKEND`.
- **38 registrerte handlers**: Dekker opprettelse, oppdatering, sletting, fakturering, bilag, lønn, bankavstemminger, årsavslutning m.m. Organisert i tier1, tier2 (invoice, travel, project, extra), tier3, og fallback.
- **TripletexClient**: Async HTTP-klient med automatisk kallsporing (`CallTracker`), `post_with_retry` for 422-feilretting, og regelbasert payload-korreksjon.
- **7 språk**: Prompts på norsk bokmål, nynorsk, engelsk, spansk, portugisisk, tysk og fransk.
- **GCS-logging**: Alle requests og resultater lagres til `tripletex-agent-requests`-bøtta for analyse og debugging.

## Prosjektstruktur

```
app/
  main.py              # FastAPI-applikasjon (POST /solve, GET /health)
  parser.py            # Multi-stage LLM-parser
  parser_gemini.py     # Gemini-basert parser
  tripletex.py         # Async Tripletex API-klient
  models.py            # ParsedTask, CallTracker, APICallRecord
  config.py            # Miljøvariabel-konfigurasjon
  storage.py           # GCS-logging
  file_processor.py    # PDF/bilde/CSV-behandling
  embeddings.py        # Vertex AI embedding-klassifisering
  error_patterns.py    # Lær av tidligere 4xx-feil
  api_rag.py           # RAG for Tripletex API-docs
  api_validator.py     # OpenAPI-validering
  handlers/
    tier1.py           # create_supplier, create_customer, create_employee, etc.
    tier2_invoice.py   # create_invoice, register_payment, reverse_payment, etc.
    tier2_travel.py    # create_travel_expense, delete_travel_expense, update_employee
    tier2_project.py   # create_project, set_project_fixed_price
    tier2_extra.py     # update/delete-operasjoner, lønn, timeregistrering, m.m.
    tier3.py           # Bilag, bankavstemminger, årsavslutning, m.m.
    fallback.py        # LLM-basert fallback for ukjente oppgavetyper
scripts/
  compete.py           # Konkurranse-CLI (submit, status, tasks, insights, m.m.)
  pre_deploy_test.py   # Obligatorisk pre-deploy testing
  test_e2e.py          # E2E-testsuite
  test_real_prompts.py # Regresjonstest med ekte prompts
  test_handlers.py     # Handler-testing
  test_parser.py       # Parser-testing
docs/
  BRUKERVEILEDNING.md  # Workflow, CLI-kommandoer, deploy
  E2E-TESTPLAN.md      # Testdesign og testplan
  SYSTEMDOKUMENTASJON.md # Fullstendig systemdokumentasjon
```

## Miljøvariabler

| Variabel | Default | Beskrivelse |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | API-nøkkel for Claude |
| `GCS_BUCKET` | `tripletex-agent-requests` | GCS-bøtte for logging |
| `LLM_MODEL` | `claude-haiku-4-5-20251001` | Primærmodell for parsing |
| `API_KEY` | — | Bearer-token for `/solve`-endepunktet |
| `PARSER_BACKEND` | `haiku` | Parser-backend: `haiku`, `gemini`, `embedding`, `auto` |
| `GCP_PROJECT` | `ai-nm26osl-1771` | Google Cloud-prosjekt |
| `GCP_LOCATION` | `europe-west1` | Vertex AI-region |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Gemini-modell |
| `TRIPLETEX_DEBUG` | — | Aktiver detaljert API-logging |

## Teknologier

| Komponent | Teknologi |
|---|---|
| Backend | Python 3.12, FastAPI 0.115, Uvicorn |
| HTTP-klient | httpx (async) |
| LLM-parsing | Claude Haiku (primær), Gemini 2.5 Flash (alternativ) |
| Embeddings | Vertex AI text-embeddings (cosine similarity) |
| Logging | Google Cloud Storage |
| Deploy | Cloud Run (europe-west1), Docker (python:3.12-slim) |
| Validering | Pydantic 2.0+, OpenAPI-spec-validering |

## Scoring-system

Poeng per oppgave = `korrekthet * tier_multiplier * effektivitet`:

| Tier | Multiplier | Eksempler |
|---|---|---|
| Tier 1 | x1 | create_supplier, create_customer, create_employee |
| Tier 2 | x2 | create_invoice, register_payment, create_travel_expense |
| Tier 3 | x3 | bank_reconciliation, year_end_closing, create_voucher |

Effektivitet belønner færre API-kall og null 4xx-feil. Maks 6.0 per Tier 3-oppgave.

## Dokumentasjon

- [Arkitektur](ARCHITECTURE.md) — Systemarkitektur, lag, designprinsipper
- [Brukerveiledning](docs/BRUKERVEILEDNING.md) — Workflow, CLI-kommandoer, deploy, testing
- [E2E-testplan](docs/E2E-TESTPLAN.md) — Testdesign, sandbox-forskjeller, testdefinisjoner
- [Systemdokumentasjon](docs/SYSTEMDOKUMENTASJON.md) — Arkitektur, handlers, parser, API-integrasjon
- [Oppgaveoversikt](docs/01-overview.md) — NM i AI oppgavebeskrivelse
- [Scoring](docs/03-scoring.md) — Scoring-system og poengregler

## Lisens

Utviklet for NM i AI 2026-konkurransen.
