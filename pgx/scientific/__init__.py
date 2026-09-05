# -*- coding: utf-8 -*-
"""Scientific source governance (WP-05).

This package decides *whether* a source may be used, and for what. It never
decides what a source means.

The boundary, stated plainly because it is the one most likely to erode: nothing
here interprets pharmacogenomic guidance, ranks the scientific quality of two
sources, resolves a disagreement between them, or approves anything. What it
does is hold the project's recorded position on each source - licensing, reuse
permissions, acquisition mode, citation and version policy, the primary evidence
those rest on, who reviewed them and when - and refuse to publish while that
position is missing.

**Five things kept separate**, because collapsing them is how a project ends up
believing it has permission it never obtained:

1. what the source published;
2. the source's own licensing or terms statements;
3. this project's interpretation of those statements;
4. this project's approval decision, made by a named human;
5. the claim categories the source may support once approved.

**Fail closed.** Missing licensing, provenance, citation, versioning or approval
information blocks publication. An unregistered source has no permissions rather
than unlimited ones; an unanswered reuse question blocks exactly as a prohibited
one does; an unresolved conflict blocks even when nobody has yet judged whether
it matters. The default state of this repository is therefore "publishes
nothing", and that is correct: no human has reviewed any source yet.

**What this package will not do.** It contains no precedence table, so it will
never silently prefer CPIC over DPWG or a label over a guideline. It contains no
way for a configuration file to approve a source: an approving status without a
review record naming a human, an instant and cited evidence raises rather than
loads. And it makes no legal conclusions - a project interpretation is recorded
as an interpretation, by name, and is not legal advice.

Modules:

* :mod:`~pgx.scientific.models` - controlled vocabularies and records.
* :mod:`~pgx.scientific.policy` - loading and querying the source registry.
* :mod:`~pgx.scientific.validation` - stable-coded findings about a policy.
* :mod:`~pgx.scientific.conflict` - detecting and blocking on disagreements.
* :mod:`~pgx.scientific.publication_gate` - the deterministic publish decision.
* :mod:`~pgx.scientific.inventory` - what the frozen legacy files already cite.
* :mod:`~pgx.scientific.ports` - persistence ports for the operational record.
* :mod:`~pgx.scientific.errors` - typed governance failures.
"""
