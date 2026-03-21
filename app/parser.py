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
    ]),
    ("register_supplier_invoice", [
        r"leverandorfaktura.*(?:PDF|vedlagt|attached)|(?:PDF|vedlagt|attached).*leverandorfaktura",
        r"supplier.?invoice.*(?:PDF|attached)|(?:PDF|attached).*supplier.?invoice",
        r"factura.*proveedor.*PDF|PDF.*factura.*proveedor",
    ]),
    ("create_custom_dimension", [
        r"dimensjon|dimension|dimensão|dimensión|Dimension",
        r"regnskapsdimensjon|accounting dimension|dimensão contab|dimensión contab|comptable.*dimension|dimension.*comptable",
    ]),
    ("set_project_fixed_price", [
        r"fastpris|fixed.?price|preço fixo|precio fijo|Festpreis|prix fixe|prix forfait",
        r"delbetaling|partial payment|pago parcial|pagamento parcial|Teilzahlung|paiement partiel",
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
    ]),
    ("create_voucher", [
        r"(?:opprett|create|bokfør|cre[ea]r?|erstellen|comptabilise).{0,30}(?:bilag|voucher|asiento|lançamento|Beleg|pièce|écriture)",
    ]),
    ("register_supplier_invoice", [
        r"(?:leverandør|supplier|innkjøps).*faktura|supplier.invoice|factura.*proveedor|fatura.*fornecedor",
    ]),
    ("create_credit_note", [
        r"kreditnota|credit.?note|nota de crédito|Gutschrift|note de crédit|avoir",
    ]),
]


def _infer_task_type_from_keywords(prompt: str) -> str | None:
    """Try to infer task type from keywords in the prompt. Returns None if no match."""
    prompt_lower = prompt.lower()
    for task_type, patterns in _KEYWORD_RULES:
        for pattern in patterns:
            if re.search(pattern, prompt_lower, re.IGNORECASE):
                logger.info(f"Keyword match: '{pattern}' → {task_type}")
                return task_type
    return None


