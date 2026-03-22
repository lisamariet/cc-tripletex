# E2E-testplan for Tripletex AI Accounting Agent

## 1. Sandbox-forskjeller: vår vs. konkurransen

### Konkurranse-sandboxen (fersk per submission)
Hver gang vi sender inn, provisjoneres et **helt nytt** Tripletex-selskap med:
- Ferdig oppsatt firma med norsk kontoplan (1000-serien til 9999)
- Minst én ansatt (admin-brukeren som eier kontoen)
- Bankkonto konfigurert (nødvendig for `:invoice` og `:payment`)
- Standard MVA-typer (kode 3=25%, 31=15%, 33=12%, 5=0%, 6=0%)
- Standard betalingstyper for faktura (bank, kontant, etc.)
- Standard reisekostnads-kategorier og betalingstyper
- **Ingen** kunder, leverandører, produkter, prosjekter, avdelinger, ordrer, fakturaer
- For `register_payment`-oppgaver: konkurransen pre-oppretter kunden + fakturaen som skal betales
- For `reverse_payment`-oppgaver: konkurransen pre-oppretter kunden + fakturaen + betalingen
- For `create_credit_note`-oppgaver: konkurransen pre-oppretter kunden + fakturaen
- For `delete_travel_expense`: pre-oppretter ansatt + reiseregning
- For `update_*`: pre-oppretter entiteten som skal oppdateres
- For `delete_*`: pre-oppretter entiteten som skal slettes

### Vår sandbox (persistent)
- Akkumulerer data over tid (mange kunder, ansatte, produkter fra testing)
- Samme bankkonto-konfigurasjon hele veien
- Kan ha navnekonflikter (f.eks. duplikat org.nr)
- Session token utloper 31. mars 2026

### Kritiske forskjeller som kan gi feil
| Scenario | Konkurranse | Vår sandbox |
|----------|-------------|-------------|
| `register_payment` — finn faktura | Faktura finnes allerede | Må opprettes fra scratch |
| `create_customer` — duplikat org.nr | Aldri duplikat | Kan krasje med 409/422 |
| `create_employee` — avdeling | Minst 1 finnes | Mange finnes |
| `delete_employee` — finn ansatt | Nøyaktig 1 treff | Kan finne feil ansatt |
| Bank-konto for `:invoice` | Alltid konfigurert | Kan mangle/være annerledes |

---

## 2. Hvordan simulere fersk sandbox

### Anbefalt strategi: Opsjon B+C (hybrid)

| Opsjon | Fordeler | Ulemper | Anbefalt? |
|--------|----------|---------|-----------|
| **A: Bruk submit** | Tester eksakt konkurranse-flow | Koster submissions (5/dag/task), ikke kontrollerbar | Nei, for dyrt |
| **B: Vår sandbox + cleanup** | Realistisk, gratis, kontrollerbar | Kan ikke slette alt (kontoplan etc.), cleanup er komplisert | Delvis |
| **C: Vår sandbox as-is** | Enklest, gratis | Tester ikke fersk-sandbox-oppførsel | Delvis |
| **D: Ny sandbox via API** | Perfekt match | API finnes ikke for dette | Nei |

**Strategi vi bruker:**

1. **Create-handlers** (Tier 1): Bruk unike navn/nummer med timestamp for a unnga konflikter. Aksepter at sandboxen har akkumulert data. (**Opsjon C**)

2. **Payment/credit-handlers** (Tier 2): Test to flyter:
   - **"Pipeline-test"**: Test at hele create-chain fungerer (customer → order → invoice → payment). Dette er det vår handler faktisk gjor.
   - **"Pre-exist-test"**: Opprett forutsetninger forst, deretter kjor handleren. Simulerer konkurranse-flow narmere.

3. **Delete/update-handlers**: Opprett entiteten forst, deretter kjor delete/update. Verifiser med GET etterpå. (**Opsjon B**)

4. **Cleanup**: Etter testen, slett det vi opprettet (best effort, feiler stille).

---

## 3. E2E-testdesign

