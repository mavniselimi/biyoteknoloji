# -*- coding: utf-8 -*-
"""The gates a conclusion must pass to reach CURATED (WP-10).

Thirteen checks, evaluated together and reported together. Every one **fails
closed**: an unknown answer is a closed gate, not an open one, because the
alternative is that a missing input reads as permission.

Against this repository they do not pass, and that is the correct result:

* the protocol is ``AWAITING_EXPERT_REVIEW``;
* the evidence build is ``QUARANTINED`` and ``NOT_PUBLICATION_ELIGIBLE``;
* no source policy has genuine human approval;
* no real curator, reviewer or steward identity exists.

So every one of the 1,559 legacy work items stays ``RAW``. Making them pass
would require changing the protocol's approval state or the evidence build's
quarantine - which is not a test fixture problem, it is the state of the
science - so the successful path is exercised by synthetic fixtures that carry
their own approved protocol and unquarantined build.

The gates are data, not a function body. A caller gets the whole list with
each gate's own reason, because "why can't I approve this" has thirteen
possible answers with different owners: a scientist, a data steward, a source
policy reviewer.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from pgx.curation.vocabulary import ConflictState, ProtocolStatus
from pgx.curation.workflow.errors import GateBlockedError
from pgx.curation.workflow.models import (CurationRevision,
                                          ProvenanceVerification)
from pgx.curation.workflow.roles import ActorContext

__all__ = [
    "GATE_CODES",
    "GateOutcome",
    "GateResult",
    "WorkflowPolicy",
    "evaluate_curated_gates",
]

#: Every gate, with what a closed one means and who can open it. Declared as
#: data so a document, a CLI and a test all cite the same code, and so the
#: owner of each blocker is visible rather than implied.
GATE_CODES: Mapping[str, Mapping[str, str]] = {
    "GATE_PROTOCOL_NOT_APPROVED": {
        "requirement": "The curation protocol is APPROVED with a genuine "
                       "named scientific approver.",
        "owner": "a named scientific expert",
    },
    "GATE_PROTOCOL_HASH_MISMATCH": {
        "requirement": "The revision was written under the protocol version "
                       "and content hash now in force.",
        "owner": "the curator, by re-authoring under the current protocol",
    },
    "GATE_PROTOCOL_EXPIRED": {
        "requirement": "The protocol's review date has not passed and it has "
                       "not been superseded.",
        "owner": "the protocol owner and a scientific approver",
    },
    "GATE_EVIDENCE_MISSING": {
        "requirement": "Every cited evidence record exists in the build.",
        "owner": "the curator, by correcting the selection",
    },
    "GATE_EVIDENCE_TRACE_UNVERIFIED": {
        "requirement": "Every cited record's trace verifies against raw bytes.",
        "owner": "the data/provenance steward",
    },
    "GATE_EVIDENCE_WRONG_BUILD": {
        "requirement": "Cited evidence belongs to the expected build and "
                       "dataset.",
        "owner": "the curator, by re-selecting from the expected build",
    },
    "GATE_EVIDENCE_QUARANTINED": {
        "requirement": "The evidence build is not quarantined.",
        "owner": "acquisition and source policy, not curation",
    },
    "GATE_SOURCE_POLICY_MISSING": {
        "requirement": "A source policy permits using this evidence.",
        "owner": "a named source-policy approver",
    },
    "GATE_UNRESOLVED_CONFLICT": {
        "requirement": "No unresolved material conflict remains.",
        "owner": "a named adjudicator",
    },
    "GATE_PROVENANCE_VERIFICATION_MISSING": {
        "requirement": "A provenance steward has verified the cited trace.",
        "owner": "the data/provenance steward",
    },
    "GATE_RATIONALE_INCOMPLETE": {
        "requirement": "The structured rationale is complete and "
                       "non-placeholder.",
        "owner": "the curator",
    },
    "GATE_REVIEWER_NOT_INDEPENDENT": {
        "requirement": "An independent reviewer, distinct from the author, "
                       "approves.",
        "owner": "a second named scientific reviewer",
    },
    "GATE_VERSION_STALE": {
        "requirement": "The caller's expected version matches the stored one.",
        "owner": "the caller, by re-reading the work item",
    },
}


@dataclass(frozen=True)
class GateOutcome:
    """One gate, and whether it is open."""

    code: str
    passed: bool
    detail: str

    def __post_init__(self) -> None:
        if self.code not in GATE_CODES:
            raise KeyError(
                "%r is not a declared gate code; an undeclared gate cannot be "
                "cited by a document or a test" % self.code)

    def to_json(self) -> Dict[str, Any]:
        entry = GATE_CODES[self.code]
        return {
            "code": self.code,
            "passed": self.passed,
            "detail": self.detail,
            "requirement": entry["requirement"],
            "unblocked_by": entry["owner"],
        }


@dataclass(frozen=True)
class GateResult:
    """Every gate's outcome, and the single question they answer together."""

    outcomes: Tuple[GateOutcome, ...]

    @property
    def blocked(self) -> Tuple[GateOutcome, ...]:
        return tuple(item for item in self.outcomes if not item.passed)

    @property
    def passed(self) -> bool:
        return not self.blocked

    def raise_if_blocked(self) -> None:
        if self.blocked:
            raise GateBlockedError(
                "%d approval gate(s) are closed: %s"
                % (len(self.blocked),
                   ", ".join(item.code for item in self.blocked)),
                blocked=[item.to_json() for item in self.blocked])

    def to_json(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "gate_count": len(self.outcomes),
            "blocked_count": len(self.blocked),
            "gates": [item.to_json() for item in self.outcomes],
            "note": ("Every gate fails closed. An unknown answer is a closed "
                     "gate, because a missing input must never read as "
                     "permission."),
        }


