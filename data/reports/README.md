# Published reports

**This directory is empty, and a test asserts that it stays empty.**

A document here would mean a report of a real assessment had been published.
None has been, and none can be: the claim boundary is
`DRAFT / AWAITING HUMAN AND SCIENTIFIC REVIEW`, no assessment is stored in
this repository, and no frozen ruleset, approved coverage manifest or active
release exists upstream. `pgx-report gate-status` reads all of that off the
repository and reports it.

Synthetic reports are never written here. `pgx-report render-synthetic` has no
default destination and refuses this one by name: a synthetic document filed
where real documents are read from is a synthetic document somebody will cite.
Synthetic fixtures live under `tests/fixtures/wp15/`.

`wp15-real-gate-status.json`, when present, is the machine-readable gate
status. It is the one file this directory is allowed to hold, and it exists to
record that there is nothing else here.
