# Authoring and approving a computable rule

| Field | Value |
|---|---|
| Document ID | `DOC-SCI-008` |
| Work package | WP-11 — Computable Rule Specification and Validated Rule Registry |
| Audience | scientific curators, independent reviewers, adjudicators |
| Status | **No rule has been authored. Nothing described here has happened.** |

---

## 1. Before a rule can exist at all

Four things must be true, and none of them is true today:

1. a named scientific expert has approved the curation protocol;
2. the canonical dataset has been published, not left `BUILDING`;
3. the evidence build has been reviewed and is no longer `QUARANTINED`;
4. real people hold real scientific roles — which needs WP-23.

`data/rulesets/wp11-real-gate-status.json` reports the current state of each.

## 2. Which curated conclusions may become rules

Only `SUPPORTED`, only `APPLICABLE`, and only with no unresolved material
conflict.

| Conclusion state | May become a rule |
|---|---|
| `SUPPORTED` | yes |
| `CONFLICTING` | no — the sources disagree; that is not a claim |
| `INSUFFICIENT` | no — a rule would assert more than the evidence does |
| `NOT_INTERPRETABLE` | no |
| `OUT_OF_SCOPE` | no |
| `NOT_APPLICABLE` | no |

A conclusion that cannot become a rule is not a failure of curation. Most of
what a careful curator writes will be one of these, and recording that
honestly is the point of the conclusion vocabulary.

## 3. The four separated acts

| Act | Role | What it means |
|---|---|---|
| authored | `SCIENTIFIC_CURATOR` | wrote the rule from a curated revision |
| reviewed | `INDEPENDENT_SCIENTIFIC_REVIEWER` | independently re-read the evidence and the reasoning |
| approved | `PROTOCOL_OWNER` or delegate | recorded the approval envelope in WP-10 |
| validated | `INDEPENDENT_SCIENTIFIC_REVIEWER` or `ADJUDICATOR` | moved the rule to `VALIDATED` |

Four different people. The service refuses an author who tries to validate
their own rule; the database refuses a row where the validator is the author;
the approval list inside every frozen artifact records all four names, and the
schema requires each of them.

None of this proves the people named are real or hold the credentials the
record claims. That is authentication, and it belongs to WP-23.

## 4. Writing the condition

State the gene, the drug, and the phenotypes — all of them, by name.

- `EXACT` for one phenotype, `ONE_OF` for several.
- `RAPID` and `ULTRARAPID` are different. Writing one does not cover the other.
- There is no wildcard and no default arm. A phenotype you do not name is a
  phenotype this rule says nothing about, and that is correct: WP-12 will
  report that nothing matched rather than inherit a reassuring default.
- `INDETERMINATE` cannot be a rule key. If the phenotype could not be
  determined, no rule fires and the assessment says so.

## 5. Writing the outcome

Choose one of `NO_ACTIVE_ATTENTION`, `LOW`, `MEDIUM`, `HIGH`, and point at the
curated rationale.

`NO_ACTIVE_ATTENTION` is a real conclusion — "we looked and found nothing to
flag" — and is deliberately distinguishable from "nobody looked", which is what
WP-12 will report as `NOT_ASSESSED`.

You cannot write a dose, a dose change, a drug recommendation, an alternative,
a treatment instruction, a safety statement, a score or a ranking. If the
conclusion you want to record needs one of those, it is not a conclusion this
system is built to carry.

## 6. When two rules disagree

The system reports it and stops. It does not pick a winner, does not order
rules by priority, and does not apply "most severe wins". A conflict between
two approved rules is a disagreement between the people who approved them,
and it comes back to them.

## 7. Withdrawing a rule

Deprecate it, with a reason. Nothing is deleted: a rule may be cited by a
frozen ruleset and by historical assessments, and deleting it would make those
unexplainable. A correction is a new version in the same family, naming the
version it supersedes.
