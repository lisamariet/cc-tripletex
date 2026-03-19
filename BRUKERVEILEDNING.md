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

## Teste mot sandbox

```bash
python3 scripts/test_handlers.py
```

Kjører alle handlers mot Tripletex sandbox og verifiserer at API-kallene fungerer.
