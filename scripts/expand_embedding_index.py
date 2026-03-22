#!/usr/bin/env python3
"""Expand the embedding index with new prompts for underrepresented task types and languages.

Usage:
    python3 scripts/expand_embedding_index.py

This adds new manually-crafted prompts (realistic competition-style), embeds them
via Vertex AI text-embedding-005, and merges them into app/embeddings_index.json.
"""

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ─── New prompts to add ───────────────────────────────────────────────────────
# Format: (task_type, prompt, fields_dict)

NEW_ENTRIES: list[tuple[str, str, dict]] = [
    # ═══════════════════════════════════════════════════════════════════════════
    # set_project_fixed_price — norsk (nb)
    # ═══════════════════════════════════════════════════════════════════════════
    ("set_project_fixed_price",
     "Sett fastpris 275000 kr på prosjektet \"Systemoppgradering\" for Nordlys AS (org.nr 912345678). Prosjektleder er Kari Nordmann (kari.nordmann@example.org). Fakturer hele beløpet ved prosjektstart.",
     {}),
    ("set_project_fixed_price",
     "Sett en fastpris på 189500 NOK på prosjektet \"Nettverksmodernisering\" for Havbris AS (org.nr 923456789). Prosjektleder er Erik Hansen (erik.hansen@example.org). Fakturer 50% ved oppstart og 50% ved ferdigstillelse.",
     {}),
    ("set_project_fixed_price",
     "Definer fastpris 345000 kr på prosjektet \"Skymigrering\" for Fjelltopp AS (org.nr 934567890). Prosjektleder er Ingrid Berg (ingrid.berg@example.org). Hele beløpet faktureres ved levering.",
     {}),
    ("set_project_fixed_price",
     "Sett fastpris på 520000 kr for prosjektet \"Digital plattform\" for Sjøstjerne AS (org.nr 845678901). Prosjektleder er Lars Olsen (lars.olsen@example.org). Beløpet skal faktureres månedlig.",
     {}),

    # set_project_fixed_price — nynorsk (nn)
    ("set_project_fixed_price",
     "Sett fastpris 312000 kr på prosjektet \"Datasikkerheit\" for Vestfjord AS (org.nr 856789012). Prosjektleiar er Solveig Haugen (solveig.haugen@example.org). Fakturer heile beløpet ved prosjektstart.",
     {}),
    ("set_project_fixed_price",
     "Sett ein fastpris på 198750 kr på prosjektet \"Kundeportal\" for Dalabygda AS (org.nr 867890123). Prosjektleiar er Olav Strand (olav.strand@example.org). Fakturer 30% ved start, resten ved levering.",
     {}),
    ("set_project_fixed_price",
     "Definer fastpris 443000 kr på prosjektet \"Automatisering logistikk\" for Brattfjell AS (org.nr 878901234). Prosjektleiar er Randi Moen (randi.moen@example.org). Beløpet skal fakturerast kvartalsvis.",
     {}),
    ("set_project_fixed_price",
     "Sett fastpris 167500 kr på prosjektet \"Integrasjonsløysing\" for Storhaug AS (org.nr 889012345). Prosjektleiar er Torbjørn Vik (torbjorn.vik@example.org). Heile summen fakturerast ved avslutning.",
     {}),

    # set_project_fixed_price — portugisisk (pt)
    ("set_project_fixed_price",
     "Defina um preço fixo de 287000 NOK no projeto \"Modernização de TI\" para Sol Nascente Lda (org. nº 890123456). O gestor de projeto é João Silva (joao.silva@example.org). Fature o valor total na conclusão.",
     {}),
    ("set_project_fixed_price",
     "Estabeleça um preço fixo de 415000 NOK no projeto \"Plataforma Digital\" para Oceano Azul Lda (org. nº 901234567). O gestor de projeto é Maria Santos (maria.santos@example.org). Fature 50% no início e 50% na entrega.",
     {}),
    ("set_project_fixed_price",
     "Defina um preço fixo de 163500 NOK no projeto \"Automatização Contábil\" para Costa Verde Lda (org. nº 812345679). O gestor de projeto é Pedro Costa (pedro.costa@example.org). Fature mensalmente.",
     {}),

    # ═══════════════════════════════════════════════════════════════════════════
    # create_custom_dimension — spansk (es)
    # ═══════════════════════════════════════════════════════════════════════════
    ("create_custom_dimension",
     'Cree una dimensión contable personalizada "Región" con los valores "Norte" y "Sur". Luego registre un asiento en la cuenta 7100 por 18500 NOK, vinculado al valor de dimensión "Norte".',
     {}),
    ("create_custom_dimension",
     'Cree una dimensión contable personalizada "Departamento" con los valores "Ventas" y "Soporte". Luego registre un asiento en la cuenta 7000 por 24300 NOK, vinculado al valor de dimensión "Ventas".',
     {}),
    ("create_custom_dimension",
     'Cree una dimensión contable personalizada "Canal" con los valores "Online" y "Butikk". Luego registre un asiento en la cuenta 7140 por 15800 NOK, vinculado al valor de dimensión "Online".',
     {}),
    ("create_custom_dimension",
     'Cree una dimensión contable personalizada "Prosjektfase" con los valores "Planlegging" y "Gjennomføring". Luego registre un asiento en la cuenta 7350 por 32100 NOK, vinculado al valor de dimensión "Planlegging".',
     {}),
    ("create_custom_dimension",
     'Cree una dimensión contable personalizada "Aktivitet" con los valores "Drift" y "Investering". Luego registre un asiento en la cuenta 7500 por 42000 NOK, vinculado al valor de dimensión "Drift".',
     {}),

    # ═══════════════════════════════════════════════════════════════════════════
    # create_department (batch) — spansk (es)
    # ═══════════════════════════════════════════════════════════════════════════
    ("create_department",
     'Crea tres departamentos en Tripletex: "Logística", "Ventas" y "Soporte".',
     {"items": [{"taskType": "create_department", "fields": {"name": "Logística"}}, {"taskType": "create_department", "fields": {"name": "Ventas"}}, {"taskType": "create_department", "fields": {"name": "Soporte"}}]}),
    ("create_department",
     'Crea tres departamentos en Tripletex: "Producción", "Calidad" y "Investigación".',
     {"items": [{"taskType": "create_department", "fields": {"name": "Producción"}}, {"taskType": "create_department", "fields": {"name": "Calidad"}}, {"taskType": "create_department", "fields": {"name": "Investigación"}}]}),
    ("create_department",
     'Crea tres departamentos en Tripletex: "Finanzas", "Marketing" y "Operaciones".',
     {"items": [{"taskType": "create_department", "fields": {"name": "Finanzas"}}, {"taskType": "create_department", "fields": {"name": "Marketing"}}, {"taskType": "create_department", "fields": {"name": "Operaciones"}}]}),
    ("create_department",
     'Crea tres departamentos en Tripletex: "Desarrollo", "Administración" y "Atención al Cliente".',
     {"items": [{"taskType": "create_department", "fields": {"name": "Desarrollo"}}, {"taskType": "create_department", "fields": {"name": "Administración"}}, {"taskType": "create_department", "fields": {"name": "Atención al Cliente"}}]}),

    # create_department (batch) — portugisisk (pt)
    ("create_department",
     'Crie três departamentos no Tripletex: "Logística", "Vendas" e "Suporte".',
     {"items": [{"taskType": "create_department", "fields": {"name": "Logística"}}, {"taskType": "create_department", "fields": {"name": "Vendas"}}, {"taskType": "create_department", "fields": {"name": "Suporte"}}]}),
    ("create_department",
     'Crie três departamentos no Tripletex: "Produção", "Qualidade" e "Pesquisa".',
     {"items": [{"taskType": "create_department", "fields": {"name": "Produção"}}, {"taskType": "create_department", "fields": {"name": "Qualidade"}}, {"taskType": "create_department", "fields": {"name": "Pesquisa"}}]}),
    ("create_department",
     'Crie três departamentos no Tripletex: "Finanças", "Recursos Humanos" e "Tecnologia".',
     {"items": [{"taskType": "create_department", "fields": {"name": "Finanças"}}, {"taskType": "create_department", "fields": {"name": "Recursos Humanos"}}, {"taskType": "create_department", "fields": {"name": "Tecnologia"}}]}),
    ("create_department",
     'Crie três departamentos no Tripletex: "Administração", "Contabilidade" e "Compras".',
     {"items": [{"taskType": "create_department", "fields": {"name": "Administração"}}, {"taskType": "create_department", "fields": {"name": "Contabilidade"}}, {"taskType": "create_department", "fields": {"name": "Compras"}}]}),

    # ═══════════════════════════════════════════════════════════════════════════
    # correct_ledger_error — fransk (fr)
    # ═══════════════════════════════════════════════════════════════════════════
    ("correct_ledger_error",
     "Nous avons découvert des erreurs dans le grand livre de janvier et février 2026. Vérifiez toutes les pièces et trouvez les 4 erreurs: une écriture sur le mauvais compte de charges, un montant incorrect sur une facture fournisseur, une écriture TVA manquante, et une double comptabilisation. Corrigez chaque erreur avec une pièce corrective.",
     {}),
    ("correct_ledger_error",
     "Des erreurs ont été identifiées dans le grand livre pour les mois de janvier et février 2026. Examinez les pièces comptables et trouvez les 4 erreurs: un compte débiteur erroné, un montant de TVA incorrect, une écriture en double, et un fournisseur mal affecté. Corrigez avec des écritures correctives.",
     {}),
    ("correct_ledger_error",
     "Nous avons trouvé des anomalies dans le grand livre de janvier et février 2026. Passez en revue tous les justificatifs et identifiez les 4 erreurs: une imputation de charge incorrecte, un montant erroné, un enregistrement dupliqué, et une TVA mal calculée. Établissez les écritures correctives nécessaires.",
     {}),
    ("correct_ledger_error",
     "Le grand livre de janvier-février 2026 contient des erreurs. Vérifiez les pièces comptables et localisez les 4 erreurs: un compte de produits mal utilisé, un montant de facture erroné, une écriture de TVA manquante, et une double saisie. Passez les écritures correctives.",
     {}),

    # correct_ledger_error — tysk (de)
    ("correct_ledger_error",
     "Wir haben Fehler im Hauptbuch für Januar und Februar 2026 entdeckt. Überprüfen Sie alle Belege und finden Sie die 4 Fehler: eine Buchung auf dem falschen Aufwandskonto, ein falscher Rechnungsbetrag, eine fehlende Umsatzsteuerbuchung und eine Doppelbuchung. Korrigieren Sie jeden Fehler mit einem Korrekturbuchung.",
     {}),
    ("correct_ledger_error",
     "Es wurden Fehler im Hauptbuch für Januar und Februar 2026 festgestellt. Prüfen Sie alle Buchungsbelege und identifizieren Sie die 4 Fehler: ein falsches Sollkonto, ein fehlerhafter Mehrwertsteuerbetrag, eine doppelte Buchung und eine falsche Lieferantenzuordnung. Erstellen Sie Korrekturbelege.",
     {}),
    ("correct_ledger_error",
     "Im Hauptbuch für Januar und Februar 2026 sind Fehler aufgetreten. Überprüfen Sie sämtliche Belege und finden Sie die 4 Fehler: eine falsche Kontierung, ein falscher Betrag, ein duplizierter Beleg und eine fehlende MwSt-Buchung. Nehmen Sie die erforderlichen Korrekturbuchungen vor.",
     {}),
    ("correct_ledger_error",
     "Das Hauptbuch für Januar-Februar 2026 enthält Fehler. Kontrollieren Sie die Belege und lokalisieren Sie die 4 Fehler: ein falsches Ertragskonto, ein fehlerhafter Rechnungsbetrag, eine fehlende Umsatzsteuerbuchung und eine doppelte Erfassung. Buchen Sie die Korrekturen.",
     {}),

    # ═══════════════════════════════════════════════════════════════════════════
    # register_expense_receipt — fransk (fr)
    # ═══════════════════════════════════════════════════════════════════════════
    ("register_expense_receipt",
     "Nous avons besoin de la dépense de Kontorrekvisita de ce reçu enregistrée au département IT. Utilisez le bon compte de charges et assurez un traitement correct de la TVA.",
     {}),
    ("register_expense_receipt",
     "Nous avons besoin de la dépense de Møteforpleining de ce reçu enregistrée au département Ledelse. Utilisez le bon compte de charges et assurez un traitement correct de la TVA.",
     {}),
    ("register_expense_receipt",
     "Nous avons besoin de la dépense de Reiseutgifter de ce reçu enregistrée au département Salg. Utilisez le bon compte de charges et assurez un traitement correct de la TVA.",
     {}),
    ("register_expense_receipt",
     "Nous avons besoin de la dépense de Programvarelisens de ce reçu enregistrée au département Utvikling. Utilisez le bon compte de charges et assurez un traitement correct de la TVA.",
     {}),

    # register_expense_receipt — portugisisk (pt)
    ("register_expense_receipt",
     "Precisamos da despesa de Kontorrekvisita deste recibo registada no departamento Administrasjon. Use a conta de despesas correta e garanta o tratamento correto do IVA.",
     {}),
    ("register_expense_receipt",
     "Precisamos da despesa de Arbeidstøy deste recibo registada no departamento Produksjon. Use a conta de despesas correta e garanta o tratamento correto do IVA.",
     {}),
    ("register_expense_receipt",
     "Precisamos da despesa de Taxi deste recibo registada no departamento Ledelse. Use a conta de despesas correta e garanta o tratamento correto do IVA.",
     {}),
    ("register_expense_receipt",
     "Precisamos da despesa de Faglitteratur deste recibo registada no departamento HR. Use a conta de despesas correta e garanta o tratamento correto do IVA.",
     {}),

    # ═══════════════════════════════════════════════════════════════════════════
    # bank_reconciliation — tillegg for å nå 15+ (trenger 8 nye)
    # ═══════════════════════════════════════════════════════════════════════════
    ("bank_reconciliation",
     "Avstem bankutskriften (vedlagt CSV) mot åpne fakturaer i Tripletex. Match innbetalinger til kundefakturaer og utbetalinger til leverandørfakturaer. Håndter delbetalinger korrekt.",
     {"accountNumber": 1920}),
    ("bank_reconciliation",
     "Avstem kontoutskrifta (vedlagt CSV) mot opne fakturaer i Tripletex. Match innbetalingar til kundefakturaer og utbetalingar til leverandørfakturaer. Handter delbetalingar korrekt.",
     {"accountNumber": 1920}),
    ("bank_reconciliation",
     "Reconcile the bank statement (attached CSV) against open invoices in Tripletex. Match incoming customer payments and outgoing supplier payments. Create journal entries for unmatched transactions.",
     {"accountNumber": 1920}),
    ("bank_reconciliation",
     "Reconcile the attached bank statement CSV with Tripletex. Match payments to invoices, handle partial payments and bank fees. Closing balance must be verified.",
     {"accountNumber": 1920}),
    ("bank_reconciliation",
     "Rapprochez le relevé bancaire (CSV ci-joint) avec les factures ouvertes dans Tripletex. Associez les encaissements aux factures clients et les décaissements aux factures fournisseurs. Gérez les paiements partiels.",
     {"accountNumber": 1920}),
    ("bank_reconciliation",
     "Rapprochez le relevé bancaire joint avec les écritures comptables dans Tripletex. Identifiez les paiements correspondants et créez des écritures pour les transactions non rapprochées.",
     {"accountNumber": 1920}),
    ("bank_reconciliation",
     "Concilie el extracto bancario (CSV adjunto) con las facturas abiertas en Tripletex. Relacione los cobros con facturas de clientes y los pagos con facturas de proveedores. Gestione pagos parciales.",
     {"accountNumber": 1920}),
    ("bank_reconciliation",
     "Concilie o extrato bancário (CSV em anexo) com as faturas abertas no Tripletex. Associe os recebimentos às faturas de clientes e os pagamentos às faturas de fornecedores. Trate pagamentos parciais corretamente.",
     {"accountNumber": 1920}),
    ("bank_reconciliation",
     "Gleichen Sie den beigefügten Kontoauszug (CSV) mit den offenen Rechnungen in Tripletex ab. Ordnen Sie Zahlungseingänge den Kundenrechnungen und Zahlungsausgänge den Lieferantenrechnungen zu. Teilzahlungen korrekt behandeln.",
     {"accountNumber": 1920}),
    ("bank_reconciliation",
     "Stemm av bankutskriften (vedlagt CSV) mot bokførte fakturaer i Tripletex. Koble innbetalinger til kundefakturaer, utbetalinger til leverandørfakturaer. Opprett bilag for umatchede transaksjoner.",
     {"accountNumber": 1920}),

    # ═══════════════════════════════════════════════════════════════════════════
    # overdue_invoice — tillegg for å nå 15+ (trenger 9 nye)
    # ═══════════════════════════════════════════════════════════════════════════
    ("overdue_invoice",
     "En av kundene dine har en forfalt faktura. Finn den forfalte fakturaen og bokfør et purregebyr på 50 kr. Debet kundefordringer (1500), kredit purregebyr (3400). Opprett også en faktura for purregebyret og registrer en delbetaling på 3000 kr.",
     {"reminderFeeAmount": 50, "debitAccount": 1500, "creditAccount": 3400, "partialPaymentAmount": 3000}),
    ("overdue_invoice",
     "En av kundene dine har en forfalt faktura. Finn den forfalte fakturaen og bokfør et purregebyr på 75 kr. Debet kundefordringer (1500), kredit purregebyr (3400). Opprett også en faktura for purregebyret og registrer en delbetaling på 4500 kr.",
     {"reminderFeeAmount": 75, "debitAccount": 1500, "creditAccount": 3400, "partialPaymentAmount": 4500}),
    ("overdue_invoice",
     "One of your customers has an overdue invoice. Find the overdue invoice and post a reminder fee of 45 NOK. Debit accounts receivable (1500), credit reminder fees (3400). Also create an invoice for the reminder fee and register a partial payment of 2500 NOK.",
     {"reminderFeeAmount": 45, "debitAccount": 1500, "creditAccount": 3400, "partialPaymentAmount": 2500}),
    ("overdue_invoice",
     "One of your customers has an overdue invoice. Find the overdue invoice and post a reminder fee of 60 NOK. Debit accounts receivable (1500), credit reminder fees (3400). Also create an invoice for the reminder fee and register a partial payment of 6000 NOK.",
     {"reminderFeeAmount": 60, "debitAccount": 1500, "creditAccount": 3400, "partialPaymentAmount": 6000}),
    ("overdue_invoice",
     "L'un de vos clients a une facture en retard. Trouvez la facture en retard et enregistrez des frais de rappel de 55 NOK. Débit créances clients (1500), crédit revenus de rappel (3400). Créez également une facture pour les frais de rappel et enregistrez un paiement partiel de 3500 NOK.",
     {"reminderFeeAmount": 55, "debitAccount": 1500, "creditAccount": 3400, "partialPaymentAmount": 3500}),
    ("overdue_invoice",
     "Um dos seus clientes tem uma fatura vencida. Encontre a fatura vencida e registe uma taxa de lembrete de 40 NOK. Débito contas a receber (1500), crédito receitas de lembrete (3400). Crie também uma fatura para a taxa de lembrete e registe um pagamento parcial de 4000 NOK.",
     {"reminderFeeAmount": 40, "debitAccount": 1500, "creditAccount": 3400, "partialPaymentAmount": 4000}),
    ("overdue_invoice",
     "Um dos seus clientes tem uma fatura vencida. Encontre a fatura vencida e registe uma taxa de lembrete de 70 NOK. Débito contas a receber (1500), crédito receitas de lembrete (3400). Crie também uma fatura para a taxa de lembrete e registe um pagamento parcial de 5500 NOK.",
     {"reminderFeeAmount": 70, "debitAccount": 1500, "creditAccount": 3400, "partialPaymentAmount": 5500}),
    ("overdue_invoice",
     "Einer Ihrer Kunden hat eine überfällige Rechnung. Finden Sie die überfällige Rechnung und buchen Sie eine Mahngebühr von 50 NOK. Soll Forderungen (1500), Haben Mahngebühren (3400). Erstellen Sie außerdem eine Rechnung für die Mahngebühr und erfassen Sie eine Teilzahlung von 3000 NOK.",
     {"reminderFeeAmount": 50, "debitAccount": 1500, "creditAccount": 3400, "partialPaymentAmount": 3000}),
    ("overdue_invoice",
     "Uno de sus clientes tiene una factura vencida. Encuentre la factura vencida y registre un cargo por recordatorio de 45 NOK. Débito cuentas por cobrar (1500), crédito ingresos por recordatorio (3400). Cree también una factura por el cargo de recordatorio y registre un pago parcial de 2500 NOK.",
     {"reminderFeeAmount": 45, "debitAccount": 1500, "creditAccount": 3400, "partialPaymentAmount": 2500}),

    # ═══════════════════════════════════════════════════════════════════════════
    # create_voucher — tillegg for å nå 15+ (trenger 10 nye)
    # ═══════════════════════════════════════════════════════════════════════════
    ("create_voucher",
     "Bokfør et bilag: debet konto 7140 (reisekostnad) 4500 kr, kredit konto 1920 (bank) 4500 kr. Beskrivelse: Tjenestereise Oslo-Bergen.",
     {"postings": [{"debitAccount": 7140, "creditAccount": 1920, "amount": 4500}]}),
    ("create_voucher",
     "Bokfør eit bilag: debet konto 7100 (bilkostnad) 3200 kr, kredit konto 1920 (bank) 3200 kr. Beskriving: Drivstoff firmabil.",
     {"postings": [{"debitAccount": 7100, "creditAccount": 1920, "amount": 3200}]}),
    ("create_voucher",
     "Post a journal entry: debit account 7000 (office supplies) 2800 NOK, credit account 1920 (bank) 2800 NOK. Description: Office supplies purchase.",
     {"postings": [{"debitAccount": 7000, "creditAccount": 1920, "amount": 2800}]}),
    ("create_voucher",
     "Post a journal entry: debit account 6300 (rent) 15000 NOK, credit account 1920 (bank) 15000 NOK. Description: Monthly office rent.",
     {"postings": [{"debitAccount": 6300, "creditAccount": 1920, "amount": 15000}]}),
    ("create_voucher",
     "Enregistrez une écriture comptable: débit compte 7350 (représentation) 1850 NOK, crédit compte 1920 (banque) 1850 NOK. Description: Dîner client.",
     {"postings": [{"debitAccount": 7350, "creditAccount": 1920, "amount": 1850}]}),
    ("create_voucher",
     "Enregistrez une pièce comptable: débit compte 6900 (téléphone) 950 NOK, crédit compte 1920 (banque) 950 NOK. Description: Facture téléphone mensuelle.",
     {"postings": [{"debitAccount": 6900, "creditAccount": 1920, "amount": 950}]}),
    ("create_voucher",
     "Registre um lançamento contábil: débito conta 7000 (material de escritório) 3600 NOK, crédito conta 1920 (banco) 3600 NOK. Descrição: Compra de material.",
     {"postings": [{"debitAccount": 7000, "creditAccount": 1920, "amount": 3600}]}),
    ("create_voucher",
     "Buchen Sie einen Beleg: Soll Konto 7140 (Reisekosten) 5200 NOK, Haben Konto 1920 (Bank) 5200 NOK. Beschreibung: Geschäftsreise Hamburg.",
     {"postings": [{"debitAccount": 7140, "creditAccount": 1920, "amount": 5200}]}),
    ("create_voucher",
     "Cree un asiento contable: débito cuenta 7000 (suministros) 2100 NOK, crédito cuenta 1920 (banco) 2100 NOK. Descripción: Compra de suministros de oficina.",
     {"postings": [{"debitAccount": 7000, "creditAccount": 1920, "amount": 2100}]}),
    ("create_voucher",
     "Bokfør et purregebyr på 65 kr for forfalt faktura. Debet kundefordringer (1500), kredit purregebyr (3400). Opprett også en faktura for purregebyret.",
     {"postings": [{"debitAccount": 1500, "creditAccount": 3400, "amount": 65}]}),

    # ═══════════════════════════════════════════════════════════════════════════
    # project_lifecycle — tillegg for å nå 15+ (trenger 10 nye)
    # ═══════════════════════════════════════════════════════════════════════════
    ("project_lifecycle",
     "Gjennomfør hele prosjektsyklusen for 'Datamigrering Solvik' (Solvik AS, org.nr 851234567): 1) Prosjektet har budsjett 350000 kr. 2) Registrer timer: Anna Bakke (prosjektleder, anna.bakke@example.org) 40 timer, Morten Dahl (utvikler, morten.dahl@example.org) 80 timer. 3) Fakturer kunden. 4) Lukk prosjektet.",
     {"projectName": "Datamigrering Solvik", "customerName": "Solvik AS", "customerOrgNumber": "851234567", "projectBudget": 350000}),
    ("project_lifecycle",
     "Gjennomfør heile prosjektsyklusen for 'Nettverksoppgradering Fjordheim' (Fjordheim AS, org.nr 862345678): 1) Prosjektet har budsjett 275000 kr. 2) Registrer timar: Liv Hauge (prosjektleiar, liv.hauge@example.org) 35 timar, Stein Viken (konsulent, stein.viken@example.org) 60 timar. 3) Fakturer kunden. 4) Lukk prosjektet.",
     {"projectName": "Nettverksoppgradering Fjordheim", "customerName": "Fjordheim AS", "customerOrgNumber": "862345678", "projectBudget": 275000}),
    ("project_lifecycle",
     "Execute the complete project lifecycle for 'Security Audit Nordhavn' (Nordhavn Ltd, org no. 873456789): 1) The project has a budget of 420000 NOK. 2) Log time: Sarah Jensen (project manager, sarah.jensen@example.org) 45 hours, Tom Berg (consultant, tom.berg@example.org) 90 hours. 3) Invoice the customer. 4) Close the project.",
     {"projectName": "Security Audit Nordhavn", "customerName": "Nordhavn Ltd", "customerOrgNumber": "873456789", "projectBudget": 420000}),
    ("project_lifecycle",
     "Execute the complete project lifecycle for 'CRM Implementation Westport' (Westport Inc, org no. 884567890): 1) The project has a budget of 510000 NOK. 2) Log time: Emma Wilson (project manager, emma.wilson@example.org) 50 hours, James Lee (developer, james.lee@example.org) 120 hours. 3) Invoice the customer. 4) Close the project.",
     {"projectName": "CRM Implementation Westport", "customerName": "Westport Inc", "customerOrgNumber": "884567890", "projectBudget": 510000}),
    ("project_lifecycle",
     "Exécutez le cycle de vie complet du projet 'Migration Cloud Pontvieux' (Pontvieux SARL, org. nº 895678901): 1) Le projet a un budget de 380000 NOK. 2) Enregistrez les heures: Pierre Dupont (chef de projet, pierre.dupont@example.org) 40 heures, Claire Martin (développeuse, claire.martin@example.org) 75 heures. 3) Facturez le client. 4) Clôturez le projet.",
     {"projectName": "Migration Cloud Pontvieux", "customerName": "Pontvieux SARL", "customerOrgNumber": "895678901", "projectBudget": 380000}),
    ("project_lifecycle",
     "Exécutez le cycle de vie complet du projet 'Intégration ERP Bellerive' (Bellerive SA, org. nº 806789012): 1) Le projet a un budget de 465000 NOK. 2) Enregistrez les heures: Anne Leroy (chef de projet, anne.leroy@example.org) 55 heures, Marc Bernard (consultant, marc.bernard@example.org) 95 heures. 3) Facturez le client. 4) Clôturez le projet.",
     {"projectName": "Intégration ERP Bellerive", "customerName": "Bellerive SA", "customerOrgNumber": "806789012", "projectBudget": 465000}),
    ("project_lifecycle",
     "Ejecute el ciclo de vida completo del proyecto 'Automatización Logística Rivera' (Rivera SL, org. nº 817890123): 1) El proyecto tiene un presupuesto de 290000 NOK. 2) Registre horas: Carlos López (director de proyecto, carlos.lopez@example.org) 30 horas, María García (desarrolladora, maria.garcia@example.org) 70 horas. 3) Facture al cliente. 4) Cierre el proyecto.",
     {"projectName": "Automatización Logística Rivera", "customerName": "Rivera SL", "customerOrgNumber": "817890123", "projectBudget": 290000}),
    ("project_lifecycle",
     "Ejecute el ciclo de vida completo del proyecto 'Portal Digital Montaña' (Montaña SL, org. nº 828901234): 1) El proyecto tiene un presupuesto de 375000 NOK. 2) Registre horas: Ana Martín (directora de proyecto, ana.martin@example.org) 45 horas, Pedro Ruiz (consultor, pedro.ruiz@example.org) 85 horas. 3) Facture al cliente. 4) Cierre el proyecto.",
     {"projectName": "Portal Digital Montaña", "customerName": "Montaña SL", "customerOrgNumber": "828901234", "projectBudget": 375000}),
    ("project_lifecycle",
     "Führen Sie den vollständigen Projektzyklus für 'Datenanalyse Bergtal' (Bergtal GmbH, Org.-Nr. 839012345) durch: 1) Das Projekt hat ein Budget von 330000 NOK. 2) Erfassen Sie Stunden: Hans Müller (Projektleiter, hans.mueller@example.org) 40 Stunden, Lisa Schmidt (Entwicklerin, lisa.schmidt@example.org) 80 Stunden. 3) Fakturieren Sie den Kunden. 4) Schließen Sie das Projekt ab.",
     {"projectName": "Datenanalyse Bergtal", "customerName": "Bergtal GmbH", "customerOrgNumber": "839012345", "projectBudget": 330000}),
    ("project_lifecycle",
     "Concluir o ciclo de vida completo do projeto 'Implementação SAP Baía' (Baía Lda, org. nº 840123456): 1) O projeto tem um orçamento de 445000 NOK. 2) Registre horas: João Costa (gestor de projeto, joao.costa@example.org) 50 horas, Ana Silva (consultora, ana.silva@example.org) 100 horas. 3) Fature o cliente. 4) Encerre o projeto.",
     {"projectName": "Implementação SAP Baía", "customerName": "Baía Lda", "customerOrgNumber": "840123456", "projectBudget": 445000}),
]


