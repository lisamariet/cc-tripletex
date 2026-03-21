#!/usr/bin/env python3
"""Real competition prompt regression suite.

Tests built from ACTUAL prompts received during the NM i AI 2026 competition,
downloaded from gs://tripletex-agent-requests/. Each test uses the verbatim
prompt text (and real attachments where present) that was submitted to our
agent, along with the expected task_type and fields that were parsed.

Purpose: Verify we score 100% on every task type we have already handled.

Usage:
    python3 scripts/test_real_prompts.py             # Dry-run: show test plan
    python3 scripts/test_real_prompts.py --live      # Execute against sandbox
    python3 scripts/test_real_prompts.py --live -v   # Verbose
    python3 scripts/test_real_prompts.py --live --only create_invoice,run_payroll
    python3 scripts/test_real_prompts.py --live --tier 1   # Run tier 1 only
    python3 scripts/test_real_prompts.py --live --tier 2   # Run tier 2 only
    python3 scripts/test_real_prompts.py --live --tier 3   # Run tier 3 only

Source: gs://tripletex-agent-requests/requests/ + results/ (downloaded 2026-03-21)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

# Reuse infrastructure from test_e2e.py
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from scripts.test_e2e import (
    E2ETestCase,
    FieldCheck,
    VerifySpec,
    get_sandbox_creds,
    green, red, yellow, dim, bold,
)

logging.basicConfig(level=logging.WARNING, format="%(message)s")
logger = logging.getLogger("real_prompts")


# ---------------------------------------------------------------------------
# Real attachment data (base64, sourced directly from GCS requests)
# ---------------------------------------------------------------------------

# Bank statement CSVs (windows-1252, semicolon-separated)
_BANK_CSV_FR_B64 = (
    "RGF0bztGb3JrbGFyaW5nO0lubjtVdDtTYWxkbw0KMjAyNi0wMS0xNztJbm5iZXRhbGluZyBm"
    "cmEgUGV0aXQgU0FSTCAvIEZha3R1cmEgMTAwMTsxODU2Mi41MDs7MTE4NTYyLjUwDQoyMDI2"
    "LTAxLTE5O0lubmJldGFsaW5nIGZyYSBCZXJuYXJkIFNBUkwgLyBGYWt0dXJhIDEwMDI7MTk3"
    "NS4wMDs7MTIwNTM3LjUwDQoyMDI2LTAxLTIyO0lubmJldGFsaW5nIGZyYSBCZXJuYXJkIFNB"
    "UkwgLyBGYWt0dXJhIDEwMDM7MTk2ODcuNTA7OzE0MDIyNS4wMA0KMjAyNi0wMS0yNTtJbm5i"
    "ZXRhbGluZyBmcmEgUGV0aXQgU0FSTCAvIEZha3R1cmEgMTAwNDsyNDEyNS4wMDs7MTY0MzUw"
    "LjAwDQoyMDI2LTAxLTI3O0lubmJldGFsaW5nIGZyYSBMZXJveSBTQVJMIC8gRmFrdHVyYSAx"
    "MDA1OzE2NzUwLjAwOzsxODExMDAuMDANCjIwMjYtMDEtMjk7QmV0YWxpbmcgRm91cm5pc3Nl"
    "dXIgUmljaGFyZCBTQVJMOzstMTYzNTAuMDA7MTY0NzUwLjAwDQoyMDI2LTAxLTMwO0JldGFs"
    "aW5nIEZvdXJuaXNzZXVyIExlcm95IFNBX1JMOzstNTUwMC4wMDsxNTkyNTAuMDANCjIwMjYt"
    "MDItMDE7QmV0YWxpbmcgRm91cm5pc3NldXIgRHVib2lzIFNBUkw7Oy05ODUwLjAwOzE0OTQw"
    "MC4wMA0KMjAyNi0wMi0wMztSZW50ZWlubnRla3Rlcjs7LTcxMy4zNjsxNDg2ODYuNjQNCjIw"
    "MjYtMDItMDU7U2thdHRldHJlazs7LTY3Mi4xMTsxNDgwMTQuNTMNCg=="
)

_BANK_CSV_NB_B64 = (
    "RGF0bztGb3JrbGFyaW5nO0lubjtVdDtTYWxkbw0KMjAyNi0wMS0xNztJbm5iZXRhbGluZyBm"
    "cmEgQmVyZyBBUyAvIEZha3R1cmEgMTAwMTsxMDkzNy41MDs7MTEwOTM3LjUwDQoyMDI2LTAx"
    "LTE5O0lubmJldGFsaW5nIGZyYSBOaWxzZW4gQVMgLyBGYWt0dXJhIDEwMDI7MTE1MDAuMDA7"
    "OzEyMjQzNy41MA0KMjAyNi0wMS0yMjtJbm5iZXRhbGluZyBmcmEgQmFra2VuIEFTIC8gRmFr"
    "dHVyYSAxMDAzOzE3Njg3LjUwOzsxNDAxMjUuMDANCjIwMjYtMDEtMjU7SW5uYmV0YWxpbmcg"
    "ZnJhIEpvaGFuc2VuIEFTIC8gRmFrdHVyYSAxMDA0OzMxMTg3LjUwOzsxNzEzMTIuNTANCjIw"
    "MjYtMDEtMjg7SW5uYmV0YWxpbmcgZnJhIEpvaGFuc2VuIEFTIC8gRmFrdHVyYSAxMDA1OzQ4"
    "NTAuMDA7OzE3NjE2Mi41MA0KMjAyNi0wMS0yOTtCZXRhbGluZyBMZXZlcmFuZG9yIEhhbnNl"
    "biBBUzs7LTcxMDAuMDA7MTY5MDYyLjUwDQoyMDI2LTAyLTAxO0JldGFsaW5nIExldmVyYW5k"
    "b3Igw5hkZWfDpXJkIEFTOzstMTgyMDAuMDA7MTUwODYyLjUwDQoyMDI2LTAyLTA0O0JldGFs"
    "aW5nIExldmVyYW5kb3IgSGFuc2VuIEFTOzstOTYwMC4wMDsxNDEyNjIuNTANCjIwMjYtMDIt"
    "MDU7QmFua2dlYnlyOzI1OC4zNjs7MTQxNTIwLjg2DQoyMDI2LTAyLTA3O0JhbmtnZWJ5cjsx"
    "NjMzLjUxOzsxNDMxNTQuMzcNCg=="
)

# Supplier invoice PDFs (real PDF content from competition requests)
_SUPPLIER_PDF_DE_B64 = (
    "JVBERi0xLjMKJenr8b8KMSAwIG9iago8PAovQ291bnQgMQovS2lkcyBbMyAwIFJdCi9NZWRp"
    "YUJveCBbMCAwIDU5NS4yOCA4NDEuODldCi9UeXBlIC9QYWdlcwo+PgplbmRvYmoKMiAwIG9i"
    "ago8PAovT3BlbkFjdGlvbiBbMyAwIFIgL0ZpdEggbnVsbF0KL1BhZ2VMYXlvdXQgL09uZUNv"
    "bHVtbgovUGFnZXMgMSAwIFIKL1R5cGUgL0NhdGFsb2cKPj4KZW5kb2JqCjMgMCBvYmoKPDwK"
    "L0NvbnRlbnRzIDQgMCBSCi9QYXJlbnQgMSAwIFIKL1Jlc291cmNlcyA3IDAgUgovVHlwZSAv"
    "UGFnZQo+PgplbmRvYmoKNCAwIG9iago8PAovRmlsdGVyIC9GbGF0ZURlY29kZQovTGVuZ3Ro"
    "IDQ0Mwo+PgpzdHJlYW0KeJyVk01v00AQhu/9FXNBKhKd7uz35pYIwkdFKoHp3ZBNcf2F1tsi"
    "/jlHNnGs2Gmp0qNX87yPd2aHw6czhsrA77NFBpdLAtLIGGQbeJdtjwQhWTBObouyNZyv2rCu"
    "ih8/I7yvv394DdndvvJyyYHYU7ARqN0Ovg632IQZWEOkOdNuxO+LlR6KV39u85iDEm/AMWYh"
    "C23d/Z0YCfjUyKVDwUE7h1bsUpbzq+zbl/kRRvTEj2plkPpbLvMy3oe8ua9rH2bHt5zCpCwa"
    "OaY/rm4uOOP6wmiik8wi9ZeNzes8tid6DyxLs5O4NZ8kTaeW99I2bPKq6l5gPcBbqzrZqoxB"
    "2/9uVlQzeFvECJsi1PlAc4tCgeISJUGdsGSi4buCr3DIEhyl2mUtfFeG4sFXnR9ypmANSmt0"
    "4ihICYFKTpOq9tfzPdjbmUOzXwof44MPZRfvfOO76MMoQHFCwcblQuk0sTI8vz3SMjQCZGqY"
    "7LnPN3Pg6lXaH0f8mE/95lPepMEYkEqhpr7hbcyrOAMplX7E/2d7ZUrldodftU16HunBMfZo"
    "b4VLDew3bpE3ZdmXcisccyTS0AfiHxwTCwsKZW5kc3RyZWFtCmVuZG9iago1IDAgb2JqCjw8"
    "Ci9CYXNlRm9udCAvSGVsdmV0aWNhLUJvbGQKL0VuY29kaW5nIC9XaW5BbnNpRW5jb2Rpbmcr"
    "L1N1YnR5cGUgL1R5cGUxCi9UeXBlIC9Gb250Cj4+CmVuZG9iago2IDAgb2JqCjw8Ci9CYXNl"
    "Rm9udCAvSGVsdmV0aWNhCi9FbmNvZGluZyAvV2luQW5zaUVuY29kaW5nCi9TdWJ0eXBlIC9U"
    "eXBlMQovVHlwZSAvRm9udAo+PgplbmRvYmoKNyAwIG9iago8PAovRm9udCA8PC9GMSA1IDAg"
    "UgovRjIgNiAwIFI+PgovUHJvY1NldCBbL1BERiAvVGV4dCAvSW1hZ2VCIC9JbWFnZUMgL0lt"
    "YWdlSV0KPj4KZW5kb2JqCjggMCBvYmoKPDwKL0NyZWF0aW9uRGF0ZSAoRDoyMDI2MDMwNDE5"
    "MTgwNVopCj4+CmVuZG9iagp4cmVmCjAgOQowMDAwMDAwMDAwIDY1NTM1IGYgCjAwMDAwMDAw"
    "MTUgMDAwMDAgbiAKMDAwMDAwMDEwMiAwMDAwMCBuIAowMDAwMDAwMjA1IDAwMDAwIG4gCjAw"
    "MDAwMDAyODUgMDAwMDAgbiAKMDAwMDAwMDgwMCAwMDAwMCBuIAowMDAwMDAwOTAyIDAwMDAw"
    "IG4gCjAwMDAwMDA5OTkgMDAwMDAgbiAKMDAwMDAwMTA5NiAwMDAwMCBuIAp0cmFpbGVyCjw8"
    "Ci9TaXplIDkKL1Jvb3QgMiAwIFIKL0luZm8gOCAwIFIKL0lEIFs8REI3RjlDMUQ1QUJEODk3"
    "N0JFOUU0OEExQzU1RUFDMUM+PERCN0Y5QzFENUFCRDg5NzdCRTlFNDhBMUM1NUVBQzFDPl0K"
    "Pj4Kc3RhcnR4cmVmCjExNTEKJSVFT0YK"
)

_SUPPLIER_PDF_NN_B64 = (
    "JVBERi0xLjMKJenr8b8KMSAwIG9iago8PAovQ291bnQgMQovS2lkcyBbMyAwIFJdCi9NZWRp"
    "YUJveCBbMCAwIDU5NS4yOCA4NDEuODldCi9UeXBlIC9QYWdlcwo+PgplbmRvYmoKMiAwIG9i"
    "ago8PAovT3BlbkFjdGlvbiBbMyAwIFIgL0ZpdEggbnVsbF0KL1BhZ2VMYXlvdXQgL09uZUNv"
    "bHVtbgovUGFnZXMgMSAwIFIKL1R5cGUgL0NhdGFsb2cKPj4KZW5kb2JqCjMgMCBvYmoKPDwK"
    "L0NvbnRlbnRzIDQgMCBSCi9QYXJlbnQgMSAwIFIKL1Jlc291cmNlcyA3IDAgUgovVHlwZSAv"
    "UGFnZQo+PgplbmRvYmoKNCAwIG9iago8PAovRmlsdGVyIC9GbGF0ZURlY29kZQovTGVuZ3Ro"
    "IDQ0Mwo+PgpzdHJlYW0KeJyVk11r2zAUhu/7K87NoINF1dG3fJewBrawDVqv94I4wbVsD1np"
    "/v7kOCZ22pX0UuI87yMd6TD4fkOJ1PD3ZpXD3RoBFaEU8h3c5/0WR4IGtBV9Ub6F23v/snUe"
    "lo+fIX8+Fd2tGSB9i9OcKHvkfoU9aUIGFrVhTGsz4U/FUo3FeRv2excdIOdfQChE2ISyi6Vr"
    "OtdsZ2oENlczYQlnoKwlhh/j1stN/vtheYEhvnFiJTXB4aZrV8VDcM2hrouQXV53DqM0RIsp"
    "/e3n04JRphZKUbzKzFOP6dS8dbG90ntmaSoQpDdfJU27hg3SNuyc990HrGe4t8qrrVJrYobj5"
    "qXP4GsZI+zKULuRZoZwCZIJIhDqhCUTjmsPj3DO4owIecxaFV0VypfCd8WYMwdrkEoRyy+CJ"
    "OdEinmSb/+834OTnVqiTw+eL6q26Q6+aGJ8Lpqii0WYZEiGhNMpkT5qerQqvD9JwlCiOYjUM"
    "zFwP56WwOSnDBTj+pJPLWdzXqeJ1iCkJApP0xWdj1nfVfOK/88ki5TKzBHftE36IenPUfpqh"
    "rlNPRyGbuWaqhpKGRrLDUWt+Ej8A6dGDK0KZW5kc3RyZWFtCmVuZG9iago1IDAgb2JqCjw8"
    "Ci9CYXNlRm9udCAvSGVsdmV0aWNhLUJvbGQKL0VuY29kaW5nIC9XaW5BbnNpRW5jb2Rpbmcr"
    "L1N1YnR5cGUgL1R5cGUxCi9UeXBlIC9Gb250Cj4+CmVuZG9iago2IDAgb2JqCjw8Ci9CYXNl"
    "Rm9udCAvSGVsdmV0aWNhCi9FbmNvZGluZyAvV2luQW5zaUVuY29kaW5nCi9TdWJ0eXBlIC9U"
    "eXBlMQovVHlwZSAvRm9udAo+PgplbmRvYmoKNyAwIG9iago8PAovRm9udCA8PC9GMSA1IDAg"
    "UgovRjIgNiAwIFI+PgovUHJvY1NldCBbL1BERiAvVGV4dCAvSW1hZ2VCIC9JbWFnZUMgL0lt"
    "YWdlSV0KPj4KZW5kb2JqCjggMCBvYmoKPDwKL0NyZWF0aW9uRGF0ZSAoRDoyMDI2MDMwNDE5"
    "MTgwNVopCj4+CmVuZG9iagp4cmVmCjAgOQowMDAwMDAwMDAwIDY1NTM1IGYgCjAwMDAwMDAw"
    "MTUgMDAwMDAgbiAKMDAwMDAwMDEwMiAwMDAwMCBuIAowMDAwMDAwMjA1IDAwMDAwIG4gCjAw"
    "MDAwMDAyODUgMDAwMDAgbiAKMDAwMDAwMDgwMCAwMDAwMCBuIAowMDAwMDAwOTAyIDAwMDAw"
    "IG4gCjAwMDAwMDA5OTkgMDAwMDAgbiAKMDAwMDAwMTA5NiAwMDAwMCBuIAp0cmFpbGVyCjw8"
    "Ci9TaXplIDkKL1Jvb3QgMiAwIFIKL0luZm8gOCAwIFIKL0lEIFs8MTYxMTZDRjU0Q0RERURD"
    "MjFGRTZGOUVDMThDNDY1OTE+PDE2MTE2Q0Y1NENEREVEQzIxRkU2RjlFQzE4QzQ2NTkxPl0K"
    "Pj4Kc3RhcnR4cmVmCjExNTEKJSVFT0YK"
)

# Employee offer letter PDFs
_EMPLOYEE_OFFER_ES_B64 = (
    "JVBERi0xLjMKJenr8b8KMSAwIG9iago8PAovQ291bnQgMQovS2lkcyBbMyAwIFJdCi9NZWRp"
    "YUJveCBbMCAwIDU5NS4yOCA4NDEuODldCi9UeXBlIC9QYWdlcwo+PgplbmRvYmoKMiAwIG9i"
    "ago8PAovT3BlbkFjdGlvbiBbMyAwIFIgL0ZpdEggbnVsbF0KL1BhZ2VMYXlvdXQgL09uZUNv"
    "bHVtbgovUGFnZXMgMSAwIFIKL1R5cGUgL0NhdGFsb2cKPj4KZW5kb2JqCjMgMCBvYmoKPDwK"
    "L0NvbnRlbnRzIDQgMCBSCi9QYXJlbnQgMSAwIFIKL1Jlc291cmNlcyA3IDAgUgovVHlwZSAv"
    "UGFnZQo+PgplbmRvYmoKNCAwIG9iago8PAovRmlsdGVyIC9GbGF0ZURlY29kZQovTGVuZ3Ro"
    "IDYwNwo+PgpzdHJlYW0KeJyNVMlu2zAQvecr5lKgBVqG1K7cGiROs7Vo4/Za0OFYpkOTLqk4"
    "6Ef3HzqSbMtLWkiAQZmat8xwhhHcnHCW5vBycj6G05EAUTDOYTyFy3GzFfGEiQTyUjTLWMHb"
    "8fXd+fcL+HIPD/R6d/356h2M5+vw01EEQuwxxIQsII9zVmYtwe1coke4kSuNHq6kf/wj3+9w"
    "rAE8Y3nRAn5omEkPlUGFFuQKJNTaTH6DwgoCvRptK/oS3AI+ffvgpar0iqg1xSpsPsLts1UY"
    "0K/0I7I9v5Rx/IrfLEsZ7+QvsJZmjv4Q9lqaWZywlLewkVMBTVCydmf/r5DII1aKXaygohNf"
    "WYpBorRbRN3haFN7KpMJOFC0x0ZUh4JFPMqGiKZFuemIjzZgXTeaYer8YpjwDn4kQ709x0Ha"
    "WcaSrpke1rCw9C6grQeK9wSCc8bfDFJNYpaXXcY+GGftQLEel8acHnga1EtpRItY601QKyqR"
    "GijZQ3OW0rQsaByW9FOyOiTgPcEv2IonecGK1jRnSUQBL80cmifpz2D/vGfOKKzBY/VsaK5D"
    "O6Cd34U2c2fcimbTVTBB5fW0RhsaK8FZaWbSqol7YkAzBtUcickDRdNhrpCyhaWETTfC1z1/"
    "GfVtO58xS4uk9beQFhuCBSqg1qJcSaahtUErXYFbLoOuOt9eh5rBJaXht2okTP8Oo2g3hjU1"
    "gxF6jZRNb6q3lCSsyNuiT5uoJdKt5GHqTLs0W20t2NFdF9PtyrshvCfvFGMN+Z1pMmGPr8Y4"
    "FSyO2/Cf/36OYbQkXR/SLbm5GtFuAv8CZTygYAplbmRzdHJlYW0KZW5kb2JqCjUgMCBvYmoK"
    "PDwKL0Jhc2VGb250IC9IZWx2ZXRpY2EtQm9sZAovRW5jb2RpbmcgL1dpbkFuc2lFbmNvZGlu"
    "ZwovU3VidHlwZSAvVHlwZTEKL1R5cGUgL0ZvbnQKPj4KZW5kb2JqCjYgMCBvYmoKPDwKL0Jh"
    "c2VGb250IC9IZWx2ZXRpY2EKL0VuY29kaW5nIC9XaW5BbnNpRW5jb2RpbmcKL1N1YnR5cGUg"
    "L1R5cGUxCi9UeXBlIC9Gb250Cj4+CmVuZG9iago3IDAgb2JqCjw8Ci9Gb250IDw8L0YxIDUg"
    "MCBSCi9GMiA2IDAgUj4+Ci9Qcm9jU2V0IFsvUERGIC9UZXh0IC9JbWFnZUIgL0ltYWdlQyAv"
    "SW1hZ2VJXQo+PgplbmRvYmoKOCAwIG9iago8PAovQ3JlYXRpb25EYXRlIChEOjIwMjYwMzA0"
    "MTkxODA1WikKPj4KZW5kb2JqCnhyZWYKMCA5CjAwMDAwMDAwMDAgNjU1MzUgZiAKMDAwMDAw"
    "MDAxNSAwMDAwMCBuIAowMDAwMDAwMTAyIDAwMDAwIG4gCjAwMDAwMDAyMDUgMDAwMDAgbiAK"
    "MDAwMDAwMDI4NSAwMDAwMCBuIAowMDAwMDAwOTY0IDAwMDAwIG4gCjAwMDAwMDEwNjYgMDAwMD"
    "AgbiAKMDAwMDAwMTE2MyAwMDAwMCBuIAowMDAwMDAxMjYwIDAwMDAwIG4gCnRyYWlsZXIKPDwK"
    "L1NpemUgOQovUm9vdCAyIDAgUgovSW5mbyA4IDAgUgovSUQgWzw2Qjg4Q0NCQ0I5OTBEMEVCODk3"
    "M0VEMTI1RDVGMTIyMT48NkI4OENDQkNCOTkwRDBFQjg5NzNFRDEyNUQ1RjEyMjE+XQo+Pgpz"
    "dGFydHhyZWYKMTMxNQolJUVPRgo="
)

_EMPLOYEE_CONTRACT_NN_B64 = (
    "JVBERi0xLjMKJenr8b8KMSAwIG9iago8PAovQ291bnQgMQovS2lkcyBbMyAwIFJdCi9NZWRp"
    "YUJveCBbMCAwIDU5NS4yOCA4NDEuODldCi9UeXBlIC9QYWdlcwo+PgplbmRvYmoKMiAwIG9i"
    "ago8PAovT3BlbkFjdGlvbiBbMyAwIFIgL0ZpdEggbnVsbF0KL1BhZ2VMYXlvdXQgL09uZUNv"
    "bHVtbgovUGFnZXMgMSAwIFIKL1R5cGUgL0NhdGFsb2cKPj4KZW5kb2JqCjMgMCBvYmoKPDwK"
    "L0NvbnRlbnRzIDQgMCBSCi9QYXJlbnQgMSAwIFIKL1Jlc291cmNlcyA3IDAgUgovVHlwZSAv"
    "UGFnZQo+PgplbmRvYmoKNCAwIG9iago8PAovRmlsdGVyIC9GbGF0ZURlY29kZQovTGVuZ3Ro"
    "IDkwOAo+PgpzdHJlYW0KeJyVVk1v4zYQve+vmEuBDdCyJPVF99QEGwNpin7EviwQoGAgWqEl"
    "UyrJeLv/fI8dUnIkZ10sawiQTPLNG47ePIrDL+8oKSr49O5mCz+uGTBBKIXtDm63YYjTkpQF"
    "VCtGWA7bGt5fP9zc3n3Y3P/+2/bh+n57Bdv9tDbC2Rk8Q5iAKitJMaHtk9K1a/RR2Z/OsPwt"
    "llWcrNgSvPFWmvqoW7jeJPGyjIhqyetlm8w7g3/VR9j4L51D6hTeMlRrFaHrvnaqc7X0fRrt"
    "AktXhFH8I4ok0lKQgkXgH8q63piXwyF1swswXTEqCk7xSqLNCyKyiLz9YeidTyScYZ0+Eudj"
    "cX9W/8jD0CnS2yaJnGeElTHKjTRt25vkMs/IKuMlFwXLePWWM7vAWQhK6CRm45T3+HqVq5WX"
    "3V7ZlKyLfEXykfv6WKtOm+ZbSYuK0NUSeGdMu/8yJNHxklRiaiDdBTrX9rWCx/eb7ceH+8e"
    "rRPY5DuOMJVHTHCX8tla73h4SKWf8WjoPbso/hTsXjOR87F9sBuc/DyqNdYEMrB2isVYHaVT"
    "d6ebxKom9EKQqzos+2N4p880GmZKYAzCKivsuiRW9kp4Mz4XEE8lmXJlR/EGbpOQcOyQbzWq"
    "rO29VHV5wIueMDS7HCKe8fIukM/JveKXNKrzFdFEeAhvi06vBo7ae+w67EaxqXjpllQN5hGa"
    "vcNCg6LseTx7omzCP09/Ds7IvOGFBjhEOutv3YZUhsDw1AK+4sJONn/KEP8/SKvIpLYYnRxbT"
    "elK11TuvjIMhurLsnvEMe+rbkIM2XlmjMBdvgkJQJughr7zOq7ATJD6qGhahotFZHD/g+EGb2"
    "iqQxsS1c2pzYll1Mjt5RJ/CRmpDKFQzOVV8uQ8qiIiHAScZp3EfHzD2WEQshAmPxulaN4Cip"
    "iqvaxgklBCbJOzg7nUCVyOmXoIU9MPg8B7dwGrcpwH8vKhlE7C36BOXtsHxaBSjG5wHvxAtO6"
    "US3nMozM5KQHHgZKABPc0jPrCB9IsoBnbSBLdR9aX68DKbbJgTkYtYn7WyWoVXugsPgzK4E+"
    "Tr4i0MXVLUswzpeQ/oEMALOGrbqlgEN4KCZqCVnZoESmA9h79Uobwk+WgaL/4pHEkof40SN6"
    "EpIs3cCVgY1WEztGTRdWMctuKkGHvzr//+LWBclCSj/x830eGZPHnd8vvwQvyvFsZCnhb+Cy"
    "Lb7nMKZW5kc3RyZWFtCmVuZG9iago1IDAgb2JqCjw8Ci9CYXNlRm9udCAvSGVsdmV0aWNhLUJv"
    "bGQKL0VuY29kaW5nIC9XaW5BbnNpRW5jb2RpbmcKL1N1YnR5cGUgL1R5cGUxCi9UeXBlIC9G"
    "b250Cj4+CmVuZG9iago2IDAgb2JqCjw8Ci9CYXNlRm9udCAvSGVsdmV0aWNhCi9FbmNvZGlu"
    "ZyAvV2luQW5zaUVuY29kaW5nCi9TdWJ0eXBlIC9UeXBlMQovVHlwZSAvRm9udAo+PgplbmRv"
    "YmoKNyAwIG9iago8PAovRm9udCA8PC9GMSA1IDAgUgovRjIgNiAwIFI+PgovUHJvY1NldCBb"
    "L1BERiAvVGV4dCAvSW1hZ2VCIC9JbWFnZUMgL0ltYWdlSV0KPj4KZW5kb2JqCjggMCBvYmoK"
    "PDwKL0NyZWF0aW9uRGF0ZSAoRDoyMDI2MDMwNDE5MTgwNVopCj4+CmVuZG9iagp4cmVmCjAg"
    "OQowMDAwMDAwMDAwIDY1NTM1IGYgCjAwMDAwMDAwMTUgMDAwMDAgbiAKMDAwMDAwMDEwMiAw"
    "MDAwMCBuIAowMDAwMDAwMjA1IDAwMDAwIG4gCjAwMDAwMDAyODUgMDAwMDAgbiAKMDAwMDAwMTI2"
    "NSAwMDAwMCBuIAowMDAwMDAxMzY3IDAwMDAwIG4gCjAwMDAwMDE0NjQgMDAwMDAgbiAKMDAwMDAw"
    "MTU2MSAwMDAwMCBuIAp0cmFpbGVyCjw8Ci9TaXplIDkKL1Jvb3QgMiAwIFIKL0luZm8gOCAw"
    "IFIKl0lEIFs8Q0IzOTk4QTRCQzQ3MDBFQkY2NEMwOEE3NDhEMkU0MjA+PENCMzk5OEE0QkM0"
    "NzAwRUJGNjRDMDhBNzQ4RDJFNDIwPl0KPj4Kc3RhcnR4cmVmCjE2MTYKJSVFT0YK"
)


def _file(filename: str, content_b64: str, mime_type: str) -> dict:
    """Build a file attachment dict matching the competition request format."""
    return {"filename": filename, "content_base64": content_b64, "mime_type": mime_type}


# ---------------------------------------------------------------------------
# Tier 1: Core task types — simple prompts, no attachments
# Source prompt hashes from GCS (verified 2026-03-21)
# ---------------------------------------------------------------------------

TIER1_REAL: list[E2ETestCase] = [

    # ---- create_invoice ----
    # [60f38c61] Nynorsk: 3 lines, different VAT rates
    E2ETestCase(
        name="real_create_invoice_nn_3lines",
        prompt=(
            "Opprett ein faktura til kunden B\u00f8lgekraft AS (org.nr 827304212) med tre "
            "produktlinjer: Webdesign (6744) til 27000 kr med 25\u00a0% MVA, Programvarelisens "
            "(2584) til 9300 kr med 15\u00a0% MVA (n\u00e6ringsmiddel), og Oppl\u00e6ring "
            "(3739) til 16300 kr med 0\u00a0% MVA (avgiftsfri)."
        ),
        expected_task_type="create_invoice",
        expected_fields={
            "customerName": "B\u00f8lgekraft AS",
            "customerOrgNumber": "827304212",
        },
        direct_fields={
            "customerName": "B\u00f8lgekraft AS",
            "customerOrgNumber": "827304212",
            "lines": [
                {"description": "Webdesign", "productNumber": "6744",
                 "quantity": 1, "unitPriceExcludingVat": 27000, "vatCode": "3"},
                {"description": "Programvarelisens", "productNumber": "2584",
                 "quantity": 1, "unitPriceExcludingVat": 9300, "vatCode": "33"},
                {"description": "Oppl\u00e6ring", "productNumber": "3739",
                 "quantity": 1, "unitPriceExcludingVat": 16300, "vatCode": "0"},
            ],
        },
        verify=VerifySpec(
            endpoint="/invoice",
            search_by_id=True,
            checks=[
                FieldCheck("id", 0, mode="gt"),
                FieldCheck("amountExcludingVatCurrency", 52600.0, mode="gte"),
            ],
        ),
        tier=1,
    ),

    # [bbc6b046] English: 3 lines
    E2ETestCase(
        name="real_create_invoice_en_3lines",
        prompt=(
            "Create an invoice for the customer Windmill Ltd (org no. 994973150) with three "
            "product lines: Consulting (5233) at 22500 NOK with 25% VAT, Software license "
            "(7612) at 8750 NOK with 0% VAT, and Training (4891) at 14200 NOK with 25% VAT."
        ),
        expected_task_type="create_invoice",
        expected_fields={"customerName": "Windmill Ltd"},
        direct_fields={
            "customerName": "Windmill Ltd",
            "customerOrgNumber": "994973150",
            "lines": [
                {"description": "Consulting", "productNumber": "5233",
                 "quantity": 1, "unitPriceExcludingVat": 22500, "vatCode": "3"},
                {"description": "Software license", "productNumber": "7612",
                 "quantity": 1, "unitPriceExcludingVat": 8750, "vatCode": "0"},
                {"description": "Training", "productNumber": "4891",
                 "quantity": 1, "unitPriceExcludingVat": 14200, "vatCode": "3"},
            ],
        },
        verify=VerifySpec(
            endpoint="/invoice",
            search_by_id=True,
            checks=[FieldCheck("id", 0, mode="gt")],
        ),
        tier=1,
    ),

    # ---- create_customer ----
    # [d94f5d05] Spanish: customer with address
    E2ETestCase(
        name="real_create_customer_es",
        prompt=(
            "Crea el cliente Monta\u00f1a SL con n\u00famero de organizaci\u00f3n 957430201. "
            "La direcci\u00f3n es Nygata 24, 3015 Drammen. Correo: post@montana.no."
        ),
        expected_task_type="create_customer",
        expected_fields={
            "name": "Monta\u00f1a SL",
            "organizationNumber": "957430201",
        },
        direct_fields={
            "name": "Monta\u00f1a SL",
            "organizationNumber": "957430201",
            "email": "post@montana.no",
            "invoiceEmail": "post@montana.no",
            "address": {"addressLine1": "Nygata 24", "postalCode": "3015", "city": "Drammen"},
        },
        verify=VerifySpec(
            endpoint="/customer",
            search_params={"organizationNumber": "957430201"},
            checks=[
                FieldCheck("name", "Monta\u00f1a SL"),
                FieldCheck("organizationNumber", "957430201"),
                FieldCheck("email", "post@montana.no"),
            ],
        ),
        tier=1,
    ),

    # ---- create_supplier ----
    # [83bddf3b] Norwegian: supplier with email
    E2ETestCase(
        name="real_create_supplier_nb",
        prompt=(
            "Registrer leverand\u00f8ren Brattli AS med organisasjonsnummer 950029978. "
            "E-post: faktura@brattli.no."
        ),
        expected_task_type="create_supplier",
        expected_fields={
            "name": "Brattli AS",
            "organizationNumber": "950029978",
        },
        direct_fields={
            "name": "Brattli AS",
            "organizationNumber": "950029978",
            "email": "faktura@brattli.no",
        },
        verify=VerifySpec(
            endpoint="/supplier",
            search_params={"organizationNumber": "950029978"},
            checks=[
                FieldCheck("name", "Brattli AS"),
                FieldCheck("organizationNumber", "950029978"),
                FieldCheck("email", "faktura@brattli.no"),
            ],
        ),
        tier=1,
    ),

    # ---- create_product ----
    # [aa154ce1] French: product with VAT
    E2ETestCase(
        name="real_create_product_fr",
        prompt=(
            "Cr\u00e9ez le produit \"Stockage cloud\" avec le num\u00e9ro de produit 9433. "
            "Le prix est de 7550 NOK hors TVA, avec le taux standard de 25\u00a0%."
        ),
        expected_task_type="create_product",
        expected_fields={
            "name": "Stockage cloud",
            "number": "9433",
            "priceExcludingVat": 7550,
        },
        direct_fields={
            "name": "Stockage cloud",
            "number": "9433",
            "priceExcludingVat": 7550,
            "vatCode": "3",
        },
        verify=None,
        tier=1,
    ),

    # ---- create_project ----
    # [e1c1a84d] Spanish: project with customer + project manager
    E2ETestCase(
        name="real_create_project_es",
        prompt=(
            "Crea el proyecto \"Migraci\u00f3n Viento\" vinculado al cliente Viento SL "
            "(org. n\u00ba 857047575). El director del proyecto es Carlos Romero "
            "(carlos.romero@example.org)."
        ),
        expected_task_type="create_project",
        expected_fields={
            "name": "Migraci\u00f3n Viento",
            "customerOrgNumber": "857047575",
        },
        direct_fields={
            "name": "Migraci\u00f3n Viento",
            "customerName": "Viento SL",
            "customerOrgNumber": "857047575",
            "projectManagerName": "Carlos Romero",
        },
        verify=VerifySpec(
            endpoint="/project",
            search_params={"name": "Migraci\u00f3n Viento"},
            checks=[FieldCheck("name", "Migraci\u00f3n Viento")],
        ),
        tier=1,
    ),

    # ---- create_employee ----
    # [dcf5dede] French: simple employee creation
    E2ETestCase(
        name="real_create_employee_fr",
        prompt=(
            "Nous avons un nouvel employ\u00e9 nomm\u00e9 Jules Richard, n\u00e9 le "
            "2. August 1986. Veuillez le cr\u00e9er en tant qu'employ\u00e9 avec "
            "l'e-mail jules.richard@example.org et la date de d\u00e9but 28. July 2026."
        ),
        expected_task_type="create_employee",
        expected_fields={
            "firstName": "Jules",
            "lastName": "Richard",
            "email": "jules.richard@example.org",
        },
        direct_fields={
            "firstName": "Jules",
            "lastName": "Richard",
            "dateOfBirth": "1986-08-02",
            "email": "jules.richard@example.org",
            "startDate": "2026-07-28",
        },
        verify=VerifySpec(
            endpoint="/employee",
            search_by_id=True,
            checks=[
                FieldCheck("firstName", "Jules"),
                FieldCheck("lastName", "Richard"),
            ],
        ),
        tier=1,
    ),

    # ---- register_supplier_invoice (text-only) ----
    # [fcf8c4f1] Nynorsk: invoice with known supplier + account
    E2ETestCase(
        name="real_register_supplier_invoice_nn",
        prompt=(
            "Me har motteke faktura INV-2026-9559 fr\u00e5 leverand\u00f8ren Elvdal AS "
            "(org.nr 935041740) p\u00e5 36600 kr inklusiv MVA. Bel\u00f8pet gjeld "
            "kontortenester (konto 7100). Registrer leverand\u00f8rfakturaen med korrekt "
            "inng\u00e5ande MVA (25\u00a0%)."
        ),
        expected_task_type="register_supplier_invoice",
        expected_fields={
            "supplierName": "Elvdal AS",
            "supplierOrgNumber": "935041740",
            "amount": 36600,
        },
        direct_fields={
            "supplierName": "Elvdal AS",
            "supplierOrgNumber": "935041740",
            "amount": 36600,
            "description": "kontortenester",
            "expenseAccount": 7100,
            "invoiceNumber": "INV-2026-9559",
            "vatRate": 25,
        },
        verify=VerifySpec(
            endpoint="/supplierInvoice",
            search_by_id=True,
            checks=[FieldCheck("id", 0, mode="gt")],
        ),
        tier=1,
    ),

    # ---- register_payment ----
    # [a686664b] Portuguese: pay open invoice in full
    E2ETestCase(
        name="real_register_payment_pt",
        prompt=(
            "O cliente Rio Azul Lda (org. n\u00ba 932217643) tem uma fatura pendente de "
            "44100 NOK sem IVA por \"Sess\u00e3o de forma\u00e7\u00e3o\". Registe o "
            "pagamento total desta fatura."
        ),
        expected_task_type="register_payment",
        expected_fields={
            "customerName": "Rio Azul Lda",
            "amount": 44100,
        },
        direct_fields={
            "customerName": "Rio Azul Lda",
            "customerOrgNumber": "932217643",
            "amount": 44100,
            "invoiceDescription": "Sess\u00e3o de forma\u00e7\u00e3o",
            "lines": [
                {"description": "Sess\u00e3o de forma\u00e7\u00e3o",
                 "quantity": 1, "unitPriceExcludingVat": 44100, "vatCode": "3"},
            ],
        },
        verify=VerifySpec(
            endpoint="/invoice",
            search_by_id=True,
            checks=[FieldCheck("amountCurrencyOutstanding", 0.0)],
        ),
        tier=1,
    ),

    # ---- reverse_payment ----
    # [d0ac3f91] German: reverse a returned payment
    E2ETestCase(
        name="real_reverse_payment_de",
        prompt=(
            "Die Zahlung von Windkraft GmbH (Org.-Nr. 823566441) f\u00fcr die Rechnung "
            "\"Wartung\" (29500 NOK ohne MwSt.) wurde von der Bank zur\u00fcckgebucht. "
            "Stornieren Sie die Zahlung, damit die Rechnung wieder den offenen Betrag "
            "anzeigt."
        ),
        expected_task_type="reverse_payment",
        expected_fields={
            "customerName": "Windkraft GmbH",
            "amount": 29500,
        },
        direct_fields={
            "customerName": "Windkraft GmbH",
            "customerOrgNumber": "823566441",
            "invoiceDescription": "Wartung",
            "amount": 29500,
            "lines": [
                {"description": "Wartung", "quantity": 1,
                 "unitPriceExcludingVat": 29500, "vatCode": "3"},
            ],
        },
        verify=VerifySpec(
            endpoint="/invoice",
            search_by_id=True,
            checks=[FieldCheck("amountCurrencyOutstanding", 36875.0, mode="gt")],
        ),
        tier=1,
    ),

    # ---- create_credit_note ----
    # [3e505f39] Spanish: full credit note
    E2ETestCase(
        name="real_create_credit_note_es",
        prompt=(
            "El cliente Viento SL (org. n\u00ba 857019199) ha reclamado sobre la factura "
            "por \"Informe de an\u00e1lisis\" (27200 NOK sin IVA). Emita una nota de "
            "cr\u00e9dito completa que revierta toda la factura."
        ),
        expected_task_type="create_credit_note",
        expected_fields={
            "customerName": "Viento SL",
            "amount": 27200,
        },
        direct_fields={
            "customerName": "Viento SL",
            "customerOrgNumber": "857019199",
            "invoiceDescription": "Informe de an\u00e1lisis",
            "amount": 27200,
            "lines": [
                {"description": "Informe de an\u00e1lisis", "quantity": 1,
                 "unitPriceExcludingVat": 27200, "vatCode": "3"},
            ],
        },
        verify=VerifySpec(
            endpoint="/invoice",
            search_by_id=True,
            checks=[FieldCheck("id", 0, mode="gt")],
        ),
        tier=1,
    ),

    # ---- create_travel_expense ----
    # [928e4c16] Portuguese: 3-day travel with per diem + flight + taxi
    E2ETestCase(
        name="real_create_travel_expense_pt",
        prompt=(
            "Registe uma despesa de viagem para Bruno Silva (bruno.silva@example.org) "
            "referente a \"Confer\u00eancia Bod\u00f8\". A viagem durou 3 dias com "
            "ajudas de custo (taxa di\u00e1ria 800 NOK). Despesas: bilhete de avi\u00e3o "
            "4900 NOK e t\u00e1xi 450 NOK."
        ),
        expected_task_type="create_travel_expense",
        expected_fields={
            "employeeName": "Bruno Silva",
            "employeeEmail": "bruno.silva@example.org",
        },
        direct_fields={
            "employeeName": "Bruno Silva",
            "employeeEmail": "bruno.silva@example.org",
            "title": "Confer\u00eancia Bod\u00f8",
            "destination": "Bod\u00f8",
            "costs": [
                {"description": "Per diem (3 days)", "amount": 2400, "currency": "NOK"},
                {"description": "Bilhete de avi\u00e3o", "amount": 4900, "currency": "NOK"},
                {"description": "T\u00e1xi", "amount": 450, "currency": "NOK"},
            ],
        },
        verify=None,
        tier=1,
    ),

    # ---- run_payroll ----
    # [e9172245] Portuguese: base salary + bonus
    E2ETestCase(
        name="real_run_payroll_pt",
        prompt=(
            "Processe o sal\u00e1rio de Beatriz Pereira (beatriz.pereira@example.org) "
            "para este m\u00eas. O sal\u00e1rio base \u00e9 de 58650 NOK. Adicione um "
            "b\u00f3nus \u00fanico de 8850 NOK al\u00e9m do sal\u00e1rio base."
        ),
        expected_task_type="run_payroll",
        expected_fields={
            "employeeEmail": "beatriz.pereira@example.org",
            "baseSalary": 58650,
            "bonus": 8850,
        },
        direct_fields={
            "employeeName": "Beatriz Pereira",
            "employeeEmail": "beatriz.pereira@example.org",
            "baseSalary": 58650,
            "bonus": 8850,
        },
        setup="find_first_employee",
        verify=None,
        tier=1,
    ),

    # ---- batch_create_department ----
    # [ac9adc6f] Spanish: batch 3 departments
    E2ETestCase(
        name="real_batch_create_department_es",
        prompt=(
            "Crea tres departamentos en Tripletex: \"Drift\", \"Administrasjon\" y \"Lager\"."
        ),
        expected_task_type="batch_create_department",
        expected_fields={},
        direct_fields={
            "items": [
                {"taskType": "create_department", "fields": {"name": "Drift"}},
                {"taskType": "create_department", "fields": {"name": "Administrasjon"}},
                {"taskType": "create_department", "fields": {"name": "Lager"}},
            ],
        },
        verify=None,
        tier=1,
    ),

    # ---- register_timesheet ----
    # [29b94909] English: log hours + generate invoice
    E2ETestCase(
        name="real_register_timesheet_en",
        prompt=(
            "Log 5 hours for Emily Johnson (emily.johnson@example.org) on the activity "
            "\"Utvikling\" in the project \"Security Audit\" for Clearwater Ltd "
            "(org no. 874828955). Hourly rate: 1600 NOK/h. Generate a project invoice "
            "to the customer based on the logged hours."
        ),
        expected_task_type="register_timesheet",
        expected_fields={
            "employeeEmail": "emily.johnson@example.org",
            "hours": 5,
        },
        direct_fields={
            "employeeName": "Emily Johnson",
            "employeeEmail": "emily.johnson@example.org",
            "activityName": "Utvikling",
            "projectName": "Security Audit",
            "hours": 5,
            "hourlyRate": 1600,
            "customerName": "Clearwater Ltd",
            "customerOrgNumber": "874828955",
        },
        setup="find_first_employee",
        verify=VerifySpec(
            endpoint="/timesheet/entry",
            search_by_id=True,
            checks=[FieldCheck("hours", 5.0)],
        ),
        tier=1,
    ),
]


# ---------------------------------------------------------------------------
# Tier 2: More complex real prompts
# ---------------------------------------------------------------------------

TIER2_REAL: list[E2ETestCase] = [

    # ---- set_project_fixed_price ----
    # [83ed9c68] French: set fixed price + invoice 25%
    E2ETestCase(
        name="real_set_project_fixed_price_fr",
        prompt=(
            "Fixez un prix forfaitaire de 125550 NOK sur le projet "
            "\"Mise \u00e0 niveau infrastructure\" pour Soleil SARL (n\u00ba org. 931336738). "
            "Le chef de projet est Nathan Thomas (nathan.thomas@example.org). "
            "Facturez au client 25\u00a0% du prix fixe comme paiement d'\u00e9tape."
        ),
        expected_task_type="set_project_fixed_price",
        expected_fields={
            "projectName": "Mise \u00e0 niveau infrastructure",
            "fixedPrice": 125550,
        },
        direct_fields={
            "projectName": "Mise \u00e0 niveau infrastructure",
            "customerName": "Soleil SARL",
            "customerOrgNumber": "931336738",
            "fixedPrice": 125550,
            "projectManagerName": "Nathan Thomas",
            "invoicePercentage": 25,
        },
        verify=VerifySpec(
            endpoint="/project",
            search_by_id=True,
            checks=[
                FieldCheck("name", "Mise \u00e0 niveau infrastructure"),
                FieldCheck("isFixedPrice", True),
            ],
        ),
        tier=2,
    ),

    # [0af6ec2c] English: set fixed price 50%
    E2ETestCase(
        name="real_set_project_fixed_price_en",
        prompt=(
            "Set a fixed price of 498050 NOK on the project \"CRM Integration\" "
            "for Ridgepoint Ltd (org no. 844419856). The project manager is "
            "George Walker (george.walker@example.org). Invoice 50% of the fixed "
            "price as a milestone payment."
        ),
        expected_task_type="set_project_fixed_price",
        expected_fields={
            "projectName": "CRM Integration",
            "fixedPrice": 498050,
        },
        direct_fields={
            "projectName": "CRM Integration",
            "customerName": "Ridgepoint Ltd",
            "customerOrgNumber": "844419856",
            "fixedPrice": 498050,
            "projectManagerName": "George Walker",
            "invoicePercentage": 50,
        },
        verify=VerifySpec(
            endpoint="/project",
            search_by_id=True,
            checks=[
                FieldCheck("name", "CRM Integration"),
                FieldCheck("isFixedPrice", True),
            ],
        ),
        tier=2,
    ),

    # ---- create_custom_dimension ----
    # [b7086bca] French: dimension + voucher linked to value
    E2ETestCase(
        name="real_create_custom_dimension_fr",
        prompt=(
            "Cr\u00e9ez une dimension comptable personnalis\u00e9e \"Kostsenter\" avec "
            "les valeurs \"Produktutvikling\" et \"Salg\". Puis comptabilisez une pi\u00e8ce "
            "sur le compte 7300 pour 37450 NOK, li\u00e9e \u00e0 la valeur de dimension "
            "\"Salg\"."
        ),
        expected_task_type="create_custom_dimension",
        expected_fields={
            "dimensionName": "Kostsenter",
            "values": ["Produktutvikling", "Salg"],
        },
        direct_fields={
            "dimensionName": "Kostsenter",
            "values": ["Produktutvikling", "Salg"],
            "voucherDate": "2026-03-21",
            "voucherDescription": "Voucher linked to dimension Salg",
            "accountNumber": 7300,
            "amount": 37450,
            "dimensionValue": "Salg",
        },
        setup="find_or_reuse_dimension",
        verify=None,
        tier=2,
    ),

    # ---- batch_create_order ----
    # [4a7f17b2] English: order -> invoice -> payment
    E2ETestCase(
        name="real_batch_create_order_en",
        prompt=(
            "Create an order for the customer Ridgepoint Ltd (org no. 925103489) with "
            "the products Consulting Hours (5359) at 21150 NOK and Analysis Report (1028) "
            "at 1600 NOK. Convert the order to an invoice and register full payment."
        ),
        expected_task_type="batch_create_order",
        expected_fields={},
        direct_fields={
            "items": [
                {
                    "taskType": "create_order",
                    "fields": {
                        "customerName": "Ridgepoint Ltd",
                        "customerOrgNumber": "925103489",
                        "lines": [
                            {"description": "Consulting Hours", "productNumber": "5359",
                             "quantity": 1, "unitPriceExcludingVat": 21150},
                            {"description": "Analysis Report", "productNumber": "1028",
                             "quantity": 1, "unitPriceExcludingVat": 1600},
                        ],
                    },
                },
            ],
        },
        verify=None,
        tier=2,
    ),

    # ---- batch_register_timesheet ----
    # [802d35fb] Portuguese: register timesheet + invoice
    E2ETestCase(
        name="real_batch_register_timesheet_pt",
        prompt=(
            "Registe 11 horas para In\u00eas Rodrigues (ines.rodrigues@example.org) na "
            "atividade \"Design\" do projeto \"Redesign do site\" para Estrela Lda "
            "(org. n\u00ba 930325325). Taxa hor\u00e1ria: 1000 NOK/h. Gere uma fatura de "
            "projeto ao cliente com base nas horas registadas."
        ),
        expected_task_type="batch_register_timesheet",
        expected_fields={},
        direct_fields={
            "items": [
                {
                    "taskType": "register_timesheet",
                    "fields": {
                        "employeeName": "In\u00eas Rodrigues",
                        "employeeEmail": "ines.rodrigues@example.org",
                        "activityName": "Design",
                        "projectName": "Redesign do site",
                        "hours": 11,
                        "hourlyRate": 1000,
                        "customerName": "Estrela Lda",
                        "customerOrgNumber": "930325325",
                    },
                },
            ],
        },
        setup="find_first_employee",
        verify=None,
        tier=2,
    ),

    # ---- batch_register_timesheet variant ----
    # [aaac3752] Norwegian: multi-day batch with invoice
    E2ETestCase(
        name="real_batch_register_timesheet_nb",
        prompt=(
            "Registrer 24 timer for Solveig Hansen (solveig.hansen@example.org) p\u00e5 "
            "aktivitetene \"Analyse\" og \"Design\" i prosjektet \"Nettstedoppgradering\" "
            "for Tinden AS (org.nr 853166553). Timepris: 1350 NOK/t. Generer en "
            "prosjektfaktura til kunden basert p\u00e5 registrerte timer."
        ),
        expected_task_type="batch_register_timesheet",
        expected_fields={},
        direct_fields={
            "items": [
                {
                    "taskType": "register_timesheet",
                    "fields": {
                        "employeeName": "Solveig Hansen",
                        "employeeEmail": "solveig.hansen@example.org",
                        "activityName": "Analyse",
                        "projectName": "Nettstedoppgradering",
                        "hours": 12,
                        "hourlyRate": 1350,
                        "customerName": "Tinden AS",
                        "customerOrgNumber": "853166553",
                    },
                },
            ],
        },
        setup="find_first_employee",
        verify=None,
        tier=2,
    ),
]


# ---------------------------------------------------------------------------
# Tier 3: Complex tasks — attachments, multi-step, Tier 3 handlers
# ---------------------------------------------------------------------------

TIER3_REAL: list[E2ETestCase] = [

    # ---- bank_reconciliation with real CSV ----
    # [f550afbd] French: reconcile bank statement CSV
    E2ETestCase(
        name="real_bank_reconciliation_fr_csv",
        prompt=(
            "Rapprochez le releve bancaire (CSV ci-joint) avec les factures ouvertes "
            "dans Tripletex. Associez les paiements entrants aux factures clients et les "
            "paiements sortants aux factures fournisseurs. Gerez correctement les "
            "paiements partiels."
        ),
        expected_task_type="bank_reconciliation",
        expected_fields={
            "accountNumber": 1920,
            "dateFrom": "2026-01-17",
            "dateTo": "2026-02-05",
        },
        direct_fields={
            "accountNumber": 1920,
            "dateFrom": "2026-01-17",
            "dateTo": "2026-02-05",
            "attachmentContent": _BANK_CSV_FR_B64,
            "attachmentName": "bankutskrift_fr_08.csv",
        },
        setup="find_bank_account",
        verify=None,  # custom: reconciliationId in result
        tier=3,
    ),

    # [be39269a] Norwegian: reconcile bank statement CSV
    E2ETestCase(
        name="real_bank_reconciliation_nb_csv",
        prompt=(
            "Avstem bankutskriften (vedlagt CSV) mot apne fakturaer i Tripletex. Match "
            "innbetalinger til kundefakturaer og utbetalinger til leverandorfakturaer. "
            "Handter delbetalinger korrekt."
        ),
        expected_task_type="bank_reconciliation",
        expected_fields={
            "accountNumber": 1920,
        },
        direct_fields={
            "accountNumber": 1920,
            "dateFrom": "2026-01-17",
            "dateTo": "2026-02-07",
            "attachmentContent": _BANK_CSV_NB_B64,
            "attachmentName": "bankutskrift_nb_07.csv",
        },
        setup="find_bank_account",
        verify=None,
        tier=3,
    ),

    # ---- register_supplier_invoice with PDF ----
    # [9c942d38] German: supplier invoice PDF
    E2ETestCase(
        name="real_register_supplier_invoice_de_pdf",
        prompt=(
            "Sie haben eine Lieferantenrechnung erhalten (siehe beigefugte PDF). "
            "Registrieren Sie die Rechnung in Tripletex. Erstellen Sie den Lieferanten, "
            "falls er nicht existiert. Verwenden Sie das richtige Aufwandskonto und "
            "die Vorsteuer."
        ),
        expected_task_type="register_supplier_invoice",
        expected_fields={
            "supplierName": "Nordlicht GmbH",
            "supplierOrgNumber": "871162069",
            "amount": 44562,
        },
        direct_fields={
            "supplierName": "Nordlicht GmbH",
            "supplierOrgNumber": "871162069",
            "amount": 44562,
            "amountExcludingVat": 35650,
            "description": "Nettverkstjenester",
            "invoiceDate": "2026-04-06",
            "invoiceNumber": "INV-2026-7611",
            "vatRate": 25,
            "vatCode": "11",
            "expenseAccount": 6300,
        },
        verify=VerifySpec(
            endpoint="/supplierInvoice",
            search_by_id=True,
            checks=[FieldCheck("id", 0, mode="gt")],
        ),
        tier=3,
    ),

    # [c5aa9f43] Nynorsk: supplier invoice PDF
    E2ETestCase(
        name="real_register_supplier_invoice_nn_pdf",
        prompt=(
            "Du har motteke ein leverandorfaktura (sjaa vedlagt PDF). Registrer fakturaen "
            "i Tripletex. Opprett leverandoren viss den ikkje finst. Bruk rett utgiftskonto "
            "og inngaaande MVA."
        ),
        expected_task_type="register_supplier_invoice",
        expected_fields={
            "supplierName": "Elvdal AS",
            "supplierOrgNumber": "917822778",
            "amount": 31187,
        },
        direct_fields={
            "supplierName": "Elvdal AS",
            "supplierOrgNumber": "917822778",
            "amount": 31187,
            "amountExcludingVat": 24950,
            "description": "IT-konsulenttjenester",
            "invoiceDate": "2026-04-01",
            "invoiceNumber": "INV-2026-6601",
            "vatRate": 25,
            "vatCode": "11",
            "expenseAccount": 6300,
        },
        verify=VerifySpec(
            endpoint="/supplierInvoice",
            search_by_id=True,
            checks=[FieldCheck("id", 0, mode="gt")],
        ),
        tier=3,
    ),

    # ---- create_employee with PDF ----
    # [66bf0b67] Spanish: onboarding from offer letter PDF
    E2ETestCase(
        name="real_create_employee_es_pdf",
        prompt=(
            "Has recibido una carta de oferta (ver PDF adjunto) para un nuevo empleado. "
            "Completa la incorporacion: crea el empleado, asigna el departamento correcto, "
            "configura los detalles de empleo con porcentaje y salario anual, y configura "
            "las horas de trabajo estandar."
        ),
        expected_task_type="create_employee",
        expected_fields={
            "firstName": "Javier",
            "lastName": "Garc\u00eda",
            "dateOfBirth": "1991-11-14",
        },
        direct_fields={
            "firstName": "Javier",
            "lastName": "Garc\u00eda",
            "dateOfBirth": "1991-11-14",
            "startDate": "2026-08-23",
            "role": "HR-r\u00e5dgiver",
            "department": "Kundeservice",
            "employmentPercentage": 100,
            "annualSalary": 530000,
            "hoursPerDay": 7.5,
        },
        verify=VerifySpec(
            endpoint="/employee",
            search_by_id=True,
            checks=[
                FieldCheck("firstName", "Javier"),
                FieldCheck("lastName", "Garc\u00eda"),
            ],
        ),
        tier=3,
    ),

    # [62b909d4] Nynorsk: onboarding from employment contract PDF
    E2ETestCase(
        name="real_create_employee_nn_pdf",
        prompt=(
            "Du har motteke ein arbeidskontrakt (sjaa vedlagt PDF). Opprett den tilsette "
            "i Tripletex med alle detaljar fraa kontrakten: personnummer, fodselsdato, "
            "avdeling, stillingskode, lonn, stillingsprosent og startdato."
        ),
        expected_task_type="create_employee",
        expected_fields={
            "firstName": "Liv",
            "lastName": "St\u00f8lsvik",
            "nationalIdentityNumber": "09108520520",
        },
        direct_fields={
            "firstName": "Liv",
            "lastName": "St\u00f8lsvik",
            "email": "liv.stlsvik@example.org",
            "dateOfBirth": "1985-10-09",
            "startDate": "2026-11-10",
            "nationalIdentityNumber": "09108520520",
            "bankAccountNumber": "73262851327",
            "department": "Innkj\u00f8p",
            "occupationCode": "1211",
            "employmentPercentage": 100,
            "annualSalary": 630000,
        },
        verify=VerifySpec(
            endpoint="/employee",
            search_by_id=True,
            checks=[
                FieldCheck("firstName", "Liv"),
                FieldCheck("lastName", "St\u00f8lsvik"),
            ],
        ),
        tier=3,
    ),

    # ---- correct_ledger_error ----
    # [67dbf77a] English: 4 error types in general ledger
    E2ETestCase(
        name="real_correct_ledger_error_en_4errors",
        prompt=(
            "We have discovered errors in the general ledger for January and February 2026. "
            "Review all vouchers and find the 4 errors: a posting to the wrong account "
            "(account 6540 used instead of 6860, amount 4800 NOK), a duplicate voucher "
            "(account 6500, amount 1050 NOK), a missing VAT line (account 7000, amount "
            "excl. 6750 NOK missing VAT on account 2710), and an incorrect amount "
            "(account 6500, 15700 NOK posted instead of 8100 NOK). Correct all errors "
            "with appropriate correction vouchers."
        ),
        expected_task_type="correct_ledger_error",
        expected_fields={
            "errors": [
                {"errorType": "wrong_account", "wrongAccount": 6540,
                 "correctAccount": 6860, "amount": 4800},
                {"errorType": "duplicate", "account": 6500, "amount": 1050},
                {"errorType": "missing_vat", "account": 7000,
                 "amount": 6750, "vatAccount": 2710},
                {"errorType": "wrong_amount", "account": 6500,
                 "amount": 15700, "correctAmount": 8100},
            ],
        },
        direct_fields={
            "errors": [
                {"errorType": "wrong_account", "wrongAccount": 6540,
                 "correctAccount": 6860, "amount": 4800, "date": "2026-03-21"},
                {"errorType": "duplicate", "account": 6500,
                 "amount": 1050, "date": "2026-03-21"},
                {"errorType": "missing_vat", "account": 7000, "amount": 6750,
                 "vatAccount": 2710, "date": "2026-03-21"},
                {"errorType": "wrong_amount", "account": 6500,
                 "amount": 15700, "correctAmount": 8100, "date": "2026-03-21"},
            ],
            "date": "2026-03-21",
        },
        setup="create_vouchers_for_multi_correction",
        verify=VerifySpec(
            endpoint="/ledger/voucher",
            search_by_id=True,
            checks=[FieldCheck("id", 0, mode="gt")],
        ),
        tier=3,
    ),

    # [85e17021] Nynorsk: 4 error types (different accounts)
    E2ETestCase(
        name="real_correct_ledger_error_nn_4errors",
        prompt=(
            "Me har oppdaga feil i hovudboka for januar og februar 2026. G\u00e5 gjennom "
            "alle bilag og finn dei 4 feila: ei postering p\u00e5 feil konto (konto 7140 "
            "brukt i staden for 7100, bel\u00f8p 2950 kr), eit duplikat bilag (konto 7300, "
            "bel\u00f8p 2800 kr), ei manglande MVA-linje (konto 4500, bel\u00f8p ekskl. "
            "21250 kr manglar MVA p\u00e5 konto 2710), og eit feil bel\u00f8p (konto 7100, "
            "23300 kr bokf\u00f8rt i staden for 19100 kr). Korriger alle feil med rette "
            "bilag."
        ),
        expected_task_type="correct_ledger_error",
        expected_fields={
            "errors": [
                {"errorType": "wrong_account", "wrongAccount": 7140,
                 "correctAccount": 7100, "amount": 2950},
                {"errorType": "duplicate", "account": 7300, "amount": 2800},
            ],
        },
        direct_fields={
            "errors": [
                {"errorType": "wrong_account", "wrongAccount": 7140,
                 "correctAccount": 7100, "amount": 2950, "date": "2026-03-21"},
                {"errorType": "duplicate", "account": 7300,
                 "amount": 2800, "date": "2026-03-21"},
                {"errorType": "missing_vat", "account": 7000, "amount": 21250,
                 "vatAccount": 2710, "date": "2026-03-21"},
                {"errorType": "wrong_amount", "account": 7100,
                 "amount": 23300, "correctAmount": 19100, "date": "2026-03-21"},
            ],
            "date": "2026-03-21",
        },
        setup="create_vouchers_for_multi_correction",
        verify=VerifySpec(
            endpoint="/ledger/voucher",
            search_by_id=True,
            checks=[FieldCheck("id", 0, mode="gt")],
        ),
        tier=3,
    ),

    # ---- monthly_closing ----
    # [d7418947] French: accrual + depreciation + provision
    E2ETestCase(
        name="real_monthly_closing_fr",
        prompt=(
            "Effectuez la cl\u00f4ture mensuelle de mars 2026. Comptabilisez la "
            "r\u00e9gularisation (13600 NOK par mois du compte 1700 vers charges). "
            "Enregistrez l'amortissement mensuel d'une immobilisation avec un co\u00fbt "
            "d'acquisition de 262850 NOK et une dur\u00e9e de vie utile de 10 ans "
            "(amortissement lin\u00e9aire sur compte 6030). V\u00e9rifiez que la balance "
            "est \u00e0 z\u00e9ro. Comptabilisez \u00e9galement une provision pour "
            "salaires (d\u00e9bit compte de charges salariales 5000, cr\u00e9dit compte "
            "de salaires \u00e0 payer 2900)."
        ),
        expected_task_type="monthly_closing",
        expected_fields={
            "month": 3,
            "year": 2026,
        },
        direct_fields={
            "month": 3,
            "year": 2026,
            "accruals": [
                {"fromAccount": 1700, "toAccount": 6300,
                 "amount": 13600, "description": "R\u00e9gularisation charges mars 2026"},
            ],
            "depreciations": [
                {"account": 6030, "assetAccount": 1200, "acquisitionCost": 262850,
                 "usefulLifeYears": 10, "description": "Amortissement immobilisation mars 2026"},
            ],
            "provisions": [
                {"debitAccount": 5000, "creditAccount": 2900,
                 "amount": 35000, "description": "Provision pour salaires mars 2026"},
            ],
        },
        verify=None,
        tier=3,
    ),

    # [4327f043] German: monthly closing
    E2ETestCase(
        name="real_monthly_closing_de",
        prompt=(
            "F\u00fchren Sie den Monatsabschluss f\u00fcr M\u00e4rz 2026 durch. "
            "Buchen Sie die Rechnungsabgrenzung (3400 NOK pro Monat von Konto 1700 "
            "zu Aufwandskonto). Erfassen Sie die monatliche Abschreibung f\u00fcr "
            "Anlageverm\u00f6gen mit Anschaffungskosten 289700 NOK und Nutzungsdauer "
            "7 Jahre (linear auf Konto 6020). Stellen Sie auch eine Lohnr\u00fcckstellung "
            "ein (Soll 5000, Haben 2900)."
        ),
        expected_task_type="monthly_closing",
        expected_fields={
            "month": 3,
            "year": 2026,
        },
        direct_fields={
            "month": 3,
            "year": 2026,
            "accruals": [
                {"fromAccount": 1700, "toAccount": 6300,
                 "amount": 3400, "description": "Rechnungsabgrenzung M\u00e4rz 2026"},
            ],
            "depreciations": [
                {"account": 6020, "assetAccount": 1200, "acquisitionCost": 289700,
                 "usefulLifeYears": 7, "description": "Abschreibung Anlage M\u00e4rz 2026"},
            ],
            "provisions": [
                {"debitAccount": 5000, "creditAccount": 2900,
                 "amount": 42000, "description": "Lohnr\u00fcckstellung M\u00e4rz 2026"},
            ],
        },
        verify=None,
        tier=3,
    ),

    # ---- year_end_closing ----
    # [5861be39] Spanish: simplified year-end with 3 asset depreciations
    E2ETestCase(
        name="real_year_end_closing_es",
        prompt=(
            "Realice el cierre anual simplificado de 2025: 1) Calcule y contabilice la "
            "depreciaci\u00f3n anual de tres activos: Kj\u00f8ret\u00f8y (249600 NOK, "
            "10 a\u00f1os lineales, cuenta 1230), IT-utstyr (292050 NOK, 9 a\u00f1os, "
            "cuenta 1210), Kontormaskiner (354500 NOK, 7 a\u00f1os, cuenta 1200). Use "
            "cuenta 6010 para gasto de depreciaci\u00f3n y 1209 para depreciaci\u00f3n "
            "acumulada. 2) Revierta gastos prepagados (total 45950 NOK en cuenta 1700). "
            "3) Calcule y contabilice la provisi\u00f3n de impuestos (22\u00a0% del "
            "resultado imponible) en cuenta 8700/2920. Registre cada depreciaci\u00f3n "
            "como un comprobante separado."
        ),
        expected_task_type="year_end_closing",
        expected_fields={"year": 2025},
        direct_fields={
            "year": 2025,
            "createOpeningBalance": True,
        },
        verify=None,
        tier=3,
    ),
]


# ---------------------------------------------------------------------------
# Combined test list
# ---------------------------------------------------------------------------

ALL_REAL_TESTS: list[E2ETestCase] = TIER1_REAL + TIER2_REAL + TIER3_REAL


# ---------------------------------------------------------------------------
# Runner — reuses test_e2e run_test logic
# ---------------------------------------------------------------------------

async def run_real_prompt_tests(
    tier: int | None,
    only: set[str] | None,
    verbose: bool,
    base_url: str,
    session_token: str,
) -> tuple[int, int]:
    """Run the real-prompt regression suite. Returns (passed, failed)."""
    from scripts.test_e2e import TripletexClient, run_test

    client = TripletexClient(base_url=base_url, session_token=session_token)

    tests = ALL_REAL_TESTS
    if tier is not None:
        tests = [t for t in tests if t.tier == tier]
    if only:
        tests = [t for t in tests if t.expected_task_type in only or t.name in only]

    passed = 0
    failed = 0
    skipped = 0

    print(f"\n{bold('Real Competition Prompt Regression Suite')}")
    print(f"Running {len(tests)} tests (tier={tier or 'all'}, filter={only or 'none'})")
    print("=" * 70)

    for test in tests:
        result = await run_test(test, client, verbose=verbose)
        if result is None:
            skipped += 1
            print(f"  {yellow('SKIP')} {test.name}")
        elif result:
            passed += 1
            print(f"  {green('PASS')} {test.name} [{test.expected_task_type}]")
        else:
            failed += 1
            print(f"  {red('FAIL')} {test.name} [{test.expected_task_type}]")

    print("=" * 70)
    print(f"{bold('Results:')} {green(str(passed))} passed, {red(str(failed))} failed, {yellow(str(skipped))} skipped")
    return passed, failed


async def dry_run(tier: int | None, only: set[str] | None) -> None:
    """Show what tests would run without executing them."""
    tests = ALL_REAL_TESTS
    if tier is not None:
        tests = [t for t in tests if t.tier == tier]
    if only:
        tests = [t for t in tests if t.expected_task_type in only or t.name in only]

    from collections import Counter
    by_type: Counter = Counter()
    by_tier: Counter = Counter()

    print(f"\n{bold('Real Competition Prompt Regression Suite — DRY RUN')}")
    print(f"{len(tests)} tests would run:\n")

    for t in tests:
        has_prompt = bool(t.prompt)
        has_files = False  # attachments embedded in direct_fields
        mode = "direct" if t.direct_fields else "prompt"
        has_prompt_str = "PROMPT" if has_prompt else "FIELDS"
        print(f"  [{t.tier}] {t.name}")
        print(f"       task_type={t.expected_task_type}, mode={mode}, {has_prompt_str}")
        by_type[t.expected_task_type] += 1
        by_tier[t.tier] += 1

    print(f"\n{bold('By task type:')}")
    for tt, count in sorted(by_type.items()):
        print(f"  {tt}: {count}")

    print(f"\n{bold('By tier:')}")
    for tier_num, count in sorted(by_tier.items()):
        print(f"  Tier {tier_num}: {count}")

    print(f"\nRun with --live to execute tests against sandbox.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Real competition prompt regression suite")
    parser.add_argument("--live", action="store_true", help="Execute tests against sandbox")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--only", help="Comma-separated task_types or test names to run")
    parser.add_argument("--tier", type=int, choices=[1, 2, 3],
                        help="Run only tests for this tier")
    args = parser.parse_args()

    only: set[str] | None = None
    if args.only:
        only = set(x.strip() for x in args.only.split(","))

    if not args.live:
        asyncio.run(dry_run(args.tier, only))
        return

    base_url, session_token = get_sandbox_creds()
    passed, failed = asyncio.run(run_real_prompt_tests(
        tier=args.tier,
        only=only,
        verbose=args.verbose,
        base_url=base_url,
        session_token=session_token,
    ))
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
