# WP-15 — the claim gate, and what it cannot do

| Field | Value |
|---|---|
| Document ID | `DOC-EVID-015B` |
| Work package | WP-15 — Canonical Structured Result and Deterministic Reporting |
| Contract versions | `pgx-report-claim-gate/1`, `claim-scanner/0.1.0` |
| Source | `pgx/reporting/gate.py`, `pgx/reporting/validator.py`, `pgx/domain/claims.py` |
| Tests | `tests/adversarial/test_report_claims.py`, `tests/unit/reporting/test_safe_status_rendering.py` |

---

## 1. Where the gate sits

Every rendered document — the Markdown **and** the JSON — is scanned by
WP-00's prohibited-claim scanner before anything is written. A non-clean scan
raises, nothing is written, and no manifest is written
(`SAFETY-INV-010`). A report published only as JSON would otherwise reach a
reader through a format the gate never saw, which is why it is scanned twice.

## 2. The scan is evidence, not a boolean

Every manifest carries the scanner version, the boundary version, the
categories in force, the rule ids, the offsets, and every match a safe context
suppressed. A reviewer can see what the scanner let through and why, instead
of trusting that something was checked.

The refusal record carries the categories, the rule ids and the offsets, and
**not** the matched sentence: a refusal log holding the prohibited sentence
puts the prohibited sentence into the log.

## 3. What is blocked, with a test per category

| Category | Fixture |
|---|---|
| `DIAGNOSIS` | a Turkish and an English diagnosis claim |
| `PRESCRIPTION` | an English prescribing instruction |
| `DOSING` | a Turkish dose-change imperative and an English deontic dose statement |
| `MEDICATION_CHANGE` | covered through the treatment-selection fixtures |
| `TREATMENT_SELECTION` | a Turkish substitution directive and an English "instead of" |
| `SAFETY_ASSURANCE` | a Turkish and an English candidate-safety claim |
| `CANDIDATE_PREFERENCE` | a Turkish and an English suitability claim |
| `FALSE_REASSURANCE` | "low risk" asserted for something nobody evaluated |
| `REAL_PATIENT_DATA` | a claim of having analysed a patient's VCF |
| `CLINICAL_DECISION_SUBSTITUTION` | a claim of replacing clinician judgement |
| `VALIDATION_OVERCLAIM` | a fixture asserting that this system is validated and approved for clinical use, which it is not |

Six further fixtures hide the same claims inside an HTML comment, an HTML
attribute, a Markdown link title, emphasis, a table cell and a fenced code
block. All are blocked, because the gate scans the document source rather than
a rendered view of it.

## 4. The scanner is never weakened

Tests assert that no reporting module edits a scanner rule, constructs its own
`ClaimBoundary`, or narrows the prohibited-category set. When a snapshot trips
a rule, the template changes. That direction is the whole value of the check:
a scanner tuned until the current output passes is a scanner that certifies
whatever it is pointed at.

## 5. What the scanner cannot do

Published in `gate_contract()["limits"]`, recorded in every scan record, and
asserted by test:

- lexical only: it matches patterns over folded text and performs no semantic
  analysis;
- a prohibited claim phrased outside the published patterns is not detected;
- safe-context suppression is broad — an English sentence containing "no" or
  "not" suppresses negatable matches inside it;
- it scans the rendered text, so a claim carried only in structured data that
  no template renders is out of its reach;
- a clean scan is evidence that no published pattern matched, and is never
  evidence that a document is safe.

Four **blind-spot fixtures** demonstrate the second and third of those
directly. `"Axes that were not assessed carry low risk."` asserts exactly what
`SAFETY-INV-001` forbids and scans clean, because the sentence contains the
word "not". The test asserts that the scanner misses it — so that if a future
rule catches it, this document is corrected rather than left as a false
confession.

## 6. What actually stops those

The structural controls, which is why they are the primary control and the
scanner is defence in depth:

- there is no free text in a report: every sentence comes from
  `CONTROLLED_STATEMENTS` and every label from a fixed lookup;
- the report types have no field to put an authored sentence in, and a test
  asserts that by field name;
- an unknown governed code raises rather than being displayed as itself;
- `additionalProperties: false` on the canonical result and the structured
  report refuses any property the contract does not name;
- no language model is reachable from this path.

## 7. Safe status rendering

Separately from the scanner, the validator checks how every status is
displayed:

- attention and coverage are constructed together in one type, so there is no
  arrangement of the report in which one is present without the other;
- `NOT_ASSESSED` carries the controlled sentence and no reassuring word;
- no rendered line places `NOT_ASSESSED` beside `dusuk`, `risk yok`, `uyari
  yok`, `guvenli`, `uygun`, `temiz`, `low`, `no risk`, `no warning`, `safe` or
  `suitable`;
- `PARTIAL` carries its reason codes, its missing axes and the sentence saying
  the level is the worst among the evaluated subset;
- `SOURCE_CONFLICT` carries every conflict reference and the sentence saying
  the conflict is preserved and unresolved;
- `FULL` carries no invented failure reason.

The legacy renderer failed the third of these literally: `RISK_LABEL_TR`
mapped the absence of a rule to *"Düşük / uyarı yok"* — low, no warning — and
printed it for an axis nothing had been evaluated on (`LEGACY-BUG-002`). Both
halves of that phrase are on the token list above, so the check that protects
against it is the check that would have caught it.

## 8. A known and deliberate cost

The `NOT_ASSESSED` line check asks whether a reassurance word shares a
rendered line with the status. It does not ask where the word came from, so a
medication whose *name* contains one blocks publication with a stable code.

That is the safe direction, chosen on purpose. Exempting text that arrived as
data is exactly the exemption an attacker would use, and a reader looking at
the line cannot tell which half of it was data either. The remedy is a curated
display name, not a weaker check.
