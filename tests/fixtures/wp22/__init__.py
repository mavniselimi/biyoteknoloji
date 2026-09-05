# -*- coding: utf-8 -*-
"""TEST-ONLY material for WP-22.

**Nothing here is a human opinion.** The approved protocol, the expert
holdout case, the reviewer principal, the pinned release, the system result
and every completed review are invented so the blind workflow can be exercised
end to end and shown to work.

That distinction is the one this package exists to keep visible. A completed
review in this fixture set proves that the software records a decision
correctly. It does not prove, suggest or contribute to any claim that a
clinician looked at anything - and a repository that let the two blur would be
one where a green test suite reads as a validated system.

Three guards:

- every identifier begins ``TEST-ONLY-``, so a fixture value appearing in a
  committed artifact is greppable and a test greps for it;
- production code never imports ``tests.*``; the fixtures are injected through
  the ports the service declares, and a boundary test reads the AST;
- the approved protocol here is constructed in Python with invented
  signatories. ``pgx.expert_review.protocol.load_protocol`` has no code path
  that reads signatories from disk, so no file can approve the real protocol.
"""

from __future__ import annotations

TEST_ONLY_MARKER = "TEST-ONLY"
