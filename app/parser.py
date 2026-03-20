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
   Fields: name*, organizationNumber, email, invoiceEmail, phoneNumber, phoneNumberMobile, isPrivateIndividual (bool), description, bankAccount, website, address (object with addressLine1, addressLine2, postalCode, city)

2. "create_customer" — Register a new customer
   Fields: name*, organizationNumber, email, invoiceEmail, phoneNumber, phoneNumberMobile, isPrivateIndividual (bool), description, isSupplier (bool), website, address (object with addressLine1, addressLine2, postalCode, city)

3. "create_employee" — Register a new employee
   Fields: firstName*, lastName*, email, phoneNumberMobile, dateOfBirth (YYYY-MM-DD), startDate (YYYY-MM-DD), employeeNumber, nationalIdentityNumber, bankAccountNumber, address (object with addressLine1, postalCode, city)

4. "create_product" — Register a new product
   Fields: name*, number, priceExcludingVat (number), priceIncludingVat (number), costExcludingVat (number), description, vatCode (string — Tripletex codes: "3" = 25% standard, "31" = 15% food/middels, "33" = 12% low/transport, "5" = 0% exempt, "6" = 0% outside VAT law), isInactive (bool)

5. "create_department" — Create a department
   Fields: name*, departmentNumber

6. "create_invoice" — Create an invoice for a customer
   Fields: customerName*, customerOrgNumber, invoiceDate (YYYY-MM-DD), dueDate (YYYY-MM-DD), lines* (array of {description, quantity, unitPriceExcludingVat, vatCode — use "3" for 25%, "31" for 15%, "33" for 12%, "5" for 0%})

7. "register_payment" — Register payment on an existing invoice (customer pays)
   Fields: customerName, customerOrgNumber, invoiceNumber (integer only), amount, paymentDate (YYYY-MM-DD)

8. "reverse_payment" — Reverse/cancel a payment on an invoice (e.g. returned by bank, undo payment)
   Fields: customerName, customerOrgNumber, invoiceNumber (integer only), amount

9. "create_credit_note" — Create a credit note for an invoice
   Fields: customerName, customerOrgNumber, invoiceNumber, comment

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

18. "unknown" — If you cannot determine the task type

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

    task = ParsedTask(
        task_type=parsed.get("taskType", "unknown"),
        fields=parsed.get("fields", {}),
        confidence=parsed.get("confidence", 0.0),
        reasoning=parsed.get("reasoning", ""),
    )
    logger.info(f"Parsed: type={task.task_type}, confidence={task.confidence}")
    return task
