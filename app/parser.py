from __future__ import annotations

import json
import logging
from typing import Any

import anthropic

from app.config import ANTHROPIC_API_KEY, LLM_MODEL, LLM_FALLBACK_MODEL
from app.file_processor import process_files
from app.models import ParsedTask

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an accounting task parser for Tripletex (Norwegian accounting software).
You receive a task prompt in one of these languages: Norwegian Bokmål, Norwegian Nynorsk, English, Spanish, Portuguese, German, or French.

Extract the task type and relevant fields. Return ONLY valid JSON.

Supported task types and their fields:

1. "create_supplier" — Register a new supplier
   Fields: name*, organizationNumber, email (IMPORTANT: if prompt says "email" or "e-post" without specifying type, put it in BOTH email AND invoiceEmail), invoiceEmail, phoneNumber, phoneNumberMobile, isPrivateIndividual (bool), description, bankAccount, website, address (object with addressLine1, addressLine2, postalCode, city)

2. "create_customer" — Register a new customer
   Fields: name*, organizationNumber, email (IMPORTANT: if prompt says "email" or "e-post" without specifying type, put it in BOTH email AND invoiceEmail), invoiceEmail, phoneNumber, phoneNumberMobile, isPrivateIndividual (bool), description, isSupplier (bool), website, address (object with addressLine1, addressLine2, postalCode, city)

3. "create_employee" — Register a new employee
   Fields: firstName*, lastName*, email, phoneNumberMobile, dateOfBirth (YYYY-MM-DD), startDate (YYYY-MM-DD), employeeNumber, nationalIdentityNumber, bankAccountNumber, address (object with addressLine1, postalCode, city), role (string — extract if the prompt mentions a role like "administrator", "kontoadministrator", "accountant", "regnskapsfører", "faktureringsansvarlig", "avdelingsleder", etc.)

4. "create_product" — Register a new product
   Fields: name*, number, priceExcludingVat (number), priceIncludingVat (number), costExcludingVat (number), description, vatCode (string — Tripletex codes: "3" = 25% standard, "31" = 15% food/middels, "33" = 12% low/transport, "5" = 0% exempt, "6" = 0% outside VAT law), isInactive (bool)

5. "create_department" — Create a department
   Fields: name*, departmentNumber

6. "create_invoice" — Create an invoice for a customer
   Fields: customerName*, customerOrgNumber, invoiceDate (YYYY-MM-DD), dueDate (YYYY-MM-DD), lines* (array of {description, quantity, unitPriceExcludingVat, vatCode — use "3" for 25%, "31" for 15%, "33" for 12%, "5" for 0%})

7. "register_payment" — Register payment on an existing invoice (customer pays)
   Fields: customerName, customerOrgNumber, invoiceNumber (integer only), amount, paymentDate (YYYY-MM-DD), invoiceDescription (what the invoice was for, e.g. "Maintenance"), lines (array of {description, quantity, unitPriceExcludingVat, vatCode} — extract if the prompt describes invoice line items)

8. "reverse_payment" — Reverse/cancel a payment on an invoice (e.g. returned by bank, undo payment)
   Fields: customerName, customerOrgNumber, invoiceNumber (integer only), amount, paymentDate (YYYY-MM-DD), invoiceDescription, lines (array of {description, quantity, unitPriceExcludingVat, vatCode})

9. "create_credit_note" — Create a credit note for an invoice
   Fields: customerName, customerOrgNumber, invoiceNumber, comment, amount, invoiceDescription, lines (array of {description, quantity, unitPriceExcludingVat, vatCode})

10. "create_travel_expense" — Register a travel expense
   Fields: employeeName*, employeeFirstName, employeeLastName, title*, date (YYYY-MM-DD), costs (array of {description, amount, vatCode, currency})

11. "delete_travel_expense" — Delete a travel expense
    Fields: employeeName, travelExpenseTitle, travelExpenseId

12. "create_project" — Create a project
    Fields: name*, customerName, customerOrgNumber, startDate (YYYY-MM-DD), endDate (YYYY-MM-DD), projectManagerName, isClosed (bool)

13. "update_employee" — Update employee details
    Fields: employeeName, employeeFirstName, employeeLastName, changes (object with fields to update)

14. "update_customer" — Update customer details
    Fields: customerName, customerOrgNumber, changes (object with fields to update)

15. "create_voucher" — Create a voucher / journal entry
    Fields: description*, date (YYYY-MM-DD), postings* (array of {debitAccount, creditAccount, amount, description})

