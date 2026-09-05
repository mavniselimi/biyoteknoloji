# -*- coding: utf-8 -*-
"""Controlled vocabularies for the validation dataset (WP-18).

Three roles, and the whole work package exists to keep them apart. Everything
else here is in service of that: what a case is made of, what may be seen by
whom, and the issue codes a separation audit reports.

**Why a second role enum.** WP-09's :class:`pgx.curation.vocabulary.CaseRole`
already names six roles, three of which - ``TRAINING``, ``CALIBRATION`` and
``INTER_CURATOR_EXERCISE`` - describe curation exercises rather than
validation partitions. A validation dataset that accepted them would have
three extra answers to "which side of the line is this on", and the line is
the point. So this module names exactly the three the partition has, and
:data:`CURATION_ROLE_EQUIVALENT` maps each onto WP-09's vocabulary so the two
cannot drift apart unnoticed. A test asserts the map is total in both
directions it can be.
"""

from __future__ import annotations

from enum import Enum
from typing import Mapping, Tuple

__all__ = [
    "AUTHOR_CONTEXTS",
    "AccessAction",
    "AccessContextKind",
    "CURATION_ROLE_EQUIVALENT",
    "DataClassification",
    "HOLDOUT_ROLES",
    "ISSUE_CODES",
    "PayloadAvailability",
    "SEPARATION_ISSUE_CODES",
    "ValidationCaseRole",
    "VisibilityLevel",
    "VOCABULARY_VERSION",
]

VOCABULARY_VERSION = "pgx-wp18-validation-vocabulary/1"


class _ValidationEnum(str, Enum):
    """String-valued, unordered. Same contract as :mod:`pgx.domain.enums`.

    Ordering is disabled because none of these vocabularies is a scale.
    ``EXPERT_HOLDOUT`` is not "more" than ``INTERNAL_HOLDOUT``; it is a
    different protocol with a different reader.
    """

    def __str__(self) -> str:
        return self.value

    def __lt__(self, other: object) -> bool:  # pragma: no cover - guard
        raise TypeError("%s values are not ordered" % type(self).__name__)

    __le__ = __lt__
    __gt__ = __lt__
    __ge__ = __lt__


class ValidationCaseRole(_ValidationEnum):
    """Which partition a validation case belongs to. Exactly one, forever.

    ``DEVELOPMENT``
        May inform rule design and may be used to debug code. Everything that
        shaped the software belongs here, including every legacy demo profile
        and every WP-17 catalogue case. A development case is *not* validation
        evidence and may never enter a holdout denominator.

    ``INTERNAL_HOLDOUT``
        Held back from rule development. Authors may not see the payload
        before the ruleset is frozen; the metric it later supports measures
        generalisation only for as long as that stays true.

    ``EXPERT_HOLDOUT``
        Held back from everyone until a named expert works it under the
        blind-first protocol. Payloads live in restricted storage and are
        never committed beside the rules they test.

    ``SAFETY-INV-009``: once a holdout informs development, the measurement it
    later produces reports memory rather than generalisation, and no analysis
    afterwards undoes it. That is why role is immutable and why relabelling is
    refused rather than audited.
    """

    DEVELOPMENT = "DEVELOPMENT"
    INTERNAL_HOLDOUT = "INTERNAL_HOLDOUT"
    EXPERT_HOLDOUT = "EXPERT_HOLDOUT"


#: The two roles whose payloads are restricted. Named rather than written as
#: ``role is not DEVELOPMENT`` at each call site, so a fourth role - if one is
#: ever added in the open - has to be classified deliberately.
HOLDOUT_ROLES: Tuple[ValidationCaseRole, ...] = (
    ValidationCaseRole.INTERNAL_HOLDOUT,
    ValidationCaseRole.EXPERT_HOLDOUT,
)

#: One WP-09 curation role per validation role. Total by construction and
#: asserted total by test: the vocabularies are allowed to differ in size, and
#: not allowed to differ in meaning.
CURATION_ROLE_EQUIVALENT: Mapping[str, str] = {
    ValidationCaseRole.DEVELOPMENT.value: "DEVELOPMENT",
    ValidationCaseRole.INTERNAL_HOLDOUT.value: "INTERNAL_HOLDOUT",
    ValidationCaseRole.EXPERT_HOLDOUT.value: "EXPERT_HOLDOUT",
}


class DataClassification(_ValidationEnum):
    """What kind of data a case is made of.

    ``SYNTHETIC``
        Constructed for this project. Names no person and derives from no
        person's record.

    ``PUBLISHED_LITERATURE_DERIVED``
        Constructed from a published, citable scientific source - a guideline
        table, a published vignette - with the citation recorded. Still not
        data about an identifiable person.

    There is no third member, and in particular there is no member meaning
    "real patient". Real-patient ingestion is P2-03/P2-04 and adding it here
    would be adding it to the product.
    """

    SYNTHETIC = "SYNTHETIC"
    PUBLISHED_LITERATURE_DERIVED = "PUBLISHED_LITERATURE_DERIVED"


