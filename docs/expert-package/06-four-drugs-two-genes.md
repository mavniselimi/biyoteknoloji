# 6. Four drugs, two genes — the entire scope

## What is covered

| Drug | Gene(s) | Shape | Care setting |
|---|---|---|---|
| amitriptyline | CYP2C19 **and** CYP2D6 | one **joint** rule family, 12 cells | — |
| clopidogrel | CYP2C19 | single-gene, 5 rules | **`ACS_OR_PCI` required** |
| codeine | CYP2D6 | single-gene, 4 rules | — |
| omeprazole | CYP2C19 | single-gene, 5 rules | — |

Twenty-six rules in total: 12 joint, 14 single-gene. Ruleset key
`PGX-CANDIDATE-RULESET-WAVE03B`, content hash `sha256:29ca1949…c7c71a`.

## The attention vocabulary

`HIGH`, `MEDIUM`, `LOW`, `NO_ACTIVE_ATTENTION`, and — only ever as the result
of a refusal — `NOT_ASSESSED`.

`NO_ACTIVE_ATTENTION` is an answer: a rule matched and it records no active
attention. `NOT_ASSESSED` is not an answer: nothing was evaluated. The two are
different fields in the result and different rows in the interface.

## The single-gene tables, in full

**clopidogrel · CYP2C19** (all require `ACS_OR_PCI`)

| Phenotype | Attention |
|---|---|
| POOR | HIGH |
| INTERMEDIATE | HIGH |
| NORMAL | NO_ACTIVE_ATTENTION |
| RAPID | NO_ACTIVE_ATTENTION |
| ULTRARAPID | NO_ACTIVE_ATTENTION |

**codeine · CYP2D6**

| Phenotype | Attention |
|---|---|
| POOR | HIGH |
| INTERMEDIATE | LOW |
| NORMAL | NO_ACTIVE_ATTENTION |
| ULTRARAPID | HIGH |

There is deliberately **no CYP2D6 `RAPID` row**; see section 10.

**omeprazole · CYP2C19**

| Phenotype | Attention |
|---|---|
| POOR | LOW |
| INTERMEDIATE | LOW |
| NORMAL | LOW |
| RAPID | LOW |
| ULTRARAPID | MEDIUM |

Amitriptyline's twelve joint cells are section 8.

## What happens outside the scope

| Situation | Result |
|---|---|
| a drug not in the four | `UNSUPPORTED_DRUG` / `DRUG_NOT_IN_CANONICAL_DATASET` |
| a required gene not observed | `INSUFFICIENT` / `PHENOTYPE_NOT_PROVIDED` |
| an observed combination no rule encodes | `UNSUPPORTED_PHENOTYPE` / `PHENOTYPE_NOT_SUPPORTED` |
| more than one rule matching | `SOURCE_CONFLICT` / `VALIDATED_RULES_CONFLICT` |
| clopidogrel with no declared care setting | `INSUFFICIENT` / `CARE_SETTING_NOT_DECLARED` |

Every one of those returns `NOT_ASSESSED`, not an attention level.

## What the scope is not

Not a claim that these four drugs are the four that matter. They are the four
whose CPIC material one person could capture by hand, correctly, in the time
available. The roadmap beyond them is future scope and is validated by
nothing.
