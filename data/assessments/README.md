# `data/assessments/`

Empty of assessments, and a test asserts it stays that way.

An assessment record here would mean this system had executed one against real
data. It has not, and it cannot: the claim boundary is
`DRAFT / AWAITING HUMAN AND SCIENTIFIC REVIEW`, the curation protocol is
`AWAITING_EXPERT_REVIEW`, the canonical dataset is `BUILDING`, the evidence
build is quarantined, there are no validated rules, no frozen ruleset, no
approved coverage manifest and no active release.

`wp14-real-gate-status.json` reports each of those, who owns clearing it, and
what clearing it would unblock. It is generated from the repository rather than
written by hand, so it cannot drift from what is actually here.

## What would have to be true first

1. Named humans approve the intended purpose, moving the claim boundary off
   `DRAFT`.
2. A named scientific expert approves the curation protocol against its
   content hash.
3. The canonical dataset is quality-checked and published.
4. The evidence build is reviewed and its quarantine labels removed.
5. WP-23 supplies authentication and somebody assigns scientific roles.
6. Rules are authored, independently validated, and a ruleset is frozen.
7. A coverage scope is declared, reviewed and approved per drug.
8. A release bundle pinning that software, dataset and ruleset is registered
   and activated.

None of these can be done by writing code, which is why none of them has been.

## Synthetic assessments

The WP-14 engine and service are exercised end to end, but only against
fixtures under `tests/fixtures/wp14/`, which are marked SYNTHETIC / TEST ONLY /
NOT CLINICAL DATA / NOT FOR REAL ASSESSMENT and are never written here. The
production gate scanner skips this directory's own status file by name and
counts nothing else, so a synthetic run cannot make the count non-zero.
