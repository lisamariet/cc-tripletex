from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

import anthropic

from app.config import ANTHROPIC_API_KEY, LLM_MODEL, LLM_FALLBACK_MODEL
from app.file_processor import process_files
from app.models import ParsedTask

# Parser backend selection (haiku | gemini | embedding | auto)
PARSER_BACKEND = os.getenv("PARSER_BACKEND", "gemini")

logger = logging.getLogger(__name__)

# All valid task types that have registered handlers
VALID_TASK_TYPES = {
    "create_supplier", "create_customer", "create_employee", "create_product",
    "create_department", "create_invoice", "register_payment", "reverse_payment",
    "create_credit_note", "create_travel_expense", "delete_travel_expense",
    "create_project", "set_project_fixed_price", "update_employee",
    "update_customer", "create_voucher", "reverse_voucher", "delete_voucher",
    "update_supplier", "update_product", "delete_employee", "delete_customer",
    "delete_supplier", "create_order", "register_supplier_invoice",
    "register_timesheet", "create_invoice_from_pdf", "run_payroll",
    "create_custom_dimension",
    "bank_reconciliation",
    "year_end_closing",
    "correct_ledger_error",
    "monthly_closing",
    "register_expense_receipt",
    "overdue_invoice",
}

# Keyword patterns for inferring task type when LLM returns "unknown"
# Each entry: (task_type, list of regex patterns — match ANY = positive signal)
_KEYWORD_RULES: list[tuple[str, list[str]]] = [
    ("year_end_closing", [
        r"årsavslutning|årsoppgjør|year.?end.?clos|cierre.?de.?año|clôture.?annuelle|Jahresabschluss|encerramento.?anual",
        r"(?:lukk|close|cerrar|clôturer|schließen|fechar).{0,30}(?:regnskapsår|regnskapsperiode|fiscal.?year|accounting.?year|ejercicio|année.?comptable|Geschäftsjahr|ano.?fiscal)",
        r"åpningsbalanse|opening.?balance|balance.?d.?ouverture|Eröffnungsbilanz|balance.?de.?apertura|balanço.?de.?abertura",
    ]),
    ("bank_reconciliation", [
        r"bankavstemming|bank.?reconcili|conciliación.?banc|rapprochement.?banc|Bankabstimmung|conciliação.?banc",
        r"(?:avstem|reconcil|concili|rapproch).{0,30}(?:bank|konto|account|cuenta|compte|Konto|conta)",
        r"bank.?statement.?match|banktransaksjon.{0,20}match|bankutskrift",
    ]),
    ("monthly_closing", [
        r"månedsavslutning|monthly.?clos|cierre.?mensual|clôture.?mensuel|Monatsabschluss|encerramento.?mensal",
        r"periodisering|accrual|periodificación|periodisation|Periodenabgrenzung|periodização",
        r"avskrivning|depreciation|depreciación|amortissement|Abschreibung|depreciação",
    ]),
    ("correct_ledger_error", [
        r"feilretting|feilrett|error.?correct|correct.{0,20}(?:ledger|posting|entry|voucher|bilag)",
        r"(?:rett|korriger|correct|fix|corrig).{0,30}(?:feil|error|mistake|bokfør|posting|bilag|voucher|asiento|lançamento|écriture|Buchung)",
        r"(?:feil|error|mistake|erreur|Fehler|erro).{0,30}(?:i regnskap|in.?(?:ledger|accounting|bookkeeping)|en.?contabilidad|dans.?la.?comptabilité|in.?der.?Buchhaltung|na.?contabilidade)",
        r"korreksjonsbilag|correction.?voucher|corrective.?entry|asiento.?correct|écriture.?correct|Korrekturbuchung|lançamento.?correct",
        r"(?:reverser|reverse|tilbakefør).{0,30}(?:og|and|y|et|und|e).{0,30}(?:korriger|correct|rett|fix|corrig)",
        r"erreurs?.{0,30}grand.?livre|grand.?livre.{0,30}erreurs?",
        # French: pièce en double, écriture mauvais compte, TVA manquante
        r"pi[eè]ce.{0,20}(?:double|err|faux)|écriture.{0,20}mauvais.?compte|TVA.{0,20}manquante",
        r"montant.{0,20}incorrect|compte.{0,10}utilis[eé].{0,20}(?:au lieu|instead)",
        # German: Hauptbuch-Fehler, Buchungsfehler, falsches Konto — only when error-correction context
        r"Hauptbuch.{0,30}(?:Fehler|überprüf|prüfen|korrigier)|Hauptbuch.{0,50}(?:Fehler|falsches?\s+Konto)",
        r"(?:falsches?|falsche).{0,20}(?:Konto|Buchung)|Buchungsfehler|Kontofehler",
        r"(?:Fehler|Korrekt).{0,30}Buchung|(?:Buchung|Konto).{0,30}(?:korrigier|berichtig)",
    ]),
    ("register_supplier_invoice", [
        r"leverand[oø]rfaktura|leverand[oø]r.{0,20}faktura",
        r"leverandorfaktura.*(?:PDF|vedlagt|attached)|(?:PDF|vedlagt|attached).*leverandorfaktura",
        r"supplier.?invoice.*(?:PDF|attached)|(?:PDF|attached).*supplier.?invoice",
        r"factura.*proveedor.*PDF|PDF.*factura.*proveedor",
    ]),
    ("create_custom_dimension", [
        r"dimensjon|dimension|dimensão|dimensión|Dimension",
        r"regnskapsdimensjon|accounting dimension|dimensão contab|dimensión contab|comptable.*dimension|dimension.*comptable",
    ]),
    ("set_project_fixed_price", [
        r"fastpris|fixed.?price|preço fixo|precio fijo|Festpreis|prix forfait(?:aire)?",
        # "prix fixe" only when combined with project context — not standalone (avoid matching "prix fixe" in other contexts)
        r"(?:prosjekt|project|projet|proyecto|projeto|Projekt).{0,60}(?:fastpris|fixed.?price|preço fixo|precio fijo|Festpreis|prix forfait|prix fixe)",
        r"(?:fastpris|fixed.?price|preço fixo|precio fijo|Festpreis|prix forfait|prix fixe).{0,60}(?:prosjekt|project|projet|proyecto|projeto|Projekt)",
    ]),
    ("run_payroll", [
        r"payroll|lønnskjøring|lønn(?:s)?kjøring|Gehaltsabrechnung|nómina|folha de pagamento|paie",
        r"(?:base|grunn).*(?:salary|gehalt|lønn|salário|salario)|(?:salary|gehalt|lønn|salário|salario).*(?:base|grunn)",
        r"Grundgehalt|baseSalary|grunnlønn",
    ]),
    ("register_timesheet", [
        r"(?:registrer?|log|book|regist[ea]r?).{0,20}(?:timer|hours?|horas?|Stunden|heures)",
        r"timesheet|timeliste|tidsskjema",
        r"horas para .+na atividade",
        r"(?:timer|hours?|horas?|Stunden|heures).{0,80}(?:prosjektfaktura|project.invoice|factura.*proyecto|fatura.*projeto|Projektrechnung|facture.*projet)",
        r"(?:prosjektfaktura|project.invoice).{0,80}(?:timer|hours?|horas?|Stunden|heures)",
    ]),
    ("create_travel_expense", [
        r"reiseregning|travel.?expense|gastos de viaje|frais de voyage|Reisekosten|despesas de viagem|nota de gastos",
        r"reiserekning|reiseutgift|Reisekostenabrechnung",
    ]),
    ("overdue_invoice", [
        r"(?:overdue|forfalt|vencida|en retard|überfällig|rappel).{0,60}(?:invoice|faktura|fatura|factura|Rechnung|facture)",
        r"(?:invoice|faktura|fatura|factura|Rechnung|facture).{0,60}(?:overdue|forfalt|vencida|en retard|überfällig)",
        r"(?:reminder|purre|rappel|lembrete|Mahn).{0,30}(?:fee|gebyr|gebühr|frais|taxa)",
        r"purregebyr|Mahngebühr|frais de rappel|taxa de lembrete|reminder fee",
    ]),
    ("create_order", [
        r"(?:opprett|create|cre[ea]r?|erstellen).{0,30}(?:ordre|order|pedido|Auftrag|commande|bestilling)",
        r"Auftrag.{0,20}(?:erstellen|anlegen)",
    ]),
    ("create_invoice", [
        r"(?:opprett|create|cre[ea]r?|erstellen).{0,30}(?:faktura|invoice|fatura|factura|Rechnung|facture)",
    ]),
    ("register_payment", [
        r"(?:registrer?|register|enregistr|regist[ea]r?).{0,30}(?:betaling|payment|pago|pagamento|Zahlung|paiement)",
    ]),
    ("create_supplier", [
        r"(?:opprett|registrer?|create|register|cre[ea]r?|erstellen|regist[ea]r?).{0,30}(?:leverandør|supplier|proveedor|fornecedor|Lieferant|fournisseur)",
    ]),
    ("create_customer", [
        r"(?:opprett|registrer?|create|register|cre[ea]r?|erstellen|regist[ea]r?).{0,30}(?:kunde|customer|client[e]?|Kunde|client)",
    ]),
    ("create_employee", [
        r"(?:opprett|registrer?|create|register|cre[ea]r?|erstellen|regist[ea]r?).{0,30}(?:ansatt|employee|empleado|empregado|Mitarbeiter|employé)",
    ]),
    ("create_project", [
        r"(?:opprett|create|cre[ea]r?|erstellen).{0,30}(?:prosjekt|project|proyecto|projeto|Projekt|projet)",
        # German: "internes Projekt", "Erstellen Sie ... Projekt"
        r"internes?.{0,10}Projekt|Projekt.{0,30}(?:anlegen|einrichten|erstellen)",
        # German: Analyse Hauptbuch + Projektanlage — Aufwandskonto-Analyse triggers project creation
        r"Aufwandskont(?:en?|o).{0,60}(?:Projekt|erstellen|anlegen)",
        r"(?:Haupt|haupt)buch.{0,80}(?:Projekt|erstellen|anlegen|identifizi)",
    ]),
    ("create_voucher", [
        r"(?:opprett|create|bokfør|cre[ea]r?|erstellen|comptabilise).{0,30}(?:bilag|voucher|asiento|lançamento|Beleg|pièce|écriture)",
    ]),
    ("register_supplier_invoice", [
        r"(?:leverand[oø]r|supplier|innkj[øo]ps).*faktura|supplier.invoice|factura.*proveedor|fatura.*fornecedor",
        r"leverand[oø]rfaktura",
    ]),
    ("create_credit_note", [
        r"kreditnota|credit.?note|nota de crédito|Gutschrift|note de crédit|avoir",
    ]),
    ("register_expense_receipt", [
        r"kvittering|receipt|reçu|Quittung|recibo|ricevuta|kvitto",
        r"(?:registrer?|bokfør|record|enregistr|regist[ea]r?|erfassen|registrar).{0,40}(?:kvittering|receipt|reçu|Quittung|recibo|ricevuta|kvitto)",
        r"(?:utgift|expense|Ausgabe|dépense|gasto|despesa).{0,40}(?:kvittering|receipt|reçu|Quittung|recibo|avdeling|département|department|Abteilung)",
        r"(?:kvittering|receipt|reçu|Quittung|recibo).{0,40}(?:utgift|expense|Ausgabe|dépense|gasto|despesa|avdeling|department)",
        # French with/without accents: dépense/depense + reçu/recu
        r"d[eé]pense.*re[çc]u|re[çc]u.*d[eé]pense",
        # French: "besoin de la depense ... de ce recu" (accent-stripped variants)
        r"(?:la\s+)?d[eé]pense\s+\S+\s+de\s+ce\s+re[çc]u",
        # Portuguese: despesa + recibo without requiring proximity
        r"despesa.{0,60}recibo|recibo.{0,60}despesa",
        # French: "enregistree au departement" (accent-stripped)
        r"enregistr[eé][es]?\s+au\s+d[eé]partement",
        # German: Ausgabe/Ausgabenbeleg + Abteilung
        r"(?:Ausgabe|Kassenbon|Quittung).{0,40}Abteilung|Abteilung.{0,40}(?:Ausgabe|Kassenbon|Quittung)",
    ]),
]