class VisibilityLevel(_ValidationEnum):
    """Who may see a case's *payload*. Metadata visibility is separate.

    ``PUBLIC_METADATA``
        The case exists, has an identity, a role and a provenance summary.
        This is what a manifest publishes and it is all a manifest can hold.

    ``AUTHOR_VISIBLE``
        The payload may be read by the people who write rules. Only ever
        correct for ``DEVELOPMENT``.

    ``RESTRICTED``
        The payload is withheld from rule authors. Correct for
        ``INTERNAL_HOLDOUT`` before freeze and for ``EXPERT_HOLDOUT`` always,
        until the permitted workflow WP-22 owns.
    """

    PUBLIC_METADATA = "PUBLIC_METADATA"
    AUTHOR_VISIBLE = "AUTHOR_VISIBLE"
    RESTRICTED = "RESTRICTED"


class AccessContextKind(_ValidationEnum):
    """What the caller is doing, as the caller declares it.

    Declared, not proven. WP-18 implements no authentication and this enum is
    not a permission: it is the caller stating a purpose, recorded so that a
    later reader can see what was claimed. WP-23 owns establishing that a
    claim is true.
    """

    RULE_AUTHORING = "RULE_AUTHORING"
    DEVELOPMENT_WORKFLOW = "DEVELOPMENT_WORKFLOW"
    DATASET_CURATION = "DATASET_CURATION"
    EXPERT_REVIEW = "EXPERT_REVIEW"
    VALIDATION_RUN = "VALIDATION_RUN"
    AUDIT = "AUDIT"


#: Contexts that write or shape the rules being measured. A holdout payload
#: reaching any of these ends that holdout's usefulness, which is why the
#: policy tests these by membership rather than by naming one of them.
AUTHOR_CONTEXTS: Tuple[AccessContextKind, ...] = (
    AccessContextKind.RULE_AUTHORING,
    AccessContextKind.DEVELOPMENT_WORKFLOW,
)


class AccessAction(_ValidationEnum):
    """What was attempted. Recorded whether or not it succeeded."""

    LIST_METADATA = "LIST_METADATA"
    READ_METADATA = "READ_METADATA"
    READ_PAYLOAD = "READ_PAYLOAD"
    IMPORT_PAYLOAD = "IMPORT_PAYLOAD"
    AUDIT_PARTITION = "AUDIT_PARTITION"


class PayloadAvailability(_ValidationEnum):
    """Whether a restricted payload is reachable from this deployment.

    ``NOT_CONFIGURED`` is the answer in this repository and is different from
    ``ABSENT``: nobody has pointed at restricted storage, which is not the
    same as having looked and found nothing. Collapsing the two would turn "we
    did not look" into "there is nothing there".
    """

    NOT_CONFIGURED = "NOT_CONFIGURED"
    CONFIGURED_EMPTY = "CONFIGURED_EMPTY"
    CONFIGURED_PRESENT = "CONFIGURED_PRESENT"


#: Every separation problem this package can report, with what it means.
#: Stable strings: an audit artifact is committed and diffed, and a renamed
#: code would read as a resolved problem.
SEPARATION_ISSUE_CODES: Mapping[str, str] = {
    "ROLE_OVERLAP":
        "one case identifier appears under more than one role",
    "CONTENT_DUPLICATE_ACROSS_PARTITIONS":
        "one canonical content fingerprint appears in development and in a "
        "holdout partition",
    "CONTENT_DUPLICATE_WITHIN_PARTITION":
        "one canonical content fingerprint appears twice in the same "
        "partition, so a denominator would count the same case twice",
    "DERIVATION_FAMILY_SPLIT":
        "two case identifiers from one derivation family are split across "
        "development and a holdout partition",
    "HOLDOUT_DERIVED_FROM_DEVELOPMENT":
        "a holdout case declares a development or demo fixture as its source",
    "DEVELOPMENT_RELABELLED_AS_HOLDOUT":
        "a case previously recorded as development now claims a holdout role",
    "HOLDOUT_PROVENANCE_MISSING":
        "a holdout case has no verifiable provenance, so its independence "
        "cannot be shown",
    "RELEASE_COMPATIBILITY_CONFLICT":
        "cases in one partition declare incompatible release or version "
        "constraints",
    "RESTRICTED_FIELD_IN_PUBLIC_MANIFEST":
        "a public manifest carries a field reserved for restricted payloads",
    "PAYLOAD_HASH_MISMATCH":
        "a declared payload hash does not match the payload it names",
}

#: Alias kept short for call sites inside this package.
ISSUE_CODES = SEPARATION_ISSUE_CODES
