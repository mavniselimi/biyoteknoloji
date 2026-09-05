# WP-11 execution governance risks

| Field | Value |
|---|---|
| Document ID | `DOC-RISK-008` |
| Work package | WP-11 — Computable Rule Specification and Validated Rule Registry |
| Scope | the risks created by having, for the first time, artifacts meant to be executed |

---

## 1. The change in kind

Everything before WP-11 recorded what somebody said. WP-11 produces artifacts
whose purpose is to be executed by a later work package. That changes what a
mistake costs: an incorrect evidence record is wrong in a file, and an
incorrect executable rule is wrong in an answer somebody acts on.

## 2. The risks, and what stands against each

| Risk | What would happen | Control |
|---|---|---|
| A rule executes before anybody validated it | an unreviewed claim reaches an engine | only `VALIDATED` rules execute and only `FROZEN` rulesets are served; the registry has no method that could return anything else |
| A rule is edited after approval | the approval covers something else | content immutable from `VALIDATED`; database trigger refuses the edit; membership pins the content hash |
| A frozen artifact is altered on disk | an engine runs bytes nobody approved | `checksums.sha256`; verification fails closed; a tampered artifact is not listed |
| A wildcard rule applies to unreviewed cases | one sentence covers cases no reviewer saw | no wildcard exists in the grammar; every construct that could act as one is refused by name |
| `RAPID` silently covers `ULTRARAPID` | a rule fires on a phenotype it was not written for | separate enum members, no implicit expansion, `Phenotype` refuses ordering (`SAFETY-INV-004`) |
| Missing data reads as low risk | absence becomes reassurance | `INDETERMINATE` cannot key a rule; there is no default arm (`SAFETY-INV-001`) |
| Two rules disagree and one silently wins | a disagreement is concealed | eight conflict kinds, all blocking, no priority or ordering anywhere (`SAFETY-INV-008`) |
| Legacy severity becomes an attention level | 1,559 unreviewed rows become clinical claims | the inventory has no outcome field; every candidate is ineligible; nothing imports the inventory into the builder |
| Someone freezes a set to meet a deadline | a permanent artifact nobody validated | no `BUILDING → FROZEN` edge; `--force-freeze` refused by name |
| One person performs several separated acts | review theatre | service, database and approval-list schema each require four distinct names |
| A synthetic fixture is served as real | invented rules reach an engine | fixtures live under `tests/`, are marked four ways, use invented entities and a year-2999 dataset; the production root is asserted empty |
| A build differs by machine | "is this the ruleset that was approved" has no answer | semantic hash excludes paths, clocks, builders, ordering; the build log is the only file that varies and no hash covers it |

## 3. The risks that remain open, and cannot be closed here

| Open risk | Why code cannot close it |
|---|---|
| The people named in an approval may not be real | authentication is WP-23's; a valid envelope is a well-formed claim, not a verified one |
| A validated rule may still be scientifically wrong | the system checks structure and process, never truth |
| The protocol itself may be inadequate | no expert has reviewed it; that review is the first blocker in the gate report |
| Nobody has decided the attention level for any real pairing | that is a scientific judgement, and this repository deliberately makes none |

## 4. The failure mode this work package most needs to avoid

Not a crash. The dangerous outcome is a system that looks finished: a registry
that returns rules, an artifact that verifies, a green test suite — with no
scientist having read anything. Every real count in
`data/rulesets/wp11-real-gate-status.json` is zero, the schema refuses a gate
report with an empty blocker list, and the tests assert the zeros. Those are
the guards against reporting readiness that does not exist.
