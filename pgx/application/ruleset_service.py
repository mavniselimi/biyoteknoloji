# -*- coding: utf-8 -*-
"""Ruleset lifecycle application service (WP-11).

Membership changes, validation, the deterministic build, freezing and
retirement. Every state change goes through a guarded update requiring exactly
one affected row and writes exactly one audit event in the same transaction.

Two decisions are worth stating plainly.

**Validating and freezing are separate acts.** There is no method that does
both, and no path from ``BUILDING`` to ``FROZEN``. Validation decides that a
membership is coherent; freezing publishes an artifact nobody may ever edit.
Collapsing them would let a set become permanent without anybody deciding it
should be.

**Reopening a validated ruleset discards its validation.** Adding a member to a
set that already validated does not carry the old result forward: the set that
validated is not the set that now exists.
"""

from __future__ import annotations

import datetime as _dt
import os
from dataclasses import dataclass
from typing import (Any, Callable, Dict, Mapping, Optional, Sequence, Tuple)

from pgx.curation.workflow.errors import ActorError, RoleViolationError
from pgx.curation.workflow.roles import ActorContext, RoleProvider
from pgx.domain.enums import AuditAction, RuleStatus, RulesetStatus
from pgx.domain.identifiers import ComputableRuleId, RulesetVersionId
from pgx.rules.builder import BuildInputs, BuildResult, build_ruleset
from pgx.rules.errors import (RuleValidationError, RulesetLifecycleError,
                              RulesetMembershipError)
from pgx.rules.lifecycle import RULE_VALIDATION_ROLES
from pgx.rules.models import (RulesetApprovalRecord, RulesetDefinition,
                              RulesetMember)
from pgx.rules.validator import ValidationReport, validate_ruleset_members

__all__ = ["RulesetService", "RulesetTransitionResult"]


@dataclass(frozen=True)
class RulesetTransitionResult:
    """What one ruleset operation did."""

    ruleset: RulesetDefinition
    previous_status: RulesetStatus
    previous_version: int
    audit_action: str
    audit_event_id: Optional[str] = None
    report: Optional[ValidationReport] = None
    build: Optional[BuildResult] = None

    def to_json(self) -> Dict[str, Any]:
        return {
            "ruleset_id": self.ruleset.ruleset_id.to_json(),
            "public_id": self.ruleset.public_id.to_json(),
            "previous_status": self.previous_status.value,
            "previous_version": self.previous_version,
            "new_status": self.ruleset.status.value,
            "new_version": self.ruleset.version,
            "member_count": self.ruleset.member_count,
            "audit_action": self.audit_action,
            "audit_event_id": self.audit_event_id,
            "validation": self.report.to_json() if self.report else None,
            "build": (self.build.record.to_json() if self.build else None),
        }


