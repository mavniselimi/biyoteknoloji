# SYNTHETIC WP-15 report fixtures. TEST ONLY. NOT CLINICAL DATA.

**NOT FOR REAL ASSESSMENT.** Everything in this directory is invented so the
reporting pipeline can be exercised while no real assessment exists.

`synthetic-canonical-result.json` is one canonical assessment result produced
by running the synthetic WP-11 → WP-14 chain in memory. Its genes, drugs,
rules, evidence identifiers and approvals are all invented, its case label
says so, and nothing in it was reviewed by anybody. It is not a statement
about any medicine.

It lives here, under `tests/`, rather than in `data/`, so that no synthetic
document sits in a directory somebody reads real output from. `pgx-report
render-synthetic` has no default source and no default destination for the
same reason: both must be named on the command line.
