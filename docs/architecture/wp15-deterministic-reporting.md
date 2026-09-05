# WP-15 — canonical structured result and deterministic reporting

| Field | Value |
|---|---|
| Document ID | `DOC-ARCH-015` |
| Work package | WP-15 — Canonical Structured Result and Deterministic Reporting |
| Depends on | WP-00 claim boundary, WP-13 coverage, WP-14 assessment and its lossless read model |
| Hands to | WP-16 serialisation, P1-06 an eventual narration adapter that does not exist |

---

## 1. One job

*Turn structured facts that were already calculated into a document a person
can read, without deciding anything.*

Not *what could be evaluated* — that is WP-13. Not *what the governed rules
said about it* — that is WP-14. Not *what should be done about it*, which this
product does not answer at all. WP-15 is a projection: it receives facts, adds
labels and structure, and adds no fact.

The pipeline has one direction and no branches:

```
AssessmentResult -> StructuredReport -> deterministic renderer
                 -> immutable artifact + manifest
```

## 2. The package

| Module | What it holds |
|---|---|
| `pgx/reporting/models.py` | `pgx-canonical-assessment-result/1`; the fact set a report may read |
| `pgx/reporting/structured.py` | `pgx-structured-report/1`; the presentation projection |
| `pgx/reporting/templates.py` | `pgx-report-template/1`; every controlled label and sentence |
| `pgx/reporting/render.py` | `pgx-report-renderer/1`; the deterministic Markdown and JSON writers |
| `pgx/reporting/validator.py` | `pgx-report-fact-ledger/1`; fact preservation and safe status rendering |
| `pgx/reporting/gate.py` | `pgx-report-claim-gate/1`; the prohibited-claim gate and its limits |
| `pgx/reporting/artifacts.py` | `pgx-report-artifact-manifest/1`; atomic writing and verified reading |
| `pgx/reporting/legacy_regression.py` | the legacy report comparison and its difference allowlist |
| `pgx/reporting/llm.py` | the language-model boundary; a port that raises |
| `pgx/reporting/errors.py` | six failure types and 24 stable codes |
| `pgx/application/report_service.py` | the eight-step service |
| `pgx/application/report_cli.py` | `pgx-report`; 11 read-mostly commands and 16 refused flags |
| `pgx/application/report_schema.py` | the five published JSON Schemas |
| `pgx/application/report_gate_status.py` | why no real report may be published |

WP-15 adds **no** module to `pgx/engine`. It computes nothing, so it has
nothing to put there.

## 3. What reporting receives, and what it may do with it

It receives a `CanonicalAssessmentResult`, built from WP-14's lossless read
model: both hashes, the coverage result hash, every pinned version, the
overall attention and coverage, every medication with its axes and findings,
every phenotype observation, and the pointer audit metadata.

It may: select a controlled label for a governed code; order sections
deterministically; escape metacharacters; group findings under the medication
they belong to; count what it was given; attach the canonical warning and the
research/prototype disclaimer.

It may not: recompute coverage, recompute attention, aggregate across axes or
medications, select or match a rule, resolve evidence, resolve an active
release, adjudicate a conflict, or hash facts it was not given. A boundary
test asserts each of those by name against the syntax tree.

## 4. Attention levels and coverage statuses

Every one of these is displayed with its controlled label beside it, never
instead of it.

| Attention | Coverage |
|---|---|
| `HIGH` | `FULL` |
| `MEDIUM` | `PARTIAL` |
| `LOW` | `INSUFFICIENT` |
| `NO_ACTIVE_ATTENTION` | `UNSUPPORTED_DRUG` |
| `NOT_ASSESSED` | `UNSUPPORTED_PHENOTYPE` |
| | `SOURCE_CONFLICT` |

`NO_ACTIVE_ATTENTION` is displayed only beside `FULL` coverage. Every other
absence path terminates in `NOT_ASSESSED`, which is displayed as *not assessed
/ outside the assessed scope* and never as low, no risk, safe, no warning,
normal or suitable (`SAFETY-INV-001`).

## 5. The eight questions

Every medication section answers all eight, and a section missing one is
refused rather than rendered:

`which_medication`, `attention_level`, `coverage`, `not_assessed`, `rules`,
`evidence`, `versions`, `limits`.

A medication with no findings still answers `rules` and `evidence` — with the
controlled sentence saying there is none and why. An empty answer is not a
short answer; it is an unanswered question in a document that looks complete.

## 6. Two hashes, and a checksum

| Digest | Covers | Changes when |
|---|---|---|
| `output_hash` | the governed assessment facts | a fact or a pinned version changes |
| `report_hash` | the validated report plus template version, locale and report schema version | the facts change, or the template or locale does |
| `rendered_checksum` | the bytes of the rendered document | any of the above, or the renderer's spacing |

Two locales of one assessment share an `output_hash` and have two
`report_hash` values. The first answers *are these the same facts?*; the
second answers *is this the same document?*

## 7. Determinism

The same report, template and locale render byte for byte identically. No
timestamp, no path, no environment value, no process id, no random id and no
dictionary ordering reaches the page. A byte difference between two renders is
therefore always a difference in the facts or in the template.

## 8. Escaping

Every value that came from data is escaped. Control characters become visible
`\xNN` escapes rather than being deleted, so two different values never render
identically. Line breaks become visible escapes. `&`, `<` and `>` become HTML
entities. Markdown metacharacters are backslash-escaped, and a leading block
marker is escaped so a value cannot open a heading, a list, a blockquote or a
setext underline. A value carrying any character a code span cannot survive is
rendered as escaped inline text instead of inside one.

Values carrying a line break or exceeding 512 characters are **refused** at
the canonical-result boundary rather than escaped: a governed reference is not
where narrative arrives.

## 9. The claim gate

Every rendered document — Markdown and JSON — passes WP-00's prohibited-claim
scanner before publication. A non-clean scan blocks publication; it is never
annotated around, and the scanner is never weakened to make output pass. The
scan evidence is preserved in the manifest: scanner version, boundary version,
categories, rule ids, offsets and every suppressed match.

The scanner is lexical defence in depth. Its documented limits are published
in `gate_contract()["limits"]`, recorded in every scan record, and asserted by
`tests/adversarial/test_report_claims.py`.

## 10. No language model

No provider is implemented. Nothing here imports an SDK, reads a key or opens
a socket, and the offline document is the report rather than a fallback. The
failure a model introduces into this product is not a wrong number; it is a
smoother sentence, and none of those is visible in a hash.

## 11. What is deliberately absent

There is no dose, no dosage, no recommendation, no preference, no ranking, no
score, no suitability label, no comparison between medications, no diagnosis
and no authored sentence. `additionalProperties: false` on the canonical
result and the structured report is where that is enforced against everything
downstream, and the report types have nowhere to put any of them.