@dataclass(frozen=True)
class WorkflowPolicy:
    """The facts the gates are evaluated against.

    Supplied by the caller rather than fetched here, so the policy object is
    pure and a test can construct the approved world without touching the real
    protocol or evidence build - which must stay exactly as they are.
    """

    protocol_status: ProtocolStatus
    protocol_version: str
    protocol_content_hash: str
    protocol_approved_by: Optional[str] = None
    protocol_review_due: Optional[_dt.date] = None
    protocol_superseded_by: Optional[str] = None
    evidence_build_key: str = ""
    evidence_build_content_hash: str = ""
    dataset_public_id: str = ""
    evidence_build_quarantined: bool = True
    evidence_build_lifecycle_labels: Tuple[str, ...] = ()
    known_evidence_uuids: Tuple[str, ...] = ()
    source_policy_status: Optional[str] = None
    author_reviewer_separation_required: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "known_evidence_uuids",
                           tuple(self.known_evidence_uuids))
        object.__setattr__(self, "evidence_build_lifecycle_labels",
                           tuple(self.evidence_build_lifecycle_labels))

    @property
    def protocol_is_approved(self) -> bool:
        return bool(self.protocol_status is ProtocolStatus.APPROVED
                    and (self.protocol_approved_by or "").strip())

    def to_json(self) -> Dict[str, Any]:
        return {
            "protocol_status": self.protocol_status.value,
            "protocol_version": self.protocol_version,
            "protocol_content_hash": self.protocol_content_hash,
            "protocol_approved_by": self.protocol_approved_by,
            "protocol_is_approved": self.protocol_is_approved,
            "evidence_build_key": self.evidence_build_key,
            "evidence_build_quarantined": self.evidence_build_quarantined,
            "evidence_build_lifecycle_labels":
                list(self.evidence_build_lifecycle_labels),
            "dataset_public_id": self.dataset_public_id,
            "source_policy_status": self.source_policy_status,
            "known_evidence_count": len(self.known_evidence_uuids),
        }


