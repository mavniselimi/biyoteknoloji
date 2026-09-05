# -*- coding: utf-8 -*-
"""Test doubles for WP-24.

Deliberately small and deliberately unconvincing. Nothing here resembles a
real release, a real image or a real deployment closely enough that a document
built from it could be mistaken for one: every identifier says ``fixture`` and
every result these produce is labelled ``TEST_ONLY_REHEARSAL`` by the caller.

The in-memory session is the interesting one. It records the order of
``flush``, ``commit``, ``rollback`` and ``close`` so a test can assert the
*transaction shape* rather than the final state - which is the only way to
tell "the audit append and the change committed together" apart from "both
happened to succeed".
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Dict, List, Optional

FIXTURE_RELEASE = {
    "release_id": "REL-FIXTURE-0000",
    "release_manifest_hash": "sha256:" + "f" * 64,
    "software_id": "SW-FIXTURE",
    "dataset_id": "DS-FIXTURE",
    "ruleset_id": "RS-FIXTURE",
}

FIXTURE_PREVIOUS_IMAGE = {
    "reference": "pgx-platform:fixture-previous",
    "image_id": "sha256:" + "a" * 64,
}

FIXTURE_CANDIDATE_IMAGE = {
    "reference": "pgx-platform:fixture-candidate",
    "image_id": "sha256:" + "b" * 64,
}


class RecordingSession:
    """A SQLAlchemy-shaped session that records what happened to it."""

    def __init__(self, *, fail_on_flush: bool = False) -> None:
        self.calls: List[str] = []
        self.added: List[Any] = []
        self.closed = False
        self.fail_on_flush = fail_on_flush

    def add(self, row: Any) -> None:
        self.added.append(row)
        self.calls.append("add")

    def flush(self) -> None:
        self.calls.append("flush")
        if self.fail_on_flush:
            raise RuntimeError("the store is unavailable")

    def commit(self) -> None:
        self.calls.append("commit")

    def rollback(self) -> None:
        self.calls.append("rollback")

    def close(self) -> None:
        self.calls.append("close")
        self.closed = True

    def execute(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append("execute")
        return _Result()


class _Result:
    def scalar_one(self) -> int:
        return 1

    def scalars(self) -> Any:
        return iter(())

    def scalar_one_or_none(self) -> Any:
        return None


class CountingSessionFactory:
    """Hands out a fresh session per call and remembers every one."""

    def __init__(self, *, fail_on_flush: bool = False) -> None:
        self.sessions: List[RecordingSession] = []
        self.fail_on_flush = fail_on_flush

    def __call__(self) -> RecordingSession:
        session = RecordingSession(fail_on_flush=self.fail_on_flush)
        self.sessions.append(session)
        return session


class FakeRateLimitStore:
    """Counts hits in memory, and can be told to fail."""

    def __init__(self) -> None:
        self.counts: Dict[Any, int] = {}
        self.fail_next = False

    def hit(self, *, policy_id: str, key: str,
            window_start: _dt.datetime) -> int:
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("backend unavailable")
        bucket = (policy_id, key, window_start.isoformat())
        self.counts[bucket] = self.counts.get(bucket, 0) + 1
        return self.counts[bucket]


def fake_runner(responses: Dict[str, Any]):
    """A subprocess replacement keyed on the first argument.

    Returns ``(returncode, text)``. Used to exercise the container and
    packaging code paths without a container runtime - which is the whole
    point: those paths have to be tested on hosts that do not have one, or
    they are only ever tested where they already work.
    """

    def _run(argv, **kwargs):
        key = " ".join(str(item) for item in argv[:2])
        for prefix, value in responses.items():
            if key.startswith(prefix):
                return value
        return (127, "not configured in this fixture")

    return _run


def module_source(module: Any) -> str:
    """Read a module's own source, with the handle closed.

    A helper rather than an inline ``io.open(...).read()`` because the suite
    runs with ``-W error::ResourceWarning``: an unclosed handle is a test
    failure here, which is the policy working.
    """
    import io

    with io.open(module.__file__, encoding="utf-8") as handle:
        return handle.read()
