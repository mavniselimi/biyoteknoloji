# `data/coverage/` — the real coverage registry

This directory is empty of coverage manifests, and that is the correct state.

A `RulesetCoverageManifest` declares what a governed ruleset is able to
evaluate: for each drug, which genes a complete assessment would have to
consider, and which phenotype-specific axes are actually supported by
validated rules with resolvable evidence.

Producing one requires, in order:

1. a curation protocol approved by a named scientific expert — currently
   `AWAITING_EXPERT_REVIEW`;
2. a published canonical dataset — currently `BUILDING`;
3. an evidence build that is not quarantined — currently quarantined and not
   publication-eligible;
4. real identities holding scientific roles — currently none, pending WP-23;
5. validated rules and a frozen ruleset for the manifest to describe —
   currently zero of each;
6. **an expected gene scope, declared by a curator, reviewed independently and
   approved.** This is the one that cannot be automated at all. A scope
   derived from the rules that happen to exist would make every drug look
   exactly as covered as its rules make it, and no gap would ever be visible —
   which is the single thing coverage exists to detect.

`wp13-real-gate-status.json` reports the current state of each, and is
regenerated from the repository rather than written by hand.

The synthetic fixtures used to verify the coverage engine live under
`tests/fixtures/wp13/` and are never written here. A manifest appearing in
this directory would mean somebody had approved a coverage scope.
