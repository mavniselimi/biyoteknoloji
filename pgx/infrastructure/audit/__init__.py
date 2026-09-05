# -*- coding: utf-8 -*-
"""The canonical governed audit trail (WP-23).

This repository already had four audit trails when WP-23 began: the release
trail from WP-03, the assessment trail from WP-14, the curation trail from
WP-10 and the hash-linked review trail from WP-22. Each is correct for what it
records and none of them can answer "who did this, under what authentication,
in which session, and can I prove the record was not edited".

This package adds a fifth stream that can, and it adds it **beside** the other
four rather than on top of them. Nothing is migrated, re-hashed or
reinterpreted. A historical row was written under a system with no
authentication, and a backfill that gave it an actor and an assurance level
would be manufacturing provenance - the exact failure an audit trail exists to
prevent.
"""

from __future__ import annotations

__all__ = ["AUDIT_PACKAGE_VERSION"]

AUDIT_PACKAGE_VERSION = "pgx-wp23-governed-audit/1"