SYSTEM_PROMPT = """You are an accounting task parser for Tripletex (Norwegian accounting software).
You receive a task prompt in one of these languages: Norwegian Bokmål, Norwegian Nynorsk, English, Spanish, Portuguese, German, or French.

Extract the task type and relevant fields. Return ONLY valid JSON.

IMPORTANT: You MUST classify the task as one of the supported types below. Only use "unknown" as an absolute last resort when none of the types match at all.

Supported task types and their fields:

1. "create_supplier" — Register a new supplier
   Fields: name*, organizationNumber, email (IMPORTANT: for suppliers, put the email ONLY in the "email" field — do NOT copy to invoiceEmail unless the prompt explicitly says "invoice email" or "fakturaepost"), invoiceEmail (only if explicitly mentioned as invoice/faktura email), phoneNumber, phoneNumberMobile, isPrivateIndividual (bool), description, bankAccount, website, address (object with addressLine1, addressLine2, postalCode, city)

2. "create_customer" — Register a new customer
   Fields: name*, organizationNumber, email (IMPORTANT: if prompt says "email" or "e-post" without specifying type, put it in BOTH email AND invoiceEmail), invoiceEmail, phoneNumber, phoneNumberMobile, isPrivateIndividual (bool), description, isSupplier (bool), website, address (object with addressLine1, addressLine2, postalCode, city)

3. "create_employee" — Register a new employee
   Fields: firstName*, lastName*, email, phoneNumberMobile, dateOfBirth (YYYY-MM-DD), startDate (YYYY-MM-DD), employeeNumber, nationalIdentityNumber, bankAccountNumber, address (object with addressLine1, postalCode, city), role (string — extract if the prompt mentions a role like "administrator", "kontoadministrator", "accountant", "regnskapsfører", "faktureringsansvarlig", "avdelingsleder", etc.)

4. "create_product" — Register a new product
   Fields: name*, number, priceExcludingVat (number), priceIncludingVat (number), costExcludingVat (number), description, vatCode (string — Tripletex codes: "3" = 25% standard, "31" = 15% food/middels, "33" = 12% low/transport, "5" = 0% exempt, "6" = 0% outside VAT law), isInactive (bool)

5. "create_department" — Create a department
   Fields: name*, departmentNumber

6. "create_invoice" — Create an invoice for a customer
   Fields: customerName*, customerOrgNumber, invoiceDate (YYYY-MM-DD), dueDate (YYYY-MM-DD), lines* (array of {description, productNumber (extract the number in parentheses if present, e.g. "Konsulenttimer (9497)" → productNumber: "9497"), quantity, unitPriceExcludingVat, vatCode — use "3" for 25%, "31" for 15%, "33" for 12%, "5" for 0%})
   IMPORTANT: If the prompt mentions product numbers like "(4783)" next to product names, include productNumber in each line.

7. "register_payment" — Register payment on an existing invoice (customer pays)
   Fields: customerName, customerOrgNumber, invoiceNumber (integer only), amount, paymentDate (YYYY-MM-DD), invoiceDescription (what the invoice was for, e.g. "Maintenance"), lines (array of {description, quantity, unitPriceExcludingVat, vatCode} — extract if the prompt describes invoice line items)

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

13. "set_project_fixed_price" — Create a project linked to a customer with a fixed price amount, and optionally invoice a percentage as partial payment (keywords: fastpris, fixed price, preço fixo, Festpreis, prix fixe, precio fijo, delbetaling, partial payment, pago parcial, pagamento parcial, Teilzahlung, paiement partiel)
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
    Fields: supplierName, supplierOrgNumber, organizationNumber, amount (gross total including VAT), description, invoiceDate (YYYY-MM-DD), expenseAccount (account number, default "4000"), invoiceNumber (the supplier's invoice reference, e.g. "INV-2026-4855"), vatRate (integer percent, e.g. 25 for 25%, default 25)

26. "register_timesheet" — Register hours/timesheet entry for an employee, AND optionally generate a project invoice to the customer based on the registered hours (registrere timer, Stunden erfassen, registar horas, enregistrer heures, prosjektfaktura, project invoice)
    Fields: employeeName, employeeEmail, projectName, activityName, hours* (number), date (YYYY-MM-DD), comment, hourlyRate (number — NOK per hour, extract if prompt mentions timesats/hourly rate/taxa horária/taux horaire/Stundensatz), customerName (the customer to invoice), customerOrgNumber (customer org number)
    IMPORTANT: If the prompt asks to BOTH register hours AND generate an invoice/project invoice, this is ONE task of type "register_timesheet" — do NOT split it into two separate tasks. Extract hourlyRate, customerName, and customerOrgNumber as fields.

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

32. "correct_ledger_error" — Correct an error in the ledger / bookkeeping (feilretting i regnskap / error correction / Korrekturbuchung / corrección contable / correction comptable / correção contábil): find and reverse the erroneous voucher, then post a corrected voucher
    Fields: voucherNumber (integer — the erroneous voucher number), date (YYYY-MM-DD — date of the erroneous voucher), description (string — description to identify the erroneous voucher), correctedPostings (array of {debitAccount, creditAccount, amount} — the CORRECT postings to replace the error), correctionDescription (string — description for the correction voucher), correctionDate (YYYY-MM-DD — date for correction, defaults to original date), accountFrom (integer — the WRONG account number used in the error), accountTo (integer — the CORRECT account number), amount (number — the amount involved), creditAccount (integer — credit account for simple correction, default 1920)

33. "monthly_closing" — Perform monthly closing (månedsavslutning/Monatsabschluss/cierre mensual/clôture mensuelle/encerramento mensal): post accruals, depreciations, and provisions as vouchers
    Fields: month* (integer 1-12), year* (integer), accruals (array of {fromAccount (balance sheet account to credit, e.g. 1720), toAccount (expense account to debit, e.g. 6300), amount (number), description (string)}), depreciations (array of {account (expense account for depreciation, e.g. 6020), assetAccount (balance sheet asset account to credit, e.g. 1200), acquisitionCost (number — original cost of the asset), usefulLifeYears (number — useful life in years), description (string)}), provisions (array of {debitAccount (expense account, e.g. 5000), creditAccount (liability account, e.g. 2900), amount (number), description (string)})

34. "unknown" — ONLY if you truly cannot determine the task type from ANY of the above categories

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
