# H04 - dataset quality decision: what has to be decided

A dataset does not become usable because a report says its numbers are fine. Somebody has to read the report and decide, and this checkpoint is where that decision is recorded. WP-C06 asked for the mechanism; Wave 2 audited what already existed, implemented the parts that were genuinely missing, and left the rest alone.

## What already worked

WP-07 has carried the transition a decision causes since it was written: `BUILDING -> QUALITY_CHECKED`, guarded inside the transaction, refusing a replay, verifying the build's digests and its schemas before opening one, and refusing to invent a reviewer. None of that was rebuilt.

## What was missing

The decision itself. `QualityCheckRequest` has no verdict field, so the only outcome it could express was approval - a data owner who read the report and said no had nowhere to put that. Nothing recorded the reviewer's role, nothing bound the decision to the source policy in force, and the only record of a decision was an audit row in a database nobody in this environment can reach.

The full audit is `evidence-table.csv`, one row per requirement, including the rows where the answer was that nothing was missing.

## What is decided here

Not the quality of any dataset - there is no legitimate dataset to decide about yet. What this checkpoint needs first is a named data owner and a decision about whether a role may be recorded before there is any authority to check it against.

