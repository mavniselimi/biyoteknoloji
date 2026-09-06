# H04 - risk summary

This is the control that stops a generated report from becoming an approval by default.

## If this is decided wrongly

- **A passing gate read as an approval.** The report says the numbers are within contract. It says nothing about whether the data should be used, and the two are easy to conflate.
- **A decision nobody can attribute.** A name with no role behind it cannot be checked against any authority, and reads as accountability without being it.
- **A silent rejection.** A system where saying no leaves no trace shows only approvals, which makes the record of decisions systematically optimistic.
- **An approval that outlived its subject.** A regenerated report is a different report; the binding exists so an old approval cannot quietly attach to it.

## If this is not decided at all

- No dataset can become `QUALITY_CHECKED`, so none can be published, so no release can be activated. That is the current state and it is correct: there is no legitimate dataset to decide about.