def main():
    from app.embeddings import embed_texts_batch

    index_path = Path(__file__).parent.parent / "app" / "embeddings_index.json"

    # Load existing index
    with open(index_path) as f:
        existing = json.load(f)
    logger.info(f"Loaded existing index: {len(existing)} entries")

    # Check for duplicates
    existing_prompts = {e["prompt"].strip() for e in existing}
    new_entries = []
    for task_type, prompt, fields in NEW_ENTRIES:
        if prompt.strip() in existing_prompts:
            logger.warning(f"Skipping duplicate: {prompt[:60]}")
            continue
        new_entries.append({"task_type": task_type, "prompt": prompt, "fields": fields})

    if not new_entries:
        logger.info("No new entries to add!")
        return

    logger.info(f"Embedding {len(new_entries)} new prompts...")
    prompts = [e["prompt"] for e in new_entries]
    embeddings = embed_texts_batch(prompts)

    # Merge
    for entry, embedding in zip(new_entries, embeddings):
        existing.append({
            "prompt": entry["prompt"],
            "task_type": entry["task_type"],
            "fields": entry["fields"],
            "embedding": embedding,
        })

    # Save
    with open(index_path, "w") as f:
        json.dump(existing, f, ensure_ascii=False)
    logger.info(f"Saved expanded index: {len(existing)} entries")

    # Summary
    from collections import Counter
    types = Counter(e["task_type"] for e in existing)
    logger.info("\nUpdated type counts:")
    for tt, count in types.most_common():
        logger.info(f"  {tt}: {count}")


if __name__ == "__main__":
    main()
