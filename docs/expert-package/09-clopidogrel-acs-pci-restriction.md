# 9. Clopidogrel and the ACS/PCI restriction

## The rule

Every clopidogrel rule carries `care_setting: ACS_OR_PCI`. The ruleset
declares the requirement separately as well:

```json
"care_setting_required": { "DRUG:clopidogrel": ["ACS_OR_PCI"] }
```

If the request does not declare that care setting, clopidogrel is **refused**
before any phenotype is consulted:

```
status        INSUFFICIENT
attention     NOT_ASSESSED
reason        CARE_SETTING_NOT_DECLARED
```

The refusal happens whether or not CYP2C19 was observed, and whether or not
the observed phenotype would have produced `NO_ACTIVE_ATTENTION`. Nothing is
evaluated.

## Why

Also a preserved owner decision from the H01 record: clopidogrel *"stays
restricted to an explicitly represented ACS/PCI context"*. The CPIC
recommendation for CYP2C19 and clopidogrel is written for acute coronary
syndrome and percutaneous coronary intervention. Applying it silently to a
patient taking clopidogrel for another indication would extend a guideline
past what it says.

## Why it is never inferred

The care setting is a declared input from a closed vocabulary. It is not
derived from the drug list, not defaulted, and — importantly for the
interface — **not read from the form when the runtime track is deciding
anything**. A missing care setting produces a refusal, never an assumption.

This is the single most visible refusal in the product, and the demonstration
walks it deliberately: clopidogrel with no care setting declared refuses;
the same request with `ACS_OR_PCI` declared is answered.

## The known asymmetry

A care setting supplied for a drug that does not need one is **ignored**, not
refused. Amitriptyline and omeprazole with `ACS_OR_PCI` declared are answered
as though it were absent. Reserved case `PGX-VAL-W4-EXP-10` asks whether that
is right, or whether an irrelevant qualifier should itself be refused.

The project's own view is that ignoring it is correct — the qualifier changes
nothing about those axes — but the argument for refusing is that silently
accepting an input the software does not use trains a user to supply inputs
that do nothing. No decision has been made; it is a question for you.

## What to criticise

- Is `ACS_OR_PCI` the right single setting, or should the vocabulary
  distinguish ACS from elective PCI?
- Is refusing without it correct, or should the product answer with a
  prominent "this recommendation is for ACS/PCI only" qualifier instead?
- Does refusing clopidogrel beside three answered drugs read as *"clopidogrel
  is fine"* to a hurried reader? Reserved case `EXP-11` is exactly this.

Question **Q07** in section 16.