### Arkitektur

```
scripts/e2e_test.py          # Hovedskript — kjores fra CLI
tests/e2e/
  conftest.py                # Sandbox-credentials, TripletexClient setup
  test_tier1.py              # create_supplier, create_customer, etc.
  test_tier2_invoice.py      # create_invoice, register_payment, etc.
  test_tier2_project.py      # create_project
  test_tier2_travel.py       # create/delete_travel_expense
  test_tier2_extra.py        # update/delete + supplier invoice
  test_tier3.py              # voucher create/reverse/delete
  test_full_pipeline.py      # prompt → parse → handler → verify (hele flyten)
  fixtures/                  # Lagrede prompts fra data/requests/
```

### Per handler: hva vi tester

Hver E2E-test folger dette monsteret:

```
1. SETUP      — Opprett forutsetninger (kunde, ansatt, faktura, etc.)
2. EXECUTE    — Kjor handleren med test-fields
3. VERIFY     — GET entiteten fra Tripletex, sjekk felt-for-felt
4. CLEANUP    — Slett opprettet data (best effort)
```

### Verifikasjon per handler

Vi gjor **felt-for-felt-sjekk** som matcher konkurransens scoring:

| Handler | Verifikasjon via GET | Felter å sjekke |
|---------|---------------------|-----------------|
| `create_supplier` | `GET /supplier?name=X` | name, organizationNumber, email, invoiceEmail, address |
| `create_customer` | `GET /customer?name=X` | name, organizationNumber, email, invoiceEmail, isCustomer, address |
| `create_employee` | `GET /employee?firstName=X&lastName=Y` | firstName, lastName, email, dateOfBirth |
| `create_product` | `GET /product?name=X` | name, number, priceExcludingVatCurrency, vatType |
| `create_department` | `GET /department?name=X` | name, departmentNumber |
| `create_invoice` | `GET /invoice/{id}` | customer.id, amount, invoiceDate, orderLines |
| `register_payment` | `GET /invoice/{id}` | amountOutstanding == 0 |
| `reverse_payment` | `GET /invoice/{id}` | amountOutstanding == original amount |
| `create_credit_note` | `GET /invoice/{id}` | sjekk at credit note finnes |
| `create_project` | `GET /project?name=X` | name, customer.id, projectManager.id, startDate |
| `create_travel_expense` | `GET /travelExpense/{id}` | title, employee.id, costs |
| `delete_travel_expense` | `GET /travelExpense/{id}` | 404 (slettet) |
| `update_employee` | `GET /employee/{id}` | endrede felter matcher |
| `update_customer` | `GET /customer/{id}` | endrede felter matcher |
| `update_supplier` | `GET /supplier/{id}` | endrede felter matcher |
| `update_product` | `GET /product/{id}` | endrede felter matcher |
| `delete_employee` | `GET /employee/{id}` | 404 |
| `delete_customer` | `GET /customer/{id}` | 404 |
| `delete_supplier` | `GET /supplier/{id}` | 404 |
| `create_order` | `GET /order/{id}` | customer.id, orderLines |
| `create_voucher` | `GET /ledger/voucher/{id}` | description, date, postings |
| `reverse_voucher` | Sjekk at reverserings-voucher finnes | |
| `delete_voucher` | `GET /ledger/voucher/{id}` | 404 |
| `register_supplier_invoice` | `GET /ledger/voucher/{id}` | description, postings, amount |
| `register_expense_receipt` | `GET /travelExpense/{id}` | title, costs |
| `project_lifecycle` | `GET /project/{id}` | status, isClosed |
| `overdue_invoice` | `GET /invoice/{id}` | overdue status |
| `bank_reconciliation` | `GET /bank/reconciliation/{id}` | status, entries |
| `year_end_closing` | `GET /ledger/voucher` | arsavslutningsbilag |
| `correct_ledger_error` | `GET /ledger/voucher/{id}` | korrigert postering |
| `monthly_closing` | `GET /ledger/voucher` | avslutningsbilag |
| `run_payroll` | `GET /salary/payslip` | lonnsavregning opprettet |
| `register_timesheet` | `GET /timesheet/entry` | timer registrert |
| `batch_create_department` | `GET /department` | alle avdelinger opprettet |

