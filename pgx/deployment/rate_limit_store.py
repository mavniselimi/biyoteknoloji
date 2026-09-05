# -*- coding: utf-8 -*-
"""The PostgreSQL rate-limit counter (WP-24).

One statement. That is the whole design, and it is worth stating why.

The obvious implementation reads the current count, decides, and writes the
new one. Under two concurrent logins that sequence interleaves as read(4),
read(4), write(5), write(5) - and the fifth and sixth attempts both pass a
limit of five. The window in which that happens is exactly the window a
credential-stuffing client operates in, so the race's losing side is precisely
the request the limiter exists to stop.

``INSERT ... ON CONFLICT DO UPDATE ... RETURNING`` has no such window. The
second writer blocks on the row lock the first writer holds, then increments
the value the first writer committed, and receives its own total back. No
read, no decision, no write - one statement that counts and reports.

Two further properties, both deliberate:

**It commits its own transaction.** A rate-limit hit is not part of the
governed change it is metering. A failed login must still be counted, and if
the counter shared the login's transaction the rollback that refuses the login
would also erase the evidence that it was attempted - which turns the limiter
off for exactly the caller it is watching. This is the one place in WP-24
where a separate transaction is correct, and it is separate on purpose.

**It never sees an identity.** ``RateLimiter`` digests the key before calling
here, so this module handles ``sha256:...`` and could not log a username if it
tried.
"""

from __future__ import annotations

import datetime as _dt
import uuid
from typing import Any, Optional

from pgx.security.rate_limit import RateLimitStore

__all__ = ["ATOMIC_HIT_SQL", "SqlAlchemyRateLimitStore"]

#: The statement. Written out rather than composed by the ORM so that the
#: atomicity is visible to a reviewer and assertable by a test: a future
#: refactor that replaced this with a query and a flush would change the
#: concurrency guarantee without changing any type signature.
#:
#: ``EXCLUDED`` is not used for the count: the new count must be derived from
#: the row already in the table, not from the value this statement proposed,
#: because the proposed value is always 1.
ATOMIC_HIT_SQL = """
INSERT INTO security_rate_limit_counters
        (id, policy_id, key_digest, window_start, hit_count)
VALUES  (:row_id, :policy_id, :key_digest, :window_start, 1)
ON CONFLICT ON CONSTRAINT uq_security_rate_limit_counters_bucket
DO UPDATE SET hit_count = security_rate_limit_counters.hit_count + 1
RETURNING hit_count
"""


class SqlAlchemyRateLimitStore(RateLimitStore):
    """Count one hit in one window, atomically, in its own transaction.

    ``session_factory`` rather than a session: this store outlives any single
    request and must not borrow a request's transaction, for the reason in the
    module docstring. Each call opens a session, runs one statement, commits
    and closes.

    Any failure propagates. ``RateLimiter.check`` turns every exception into
    ``RATE_LIMIT_UNAVAILABLE`` and denies, so a database that cannot count is
    a database that refuses the attempt - never one that waves it through.
    """

    def __init__(self, session_factory: Any,
                 *, id_factory: Optional[Any] = None) -> None:
        self._session_factory = session_factory
        self._id_factory = id_factory or uuid.uuid4

    def hit(self, *, policy_id: str, key: str,
            window_start: _dt.datetime) -> int:
        from sqlalchemy import text

        session = self._session_factory()
        try:
            count = session.execute(
                text(ATOMIC_HIT_SQL),
                {"row_id": self._id_factory(), "policy_id": policy_id,
                 "key_digest": key, "window_start": window_start},
            ).scalar_one()
            session.commit()
            return int(count)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
