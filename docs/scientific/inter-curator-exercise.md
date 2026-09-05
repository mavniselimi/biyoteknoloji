# Inter-curator exercise (WP-09)

| Field | Value |
|---|---|
| Document ID | `DOC-SCI-013` |
| Exercise ID | `wp09-inter-curator-1` |
| Exercise version | `pgx-inter-curator-exercise/1` |
| Content hash | `sha256:7831e1ee275fe0bbae81b66ec66f3dd6f4337661178db70b28e161221307d9ac` |
| Status | **`AWAITING_HUMAN_CURATORS`** |
| Artifacts | [`data/curation/protocol-v1/exercises/`](../../data/curation/protocol-v1/exercises/) |

> **This exercise has not been run.** No curator has been assigned, neither
> response has been completed, and no comparison or adjudication record exists.
> Nothing in this repository can change that, because doing so would assert
> that two scientists reviewed evidence they have not seen.

---

## 1. What the exercise is for

Two scientists answer the same questions independently, from the same evidence,
without seeing each other's answers or the legacy project's previous
conclusion. The two answers are then compared field by field.

**Agreement is not correctness.** Two curators who agree may both be wrong, and
a comparison that treated agreement as validity would manufacture confidence
out of a coincidence. What the exercise actually produces is a map of *where
the protocol is ambiguous* — the fields two competent people read differently
are the fields the protocol has not defined well enough.

## 2. Case selection

Deterministic and by situation, not by sampling. Each selector names a place
where the protocol makes a demand that a straightforward case would not
exercise; the first record satisfying it in natural-key order is taken, and a
record already used is not reused.

Sorting by natural key makes the choice reproducible. Taking the first makes it
independent of how many records happen to match. Several selectors pin a record
type deliberately: natural keys sort `DRUG_LABEL_ANNOTATION` first, so an
unpinned selector would keep returning drug labels and the packet would be
alphabetically skewed rather than representative.

Regenerating the packet from the same evidence build produces byte-identical
output. A packet that varied between runs could not be shown to be
representative rather than convenient.

## 3. The nine cases

| Case | Situation | Record type | Genes | Drugs | Locators | Pubs | Version | Origin | Legacy hint |
|---|---|---|---|---:|---:|---:|---|---|:-:|
| `01` | guideline with stated origin | GUIDELINE | 1 | 5 | 5 | 1 | KNOWN | STATED | – |
| `02` | variant annotation with publication | VARIANT | 1 | 0 | 1 | 1 | MISSING | NOT_STATED | – |
| `03` | multiple publications | GUIDELINE | 1 | 5 | 5 | 2 | KNOWN | STATED | – |
| `04` | multi gene or multi drug | DRUG_LABEL | 2 | 1 | 4 | 0 | UNKNOWN_LEGACY | NOT_STATED | – |
| `05` | unknown source version | VARIANT | 1 | 1 | 2 | 1 | UNKNOWN_LEGACY | NOT_STATED | yes (blinded) |
| `06` | no stated origin | VARIANT | 1 | 1 | 3 | 1 | KNOWN | NOT_STATED | yes (blinded) |
| `07` | pending record type mapping | DRUG_LABEL | 1 | 1 | 2 | 0 | UNKNOWN_LEGACY | NOT_STATED | – |
| `08` | multiple locators | GUIDELINE | 1 | 5 | 5 | 2 | KNOWN | STATED | – |
| `09` | linked legacy hint | GUIDELINE | 1 | 5 | 7 | 3 | KNOWN | STATED | yes (blinded) |

Situations the protocol wants covered that this evidence build does not contain
are **recorded in the packet** rather than silently omitted, under
`unmatched_selectors`. A situation this corpus lacks is a fact about the corpus,
and a packet that quietly dropped it would look more representative than it is.

For this build, every selector matched.

## 4. Blinding

The legacy project's previous conclusion is **withheld**. A case names the
linked proposal identifiers so the hint can be found afterwards, but carries
none of its values — a test asserts that `demo_risk_level`, `risk_meaning`,
`plain_language_mvp`, `effect_direction`, `evidence_strength` and
`usable_for_mvp` appear nowhere in a case payload.

A curator who has seen what the project previously concluded is no longer
forming an independent view of the evidence, and the comparison would be
measuring agreement with the legacy answer rather than between two scientists.
The hint is revealed only after a response is recorded, for migration
comparison.

Three of the nine cases link a legacy hint, so the blinding is genuinely
exercised rather than vacuously true.

## 5. What a curator receives

`curator-a.template.json` and `curator-b.template.json`. Every answer field is
present and empty — present so the curator sees what is asked, empty so nothing
can be mistaken for an answer.

Per case: included evidence, excluded evidence, exclusion reasons, normalized
phenotypes, effect dimension, conclusion state, applicability, conflict state,
insufficiency reasons, rationale notes.

The template carries instructions and **no expected answers**:

> Answer from the cited evidence alone. Do not consult the other curator's
> response. The legacy project's previous conclusion is deliberately withheld.
> `INSUFFICIENT` is a valid answer and is not a weaker form of `SUPPORTED`. If
> evidence conflicts, say so; do not prefer a source by its organisation, its
> recency or its score.

**A blank template is not a response.** `CuratorResponse.is_complete` requires
a name and a non-empty answer for every case, and the comparison refuses
anything less — otherwise two blank forms would report perfect agreement about
nothing.

## 6. The comparison

`compare_responses` reports, per case and per field:

| Field | Compared as |
|---|---|
| included evidence | set — the order a curator listed evidence in is not a disagreement |
| excluded evidence | set |
| exclusion reasons | mapping, per record |
| normalized phenotypes | set |
| effect dimension | exact |
| conclusion state | exact |
| applicability | exact |
| conflict state | exact |
| insufficiency reasons | set |

Both values are reported **even where they agree**. A report showing only
differences would let a reader assume the rest was verified, when what happened
is that two people said the same thing.

It refuses: a blank template, a response to a different exercise, and two
responses by the same person — the last because one person answering twice
produces agreement that measures nothing at all.

It does **not**: decide who is correct, merge responses, generate a consensus,
score agreement, or adjudicate. The published schema forbids `winner`,
`correct_response`, `consensus`, `merged_response`, `agreement_score` and
`validity` outright, so a hand-written comparison claiming one does not
validate.

## 7. Adjudication

Where the two disagree, a named third person decides with written reasons, and
**both original responses are preserved** in the record. The template refuses a
decision with no named adjudicator, and refuses to hold fewer than two
preserved responses.

## 8. To run this exercise

1. Assign two named scientific curators. They must be different people, and
   neither may be the protocol owner.
2. Give each a copy of `curator-a.template.json` / `curator-b.template.json`
   and the sealed evidence build. Do not give them the legacy hints.
3. Each completes every case independently and sets `completed: true` with
   their name.
4. Run `pgx-curation-protocol compare <a> <b>` to produce the field-level
   report.
5. Where they differ, a named adjudicator completes
   `adjudication.template.json`, keeping both responses.
6. Reveal the legacy hints and record what the migration comparison shows.

Steps 1 to 5 require people. Nothing in this repository performs them.
