# -*- coding: utf-8 -*-
"""Source conflicts and how they block publication (WP-05).

Standard library plus :mod:`pgx.scientific.models` and
:mod:`pgx.scientific.validation`.

**What a conflict is here.** Two registered sources making incompatible
statements about the same subject - a gene/drug pair, an allele's function, a
phenotype mapping. Not a data-quality problem, not a parsing bug: a genuine
disagreement between two things the project might cite.

**What this module deliberately does not do.** It does not decide who wins.
There is no precedence table, no "CPIC over DPWG", no "the newest publication
supersedes the older one", and no automatic merge. Those would be scientific
judgements, and encoding one here would apply it to every future disagreement
without anybody having agreed to it. The most this module will do unattended is
*detect* that two sources disagree and *refuse to publish* until a named human
has recorded what should happen.

**Detection is deliberately narrow.** :func:`detect_conflicts` compares
statements the caller has already extracted and normalised; it does no
interpretation of scientific text. A pair of statements is in conflict when
their normalised values differ, and the resulting record is ``OPEN`` with
materiality ``UNDETERMINED`` - the two states that block hardest. Deciding a
disagreement is harmless is a review decision, not a default.

**Silent overwrite is impossible by construction.** There is no "merge" or
"prefer" function taking two statements and returning one. The only way one
source supersedes another is a :class:`~pgx.scientific.models.ConflictResolution`
naming the person who decided and why.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from pgx.scientific.errors import ConflictRegistryError
from pgx.scientific.models import (
    SETTLED_CONFLICT_STATUSES,
    ConflictMateriality,
    ConflictStatus,
    SourceConflict,
)
from pgx.scientific.validation import (
    IssueSeverity,
    PolicyIssue,
    PolicyIssueCode,
    sort_issues,
    validate_conflict,
)

__all__ = [
    "ConflictRegister",
    "SourceStatement",
    "conflict_key_for",
    "detect_conflicts",
    "unresolved_material_conflicts",
]


@dataclass(frozen=True, slots=True)
class SourceStatement:
    """One normalised statement one source makes about one subject.

    The caller does the extraction and the normalisation; this type is only the
    shape they are compared in. ``value`` is compared verbatim, so whatever
    normalisation the caller applied is the normalisation that decides whether
    two sources disagree - and it is visible in the record rather than buried in
    a comparison function here.
    """

    subject: str
    source_key: str
    value: str
    detail: Optional[str] = None

    def __post_init__(self) -> None:
        for name in ("subject", "source_key", "value"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ConflictRegistryError(
                    "SourceStatement.%s must be a non-blank string" % name)
        if self.detail is not None and not isinstance(self.detail, str):
            raise ConflictRegistryError("SourceStatement.detail must be a string")


def conflict_key_for(subject: str, source_keys: Iterable[str]) -> str:
    """Return the stable key identifying a disagreement.

    Built from the subject and the sorted source keys, so the same
    disagreement discovered twice produces one record rather than two. Sorting
    is what makes it stable: ``cpic`` disagreeing with ``dpwg`` is the same
    conflict as ``dpwg`` disagreeing with ``cpic``.
    """
    keys = sorted({key for key in source_keys})
    if len(keys) < 2:
        raise ConflictRegistryError(
            "a conflict key needs at least two distinct sources, got %d" % len(keys))
    return "%s::%s" % (subject, "|".join(keys))


def detect_conflicts(
    statements: Sequence[SourceStatement],
    detected_at: Optional[_dt.datetime] = None,
) -> Tuple[SourceConflict, ...]:
    """Group statements by subject and record every disagreement found.

    Two sources agreeing produce nothing. Two sources whose normalised values
    differ produce one ``OPEN`` conflict with materiality ``UNDETERMINED``,
    naming every source involved.

    The same source making two different statements about one subject is *also*
    a conflict - a source that contradicts itself is not a source the project
    can cite without somebody looking - and is recorded with that source named
    once.

    Deterministic: subjects are processed in sorted order and source keys are
    sorted inside each record, so the same input always produces byte-identical
    output.
    """
    by_subject: Dict[str, List[SourceStatement]] = {}
    for statement in statements:
        if not isinstance(statement, SourceStatement):
            raise ConflictRegistryError(
                "detect_conflicts takes SourceStatement records, got %r"
                % type(statement).__name__)
        by_subject.setdefault(statement.subject, []).append(statement)

    conflicts: List[SourceConflict] = []
    for subject in sorted(by_subject):
        group = by_subject[subject]
        values = sorted({statement.value for statement in group})
        if len(values) < 2:
            continue
        source_keys = sorted({statement.source_key for statement in group})
        if len(source_keys) < 2:
            # One source contradicting itself. Name it twice so the record can
            # exist, rather than dropping a real problem for want of a shape.
            source_keys = [source_keys[0], source_keys[0] + " (second statement)"]
        described = "; ".join(
            "%s says %r" % (statement.source_key, statement.value)
            for statement in sorted(group, key=lambda s: (s.source_key, s.value)))
        conflicts.append(SourceConflict(
            conflict_key=conflict_key_for(subject, source_keys),
            subject=subject,
            source_keys=tuple(source_keys),
            description=(
                "%d distinct values recorded for this subject. %s. No "
                "precedence is applied: which statement prevails is a review "
                "decision." % (len(values), described)),
            materiality=ConflictMateriality.UNDETERMINED,
            status=ConflictStatus.OPEN,
            detected_at=detected_at,
        ))
    return tuple(conflicts)


def unresolved_material_conflicts(
    conflicts: Sequence[SourceConflict],
) -> Tuple[SourceConflict, ...]:
    """Conflicts that stop publication, in canonical key order.

    ``UNDETERMINED`` materiality counts as blocking alongside ``MATERIAL``:
    until somebody has judged whether a disagreement could change output, the
    system must assume it could.
    """
    return tuple(sorted(
        (conflict for conflict in conflicts if conflict.blocks_publication),
        key=lambda item: item.conflict_key))


@dataclass(frozen=True)
class ConflictRegister:
    """An immutable set of conflict records with lookup and reporting.

    Immutable because a register that could be edited in place would let a
    caller "resolve" a conflict by removing it. Resolution is expressed by
    building a new record carrying a
    :class:`~pgx.scientific.models.ConflictResolution`; deletion is not a
    resolution.
    """

    conflicts: Tuple[SourceConflict, ...] = ()

    def __post_init__(self) -> None:
        seen = set()
        for conflict in self.conflicts:
            if not isinstance(conflict, SourceConflict):
                raise ConflictRegistryError(
                    "ConflictRegister takes SourceConflict records, got %r"
                    % type(conflict).__name__)
            if conflict.conflict_key in seen:
                raise ConflictRegistryError(
                    "duplicate conflict_key %r" % conflict.conflict_key)
            seen.add(conflict.conflict_key)
        object.__setattr__(
            self, "conflicts",
            tuple(sorted(self.conflicts, key=lambda item: item.conflict_key)))

    def __len__(self) -> int:
        return len(self.conflicts)

    def get(self, conflict_key: str) -> Optional[SourceConflict]:
        for conflict in self.conflicts:
            if conflict.conflict_key == conflict_key:
                return conflict
        return None

    def involving(self, source_key: str) -> Tuple[SourceConflict, ...]:
        """Every conflict this source takes part in."""
        return tuple(c for c in self.conflicts if source_key in c.source_keys)

    def blocking(self) -> Tuple[SourceConflict, ...]:
        """Every conflict that currently stops publication."""
        return unresolved_material_conflicts(self.conflicts)

    def blocking_for(self, source_keys: Sequence[str]) -> Tuple[SourceConflict, ...]:
        """Blocking conflicts touching any of ``source_keys``.

        A release that cites only sources A and B is not held up by an
        unresolved disagreement between C and D.
        """
        wanted = set(source_keys)
        return tuple(c for c in self.blocking() if wanted & set(c.source_keys))

    def settled(self) -> Tuple[SourceConflict, ...]:
        return tuple(c for c in self.conflicts
                     if c.status in SETTLED_CONFLICT_STATUSES)

    def issues(self) -> Tuple[PolicyIssue, ...]:
        """Findings for every conflict, in canonical report order."""
        found: List[PolicyIssue] = []
        for conflict in self.conflicts:
            found.extend(validate_conflict(conflict))
        return sort_issues(found)

    def issues_for(self, source_keys: Sequence[str]) -> Tuple[PolicyIssue, ...]:
        """Findings limited to conflicts touching ``source_keys``."""
        wanted = set(source_keys)
        found: List[PolicyIssue] = []
        for conflict in self.conflicts:
            if wanted & set(conflict.source_keys):
                found.extend(validate_conflict(conflict))
        return sort_issues(found)

    def to_json(self) -> List[Mapping[str, object]]:
        return [conflict.to_json() for conflict in self.conflicts]

    @classmethod
    def from_records(cls, conflicts: Iterable[SourceConflict]) -> "ConflictRegister":
        return cls(tuple(conflicts))


def describe_blocking(conflicts: Sequence[SourceConflict]) -> Tuple[PolicyIssue, ...]:
    """One issue per blocking conflict, for callers that only want the list."""
    return sort_issues(tuple(
        PolicyIssue(
            PolicyIssueCode.CONFLICT_UNRESOLVED, IssueSeverity.BLOCKER,
            conflict.conflict_key,
            "unresolved %s conflict about %s between %s"
            % (conflict.materiality.value, conflict.subject,
               " and ".join(conflict.source_keys)))
        for conflict in unresolved_material_conflicts(conflicts)))
