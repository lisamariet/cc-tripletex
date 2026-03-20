# Analyse av Tripletex AI Agent - Submissions og Feilmoenstre

**Dato:** 2026-03-20
**Totalt antall submissions:** 24
**Totalt antall lokale request-logg:** 26 (inkl. 3 uten resultater)
**Totalt antall lokale result-logg:** 21

---

## 1. SAMLET POENGSTATUS

| # | Tidspunkt (UTC) | Raw Score | Max | Normalisert | Checks | Kommentar |
|---|-----------------|-----------|-----|-------------|--------|-----------|
| 1 | 19. mars 22:22 | 0/7 | 0.00 | 5/5 failed | Tidlig test, ingen handler fungerte |
| 2 | 19. mars 22:25 | 0/7 | 0.00 | 5/5 failed | Tidlig test |
| 3 | 19. mars 22:40 | 2/7 | 0.29 | 1/2 failed | create_supplier, delvis OK |
| 4 | 19. mars 23:03 | 0/7 | 0.00 | 4/4 failed | Mislyktes helt |
| 5 | 19. mars 23:09 | 0/8 | 0.00 | 7/7 failed | create_employee, alt feilet |
| 6 | 19. mars 23:15 | 0/7 | 0.00 | 5/5 failed | Feil |
| 7 | 19. mars 23:32 | **7/7** | **2.00** | All passed! | **PERFEKT** - create_project |
| 8 | 19. mars 23:41 | 2/7 | 0.29 | 1/2 failed | register_payment, delvis |
| 9 | 19. mars 23:57 | 5/8 | 0.63 | 3/7 failed | create_customer, 4/7 OK |
| 10 | 20. mars 00:05 | 0/8 | 0.00 | 7/7 failed | create_employee, feilet |
| 11 | 20. mars 07:09 | **8/8** | **2.00** | All passed! | **PERFEKT** - create_customer |
| 12 | 20. mars 07:14 | 0/7 | 0.00 | 5/5 failed | create_invoice, feilet |
| 13 | 20. mars 07:37 | 2/8 | 0.50 | 2/3 failed | reverse_payment, delvis |
| 14 | 20. mars 07:43 | 6/7 | 0.86 | 1/5 failed | create_product, nesten perfekt |
| 15 | 20. mars 07:53 | 0/7 | 0.00 | 3/3 failed | create_department batch, feilet |
| 16 | 20. mars 08:23 | 4/7 | 0.57 | 2/5 failed | create_supplier, bra |
| 17 | 20. mars 08:39 | 0/13 | 0.00 | 6/6 failed | custom dimension, ingen handler |
| 18 | 20. mars 09:27 | 0/8 | 0.00 | 4/4 failed | payroll/loennsavregning, ingen handler |
| 19 | 20. mars 11:47 | 0/13 | 0.00 | 6/6 failed | custom dimension, feilet med fallback |
| 20 | 20. mars 11:48 | 1/8 | 0.25 | 4/5 failed | credit_note, nesten alt feilet |
| 21 | 20. mars 11:51 | 0/8 | 0.00 | 5/5 failed | order->invoice->payment, feilet |
| 22 | 20. mars 11:51 | 0/8 | 0.00 | 6/6 failed | multi-line faktura, feilet |
| 23 | 20. mars 12:49 | 2/7 | 0.29 | 1/2 failed | register_payment, delvis OK |
| 24 | 20. mars 13:10 | 0/8 | 0.00 | 4/4 failed | timeregistrering+prosjektfaktura, feilet |

**Totalt opptjent:** 32 poeng raw, av 189 mulige max = **16.9% suksessrate**
**Perfekte scores:** 2 av 24 (8.3%)
**Null-scores:** 15 av 24 (62.5%)

---

## 2. OPPGAVETYPER - HVA FUNGERER OG HVA FEILER

### Fungerer godt (score >= 50%):
| Oppgavetype | Antall | Beste score | Kommentar |
|-------------|--------|-------------|-----------|
| create_customer | 2 | **2.00 (100%)** | Fungerer perfekt nar sandboxen er ren |
| create_project | 1 | **2.00 (100%)** | Perfekt score |
| create_supplier | 2 | 0.57 (57%) | Delvis - mangler noe |
| create_product | 1 | 0.86 (86%) | Nesten perfekt, 1 check feilet |