---

## 4. Test-definisjoner med eksempler

### Tier 1: create_supplier

```python
E2E_TESTS = {
    "create_supplier": {
        "prompt": "Registre el proveedor Dorada SL con número de organización 853166553. Correo electrónico: faktura@doradasl.no.",
        "expected_parse": {
            "taskType": "create_supplier",
            "fields": {
                "name": "Dorada SL",
                "organizationNumber": "853166553",
                "email": "faktura@doradasl.no",
            }
        },
        "setup": None,  # Ingen forutsetninger
        "verify": {
            "endpoint": "/supplier",
            "search_params": {"organizationNumber": "853166553"},
            "checks": {
                "name": "Dorada SL",
                "organizationNumber": "853166553",
                "email": "faktura@doradasl.no",
                "invoiceEmail": "faktura@doradasl.no",  # Synkronisert
            }
        },
        "cleanup": {"method": "DELETE", "endpoint": "/supplier/{id}"},
    },
}
```

### Tier 1: create_employee (med rolle)

```python
{
    "create_employee_admin": {
        "prompt": "Opprett en ansatt med navn Ola Nordmann, ola@example.org. Han skal være kontoadministrator.",
        "expected_parse": {
            "taskType": "create_employee",
            "fields": {
                "firstName": "Ola",
                "lastName": "Nordmann",
                "email": "ola@example.org",
                "role": "kontoadministrator",
            }
        },
        "verify": {
            "endpoint": "/employee",
            "search_params": {"firstName": "Ola", "lastName": "Nordmann"},
            "checks": {
                "firstName": "Ola",
                "lastName": "Nordmann",
                "email": "ola@example.org",
            },
            "extra_checks": ["entitlement_ALL_PRIVILEGES"],
        },
    },
}
```

### Tier 2: register_payment (viktig spesialtilfelle)

```python
{
    "register_payment": {
        "prompt": "Le client Océan SARL (nº org. 924390735) a une facture impayée de 39300 NOK hors TVA pour \"Maintenance\". Enregistrez le paiement intégral de cette facture.",
        "expected_parse": {
            "taskType": "register_payment",
            "fields": {
                "customerName": "Océan SARL",
                "customerOrgNumber": "924390735",
                "amount": 39300,
                "invoiceDescription": "Maintenance",
            }
        },
        # I konkurransen: kunde+faktura finnes allerede
        # I vår test: vi oppretter dem forst
        "setup": [
            {"action": "create_customer", "fields": {"name": "Océan SARL", "organizationNumber": "924390735"}},
            {"action": "create_invoice", "fields": {
                "customerName": "Océan SARL",
                "lines": [{"description": "Maintenance", "quantity": 1, "unitPriceExcludingVat": 39300}]
            }},
        ],
        "verify": {
            "endpoint": "/invoice",
            "search_by_customer_org": "924390735",
            "checks": {
                "amountOutstanding": 0,  # Fullt betalt
            }
        },
    },
}
```

### Tier 2: reverse_payment

```python
{
    "reverse_payment": {
        "prompt": "Betalingen fra Nordhav AS (org.nr 973826018) for fakturaen \"Opplæring\" (42500 kr ekskl. MVA) ble returnert av banken. Reverser betalingen.",
        "setup": [
            {"action": "create_customer", "fields": {"name": "Nordhav AS", "organizationNumber": "973826018"}},
            {"action": "create_and_pay_invoice", "fields": {
                "customerName": "Nordhav AS",
                "lines": [{"description": "Opplæring", "quantity": 1, "unitPriceExcludingVat": 42500}]
            }},
        ],
        "verify": {
            "endpoint": "/invoice",
            "search_by_customer_org": "973826018",
            "checks": {
                "amountOutstanding__gt": 0,  # Tilbake til ubetalt
            }
        },
    },
}
```

### Tier 1: batch_create_department

