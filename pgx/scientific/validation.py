# -*- coding: utf-8 -*-
"""Source-policy validation with stable issue codes (WP-05).

Standard library plus :mod:`pgx.scientific.models` and :mod:`pgx.domain`.

**Reports, does not raise.** Structural impossibilities are refused at
construction time by :mod:`pgx.scientific.models`; what is left is the far more
common case of a record that is *well-formed and not yet finished*. An operator
completing a source review wants the whole list of what is missing, so this
module collects and returns rather than raising on the first gap.

**Codes, not prose.** Every finding carries a member of :class:`PolicyIssueCode`.
A CI job, a CLI and a human all need to agree on which check failed, and prose
that gets reworded breaks the first two. Details are for people; codes are the
contract.

**Severity is about consequence, not tone.**

* ``BLOCKER`` - publication may not proceed while this stands.
* ``WARNING`` - publication may proceed; somebody should still look.
* ``INFO`` - recorded so the report is complete, not a problem.

The default state of a freshly seeded registry is a long list of ``BLOCKER``
findings. That is the intended output, not a failure of this module: the
project has not yet done source review, and the honest report says so.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Sequence, Tuple

from pgx.domain.enums import SourceRole
from pgx.scientific.models import (
    AUTOMATED_ACQUISITION_MODES,
    APPROVING_STATUSES,
    AcquisitionMode,
    ClaimCategory,
    ConflictMateriality,
    EvidenceVerificationStatus,
    ReuseDimension,
    ReusePermission,
    SourceConflict,
    SourcePolicyRecord,
    SourcePolicyStatus,
)

__all__ = [
    "CORE_PUBLICATION_DIMENSIONS",
    "IssueSeverity",
    "PolicyIssue",
    "PolicyIssueCode",
    "REQUIRED_POLICY_FIELDS",
    "approved_source_keys",
    "blocking_issues",
    "issue_summary",
    "sort_issues",
    "validate_claim_use",
    "validate_conflict",
    "validate_registry",
    "validate_source",
]


class IssueSeverity(str, Enum):
    """What a finding means for the caller."""

    BLOCKER = "BLOCKER"
    WARNING = "WARNING"
    INFO = "INFO"

    def __str__(self) -> str:
        return self.value


class PolicyIssueCode(str, Enum):
    """Stable machine-readable finding codes.

    These are a public contract: renaming one is a breaking change, because a
    downstream check may be keyed on it. New checks add members; existing
    members keep their spelling.
    """

    # -- registry level ---------------------------------------------------
    REGISTRY_EMPTY = "REGISTRY_EMPTY"
    SOURCE_KEY_DUPLICATE = "SOURCE_KEY_DUPLICATE"

    # -- required policy fields ------------------------------------------
    MISSING_VERSION_POLICY = "MISSING_VERSION_POLICY"
    MISSING_CITATION_POLICY = "MISSING_CITATION_POLICY"
    MISSING_LICENSE_IDENTIFIER = "MISSING_LICENSE_IDENTIFIER"

    # -- evidence ---------------------------------------------------------
    MISSING_OFFICIAL_EVIDENCE = "MISSING_OFFICIAL_EVIDENCE"
    EVIDENCE_NOT_VERIFIED = "EVIDENCE_NOT_VERIFIED"
    EVIDENCE_RETRIEVAL_BLOCKED = "EVIDENCE_RETRIEVAL_BLOCKED"
    EVIDENCE_STALE = "EVIDENCE_STALE"

    # -- interpretation and review ---------------------------------------
    NO_INTERPRETATION_RECORDED = "NO_INTERPRETATION_RECORDED"
    NO_REVIEW_RECORDED = "NO_REVIEW_RECORDED"
    REVIEW_NOT_APPROVING = "REVIEW_NOT_APPROVING"
    REVIEW_EXPIRED = "REVIEW_EXPIRED"

    # -- status -----------------------------------------------------------
    SOURCE_PENDING_REVIEW = "SOURCE_PENDING_REVIEW"
    SOURCE_UNDER_REVIEW = "SOURCE_UNDER_REVIEW"
    SOURCE_REJECTED = "SOURCE_REJECTED"
    SOURCE_SUSPENDED = "SOURCE_SUSPENDED"
    SOURCE_INACTIVE = "SOURCE_INACTIVE"
    SOURCE_UNREGISTERED = "SOURCE_UNREGISTERED"

    # -- reuse matrix -----------------------------------------------------
    REUSE_PERMISSION_UNKNOWN = "REUSE_PERMISSION_UNKNOWN"
    REUSE_PERMISSION_PROHIBITED = "REUSE_PERMISSION_PROHIBITED"
    REUSE_PERMISSION_RESTRICTED = "REUSE_PERMISSION_RESTRICTED"

    # -- acquisition ------------------------------------------------------
    ACQUISITION_MODE_NOT_DETERMINED = "ACQUISITION_MODE_NOT_DETERMINED"
    AUTOMATED_ACQUISITION_NOT_PERMITTED = "AUTOMATED_ACQUISITION_NOT_PERMITTED"

    # -- claim categories -------------------------------------------------
    NO_CLAIM_CATEGORY_APPROVED = "NO_CLAIM_CATEGORY_APPROVED"
    CLAIM_CATEGORY_NOT_APPROVED = "CLAIM_CATEGORY_NOT_APPROVED"
    INTERNAL_SYSTEM_NOT_SCIENTIFIC = "INTERNAL_SYSTEM_NOT_SCIENTIFIC"

    # -- conflicts --------------------------------------------------------
    CONFLICT_UNRESOLVED = "CONFLICT_UNRESOLVED"
    CONFLICT_MATERIALITY_UNDETERMINED = "CONFLICT_MATERIALITY_UNDETERMINED"

    # -- legacy inventory --------------------------------------------------
    LEGACY_SOURCE_UNREGISTERED = "LEGACY_SOURCE_UNREGISTERED"

    def __str__(self) -> str:
        return self.value


#: Policy fields ``architecture.md`` section 8.3 requires before publication.
#: Their absence blocks; none of them is ever inferred from anything else.
REQUIRED_POLICY_FIELDS: Tuple[Tuple[str, PolicyIssueCode], ...] = (
    ("version_policy", PolicyIssueCode.MISSING_VERSION_POLICY),
    ("citation_policy", PolicyIssueCode.MISSING_CITATION_POLICY),
    ("license_identifier", PolicyIssueCode.MISSING_LICENSE_IDENTIFIER),
)

#: The reuse dimensions any use of a source inside this project touches, no
#: matter what the output is: the records are stored, read, and turned into
#: derived records. Redistribution and display add more (see
#: :mod:`pgx.scientific.publication_gate`).
CORE_PUBLICATION_DIMENSIONS: Tuple[ReuseDimension, ...] = (
    ReuseDimension.LOCAL_STORAGE,
    ReuseDimension.INTERNAL_ANALYSIS,
    ReuseDimension.DERIVED_WORK_CREATION,
)


@dataclass(frozen=True, slots=True)
class PolicyIssue:
    """One finding about one subject.

    ``subject`` is the source key, conflict key or registry-level marker the
    finding is about, so a report can be grouped without parsing prose.
    """

    code: PolicyIssueCode
    severity: IssueSeverity
    subject: str
    detail: str

    @property
    def is_blocking(self) -> bool:
        return self.severity is IssueSeverity.BLOCKER

    def to_json(self) -> Dict[str, str]:
        return {
            "code": self.code.value,
            "severity": self.severity.value,
            "subject": self.subject,
            "detail": self.detail,
        }

    def render(self) -> str:
        """One line, stable enough to diff between runs."""
        return "%-9s %-38s %-34s %s" % (
            self.severity.value, self.code.value, self.subject, self.detail)


def _sort_key(issue: PolicyIssue) -> Tuple[int, str, str]:
    """Blockers first, then by subject, then by code.

    Fixed so that two runs over the same registry produce the same report and a
    diff between two reports shows a policy change rather than a reordering.
    """
    order = {IssueSeverity.BLOCKER: 0, IssueSeverity.WARNING: 1, IssueSeverity.INFO: 2}
    return (order[issue.severity], issue.subject, issue.code.value)


def sort_issues(issues: Sequence[PolicyIssue]) -> Tuple[PolicyIssue, ...]:
    """Return ``issues`` in canonical report order."""
    return tuple(sorted(issues, key=_sort_key))


# ---------------------------------------------------------------------------
# Source-level checks
# ---------------------------------------------------------------------------


def validate_source(
    record: SourcePolicyRecord,
    now: _dt.datetime,
    required_dimensions: Sequence[ReuseDimension] = CORE_PUBLICATION_DIMENSIONS,
) -> Tuple[PolicyIssue, ...]:
    """Every finding about one source policy record.

    Args:
        record: the policy to check.
        now: the instant to evaluate expiry against. Injected rather than read
            from the wall clock so a test can pin it and a report can state the
            instant it describes.
        required_dimensions: the reuse dimensions this use touches.

    Returns:
        Findings in canonical order. An empty tuple means the record is complete
        *and* approved - which, for a freshly seeded registry, it will not be.
    """
    issues: List[PolicyIssue] = []
    key = record.source_key

    def add(code: PolicyIssueCode, severity: IssueSeverity, detail: str) -> None:
        issues.append(PolicyIssue(code, severity, key, detail))

    # -- 1. Required policy fields ---------------------------------------
    for field_name, code in REQUIRED_POLICY_FIELDS:
        if getattr(record, field_name) is None:
            add(code, IssueSeverity.BLOCKER,
                "%s is not recorded, and is never inferred from a similar "
                "source or from the absence of a restriction." % field_name)

    # -- 2. Evidence -------------------------------------------------------
    official = tuple(item for item in record.evidence if item.is_official)
    if not official:
        add(PolicyIssueCode.MISSING_OFFICIAL_EVIDENCE, IssueSeverity.BLOCKER,
            "no official evidence reference is recorded. Licensing facts must "
            "rest on primary source material, not on summaries of it.")
    elif not any(item.is_verified for item in official):
        add(PolicyIssueCode.EVIDENCE_NOT_VERIFIED, IssueSeverity.BLOCKER,
            "%d official evidence reference(s) are named but none has been "
            "retrieved and hashed by this project. Naming a URL is not reading "
            "the document at it." % len(official))

    # Failed and stale retrievals are reported whatever else the record holds.
    # A record whose only evidence is a blocked attempt still has to say so:
    # burying that inside the "has official evidence" branch would have hidden
    # the most important line in the report.
    for item in record.evidence:
        if item.verification is EvidenceVerificationStatus.BLOCKED:
            add(PolicyIssueCode.EVIDENCE_RETRIEVAL_BLOCKED, IssueSeverity.BLOCKER,
                "retrieval of %s failed: %s. A failed retrieval is an "
                "outstanding obligation, never an approval."
                % (item.official_url or item.evidence_type.value,
                   item.blocked_reason or "no reason recorded"))
        elif item.verification is EvidenceVerificationStatus.STALE:
            add(PolicyIssueCode.EVIDENCE_STALE, IssueSeverity.BLOCKER,
                "the recorded hash for %s no longer matches the source; the "
                "terms may have changed since they were read."
                % (item.official_url or item.evidence_type.value))

    # -- 3. Interpretation and review --------------------------------------
    if record.interpretation is None:
        add(PolicyIssueCode.NO_INTERPRETATION_RECORDED, IssueSeverity.WARNING,
            "the project has recorded no interpretation of this source's terms. "
            "A reviewer will need one, kept separate from the source's wording.")

    if record.review is None:
        add(PolicyIssueCode.NO_REVIEW_RECORDED, IssueSeverity.BLOCKER,
            "no named human has reviewed this source. Approval is a human act; "
            "no configuration value substitutes for it.")
    else:
        if not record.review.is_approving:
            add(PolicyIssueCode.REVIEW_NOT_APPROVING, IssueSeverity.BLOCKER,
                "the recorded review decision is %s by %s"
                % (record.review.decision.value, record.review.reviewer_name))
        if record.review.is_expired(now):
            add(PolicyIssueCode.REVIEW_EXPIRED, IssueSeverity.BLOCKER,
                "the review by %s expired at %s; a licence read once is not a "
                "licence forever."
                % (record.review.reviewer_name,
                   record.review.expires_at.isoformat()
                   if record.review.expires_at else "an unrecorded time"))

    # -- 4. Status ----------------------------------------------------------
    effective = record.effective_status(now)
    status_codes = {
        SourcePolicyStatus.PENDING_REVIEW: (
            PolicyIssueCode.SOURCE_PENDING_REVIEW, IssueSeverity.BLOCKER,
            "the source is awaiting review and may not back published output."),
        SourcePolicyStatus.UNDER_REVIEW: (
            PolicyIssueCode.SOURCE_UNDER_REVIEW, IssueSeverity.BLOCKER,
            "review has started but no decision has been recorded."),
        SourcePolicyStatus.REJECTED: (
            PolicyIssueCode.SOURCE_REJECTED, IssueSeverity.BLOCKER,
            "a reviewer decided this source may not be used."),
        SourcePolicyStatus.SUSPENDED: (
            PolicyIssueCode.SOURCE_SUSPENDED, IssueSeverity.BLOCKER,
            "a previous approval has been withdrawn; treat as unapproved."),
        SourcePolicyStatus.UNREGISTERED: (
            PolicyIssueCode.SOURCE_UNREGISTERED, IssueSeverity.BLOCKER,
            "the source carries no policy at all."),
    }
    if effective in status_codes:
        code, severity, detail = status_codes[effective]
        add(code, severity, detail)

    if not record.active:
        add(PolicyIssueCode.SOURCE_INACTIVE, IssueSeverity.BLOCKER,
            "the source is marked inactive and must not back new output.")

    # -- 5. Reuse matrix ----------------------------------------------------
    for dimension in required_dimensions:
        permission = record.reuse.permission(dimension)
        if permission is ReusePermission.UNKNOWN:
            add(PolicyIssueCode.REUSE_PERMISSION_UNKNOWN, IssueSeverity.BLOCKER,
                "reuse dimension %s is unanswered. Unknown blocks exactly as "
                "prohibited does; the difference is what a reviewer does next."
                % dimension.value)
        elif permission is ReusePermission.PROHIBITED:
            add(PolicyIssueCode.REUSE_PERMISSION_PROHIBITED, IssueSeverity.BLOCKER,
                "the source's own terms prohibit %s." % dimension.value)
        elif permission is ReusePermission.RESTRICTED:
            add(PolicyIssueCode.REUSE_PERMISSION_RESTRICTED, IssueSeverity.BLOCKER,
                "%s is permitted only under recorded conditions; a review must "
                "record that those conditions are met." % dimension.value)

    # -- 6. Acquisition ------------------------------------------------------
    if record.acquisition_mode is AcquisitionMode.NOT_DETERMINED:
        add(PolicyIssueCode.ACQUISITION_MODE_NOT_DETERMINED, IssueSeverity.BLOCKER,
            "no acquisition mode has been decided. How records may be obtained "
            "is a separate question from what may be done with them.")
    elif record.acquisition_mode in AUTOMATED_ACQUISITION_MODES:
        if not record.reuse.is_permitted(ReuseDimension.AUTOMATED_ACQUISITION):
            add(PolicyIssueCode.AUTOMATED_ACQUISITION_NOT_PERMITTED,
                IssueSeverity.BLOCKER,
                "acquisition mode %s is automated, but AUTOMATED_ACQUISITION is "
                "%s in the reuse matrix."
                % (record.acquisition_mode.value,
                   record.reuse.permission(ReuseDimension.AUTOMATED_ACQUISITION).value))

    # -- 7. Claim categories -------------------------------------------------
    if record.role is SourceRole.INTERNAL_SYSTEM:
        add(PolicyIssueCode.INTERNAL_SYSTEM_NOT_SCIENTIFIC, IssueSeverity.INFO,
            "INTERNAL_SYSTEM: technical bookkeeping only, never scientific "
            "evidence for a release.")
    elif not record.permitted_claim_categories:
        add(PolicyIssueCode.NO_CLAIM_CATEGORY_APPROVED, IssueSeverity.BLOCKER,
            "no claim category has been approved for this source, so there is "
            "nothing it may be cited for.")

    return sort_issues(issues)


def validate_claim_use(
    record: SourcePolicyRecord, category: ClaimCategory, now: _dt.datetime
) -> Tuple[PolicyIssue, ...]:
    """Findings about citing ``record`` for one specific claim category."""
    if record.may_support_claim(category, now):
        return ()
    return (PolicyIssue(
        PolicyIssueCode.CLAIM_CATEGORY_NOT_APPROVED, IssueSeverity.BLOCKER,
        record.source_key,
        "the source is not approved to support %s (status %s, approved "
        "categories: %s)"
        % (category.value, record.effective_status(now).value,
           ", ".join(c.value for c in record.permitted_claim_categories) or "none")),)


# ---------------------------------------------------------------------------
# Conflict-level checks
# ---------------------------------------------------------------------------


def validate_conflict(conflict: SourceConflict) -> Tuple[PolicyIssue, ...]:
    """Findings about one recorded source conflict."""
    issues: List[PolicyIssue] = []
    if conflict.materiality is ConflictMateriality.UNDETERMINED and not conflict.is_settled:
        issues.append(PolicyIssue(
            PolicyIssueCode.CONFLICT_MATERIALITY_UNDETERMINED, IssueSeverity.BLOCKER,
            conflict.conflict_key,
            "nobody has decided whether this disagreement could change output. "
            "Deciding it does not matter is itself a review decision."))
    if conflict.blocks_publication:
        issues.append(PolicyIssue(
            PolicyIssueCode.CONFLICT_UNRESOLVED, IssueSeverity.BLOCKER,
            conflict.conflict_key,
            "%s disagree about %s and the conflict is %s"
            % (" and ".join(conflict.source_keys), conflict.subject,
               conflict.status.value)))
    return sort_issues(issues)


# ---------------------------------------------------------------------------
# Registry-level checks
# ---------------------------------------------------------------------------


def validate_registry(
    registry: Any,
    now: _dt.datetime,
    required_dimensions: Sequence[ReuseDimension] = CORE_PUBLICATION_DIMENSIONS,
) -> Tuple[PolicyIssue, ...]:
    """Every finding about every record and conflict in ``registry``.

    ``registry`` is typed loosely to keep this module independent of
    :mod:`pgx.scientific.policy`; anything exposing ``records`` and
    ``conflicts`` works, which is what lets a test build one inline.
    """
    issues: List[PolicyIssue] = []
    records: Sequence[SourcePolicyRecord] = tuple(registry.records)
    if not records:
        issues.append(PolicyIssue(
            PolicyIssueCode.REGISTRY_EMPTY, IssueSeverity.BLOCKER, "registry",
            "the source registry is empty. An empty registry permits nothing; "
            "it does not permit everything."))
    for record in records:
        issues.extend(validate_source(record, now, required_dimensions))
    for conflict in tuple(getattr(registry, "conflicts", ())):
        issues.extend(validate_conflict(conflict))
    return sort_issues(issues)


def blocking_issues(issues: Sequence[PolicyIssue]) -> Tuple[PolicyIssue, ...]:
    """Only the findings that stop publication."""
    return tuple(issue for issue in issues if issue.is_blocking)


def issue_summary(issues: Sequence[PolicyIssue]) -> Dict[str, int]:
    """Counts per severity, with every severity present even at zero.

    A report that omits ``"BLOCKER": 0`` makes a reader wonder whether the check
    ran at all.
    """
    counts = {severity.value: 0 for severity in IssueSeverity}
    for issue in issues:
        counts[issue.severity.value] += 1
    return counts


def approved_source_keys(
    registry: Any, now: _dt.datetime
) -> Tuple[str, ...]:
    """Sources whose approval is genuine and in force at ``now``.

    Usually empty. That is the correct answer for a project that has not yet
    run source review, and it is what makes the default state publish nothing.
    """
    keys = []
    for record in tuple(registry.records):
        if (record.active
                and record.effective_status(now) in APPROVING_STATUSES
                and record.is_approved):
            keys.append(record.source_key)
    return tuple(sorted(keys))
