# 13. The non-independence limitation

This section exists so that section 12's row of 1.0s cannot be quoted without
it.

## The problem, stated plainly

**One process authored the candidate rules, authored the validation cases, and
authored the expected answers for the two partitions that were scored.**

A metric of 1.0 under those conditions says: the ruleset encodes what its
author intended, and the author's expectations agree with the author's
implementation. It does not say the intention was correct.

The catalogue's own manifest carries this in its `limitations` field, so it
travels with the data rather than living only in a report:

> *"no partition here is independent of the build it tests, and a passing
> separation audit says the partitions do not leak into each other, not that
> any of them is independent evidence"*

## What each partition can and cannot support

**`DEVELOPMENT` (34 cases).** Internal consistency only. It can catch a rule
that was mistyped. It cannot catch a rule that was faithfully implemented from
a misread guideline. Never describe a development-partition result as
validation of the science.

**`INTERNAL_HOLDOUT` (21 cases).** Stronger, and still internal. These test
refusal and boundary behaviour that no rule states — a ruleset can encode
every rule correctly and still fail them, which is what makes them worth
running. They were still written by the process that built the rules, by
someone who knew where the boundaries were.

**`EXPERT_HOLDOUT` (12 cases).** Carries no expected answers, because
recording one would have invented the judgment being asked for. Reserved
unopened. This is the only partition capable of producing independent
evidence, and it has produced none, because it has not been reviewed.

## What the separation audit does and does not prove

It proves the partitions do not contaminate each other: no case appears twice,
no holdout case was derived from a development case, no development case was
relabelled. `issue_count: 0`.

It does not prove independence from the build. Nothing in this repository can
prove that, because nothing in this repository was written by anyone else.

## What "unsafe_false_reassurance_count = 0" is worth

The check is real and the definition is narrow: a case where a refusal or a
missing-data condition was presented as an attention level implying safety.
Zero out of 55.

The weakness is not the check. It is the case set. The cases that would
produce a false reassurance are the ones nobody thought of — and the person
who chose the 55 is the person who wrote the code that would have to fail
them. Reserved cases `EXP-11` (`NO_ACTIVE_ATTENTION` beside a refusal) and
`EXP-12` (everything refused) were written to probe exactly this, and they have
no answers.

**Question Q09 asks you to find one.** That is the single most valuable thing
this review could produce.

## The honest description of the current evidence

`INTERNAL_VALIDATION`, or `LITERATURE_DERIVED_VALIDATION`. The catalogue
manifest permits those two descriptions and no others. Not "validated". Not
"clinically validated". Not "independently validated".
