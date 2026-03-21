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
python3 scripts/compete.py status -n 10      # vis kun 10 siste
python3 scripts/compete.py status --limit 10 # samme
```

Viser totalpoeng, antall oppgaver med poeng (av 30), submissions i dag av 300, og tabell over submissions.

Default viser alle submissions. Bruk `-n N` / `--limit N` for å begrense antallet rader.

Tabellen har kolonnene: `#`, `Tid`, `Oppgavetype`, `Score`, `4xx`, `5xx`, `Varighet`, `Status`.
`4xx` og `5xx` hentes fra GCS-logger og viser antall feilede API-kall per submission.

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

### Status per oppgavetype (tasks)

```bash
python3 scripts/compete.py tasks
```

Viser aggregert statistikk per oppgavetype, hentet fra GCS-logger og leaderboard:

| Kolonne | Beskrivelse |
|---|---|
| Oppgavetype | task_type-navn |
| Tier | 1, 2 eller 3 |
| Maks score | Høyeste score vi har oppnådd |
| Avg score | Gjennomsnittlig score |
| Forsøk | Totalt antall submissions |
| OK/Fail | Antall vellykkede / feilede |
| Suksess% | Andel med poeng |
| 4xx avg | Gjennomsnittlig antall 4xx-feil per submission |

### Sammenlign med lederlaget

```bash
python3 scripts/compete.py compare
```

Sammenligner vår task-score med #1 på leaderboard — viser gap per oppgavetype.

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

## TASK_ID_MAP — oppgavenummer til type og tier

Definert i `scripts/compete.py`. Brukes av `tasks`-kommandoen og andre analyse-verktøy for å mappe oppgavenummer (01–30) til `task_type` og tier.

| ID | task_type | Tier |
|---|---|---|
| 01 | create_supplier | 1 |
| 02 | create_customer | 1 |
| 03 | create_product | 1 |
| 04 | create_employee | 1 |
| 05 | batch_create_department | 1 |
| 06 | create_department | 1 |
| 07 | create_employee (variant med rolle/rettigheter) | 1 |
| 08 | create_customer (variant med adresse) | 1 |
|-|-|-|
| 09 | set_project_fixed_price | 2 |
| 10 | create_invoice | 2 |
| 11 | create_custom_dimension | 2 |
| 12 | batch_create_department (batch-variant) | 2 |
| 13 | register_payment | 2 |
| 14 | create_travel_expense | 2 |
| 15 | register_supplier_invoice | 2 |
| 16 | register_timesheet | 2 |
| 17 | create_credit_note | 2 |
| 18 | reverse_payment | 2 |
|-|-|-|
| 19 | create_employee (PDF tilbudsbrev-variant) | 3 |
| 20 | unknown | 3 |
| 21 | monthly_closing | 3 |
| 22 | register_expense_receipt | 3 |
| 23 | bank_reconciliation ? | 3 |
| 24 | unknown | 3 |
| 25 | unknown | 3 |
| 26 | create_voucher | 3 |
| 27 | register_payment | 3 |
| 28 | correct_ledger_error | 3 |
| 29 | bank_reconciliation | 3 |
| 30 | run_payroll | 3 |

year_end_closing


Scoring: T1 = ×1 (maks 2), T2 = ×2 (maks 4), T3 = ×3 (maks 6)

## Viktige konkurranse-regler

- **BETA-endepunkter** i Tripletex kan gi 403 — bruk alltid alternativ ved feil
- **Ny session token per submission** — aldri gjenbruk tokens
- **120s timeout** (Cloudflare) — ikke 5 min som tidligere antatt
- **MVA ma aktiveres**: PUT /ledger/vatSettings med vatRegistrationStatus=VAT_REGISTERED
- **Tier 3 apner**: 2026-03-21
- **Daglig submission-grense: 300** submissions per dag (vises i `status`-tabellen)

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

### test_real_prompts.py — regresjonstest med ekte competition-prompts

```bash
python3 scripts/test_real_prompts.py                          # Dry-run: vis testplan
python3 scripts/test_real_prompts.py --live                   # Kjør mot sandbox
python3 scripts/test_real_prompts.py --live -v                # Verbose output
python3 scripts/test_real_prompts.py --live --tier 1          # Kun tier 1
python3 scripts/test_real_prompts.py --live --tier 2          # Kun tier 2
python3 scripts/test_real_prompts.py --live --tier 3          # Kun tier 3
python3 scripts/test_real_prompts.py --live --only create_invoice,run_payroll
```

Tester bygget fra faktiske prompts mottatt under NM i AI 2026, lastet ned fra GCS (`gs://tripletex-agent-requests/`). Verifiserer at vi scorer 100% på alle oppgavetyper vi allerede har håndtert.

Krever sandbox-credentials (`NMIAI_ACCESS_TOKEN` i `.env`).

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
