# Brukerveiledning

## Workflow

Riktig rekkefølge for endringer:

1. **Kode** — gjør endringer i handlers, parser, etc.
2. **Test** — kjør `pre_deploy_test.py` (obligatorisk, blokkerer deploy ved feil)
3. **Deploy** — push til Cloud Run
4. **Submit** — trigger en submission via CLI
5. **Analyser** — bruk `status`, `show`, `insights` for å evaluere resultatet

## Deploy

```bash
gcloud run deploy tripletex-agent --source . --region europe-west1 --allow-unauthenticated
```

Env vars er allerede satt på Cloud Run-servicen — ikke bruk `--set-env-vars`:

| Variabel | Beskrivelse |
|---|---|
| `ANTHROPIC_API_KEY` | Claude API-nøkkel |
| `GCS_BUCKET` | GCS-bøtte for logging (`tripletex-agent-requests`) |
| `LLM_MODEL` | Modell for parsing (`claude-haiku-4-5-20251001`) |
| `API_KEY` | Bearer-token for `/solve`-endepunktet |
| `PARSER_BACKEND` | Parser-backend: `haiku` (default), `gemini`, `embedding`, `auto` |

## Pre-deploy testing

Kjør **alltid** før deploy:

```bash
python3 scripts/pre_deploy_test.py
```

Denne testen:
- Henter sandbox-credentials fra NM i AI API automatisk (krever `NMIAI_ACCESS_TOKEN` i `.env`)
- Kjører alle handlers (tier 1 + tier 2) mot Tripletex sandbox
- Sjekker at API-kall returnerer 2xx og at entiteter blir opprettet
- Avslutter med exit code 1 ved feil — **ikke deploy hvis den feiler**

## Konkurranse-CLI

Alle kommandoer bruker `scripts/compete.py`. Krever `NMIAI_ACCESS_TOKEN` i `.env`.

### Oversikt over submissions

```bash
python3 scripts/compete.py status
```

Viser totalpoeng, antall oppgaver med poeng (av 30), og tabell med de siste 25 submissions.

### Detaljer for en submission

```bash
python3 scripts/compete.py show 1    # 1 = nyeste
python3 scripts/compete.py show 5    # 5. nyeste
```

Viser prompt, parsed oppgave, alle API-kall med status/tid, feedback og sjekker.

### Analyse av score og API-effektivitet

```bash
python3 scripts/compete.py insights           # oversikt
python3 scripts/compete.py insights --detail   # inkluderer 4xx-feildetaljer
```

Viser beste score per oppgavetype, forbedringsmuligheter, feilede oppgaver, og API-kallstatistikk per handler.

### Overvåk nye submissions i sanntid

```bash
python3 scripts/compete.py poll                    # default: sjekk hvert 10s, 30 min timeout
python3 scripts/compete.py poll --interval 5       # sjekk hvert 5s
python3 scripts/compete.py poll --timeout 600      # 10 min timeout
```

### 4xx-feilrapport

```bash
python3 scripts/compete.py errors
```

Viser detaljert 4xx-feilanalyse: totalt antall, siste timens feil, feil per endpoint, per oppgavetype, og vanligste feilmeldinger.

### Trigger ny submission

```bash
python3 scripts/compete.py submit
python3 scripts/compete.py submit --no-poll    # ikke vent på resultat
```

## API Key

Nøkkel: `Qcbic1RyHSC608U2WpzJvYTQc3M4mv0g59jFEE5ZWsk`

Registrer nøkkelen på: https://app.ainm.no/submit/tripletex

Satt som `API_KEY` env var på Cloud Run. Endepunktet `/solve` krever `Authorization: Bearer <key>`.

## Endpoints

| Metode | Sti | Beskrivelse |
|---|---|---|
| GET | `/health` | Helsesjekk |
| POST | `/solve` | Mottar oppgave, parser med LLM, kjører handler, returnerer resultat |

## Registrerte handlers (30 stk.)

Handlers registreres via `@register_handler` i `app/handlers/`:

- **tier1.py**: `create_supplier`, `create_customer`, `create_employee`, `create_product`, `create_department`
- **tier2_invoice.py**: `create_invoice`, `register_payment`, `reverse_payment`, `create_credit_note`, `update_customer`
- **tier2_travel.py**: `create_travel_expense`, `delete_travel_expense`, `update_employee`
- **tier2_project.py**: `create_project`, `set_project_fixed_price`
- **tier2_extra.py**: `update_supplier`, `update_product`, `delete_employee`, `delete_customer`, `delete_supplier`, `create_order`, `register_supplier_invoice`, `register_timesheet`, `create_invoice_from_pdf`, `run_payroll`, `create_custom_dimension`
- **tier3.py**: `create_voucher`, `reverse_voucher`, `delete_voucher`
- **fallback.py**: `unknown` (LLM-basert fallback for ukjente oppgavetyper)

## Viktige konkurranse-regler

- **BETA-endepunkter** i Tripletex kan gi 403 — bruk alltid alternativ ved feil
- **Ny session token per submission** — aldri gjenbruk tokens
- **120s timeout** (Cloudflare) — ikke 5 min som tidligere antatt
- **MVA ma aktiveres**: PUT /ledger/vatSettings med vatRegistrationStatus=VAT_REGISTERED
- **Tier 3 apner**: 2026-03-21

## Logger

### GCS — resultat-logger (API-kall, parsing, timing)

```bash
gsutil ls gs://tripletex-agent-requests/results/
gsutil cat gs://tripletex-agent-requests/results/<timestamp>.json
```

### GCS — innkommende requests (prompt, filer, credentials)

```bash
gsutil ls gs://tripletex-agent-requests/requests/
gsutil cat gs://tripletex-agent-requests/requests/<timestamp>.json
```

### Cloud Run-logger (stdout/stderr)

```bash
# Siste 50 logglinjer
gcloud logging read 'resource.labels.service_name="tripletex-agent" resource.labels.location="europe-west1"' \
  --limit 50 --format=json --freshness=1h

# Kun feil
gcloud logging read 'resource.labels.service_name="tripletex-agent" resource.labels.location="europe-west1" severity>=ERROR' \
  --limit 20 --format=json --freshness=1h
```

## E2E-testing

```bash
python3 scripts/test_e2e.py           # Alle 32 tester
python3 scripts/test_e2e.py --tier2   # Kun tier 2
python3 scripts/test_e2e.py --plan    # Vis testplan uten å kjøre
```

Full pipeline-test: prompt → parse_task() → handler → verifikasjons-GET. 32 tester, 132-138 API-kall.

## ML-verktøy

```bash
python3 scripts/build_embeddings.py       # Bygg embedding-indeks (128 prompts, 17 typer)
python3 scripts/build_api_rag.py          # Bygg RAG-indeks (751 chunks)
python3 scripts/build_error_patterns.py   # Bygg error pattern database (112 mønstre)
```

## Sandbox-testing

### pre_deploy_test.py (anbefalt)

```bash
python3 scripts/pre_deploy_test.py
```

Henter credentials automatisk. Kjører tier 1 + tier 2 tester. Exit code 0/1.

### test_handlers.py (manuell)

```bash
python3 scripts/test_handlers.py --from-gcs              # bruk credentials fra siste GCS request-logg
python3 scripts/test_handlers.py --token <session_token>  # bruk manuelt token
python3 scripts/test_handlers.py --tier2                  # inkluder tier 2 tester
```

Kjører et subset av handlers og viser hvert API-kall med status og tid.