### Fungerer delvis (score > 0 men < 50%):
| Oppgavetype | Antall | Beste score | Problem |
|-------------|--------|-------------|---------|
| register_payment | 3 | 0.29 | Finner ikke faktura, eller oppretter feil |
| reverse_payment | 1 | 0.50 | Pipeline feiler delvis |
| create_credit_note | 1 | 0.25 | Finner faktura men createCreditNote feiler (422) |

### Fungerer ikke (score = 0):
| Oppgavetype | Antall | Problem |
|-------------|--------|---------|
| create_employee | 2 | 422-feil pa POST /employee - trolig manglende/feil felt |
| create_invoice | 2 | Ordre opprettes men :invoice feiler (422/404) |
| batch_create_department | 1 | Parser returnerer liste -> 'list' object has no attribute 'get' |
| custom_dimension (ukjent) | 2 | Ingen dedikert handler, fallback feiler |
| payroll/loenn (ukjent) | 1 | Ingen handler, fallback JSON parse error |
| order->invoice->payment (ukjent) | 1 | Kompleks flerstegsoppgave, fallback feiler med 422/404 |
| timeregistrering+prosjektfaktura (ukjent) | 1 | 5 av 8 kall feiler (400/422) |

---

## 3. DETALJERT FEILANALYSE

### 3.1 create_employee - 422-feil (2 tilfeller)
**Logg:** 20260320_000515 (Sarah Richard), 20260319_230933 (Bjorn Neset, uten result-logg)
- Parser fungerer: firstName, lastName, email, dateOfBirth, startDate blir korrekt ekstrakt
- GET /department returnerer 200 OK
- POST /employee returnerer **422 Unprocessable Entity**
- Resultatet er `"created": {}` - tomt objekt
- **Rotaarsak:** Sannsynligvis mangler required fields som `userType` settes, men `startDate` sendes IKKE pa Employee (er kommentert ut: "belongs on Employment, not Employee"). Det kan vaere sandboxen krever Employment-opprettelse separat, eller at datoen er ugyldig.
- **Fix:** Etter POST /employee, opprett Employment med POST /employee/employment med startDate. Feilhaandtering bor logge selve 422-meldingen fra API-et.

### 3.2 create_invoice - 422 pa /order og 404 pa :invoice (2 tilfeller)
**Logg:** 20260320_071441 (Colline SARL), 20260320_115144 (Bolgekraft AS multi-line)
- Colline SARL: POST /order returnerer 422, deretter PUT /order/None/:invoice gir 404 (fordi order_id er None)
- Bolgekraft multi-line: POST /order returnerer 201 OK, men PUT /order/401955456/:invoice returnerer 422
- **Rotaarsak for 422 pa ordre:** Ordrelinjer mangler trolig product-referanse eller har feil vatType-format. Tripletex krever enten et produkt eller spesifikke felter pa ordrelinjer.
- **Rotaarsak for 404:** Nar ordre-opprettelse feiler, blir order_id None, og URL-en blir `/order/None/:invoice`.
- **Fix:**
  1. Legg til bedre feilhaandtering nar POST /order feiler (les feilmeldingen)
  2. Test at ordrelinjer har korrekt format for Tripletex API
  3. Mulig at `unitPriceExcludingVatCurrency` trenger et `product`-objekt

### 3.3 Batch-oppgaver feiler med TypeError (1 tilfelle)
**Logg:** 20260320_075419 - "Create three departments"
- `parsed_task: null`, error: `'list' object has no attribute 'get'`
- **Rotaarsak:** Parseren returnerer en liste med 3 elementer. Batch-logikken i `parser.py` (linje 176-189) haandterer dette korrekt i teorien, men noe feiler i praksis. Trolig returnerer LLM en liste der hvert element IKKE har `taskType`-noekkelen, eller formatet er uventet.
- **Fix:** Legg til mer robust haandtering av listeformat. Logg raat LLM-svar ved feil. Test med mock.

### 3.4 create_product - 422 pa forste forsok (1 tilfelle)
**Logg:** 20260319_231533 (Konsulenttimer, vatCode "3")
- GET /ledger/vatType returnerer 200
- POST /product returnerer 422
- Resultatet er `"created": {}` - tomt
- **Rotaarsak:** vatCode "3" ble brukt, vatType ble slatt opp. Men produktet ble IKKE opprettet. 422-feilen indikerer ugyldig payload. Mulig at `number` feltet "9497" er string men Tripletex forventer integer, eller at vatType-ID er feil.
- **Sammenligning:** 20260320_074340 (Orangensaft) lyktes med noyaktig samme flow. Forskjellen: Orangensaft brukte vatCode "2" og fikk vatType id=3. Men Konsulenttimer brukte vatCode "3" og fikk trolig RIKTIG vatType. Kan vaere at `number` feltet kolliderer med eksisterende produkt.