class RulesetService:
    """Moves rulesets, and refuses to move them wrongly."""

    def __init__(self, uow_factory: Callable[[], Any],
                 role_provider: RoleProvider,
                 clock: Optional[Callable[[], _dt.datetime]] = None) -> None:
        self._uow_factory = uow_factory
        self._roles = role_provider
        self._clock = clock or (lambda: _dt.datetime.now(tz=_dt.timezone.utc))

    def _actor(self, actor_id: str) -> ActorContext:
        if isinstance(actor_id, ActorContext) or actor_id is ActorContext:
            raise ActorError(
                "pass an actor id, not an ActorContext. Roles are resolved by "
                "the injected provider.")
        return self._roles.for_actor(actor_id)

    def _require_governance_role(self, actor: ActorContext, act: str) -> None:
        if not (actor.roles & RULE_VALIDATION_ROLES):
            raise RoleViolationError(
                "%s may not %s: it requires one of %s"
                % (actor.actor_id, act,
                   ", ".join(sorted(role.value for role in RULE_VALIDATION_ROLES))))

    @staticmethod
    def _require_affected_one(affected: int, ruleset_id: RulesetVersionId,
                              expected_version: int) -> None:
        if affected == 1:
            return
        if affected == 0:
            raise RulesetLifecycleError(
                "ruleset %s was not at version %d when this ran; somebody else "
                "moved it first" % (ruleset_id, expected_version))
        raise RulesetLifecycleError(
            "a guarded update matched %d rows for one ruleset id" % affected)

    def _load(self, uow, ruleset_id: RulesetVersionId) -> RulesetDefinition:
        found = uow.rulesets.get(ruleset_id)
        if found is None:
            raise RulesetLifecycleError("no ruleset %s" % ruleset_id)
        return found

    # -- operations -----------------------------------------------------

    def create(self, *, actor_id: str, ruleset: RulesetDefinition,
               reason: str = "") -> RulesetTransitionResult:
        """Create one BUILDING ruleset."""
        actor = self._actor(actor_id)
        self._require_governance_role(actor, "create a ruleset")
        if ruleset.status is not RulesetStatus.BUILDING:
            raise RulesetLifecycleError(
                "a new ruleset starts BUILDING; %s would assert a validation "
                "nobody performed" % ruleset.status.value,
                requested=ruleset.status.value)
        now = self._clock()
        with self._uow_factory() as uow:
            uow.rulesets.add(ruleset)
            event_id = uow.audit.record(
                action=AuditAction.RULESET_CREATED.value, actor=actor.actor_id,
                object_type="ruleset", object_id=ruleset.ruleset_id.to_json(),
                occurred_at=now, reason=reason or None,
                metadata={"public_id": ruleset.public_id.to_json()})
            uow.commit()
        return RulesetTransitionResult(
            ruleset=ruleset, previous_status=RulesetStatus.BUILDING,
            previous_version=ruleset.version,
            audit_action=AuditAction.RULESET_CREATED.value,
            audit_event_id=event_id)

    def add_member(self, *, actor_id: str, ruleset_id: RulesetVersionId,
                   rule_id: ComputableRuleId, expected_version: int,
                   reason: str = "") -> RulesetTransitionResult:
        """Pin one VALIDATED rule into a BUILDING ruleset."""
        actor = self._actor(actor_id)
        self._require_governance_role(actor, "change ruleset membership")
        now = self._clock()
        with self._uow_factory() as uow:
            ruleset = self._load(uow, ruleset_id)
            ruleset.require_membership_open()
            found = uow.rules.get(rule_id)
            if found is None:
                raise RulesetMembershipError("no rule %s" % rule_id)
            definition, lifecycle = found
            if lifecycle.status is not RuleStatus.VALIDATED:
                raise RulesetMembershipError(
                    "rule %s is %s; only VALIDATED rules enter a ruleset "
                    "(SAFETY-INV-003)" % (rule_id, lifecycle.status.value))
            member = RulesetMember(
                rule_id=definition.rule_id, family_id=definition.family_id,
                rule_version=definition.rule_version,
                content_hash=definition.content_hash())
            affected = uow.rulesets.add_member(
                ruleset_id, member, expected_version=expected_version,
                actor=actor.actor_id, at=now)
            if affected == 0 and any(existing.rule_id == rule_id
                                     for existing in ruleset.members):
                raise RulesetMembershipError(
                    "rule %s is already a member; a rule counted twice would be "
                    "weighted twice by anything reading the set" % rule_id)
            self._require_affected_one(affected, ruleset_id, expected_version)
            event_id = uow.audit.record(
                action=AuditAction.RULESET_MEMBER_ADDED.value,
                actor=actor.actor_id, object_type="ruleset",
                object_id=ruleset_id.to_json(), occurred_at=now,
                reason=reason or None,
                metadata={"rule_id": rule_id.to_json(),
                          "content_hash": definition.content_hash()})
            moved = self._load(uow, ruleset_id)
            uow.commit()
        return RulesetTransitionResult(
            ruleset=moved, previous_status=RulesetStatus.BUILDING,
            previous_version=expected_version,
            audit_action=AuditAction.RULESET_MEMBER_ADDED.value,
            audit_event_id=event_id)

    def remove_member(self, *, actor_id: str, ruleset_id: RulesetVersionId,
                      rule_id: ComputableRuleId, expected_version: int,
                      reason: str) -> RulesetTransitionResult:
        """Unpin one rule from a BUILDING ruleset."""
        actor = self._actor(actor_id)
        self._require_governance_role(actor, "change ruleset membership")
        if not (reason or "").strip():
            raise RulesetMembershipError(
                "removing a member requires a stated reason")
        now = self._clock()
        with self._uow_factory() as uow:
            ruleset = self._load(uow, ruleset_id)
            ruleset.require_membership_open()
            affected = uow.rulesets.remove_member(
                ruleset_id, rule_id, expected_version=expected_version,
                actor=actor.actor_id, at=now, reason=reason)
            self._require_affected_one(affected, ruleset_id, expected_version)
            event_id = uow.audit.record(
                action=AuditAction.RULESET_MEMBER_REMOVED.value,
                actor=actor.actor_id, object_type="ruleset",
                object_id=ruleset_id.to_json(), occurred_at=now, reason=reason,
                metadata={"rule_id": rule_id.to_json()})
            moved = self._load(uow, ruleset_id)
            uow.commit()
        return RulesetTransitionResult(
            ruleset=moved, previous_status=RulesetStatus.BUILDING,
            previous_version=expected_version,
            audit_action=AuditAction.RULESET_MEMBER_REMOVED.value,
            audit_event_id=event_id)

    def validate(self, *, actor_id: str, ruleset_id: RulesetVersionId,
                 expected_version: int, reason: str = ""
                 ) -> RulesetTransitionResult:
        """BUILDING -> VALIDATED.

        A refusal writes ``RULESET_VALIDATION_REFUSED`` and changes nothing.
        """
        actor = self._actor(actor_id)
        self._require_governance_role(actor, "validate a ruleset")
        now = self._clock()
        with self._uow_factory() as uow:
            ruleset = self._load(uow, ruleset_id)
            ruleset.require_transition(RulesetStatus.VALIDATED)
            definitions = []
            lifecycles: Dict[str, Any] = {}
            for member in ruleset.members:
                found = uow.rules.get(member.rule_id)
                if found is None:
                    continue
                definition, lifecycle = found
                definitions.append(definition)
                lifecycles[member.rule_id.to_json()] = lifecycle
            report = validate_ruleset_members(
                definitions, lifecycles,
                pinned_hashes={member.rule_id.to_json(): member.content_hash
                               for member in ruleset.members})
            if not report.passed:
                uow.audit.record(
                    action=AuditAction.RULESET_VALIDATION_REFUSED.value,
                    actor=actor.actor_id, object_type="ruleset",
                    object_id=ruleset_id.to_json(), occurred_at=now,
                    reason="validation refused",
                    metadata={"issue_codes": list(report.codes),
                              "result_hash": report.result_hash()})
                uow.commit()
                raise RuleValidationError(
                    "ruleset %s cannot be validated: %s"
                    % (ruleset_id, "; ".join(sorted(report.codes))),
                    issues=report.issues)
            affected = uow.rulesets.guarded_status_update(
                ruleset_id, expected_status=RulesetStatus.BUILDING,
                expected_version=expected_version,
                new_status=RulesetStatus.VALIDATED, actor=actor.actor_id,
                at=now)
            self._require_affected_one(affected, ruleset_id, expected_version)
            event_id = uow.audit.record(
                action=AuditAction.RULESET_VALIDATED.value, actor=actor.actor_id,
                object_type="ruleset", object_id=ruleset_id.to_json(),
                occurred_at=now, reason=reason or None,
                metadata={"member_count": ruleset.member_count,
                          "result_hash": report.result_hash()})
            moved = self._load(uow, ruleset_id)
            uow.commit()
        return RulesetTransitionResult(
            ruleset=moved, previous_status=RulesetStatus.BUILDING,
            previous_version=expected_version,
            audit_action=AuditAction.RULESET_VALIDATED.value,
            audit_event_id=event_id, report=report)

    def reopen(self, *, actor_id: str, ruleset_id: RulesetVersionId,
               expected_version: int, reason: str) -> RulesetTransitionResult:
        """VALIDATED -> BUILDING, discarding the validation result."""
        actor = self._actor(actor_id)
        self._require_governance_role(actor, "reopen a ruleset")
        if not (reason or "").strip():
            raise RulesetLifecycleError("reopening requires a stated reason")
        now = self._clock()
        with self._uow_factory() as uow:
            ruleset = self._load(uow, ruleset_id)
            ruleset.require_transition(RulesetStatus.BUILDING)
            affected = uow.rulesets.guarded_status_update(
                ruleset_id, expected_status=RulesetStatus.VALIDATED,
                expected_version=expected_version,
                new_status=RulesetStatus.BUILDING, actor=actor.actor_id, at=now,
                reason=reason)
            self._require_affected_one(affected, ruleset_id, expected_version)
            event_id = uow.audit.record(
                action=AuditAction.RULESET_REOPENED.value, actor=actor.actor_id,
                object_type="ruleset", object_id=ruleset_id.to_json(),
                occurred_at=now, reason=reason,
                metadata={"note": "the validation result is discarded: the set "
                                  "that validated is not the set that will "
                                  "exist after this change"})
            moved = self._load(uow, ruleset_id)
            uow.commit()
        return RulesetTransitionResult(
            ruleset=moved, previous_status=RulesetStatus.VALIDATED,
            previous_version=expected_version,
            audit_action=AuditAction.RULESET_REOPENED.value,
            audit_event_id=event_id)

    def build_and_freeze(self, *, actor_id: str, ruleset_id: RulesetVersionId,
                         expected_version: int, destination: str,
                         inputs_factory: Callable[[RulesetDefinition,
                                                   Sequence[Any],
                                                   Mapping[str, Any],
                                                   Sequence[RulesetApprovalRecord]],
                                                  BuildInputs],
                         approvals: Sequence[RulesetApprovalRecord],
                         reason: str = "") -> RulesetTransitionResult:
        """VALIDATED -> FROZEN, by way of a deterministic verified build.

        The artifact is written and verified *before* the state changes, so a
        ruleset is never marked frozen without an artifact behind it. If the
        build refuses, the state does not move and the refusal is audited.
        """
        actor = self._actor(actor_id)
        self._require_governance_role(actor, "freeze a ruleset")
        now = self._clock()
        with self._uow_factory() as uow:
            ruleset = self._load(uow, ruleset_id)
            ruleset.require_transition(RulesetStatus.FROZEN)
            definitions = []
            lifecycles: Dict[str, Any] = {}
            for member in ruleset.members:
                found = uow.rules.get(member.rule_id)
                if found is None:
                    continue
                definition, lifecycle = found
                definitions.append(definition)
                lifecycles[member.rule_id.to_json()] = lifecycle

            inputs = inputs_factory(ruleset, definitions, lifecycles, approvals)
            result = build_ruleset(inputs, destination=destination,
                                   built_by=actor.actor_id, clock=self._clock)
            uow.rulesets.record_build(result.record)
            if not result.succeeded:
                uow.audit.record(
                    action=AuditAction.RULESET_VALIDATION_REFUSED.value,
                    actor=actor.actor_id, object_type="ruleset",
                    object_id=ruleset_id.to_json(), occurred_at=now,
                    reason="build refused",
                    metadata={"issue_codes": list(result.record.issue_codes)})
                uow.commit()
                raise RuleValidationError(
                    "ruleset %s cannot be frozen: %s"
                    % (ruleset_id, "; ".join(result.record.issue_codes)),
                    issues=result.report.issues)

            uow.rulesets.record_approvals(ruleset_id, approvals)
            affected = uow.rulesets.guarded_status_update(
                ruleset_id, expected_status=RulesetStatus.VALIDATED,
                expected_version=expected_version,
                new_status=RulesetStatus.FROZEN, actor=actor.actor_id, at=now,
                manifest_hash=result.manifest.content_hash(),
                ruleset_content_hash=result.ruleset_content_hash)
            self._require_affected_one(affected, ruleset_id, expected_version)
            event_id = uow.audit.record(
                action=AuditAction.RULESET_FROZEN.value, actor=actor.actor_id,
                object_type="ruleset", object_id=ruleset_id.to_json(),
                occurred_at=now, reason=reason or None,
                metadata={"manifest_hash": result.manifest.content_hash(),
                          "ruleset_content_hash": result.ruleset_content_hash,
                          "member_count": result.record.member_count,
                          "artifact": result.record.artifact_relative_path})
            moved = self._load(uow, ruleset_id)
            uow.commit()
        return RulesetTransitionResult(
            ruleset=moved, previous_status=RulesetStatus.VALIDATED,
            previous_version=expected_version,
            audit_action=AuditAction.RULESET_FROZEN.value,
            audit_event_id=event_id, report=result.report, build=result)

    def retire(self, *, actor_id: str, ruleset_id: RulesetVersionId,
               expected_version: int, reason: str) -> RulesetTransitionResult:
        """FROZEN -> RETIRED. The artifact is kept."""
        actor = self._actor(actor_id)
        self._require_governance_role(actor, "retire a ruleset")
        if not (reason or "").strip():
            raise RulesetLifecycleError("retirement requires a stated reason")
        now = self._clock()
        with self._uow_factory() as uow:
            ruleset = self._load(uow, ruleset_id)
            ruleset.require_transition(RulesetStatus.RETIRED)
            affected = uow.rulesets.guarded_status_update(
                ruleset_id, expected_status=RulesetStatus.FROZEN,
                expected_version=expected_version,
                new_status=RulesetStatus.RETIRED, actor=actor.actor_id, at=now,
                reason=reason)
            self._require_affected_one(affected, ruleset_id, expected_version)
            event_id = uow.audit.record(
                action=AuditAction.RULESET_RETIRED.value, actor=actor.actor_id,
                object_type="ruleset", object_id=ruleset_id.to_json(),
                occurred_at=now, reason=reason,
                metadata={"note": "the frozen artifact is kept: assessments "
                                  "that cited it must stay reproducible"})
            moved = self._load(uow, ruleset_id)
            uow.commit()
        return RulesetTransitionResult(
            ruleset=moved, previous_status=RulesetStatus.FROZEN,
            previous_version=expected_version,
            audit_action=AuditAction.RULESET_RETIRED.value,
            audit_event_id=event_id)

    def inspect(self, ruleset_id: RulesetVersionId) -> Dict[str, Any]:
        with self._uow_factory() as uow:
            return self._load(uow, ruleset_id).to_json()
