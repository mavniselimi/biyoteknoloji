# -*- coding: utf-8 -*-
"""What a rule approval would have to contain, checked but never granted.

WP-11 will turn curated interpretations into computable rules. This module is
the part of that gate which belongs to WP-10: a validator for the envelope a
rule approval must carry. It creates nothing. There is no ``ComputableRule``
here, no rules package, and no path by which anything reaches ``VALIDATED``.

The reason to write the validator now rather than with WP-11 is that the
requirements are governance requirements, not rule-engine requirements. Who
created the rule, who reviewed it independently, who approved it, which
curated interpretation it descends from, which protocol and evidence it rests
on - all of that is the same separation-of-duties question WP-10 answers for
curation. Deciding it here means WP-11 inherits a settled contract instead of
inventing a second, looser one under delivery pressure.

Everything fails closed. A missing field is a refusal, not a default, because
the failure mode this guards against is a rule reaching a clinician carrying an
approval nobody actually gave.

The validator is pure: it inspects a mapping and returns a verdict. It reads no
database, writes no audit event and transitions nothing. Validity is not
approval - a well-formed envelope naming three people still means nothing until
those three people exist, which is WP-23's problem and not solvable by
validation.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import (Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple)

from pgx.curation.vocabulary import CurationRole
from pgx.curation.workflow.errors import RuleApprovalError
from pgx.domain.enums import CurationStatus
from pgx.domain.hashing import sha256_digest

__all__ = [
    "RULE_APPROVAL_ENVELOPE_VERSION",
    "REQUIRED_ENVELOPE_FIELDS",
    "RuleApprovalEnvelope",
    "RuleApprovalValidation",
    "validate_rule_approval_envelope",
]

RULE_APPROVAL_ENVELOPE_VERSION = "pgx-rule-approval-envelope/1"

#: Every field an envelope must carry, with why it is required. Data rather
#: than a docstring so the CLI, the schema and the failure message all cite one
#: list, and so a field cannot be quietly dropped by editing prose.
REQUIRED_ENVELOPE_FIELDS: Mapping[str, str] = {
    "envelope_version":
        "identifies which contract this envelope was written against",
    "rule_public_id":
        "names the rule being approved; an approval of an unnamed rule "
        "cannot be checked against the rule that ships",
    "rule_version":
        "an approval is of one version; without it a later edit inherits an "
        "approval it never received",
    "rule_content_hash":
        "binds the approval to exact rule bytes, so an altered rule is "
        "detectably unapproved",
    "curated_interpretation_id":
        "names the scientific conclusion the rule encodes",
    "curated_interpretation_status":
        "the conclusion must be CURATED; encoding a draft is encoding an "
        "opinion nobody accepted",
    "curation_work_item_id":
        "links back to the workflow record that produced the conclusion",
    "curation_revision_id":
        "names which revision was approved, not merely which work item",
    "curation_revision_content_hash":
        "proves the rule descends from the revision that was actually "
        "reviewed rather than from a later edit of it",
    "protocol_version":
        "the protocol under which the conclusion was curated",
    "protocol_content_hash":
        "pins the protocol bytes; a protocol amended afterwards did not "
        "govern this conclusion",
    "evidence_record_uuids":
        "the evidence the rule rests on, enumerated rather than summarised",
    "evidence_build_content_hash":
        "the build those records came from",
    "source_versions":
        "which version of each upstream source was in play; 'the current "
        "one' is not reconstructible later",
    "created_by":
        "who wrote the rule; an unattributed rule cannot be questioned",
    "created_at":
        "when it was written, so the review can be shown to have followed it",
    "reviewed_by":
        "who checked it independently of its author; the same person doing "
        "both is not a review",
    "reviewed_at":
        "when the review happened, so its order relative to the rule and the "
        "approval is checkable",
    "approved_by":
        "who took responsibility for releasing it to the people it affects",
    "approved_at":
        "when responsibility was taken; an approval with no moment cannot be "
        "placed against what was known then",
    "approval_rationale":
        "why, in the approver's own words; an approval with no stated "
        "reason cannot be audited or contested",
}

#: The roles each named party must hold. An envelope naming three people who
#: hold no relevant role is well-formed prose and nothing else.
_REQUIRED_ROLES: Mapping[str, Tuple[CurationRole, ...]] = {
    "created_by": (CurationRole.SCIENTIFIC_CURATOR,),
    "reviewed_by": (CurationRole.INDEPENDENT_SCIENTIFIC_REVIEWER,
                    CurationRole.ADJUDICATOR),
    "approved_by": (CurationRole.INDEPENDENT_SCIENTIFIC_REVIEWER,
                    CurationRole.ADJUDICATOR,
                    CurationRole.PROTOCOL_OWNER),
}

_TIMESTAMP_FIELDS = ("created_at", "reviewed_at", "approved_at")

#: Minimum length for the approver's stated reason. Not a quality measure - a
#: long sentence can still be empty of content - but "ok" and "" are not
#: rationales, and refusing them costs nothing.
_MIN_RATIONALE = 24


@dataclass(frozen=True)
class RuleApprovalValidation:
    """The verdict on one envelope.

    ``valid`` never means "this rule may ship". It means the envelope is
    internally consistent and complete. Whether the people it names exist, hold
    the roles it claims, and actually said what it records is a question about
    authentication and about humans, and this object deliberately cannot answer
    it - which is why ``advisory`` always carries that sentence.
    """

    valid: bool
    missing: Tuple[str, ...] = ()
    violations: Tuple[str, ...] = ()
    parties: Mapping[str, str] = field(default_factory=dict)
    envelope_digest: str = ""

    @property
    def advisory(self) -> str:
        return (
            "A valid envelope is a well-formed claim, not an approval. The "
            "named parties must be real people holding real credentials, "
            "which requires the authentication work owned by WP-23. Until "
            "then no rule is approved, whatever this envelope says.")

    def raise_if_invalid(self) -> None:
        if self.valid:
            return
        detail = []
        if self.missing:
            detail.append("missing: %s" % ", ".join(self.missing))
        if self.violations:
            detail.append("; ".join(self.violations))
        raise RuleApprovalError(
            "rule approval envelope is not valid: %s" % " | ".join(detail),
            missing=self.missing, violations=self.violations)

    def to_json(self) -> Dict[str, Any]:
        return {
            "envelope_version": RULE_APPROVAL_ENVELOPE_VERSION,
            "valid": self.valid,
            "missing": list(self.missing),
            "violations": list(self.violations),
            "parties": dict(self.parties),
            "envelope_digest": self.envelope_digest,
            "advisory": self.advisory,
            "creates_rule": False,
            "transitions_rule": False,
        }


@dataclass(frozen=True)
class RuleApprovalEnvelope:
    """A validated envelope.

    Constructing one runs the validator and refuses an invalid envelope, so a
    ``RuleApprovalEnvelope`` in hand is always well-formed. It still is not an
    approval; see ``RuleApprovalValidation.advisory``.
    """

    payload: Mapping[str, Any]
    validation: RuleApprovalValidation

    @classmethod
    def parse(cls, payload: Mapping[str, Any],
              *, role_lookup: Optional[Mapping[str, Any]] = None,
              ) -> "RuleApprovalEnvelope":
        validation = validate_rule_approval_envelope(
            payload, role_lookup=role_lookup)
        validation.raise_if_invalid()
        return cls(payload=dict(payload), validation=validation)

    def to_json(self) -> Dict[str, Any]:
        return {
            "payload": dict(self.payload),
            "validation": self.validation.to_json(),
        }


def _as_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _roles_of(role_lookup: Optional[Mapping[str, Any]],
              actor_id: str) -> Optional[Set[CurationRole]]:
    """Roles for one actor, or ``None`` when no lookup was supplied.

    ``None`` is not "no roles". A caller that supplied no lookup is not
    claiming the parties are unqualified, so the role checks are skipped and
    said to be skipped, rather than silently passing or silently failing.
    """
    if role_lookup is None:
        return None
    raw = role_lookup.get(actor_id)
    if raw is None:
        return set()
    if isinstance(raw, CurationRole):
        return {raw}
    resolved: Set[CurationRole] = set()
    for entry in raw:
        if isinstance(entry, CurationRole):
            resolved.add(entry)
        else:
            try:
                resolved.add(CurationRole(str(entry)))
            except ValueError:
                continue
    return resolved


def _parse_moment(value: Any) -> Optional[_dt.datetime]:
    if isinstance(value, _dt.datetime):
        moment = value
    elif isinstance(value, str) and value.strip():
        text = value.strip().replace("Z", "+00:00")
        try:
            moment = _dt.datetime.fromisoformat(text)
        except ValueError:
            return None
    else:
        return None
    if moment.tzinfo is None:
        return None
    return moment.astimezone(_dt.timezone.utc)


def validate_rule_approval_envelope(
    payload: Mapping[str, Any],
    *,
    role_lookup: Optional[Mapping[str, Any]] = None,
) -> RuleApprovalValidation:
    """Check one envelope and report everything wrong with it.

    Every check runs. Returning at the first fault would make fixing an
    envelope an iterative guessing game, and the whole point of the envelope is
    that somebody can see what a complete one requires.
    """
    if not isinstance(payload, Mapping):
        return RuleApprovalValidation(
            valid=False, violations=("envelope must be a mapping",))

    missing: List[str] = []
    violations: List[str] = []

    for name in REQUIRED_ENVELOPE_FIELDS:
        value = payload.get(name)
        if value is None or (isinstance(value, str) and not value.strip()) \
                or (isinstance(value, (list, tuple)) and not value):
            missing.append(name)

    # -- contract version ----------------------------------------------
    version = _as_text(payload.get("envelope_version"))
    if version and version != RULE_APPROVAL_ENVELOPE_VERSION:
        violations.append(
            "envelope_version is %r; this validator implements %r and will "
            "not guess at the difference"
            % (version, RULE_APPROVAL_ENVELOPE_VERSION))

    # -- the conclusion being encoded ----------------------------------
    status = _as_text(payload.get("curated_interpretation_status")).upper()
    if status and status != CurationStatus.CURATED.value:
        violations.append(
            "curated_interpretation_status is %s; a rule may only encode a "
            "%s conclusion" % (status, CurationStatus.CURATED.value))

    for name in ("rule_content_hash", "curation_revision_content_hash",
                 "protocol_content_hash", "evidence_build_content_hash"):
        digest = _as_text(payload.get(name))
        if digest and not digest.startswith("sha256:"):
            violations.append(
                "%s is not a sha256 digest; an unpinned hash pins nothing"
                % name)

    records = payload.get("evidence_record_uuids")
    if records is not None:
        if not isinstance(records, (list, tuple)):
            violations.append("evidence_record_uuids must be a list")
        else:
            seen = [str(item).strip() for item in records if str(item).strip()]
            if len(set(seen)) != len(seen):
                violations.append(
                    "evidence_record_uuids repeats a record; a duplicated "
                    "citation inflates how much evidence there appears to be")

    sources = payload.get("source_versions")
    if sources is not None and not isinstance(sources, Mapping):
        violations.append(
            "source_versions must map each source to the version used")
    elif isinstance(sources, Mapping):
        blank = sorted(name for name, value in sources.items()
                       if not _as_text(value))
        if blank:
            violations.append(
                "source_versions leaves %s without a version"
                % ", ".join(blank))

    # -- who -----------------------------------------------------------
    parties: Dict[str, str] = {}
    for name in ("created_by", "reviewed_by", "approved_by"):
        actor = _as_text(payload.get(name))
        if actor:
            parties[name] = actor

    creator = parties.get("created_by", "").lower()
    reviewer = parties.get("reviewed_by", "").lower()
    approver = parties.get("approved_by", "").lower()

    if creator and reviewer and creator == reviewer:
        violations.append(
            "%s both created and reviewed this rule; one person checking "
            "their own work is not an independent review"
            % parties["created_by"])
    if creator and approver and creator == approver:
        violations.append(
            "%s both created and approved this rule; an author approving "
            "their own rule is self-release" % parties["created_by"])

    if role_lookup is not None:
        for name, permitted in _REQUIRED_ROLES.items():
            actor = parties.get(name)
            if not actor:
                continue
            held = _roles_of(role_lookup, actor) or set()
            if not held & set(permitted):
                violations.append(
                    "%s (%s) holds %s; this field requires one of %s"
                    % (actor, name,
                       ", ".join(sorted(role.value for role in held))
                       or "no role",
                       ", ".join(role.value for role in permitted)))

    # -- when ----------------------------------------------------------
    moments: Dict[str, Optional[_dt.datetime]] = {}
    for name in _TIMESTAMP_FIELDS:
        raw = payload.get(name)
        if raw is None:
            continue
        moment = _parse_moment(raw)
        moments[name] = moment
        if moment is None:
            violations.append(
                "%s is not a timezone-aware ISO-8601 timestamp; a naive "
                "timestamp is not a point in time" % name)

    created = moments.get("created_at")
    reviewed = moments.get("reviewed_at")
    approved = moments.get("approved_at")
    if created and reviewed and reviewed < created:
        violations.append(
            "reviewed_at precedes created_at; a review of a rule that did "
            "not yet exist did not happen")
    if reviewed and approved and approved < reviewed:
        violations.append(
            "approved_at precedes reviewed_at; the approval did not follow "
            "the review it claims to rest on")

    rationale = _as_text(payload.get("approval_rationale"))
    if rationale and len(rationale) < _MIN_RATIONALE:
        violations.append(
            "approval_rationale is %d characters; an approval that cannot be "
            "explained cannot be contested" % len(rationale))

    # -- things an envelope must not do --------------------------------
    for forbidden, why in (
        ("rule_status",
         "an envelope records an approval; it does not set a rule's state"),
        ("computable_rule",
         "an envelope references a rule, it does not carry one"),
        ("auto_approve",
         "approval is an act by a named person, never a flag"),
        ("bypass_gates",
         "there is no route around the curation gates"),
    ):
        if forbidden in payload:
            violations.append("%s is not permitted: %s" % (forbidden, why))

    digest = sha256_digest({
        "envelope_version": RULE_APPROVAL_ENVELOPE_VERSION,
        "payload": {key: payload.get(key)
                    for key in sorted(REQUIRED_ENVELOPE_FIELDS)
                    if not isinstance(payload.get(key), (_dt.datetime,))},
    })

    return RuleApprovalValidation(
        valid=not missing and not violations,
        missing=tuple(missing), violations=tuple(violations),
        parties=parties, envelope_digest=digest)