16. "reverse_voucher" — Reverse an existing voucher
    Fields: voucherNumber, date

17. "delete_voucher" — Delete a voucher
    Fields: voucherNumber, date

18. "update_supplier" — Update supplier details
    Fields: supplierName, supplierOrgNumber, organizationNumber, changes (object with fields to update)

19. "update_product" — Update product details
    Fields: productName, productNumber, number, changes (object with fields to update)

20. "delete_employee" — Delete an employee
    Fields: employeeName, employeeFirstName, employeeLastName

21. "delete_customer" — Delete a customer
    Fields: customerName, customerOrgNumber

22. "delete_supplier" — Delete a supplier
    Fields: supplierName, supplierOrgNumber

23. "create_order" — Create an order (without invoicing)
    Fields: customerName*, customerOrgNumber, orderDate (YYYY-MM-DD), deliveryDate (YYYY-MM-DD), lines (array of {description, quantity, unitPriceExcludingVat})

24. "register_supplier_invoice" — Register a supplier invoice (innkjøpsfaktura/leverandørfaktura)
    Fields: supplierName, supplierOrgNumber, organizationNumber, amount, description, invoiceDate (YYYY-MM-DD), expenseAccount (account number, default "4000")

25. "register_timesheet" — Register hours/timesheet entry for an employee
    Fields: employeeName, employeeEmail, projectName, activityName, hours* (number), date (YYYY-MM-DD), comment

26. "create_invoice_from_pdf" — Create an invoice from an attached PDF (scanned invoice)
    Fields: customerName, customerOrgNumber, invoiceDate (YYYY-MM-DD), dueDate (YYYY-MM-DD), lines (array of {description, quantity, unitPriceExcludingVat, vatCode}), totalAmount (number)

27. "unknown" — If you cannot determine the task type

Examples:

Prompt: "Registre el proveedor Dorada SL con número de organización 853166553. Correo electrónico: faktura@doradasl.no."
Output: {"taskType": "create_supplier", "fields": {"name": "Dorada SL", "organizationNumber": "853166553", "email": "faktura@doradasl.no", "invoiceEmail": "faktura@doradasl.no"}, "confidence": 0.95, "reasoning": "Spanish prompt requesting supplier registration with org number and email."}

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

Prompt: "Create three departments in Tripletex: \"Utvikling\", \"Lager\", and \"Regnskap\"."
Output: [{"taskType": "create_department", "fields": {"name": "Utvikling"}, "confidence": 0.95, "reasoning": "Batch: department 1 of 3."}, {"taskType": "create_department", "fields": {"name": "Lager"}, "confidence": 0.95, "reasoning": "Batch: department 2 of 3."}, {"taskType": "create_department", "fields": {"name": "Regnskap"}, "confidence": 0.95, "reasoning": "Batch: department 3 of 3."}]

Prompt: "Kunden Vestfjord AS (org.nr 860678403) har reklamert på fakturaen for \"Skylagring\" (45350 kr ekskl. MVA). Opprett ei fullstendig kreditnota som reverserer heile fakturaen."
Output: {"taskType": "create_credit_note", "fields": {"customerName": "Vestfjord AS", "customerOrgNumber": "860678403", "invoiceDescription": "Skylagring", "amount": 45350, "lines": [{"description": "Skylagring", "quantity": 1, "unitPriceExcludingVat": 45350, "vatCode": "3"}]}, "confidence": 0.94, "reasoning": "Norwegian Nynorsk prompt to create a full credit note reversing an invoice."}

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
    """Parse a task prompt into a structured ParsedTask using one LLM call."""
    logger.info(f"Parsing task: {prompt[:200]}")

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, timeout=30.0)
    user_content = _build_user_content(prompt, files or [])

    try:
        message = client.messages.create(
            model=LLM_MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
    except Exception as e:
        logger.warning(f"Primary model failed ({LLM_MODEL}), trying fallback: {e}")
        message = client.messages.create(
            model=LLM_FALLBACK_MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
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

    # Confidence-based Sonnet fallback: re-parse with stronger model if confidence is low
    if task.confidence < 0.80 and message.model != LLM_FALLBACK_MODEL:
        logger.info(f"Low confidence ({task.confidence}), re-parsing with {LLM_FALLBACK_MODEL}")
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
                if fallback_task.confidence > task.confidence:
                    logger.info(f"Fallback improved confidence: {task.confidence} → {fallback_task.confidence}")
                    return fallback_task
        except Exception as e:
            logger.warning(f"Fallback re-parse failed: {e}")

    return task
