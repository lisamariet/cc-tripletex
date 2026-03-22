# BUG-{NNN}: {task_type} — {score}/{max} ({percent}%)

## Submission
- **Tidspunkt:** {timestamp}
- **Oppgave:** {task_type} (T{tier})
- **Score:** {score}/{max} ({percent}%)
- **Varighet:** {duration}s
- **Revisjon:** {revision}
- **Feilende checks:** {failed_checks}

## Prompt
> {original_prompt}

**Oversettelse:**
> {translation}

## Parsed Fields
| Felt | Verdi |
|------|-------|
| {field1} | {value1} |
| {field2} | {value2} |

## API-kall
| # | Metode | Sti | Status | Tid |
|---|--------|-----|--------|-----|
| 1 | {method} | {path} | {status} | {ms}ms |

## Sjekket
| # | Hva | Resultat | Detaljer |
|---|-----|----------|----------|
| 1 | {check_description} | ✓ OK | {details} |
| 2 | {check_description} | ✗ FEIL | {details} |
| 3 | {check_description} | — Ikke sjekket | |

## Hypoteser (rangert etter sannsynlighet)
1. **(70%)** {hypothesis_1}
2. **(20%)** {hypothesis_2}
3. **(10%)** {hypothesis_3}

## Forslag til videre sjekk
- [ ] {suggestion_1}
- [ ] {suggestion_2}
- [ ] {suggestion_3}

## Kodereferanser
- `{file}:{line}` — {description}
- `{file}:{line}` — {description}

## Logg
| Dato | Handling | Resultat |
|------|----------|----------|
| {date} | Opprettet rapport | — |
| | | |
