# -*- coding: utf-8 -*-
"""SAFETY-INV-009 negative controls: auditors that miss an overlap.

Independence is the entire evidential value of a holdout set. Once it informs
development, the resulting metric measures memory rather than generalisation,
and no later analysis can undo it - the set is burned.

The safe subject is WP-18's real ``audit_partition``. The unsafe ones are
auditors that check less than it does, each missing one of the three ways a
partition leaks.
"""

from __future__ import annotations

from typing import Any, Sequence


class _Audit:
    """The shape ``audit_partition`` returns, for the doubles."""

    def __init__(self, is_clean: bool, issues: Sequence[str] = ()) -> None:
        self.is_clean = is_clean
        self.issues = tuple(issues)


def _role(case: Any) -> str:
    role = getattr(case, "role", None)
    return getattr(role, "value", str(role))


def _identifier(case: Any) -> str:
    return str(getattr(case, "case_id", ""))


def _content(case: Any) -> str:
    return str(getattr(case, "content_fingerprint", ""))


def _family(case: Any) -> str:
    return str(getattr(case, "derivation_family", ""))


def identifier_only_auditor(cases: Sequence[Any]) -> _Audit:
    """NC-INV-009-CONTENT-DUPLICATE-ACROSS-PARTITIONS misses here.

    Checks that no case *identifier* appears in two roles - which is the check
    everybody writes first, and which two copies of the same case under
    different identifiers walk straight past.
    """
    seen = {}
    for case in cases:
        identifier = _identifier(case)
        if identifier in seen and seen[identifier] != _role(case):
            return _Audit(False, ("ROLE_OVERLAP",))
        seen[identifier] = _role(case)
    return _Audit(True)


def content_blind_to_family_auditor(cases: Sequence[Any]) -> _Audit:
    """NC-INV-009-DERIVATION-FAMILY-SPLIT misses here.

    Catches identical content and distinct identifiers, and still misses two
    *different* cases derived from one source - which neither an identifier nor
    a content check can see, and which leaks the source just as thoroughly.
    """
    by_role = {}
    for case in cases:
        by_role.setdefault(_role(case), set()).add(_content(case))
        by_role.setdefault(_role(case), set())
    development = by_role.get("DEVELOPMENT", set())
    for role, contents in by_role.items():
        if role == "DEVELOPMENT":
            continue
        if development & contents:
            return _Audit(False, ("CONTENT_DUPLICATE_ACROSS_PARTITIONS",))
    return _Audit(True)


def permissive_auditor(cases: Sequence[Any]) -> _Audit:
    """NC-INV-009-ID-IN-TWO-ROLES misses here - it reports everything clean.

    The degenerate case, included because it is what an auditor becomes after
    somebody "temporarily" disables it to unblock a build.
    """
    return _Audit(True)


UNSAFE_SUBJECTS = {
    "NC-INV-009-ID-IN-TWO-ROLES": permissive_auditor,
    "NC-INV-009-CONTENT-DUPLICATE-ACROSS-PARTITIONS": identifier_only_auditor,
    "NC-INV-009-DERIVATION-FAMILY-SPLIT": content_blind_to_family_auditor,
}
