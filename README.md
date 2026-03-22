# Tripletex AI Accounting Agent — NM i AI 2026

En AI-agent som løser regnskapsoppgaver i Tripletex for [NM i AI 2026](https://ainm.no)-konkurransen. Agenten mottar et naturlig språk-prompt (på 7 språk), parser oppgaven med LLM, og utfører de nødvendige API-kallene mot Tripletex.

## Kom i gang

### Forutsetninger

- **Python 3.12+**
- **Google Cloud SDK** (`gcloud` CLI) — for autentisering og deploy
- **Anthropic API-nøkkel** — for Claude-basert parsing
- **NM i AI-tilgang** — `NMIAI_ACCESS_TOKEN` for sandbox-testing og submissions

### 1. Klon og installer

```bash
git clone <repo-url>
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
POST /solve → Parser (Embedding → LLM → Keyword) → Handler Registry → Tripletex API
```

- **Parser**: Multi-stage pipeline med embedding-klassifisering, LLM (Haiku/Gemini), og keyword-fallback
- **35 registrerte handlers**: Dekker opprettelse, oppdatering, sletting, fakturering, bilag, lønn, bankavstemminger m.m.
- **TripletexClient**: Async HTTP-klient med automatisk kallsporing og smart retry
- **GCS-logging**: Alle requests og resultater lagres for analyse

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

## Dokumentasjon

- [Brukerveiledning](docs/BRUKERVEILEDNING.md) — Workflow, CLI-kommandoer, deploy, testing
- [E2E-testplan](docs/E2E-TESTPLAN.md) — Testdesign, sandbox-forskjeller, testdefinisjoner
- [Systemdokumentasjon](docs/SYSTEMDOKUMENTASJON.md) — Arkitektur, handlers, parser, API-integrasjon
- [Oppgaveoversikt](docs/01-overview.md) — NM i AI oppgavebeskrivelse
- [Scoring](docs/03-scoring.md) — Scoring-system og poengregler
