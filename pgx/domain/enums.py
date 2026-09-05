# -*- coding: utf-8 -*-
"""Domain enumerations (WP-02).

Standard library only. These are *vocabulary*, not behaviour: no matching, no
scoring, and no scientific logic lives here. Assessment semantics arrive in
WP-12 to WP-14.

Two properties are load-bearing and are pinned by tests:

* ``RAPID`` and ``ULTRARAPID`` are distinct and are never aliased
  (``SAFETY-INV-004``, ``LEGACY-BUG-001``).
* ``AttentionLevel`` carries no numeric score and no ordering, so
  ``NOT_ASSESSED`` can never be compared against ``LOW`` (``SAFETY-INV-001``,
  ``LEGACY-BUG-002``).
"""

from __future__ import annotations

from enum import Enum

__all__ = [
    "AttentionLevel",
    "AuditAction",
    "CoverageReasonCode",
    "CoverageStatus",
    "CurationStatus",
    "DatasetStatus",
    "Phenotype",
    "ReleaseStatus",
    "RuleStatus",
    "RulesetStatus",
    "SourceRole",
]


class _DomainEnum(str, Enum):
    """String-valued enum with a stable representation and no ordering.

    Inheriting ``str`` keeps transport and JSON stable. Ordering comparisons are
    explicitly disabled so that no caller can accidentally treat a lifecycle or
    attention value as a magnitude.
    """

    def __str__(self) -> str:
        return self.value

    def __lt__(self, other: object) -> bool:  # pragma: no cover - guard
        raise TypeError(
            "%s values are not ordered; comparing them as magnitudes is a "
            "domain error" % type(self).__name__
        )

    __le__ = __lt__
    __gt__ = __lt__
    __ge__ = __lt__


class SourceRole(_DomainEnum):
    """Role a registered source plays in the scientific pipeline."""

    PRIMARY_GUIDELINE = "PRIMARY_GUIDELINE"
    SUPPORTING_ANNOTATION = "SUPPORTING_ANNOTATION"
    REFERENCE_ONLY = "REFERENCE_ONLY"
    #: Technical, non-scientific bookkeeping source (see scripts/db_seed.py).
    INTERNAL_SYSTEM = "INTERNAL_SYSTEM"


class CurationStatus(_DomainEnum):
    """Lifecycle of a curated interpretation."""

    RAW = "RAW"
    UNDER_REVIEW = "UNDER_REVIEW"
    CURATED = "CURATED"
    REJECTED = "REJECTED"


class RuleStatus(_DomainEnum):
    """Lifecycle of a computable rule.

    Only ``VALIDATED`` rules from the active ruleset may ever execute
    (``SAFETY-INV-003``). WP-02 defines the vocabulary; the engine that honours
    it arrives in WP-14.
    """

    DRAFT = "DRAFT"
    CURATED = "CURATED"
    VALIDATED = "VALIDATED"
    DEPRECATED = "DEPRECATED"


class DatasetStatus(_DomainEnum):
    """Lifecycle of an immutable dataset version."""

    BUILDING = "BUILDING"
    QUALITY_CHECKED = "QUALITY_CHECKED"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class RulesetStatus(_DomainEnum):
    """Lifecycle of a ruleset version."""

    BUILDING = "BUILDING"
    VALIDATED = "VALIDATED"
    FROZEN = "FROZEN"
    RETIRED = "RETIRED"


class ReleaseStatus(_DomainEnum):
    """Lifecycle of a release bundle. Activation logic belongs to WP-03."""

    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    ROLLED_BACK = "ROLLED_BACK"
    RETIRED = "RETIRED"


