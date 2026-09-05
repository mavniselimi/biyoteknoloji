# -*- coding: utf-8 -*-
"""SAFETY-INV-007 negative controls: stores that accept an incomplete bundle.

``LEGACY-BUG-007``: legacy wrote results with no version metadata at all, so a
stored result could not be attributed to the data and rules that produced it.
A result nobody can attribute cannot be reviewed, defended, or retracted.

Every store here is in-memory. Each required field is omitted individually,
because a check that counts fields passes a record missing one and carrying a
duplicate.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping


def complete_record() -> Dict[str, Any]:
    """A record with the whole pinned bundle and both hashes. Synthetic."""
    return {
        "assessment_id": "A-TEST-0001",
        "release_id": "REL-TEST-001",
        "software_version": "0.2.0.dev0",
        "dataset_version": "PGX-DATA-TEST-001",
        "ruleset_version": "1.0.0",
        "input_hash": "0" * 64,
        "output_hash": "1" * 64,
    }


REQUIRED = ("release_id", "software_version", "dataset_version",
            "ruleset_version", "input_hash", "output_hash")


class SafeStore:
    """The safe control: refuses anything the bundle is missing a field of."""

    def __init__(self) -> None:
        self.rows: List[Mapping[str, Any]] = []

    def __call__(self, record: Mapping[str, Any]) -> Mapping[str, Any]:
        missing = [name for name in REQUIRED if not record.get(name)]
        if missing:
            raise ValueError("incomplete release bundle: %s"
                             % ", ".join(missing))
        self.rows.append(dict(record))
        return {"stored": True, "partial": False}


class StoreMissingReleaseField:
    """NC-INV-007-MISSING-RELEASE-FIELD - checks the hashes, not the bundle.

    Somebody added hash verification and stopped there, because the hashes felt
    like the security-relevant part. The release identity is what makes the
    hashes mean anything.
    """

    def __init__(self) -> None:
        self.rows: List[Mapping[str, Any]] = []

    def __call__(self, record: Mapping[str, Any]) -> Mapping[str, Any]:
        for name in ("input_hash", "output_hash"):
            if not record.get(name):
                raise ValueError("missing %s" % name)
        self.rows.append(dict(record))
        return {"stored": True, "partial": False}


class StoreMissingInputHash:
    """NC-INV-007-MISSING-INPUT-HASH - the bundle checked, the input not.

    Without the input hash the stored output cannot be tied to what was asked,
    so re-running to check a result is impossible.
    """

    def __init__(self) -> None:
        self.rows: List[Mapping[str, Any]] = []

    def __call__(self, record: Mapping[str, Any]) -> Mapping[str, Any]:
        missing = [n for n in REQUIRED if n != "input_hash"
                   and not record.get(n)]
        if missing:
            raise ValueError("incomplete: %s" % ", ".join(missing))
        self.rows.append(dict(record))
        return {"stored": True, "partial": False}


class StoreMissingOutputHash:
    """NC-INV-007-MISSING-OUTPUT-HASH - the mirror image, equally fatal."""

    def __init__(self) -> None:
        self.rows: List[Mapping[str, Any]] = []

    def __call__(self, record: Mapping[str, Any]) -> Mapping[str, Any]:
        missing = [n for n in REQUIRED if n != "output_hash"
                   and not record.get(n)]
        if missing:
            raise ValueError("incomplete: %s" % ", ".join(missing))
        self.rows.append(dict(record))
        return {"stored": True, "partial": False}


class PartiallyCommittingStore:
    """NC-INV-007-PARTIAL-PERSISTENCE - the row lands, the children do not.

    The worst outcome of the four, because it looks like success. A stored
    assessment whose findings were abandoned is a result whose trustworthy half
    cannot be told from its other half.
    """

    def __init__(self) -> None:
        self.rows: List[Mapping[str, Any]] = []

    def __call__(self, record: Mapping[str, Any]) -> Mapping[str, Any]:
        missing = [name for name in REQUIRED if not record.get(name)]
        if missing:
            raise ValueError("incomplete: %s" % ", ".join(missing))
        self.rows.append(dict(record))
        return {"stored": True,
                "partial": bool(record.get("_simulate_partial_commit"))}


UNSAFE_SUBJECTS = {
    "NC-INV-007-MISSING-RELEASE-FIELD": StoreMissingReleaseField,
    "NC-INV-007-MISSING-INPUT-HASH": StoreMissingInputHash,
    "NC-INV-007-MISSING-OUTPUT-HASH": StoreMissingOutputHash,
    "NC-INV-007-PARTIAL-PERSISTENCE": PartiallyCommittingStore,
}

SAFE_SUBJECT = SafeStore
