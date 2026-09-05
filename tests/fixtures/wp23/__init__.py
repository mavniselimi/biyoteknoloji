# -*- coding: utf-8 -*-
"""TEST-ONLY security fixtures (WP-23).

Nothing in this package is a credential. The passwords below are literal
strings in a public repository, the users are invented, and none of them can
authenticate against any deployment: no artifact under ``data/`` contains a
user, and no code path outside the test suite reads this package.

The secret scanner classifies this directory as a **negative-fixture
location** rather than ignoring it. The difference matters: an ignored
directory is one where a real secret could later be committed unnoticed, while
a classified one still reports what it finds and records why the finding is
expected.
"""

from __future__ import annotations

__all__ = ["FIXTURE_MARKER"]

#: Present in every synthetic identifier this package produces, so a value
#: that escaped into an artifact would be recognisable on sight.
FIXTURE_MARKER = "TEST-ONLY"
