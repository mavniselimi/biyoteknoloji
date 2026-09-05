# -*- coding: utf-8 -*-
"""Whether a set of cases keeps development and holdout apart (WP-18).

``SAFETY-INV-009``. Eight ways a partition can be broken, checked over a whole
case set and **reported together** rather than raised one at a time - somebody
repairing a dataset wants the list, not a sequence of round trips.

The eight are not variations of one check. Each catches a different way the
line gets crossed, and each was chosen because the previous one does not catch
it:

1. *Role overlap.* One identifier, two roles. The obvious one, and the only
   one a naive check finds.
2. *Content duplicate across partitions.* Different identifiers, same
   canonical content. This is what copying a case and renaming it looks like.
3. *Content duplicate within a partition.* Not a leak, but a denominator that
   counts one case twice - so a rate computed over it is wrong in a way that
   flatters or punishes at random.
4. *Derivation family split.* Different identifiers *and* different content,
   from one source vignette by one method. Neither 1 nor 2 sees it, and it
   leaks: whoever wrote the development case has read the source the holdout
   came from.
5. *Holdout derived from development.* Declared by the author, refused here.
6. *Development relabelled as holdout.* Detected against a prior audit's
   record, because relabelling is invisible in a single snapshot - the case
   simply looks like a holdout.
7. *Holdout provenance missing.* Independence that cannot be shown is not
   independence.
8. *Release compatibility conflict.* Cases in one partition written against
   incompatible versions cannot be aggregated into one measurement.

The audit **never reads a payload**. It works on metadata and fingerprints, so
running it does not constitute seeing a holdout, and it can therefore be run by
anybody at any time - including by an author, which is the point.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from pgx.domain.hashing import sha256_digest
from pgx.validation.cases import ValidationCaseMetadata
from pgx.validation.errors import SeparationError
from pgx.validation.vocabulary import (HOLDOUT_ROLES, SEPARATION_ISSUE_CODES,
                                       ValidationCaseRole)

__all__ = [
    "SEPARATION_AUDIT_VERSION",
    "SeparationAudit",
    "SeparationIssue",
    "audit_partition",
    "require_separation",
]

SEPARATION_AUDIT_VERSION = "pgx-wp18-separation-audit/1"


@dataclass(frozen=True, slots=True)
class SeparationIssue:
    """One problem, as a controlled code plus the identifiers involved.

    Carries identifiers and never content. An audit artifact is committed and
    read by people who are not allowed to see holdout payloads, so an issue
    that quoted the duplicated content in order to explain the duplicate would
    publish the very thing it found.
    """

    code: str
    case_ids: Tuple[str, ...]
    detail: str

    def __post_init__(self) -> None:
        if self.code not in SEPARATION_ISSUE_CODES:
            raise SeparationError("unknown separation issue code %r"
                                  % self.code)
        object.__setattr__(self, "case_ids",
                           tuple(sorted(str(item) for item in self.case_ids)))

    def to_json(self) -> Dict[str, Any]:
        return {"code": self.code, "case_ids": list(self.case_ids),
                "meaning": SEPARATION_ISSUE_CODES[self.code],
                "detail": self.detail}


@dataclass(frozen=True, slots=True)
class SeparationAudit:
    """The whole result. Clean or not, and why."""

    issues: Tuple[SeparationIssue, ...]
    development_count: int
    internal_holdout_count: int
    expert_holdout_count: int
    checked_case_count: int
    audit_version: str = SEPARATION_AUDIT_VERSION

    @property
    def is_clean(self) -> bool:
        return not self.issues

    @property
    def issue_codes(self) -> Tuple[str, ...]:
        return tuple(sorted({issue.code for issue in self.issues}))

    def to_json(self) -> Dict[str, Any]:
        return {
            "audit_version": self.audit_version,
            "is_clean": self.is_clean,
            "checked_case_count": self.checked_case_count,
            "development_count": self.development_count,
            "internal_holdout_count": self.internal_holdout_count,
            "expert_holdout_count": self.expert_holdout_count,
            "issue_count": len(self.issues),
            "issue_codes": list(self.issue_codes),
            "issues": [issue.to_json() for issue in self.issues],
            "checked_rules": sorted(SEPARATION_ISSUE_CODES),
        }

    def content_hash(self) -> str:
        return sha256_digest(self.to_json())


def _partition_of(role: ValidationCaseRole) -> str:
    return "DEVELOPMENT" if role is ValidationCaseRole.DEVELOPMENT \
        else "HOLDOUT"


def audit_partition(cases: Sequence[ValidationCaseMetadata], *,
                    previous_roles: Optional[Mapping[str, str]] = None
                    ) -> SeparationAudit:
    """Run every separation rule over a case set. Returns; never raises.

    ``previous_roles`` is an earlier ``{case_id: role}`` record - typically the
    last committed audit artifact. Rule 6 needs it and cannot work without it:
    a case that was development yesterday and claims holdout today looks
    exactly like a case that was always holdout, in any single snapshot.
    """
    issues: List[SeparationIssue] = []
    by_id: Dict[str, List[ValidationCaseMetadata]] = {}
    for case in cases:
        if not isinstance(case, ValidationCaseMetadata):
            raise SeparationError("audit_partition takes "
                                  "ValidationCaseMetadata values")
        by_id.setdefault(case.case_id.value, []).append(case)

    # 1. One identifier, one role.
    for case_id, entries in sorted(by_id.items()):
        roles = {entry.role for entry in entries}
        if len(roles) > 1:
            issues.append(SeparationIssue(
                "ROLE_OVERLAP", (case_id,),
                "holds %s" % ", ".join(sorted(role.value for role in roles))))

    # 2 and 3. Content fingerprints, across and within partitions.
    by_fingerprint: Dict[str, List[ValidationCaseMetadata]] = {}
    for case in cases:
        by_fingerprint.setdefault(case.content_fingerprint, []).append(case)
    for fingerprint, entries in sorted(by_fingerprint.items()):
        identifiers = {entry.case_id.value for entry in entries}
        partitions = {_partition_of(entry.role) for entry in entries}
        if len(identifiers) < 2:
            continue
        if len(partitions) > 1:
            issues.append(SeparationIssue(
                "CONTENT_DUPLICATE_ACROSS_PARTITIONS", tuple(identifiers),
                "one canonical content fingerprint appears in development and "
                "in a holdout partition"))
        else:
            issues.append(SeparationIssue(
                "CONTENT_DUPLICATE_WITHIN_PARTITION", tuple(identifiers),
                "one canonical content fingerprint appears more than once in "
                "the %s partition" % sorted(partitions)[0]))

    # 4. Derivation families split across the line.
    by_family: Dict[str, List[ValidationCaseMetadata]] = {}
    for case in cases:
        by_family.setdefault(case.provenance.family_fingerprint,
                             []).append(case)
    for family, entries in sorted(by_family.items()):
        partitions = {_partition_of(entry.role) for entry in entries}
        if len(partitions) > 1:
            issues.append(SeparationIssue(
                "DERIVATION_FAMILY_SPLIT",
                tuple(entry.case_id.value for entry in entries),
                "one derivation family spans development and a holdout "
                "partition"))

    # 5 and 7. Per-case holdout obligations.
    for case in cases:
        if case.role not in HOLDOUT_ROLES:
            continue
        if case.provenance.derived_from_development:
            issues.append(SeparationIssue(
                "HOLDOUT_DERIVED_FROM_DEVELOPMENT", (case.case_id.value,),
                "declares a development or demo fixture as its source"))
        if case.provenance.source_digest is None and \
                case.provenance.citation is None:
            issues.append(SeparationIssue(
                "HOLDOUT_PROVENANCE_MISSING", (case.case_id.value,),
                "carries neither a source digest nor a citation"))

    # 6. Relabelling, against the previous record.
    for case in cases:
        was = (previous_roles or {}).get(case.case_id.value)
        if was is None or was == case.role.value:
            continue
        if was == ValidationCaseRole.DEVELOPMENT.value and \
                case.role in HOLDOUT_ROLES:
            issues.append(SeparationIssue(
                "DEVELOPMENT_RELABELLED_AS_HOLDOUT", (case.case_id.value,),
                "was recorded as DEVELOPMENT and now claims %s"
                % case.role.value))
        else:
            issues.append(SeparationIssue(
                "ROLE_OVERLAP", (case.case_id.value,),
                "changed role from %s to %s; a case holds one role for its "
                "lifetime" % (was, case.role.value)))

    # 8. Compatibility conflicts inside one partition.
    for partition in ("DEVELOPMENT", "HOLDOUT"):
        members = [case for case in cases
                   if _partition_of(case.role) == partition]
        for index, left in enumerate(members):
            for right in members[index + 1:]:
                if left.compatibility.conflicts_with(right.compatibility):
                    issues.append(SeparationIssue(
                        "RELEASE_COMPATIBILITY_CONFLICT",
                        (left.case_id.value, right.case_id.value),
                        "two cases in the %s partition declare different "
                        "values for a pinned version field" % partition))

    counts = {role: sum(1 for case in cases if case.role is role)
              for role in ValidationCaseRole}
    unique = {issue.to_json()["code"] + "|" + "|".join(issue.case_ids): issue
              for issue in issues}
    return SeparationAudit(
        issues=tuple(sorted(unique.values(),
                            key=lambda item: (item.code, item.case_ids))),
        development_count=counts[ValidationCaseRole.DEVELOPMENT],
        internal_holdout_count=counts[ValidationCaseRole.INTERNAL_HOLDOUT],
        expert_holdout_count=counts[ValidationCaseRole.EXPERT_HOLDOUT],
        checked_case_count=len(cases))


def require_separation(cases: Sequence[ValidationCaseMetadata], *,
                       previous_roles: Optional[Mapping[str, str]] = None
                       ) -> SeparationAudit:
    """Audit, and raise if anything is wrong. For write paths.

    The reporting form is right for a curator inspecting a dataset; this one
    is right for an importer about to persist something, where continuing past
    a separation fault would write the fault to disk.
    """
    audit = audit_partition(cases, previous_roles=previous_roles)
    if not audit.is_clean:
        raise SeparationError(
            "the case set does not keep development and holdout apart: %s"
            % ", ".join(audit.issue_codes), audit.issue_codes)
    return audit
