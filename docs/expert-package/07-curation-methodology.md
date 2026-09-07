# 7. Curation methodology — how a guideline row became a rule

Protocol: `docs/scientific/curation-protocol-v1.md`,
`docs/scientific/curation-field-dictionary.md`,
`docs/scientific/rule-authoring-and-approval.md`.

## The path

```
guideline table row
   │ read by a person from a manually downloaded document
   ▼
capture row              capture:row:<gene>|<drug>|<source phenotype>|<context>
   │ normalised: source phenotype term → project Phenotype member
   ▼
interpretation           CANDIDATE-INTERP:<drug>|<gene>|<PHENOTYPE>
   │ content-hashed; carries citation and source annotation id
   ▼
candidate rule           CANDIDATE-RULE:<drug>|<gene>|<PHENOTYPE>
   │ condition (gene, phenotype operator, values, care setting)
   │ outcome  (attention level, rationale reference)
   ▼
frozen candidate ruleset PGX-CANDIDATE-RULESET-WAVE03B
   ▼
active candidate release PGX-CANDIDATE-REL-20260906-001
```

Each rule stores its own provenance block: the canonical build key and hash,
the capture record identifiers, the capture snapshot manifest hash, the
citations, the dataset id, the DQ decision id, the interpretation key and
hash, the source policy hash — and `source_policy_status: PENDING_REVIEW`,
carried on every rule rather than mentioned once in a report.

## Who did the curation

An automated pass. The ruleset manifest says so in the field a human curator's
name would occupy:

```json
"built_by": "pgx-closure-wave03b automated curation pass (NOT A HUMAN CURATOR)"
```

There is no WP-10 approval envelope on any rule, because no envelope exists —
approval envelopes require an approving curator, and there was none. The
ruleset's provenance file states this rather than leaving the absence to be
noticed.

## The rule condition grammar

Two condition kinds:

- `PGX_AXIS` — one gene, one phenotype matcher (`EXACT` over one value, or
  `ONE_OF` over several), optionally a required care setting.
- `PGX_JOINT_AXIS` — a list of genes, each with its own matcher. **All** must
  match.

`INDETERMINATE` is refused as a rule phenotype by the grammar itself. It
describes the input, not a phenotype a rule can be about, so a rule that named
it could never be correct.

## Authority states, and what they mean

Each rule carries `authority_state: SOURCE_GROUNDED_INTERNAL_DECISION`. Read
it as two claims: the rule is traceable to an approved source
(*source-grounded*), and the decision to encode it that way was made inside
this project and by nobody else (*internal decision*). It is not
`SOURCE_APPROVED`, and there is no state above it that this build has reached.

## Where you should be sceptical

Three places, and they are the reason for questions **Q02**, **Q05** and
**Q07**:

1. **The normalisation step.** A source term became a project `Phenotype`
   member. Thirteen terms were refused rather than mapped (section 10) — but
   the ones that *were* mapped were mapped by the same process, with no second
   reader.
2. **The attention level.** A guideline's recommendation text became one of
   five attention levels. That compression is a scientific act performed by an
   automated pass, and the mapping table it used is not itself in any
   guideline.
3. **Ordering.** `HIGH` for clopidogrel POOR and `HIGH` for clopidogrel
   INTERMEDIATE are the same level for two clinically different situations.
   Whether the five-level vocabulary is too coarse is a fair criticism.
