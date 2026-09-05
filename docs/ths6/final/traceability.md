# Traceability matrix

Twenty-one rows: fifteen for the Definition of Done bullets and six for the
gates. The machine-readable matrix is
`data/ths6/wp25-traceability-matrix.json`.

Each row names the requirement, where it is written, the modules that
implement it, the tests that exercise them, the evidence it produced, the
claims it supports, the gate it feeds, the result, and — for anything short of
SUPPORTED — what is missing and who owns it.

| Result | Count |
|---|---|
| SUPPORTED | 1 |
| UNSUPPORTED | 20 |

## Nothing dangles

Every evidence identifier resolves in the evidence registry, every claim
identifier in the claim registry, every gate identifier in the gate matrix,
every Definition of Done identifier in the DoD registry, and every
implementation and test path is a file or directory that exists.

That property is what turns this from a table somebody wrote into a table
somebody can check. A matrix citing a deleted module asserts coverage it does
not have, which is worse than no matrix because it looks like diligence.

The check is `pgx-ths6 traceability`, which exits `1` — not `2` — if anything
dangles, because a dangling reference is a defect rather than a blocked
condition.

## A row reports its own requirement, not its gate's verdict

This is a deliberate choice worth stating. An earlier version folded the
gate's conjunction into every row, which made all twenty-one read UNSUPPORTED.
A matrix that distinguishes nothing is one nobody can use to find the next
thing to fix.

So a requirement row is SUPPORTED when *that requirement* is met, whatever
else is blocking the gate it feeds. Gate rows follow their gate. The
conjunction lives in the gate matrix, which is the only place it belongs, and
the unit suite asserts both halves of that split.

## Gap owners

Nine distinct roles own the twenty gaps: WP-25 evidence owner, curation lead,
expert review chair, expert reviewer, platform owner, release approver,
scientific source approver, security owner and validation owner.

No gap is owned by "the team". An unowned gap is one nobody clears, and the
row type refuses to be constructed without an owner when the result is short
of SUPPORTED.