### 3.5 register_payment - Finner ikke faktura (3 tilfeller)
**Logg:** 20260319_234203 (Luz do Sol), 20260320_073738 (Nordhav AS), 20260320_124957 (Floresta Lda)
- Floresta Lda (124957): **Fungerte!** Score 2/7, fant faktura, registrerte betaling OK
- Luz do Sol: GET /invoice returnerer 422 - feilparametre i soeket
- Nordhav AS: GET /invoice returnerer 200 men tom liste - ingen faktura funnet
- **Rotaarsak:** `_find_invoice` soeker med `invoiceDateFrom` og `invoiceDateTo`, men faar ingen treff. For Luz do Sol feiler selve GET /invoice med 422, trolig pga feil parameterformat.
- **Forbedring:** `_ensure_invoice_exists` oppretter naa hele kjeden (kunde->ordre->faktura), men dette feiler ofte pga ordrelinje-problemer. Floresta Lda viser at nar pipeline fungerer, saa fungerer betalingen ogsaa.

### 3.6 create_credit_note - 422 pa :createCreditNote (1 tilfelle)
**Logg:** 20260320_114811 (Vestfjord AS)
- Finner kunde OK, finner faktura OK (id 2147490386)
- PUT /invoice/2147490386/:createCreditNote returnerer 422
- **Rotaarsak:** Fakturaen er kanskje allerede kreditert, eller det mangler parametre. Tripletex :createCreditNote kan kreve at fakturaen har status "sent" eller lignende.
- **Fix:** Sjekk fakturastatus for kreditering. Les 422-feilmeldingen fra API-et.

### 3.7 Ukjente oppgavetyper som faller til fallback
| Oppgave | Logg-ID | Resultat |
|---------|---------|----------|
| Custom dimension + bilag | 084027, 114805 | fallback genererer kall, men 422 pa voucher |
| Loennsavregning (payroll) | 092843 | JSON parse error fra fallback-LLM |
| Ordre->faktura->betaling | 115104 | Fallback: 3 av 4 kall feiler (422/404) |
| Timeregistrering+prosjektfaktura | 131006 | Fallback: 5 av 8 kall feiler |

---

## 4. 4xx-FEIL OVERSIKT

| HTTP-status | Antall | Vanligste endepunkt | Aarsak |
|-------------|--------|---------------------|--------|
| 422 | 12 | POST /order, POST /product, POST /employee, POST /invoice, PUT /:createCreditNote | Ugyldig payload - manglende/feil felt |
| 404 | 3 | PUT /order/None/:invoice, PUT /invoice/$PREV/:payment | Referanse til ikke-eksisterende ressurs (None/placeholder ikke resolved) |
| 400 | 1 | GET /activity | Feil queryparametre |

**422 er det klart stoerste problemet** - 12 av 16 feil (75%).

---

## 5. EFFEKTIVITETSANALYSE (API-kall)

| Handler | Gj.snitt kall | Min-max | Kommentar |
|---------|---------------|---------|-----------|
| create_customer | 1.0 | 1 | Optimalt |
| create_supplier | 1.0 | 1 | Optimalt |
| create_product | 2.0 | 2 | 1 GET vatType + 1 POST |
| create_project | 3.0 | 3 | GET employee + GET customer + POST project |
| create_invoice | 4-6 | 4-6 | GET customer + N*GET vatType + POST order + PUT :invoice |
| register_payment | 2-4 | 2-4 | GET customer + GET invoice + GET paymentType + PUT :payment |
| create_credit_note | 3.0 | 3 | GET customer + GET invoice + PUT :createCreditNote |
| fallback (ukjent) | 3-8 | 0-8 | Uforutsigbart, mange feil |

**Stoerste ineffektivitet:**
- `create_invoice` med multi-line: 6 kall, inkludert **3 separate GET /ledger/vatType** for same vatCode. Bor cache vatType-oppslag.
- Fallback-handler bruker 3-8 kall og feiler nesten alltid.

---

## 6. MATRISE: SUBMISSION vs LOKAL LOGG (tidspunktkobling)

