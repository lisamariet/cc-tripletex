# BUG-001: correct_ledger_error — missing_vat korreksjon 0/10

## Submission
- **Tidspunkt:** 2026-03-22 12:30:38
- **Oppgave:** correct_ledger_error (T3)
- **Score:** 0/10 (0%)
- **Varighet:** 174.3s
- **Revisjon:** tripletex-agent-00131-qsk
- **Feilende checks:** 2/2 (begge)

## Prompt
> Descobrimos erros no livro razão de janeiro e fevereiro de 2026...

**Oversettelse:**
> 4 feil: feil konto (6300→7100, 3650kr), duplikat (6300, 3700kr), manglende MVA (6300, 23350kr ekskl MVA, mangler MVA på 2710), feil beløp (6340, 23800→21350kr)

## Parsed Fields
| Felt | Verdi |
|------|-------|
| dateFrom | 2026-01-01 |
| dateTo | 2026-02-28 |
| errors[0] | wrong_account: 6300→7100, 3650 |
| errors[1] | duplicate: 6300, 3700 |
| errors[2] | missing_vat: 6300, 23350, vatAccount 2710 |
| errors[3] | wrong_amount: 6340, 23800→21350 |

## API-kall
| # | Metode | Sti | Status | Tid |
|---|--------|-----|--------|-----|
| 1-7 | wrong_account | reverse+repost 7100 | ✓ | OK |
| 8-10 | duplicate | reverse only | ✓ | OK |
| 11-15 | missing_vat | reverse+repost gross | ✗ FEIL | Se analyse |
| 16-20 | wrong_amount | reverse+repost 21350 | ✓ | OK |

## Sjekket
| # | Hva | Resultat | Detaljer |
|---|-----|----------|----------|
| 1 | wrong_account korreksjon | ✓ OK | Debit 7100 (3650), kredit motkonto (-3650) |
| 2 | duplicate reversal | ✓ OK | Bare reversert, ingen ny voucher |
| 3 | missing_vat korreksjon | ✗ FEIL | Alt A: gross 29187.5 med vatType — scorer forventet netto+MVA separat |
| 4 | wrong_amount korreksjon | ✓ OK | Debit 6340 (21350), kredit motkonto (-21350) |

## Hypoteser (rangert etter sannsynlighet)
1. **(60%) Alt C** — Reverser + post ny med 3 postings: expense netto (23350) + MVA (5837.5 på 2710) + kredit gross (-29187.5)
2. **(25%) Alt B** — IKKE reverser. Bare post separat MVA-voucher: debit 2710 (5837.5), kredit motkonto (-5837.5)
3. **(15%) Alt A var riktig** men feilet pga annet (f.eks. 3 feil på konto 6300 forvirrer søket)

## Forslag til videre sjekk
- [x] Implementert Alt C — teste mot sandbox
- [ ] Hvis Alt C feiler: prøv Alt B (revert til gammel kode uten reversering)
- [ ] Sjekk om 3 feil på samme konto (6300) forstyrrer voucher-søket

## Kodereferanser
- `app/handlers/tier3.py:1893-1962` — missing_vat logikk
- `app/handlers/tier3.py:1926-1954` — Alt A (gammel), nå endret til Alt C

## Logg
| Dato | Handling | Resultat |
|------|----------|----------|
| 2026-03-22 | Alt A deployet (rev 00129) | 0/10 regresjon |
| 2026-03-22 | Alt C implementert | Tester nå |
| | Alt B (fallback plan) | Ikke prøvd ennå |
