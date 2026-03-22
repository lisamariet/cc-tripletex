# Arkitektur — Tripletex AI Accounting Agent

## Oversikt

Systemet er en asynkron FastAPI-applikasjon som mottar naturlig-sprak-oppgaver via `POST /solve`, parser dem til strukturerte oppgavedefinisjoner, og utforer dem mot Tripletex REST API.

```
NM i AI Platform
      |
      v
POST /solve (prompt + filer + credentials)
      |
      v
+---------------------------+
|  FastAPI (main.py)        |
|  - Auth-verifisering      |
|  - GCS request-logging    |
+---------------------------+
      |
      v
+---------------------------+     +------------------+
|  Parser Pipeline          |<----|  File Processor  |
|  1. Embedding (Vertex AI) |     |  PDF/bilde/CSV   |
|  2. LLM (Haiku/Gemini)   |     +------------------+
|  3. Keyword-fallback      |
+---------------------------+
      |
      v
+---------------------------+
|  ParsedTask               |
|  task_type + fields +     |
|  confidence + reasoning   |
+---------------------------+
      |
      v
+---------------------------+
|  Handler Registry         |
|  38 handlers (6 moduler)  |
+---------------------------+
      |
      v
+---------------------------+
|  TripletexClient          |
|  - Async httpx            |
|  - CallTracker            |
|  - post_with_retry (422)  |
|  - Error patterns         |
+---------------------------+
      |
      v
Tripletex REST API (proxy)
      |
      v
+---------------------------+
|  GCS Logging              |
|  requests/ + results/     |
+---------------------------+
```

## Lag

### 1. Orkestrering (`app/main.py`)

Mottar HTTP-request, validerer eventuelt Bearer-token, logger til GCS, kaller parser og handler, returnerer alltid HTTP 200.

### 2. Parser (`app/parser.py`, `app/parser_gemini.py`, `app/embeddings.py`)

Multi-stage pipeline for a konvertere naturlig sprak til `ParsedTask`:

1. **Embedding-klassifisering** (Vertex AI): Cosine similarity mot kjente oppgavetyper. Rask (~10ms), filtrerer ut det meste.
2. **LLM-parsing** (Claude Haiku / Gemini 2.5 Flash): Few-shot prompting for a ekstrahere task_type og felter. Fallback til Sonnet ved lav konfidenssscore.
3. **Keyword-fallback**: Regex-basert matching pa nokkelord pa alle 7 sprak.

Konfigurerbar via `PARSER_BACKEND`: `haiku`, `gemini`, `embedding`, `auto`.

### 3. Handler Registry (`app/handlers/`)

Decorator-basert selvregistrering:

```python
@register_handler("create_supplier")
async def create_supplier(client: TripletexClient, fields: dict[str, Any]) -> dict:
    ...
```

**Moduler:**
| Modul | Handlers | Eksempler |
|---|---|---|
| `tier1.py` | 6 | create_supplier, create_customer, create_employee, create_department, create_product, delete_contact |
| `tier2_invoice.py` | 6 | create_invoice, register_payment, reverse_payment, credit_invoice, update_customer, update_supplier |
| `tier2_travel.py` | 3 | create_travel_expense, delete_travel_expense, update_employee |
| `tier2_project.py` | 2 | create_project, set_project_fixed_price |
| `tier2_extra.py` | 11 | update/delete-operasjoner, lonn, timeregistrering, m.m. |
| `tier3.py` | 9 | create_voucher, bank_reconciliation, year_end_closing, supplier_invoice, m.m. |
| `fallback.py` | 1 | LLM-basert fallback for ukjente oppgavetyper |

### 4. TripletexClient (`app/tripletex.py`)

Async wrapper rundt Tripletex REST API:

- **HTTP-metoder**: `get()`, `post()`, `put()`, `delete()` — alle async med httpx
- **CallTracker**: Logger alle API-kall (metode, sti, statuskode, varighet, feilmelding)
- **post_with_retry**: Automatisk feilretting pa 422-svar (fjerner ugyldige felt, korrigerer verdier)
- **Error patterns** (`app/error_patterns.py`): Laerer av tidligere feil — fjerner kjente problematiske felt for sending
- **API-validering** (`app/api_validator.py`): Sjekker payload mot OpenAPI-spec (advarsler, ikke blokk)

### 5. Stotte-moduler

- **`app/error_patterns.py`**: Regelbasert laering fra 4xx-feil. Lagret i `error_patterns.json`.
- **`app/api_rag.py`**: RAG-basert oppslag i Tripletex API-dokumentasjon ved 422-feil.
- **`app/api_validator.py`**: OpenAPI-spec-validering av payloads for sending.
- **`app/file_processor.py`**: Forbehandling av vedlegg (PDF, bilder, CSV).
- **`app/storage.py`**: GCS-logging av requests og resultater.

## Designprinsipper

1. **Parse en gang, utfor deterministisk**: LLM brukes kun til parsing. Handlers er hardkodet og forutsigbare.
2. **Alltid HTTP 200**: Uansett feil returnerer agenten `{"status": "completed"}`. Feil logges men bryter aldri responsen.
3. **Graceful degradation**: RAG, error patterns og API-validering er valgfrie — feiler de, fortsetter agenten uten dem.
4. **Batch-stotte**: Parser kan returnere lister (f.eks. "opprett 3 avdelinger"), som wrappes og kjores iterativt.
5. **Minimal API-kall**: Scoring belonner effektivitet — handlers er optimalisert for a bruke faerrest mulig kall.

## Sprakstotte

Parseren handterer prompts pa 7 sprak: norsk bokmal (nb), nynorsk (nn), engelsk (en), spansk (es), portugisisk (pt), tysk (de) og fransk (fr). Keyword-patterns og embedding-index dekker alle sprak.
