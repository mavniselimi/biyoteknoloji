# -*- coding: utf-8 -*-
"""Rule lifecycle application service (WP-11).

The one place a rule changes state. Every operation resolves the actor's roles
through an injected provider, checks policy, runs the validator, issues a
guarded update requiring exactly one affected row, and writes exactly one audit
event in the same transaction.

Nothing here decides science. The service checks that a named person with a
suitable role performed an audited act after every gate opened; whether the
conclusion is *correct* was decided by the curation workflow, and this layer
cannot and does not second-guess it.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from typing import (Any, Callable, Dict, Mapping, Optional, Sequence, Tuple)

from pgx.curation.vocabulary import CurationRole
from pgx.curation.workflow.errors import ActorError, RoleViolationError
from pgx.curation.workflow.roles import ActorContext, RoleProvider
from pgx.domain.enums import AuditAction, RuleStatus
from pgx.domain.identifiers import ComputableRuleId
from pgx.rules.errors import (RuleImmutabilityError, RuleLifecycleError,
                              RuleValidationError)
from pgx.rules.lifecycle import RULE_VALIDATION_ROLES
from pgx.rules.models import (ComputableRuleDefinition, RuleLifecycleRecord,
                              allowed_rule_transitions)
from pgx.rules.validator import (ValidationContext, ValidationReport,
                                 validate_rule)

__all__ = ["RuleService", "RuleTransitionResult"]

#: Which audit action each transition writes.
_ACTIONS: Mapping[RuleStatus, AuditAction] = {
    RuleStatus.DRAFT: AuditAction.RULE_DRAFTED,
    RuleStatus.CURATED: AuditAction.RULE_CURATED,
    RuleStatus.VALIDATED: AuditAction.RULE_VALIDATED,
    RuleStatus.DEPRECATED: AuditAction.RULE_DEPRECATED,
}


@dataclass(frozen=True)
class RuleTransitionResult:
    """What one transition did, with the audit event it wrote."""

    definition: ComputableRuleDefinition
    lifecycle: RuleLifecycleRecord
    previous_status: RuleStatus
    previous_version: int
    audit_action: str
    audit_event_id: Optional[str] = None
    report: Optional[ValidationReport] = None

    def to_json(self) -> Dict[str, Any]:
        return {
            "rule_id": self.definition.rule_id.to_json(),
            "content_hash": self.definition.content_hash(),
            "previous_status": self.previous_status.value,
            "previous_version": self.previous_version,
            "new_status": self.lifecycle.status.value,
            "new_version": self.lifecycle.version,
            "audit_action": self.audit_action,
            "audit_event_id": self.audit_event_id,
            "validation": self.report.to_json() if self.report else None,
        }


class RuleService:
    """Moves rules, and refuses to move them wrongly."""

    def __init__(self, uow_factory: Callable[[], Any],
                 role_provider: RoleProvider,
                 clock: Optional[Callable[[], _dt.datetime]] = None) -> None:
        self._uow_factory = uow_factory
        self._roles = role_provider
        self._clock = clock or (lambda: _dt.datetime.now(tz=_dt.timezone.utc))

    # -- helpers --------------------------------------------------------

    def _actor(self, actor_id: str) -> ActorContext:
        """Resolve roles, never accept them.

        The single place an ``ActorContext`` enters this service. A caller
        wanting to supply its own roles would have to change this line, which
        is the point: self-elevation should require an edit somebody reviews.
        """
        if isinstance(actor_id, ActorContext) or actor_id is ActorContext:
            raise ActorError(
                "pass an actor id, not an ActorContext. Roles are resolved by "
                "the injected provider so a caller cannot assert its own "
                "permissions.")
        return self._roles.for_actor(actor_id)

    @staticmethod
    def _require_affected_one(affected: int, rule_id: ComputableRuleId,
                              expected_status: RuleStatus,
                              expected_version: int) -> None:
        if affected == 1:
            return
        if affected == 0:
            raise RuleLifecycleError(
                "rule %s was not at %s/version %d when this ran; somebody else "
                "moved it first, or its content changed"
                % (rule_id, expected_status.value, expected_version),
                current=expected_status.value)
        raise RuleLifecycleError(
            "a guarded update matched %d rows for one rule id; the store is "
            "not behaving as a keyed table" % affected)

    def _load(self, uow, rule_id: ComputableRuleId
              ) -> Tuple[ComputableRuleDefinition, RuleLifecycleRecord]:
        found = uow.rules.get(rule_id)
        if found is None:
            raise RuleLifecycleError("no rule %s" % rule_id)
        return found

    # -- operations -----------------------------------------------------

    def draft_rule(self, *, actor_id: str,
                   definition: ComputableRuleDefinition,
                   reason: str = "") -> RuleTransitionResult:
        """Create one DRAFT rule.

        A draft is not executable, cannot enter a ruleset and is never returned
        by the engine-facing registry. It exists so a curator can write a rule
        down and have somebody else look at it.
        """
        actor = self._actor(actor_id)
        if CurationRole.SCIENTIFIC_CURATOR not in actor.roles:
            raise RoleViolationError(
                "%s may not author a rule: it requires the SCIENTIFIC_CURATOR "
                "role" % actor.actor_id)
        if actor.actor_id.strip().lower() != definition.created_by.strip().lower():
            raise RoleViolationError(
                "the rule records %s as its author but %s is acting; a rule's "
                "author is who wrote it"
                % (definition.created_by, actor.actor_id))

        now = self._clock()
        lifecycle = RuleLifecycleRecord(
            rule_id=definition.rule_id, status=RuleStatus.DRAFT, version=0,
            content_hash=definition.content_hash(), created_at=now)
        with self._uow_factory() as uow:
            uow.rules.add(definition, lifecycle)
            event_id = uow.audit.record(
                action=AuditAction.RULE_DRAFTED.value, actor=actor.actor_id,
                object_type="computable_rule",
                object_id=definition.rule_id.to_json(), occurred_at=now,
                reason=reason or None,
                metadata={"family_id": definition.family_id.to_json(),
                          "rule_version": definition.rule_version,
                          "content_hash": definition.content_hash(),
                          "condition": str(definition.condition)})
            uow.commit()
        return RuleTransitionResult(
            definition=definition, lifecycle=lifecycle,
            previous_status=RuleStatus.DRAFT, previous_version=0,
            audit_action=AuditAction.RULE_DRAFTED.value, audit_event_id=event_id)

    def mark_curated(self, *, actor_id: str, rule_id: ComputableRuleId,
                     expected_version: int, context: ValidationContext,
                     reason: str = "") -> RuleTransitionResult:
        """DRAFT -> CURATED.

        Requires the referenced interpretation to be genuinely ``CURATED`` in
        WP-10, at the exact revision whose hash still matches. A rule built
        from a ``RAW`` or ``UNDER_REVIEW`` item would make the whole curation
        workflow decorative.
        """
        actor = self._actor(actor_id)
        if CurationRole.SCIENTIFIC_CURATOR not in actor.roles:
            raise RoleViolationError(
                "%s may not curate a rule: it requires the SCIENTIFIC_CURATOR "
                "role" % actor.actor_id)

        with self._uow_factory() as uow:
            definition, lifecycle = self._load(uow, rule_id)
            lifecycle.require_transition(RuleStatus.CURATED)
            report = validate_rule(definition, context,
                                   target_status=RuleStatus.CURATED,
                                   lifecycle=lifecycle)
            if not report.passed:
                raise RuleValidationError(
                    "rule %s cannot be marked CURATED: %s"
                    % (rule_id, "; ".join(sorted(report.codes))),
                    issues=report.issues)
            now = self._clock()
            affected = uow.rules.guarded_status_update(
                rule_id, expected_status=RuleStatus.DRAFT,
                expected_version=expected_version,
                new_status=RuleStatus.CURATED,
                content_hash=definition.content_hash(),
                actor=actor.actor_id, at=now)
            self._require_affected_one(affected, rule_id, RuleStatus.DRAFT,
                                       expected_version)
            event_id = uow.audit.record(
                action=AuditAction.RULE_CURATED.value, actor=actor.actor_id,
                object_type="computable_rule", object_id=rule_id.to_json(),
                occurred_at=now, reason=reason or None,
                metadata={"content_hash": definition.content_hash(),
                          "curation_revision_id":
                              definition.provenance.curation_revision_id,
                          "curation_revision_hash":
                              definition.provenance.curation_revision_hash})
            _, moved = self._load(uow, rule_id)
            uow.commit()
        return RuleTransitionResult(
            definition=definition, lifecycle=moved,
            previous_status=RuleStatus.DRAFT, previous_version=expected_version,
            audit_action=AuditAction.RULE_CURATED.value,
            audit_event_id=event_id, report=report)

    def validate(self, *, actor_id: str, rule_id: ComputableRuleId,
                 expected_version: int, context: ValidationContext,
                 reason: str = "") -> RuleTransitionResult:
        """CURATED -> VALIDATED.

        Runs every validation layer. A refusal writes a
        ``RULE_VALIDATION_REFUSED`` audit event and no state change: an
        attempted validation is itself worth recording, and the two must never
        be confused.
        """
        actor = self._actor(actor_id)
        if not (actor.roles & RULE_VALIDATION_ROLES):
            raise RoleViolationError(
                "%s may not validate a rule: it requires one of %s"
                % (actor.actor_id,
                   ", ".join(sorted(role.value for role in RULE_VALIDATION_ROLES))))

        with self._uow_factory() as uow:
            definition, lifecycle = self._load(uow, rule_id)
            lifecycle.require_transition(RuleStatus.VALIDATED)
            checked = ValidationContext(
                **dict(context.__dict__,
                       actor_id=actor.actor_id,
                       actor_roles=frozenset(actor.roles)))
            report = validate_rule(definition, checked,
                                   target_status=RuleStatus.VALIDATED,
                                   lifecycle=lifecycle)
            now = self._clock()
            if not report.passed:
                uow.audit.record(
                    action=AuditAction.RULE_VALIDATION_REFUSED.value,
                    actor=actor.actor_id, object_type="computable_rule",
                    object_id=rule_id.to_json(), occurred_at=now,
                    reason="validation refused",
                    metadata={"issue_codes": list(report.codes),
                              "result_hash": report.result_hash()})
                uow.commit()
                raise RuleValidationError(
                    "rule %s cannot be validated: %s"
                    % (rule_id, "; ".join(sorted(report.codes))),
                    issues=report.issues)

            affected = uow.rules.guarded_status_update(
                rule_id, expected_status=RuleStatus.CURATED,
                expected_version=expected_version,
                new_status=RuleStatus.VALIDATED,
                content_hash=definition.content_hash(),
                actor=actor.actor_id, at=now,
                validation_result_hash=report.result_hash())
            self._require_affected_one(affected, rule_id, RuleStatus.CURATED,
                                       expected_version)
            event_id = uow.audit.record(
                action=AuditAction.RULE_VALIDATED.value, actor=actor.actor_id,
                object_type="computable_rule", object_id=rule_id.to_json(),
                occurred_at=now, reason=reason or None,
                metadata={"content_hash": definition.content_hash(),
                          "validation_result_hash": report.result_hash(),
                          "approval_envelope_hash":
                              definition.provenance.approval_envelope_hash,
                          "author": definition.created_by})
            _, moved = self._load(uow, rule_id)
            uow.commit()
        return RuleTransitionResult(
            definition=definition, lifecycle=moved,
            previous_status=RuleStatus.CURATED,
            previous_version=expected_version,
            audit_action=AuditAction.RULE_VALIDATED.value,
            audit_event_id=event_id, report=report)

    def deprecate(self, *, actor_id: str, rule_id: ComputableRuleId,
                  expected_version: int, reason: str) -> RuleTransitionResult:
        """VALIDATED -> DEPRECATED.

        The rule is never deleted. Frozen rulesets that cite it must stay
        verifiable, and an assessment made last year has to remain explicable.
        """
        actor = self._actor(actor_id)
        if not (actor.roles & RULE_VALIDATION_ROLES):
            raise RoleViolationError(
                "%s may not deprecate a rule: it requires one of %s"
                % (actor.actor_id,
                   ", ".join(sorted(role.value for role in RULE_VALIDATION_ROLES))))
        if not (reason or "").strip():
            raise RuleLifecycleError(
                "deprecation requires a stated reason; a rule withdrawn "
                "without one cannot be reviewed")

        with self._uow_factory() as uow:
            definition, lifecycle = self._load(uow, rule_id)
            lifecycle.require_transition(RuleStatus.DEPRECATED)
            now = self._clock()
            affected = uow.rules.guarded_status_update(
                rule_id, expected_status=RuleStatus.VALIDATED,
                expected_version=expected_version,
                new_status=RuleStatus.DEPRECATED,
                content_hash=definition.content_hash(),
                actor=actor.actor_id, at=now, reason=reason)
            self._require_affected_one(affected, rule_id, RuleStatus.VALIDATED,
                                       expected_version)
            event_id = uow.audit.record(
                action=AuditAction.RULE_DEPRECATED.value, actor=actor.actor_id,
                object_type="computable_rule", object_id=rule_id.to_json(),
                occurred_at=now, reason=reason,
                metadata={"content_hash": definition.content_hash(),
                          "note": "the rule is retained; frozen rulesets that "
                                  "cite it stay verifiable"})
            _, moved = self._load(uow, rule_id)
            uow.commit()
        return RuleTransitionResult(
            definition=definition, lifecycle=moved,
            previous_status=RuleStatus.VALIDATED,
            previous_version=expected_version,
            audit_action=AuditAction.RULE_DEPRECATED.value,
            audit_event_id=event_id)

    # -- read-only ------------------------------------------------------

    def inspect(self, rule_id: ComputableRuleId) -> Dict[str, Any]:
        with self._uow_factory() as uow:
            definition, lifecycle = self._load(uow, rule_id)
        return {"definition": definition.to_json(),
                "lifecycle": lifecycle.to_json()}

    def counts(self) -> Mapping[str, int]:
        with self._uow_factory() as uow:
            return dict(uow.rules.count_by_status())
