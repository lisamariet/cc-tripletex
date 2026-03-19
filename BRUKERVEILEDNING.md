# Brukerveiledning

## Deploy

```bash
gcloud run deploy tripletex-agent --source . --region europe-west1 --allow-unauthenticated
```

Env vars (ANTHROPIC_API_KEY, GCS_BUCKET) er allerede satt på servicen — ikke bruk `--set-env-vars`.

## Konkurranse-CLI

Se submissions og score:
```bash
python3 scripts/compete.py status
```

Trigger ny submission:
```bash
python3 scripts/compete.py submit
```

## Logger

### Submissions (score + feedback)
```bash
python3 scripts/compete.py status
```

### Detaljerte resultat-logger (API-kall, parsing, timing)
```bash
# List alle resultat-logger
gsutil ls gs://tripletex-agent-requests/results/

# Les en spesifikk logg
gsutil cat gs://tripletex-agent-requests/results/<timestamp>.json
```

### Innkommende requests (prompt, filer, credentials)
```bash
gsutil ls gs://tripletex-agent-requests/requests/
gsutil cat gs://tripletex-agent-requests/requests/<timestamp>.json
```

### Cloud Run-logger (stdout/stderr, feilmeldinger)
```bash
# Siste 50 logglinjer
gcloud logging read 'resource.labels.service_name="tripletex-agent" resource.labels.location="europe-west1"' --limit 50 --format=json --freshness=1h

# Kun feil
gcloud logging read 'resource.labels.service_name="tripletex-agent" resource.labels.location="europe-west1" severity>=ERROR' --limit 20 --format=json --freshness=1h
```

## API Key

Endpointet er beskyttet med Bearer token. Nøkkelen må registreres på https://app.ainm.no/submit/tripletex.

Nøkkel: `Qcbic1RyHSC608U2WpzJvYTQc3M4mv0g59jFEE5ZWsk`

Satt som `API_KEY` env var på Cloud Run.

## Insights (API-kall analyse)

Se effektivitet, 4xx-feil og unødvendige kall per handler:
```bash
python3 scripts/compete.py insights --detail
```

## Teste mot sandbox

```bash
python3 scripts/test_handlers.py
```

Kjører alle handlers mot Tripletex sandbox og verifiserer at API-kallene fungerer.