```python
{
    "batch_create_department": {
        "prompt": "Create three departments in Tripletex: \"Utvikling\", \"Lager\", and \"Regnskap\".",
        "expected_parse": {
            "taskType": "batch_create_department",
        },
        "verify": [
            {"endpoint": "/department", "search_params": {"name": "Utvikling"}, "checks": {"name": "Utvikling"}},
            {"endpoint": "/department", "search_params": {"name": "Lager"}, "checks": {"name": "Lager"}},
            {"endpoint": "/department", "search_params": {"name": "Regnskap"}, "checks": {"name": "Regnskap"}},
        ],
    },
}
```

### Tier 3: create_voucher

```python
{
    "create_voucher": {
        "prompt": "Opprett et bilag datert 2026-03-15 med beskrivelse 'Husleie mars'. Debiter konto 6300 med 15000 kr, krediter konto 1920.",
        "expected_parse": {
            "taskType": "create_voucher",
            "fields": {
                "description": "Husleie mars",
                "date": "2026-03-15",
                "postings": [
                    {"debitAccount": "6300", "creditAccount": "1920", "amount": 15000}
                ]
            }
        },
        "verify": {
            "endpoint": "/ledger/voucher/{id}",
            "checks": {
                "description__contains": "Husleie mars",
                "postings_balanced": True,
            }
        },
    },
}
```

---

## 5. Haandtering av faktura/betalings-flyt

### Problemet
I konkurransen pre-opprettes kunde + faktura for `register_payment`, `reverse_payment` og `create_credit_note`. Vår handler (`_ensure_invoice_exists`) oppretter hele kjeden selv om den ikke finnes. Dette betyr:

- **I konkurransen**: handler finner eksisterende faktura → registrerer betaling → 2-3 API-kall
- **I vår test uten setup**: handler oppretter customer → order → invoice → betaling → 6-8 API-kall
- **I vår test med setup**: vi oppretter forst, handler finner den → narmere konkurranse-flow

### Losning: to test-moduser

#### Modus 1: "Pipeline" (standard)
Tester at hele kjeden fungerer. Kjorer handleren direkte uten setup. Verifiserer sluttresultatet. Teller API-kall for efficiency-optimalisering.

#### Modus 2: "Competition-sim" (simulerer konkurranse)
Oppretter forutsetninger forst (setup-blokken). Kjorer handleren — den bor finne eksisterende data. Verifiserer at den IKKE opprettet duplikater. Teller API-kall — dette tallet er naermere hva konkurransen ser.

```python
# Kjor begge:
# python scripts/e2e_test.py --mode pipeline
# python scripts/e2e_test.py --mode competition
```

### Viktig sjekk for competition-mode
Etter at `register_payment`-handleren har kjort, verifiser at det IKKE ble opprettet en ny kunde eller faktura — handleren bor ha funnet den som allerede fantes.

---

## 6. Genererte prompts for handlers vi ikke har sett

Basert på data/requests/ har vi sett:
- create_supplier (spansk, engelsk)
- register_payment (fransk, portugisisk, norsk)
- create_project (nynorsk, engelsk)
- create_employee (nynorsk, fransk)
- create_product (norsk, tysk)
- create_customer (norsk)
- create_invoice (fransk)
- reverse_payment (norsk)
- batch_create_department (engelsk)

**Handlers vi IKKE har sett i ekte prompts:**
- create_travel_expense
- delete_travel_expense
- update_employee
- update_customer
- update_supplier
- update_product
- delete_employee
- delete_customer
- delete_supplier
- create_order
- create_voucher
- reverse_voucher
- delete_voucher
- create_credit_note
- register_supplier_invoice
- register_expense_receipt
- project_lifecycle
- overdue_invoice
- bank_reconciliation
- year_end_closing
- correct_ledger_error
- monthly_closing

For disse genererer vi syntetiske test-prompts:

