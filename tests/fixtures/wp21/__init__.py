# -*- coding: utf-8 -*-
"""TEST-ONLY synthetic material for WP-21.

**Nothing in this package is real.** The release, the dataset, the ruleset,
the cases, the observations and the reference judgments are all invented so
that the benchmark engine can be exercised end to end and shown to produce a
numerical validation table.

They exist because the alternative is worse. Without them the only evidence
that the metric machinery works would be the machinery reporting that it could
not run - which is indistinguishable from machinery that does not work at all.

Three guards keep this material out of anything real:

- every identifier here starts with ``TEST-ONLY-`` or ``SYNTH-``, so a value
  from this package appearing in a committed artifact is greppable;
- production code never imports ``tests.*``; the fixtures are injected through
  the ports the engine declares, and a boundary test asserts the direction;
- the real report is built by a different function
  (``build_real_report``) which takes no ports at all.
"""

from __future__ import annotations

TEST_ONLY_MARKER = "TEST-ONLY"