_YEAR_END_SIGNALS = re.compile(
    r"årsavslutning|årsoppgjør|year.?end|cierre.*anual|encerramento.*anual|"
    r"Jahresabschluss|clôture.*annuelle|forenkl.*årsavslut|simplified.*year.?end|"
    r"cierre.*simplificado|encerramento.*simplificado|clôture.*simplifiée",
    re.IGNORECASE,
)


def _infer_task_type_from_keywords(prompt: str) -> str | None:
    """Try to infer task type from keywords in the prompt. Returns None if no match."""
    prompt_lower = prompt.lower()

    # Disambiguation: if prompt mentions year-end closing keywords BUT also mentions
    # depreciations/accruals/provisions, it should be monthly_closing (posting vouchers)
    # rather than year_end_closing (closing accounting periods).
    # EXCEPTION: "forenklet årsavslutning med avskrivninger" IS year_end_closing —
    # year-end signals override the monthly signals.
    _MONTHLY_SIGNALS = re.compile(
        r"avskrivning|depreciation|depreciaci[oó]n|d[eé]pr[eé]ciation|Abschreibung|deprecia[cç][aã]o"
        r"|periodisering|accrual|periodificaci[oó]n|periodisation|Periodenabgrenzung|periodiza[cç][aã]o"
        r"|avsetning|provision|provisi[oó]n|provision salariale|R[uü]ckstellung|provis[aã]o"
        r"|forskudd|prepaid|skatteavsetning|tax.?provision"
        r"|Gehaltsrückstellung|lønnsavsetning|dotaci[oó]n|acumula[cç][aã]o",
        re.IGNORECASE,
    )

    # Reminder fee / purregebyr signals — these should NOT be classified as set_project_fixed_price
    _REMINDER_FEE_SIGNALS = re.compile(
        r"frais de rappel|taxa de lembrete|purregebyr|reminder.?fee|late.?fee"
        r"|overdue.?fee|frais.{0,20}retard|frais.{0,20}rappel|lembrete.{0,20}atraso",
        re.IGNORECASE,
    )

    for task_type, patterns in _KEYWORD_RULES:
        for pattern in patterns:
            if re.search(pattern, prompt_lower, re.IGNORECASE):
                # If we matched year_end_closing but prompt has monthly_closing signals, reclassify
                if task_type == "year_end_closing" and _MONTHLY_SIGNALS.search(prompt_lower):
                    if _YEAR_END_SIGNALS.search(prompt_lower):
                        # Year-end + avskrivning = forenklet årsavslutning, IKKE monthly_closing
                        logger.info(f"Keyword match '{pattern}' → year_end_closing (year-end signals override monthly signals)")
                        return "year_end_closing"
                    logger.info(f"Keyword match '{pattern}' → monthly_closing (monthly signals without year-end context)")
                    return "monthly_closing"
                # If we matched monthly_closing but prompt has year-end signals, reclassify to year_end_closing
                # (e.g. "cierre anual simplificado" with "depreciación" should be year_end_closing)
                if task_type == "monthly_closing" and _YEAR_END_SIGNALS.search(prompt_lower):
                    logger.info(f"Keyword match '{pattern}' → monthly_closing, but year-end signals present → year_end_closing")
                    return "year_end_closing"
                # If we matched set_project_fixed_price but prompt is about reminder/late fees, use overdue_invoice
                if task_type == "set_project_fixed_price" and _REMINDER_FEE_SIGNALS.search(prompt_lower):
                    logger.info(f"Keyword match '{pattern}' → set_project_fixed_price, but reminder fee signals present → overdue_invoice")
                    return "overdue_invoice"
                logger.info(f"Keyword match: '{pattern}' → {task_type}")
                return task_type
    return None