```python
SYNTHETIC_PROMPTS = {
    "create_travel_expense": "Registrer en reiseregning for ansatt Per Hansen. Tittel: Kundebesøk Bergen. Dato: 2026-03-10. Kostnad: Togbillett 450 kr.",
    "delete_travel_expense": "Slett reiseregningen 'Kundebesøk Bergen' for Per Hansen.",
    "update_employee": "Oppdater mobilnummeret til ansatt Per Hansen til 99887766.",
    "update_customer": "Endre e-postadressen til kunden Testfirma AS (org.nr 999888777) til ny@testfirma.no.",
    "update_supplier": "Oppdater adressen til leverandøren Leveransen AS til Storgata 1, 0001 Oslo.",
    "update_product": "Endre prisen på produktet 'Konsulenttimer' til 1500 kr ekskl. MVA.",
    "delete_employee": "Slett ansatt Test Testesen.",
    "delete_customer": "Slett kunden Slettemeg AS (org.nr 999777666).",
    "delete_supplier": "Slett leverandøren Fjernansen AS.",
    "create_order": "Opprett en ordre til kunden Bestilling AS (org.nr 999666555) på 2 stk Konsulenttimer à 1200 kr ekskl. MVA.",
    "create_voucher": "Opprett et bilag datert 2026-03-15: Debet konto 6300 med 15000 kr, kredit konto 1920.",
    "reverse_voucher": "Reverser bilag nummer 1 datert 2026-03-15.",
    "delete_voucher": "Slett bilag nummer 2 datert 2026-03-15.",
    "create_credit_note": "Opprett en kreditnota for fakturaen til kunde Kredittkunden AS.",
    "register_supplier_invoice": "Registrer en leverandørfaktura fra Kontorsupply AS (org.nr 999555444) på 8500 kr for kontorutstyr. Dato: 2026-03-10.",
}
```

---

## 7. Praktisk implementasjonsplan

### Filstruktur

```
scripts/
  e2e_test.py                # CLI-entrypoint
tests/
  e2e/
    __init__.py
    conftest.py              # Shared fixtures, TripletexClient
    runner.py                # TestRunner-klasse
    definitions.py           # Alle test-definisjoner (prompts, fields, verify)
    verifier.py              # Felt-for-felt verifikasjon
    cleanup.py               # Best-effort cleanup-funksjoner
```

### Kjoring

```bash
# Kjor alle E2E-tester
python scripts/e2e_test.py

# Kun spesifikke handlers
python scripts/e2e_test.py --handlers create_supplier,create_employee

# Competition-simulering (oppretter forutsetninger forst)
python scripts/e2e_test.py --mode competition

# Pipeline-modus (tester hele kjeden)
python scripts/e2e_test.py --mode pipeline

# Med full prompt → parse → execute → verify (bruker LLM)
python scripts/e2e_test.py --full-pipeline

# Verbose output
python scripts/e2e_test.py -v
```

### Steg 1: Implementer runner.py