class AuditAction(_DomainEnum):
    """Actions the release registry records in the append-only audit log (WP-03).

    A closed vocabulary rather than free text: an audit log whose action names
    drift cannot be queried, and "what happened" must be answerable without
    reading prose. WP-03 owns release lifecycle actions only; ingestion,
    curation and assessment actions arrive with the work packages that perform
    them.
    """

    RELEASE_REGISTERED = "RELEASE_REGISTERED"
    RELEASE_ACTIVATED = "RELEASE_ACTIVATED"
    RELEASE_ROLLED_BACK = "RELEASE_ROLLED_BACK"
    RELEASE_RETIRED = "RELEASE_RETIRED"
    LEGACY_BASELINE_REGISTERED = "LEGACY_BASELINE_REGISTERED"
    #: WP-06. A verified raw snapshot was registered as a dataset build. It
    #: records that a build *started*, never that a dataset was approved: the
    #: dataset it creates is BUILDING and carries no approval metadata.
    DATASET_BUILD_REGISTERED = "DATASET_BUILD_REGISTERED"
    #: WP-07. A named human recorded a data-quality decision on a dataset.
    #: The vocabulary entry exists so that a real decision has somewhere to go;
    #: WP-07 emits none, and no code path in this repository produces one
    #: automatically. A dataset reaching QUALITY_CHECKED without a named
    #: approver and an instant is refused by the database.
    DATASET_QUALITY_CHECKED = "DATASET_QUALITY_CHECKED"
    #: WP-10. The curation workflow's eight actions. Added rather than
    #: reusing a generic "CHANGED", because "who approved this conclusion"
    #: and "who asked for changes to it" are different questions and an audit
    #: log that cannot separate them answers neither.
    #:
    #: None of these is emitted automatically. Every one requires a named
    #: actor whose roles came from a role provider, and this repository's
    #: production role assignment set is empty.
    CURATION_WORK_ITEM_IMPORTED = "CURATION_WORK_ITEM_IMPORTED"
    CURATION_REVISION_CREATED = "CURATION_REVISION_CREATED"
    CURATION_REVISION_SUBMITTED = "CURATION_REVISION_SUBMITTED"
    CURATION_CHANGES_REQUESTED = "CURATION_CHANGES_REQUESTED"
    CURATION_APPROVED = "CURATION_APPROVED"
    CURATION_REJECTED = "CURATION_REJECTED"
    CURATION_REFERRED_TO_ADJUDICATION = "CURATION_REFERRED_TO_ADJUDICATION"
    CURATION_ADJUDICATED = "CURATION_ADJUDICATED"

    # WP-11 rule and ruleset governance. Every state change in the rule layer
    # writes exactly one of these, in the same transaction as the change.
    RULE_DRAFTED = "RULE_DRAFTED"
    RULE_CURATED = "RULE_CURATED"
    RULE_VALIDATED = "RULE_VALIDATED"
    RULE_DEPRECATED = "RULE_DEPRECATED"
    RULE_VALIDATION_REFUSED = "RULE_VALIDATION_REFUSED"
    RULESET_CREATED = "RULESET_CREATED"
    RULESET_MEMBER_ADDED = "RULESET_MEMBER_ADDED"
    RULESET_MEMBER_REMOVED = "RULESET_MEMBER_REMOVED"
    RULESET_VALIDATED = "RULESET_VALIDATED"
    RULESET_VALIDATION_REFUSED = "RULESET_VALIDATION_REFUSED"
    RULESET_REOPENED = "RULESET_REOPENED"
    RULESET_FROZEN = "RULESET_FROZEN"
    RULESET_RETIRED = "RULESET_RETIRED"

    # WP-14 assessment execution. Exactly two, and the pair is the point: a
    # completed assessment and a refused one are different events with
    # different consequences, and an audit log that recorded only successes
    # could not answer "what did this system decline to do, and why".
    #
    # ASSESSMENT_COMPLETED is written in the same transaction as the
    # assessment it describes, so it cannot outlive a rolled-back calculation.
    # ASSESSMENT_REFUSED carries a stable failure code and no case content:
    # a refusal record holding a phenotype profile or a clinical sentence
    # would be a disclosure that outlives the request.
    ASSESSMENT_COMPLETED = "ASSESSMENT_COMPLETED"
    ASSESSMENT_REFUSED = "ASSESSMENT_REFUSED"


class Phenotype(_DomainEnum):
    """P0 phenotype model (architecture.md section 9.1).

    Matching is exact. ``RAPID`` and ``ULTRARAPID`` are separate members and no
    alias, synonym table, or equality shim may join them; a rule covering both
    must list both explicitly.
    """

    POOR = "POOR"
    INTERMEDIATE = "INTERMEDIATE"
    NORMAL = "NORMAL"
    RAPID = "RAPID"
    ULTRARAPID = "ULTRARAPID"
    INDETERMINATE = "INDETERMINATE"


class CoverageStatus(_DomainEnum):
    """Coverage model (architecture.md section 9.2).

    Coverage is a first-class output, separate from attention.
    """

    FULL = "FULL"
    PARTIAL = "PARTIAL"
    INSUFFICIENT = "INSUFFICIENT"
    UNSUPPORTED_DRUG = "UNSUPPORTED_DRUG"
    UNSUPPORTED_PHENOTYPE = "UNSUPPORTED_PHENOTYPE"
    SOURCE_CONFLICT = "SOURCE_CONFLICT"


class CoverageReasonCode(_DomainEnum):
    """Stable machine-readable coverage reasons (architecture.md section 9.2)."""

    DRUG_NOT_IN_CANONICAL_DATASET = "DRUG_NOT_IN_CANONICAL_DATASET"
    PHENOTYPE_NOT_PROVIDED = "PHENOTYPE_NOT_PROVIDED"
    PHENOTYPE_NOT_SUPPORTED = "PHENOTYPE_NOT_SUPPORTED"
    NO_VALIDATED_RULE_FOR_AXIS = "NO_VALIDATED_RULE_FOR_AXIS"
    SOME_AXES_NOT_COVERED = "SOME_AXES_NOT_COVERED"
    VALIDATED_RULES_CONFLICT = "VALIDATED_RULES_CONFLICT"
    DATASET_RULESET_MISMATCH = "DATASET_RULESET_MISMATCH"
    EVIDENCE_REFERENCE_MISSING = "EVIDENCE_REFERENCE_MISSING"


class AttentionLevel(_DomainEnum):
    """Attention model (architecture.md section 9.3).

    Deliberately *not* a score. ``NOT_ASSESSED`` means "we did not look" and is
    not ordered against ``LOW``/``MEDIUM``/``HIGH``; conflating the two is the
    false-reassurance failure mode ``SAFETY-INV-001`` exists to prevent.
    """

    NOT_ASSESSED = "NOT_ASSESSED"
    NO_ACTIVE_ATTENTION = "NO_ACTIVE_ATTENTION"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"

    @property
    def is_calculated(self) -> bool:
        """True when an applicable validated rule produced this level.

        ``NOT_ASSESSED`` is the only non-calculated member. This is a factual
        classification, not a magnitude, and returns no number.
        """
        return self is not AttentionLevel.NOT_ASSESSED
