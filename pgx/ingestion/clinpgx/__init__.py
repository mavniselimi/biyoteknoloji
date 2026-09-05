# -*- coding: utf-8 -*-
"""ClinPGx source adapter (WP-04).

The endpoint knowledge here is ported from ``clinpgx_probe.py`` and
``clinpgx_probe_v2.py``. What was ported, what was deliberately left behind, and
what still needs live confirmation are written down in
``docs/migration/clinpgx-probe-intent.md``.

No module in this package makes a network call at import time, and nothing in
WP-04 made one at all: every adapter test runs against a scripted fake
transport.
"""