```python
"""E2E test runner."""
import asyncio
import time
from app.tripletex import TripletexClient
from app.handlers import HANDLER_REGISTRY, execute_task
from app.parser import parse_task

class E2ETestRunner:
    def __init__(self, client: TripletexClient, mode: str = "pipeline"):
        self.client = client
        self.mode = mode  # "pipeline" | "competition"
        self.results = []
        self.created_ids = []  # For cleanup

    async def run_test(self, test_def: dict) -> dict:
        test_name = test_def["name"]
        handler_name = test_def["handler"]

        # 1. Setup (kun i competition-mode)
        if self.mode == "competition" and test_def.get("setup"):
            for setup_step in test_def["setup"]:
                await self._run_setup(setup_step)

        # 2. Execute handler
        calls_before = len(self.client.tracker.api_calls)
        t0 = time.time()

        handler = HANDLER_REGISTRY.get(handler_name)
        if not handler:
            return {"name": test_name, "pass": False, "reason": "Handler ikke registrert"}

        result = await handler(self.client, test_def["fields"])

        elapsed = time.time() - t0
        calls_after = len(self.client.tracker.api_calls)
        api_calls = calls_after - calls_before
        errors_4xx = sum(1 for c in self.client.tracker.api_calls[calls_before:]
                        if 400 <= c.status < 500)

        # 3. Verify
        entity_id = self._extract_id(result)
        verify_result = await self._verify(test_def.get("verify", {}), entity_id)

        # 4. Registrer for cleanup
        if entity_id and test_def.get("cleanup"):
            self.created_ids.append((test_def["cleanup"]["endpoint"], entity_id))

        return {
            "name": test_name,
            "pass": verify_result["ok"],
            "checks": verify_result["checks"],
            "api_calls": api_calls,
            "errors_4xx": errors_4xx,
            "elapsed_sec": round(elapsed, 2),
            "reason": verify_result.get("reason", ""),
        }

    async def _verify(self, verify_def: dict, entity_id: int | None) -> dict:
        """Hent entiteten fra API og sjekk felt-for-felt."""
        if not verify_def:
            return {"ok": True, "checks": {}}

        endpoint = verify_def["endpoint"]
        if "{id}" in endpoint and entity_id:
            endpoint = endpoint.replace("{id}", str(entity_id))

        search_params = verify_def.get("search_params", {})
        resp = await self.client.get(endpoint, params=search_params)
        data = resp.json()

        # Finn entiteten
        if "values" in data:
            entities = data["values"]
            if not entities:
                return {"ok": False, "checks": {}, "reason": "Entitet ikke funnet"}
            entity = entities[0]
        elif "value" in data:
            entity = data["value"]
        else:
            entity = data

        # Sjekk felter
        checks = verify_def.get("checks", {})
        results = {}
        all_ok = True
        for field, expected in checks.items():
            actual = entity.get(field)
            if field.endswith("__contains"):
                real_field = field.replace("__contains", "")
                actual = entity.get(real_field, "")
                ok = expected in str(actual)
            elif field.endswith("__gt"):
                real_field = field.replace("__gt", "")
                actual = entity.get(real_field, 0)
                ok = actual > expected
            else:
                ok = str(actual) == str(expected)
            results[field] = {"expected": expected, "actual": actual, "ok": ok}
            if not ok:
                all_ok = False

        return {"ok": all_ok, "checks": results}

    async def cleanup(self):
        """Slett opprettede entiteter (best effort)."""
        for endpoint_template, entity_id in reversed(self.created_ids):
            endpoint = endpoint_template.replace("{id}", str(entity_id))
            try:
                await self.client.delete(endpoint)
            except Exception:
                pass  # Best effort
```

### Steg 2: Implementer test-definisjoner (definitions.py)

Se seksjon 4 over for format. Filen inneholder alle test-caser som en dict.

### Steg 3: Implementer full-pipeline-test

```python
async def run_full_pipeline_test(client, prompt: str, expected_task_type: str):
    """Test hele flyten: prompt → parse → handler → verify."""

    # 1. Parse prompt (bruker LLM)
    parsed = parse_task(prompt)
    assert parsed.task_type == expected_task_type, \
        f"Forventet {expected_task_type}, fikk {parsed.task_type}"

    # 2. Execute via dispatcher
    result = await execute_task(parsed.task_type, client, parsed.fields, prompt=prompt)

    # 3. Verifiser (handler-spesifikk)
    return result
```

### Steg 4: CLI-entrypoint (scripts/e2e_test.py)

Utvid eksisterende `pre_deploy_test.py`-struktur med:
- `--mode` flag for pipeline/competition
- `--handlers` filter
- `--full-pipeline` for prompt-til-verifikasjon
- `-v` for verbose logging
- Fargekodede resultater (PASS/FAIL)
- Oppsummering med API-kall-statistikk

### Steg 5: Kjoring og output