SYSTEM_PROMPT = """You are an accounting task parser for Tripletex (Norwegian accounting software).
You receive a task prompt in one of these languages: Norwegian Bokmål, Norwegian Nynorsk, English, Spanish, Portuguese, German, or French.

Extract the task type and relevant fields. Return ONLY valid JSON.

IMPORTANT: If the prompt references an attached file (PDF, image), the file content is included in this message. Extract ALL relevant data from both the prompt text AND the attached file. For offer letters / tilbudsbrev: extract name, email, national identity number (fødselsnummer/personnummer), bank account, occupation code (STYRK), department, salary, employment percentage, start date, and work hours from the PDF.

IMPORTANT: You MUST classify the task as one of the supported types below. Only use "unknown" as an absolute last resort when none of the types match at all.

Supported task types and their fields:

1. "create_supplier" — Register a new supplier
   Fields: name*, organizationNumber, email (IMPORTANT: for suppliers, put the email ONLY in the "email" field — do NOT copy to invoiceEmail unless the prompt explicitly says "invoice email" or "fakturaepost"), invoiceEmail (only if explicitly mentioned as invoice/faktura email), phoneNumber, phoneNumberMobile, isPrivateIndividual (bool), description, bankAccount, website, address (object with addressLine1, addressLine2, postalCode, city)

2. "create_customer" — Register a new customer
   Fields: name*, organizationNumber, email (IMPORTANT: if prompt says "email" or "e-post" without specifying type, put it in BOTH email AND invoiceEmail), invoiceEmail, phoneNumber, phoneNumberMobile, isPrivateIndividual (bool), description, isSupplier (bool), website, address (object with addressLine1, addressLine2, postalCode, city)

3. "create_employee" — Register a new employee
   Fields: firstName*, lastName*, email, phoneNumberMobile, dateOfBirth (YYYY-MM-DD), startDate (YYYY-MM-DD), employeeNumber, nationalIdentityNumber (11-digit Norwegian fødselsnummer/personnummer), bankAccountNumber (11-digit Norwegian bank account), address (object with addressLine1, postalCode, city), role (string — extract if the prompt mentions a role like "administrator", "kontoadministrator", "accountant", "regnskapsfører", "faktureringsansvarlig", "avdelingsleder", etc.), occupationCode (string — the STYRK/occupation code if mentioned, e.g. "3313"), employmentPercentage (number 0–100 — employment percentage / stillingsprosent, e.g. 80 for 80%), annualSalary (number — annual salary in NOK if mentioned, e.g. 640000), monthlySalary (number — monthly salary in NOK if mentioned), department (string — department name if mentioned, e.g. "Drift", "Kundeservice", "IT"), hoursPerDay (number — standard work hours per day, e.g. 7.5)

4. "create_product" — Register a new product
   Fields: name*, number, priceExcludingVat (number), priceIncludingVat (number), costExcludingVat (number), description, vatCode (string — Tripletex codes: "3" = 25% standard, "31" = 15% food/middels, "33" = 12% low/transport, "5" = 0% exempt, "6" = 0% outside VAT law), isInactive (bool)

5. "create_department" — Create a department
   Fields: name*, departmentNumber, departmentManagerName (string — full name of the department manager if mentioned in the prompt)

6. "create_invoice" — Create an invoice for a customer
   Fields: customerName*, customerOrgNumber, invoiceDate (YYYY-MM-DD), dueDate (YYYY-MM-DD), lines* (array of {description, productNumber (extract the number in parentheses if present, e.g. "Konsulenttimer (9497)" → productNumber: "9497"), quantity, unitPriceExcludingVat, vatCode — use "3" for 25%, "31" for 15%, "33" for 12%, "5" for 0%})
   IMPORTANT: If the prompt mentions product numbers like "(4783)" next to product names, include productNumber in each line.

7. "register_payment" — Register payment on an existing invoice (customer pays)
   Fields: customerName, customerOrgNumber, invoiceNumber (integer only), amount, paymentDate (YYYY-MM-DD), invoiceDescription (what the invoice was for, e.g. "Maintenance"), lines (array of {description, quantity, unitPriceExcludingVat, vatCode} — extract if the prompt describes invoice line items), foreignCurrency (string ISO code if invoice was in foreign currency, e.g. "EUR"), foreignAmount (number — invoice amount in foreign currency), invoiceExchangeRate (number — exchange rate when invoice was issued, NOK per 1 unit of foreign currency), paymentExchangeRate (number — exchange rate when payment was made), agioAccount (integer — ledger account for agio/disagio forex difference, default 8060 for agio/gain or 8160 for disagio/loss)

8. "reverse_payment" — Reverse/cancel a payment on an invoice (e.g. returned by bank, undo payment)
   Fields: customerName, customerOrgNumber, invoiceNumber (integer only), amount, paymentDate (YYYY-MM-DD), invoiceDescription, lines (array of {description, quantity, unitPriceExcludingVat, vatCode})

9. "create_credit_note" — Create a credit note for an invoice
   Fields: customerName, customerOrgNumber, invoiceNumber, comment, amount, invoiceDescription, lines (array of {description, quantity, unitPriceExcludingVat, vatCode})

10. "create_travel_expense" — Register a travel expense
    Fields: employeeName*, employeeFirstName, employeeLastName, title*, date (YYYY-MM-DD — if not explicitly stated, use today's date), destination (travel destination city/place extracted from title or context), costs (array of {description, amount, vatCode, currency})
    IMPORTANT for per diem / diet: If the prompt mentions "per diem", "diett", "dagpenger", "daily rate/allowance", "diet", "Tagegeld", "Tagessatz", "dietas", "indemnites journalieres", include the per diem as a cost with description starting with "Per diem" and include the number of days in parentheses (e.g. "Per diem (4 days)" or "Per diem (2 days)"). Calculate the total: days * daily rate. Always extract the destination city from the title.

11. "delete_travel_expense" — Delete a travel expense
    Fields: employeeName, travelExpenseTitle, travelExpenseId

12. "create_project" — Create a project (without fixed price)
    Fields: name*, customerName, customerOrgNumber, startDate (YYYY-MM-DD), endDate (YYYY-MM-DD), projectManagerName, isClosed (bool)
    ANALYTICAL MODE: If the prompt asks to first analyze the ledger/accounts and then create projects based on the results (e.g. "find the top 3 cost accounts and create one project per account"), set analyzeTopCosts=true and projectCount=N (number of projects to create). In this case, name is NOT required — the handler will derive project names from the analysis.
    Example analytical fields: {"analyzeTopCosts": true, "projectCount": 3, "isInternal": true, "period": "2026-01-01/2026-02-28"}

13. "set_project_fixed_price" — Create a NEW project linked to a customer with a FIXED PRICE amount (fastpris/prix forfaitaire/preço fixo/Festpreis/precio fijo). Optionally invoice a percentage as partial payment.
    IMPORTANT: This task type is ONLY for creating a project with a fixed budget/price. Do NOT use this type for: reminder fees (frais de rappel, purregebyr, taxa de lembrete), late payment fees, overdue invoice handling, or any task that does not explicitly mention creating a new project with a fixed price.
    Fields: projectName*, customerName*, customerOrgNumber, fixedPrice* (number — the fixed price amount in NOK), projectManagerName, startDate (YYYY-MM-DD), endDate (YYYY-MM-DD), invoicePercentage (number — if the prompt asks to invoice X% of the fixed price as partial payment, extract the percentage here, e.g. 50 for 50%)

14. "update_employee" — Update employee details
    Fields: employeeName, employeeFirstName, employeeLastName, changes (object with fields to update)

15. "update_customer" — Update customer details
    Fields: customerName, customerOrgNumber, changes (object with fields to update)

16. "create_voucher" — Create a voucher / journal entry
    Fields: description*, date (YYYY-MM-DD), postings* (array of {debitAccount, creditAccount, amount, description})

17. "reverse_voucher" — Reverse an existing voucher
    Fields: voucherNumber, date

18. "delete_voucher" — Delete a voucher
    Fields: voucherNumber, date

19. "update_supplier" — Update supplier details
    Fields: supplierName, supplierOrgNumber, organizationNumber, changes (object with fields to update)

20. "update_product" — Update product details
    Fields: productName, productNumber, number, changes (object with fields to update)

21. "delete_employee" — Delete an employee
    Fields: employeeName, employeeFirstName, employeeLastName

22. "delete_customer" — Delete a customer
    Fields: customerName, customerOrgNumber

23. "delete_supplier" — Delete a supplier
    Fields: supplierName, supplierOrgNumber

24. "create_order" — Create an order for a customer, optionally convert to invoice and register payment
    Fields: customerName*, customerOrgNumber, orderDate (YYYY-MM-DD), deliveryDate (YYYY-MM-DD), lines (array of {description, productNumber (if given in parentheses), quantity, unitPriceExcludingVat, vatCode}), convertToInvoice (bool — true if prompt asks to convert/invoice), registerPayment (bool — true if prompt asks to register payment)

25. "register_supplier_invoice" — Register a supplier invoice (innkjøpsfaktura/leverandørfaktura)
    Fields: supplierName, supplierOrgNumber, organizationNumber, amount (gross total including VAT — extract from attached receipt/PDF if present), amountExcludingVat (number — net amount excl. VAT, extract from receipt if present), description, productName (name of the product/service purchased — extract from receipt/PDF), invoiceDate (YYYY-MM-DD), invoiceNumber (the supplier's invoice reference, e.g. "INV-2026-4855"), vatRate (integer percent, e.g. 25 for 25%, default 25), vatCode (Tripletex VAT code for INPUT VAT: "11" = 25% standard input, "13" = 15% food/middels input, "14" = 12% low/transport input, "0" = no VAT — default "11" for standard purchases), expenseAccount (account number — map based on purchase type: 6010=office supplies/kontorrekvisita, 6540=IT equipment/datautstyr, 6000=office furniture/kontormøbler, 5000=materials/materialer, 7140=travel/reise, 4000=general purchases; default "6010" if office supplies, "6540" if electronics/IT, "6000" if furniture/møbler), department (department name — extract from prompt, e.g. "Drift", "IT", "Salg")
    RECEIPT/PDF EXTRACTION: If a receipt or invoice PDF/image is attached, extract ALL of the following from it: supplierName, supplierOrgNumber, amount (total inkl. MVA), amountExcludingVat (total ekskl. MVA), vatRate, invoiceDate, invoiceNumber, and productName (the main product/service). Do NOT leave amount as 0 if a receipt is attached — read it from the document.

26. "register_timesheet" — Register hours/timesheet entry for one or more employees on a project/activity, AND optionally generate a project invoice to the customer based on the registered hours (registrere timer, Stunden erfassen, registar horas, enregistrer heures, prosjektfaktura, project invoice)
    Fields: employeeName, employeeEmail, projectName, activityName, hours* (number), date (YYYY-MM-DD), comment, hourlyRate (number — NOK per hour, extract if prompt mentions timesats/hourly rate/taxa horária/taux horaire/Stundensatz), customerName (the customer to invoice), customerOrgNumber (customer org number), projectBudget (number — total project budget/NOK if mentioned), employees (array — use when MULTIPLE employees are mentioned, each with: {name (full name), email (if provided), hours (number), activityName (if specified per employee)}), supplierName (name of supplier if a supplier cost is part of the project), supplierOrgNumber, supplierAmount (NOK amount of supplier cost if mentioned), supplierExpenseAccount (account number for supplier cost, default 4000)
    IMPORTANT: If the prompt asks to BOTH register hours AND generate an invoice/project invoice, this is ONE task of type "register_timesheet" — do NOT split it into two separate tasks. Extract hourlyRate, customerName, and customerOrgNumber as fields.
    IMPORTANT for multiple employees: If the prompt mentions multiple employees with hours (e.g. "Carlos García 40 timer og Rafael García 47 timer"), use the "employees" array field with each employee's details. Each entry must have: name (full name), email (if mentioned), hours (number), activityName (if specified per employee).

27. "create_invoice_from_pdf" — Create an invoice from an attached PDF (scanned invoice)
    Fields: customerName, customerOrgNumber, invoiceDate (YYYY-MM-DD), dueDate (YYYY-MM-DD), lines (array of {description, quantity, unitPriceExcludingVat, vatCode}), totalAmount (number)

28. "run_payroll" — Run payroll / salary payment / Gehaltsabrechnung / lønnskjøring / nómina / folha de pagamento for an employee
    Fields: employeeName*, employeeEmail, baseSalary* (number in NOK), bonus (number in NOK, optional one-time bonus), month (integer 1-12, default current month), year (integer, default current year)

29. "create_custom_dimension" — Create a custom accounting dimension (dimensjon/dimension/dimensão/dimensión/Dimension) with values, then optionally post a voucher linked to a dimension value
    Fields: dimensionName* (name of the dimension, e.g. "Region", "Kostsenter"), values* (array of strings, e.g. ["Sør-Norge", "Nord-Norge"]), voucherDate (YYYY-MM-DD), voucherDescription (string), accountNumber (integer, the expense/cost account), amount (number in NOK), dimensionValue (string — which value from the values array to link to the voucher posting), creditAccount (integer, default 1920 for bank)

30. "bank_reconciliation" — Perform bank reconciliation (bankavstemming/Bankabstimmung/rapprochement bancaire/conciliación bancaria/conciliação bancária): match bank transactions to ledger postings
    Fields: accountNumber (integer, e.g. 1920 for bank account), accountId (integer, Tripletex bank account ID), dateFrom (YYYY-MM-DD), dateTo (YYYY-MM-DD), closingBalance (number — bank statement closing balance)

31. "year_end_closing" — Perform year-end closing (årsavslutning/årsoppgjør/Jahresabschluss/clôture annuelle/cierre de año/encerramento anual): close accounting periods, close postings, and create opening balance for the next year
    Fields: year* (integer, the fiscal year to close, e.g. 2025), createOpeningBalance (bool, default true — whether to create an opening balance for the next year), openingBalanceDate (YYYY-MM-DD, default first day of next year)

32. "correct_ledger_error" — Correct one or MORE errors in the ledger / bookkeeping (feilretting i regnskap / error correction / Korrekturbuchung / corrección contable / correction comptable / correção contábil / erreurs dans le grand livre): find and reverse erroneous vouchers, then post corrected vouchers
    Fields: voucherNumber (integer — the erroneous voucher number), date (YYYY-MM-DD — date of the erroneous voucher), dateFrom (YYYY-MM-DD — start of the period to search for erroneous vouchers, e.g. first day of the month/period mentioned in the prompt), dateTo (YYYY-MM-DD — end of the period to search, e.g. last day of the month/period), description (string — description to identify the erroneous voucher), correctedPostings (array of {debitAccount, creditAccount, amount} — the CORRECT postings to replace the error), correctionDescription (string — description for the correction voucher), correctionDate (YYYY-MM-DD — date for correction, defaults to original date), accountFrom (integer — the WRONG account number used in the error), accountTo (integer — the CORRECT account number), amount (number — the amount involved), creditAccount (integer — credit account for simple correction, default 1920), errors (array of error objects when MULTIPLE errors need correction — each object has: {errorType ("wrong_account" | "duplicate" | "missing_vat" | "wrong_amount"), account (integer — the account number involved), wrongAccount (integer — for wrong_account: the wrong account used), correctAccount (integer — for wrong_account: the correct account), amount (number — the amount on the erroneous posting), correctAmount (number — for wrong_amount: what it should be), vatAccount (integer — for missing_vat: the VAT account that should have been used, e.g. 2710), date (YYYY-MM-DD — specific date to search for the voucher, if known)})
    IMPORTANT: If the prompt mentions a period (e.g. "January and February 2026", "januar og februar 2026", "janvier et février 2026") but NO specific voucher date, always set top-level dateFrom and dateTo to cover that entire period (e.g. dateFrom: "2026-01-01", dateTo: "2026-02-28"). This allows the system to search for the erroneous vouchers across the full period.

33. "monthly_closing" — Perform monthly closing (månedsavslutning/Monatsabschluss/cierre mensual/clôture mensuelle/encerramento mensal): post accruals, depreciations, and provisions as vouchers
    Fields: month* (integer 1-12), year* (integer), accruals (array of {fromAccount (balance sheet account to credit, e.g. 1720), toAccount (expense account to debit, e.g. 6300), amount (number), description (string)}), depreciations (array of {account (expense account for depreciation, e.g. 6020), assetAccount (balance sheet asset account to credit, e.g. 1200), acquisitionCost (number — original cost of the asset), usefulLifeYears (number — useful life in years), description (string)}), provisions (array of {debitAccount (expense account, e.g. 5000), creditAccount (liability account, e.g. 2900), amount (number — REQUIRED, see inference rules below), description (string)} — also known as: avsetning (nb/nn), Rückstellung/Gehaltsrückstellung (de), provisión/dotación (es), provision salariale (fr), provisão salarial (pt))
    IMPORTANT — provision amount inference: provision.amount MUST always be a positive number. If the prompt does not state an explicit amount for the provision, infer it from context using these rules in priority order:
      1. If the prompt states a monthly salary/wage (e.g. "lønn 50000 kr/mnd", "Gehalt 45000 NOK/Monat", "salaire mensuel 42000"), use that value as provision.amount.
      2. If the prompt states an annual salary (e.g. "årslønn 600000"), divide by 12 and use as provision.amount.
      3. If there is an accrual (periodisering/Rechnungsabgrenzung/régularisation) with an amount, and it represents the same monthly cost category (e.g. wages/salary), use accrual.amount as provision.amount.
      4. If a tax provision percentage is given (e.g. "22% du bénéfice", "skatteprosent 22%") but no profit figure is stated, set amount to 10000 as a placeholder.
      5. If no amount can be inferred at all, set amount to 10000 as a placeholder — never use null or 0.

34. "register_expense_receipt" — Register an expense from a receipt/kvittering (utgift fra kvittering / dépense du reçu / Ausgabe aus Quittung / gasto del recibo / despesa do recibo). Creates a voucher with debit on expense account and credit on bank (1920). Apply correct input VAT (inngående mva) if applicable. Link to department if specified.
    IMPORTANT: If the prompt mentions "kvittering", "Quittung", "receipt", "reçu", "recibo", "ricevuta" — this is ALWAYS register_expense_receipt, NEVER register_supplier_invoice. A receipt (kvittering) and a supplier invoice (leverandørfaktura) are different things.
    Fields: description* (item name / what was purchased, e.g. "Skrivebordlampe", "Kontorstoler"), amount* (number — gross amount including VAT), date (YYYY-MM-DD — receipt date, default today), department (string — department name if mentioned, e.g. "Kvalitetskontroll", "Drift"), expenseAccount (integer — choose the most appropriate Norwegian expense account based on the item: 6500=kontorrekvisita/office supplies/desk lamp, 6540=kontormøbler/furniture/office chairs, 6300=leie lokaler, 7140=reise, 4000=varekjøp — default 6500), creditAccount (integer — default 1920 for bank), vatRate (integer percent — 25 for standard goods/services, 15 for food, 0 for exempt — default 25)
    IMPORTANT: Infer expenseAccount from the item name: "Skrivebordlampe" / "lampe" / "lampa" → 6500; "Kontorstoler" / "stol" / "chair" / "chaise" / "Stuhl" / "silla" → 6540; "kontorrekvisita" / "papir" / "penn" → 6500. Default to 6500 if uncertain.

35. "overdue_invoice" — Handle overdue invoice: find the overdue invoice, post a reminder fee voucher, create and send a reminder fee invoice to the customer, and optionally register a partial payment on the overdue invoice. This is a COMPOSITE task — do NOT classify as "create_voucher" if the prompt also asks to create an invoice and/or register a payment.
    IMPORTANT: If the prompt mentions "overdue", "reminder fee", "purregebyr", "frais de rappel", "taxa de lembrete", "Mahngebühr", "rappelgebühr", "forfalt faktura", "facture en retard", "fatura vencida", "überfällige Rechnung" AND also mentions creating an invoice or registering a payment, this is "overdue_invoice", NOT "create_voucher".
    Fields: reminderFeeAmount* (number — the reminder fee amount in NOK), debitAccount (integer, default 1500 — accounts receivable), creditAccount (integer, default 3400 — reminder fee income), partialPaymentAmount (number — amount of partial payment on overdue invoice, if mentioned)

36. "unknown" — ONLY if you truly cannot determine the task type from ANY of the above categories

Examples:

Prompt: "Crie uma dimensão contabilística personalizada 'Region' com os valores 'Sør-Norge' e 'Nord-Norge'. Em seguida, lance um documento na conta 7140 por 23050 NOK, vinculado ao valor de dimensão 'Sør-Norge'."
Output: {"taskType": "create_custom_dimension", "fields": {"dimensionName": "Region", "values": ["Sør-Norge", "Nord-Norge"], "voucherDate": "2026-03-20", "voucherDescription": "Voucher linked to dimension Sør-Norge", "accountNumber": 7140, "amount": 23050, "dimensionValue": "Sør-Norge"}, "confidence": 0.95, "reasoning": "Portuguese prompt to create a custom accounting dimension 'Region' with values, then post a voucher on account 7140 linked to dimension value 'Sør-Norge'."}

Prompt: "Créez une dimension comptable personnalisée 'Kostsenter' avec les valeurs 'Kundeservice' et 'Økonomi'. Puis comptabilisez un document sur le compte 6300 pour 15000 NOK, lié à la valeur 'Økonomi'."
Output: {"taskType": "create_custom_dimension", "fields": {"dimensionName": "Kostsenter", "values": ["Kundeservice", "Økonomi"], "voucherDate": "2026-03-20", "voucherDescription": "Voucher linked to dimension Økonomi", "accountNumber": 6300, "amount": 15000, "dimensionValue": "Økonomi"}, "confidence": 0.95, "reasoning": "French prompt to create custom dimension 'Kostsenter' with values and post a voucher linked to 'Økonomi'."}

Prompt: "Registre el proveedor Dorada SL con número de organización 853166553. Correo electrónico: faktura@doradasl.no."
Output: {"taskType": "create_supplier", "fields": {"name": "Dorada SL", "organizationNumber": "853166553", "email": "faktura@doradasl.no"}, "confidence": 0.95, "reasoning": "Spanish prompt requesting supplier registration with org number and email. For suppliers, email goes only in 'email' field, not invoiceEmail."}

Prompt: "Le client Océan SARL (nº org. 924390735) a une facture impayée de 39300 NOK hors TVA pour \"Maintenance\". Enregistrez le paiement intégral de cette facture."
Output: {"taskType": "register_payment", "fields": {"customerName": "Océan SARL", "customerOrgNumber": "924390735", "amount": 39300, "invoiceDescription": "Maintenance", "lines": [{"description": "Maintenance", "quantity": 1, "unitPriceExcludingVat": 39300, "vatCode": "3"}]}, "confidence": 0.92, "reasoning": "French prompt to register full payment on an unpaid invoice for Maintenance."}

Prompt: "Nous avons un nouvel employé nommé Sarah Richard, né le 15. August 1980. Veuillez le créer en tant qu'employé avec l'e-mail sarah.richard@example.org et la date de début 29. June 2026."
Output: {"taskType": "create_employee", "fields": {"firstName": "Sarah", "lastName": "Richard", "dateOfBirth": "1980-08-15", "email": "sarah.richard@example.org", "startDate": "2026-06-29"}, "confidence": 0.95, "reasoning": "French prompt to create employee with name, DOB, email, and start date."}

Prompt: "Erstellen Sie das Produkt \"Orangensaft\" mit der Produktnummer 1256. Der Preis beträgt 17450 NOK ohne MwSt., mit dem MwSt.-Satz für Lebensmittel von 15 %."
Output: {"taskType": "create_product", "fields": {"name": "Orangensaft", "number": "1256", "priceExcludingVat": 17450, "vatCode": "31"}, "confidence": 0.95, "reasoning": "German prompt to create a food product with 15% VAT (code 31)."}

Prompt: "O cliente Floresta Lda (org. nº 916058896) tem uma fatura pendente de 30450 NOK sem IVA por \"Desenvolvimento de sistemas\". Registe o pagamento total desta fatura."
Output: {"taskType": "register_payment", "fields": {"customerName": "Floresta Lda", "customerOrgNumber": "916058896", "amount": 30450, "invoiceDescription": "Desenvolvimento de sistemas", "lines": [{"description": "Desenvolvimento de sistemas", "quantity": 1, "unitPriceExcludingVat": 30450, "vatCode": "3"}]}, "confidence": 0.93, "reasoning": "Portuguese prompt to register full payment on a pending invoice."}

Prompt: "Registe 4 horas para Maria Ferreira (maria.ferreira@example.org) na atividade \"Utvikling\" do projeto \"App-utvikling\" para hoje."
Output: {"taskType": "register_timesheet", "fields": {"employeeName": "Maria Ferreira", "employeeEmail": "maria.ferreira@example.org", "activityName": "Utvikling", "projectName": "App-utvikling", "hours": 4}, "confidence": 0.94, "reasoning": "Portuguese prompt to register 4 timesheet hours for an employee on a project activity."}

Prompt: "Registrer 24 timer for Solveig Hansen (solveig.hansen@example.org) på aktiviteten \"Analyse\" i prosjektet \"Apputvikling\" for Tindra AS (org.nr 945097523). Timesats: 1850 kr/t. Generer en prosjektfaktura til kunden basert på de registrerte timene."
Output: {"taskType": "register_timesheet", "fields": {"employeeName": "Solveig Hansen", "employeeEmail": "solveig.hansen@example.org", "activityName": "Analyse", "projectName": "Apputvikling", "hours": 24, "hourlyRate": 1850, "customerName": "Tindra AS", "customerOrgNumber": "945097523"}, "confidence": 0.95, "reasoning": "Norwegian prompt to register 24 hours and generate a project invoice to Tindra AS based on the registered hours at 1850 NOK/h."}

Prompt: "Create three departments in Tripletex: \"Utvikling\", \"Lager\", and \"Regnskap\"."
Output: [{"taskType": "create_department", "fields": {"name": "Utvikling"}, "confidence": 0.95, "reasoning": "Batch: department 1 of 3."}, {"taskType": "create_department", "fields": {"name": "Lager"}, "confidence": 0.95, "reasoning": "Batch: department 2 of 3."}, {"taskType": "create_department", "fields": {"name": "Regnskap"}, "confidence": 0.95, "reasoning": "Batch: department 3 of 3."}]

Prompt: "Kunden Vestfjord AS (org.nr 860678403) har reklamert på fakturaen for \"Skylagring\" (45350 kr ekskl. MVA). Opprett ei fullstendig kreditnota som reverserer heile fakturaen."
Output: {"taskType": "create_credit_note", "fields": {"customerName": "Vestfjord AS", "customerOrgNumber": "860678403", "invoiceDescription": "Skylagring", "amount": 45350, "lines": [{"description": "Skylagring", "quantity": 1, "unitPriceExcludingVat": 45350, "vatCode": "3"}]}, "confidence": 0.94, "reasoning": "Norwegian Nynorsk prompt to create a full credit note reversing an invoice."}

Prompt: "Führen Sie die Gehaltsabrechnung für Laura Schneider (laura.schneider@example.org) für diesen Monat durch. Das Grundgehalt beträgt 33000 NOK. Fügen Sie einen einmaligen Bonus von 17850 NOK zum Grundgehalt hinzu."
Output: {"taskType": "run_payroll", "fields": {"employeeName": "Laura Schneider", "employeeEmail": "laura.schneider@example.org", "baseSalary": 33000, "bonus": 17850}, "confidence": 0.95, "reasoning": "German prompt to run payroll with base salary and one-time bonus."}

Prompt: "Run payroll for William Taylor (william.taylor@example.org) for this month. The base salary is 39400 NOK. Add a one-time bonus of 11800 NOK on top of the base salary."
Output: {"taskType": "run_payroll", "fields": {"employeeName": "William Taylor", "employeeEmail": "william.taylor@example.org", "baseSalary": 39400, "bonus": 11800}, "confidence": 0.95, "reasoning": "English prompt to run payroll with base salary and bonus."}

Prompt: "Me sende ein faktura på 8387 EUR til Dalheim AS (org.nr 847589930) då kursen var 11.99 NOK/EUR. Kunden har no betalt, men kursen er 12.84 NOK/EUR. Registrer betalinga og bokfør valutadifferansen (agio) på rett konto."
Output: {"taskType": "register_payment", "fields": {"customerName": "Dalheim AS", "customerOrgNumber": "847589930", "foreignCurrency": "EUR", "foreignAmount": 8387, "invoiceExchangeRate": 11.99, "paymentExchangeRate": 12.84, "agioAccount": 8060}, "confidence": 0.95, "reasoning": "Norwegian Nynorsk prompt to register payment on EUR invoice with currency gain (agio). Invoice was 8387 EUR at rate 11.99, payment received at rate 12.84 — difference is agio (valutagevinst) booked to account 8060."}

Prompt: "Ejecute el ciclo de vida completo del proyecto 'Actualización Sistema' (Dorada SL, org. nº 888398554): 1) Proyecto con presupuesto de 460950 NOK. 2) Registre horas: Carlos García (carlos.garcia@example.org) 40 horas y Rafael García (rafael.garcia@example.org) 47 horas. 3) Registre costo de proveedor de 41650 NOK de Estrella SL (org. nº 913385853). 4) Cree una factura al cliente."
Output: {"taskType": "register_timesheet", "fields": {"projectName": "Actualización Sistema", "customerName": "Dorada SL", "customerOrgNumber": "888398554", "projectBudget": 460950, "employees": [{"name": "Carlos García", "email": "carlos.garcia@example.org", "hours": 40}, {"name": "Rafael García", "email": "rafael.garcia@example.org", "hours": 47}], "supplierName": "Estrella SL", "supplierOrgNumber": "913385853", "supplierAmount": 41650, "supplierExpenseAccount": 4000}, "confidence": 0.94, "reasoning": "Spanish project lifecycle prompt with multiple employees registering hours, supplier cost, and project invoice to customer."}

Prompt: "Du har motteke ein leverandorfaktura (sjaa vedlagt PDF). Registrer fakturaen i Tripletex. Opprett leverandoren viss den ikkje finst. Bruk rett utgiftskonto og inngaaande MVA."
Output: {"taskType": "register_supplier_invoice", "fields": {"description": "Leverandørfaktura fra vedlagt PDF", "expenseAccount": 4000, "vatRate": 25, "vatCode": "11"}, "confidence": 0.90, "reasoning": "Norwegian Nynorsk prompt to register a supplier invoice from PDF. Extract all amounts, supplier info and product name from the attached PDF. leverandorfaktura (Nynorsk) = leverandørfaktura (Bokmål)."}

Prompt: "Vi treng Kontorstoler fra denne kvitteringa bokfort pa avdeling Drift. Bruk rett utgiftskonto basert pa kjopet, og sorg for korrekt MVA-behandling."
Output: {"taskType": "register_expense_receipt", "fields": {"description": "Kontorstoler", "department": "Drift", "expenseAccount": 6540, "vatRate": 25}, "confidence": 0.95, "reasoning": "Nynorsk prompt with 'kvitteringa' (receipt) → register_expense_receipt, NOT register_supplier_invoice. Key signal: 'kvittering/Quittung/receipt/reçu/recibo' always means expense receipt. Kontorstoler = office furniture → account 6540. Department Drift specified."}

Prompt: "Totalkostnadene økte betydelig fra januar til februar 2026. Analyser hovedboken og finn de tre kostnadskontoene med størst økning i beløp. Opprett et internt prosjekt for hver av de tre kontoene med kontoens namn. Opprett også en aktivitet for hvert prosjekt."
Output: {"taskType": "create_project", "fields": {"analyzeTopCosts": true, "projectCount": 3, "isInternal": true, "period": "2026-01-01/2026-02-28", "createActivity": true}, "confidence": 0.88, "reasoning": "Norwegian prompt to analyze the ledger and create one internal project per top-3 cost account. Project names are not static — the handler will derive them from the analysis. analyzeTopCosts=true triggers the analytical workflow."}

Prompt: "Totalkostnadene auka monaleg frå januar til februar 2026. Analyser hovudboka og finn dei tre kostnadskontoane med størst auke i beløp. Opprett eit internt prosjekt for kvar av dei tre kontoane med kontoens namn. Opprett også ein aktivitet for kvart prosjekt."
Output: {"taskType": "create_project", "fields": {"analyzeTopCosts": true, "projectCount": 3, "isInternal": true, "period": "2026-01-01/2026-02-28", "createActivity": true}, "confidence": 0.88, "reasoning": "Norwegian Nynorsk prompt identical in meaning to the Bokmål version above — analyze ledger, find top-3 cost accounts, create internal projects with activities."}

Prompt: "One of your customers has an overdue invoice. Find the overdue invoice and post a reminder fee of 35 NOK. Debit accounts receivable (1500), credit reminder fees (3400). Also create an invoice for the reminder fee to the customer and send it. Additionally, register a partial payment of 5000 NOK on the overdue invoice."
Output: {"taskType": "overdue_invoice", "fields": {"reminderFeeAmount": 35, "debitAccount": 1500, "creditAccount": 3400, "partialPaymentAmount": 5000}, "confidence": 0.96, "reasoning": "English prompt about an overdue invoice with MULTIPLE actions: find overdue, post reminder fee voucher, create+send reminder invoice, register partial payment. This is 'overdue_invoice' (composite), NOT 'create_voucher'."}

Prompt: "L'un de vos clients a une facture en retard. Trouvez la facture en retard et enregistrez des frais de rappel de 50 NOK. Debit creances clients (1500), credit revenus de rappel (3400). Créez également une facture pour les frais de rappel au client et envoyez-la. De plus, enregistrez un paiement partiel de 5000 NOK sur la facture en retard."
Output: {"taskType": "overdue_invoice", "fields": {"reminderFeeAmount": 50, "debitAccount": 1500, "creditAccount": 3400, "partialPaymentAmount": 5000}, "confidence": 0.95, "reasoning": "French prompt about an overdue invoice (facture en retard) with MULTIPLE actions: post reminder fee voucher, create invoice for the fee, send it, AND register partial payment. This is 'overdue_invoice' (composite task), NOT 'create_voucher' (which only handles journal entries)."}

Prompt: "Um dos seus clientes tem uma fatura vencida. Encontre a fatura vencida e registe uma taxa de lembrete de 70 NOK. Débito contas a receber (1500), crédito receitas de lembrete (3400). Também crie uma fatura para a taxa de lembrete ao cliente."
Output: {"taskType": "overdue_invoice", "fields": {"reminderFeeAmount": 70, "debitAccount": 1500, "creditAccount": 3400}, "confidence": 0.93, "reasoning": "Portuguese prompt about an overdue invoice (fatura vencida) with MULTIPLE actions: post reminder fee voucher AND create invoice for the fee. This is 'overdue_invoice' (composite), NOT 'create_voucher'. No partial payment mentioned in this variant."}

Prompt: "Sett fastpris 430750 kr på prosjektet 'Automatisering' for Havbris AS (org.nr 967636665). Prosjektleder er Kari Olsen."
Output: {"taskType": "set_project_fixed_price", "fields": {"projectName": "Automatisering", "customerName": "Havbris AS", "customerOrgNumber": "967636665", "fixedPrice": 430750, "projectManagerName": "Kari Olsen"}, "confidence": 0.96, "reasoning": "Norwegian prompt to create a project with a fixed price for a customer."}

Prompt: "Defina um preço fixo de 114250 NOK no projeto 'Implementação ERP' para Luz do Sol Lda (org. nº 898537447)."
Output: {"taskType": "set_project_fixed_price", "fields": {"projectName": "Implementação ERP", "customerName": "Luz do Sol Lda", "customerOrgNumber": "898537447", "fixedPrice": 114250}, "confidence": 0.95, "reasoning": "Portuguese prompt to set a fixed price on a project for a customer."}

Prompt: "Sett fastpris 430750 kr på prosjektet 'Automatiseringsprosjekt' for Fossekraft AS (org.nr 907433498). Prosjektleiar er Solveig Eide. Fakturer kunden for 50 % av fastprisen som ei delbetaling."
Output: {"taskType": "set_project_fixed_price", "fields": {"projectName": "Automatiseringsprosjekt", "customerName": "Fossekraft AS", "customerOrgNumber": "907433498", "fixedPrice": 430750, "projectManagerName": "Solveig Eide", "invoicePercentage": 50}, "confidence": 0.96, "reasoning": "Norwegian Nynorsk prompt to create a fixed-price project and invoice 50% as partial payment."}

Prompt: "Establezca un precio fijo de 152400 NOK en el proyecto 'Mejora de infraestructura' para Estrella SL. Facture al cliente el 75 % del precio fijo como pago parcial."
Output: {"taskType": "set_project_fixed_price", "fields": {"projectName": "Mejora de infraestructura", "customerName": "Estrella SL", "fixedPrice": 152400, "invoicePercentage": 75}, "confidence": 0.95, "reasoning": "Spanish prompt to set fixed price on project and invoice 75% as partial payment."}

Prompt: "Gjennomfør månedsavslutningen for mars 2026. 1) Registrer opptjeningen (12500 kr/mnd fra konto 1720 til utgift). 2) Konter månedlig avskrivning av anleggsmiddel med anskaffelseskost 61400 NOK, levetid 10 år (lineær til konto 6020). 3) Registrer lønnsavsetning (debet 5000, kredit 2900, beløp 35000)."
Output: {"taskType": "monthly_closing", "fields": {"month": 3, "year": 2026, "accruals": [{"fromAccount": 1720, "toAccount": 6300, "amount": 12500, "description": "Periodisering mars 2026"}], "depreciations": [{"account": 6020, "assetAccount": 1200, "acquisitionCost": 61400, "usefulLifeYears": 10, "description": "Avskrivning anleggsmiddel mars 2026"}], "provisions": [{"debitAccount": 5000, "creditAccount": 2900, "amount": 35000, "description": "Lønnsavsetning mars 2026"}]}, "confidence": 0.95, "reasoning": "Norwegian prompt for monthly closing with accrual, depreciation, and salary provision."}

Prompt: "Realizar o encerramento mensal para março de 2026. 1) Registrar a periodização (8500 kr/mês da conta 1720 para despesa 6300). 2) Registrar provisão salarial (débito 5000, crédito 2900, valor 42000)."
Output: {"taskType": "monthly_closing", "fields": {"month": 3, "year": 2026, "accruals": [{"fromAccount": 1720, "toAccount": 6300, "amount": 8500, "description": "Periodização março 2026"}], "depreciations": [], "provisions": [{"debitAccount": 5000, "creditAccount": 2900, "amount": 42000, "description": "Provisão salarial março 2026"}]}, "confidence": 0.95, "reasoning": "Portuguese monthly closing with accrual and salary provision (provisão salarial)."}

Prompt: "Führen Sie den Monatsabschluss für März 2026 durch. Buchen Sie eine Gehaltsrückstellung: Soll 5000, Haben 2900, Betrag 38000 NOK."
Output: {"taskType": "monthly_closing", "fields": {"month": 3, "year": 2026, "accruals": [], "depreciations": [], "provisions": [{"debitAccount": 5000, "creditAccount": 2900, "amount": 38000, "description": "Gehaltsrückstellung März 2026"}]}, "confidence": 0.95, "reasoning": "German monthly closing with salary provision (Gehaltsrückstellung)."}

Prompt: "Führen Sie den Monatsabschluss für März 2026 durch. Buchen Sie die Rechnungsabgrenzung (3400 NOK pro Monat von Konto 1700 auf Aufwand). Erfassen Sie die monatliche Abschreibung für eine Anlage mit Anschaffungskosten 289700 NOK und Nutzungsdauer 7 Jahre (lineare Abschreibung auf Konto 6020). Überprüfen Sie, ob die Saldenbilanz null ergibt. Buchen Sie außerdem eine Gehaltsrückstellung (Soll Gehaltsaufwand Konto 5000, Haben aufgelaufene Gehälter Konto 2900)."
Output: {"taskType": "monthly_closing", "fields": {"month": 3, "year": 2026, "accruals": [{"fromAccount": 1700, "toAccount": 6300, "amount": 3400, "description": "Rechnungsabgrenzung März 2026"}], "depreciations": [{"account": 6020, "assetAccount": 1200, "acquisitionCost": 289700, "usefulLifeYears": 7, "description": "Abschreibung Anlage März 2026"}], "provisions": [{"debitAccount": 5000, "creditAccount": 2900, "amount": 3400, "description": "Gehaltsrückstellung März 2026"}]}, "confidence": 0.93, "reasoning": "German monthly closing. No explicit provision amount stated — inferred from accrual amount (3400 NOK/month) as the same monthly cost category."}

Prompt: "Effectuez la clôture mensuelle de mars 2026. Comptabilisez la régularisation (13600 NOK par mois du compte 1700 vers charges). Enregistrez l'amortissement mensuel d'une immobilisation avec un coût d'acquisition de 262850 NOK et une durée de vie utile de 10 ans (amortissement linéaire sur compte 6030). Comptabilisez également une provision pour salaires (débit compte de charges salariales 5000, crédit compte de salaires à payer 2900)."
Output: {"taskType": "monthly_closing", "fields": {"month": 3, "year": 2026, "accruals": [{"fromAccount": 1700, "toAccount": 6300, "amount": 13600, "description": "Régularisation charges mars 2026"}], "depreciations": [{"account": 6030, "assetAccount": 1200, "acquisitionCost": 262850, "usefulLifeYears": 10, "description": "Amortissement immobilisation mars 2026"}], "provisions": [{"debitAccount": 5000, "creditAccount": 2900, "amount": 13600, "description": "Provision pour salaires mars 2026"}]}, "confidence": 0.93, "reasoning": "French monthly closing. No explicit provision amount — inferred from accrual amount (13600 NOK/month) as proxy for monthly salary cost."}

Prompt: "Nous avons besoin de la depense Skrivebordlampe de ce recu enregistree au departement Kvalitetskontroll. Utilisez le bon compte de charges et assurez le traitement correct de la TVA."
Output: {"taskType": "register_expense_receipt", "fields": {"description": "Skrivebordlampe", "department": "Kvalitetskontroll", "expenseAccount": 6500, "vatRate": 25}, "confidence": 0.94, "reasoning": "French prompt to register a desk lamp expense from a receipt in the Kvalitetskontroll department. Skrivebordlampe is office equipment → account 6500 (kontorrekvisita). Standard 25% input VAT applies."}

Prompt: "Vi treng Kontorstoler fra denne kvitteringa bokfort pa avdeling Drift. Bruk rett utgiftskonto basert pa kjopet, og sorg for korrekt MVA-behandling."
Output: {"taskType": "register_expense_receipt", "fields": {"description": "Kontorstoler", "department": "Drift", "expenseAccount": 6540, "vatRate": 25}, "confidence": 0.95, "reasoning": "Norwegian Nynorsk prompt to register office chairs (Kontorstoler) from a receipt for the Drift department. Furniture/chairs → account 6540 (kontormøbler). Standard 25% input VAT applies."}

Prompt: "Die Gesamtkosten sind von Januar bis Februar 2026 deutlich gestiegen. Analysieren Sie das Hauptbuch und identifizieren Sie die drei Aufwandskonten mit dem größten Anstieg. Erstellen Sie für jedes der drei Konten ein internes Projekt mit dem Kontonamen. Erstellen Sie außerdem eine Aktivität für jedes Projekt."
Output: {"taskType": "create_project", "fields": {"analyzeTopCosts": true, "projectCount": 3, "isInternal": true, "period": "2026-01-01/2026-02-28", "createActivity": true}, "confidence": 0.88, "reasoning": "German prompt to analyze the Hauptbuch (general ledger) and identify the 3 Aufwandskonten (expense accounts) with the largest cost increase, then create an internal project per account with an activity. This is NOT correct_ledger_error — there are no errors to correct. The primary action is create_project based on ledger analysis."}

Prompt: "Nous avons découvert des erreurs dans le grand livre de janvier et février 2026. Vérifiez toutes les pièces et trouvez les 4 erreurs : une écriture sur le mauvais compte (compte 6500 utilisé au lieu de 6540, montant 6800 NOK), une pièce en double (compte 7000, montant 1300 NOK), une ligne de TVA manquante (compte 4300, montant HT 17300 NOK, TVA manquante sur compte 2710), et un montant incorrect (compte 6300, 10150 NOK comptabilisé au lieu de 7450 NOK). Corrigez toutes les erreurs avec des écritures correctives."
Output: {"taskType": "correct_ledger_error", "fields": {"dateFrom": "2026-01-01", "dateTo": "2026-02-28", "errors": [{"errorType": "wrong_account", "wrongAccount": 6500, "correctAccount": 6540, "amount": 6800}, {"errorType": "duplicate", "account": 7000, "amount": 1300}, {"errorType": "missing_vat", "account": 4300, "amount": 17300, "vatAccount": 2710}, {"errorType": "wrong_amount", "account": 6300, "amount": 10150, "correctAmount": 7450}]}, "confidence": 0.93, "reasoning": "French prompt identifying 4 accounting errors in the grand livre (general ledger) for January and February 2026: wrong account (6500→6540), duplicate entry (7000), missing VAT (4300/2710), wrong amount (6300). dateFrom/dateTo set to cover the full period so vouchers can be found by date range."}

Prompt: "We have discovered errors in the general ledger for January and February 2026. Review all vouchers and find the 4 errors: a posting to the wrong account (account 6540 used instead of 6860, amount 4800 NOK), a duplicate voucher (account 6500, amount 1050 NOK), a missing VAT line (account 7000, amount excl. 6750 NOK missing VAT on account 2710), and an incorrect amount (account 6500, 15700 NOK posted instead of 8100 NOK). Correct all errors with appropriate correction vouchers."
Output: {"taskType": "correct_ledger_error", "fields": {"dateFrom": "2026-01-01", "dateTo": "2026-02-28", "errors": [{"errorType": "wrong_account", "wrongAccount": 6540, "correctAccount": 6860, "amount": 4800}, {"errorType": "duplicate", "account": 6500, "amount": 1050}, {"errorType": "missing_vat", "account": 7000, "amount": 6750, "vatAccount": 2710}, {"errorType": "wrong_amount", "account": 6500, "amount": 15700, "correctAmount": 8100}]}, "confidence": 0.93, "reasoning": "English prompt with 4 ledger errors for January and February 2026: wrong account (6540→6860), duplicate entry (6500), missing VAT (7000/2710), wrong amount (6500). dateFrom/dateTo set to cover the full 2-month period so vouchers can be found by date range."}

Prompt: "Opprett kunden Bølgekraft AS med organisasjonsnummer 988957747. Adressa er Kirkegata 23, 0182 Oslo. E-post: post@blgekraft.no."
Output: {"taskType": "create_customer", "fields": {"name": "Bølgekraft AS", "organizationNumber": "988957747", "email": "post@blgekraft.no", "invoiceEmail": "post@blgekraft.no", "address": {"addressLine1": "Kirkegata 23", "postalCode": "0182", "city": "Oslo"}}, "confidence": 0.98, "reasoning": "Norwegian Nynorsk prompt to create a customer with org number, address, and email. For customers, email goes in both email and invoiceEmail."}

Prompt: "Create the customer Oakwood Ltd with organization number 980094863. The address is Torggata 10, 6003 Ålesund. Email: post@oakwood.no."
Output: {"taskType": "create_customer", "fields": {"name": "Oakwood Ltd", "organizationNumber": "980094863", "email": "post@oakwood.no", "invoiceEmail": "post@oakwood.no", "address": {"addressLine1": "Torggata 10", "postalCode": "6003", "city": "Ålesund"}}, "confidence": 0.95, "reasoning": "English prompt to create customer with address and email. Email goes in both email and invoiceEmail for customers."}

Prompt: "We have a new employee named Henry Smith, born 2. December 1988. Please create them as an employee with email henry.smith@example.org and start date 1. November 2026."
Output: {"taskType": "create_employee", "fields": {"firstName": "Henry", "lastName": "Smith", "email": "henry.smith@example.org", "dateOfBirth": "1988-12-02", "startDate": "2026-11-01"}, "confidence": 0.98, "reasoning": "English prompt to create employee with name, date of birth, email, and start date."}

Prompt: "Create and send an invoice to the customer Blueshore Ltd (org no. 987928921) for 40600 NOK excluding VAT. The invoice is for Maintenance."
Output: {"taskType": "create_invoice", "fields": {"customerName": "Blueshore Ltd", "customerOrgNumber": "987928921", "lines": [{"description": "Maintenance", "quantity": 1, "unitPriceExcludingVat": 40600, "vatCode": "3"}]}, "confidence": 0.95, "reasoning": "English prompt to create and send an invoice for Maintenance services. Standard 25% VAT (code 3)."}

Prompt: "Create an order for the customer Greenfield Ltd (org no. 914083478) with the products Web Design (8474) at 23450 NOK and Software License (3064) at 7800 NOK. Convert the order to an invoice and register full payment."
Output: {"taskType": "create_order", "fields": {"customerName": "Greenfield Ltd", "customerOrgNumber": "914083478", "lines": [{"description": "Web Design", "productNumber": "8474", "quantity": 1, "unitPriceExcludingVat": 23450, "vatCode": "3"}, {"description": "Software License", "productNumber": "3064", "quantity": 1, "unitPriceExcludingVat": 7800, "vatCode": "3"}], "convertToInvoice": true, "registerPayment": true}, "confidence": 0.95, "reasoning": "English prompt to create an order with two products (product numbers in parentheses), then convert to invoice and register full payment."}

Prompt: "Registrer leverandøren Vestfjord AS med organisasjonsnummer 914908787. E-post: faktura@vestfjord.no."
Output: {"taskType": "create_supplier", "fields": {"name": "Vestfjord AS", "organizationNumber": "914908787", "email": "faktura@vestfjord.no"}, "confidence": 0.98, "reasoning": "Norwegian prompt to register a supplier with org number and email. For suppliers, email goes ONLY in the 'email' field, not invoiceEmail."}

Prompt: "The customer Greenfield Ltd (org no. 853801941) has an outstanding invoice for 34450 NOK excluding VAT for \"Consulting Hours\". Register full payment on this invoice."
Output: {"taskType": "register_payment", "fields": {"customerName": "Greenfield Ltd", "customerOrgNumber": "853801941", "amount": 34450, "invoiceDescription": "Consulting Hours", "lines": [{"description": "Consulting Hours", "quantity": 1, "unitPriceExcludingVat": 34450, "vatCode": "3"}]}, "confidence": 0.95, "reasoning": "English prompt to register full payment on an outstanding invoice for Consulting Hours."}

Prompt: "We have received invoice INV-2026-3205 from the supplier Ironbridge Ltd (org no. 828254375) for 24500 NOK including VAT. The amount relates to office services (account 6590). Register the supplier invoice with the correct input VAT (25%)."
Output: {"taskType": "register_supplier_invoice", "fields": {"supplierName": "Ironbridge Ltd", "supplierOrgNumber": "828254375", "amount": 24500, "description": "office services", "invoiceNumber": "INV-2026-3205", "expenseAccount": 6590, "vatRate": 25, "vatCode": "11"}, "confidence": 0.95, "reasoning": "English prompt to register a supplier invoice with invoice number, amount including VAT, and expense account 6590 for office services. Standard input VAT 25% (code 11)."}

Prompt: "Log 5 hours for Emily Johnson (emily.johnson@example.org) on the activity \"Utvikling\" in the project \"Security Audit\" for Clearwater Ltd (org no. 874828955). Hourly rate: 1600 NOK/h. Generate a project invoice to the customer based on the logged hours."
Output: {"taskType": "register_timesheet", "fields": {"employeeName": "Emily Johnson", "employeeEmail": "emily.johnson@example.org", "activityName": "Utvikling", "projectName": "Security Audit", "hours": 5, "hourlyRate": 1600, "customerName": "Clearwater Ltd", "customerOrgNumber": "874828955"}, "confidence": 0.95, "reasoning": "English prompt to register 5 timesheet hours and generate a project invoice. Both timesheet and invoice are handled as one register_timesheet task."}

Prompt: "Die Zahlung von Grünfeld GmbH (Org.-Nr. 808603152) für die Rechnung \"Netzwerkdienst\" (44300 NOK ohne MwSt.) wurde von der Bank zurückgebucht. Stornieren Sie die Zahlung, damit die Rechnung wieder den offenen Betrag anzeigt."
Output: {"taskType": "reverse_payment", "fields": {"customerName": "Grünfeld GmbH", "customerOrgNumber": "808603152", "amount": 44300, "invoiceDescription": "Netzwerkdienst", "lines": [{"description": "Netzwerkdienst", "quantity": 1, "unitPriceExcludingVat": 44300, "vatCode": "3"}]}, "confidence": 0.94, "reasoning": "German prompt to reverse a payment that was returned by the bank. 'zurückgebucht' = payment reversal/reverse_payment."}

Prompt: "Run payroll for Charles Taylor (charles.taylor@example.org) for this month. The base salary is 36450 NOK. Add a one-time bonus of 10300 NOK on top of the base salary."
Output: {"taskType": "run_payroll", "fields": {"employeeName": "Charles Taylor", "employeeEmail": "charles.taylor@example.org", "baseSalary": 36450, "bonus": 10300}, "confidence": 0.95, "reasoning": "English prompt to run payroll with base salary and one-time bonus."}

Prompt: "Set a fixed price of 498050 NOK on the project \"CRM Integration\" for Ridgepoint Ltd (org no. 844419856). The project manager is George Walker (george.walker@example.org). Invoice the customer for 50% of the fixed price as a milestone payment."
Output: {"taskType": "set_project_fixed_price", "fields": {"projectName": "CRM Integration", "customerName": "Ridgepoint Ltd", "customerOrgNumber": "844419856", "fixedPrice": 498050, "projectManagerName": "George Walker", "invoicePercentage": 50}, "confidence": 0.98, "reasoning": "English prompt to create a fixed-price project and invoice 50% as a milestone payment."}

Prompt: "Create the project \"Integration Northwave\" linked to the customer Northwave Ltd (org no. 950072652). The project manager is James Johnson (james.johnson@example.org)."
Output: {"taskType": "create_project", "fields": {"name": "Integration Northwave", "customerName": "Northwave Ltd", "customerOrgNumber": "950072652", "projectManagerName": "James Johnson"}, "confidence": 0.95, "reasoning": "English prompt to create a project linked to a customer with a project manager."}

Prompt: "Reconcile the bank statement (attached CSV) against open invoices in Tripletex. Match incoming payments to customer invoices and outgoing payments to supplier invoices. Handle partial payments correctly."
Output: {"taskType": "bank_reconciliation", "fields": {"accountNumber": 1920, "dateFrom": "2026-01-16", "dateTo": "2026-02-02"}, "confidence": 0.95, "reasoning": "English prompt for bank reconciliation: match bank statement transactions (CSV) against open customer and supplier invoices in Tripletex. Default bank account 1920."}

Prompt: "Register a travel expense for Charles Harris (charles.harris@example.org) for \"Client visit Oslo\". The trip lasted 5 days with per diem (daily rate 800 NOK). Expenses: flight ticket 2300 NOK and taxi 500 NOK."
Output: {"taskType": "create_travel_expense", "fields": {"employeeName": "Charles Harris", "employeeFirstName": "Charles", "employeeLastName": "Harris", "title": "Client visit Oslo", "destination": "Oslo", "costs": [{"description": "Per diem (5 days)", "amount": 4000, "vatCode": "5"}, {"description": "Flight ticket", "amount": 2300, "vatCode": "5"}, {"description": "Taxi", "amount": 500, "vatCode": "5"}]}, "confidence": 0.94, "reasoning": "English travel expense with 5-day per diem (5 × 800 = 4000 NOK), flight, and taxi. Destination Oslo extracted from title."}

IMPORTANT:
- Extract ALL fields mentioned in the prompt
- Organization numbers should be strings (preserve leading zeros)
- Amounts should be numbers (not strings)
- Dates should be YYYY-MM-DD format
- For names in prompts, map to the correct field (e.g. "fornavn" → firstName, "etternavn" → lastName, "Nom" → name)
- If the prompt mentions both a customer and a product/service for an invoice, include them

Output format:
{
  "taskType": "create_supplier",
  "fields": {"name": "...", "organizationNumber": "..."},
  "confidence": 0.95,
  "reasoning": "Brief explanation"
}"""


