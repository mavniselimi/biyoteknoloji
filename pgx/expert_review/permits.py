# -*- coding: utf-8 -*-
"""Assignment-scoped payload permits (WP-22).

WP-18 refuses every EXPERT_HOLDOUT payload read, including one requested by an
``EXPERT_REVIEW`` context. That refusal is correct and stays: "any expert
reviewer" is not a boundary, because the set of people holding that role is
not the set of people assigned to any particular case, and a policy that
conflated them would let a reviewer working case A read case B - the two cases
they might later be asked to compare.

So the boundary is not widened. A single narrow gate is added beside it: a
permit, issued by the WP-22 service, that authorises **one actor** to read
**one case** at **one stage** of **one assignment**, under **one protocol**
and **one release**.

Every one of those bindings is load-bearing:

- **actor** - so a permit leaked to another reviewer is useless;
- **case** - so a reviewer cannot read the case next to theirs;
- **assignment** - so a permit outlives neither its assignment nor a
  reassignment;
- **stage** - so a reviewer who has completed cannot re-open the payload; what
  they saw and when is the evidential question, and an unbounded permit makes
  it unanswerable;
- **protocol and release hashes** - so a permit issued under conditions that
  have since changed stops matching.

A permit is a value, not a capability token. It is never returned to a client,
never serialised into a page, and cannot be presented by a caller: the service
constructs one and hands it to the access check in the same call. Nothing here
is a bearer credential.
"""

from __future__ import annotations

import datetime as _dt
import hmac
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional

from pgx.domain.hashing import sha256_digest
from pgx.expert_review.errors import PermitError
from pgx.expert_review.models import ReviewAssignment
from pgx.expert_review.vocabulary import PERMITTED_STAGES, ReviewState

__all__ = [
    "PERMIT_VERSION",
    "PayloadPermit",
    "issue_permit",
    "permit_allows",
]

PERMIT_VERSION = "pgx-wp22-payload-permit/1"


@dataclass(frozen=True, slots=True)
class PayloadPermit:
    """Authorisation for one actor to read one case's payload, once, now."""

    permit_version: str
    assignment_id: str
    review_id: str
    case_id: str
    reviewer_actor: str
    protocol_hash: str
    case_manifest_hash: str
    release_manifest_hash: str
    stage: str
    issued_at: _dt.datetime

    def __post_init__(self) -> None:
        if self.stage not in PERMITTED_STAGES:
            raise PermitError(
                "a permit is bound to a stage at which reading the payload is "
                "part of the protocol; %s is not one" % self.stage)
        if self.issued_at.tzinfo is None:
            raise PermitError("a permit records a timezone-aware issue time")

    def permit_hash(self) -> str:
        return sha256_digest({
            "permit_version": self.permit_version,
            "assignment_id": self.assignment_id,
            "review_id": self.review_id,
            "case_id": self.case_id,
            "reviewer_actor": self.reviewer_actor,
            "protocol_hash": self.protocol_hash,
            "case_manifest_hash": self.case_manifest_hash,
            "release_manifest_hash": self.release_manifest_hash,
            "stage": self.stage,
        })

    def to_json(self) -> Dict[str, Any]:
        """Audit shape. Never returned to a client and never rendered."""
        return {
            "permit_version": self.permit_version,
            "assignment_id": self.assignment_id,
            "review_id": self.review_id,
            "case_id": self.case_id,
            "reviewer_actor": self.reviewer_actor,
            "stage": self.stage,
            "permit_hash": self.permit_hash(),
            "issued_at": self.issued_at.isoformat().replace("+00:00", "Z"),
        }


def issue_permit(assignment: ReviewAssignment, *,
                 now: _dt.datetime) -> PayloadPermit:
    """Issue a permit for an assignment at its current stage, or refuse.

    A completed or invalidated assignment gets no permit. That is the rule
    that keeps "what did the reviewer see, and when" answerable: a permit
    available after completion would let the payload be re-opened at a moment
    nobody can reconstruct.
    """
    if assignment.state.value not in PERMITTED_STAGES:
        raise PermitError(
            "no payload permit is issued at state %s; a finished review "
            "cannot re-open the material it was blinded on"
            % assignment.state.value,
            details={"state": assignment.state.value})
    return PayloadPermit(
        permit_version=PERMIT_VERSION,
        assignment_id=assignment.assignment_id,
        review_id=assignment.review_id,
        case_id=assignment.case_id,
        reviewer_actor=assignment.reviewer_actor,
        protocol_hash=assignment.protocol_hash,
        case_manifest_hash=assignment.case_manifest_hash,
        release_manifest_hash=assignment.release_manifest_hash,
        stage=assignment.state.value,
        issued_at=now.astimezone(_dt.timezone.utc))


def permit_allows(permit: Optional[PayloadPermit], *, case_id: str,
                  actor: str, case_manifest_hash: Optional[str] = None,
                  protocol_hash: Optional[str] = None) -> bool:
    """Whether this permit authorises this actor to read this case.

    Constant-time comparison on the actor and case, following the project's
    convention for identity comparison. These are not secrets, but the habit
    is the point: the first version of this function that gets copied into a
    context where they are should not be the timing-variable one.

    Returns a boolean rather than raising, because the caller records the
    refusal in the access ledger and must not lose the attempt to an
    exception.
    """
    if permit is None:
        return False
    if permit.permit_version != PERMIT_VERSION:
        return False
    if not hmac.compare_digest(str(permit.case_id), str(case_id)):
        return False
    if not hmac.compare_digest(str(permit.reviewer_actor), str(actor)):
        return False
    if case_manifest_hash is not None and \
            permit.case_manifest_hash != case_manifest_hash:
        return False
    if protocol_hash is not None and permit.protocol_hash != protocol_hash:
        return False
    return permit.stage in PERMITTED_STAGES