```
$ python scripts/e2e_test.py --mode competition -v

  E2E-test mot https://kkpqfuj-amager.tripletex.dev/v2
  Modus: competition (med forutsetninger)
  25 tester, 25 handlers

  =========================================================
  PASS  create_supplier          2 API-kall, 0 feil, 0.8s
        ✓ name=Dorada SL  ✓ orgNr=853166553  ✓ email
  PASS  create_customer          2 API-kall, 0 feil, 0.7s
        ✓ name  ✓ orgNr  ✓ email  ✓ isCustomer  ✓ address
  PASS  create_employee          3 API-kall, 0 feil, 1.2s
        ✓ firstName  ✓ lastName  ✓ email  ✓ entitlements
  PASS  register_payment         3 API-kall, 0 feil, 1.5s
        ✓ amountOutstanding=0
  FAIL  create_voucher           4 API-kall, 1 feil, 2.1s
        ✗ postings_balanced (forventet True, fikk False)
  =========================================================

  Totalt: 22 PASS, 3 FAIL
  API-kall: 67 totalt, 4 feil (4xx)

  FAIL-detaljer:
    - create_voucher: postings_balanced mismatch
    - reverse_voucher: Voucher not found
    - register_supplier_invoice: Account 4000 not found
```

---

## 8. Haandtering av sandbox-tilstand

### Forstegangs-setup
For forste gang E2E kjores mot en ren sandbox, trenger vi grunndata:
- Minst 1 avdeling (for create_employee)
- Bankkonto konfigurert (for `:invoice`)

Denne setupen bor vaere et eget skript: `scripts/setup_sandbox.py`

### Mellom testkjoringer
- Bruk unike tidsstempel-baserte navn: `f"E2E Supplier {int(time.time())}"`
- Cleanup etter hver test (DELETE)
- For vouchers: kan ikke alltid slettes, aksepter akkumulering

### Idempotens
Designet testerne slik at de kan kjores flere ganger uten at de feiler pga. gammel data:
- Alltid sok for entiteten forst
- Bruk unike identifikatorer
- Verifiser mot det vi nettopp opprettet, ikke alt i systemet

---

## 9. Prioritert implementasjonsrekkefolge

| # | Hva | Hvorfor | Estimat |
|---|-----|---------|---------|
| 1 | Refaktorer `pre_deploy_test.py` til å bruke verifikasjon (GET + feltsjekk) | Fanger reelle feil, ikke bare "ingen 4xx" | 2t |
| 2 | Legg til competition-mode for payment/credit-handlers | Dette er der vi feiler mest | 1t |
| 3 | Legg til full-pipeline-tester med ekte prompts fra `data/requests/` | Tester parsing + execution sammen | 2t |
| 4 | Legg til syntetiske prompts for usette handlers | Dekker blindsoner | 1t |
| 5 | Legg til API-kall-telling per test | Optimaliserer efficiency-bonus | 30min |
| 6 | Legg til cleanup-logikk | Holder sandbox ryddig | 1t |

**Total estimert tid: ca. 8 timer**

---

## 10. Ekte prompts som test-fixtures

Folgende filer fra `data/requests/` brukes direkte:

| Fil | Task type | Sprak |
|-----|-----------|-------|
| `20260319_222611_345499.json` | create_supplier | Spansk |
| `20260319_224215_118186.json` | register_payment | Fransk |
| `20260319_230350_991085.json` | create_project | Nynorsk |
| `20260319_230933_826389.json` | create_employee | Nynorsk |
| `20260319_231533_949354.json` | create_product | Norsk |
| `20260319_233306_546665.json` | create_project | Engelsk |
| `20260319_234203_448402.json` | register_payment | Portugisisk |
| `20260319_235722_219962.json` | create_customer | Norsk |
| `20260320_000515_044491.json` | create_employee | Fransk |
| `20260320_071441_354027.json` | create_invoice | Fransk |
| `20260320_073738_007842.json` | reverse_payment | Norsk |
| `20260320_074340_801034.json` | create_product | Tysk |
| `20260320_075419_094114.json` | batch_create_department | Engelsk |
| `20260320_082409_705223.json` | create_supplier | Engelsk |

Filene `20260320_084027_305835.json` (custom dimension) og `20260320_092843_639022.json` (lonnskjoring) er Tier 3-oppgaver vi ikke har handler for enna — bruk dem som fallback-handler-tester.