| Submission UTC | Score | Lokal logg-timestamp | Oppgavetype | Match |
|----------------|-------|---------------------|-------------|-------|
| 19. mar 23:32 | 7/7 PERFEKT | 20260319_233306 | create_project | Ja - Northwave |
| 20. mar 07:09 | 8/8 PERFEKT | 20260320_071043 | create_customer | Ja - Bolgekraft |
| 20. mar 07:43 | 6/7 | 20260320_074340 | create_product | Ja - Orangensaft |
| 20. mar 08:23 | 4/7 | 20260320_082409 | create_supplier | Ja - Northwave Ltd |
| 20. mar 12:49 | 2/7 | 20260320_124957 | register_payment | Ja - Floresta |

---

## 7. PRIORITERT HANDLINGSPLAN (stoerst poengforbedring foerst)

### Prioritet 1: Fiks create_employee (8-16 poeng potensial)
- **Problem:** POST /employee gir 422
- **Tiltak:**
  - Logg full 422-respons fra Tripletex for aa se noyaktig hva som mangler
  - Opprett Employment (POST /employee/employment) etter Employee med startDate
  - Test med ulike userType-verdier
- **Estimert effekt:** 8+ poeng (2 oppgaver sett, max 8 poeng hver)

### Prioritet 2: Fiks create_invoice ordrelinje-format (8-16 poeng potensial)
- **Problem:** POST /order gir 422, eller PUT /order/:invoice gir 422
- **Tiltak:**
  - Logg full 422-respons
  - Test ordrelinje-format: mulig at `description` alene ikke holder, trenger kanskje `product`-referanse
  - Sjekk om vatType pa ordrelinje har korrekt format
  - Haandter `order_id = None` gracefully (ikke kall :invoice med None)
- **Estimert effekt:** 8+ poeng

### Prioritet 3: Implementer dedicated handlers for nye oppgavetyper
- **Custom dimension + bilag** (2 oppgaver sett, 13 poeng max): Implementer handler for `create_custom_dimension` og `create_voucher_with_dimension`
- **Loennsavregning/payroll** (1 oppgave, 8 poeng max): Implementer `run_payroll` handler med salary/transaction og salary/payslip
- **Timeregistrering + prosjektfaktura** (1 oppgave, 8 poeng max): Implementer `register_project_hours` + prosjektfakturering
- **Estimert effekt:** 20+ poeng

### Prioritet 4: Fiks batch-haandtering (7 poeng potensial)
- **Problem:** Batch-oppgaver (f.eks. "opprett 3 avdelinger") krasjer med TypeError
- **Tiltak:** Fiks listeparsing i parser.py - sorg for at hvert element har `taskType` og `fields`
- **Estimert effekt:** 7 poeng

### Prioritet 5: Forbedre register_payment og reverse_payment
- **Problem:** Finner ikke faktura, eller oppretter feil pipeline
- **Tiltak:**
  - Forbedre `_ensure_invoice_exists` til aa haandtere ordrelinjefeil
  - Bruk `paidAmount` korrekt (inkl. MVA, ikke ekskl.)
  - Forbedre fakturasok med flere parametre
- **Estimert effekt:** 5-10 poeng

### Prioritet 6: Forbedre create_credit_note
- **Problem:** 422 pa :createCreditNote
- **Tiltak:** Sjekk fakturastatus foer kreditering, les feilmelding
- **Estimert effekt:** 3-5 poeng

### Prioritet 7: Optimaliseringer
- **Cache vatType-oppslag** - spar 1-3 API-kall per faktura
- **Logg 422/400-responskropp** - kritisk for feilsoking
- **Forbedre fallback-handler** - bruk sterkere modell (claude-sonnet) i stedet for haiku

---

## 8. SPRAKDISTRIBUSJON

Oppgavene kommer pa mange sprak:
- **Norsk (bokmal/nynorsk):** 7 oppgaver
- **Fransk:** 4 oppgaver
- **Portugisisk:** 4 oppgaver
- **Engelsk:** 3 oppgaver
- **Tysk:** 3 oppgaver
- **Spansk:** 1 oppgave
- **Test:** 2 oppgaver (tomme)

Parseren haandterer alle sprak godt - ingen sprakrelaterte feil observert.

---

## 9. KONKLUSJON

Agenten fungerer godt for **enkle opprettelse-oppgaver** (kunde, leverandor, prosjekt, produkt) men feiler paa **alt som involverer fakturering, ansatte, og komplekse flerstegsoperasjoner**.

De tre viktigste forbedringene er:
1. **Fiks 422-feil pa create_employee og create_invoice** (krever API-feilmeldingslogging)
2. **Implementer dedikerte handlers for custom dimension, payroll, og timeregistrering**
3. **Fiks batch-parsing**

Med disse forbedringene kan vi gaa fra ~17% til potensielt 60-70% suksessrate.