def _build_user_content(prompt: str, files: list[dict[str, Any]]) -> list[dict]:
    """Build the user message content array with text + file blocks."""
    content: list[dict] = [{"type": "text", "text": prompt}]
    if files:
        content.extend(process_files(files))
    return content


def _parse_json_response(raw: str) -> dict:
    """Extract JSON from LLM response, stripping markdown fences if present."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    return json.loads(text)


def parse_task(prompt: str, files: list[dict[str, Any]] | None = None) -> ParsedTask:
    """Parse a task prompt into a structured ParsedTask.

    Backend selection via PARSER_BACKEND env var:
      - "haiku"  (default) — Anthropic Haiku + Sonnet fallback
      - "gemini" — Vertex AI Gemini 2.0 Flash
      - "embedding" — embedding classification (stub, falls back to haiku)
      - "auto" — embedding first, then Gemini, then Haiku as fallback
    """
    backend = PARSER_BACKEND.lower()
    logger.info(f"parse_task called with backend={backend}")
    gemini_result = None  # Track Gemini result for auto-mode fallback

    if backend == "gemini":
        from app.parser_gemini import parse_task_gemini
        return parse_task_gemini(prompt, files)

    if backend == "auto":
        # Try embedding first
        try:
            from app.embeddings import classify_prompt
            emb_type, emb_conf = classify_prompt(prompt)
            if emb_type and emb_type != "unknown" and emb_conf > 0.90:
                logger.info(f"[auto] Embedding resolved: {emb_type} (conf={emb_conf:.4f}), using Gemini for fields")
                # Add few-shot examples to prompt for better field extraction
                augmented_prompt = prompt
                try:
                    from app.embeddings import get_similar_examples
                    examples = get_similar_examples(prompt, emb_type, top_k=3)
                    if examples:
                        few_shot_parts = []
                        for i, ex in enumerate(examples, 1):
                            fields_json = json.dumps(ex["fields"], ensure_ascii=False)
                            few_shot_parts.append(
                                f"Eksempel {i}:\nPrompt: {ex['prompt']}\nFelter: {fields_json}"
                            )
                        augmented_prompt = (
                            f'This task is of type "{emb_type}". Extract the fields.\n\n'
                            f"Her er lignende oppgaver og korrekte felt:\n\n"
                            + "\n\n".join(few_shot_parts)
                            + f"\n\nOriginal prompt: {prompt}"
                        )
                        logger.info(f"[auto] Added {len(examples)} few-shot examples for {emb_type}")
                except Exception as e:
                    logger.warning(f"[auto] Few-shot retrieval failed: {e}")
                from app.parser_gemini import parse_task_gemini
                result = parse_task_gemini(augmented_prompt, files)
                if result.task_type != "unknown":
                    return result
        except Exception as e:
            logger.warning(f"[auto] Embedding step failed: {e}")

        # Then try Gemini standalone
        try:
            from app.parser_gemini import parse_task_gemini
            result = parse_task_gemini(prompt, files)
            if result.task_type != "unknown" and result.confidence >= 0.85:
                logger.info(f"[auto] Gemini resolved: {result.task_type} (conf={result.confidence})")
                return result
            # Accept lower-confidence Gemini results if task_type is valid
            if result.task_type != "unknown" and result.task_type in VALID_TASK_TYPES:
                logger.info(f"[auto] Gemini resolved (low conf): {result.task_type} (conf={result.confidence})")
                gemini_result = result  # Save for potential use if Haiku also fails
            else:
                gemini_result = None
        except Exception as e:
            logger.warning(f"[auto] Gemini step failed: {e}")
            gemini_result = None

        # Fall through to Haiku below
        logger.info("[auto] Falling back to Haiku")

    # backend == "haiku" or "embedding" or auto-fallback
    logger.info(f"Parsing task: {prompt[:200]}")

    # --- Step 1: Embedding-based pre-classification ---
    embedding_type: str | None = None
    embedding_confidence: float = 0.0
    try:
        from app.embeddings import classify_prompt
        embedding_type, embedding_confidence = classify_prompt(prompt)
        logger.info(f"Embedding classification: type={embedding_type}, confidence={embedding_confidence:.4f}")
    except Exception as e:
        logger.warning(f"Embedding classification failed (falling back to LLM): {e}")

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, timeout=30.0)
    user_content = _build_user_content(prompt, files or [])

    # If embedding gave high confidence, add type hint + few-shot examples to the LLM prompt
    if embedding_type and embedding_type != "unknown" and embedding_confidence > 0.85:
        logger.info(f"Using embedding hint: {embedding_type} (confidence={embedding_confidence:.4f})")

        # Try to retrieve few-shot examples for better field extraction
        few_shot_text = ""
        try:
            from app.embeddings import get_similar_examples
            examples = get_similar_examples(prompt, embedding_type, top_k=3)
            if examples:
                few_shot_parts = []
                for i, ex in enumerate(examples, 1):
                    fields_json = json.dumps(ex["fields"], ensure_ascii=False)
                    few_shot_parts.append(
                        f"Eksempel {i}:\nPrompt: {ex['prompt']}\nFelter: {fields_json}"
                    )
                few_shot_text = (
                    "\n\nHer er lignende oppgaver og korrekte felt:\n\n"
                    + "\n\n".join(few_shot_parts)
                    + "\n\n"
                )
                logger.info(f"Added {len(examples)} few-shot examples for {embedding_type}")
        except Exception as e:
            logger.warning(f"Few-shot retrieval failed (continuing without): {e}")

        hint_text = (
            f'This task is of type "{embedding_type}". '
            f"Extract the fields for this task type."
            f"{few_shot_text}"
            f"\n\nOriginal prompt: {prompt}"
        )
        hint_content = [{"type": "text", "text": hint_text}]
        if files:
            hint_content.extend(process_files(files))
        llm_content = hint_content
    else:
        llm_content = user_content

    try:
        message = client.messages.create(
            model=LLM_MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": llm_content}],
        )
    except Exception as e:
        logger.warning(f"Primary model failed ({LLM_MODEL}), trying fallback: {e}")
        try:
            message = client.messages.create(
                model=LLM_FALLBACK_MODEL,
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": llm_content}],
            )
        except Exception as e2:
            logger.error(f"Fallback model also failed ({LLM_FALLBACK_MODEL}): {e2}")
            # If auto mode had a Gemini result, use it
            if backend == "auto" and gemini_result is not None:
                logger.info(f"[auto] Using saved Gemini result: {gemini_result.task_type}")
                return gemini_result
            # Last resort: keyword inference
            inferred = _infer_task_type_from_keywords(prompt)
            if inferred:
                logger.info(f"[auto] Keyword fallback: {inferred}")
                return ParsedTask(
                    task_type=inferred,
                    fields={},
                    confidence=0.5,
                    reasoning=f"All LLM backends failed, keyword-inferred: {inferred}",
                )
            return ParsedTask(
                task_type="unknown",
                fields={},
                confidence=0.0,
                reasoning=f"All LLM backends failed: {e2}",
            )

    raw_text = message.content[0].text
    logger.info(f"LLM response: {raw_text}")

    try:
        parsed = _parse_json_response(raw_text)
    except (json.JSONDecodeError, ValueError) as e:
        logger.error(f"Failed to parse LLM JSON: {e}")
        return ParsedTask(task_type="unknown", fields={}, reasoning=f"JSON parse error: {e}")

    # Handle case where LLM returns a list (batch tasks like "create 3 departments")
    if isinstance(parsed, list):
        if len(parsed) == 1:
            parsed = parsed[0]
        elif len(parsed) > 1:
            # Batch task — wrap in a batch structure
            # Use the task type from the first item
            first = parsed[0] if isinstance(parsed[0], dict) else {}
            task_type = first.get("taskType", "unknown")
            return ParsedTask(
                task_type=f"batch_{task_type}" if task_type != "unknown" else "unknown",
                fields={"items": parsed},
                confidence=first.get("confidence", 0.5),
                reasoning=f"Batch of {len(parsed)} items",
            )

    if not isinstance(parsed, dict):
        logger.error(f"Unexpected parse result type: {type(parsed)}")
        return ParsedTask(task_type="unknown", fields={}, reasoning="Unexpected response format")

    task = ParsedTask(
        task_type=parsed.get("taskType", "unknown"),
        fields=parsed.get("fields", {}),
        confidence=parsed.get("confidence", 0.0),
        reasoning=parsed.get("reasoning", ""),
    )
    logger.info(f"Parsed: type={task.task_type}, confidence={task.confidence}")

    # Validate task_type: if LLM returned something not in our known types, treat as unknown
    if task.task_type not in VALID_TASK_TYPES and task.task_type != "unknown":
        logger.warning(f"LLM returned unrecognized task type: {task.task_type}")
        task.task_type = "unknown"

    # Sonnet fallback: re-parse if confidence is low OR task_type is "unknown"
    needs_fallback = (task.confidence < 0.90 or task.task_type == "unknown") and message.model != LLM_FALLBACK_MODEL
    if needs_fallback:
        logger.info(f"Fallback needed (type={task.task_type}, confidence={task.confidence}), re-parsing with {LLM_FALLBACK_MODEL}")
        try:
            fallback_message = client.messages.create(
                model=LLM_FALLBACK_MODEL,
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_content}],
            )
            fallback_raw = fallback_message.content[0].text
            logger.info(f"Fallback LLM response: {fallback_raw}")
            fallback_parsed = _parse_json_response(fallback_raw)
            if isinstance(fallback_parsed, dict):
                fallback_task = ParsedTask(
                    task_type=fallback_parsed.get("taskType", "unknown"),
                    fields=fallback_parsed.get("fields", {}),
                    confidence=fallback_parsed.get("confidence", 0.0),
                    reasoning=fallback_parsed.get("reasoning", ""),
                )
                # Accept fallback if it improved confidence or resolved unknown
                if fallback_task.task_type != "unknown" and fallback_task.task_type in VALID_TASK_TYPES:
                    logger.info(f"Fallback resolved: {task.task_type} → {fallback_task.task_type} (confidence {fallback_task.confidence})")
                    return fallback_task
                if fallback_task.confidence > task.confidence and fallback_task.task_type != "unknown":
                    logger.info(f"Fallback improved confidence: {task.confidence} → {fallback_task.confidence}")
                    return fallback_task
        except Exception as e:
            logger.warning(f"Fallback re-parse failed: {e}")

    # Last resort: keyword-based inference if still "unknown"
    if task.task_type == "unknown":
        inferred = _infer_task_type_from_keywords(prompt)
        if inferred:
            logger.info(f"Keyword inference resolved unknown → {inferred}")
            task.task_type = inferred
            task.reasoning = f"Keyword-inferred: {inferred}. Original: {task.reasoning}"
            # Re-parse with fallback model to extract fields properly
            try:
                hint_prompt = f"This task is of type \"{inferred}\". Extract the fields.\n\nOriginal prompt: {prompt}"
                hint_message = client.messages.create(
                    model=LLM_FALLBACK_MODEL,
                    max_tokens=1024,
                    system=SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": [{"type": "text", "text": hint_prompt}]}],
                )
                hint_raw = hint_message.content[0].text
                hint_parsed = _parse_json_response(hint_raw)
                if isinstance(hint_parsed, dict) and hint_parsed.get("fields"):
                    task.fields = hint_parsed["fields"]
                    task.confidence = hint_parsed.get("confidence", 0.85)
                    logger.info(f"Keyword-hinted re-parse extracted fields for {inferred}")
            except Exception as e:
                logger.warning(f"Keyword-hinted re-parse failed: {e}")

    return task
