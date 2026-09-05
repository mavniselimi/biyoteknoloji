# -*- coding: utf-8 -*-
"""The evidence vocabulary (WP-25).

Four enumerations, and one deliberate omission.

The enumerations name what a piece of evidence *is* (``EvidenceType``), what
a claim's evidence *does for it* (``ClaimSupport``), what a gate *concluded*
(``GateResult``), and why something did not happen (``BLOCKER_CODES``).

The omission is a truthiness API. There is no ``is_ok``, no ``__bool__``, no
``status.ok`` and no generic ``passed`` property anywhere in this package,
because every one of those is a place where ``IMPLEMENTED`` quietly becomes
``PASS``. The affirmative predicates that do exist are narrow, named for the
exact decision they may inform, and each is true for one value only:

* ``EvidenceType.may_support_a_ths6_claim`` - true for ``REAL_EXECUTED`` and
  ``REAL_OBSERVED``, nothing else;
* ``ClaimSupport.is_sufficient`` - true for ``SUPPORTED``, nothing else;
* ``GateResult.is_pass`` - true for ``PASS``, nothing else.

Ordering is disabled on all four. ``PARTIALLY_SUPPORTED`` is not "greater
than" ``UNSUPPORTED`` on any scale that exists, and the first thing built on
an invented scale would be ``support >= PARTIALLY_SUPPORTED``.

``IMPLEMENTATION_TEST`` deserves its own note, because it is the state most of
this repository is in and the one most likely to be misread. 6,920 unit tests
passing proves the software does what its authors intended. It proves nothing
about whether a pharmacogenomic rule is correct, and this package will never
let a test count close a scientific gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import FrozenSet, Mapping, Optional, Tuple

__all__ = [
    "BLOCKER_CODES",
    "EXIT_BLOCKED",
    "EXIT_FAILURE",
    "EXIT_SUCCESS",
    "EXIT_USAGE",
    "PACK_INTEGRITY_IS_NOT_ACHIEVEMENT",
    "SCIENTIFIC_EVIDENCE_TYPES",
    "THS6_VOCABULARY_VERSION",
    "Blocker",
    "ClaimSupport",
    "EvidenceType",
    "GateResult",
    "exit_code_for_gate",
]

THS6_VOCABULARY_VERSION = "pgx-wp25-ths6-vocabulary/1"

#: Printed by every command that emits a pack result, verbatim, so that no
#: reader of any output can take a well-formed pack for an achieved standard.
#: Spelled once so a banner, a document and a test cannot disagree.
PACK_INTEGRITY_IS_NOT_ACHIEVEMENT = (
    "Evidence pack integrity describes this pack, not the programme. A valid "
    "pack that honestly records blockers is still a blocked programme.")

#: Exit codes, matching WP-24's contract so the shell means the same thing
#: across every command in this repository.
EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXIT_BLOCKED = 2
EXIT_USAGE = 3


class _Ths6Enum(str, Enum):
    """String-valued and unordered, following the project convention."""

    def __str__(self) -> str:
        return self.value

    def __lt__(self, other: object) -> bool:  # pragma: no cover - guard
        raise TypeError("%s values are not ordered" % type(self).__name__)

    __gt__ = __le__ = __ge__ = __lt__


class EvidenceType(_Ths6Enum):
    """What one piece of evidence actually is.

    Twelve values because the twelve are genuinely different, and because the
    distinction between the first two and the other ten is the entire subject
    of this work package.
    """

    #: A real operation ran against real inputs and its result was recorded.
    #: A migration applied to a server; a benchmark computed over real cases.
    REAL_EXECUTED = "REAL_EXECUTED"
    #: A real system was watched behaving - an endpoint answered, a page
    #: rendered, a chain verified. Distinct from REAL_EXECUTED because a
    #: command completing is not a system responding.
    REAL_OBSERVED = "REAL_OBSERVED"
    #: A unit or integration test passed. Evidence that the software does what
    #: its authors intended, and evidence of nothing else. Never scientific,
    #: never clinical, never operational.
    IMPLEMENTATION_TEST = "IMPLEMENTATION_TEST"
    #: A workflow, Dockerfile, compose file, policy or service definition
    #: exists and has been reviewed. Nothing has run it. A configured CI
    #: pipeline is not a CI run; a Dockerfile is not an image.
    CONFIGURED_NOT_EXECUTED = "CONFIGURED_NOT_EXECUTED"
    #: Prose. A runbook, a protocol, a policy, a handoff, an architecture
    #: section. It records intent and instructions. A written runbook is not
    #: an executed operation.
    DOCUMENT_ONLY = "DOCUMENT_ONLY"
    #: Machinery exercised against deliberately labelled fixtures to show the
    #: machinery works. Proves the measurement math; proves nothing measured.
    TEST_ONLY_REHEARSAL = "TEST_ONLY_REHEARSAL"
    #: The evidence cannot exist until a named person acts - approves a
    #: protocol, signs a boundary, completes a review.
    HUMAN_PENDING = "HUMAN_PENDING"
    #: The evidence cannot exist until a scientific precondition holds - an
    #: approved source, a curated interpretation, a validated rule.
    SCIENTIFIC_PENDING = "SCIENTIFIC_PENDING"
    #: The evidence cannot exist until an operational precondition holds - a
    #: database, a container runtime, a CI provider, a staging host.
    OPERATIONAL_PENDING = "OPERATIONAL_PENDING"
    #: It existed and was true about inputs that have since changed. A stale
    #: result is not a weaker result; it is a result about a different thing.
    STALE = "STALE"
    #: It exists but does not satisfy its own schema, its checksum disagrees,
    #: or it contradicts another artifact. Reported, never repaired here.
    INVALID = "INVALID"
    #: The artifact is named by some other document but is not present, or is
    #: outside the repository and could not be read.
    UNAVAILABLE = "UNAVAILABLE"

    @property
    def may_support_a_ths6_claim(self) -> bool:
        """True only for evidence of a real event.

        Not for ``IMPLEMENTATION_TEST``: 6,920 passing tests are a statement
        about software, and every THS 6 claim in this project is a statement
        about pharmacogenomics, operations or human review. Not for
        ``TEST_ONLY_REHEARSAL``, which is the same substitution wearing a
        fixture. Not for ``CONFIGURED_NOT_EXECUTED`` or ``DOCUMENT_ONLY``,
        which are statements about intent.
        """
        return self in (EvidenceType.REAL_EXECUTED, EvidenceType.REAL_OBSERVED)

    @property
    def is_pending(self) -> bool:
        """True when something outside the software has to happen first."""
        return self in (EvidenceType.HUMAN_PENDING,
                        EvidenceType.SCIENTIFIC_PENDING,
                        EvidenceType.OPERATIONAL_PENDING)

    @property
    def is_defective(self) -> bool:
        """True when the artifact itself is wrong or missing, not merely
        insufficient. These are engineering faults; the pending states are
        not."""
        return self in (EvidenceType.STALE, EvidenceType.INVALID,
                        EvidenceType.UNAVAILABLE)


#: The only two types a scientific, operational or human claim may cite.
SCIENTIFIC_EVIDENCE_TYPES: FrozenSet[EvidenceType] = frozenset(
    {EvidenceType.REAL_EXECUTED, EvidenceType.REAL_OBSERVED})


class ClaimSupport(_Ths6Enum):
    """What the cited evidence does for one claim."""

    #: Every mandatory condition of the claim is met by evidence that may
    #: support a THS 6 claim. The only sufficient value.
    SUPPORTED = "SUPPORTED"
    #: Some conditions are met and at least one is not. Reported as its own
    #: value rather than rounded up, because a partially supported claim is
    #: one nobody may make.
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    #: No evidence of an admissible type supports it. Usually because the
    #: underlying thing has not happened.
    UNSUPPORTED = "UNSUPPORTED"
    #: The claim was registered but no evaluation has been run. Never a
    #: synonym for UNSUPPORTED: "we did not look" and "we looked and found
    #: nothing" are different states with different fixes.
    NOT_EVALUATED = "NOT_EVALUATED"
    #: Evidence exists and says the opposite. The most serious value, and the
    #: one an aggregate must never average away.
    CONTRADICTED = "CONTRADICTED"

    @property
    def is_sufficient(self) -> bool:
        """True only for SUPPORTED."""
        return self is ClaimSupport.SUPPORTED

    @property
    def is_publishable(self) -> bool:
        """Whether the claim may appear in outward-facing material.

        Identical to ``is_sufficient`` today and kept separate on purpose: if
        a future reviewer ever decides a partially supported claim may be
        published with a caveat, that decision changes one property here and
        is visible in the diff, rather than being smuggled in at a call site.
        """
        return self.is_sufficient


class GateResult(_Ths6Enum):
    """What one gate concluded."""

    #: Every mandatory condition holds, each on admissible evidence.
    PASS = "PASS"
    #: At least one mandatory condition is not met because a named
    #: precondition is absent. Carries the blocker and its owner.
    BLOCKED = "BLOCKED"
    #: A condition was evaluated and came out wrong - a contradiction, an
    #: invalid artifact, a checksum mismatch. Distinct from BLOCKED because
    #: this is a defect and BLOCKED is an absence.
    FAIL = "FAIL"
    #: The gate has not been evaluated. Never counts as PASS and never
    #: counts as BLOCKED.
    NOT_EVALUATED = "NOT_EVALUATED"
    #: It was evaluated against inputs that have since changed.
    STALE = "STALE"

    @property
    def is_pass(self) -> bool:
        """True only for PASS. The single affirmative predicate on gates."""
        return self is GateResult.PASS


#: Every blocker code WP-25 may report. Closed, like WP-24's, because a code
#: invented at a call site is a code no aggregator can enumerate and no
#: document can be searched for.
BLOCKER_CODES: Mapping[str, str] = {
    # -- Gate A: data and sources -------------------------------------------
    "THS6_NO_APPROVED_SOURCE":
        "no scientific source has been approved; every registered source is "
        "still awaiting review",
    "THS6_DATASET_NOT_PUBLISHED":
        "no canonical dataset has been published; the current one is still "
        "being built",
    "THS6_SNAPSHOT_QUARANTINED":
        "the raw snapshot is quarantined and incomplete, so nothing "
        "downstream may treat it as a corpus",
    "THS6_EVIDENCE_BUILD_NOT_APPROVED":
        "the evidence build is not approved for rules and is labelled not "
        "curated and not publication eligible",
    # -- Gate B: curation and rules -----------------------------------------
    "THS6_CURATION_PROTOCOL_NOT_APPROVED":
        "the curation protocol has not been approved by a named expert",
    "THS6_NO_CURATED_INTERPRETATION":
        "no interpretation has been curated under an approved protocol",
    "THS6_NO_APPROVED_RULE":
        "no rule approval envelope exists, so no rule has been approved",
    "THS6_NO_EXECUTABLE_RULESET":
        "no executable ruleset is registered, so no assessment can be "
        "computed from governed content",
    "THS6_LEGACY_WORK_ITEMS_UNLINKED":
        "legacy rule candidates remain unlinked to governed work items",
    # -- Gate C: assessment, coverage and safety ----------------------------
    "THS6_NO_REAL_ASSESSMENT":
        "no assessment has been computed from governed content, so no "
        "finding exists to trace",
    "THS6_NO_COVERAGE_EXECUTION":
        "no coverage manifest has been executed, so no supported axis is "
        "measured",
    "THS6_SAFETY_GATE_BLOCKED":
        "the safety gate reports BLOCKED in its own artifact",
    "THS6_CLAIM_BOUNDARY_NOT_APPROVED":
        "the claim boundary is a draft awaiting human and scientific review",
    "THS6_NO_ACTIVE_RELEASE":
        "no release is active, so no result can be attributed to a version "
        "bundle",
    "THS6_SAFETY_CI_NOT_EXECUTED":
        "the safety invariants have not been executed by a continuous "
        "integration provider",
    # -- Gate D: validation and expert review -------------------------------
    "THS6_INSUFFICIENT_VALIDATION_CASES":
        "fewer validation cases exist than the P0 target requires",
    "THS6_NO_HOLDOUT_SET":
        "no independent holdout set exists, so separation cannot be "
        "demonstrated",
    "THS6_NO_COMPUTED_METRIC":
        "no validation metric has been computed; definitions exist, values "
        "do not",
    "THS6_BENCHMARK_NOT_EXECUTED":
        "no benchmark run has been executed against a release",
    "THS6_EXPERT_PROTOCOL_NOT_APPROVED":
        "the expert review protocol has no signatory",
    "THS6_NO_NAMED_REVIEWER":
        "no expert reviewer has been named",
    "THS6_NO_COMPLETED_REVIEW":
        "no expert review has been completed",
    # -- Gate E: security and deployment ------------------------------------
    "THS6_SECURITY_GATE_BLOCKED":
        "the security gate reports BLOCKED in its own artifact",
    "THS6_DEPLOYMENT_GATE_BLOCKED":
        "the deployment gate reports BLOCKED in its own artifact",
    "THS6_DATABASE_UNAVAILABLE":
        "no database is reachable, so no governed store can be exercised",
    "THS6_MIGRATION_NOT_EXECUTED":
        "the governed schema migrations have not been applied to a server",
    "THS6_AUDIT_CHAIN_UNVERIFIED":
        "no audit chain has been verified against a real store",
    "THS6_BACKUP_RESTORE_NOT_VERIFIED":
        "no backup has been restored and verified against its conditions",
    "THS6_CI_NOT_EXECUTED":
        "no continuous integration provider has run the configured workflows",
    "THS6_CONTAINER_RUNTIME_UNAVAILABLE":
        "no container runtime answered, so no image exists to deploy",
    "THS6_STAGING_NOT_DEPLOYED":
        "no staging environment has been deployed or observed",
    # -- Gate F: THS 6 aggregate --------------------------------------------
    "THS6_UPSTREAM_GATE_NOT_PASS":
        "at least one of gates A through E is not PASS, which forbids F",
    "THS6_DEMO_NOT_EXECUTED":
        "the final representative demonstration has not been executed",
    "THS6_NO_HUMAN_SIGNOFF":
        "no role on the sign-off matrix has signed",
    # -- evidence pack and inventory ----------------------------------------
    "THS6_EVIDENCE_UNAVAILABLE":
        "an artifact named by a document is not present in the repository",
    "THS6_EVIDENCE_STALE":
        "an artifact records a value its own source has since changed",
    "THS6_EVIDENCE_INVALID":
        "an artifact does not satisfy its declared schema or its checksum "
        "disagrees",
    "THS6_SOURCE_ARTIFACT_DISAGREEMENT":
        "two authoritative artifacts state different values for the same "
        "fact, and neither may be preferred without a decision",
    "THS6_SOURCE_DOCUMENT_UNAVAILABLE":
        "a requirement document named by the work package could not be read "
        "from this environment",
    "THS6_DOD_DECLARED_COUNT_MISMATCH":
        "a document's declared count of Definition of Done items disagrees "
        "with the number it enumerates",
    "THS6_PROSE_INVENTORY_DISCREPANCY":
        "a work package's prose describes the repository incorrectly",
}


@dataclass(frozen=True)
class Blocker:
    """One named reason a condition is not met.

    ``owner`` is required and is never "the team". WP-25 exists in part to
    make the human and scientific blockers as legible as the operational
    ones, and an unowned blocker is one nobody clears.
    """

    code: str
    detail: str
    owner: str
    gate_id: Optional[str] = None

    def __post_init__(self) -> None:
        if self.code not in BLOCKER_CODES:
            raise ValueError(
                "%r is not a declared WP-25 blocker code; an undeclared code "
                "is one no document can be searched for" % (self.code,))
        if not self.detail.strip():
            raise ValueError("a blocker states what is missing")
        if not self.owner.strip():
            raise ValueError("a blocker names who supplies the missing thing")

    def to_json(self) -> Mapping[str, object]:
        return {"code": self.code, "detail": self.detail, "owner": self.owner,
                "gate_id": self.gate_id, "blocking": True}


def exit_code_for_gate(result: GateResult) -> int:
    """The process exit code one gate result earns.

    ``FAIL`` is louder than ``BLOCKED`` on purpose: a blocked gate is the
    expected state of this programme, and a failing one means an artifact is
    wrong. A caller that treated both as "not zero" would never notice the
    day a checksum stopped matching.
    """
    if result is GateResult.PASS:
        return EXIT_SUCCESS
    if result is GateResult.FAIL:
        return EXIT_FAILURE
    return EXIT_BLOCKED
