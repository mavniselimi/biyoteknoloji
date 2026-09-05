# Validation dataset

**This directory holds four documents and no case payload. A test asserts it
holds nothing else.**

A restricted payload here would mean an expert holdout case was committed
beside the rules it exists to test, which is the arrangement WP-18 was built to
prevent. Payloads live in restricted storage a deployment configures through
`PGX_VALIDATION_RESTRICTED_ROOT`; nothing in this repository points at one.

| File | What it is |
| --- | --- |
| `wp18-development-case-manifest.json` | The seven WP-17 cases, listed as DEVELOPMENT. A view over `data/demo/wp17-development-cases.json`, which remains the source. |
| `wp18-holdout-case-manifest.json` | The holdout partition. It lists nothing, and says why. |
| `wp18-separation-audit.json` | Whether development and holdout are kept apart, and where they are not. |
| `wp18-real-gate-status.json` | What this repository can honestly say about validation. |

Regenerate all four with:

```
python -m pgx.application.validation_cli artifacts
```

## The number that matters is zero

There are **no holdout cases**. The P0 Definition of Done asks for at least 50
serious validation cases, preferably 100 or more; this repository has none, and
the manifests report the count and the target as separate fields so that the
gap is visible rather than papered over.

Authoring a holdout case is scientific work. It needs a source, a derivation a
reviewer can follow, and — for an expert holdout — a named expert working it
blind under the protocol WP-22 owns. None of that can be generated, and
generating it would produce exactly the fabricated evidence this architecture
exists to make impossible.

## The seven cases here are not evidence

P1 through P6 and the authored insufficiency case are careful work, and they
are development fixtures. They demonstrated the same rules they would be
measured against, so using them as validation evidence would report memory as
generalisation — `SAFETY-INV-009`. Every one of them declares
`is_validation_evidence: false`, and the case model derives that from the role
rather than storing it, so the two cannot disagree.

## No metric appears in any of these files

No rate, no percentage, no denominator. WP-21 owns validation metrics and has
not started; WP-22 owns expert review and has not started. Until there is a
holdout case, a metric over this dataset would have a zero denominator, and a
zero-denominator rate is not a number.