def evaluate_curated_gates(
    policy: WorkflowPolicy,
    revision: CurationRevision,
    *,
    reviewer: Optional[ActorContext] = None,
    author_actor_id: Optional[str] = None,
    provenance: Optional[ProvenanceVerification] = None,
    conflict_state: Optional[ConflictState] = None,
    conflict_material: Optional[bool] = None,
    rationale_complete: Optional[bool] = None,
    expected_version: Optional[int] = None,
    actual_version: Optional[int] = None,
    now: Optional[_dt.date] = None,
) -> GateResult:
    """Evaluate every gate and return them all.

    Every gate is evaluated even after one has failed. Returning on the first
    closed gate would hide the other twelve, and an operator would fix them one
    round-trip at a time.
    """
    outcomes: List[GateOutcome] = []

    def add(code: str, passed: bool, detail: str) -> None:
        outcomes.append(GateOutcome(code=code, passed=passed, detail=detail))

    # -- protocol -------------------------------------------------------
    add("GATE_PROTOCOL_NOT_APPROVED", policy.protocol_is_approved,
        "protocol %s is %s%s" % (
            policy.protocol_version, policy.protocol_status.value,
            "" if policy.protocol_is_approved
            else "; no named scientific approver is on record"))

    matches = (revision.protocol_version == policy.protocol_version
               and revision.protocol_content_hash == policy.protocol_content_hash)
    add("GATE_PROTOCOL_HASH_MISMATCH", matches,
        "revision written under %s/%s; in force is %s/%s"
        % (revision.protocol_version, revision.protocol_content_hash[:23],
           policy.protocol_version, policy.protocol_content_hash[:23]))

    today = now or _dt.date.today()
    expired = bool(policy.protocol_superseded_by) or bool(
        policy.protocol_review_due and policy.protocol_review_due < today)
    add("GATE_PROTOCOL_EXPIRED", not expired,
        "superseded by %s" % policy.protocol_superseded_by
        if policy.protocol_superseded_by
        else ("review was due %s" % policy.protocol_review_due if expired
              else "not expired"))

    # -- evidence -------------------------------------------------------
    known = frozenset(policy.known_evidence_uuids)
    cited = tuple(revision.evidence.evidence_record_uuids)
    missing = tuple(sorted(item for item in cited if item not in known))
    add("GATE_EVIDENCE_MISSING", not missing,
        "all %d cited records exist" % len(cited) if not missing
        else "%d cited record(s) are not in the build: %s"
             % (len(missing), ", ".join(missing[:3])))

    if provenance is None:
        add("GATE_EVIDENCE_TRACE_UNVERIFIED", False,
            "no provenance verification was supplied, so no trace is known to "
            "verify")
    else:
        unverified = tuple(sorted(set(cited)
                                  - set(provenance.evidence_record_uuids)))
        ok = bool(provenance.all_traces_verified and not unverified)
        add("GATE_EVIDENCE_TRACE_UNVERIFIED", ok,
            "every cited trace verified" if ok
            else "unverified: %s" % (", ".join(unverified[:3])
                                     or "; ".join(provenance.problems[:2])))

    build_ok = (revision.evidence.evidence_build_content_hash
                == policy.evidence_build_content_hash
                and revision.evidence.dataset_public_id
                == policy.dataset_public_id)
    add("GATE_EVIDENCE_WRONG_BUILD", build_ok,
        "cited build matches the expected one" if build_ok
        else "revision cites build %s / dataset %s; expected %s / %s"
             % (revision.evidence.evidence_build_content_hash[:23],
                revision.evidence.dataset_public_id,
                policy.evidence_build_content_hash[:23],
                policy.dataset_public_id))

    add("GATE_EVIDENCE_QUARANTINED", not policy.evidence_build_quarantined,
        "build is quarantined (%s)"
        % ", ".join(policy.evidence_build_lifecycle_labels)
        if policy.evidence_build_quarantined else "build is not quarantined")

    policy_ok = str(policy.source_policy_status or "").upper() == "APPROVED"
    add("GATE_SOURCE_POLICY_MISSING", policy_ok,
        "source policy status is %s" % (policy.source_policy_status or "absent"))

    # -- science --------------------------------------------------------
    blocking_conflict = bool(
        conflict_state in (ConflictState.UNRESOLVED,
                           ConflictState.ADJUDICATION_REQUIRED)
        or (conflict_state is ConflictState.PRESENT and conflict_material))
    add("GATE_UNRESOLVED_CONFLICT", not blocking_conflict,
        "conflict state %s%s" % (
            getattr(conflict_state, "value", conflict_state),
            " and material" if conflict_material else "")
        if blocking_conflict else "no blocking conflict")

    add("GATE_PROVENANCE_VERIFICATION_MISSING", provenance is not None,
        "verified by %s" % provenance.verified_by if provenance
        else "no provenance steward has verified this evidence")

    add("GATE_RATIONALE_INCOMPLETE", bool(rationale_complete),
        "structured rationale complete" if rationale_complete
        else "the structured rationale is absent or incomplete")

    # -- separation and concurrency -------------------------------------
    if reviewer is None:
        add("GATE_REVIEWER_NOT_INDEPENDENT", False,
            "no independent reviewer has approved this revision")
    else:
        distinct = (not policy.author_reviewer_separation_required
                    or (author_actor_id or "").strip().lower()
                    != reviewer.actor_id.strip().lower())
        scientific = reviewer.may_approve_science
        add("GATE_REVIEWER_NOT_INDEPENDENT", bool(distinct and scientific),
            "reviewer %s approves" % reviewer.actor_id
            if distinct and scientific
            else ("the reviewer authored this revision"
                  if not distinct
                  else "%s holds no role that may approve science"
                       % reviewer.actor_id))

    version_ok = (expected_version is not None
                  and expected_version == actual_version)
    add("GATE_VERSION_STALE", version_ok,
        "version %s matches" % expected_version if version_ok
        else "caller holds version %s; stored is %s"
             % (expected_version, actual_version))

    return GateResult(outcomes=tuple(outcomes))
