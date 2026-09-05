# -*- coding: utf-8 -*-
"""In-memory reference implementation of the rule ports (WP-11).

Not a test double bolted on afterwards: this is the reference implementation
the SQLAlchemy adapter is compared against. Every rule the database enforces
with a constraint or a trigger is enforced here in Python, so the two can be
checked against each other by a test rather than by reading.

Rollback is real. Entering the unit of work snapshots every collection - the
audit list included - and leaving without committing restores them. A store
that dropped only the rule change on failure would keep an audit event
describing something that did not happen.
"""

from __future__ import annotations

import datetime as _dt
import itertools
from typing import (Any, Dict, List, Mapping, Optional, Sequence, Tuple)

from pgx.domain.enums import RuleStatus, RulesetStatus
from pgx.domain.identifiers import ComputableRuleId, RulesetVersionId
from pgx.rules.models import (ComputableRuleDefinition, RuleLifecycleRecord,
                              RulesetApprovalRecord, RulesetBuildRecord,
                              RulesetDefinition, RulesetMember)

__all__ = ["InMemoryRuleStore", "InMemoryRuleUnitOfWork"]


class InMemoryRuleStore:
    """The shared state several units of work operate on."""

    def __init__(self) -> None:
        self.definitions: Dict[str, ComputableRuleDefinition] = {}
        self.lifecycles: Dict[str, RuleLifecycleRecord] = {}
        self.rulesets: Dict[str, RulesetDefinition] = {}
        self.builds: List[RulesetBuildRecord] = []
        self.approvals: Dict[str, Tuple[RulesetApprovalRecord, ...]] = {}
        self.audit: List[Dict[str, Any]] = []
        self._ids = itertools.count(1)

    def next_id(self, prefix: str) -> str:
        return "%s-%06d" % (prefix, next(self._ids))

    def snapshot(self) -> Dict[str, Any]:
        return {
            "definitions": dict(self.definitions),
            "lifecycles": dict(self.lifecycles),
            "rulesets": dict(self.rulesets),
            "builds": list(self.builds),
            "approvals": dict(self.approvals),
            "audit": list(self.audit),
        }

    def restore(self, snapshot: Mapping[str, Any]) -> None:
        self.definitions = dict(snapshot["definitions"])
        self.lifecycles = dict(snapshot["lifecycles"])
        self.rulesets = dict(snapshot["rulesets"])
        self.builds = list(snapshot["builds"])
        self.approvals = dict(snapshot["approvals"])
        self.audit = list(snapshot["audit"])


class _Rules:
    def __init__(self, store: InMemoryRuleStore) -> None:
        self._store = store

    def add(self, definition: ComputableRuleDefinition,
            lifecycle: RuleLifecycleRecord) -> None:
        key = definition.rule_id.to_json()
        if key in self._store.definitions:
            raise KeyError("rule %s already exists" % key)
        for existing in self._store.definitions.values():
            if existing.family_id == definition.family_id and \
                    existing.rule_version == definition.rule_version:
                raise KeyError(
                    "family %s already has version %d; two answers claiming to "
                    "be the same revision of one question"
                    % (definition.family_id, definition.rule_version))
        self._store.definitions[key] = definition
        self._store.lifecycles[key] = lifecycle

    def get(self, rule_id: ComputableRuleId
            ) -> Optional[Tuple[ComputableRuleDefinition, RuleLifecycleRecord]]:
        key = rule_id.to_json()
        if key not in self._store.definitions:
            return None
        return self._store.definitions[key], self._store.lifecycles[key]

    def list_by_status(self, status: RuleStatus,
                       limit: int = 100) -> Sequence[ComputableRuleDefinition]:
        found = [definition for key, definition in self._store.definitions.items()
                 if self._store.lifecycles[key].status is status]
        return tuple(sorted(found, key=lambda item: item.sort_key()))[:limit]

    def list_family(self, family_id: str
                    ) -> Sequence[Tuple[ComputableRuleDefinition,
                                        RuleLifecycleRecord]]:
        pairs = [(definition, self._store.lifecycles[key])
                 for key, definition in self._store.definitions.items()
                 if definition.family_id.to_json() == family_id]
        return tuple(sorted(pairs, key=lambda pair: pair[0].rule_version))

    def count_by_status(self) -> Mapping[str, int]:
        counts: Dict[str, int] = {}
        for lifecycle in self._store.lifecycles.values():
            counts[lifecycle.status.value] = counts.get(lifecycle.status.value, 0) + 1
        return counts

    def guarded_status_update(self, rule_id: ComputableRuleId, *,
                              expected_status: RuleStatus,
                              expected_version: int,
                              new_status: RuleStatus,
                              content_hash: str,
                              actor: str,
                              at: _dt.datetime,
                              validation_result_hash: Optional[str] = None,
                              reason: Optional[str] = None) -> int:
        """The three-part predicate the SQL adapter issues, in Python."""
        key = rule_id.to_json()
        lifecycle = self._store.lifecycles.get(key)
        if lifecycle is None:
            return 0
        if lifecycle.status is not expected_status or \
                lifecycle.version != expected_version:
            return 0
        if lifecycle.is_immutable and lifecycle.content_hash != content_hash:
            return 0
        extra: Dict[str, Any] = {}
        if new_status is RuleStatus.VALIDATED:
            extra.update(validated_by=actor, validated_at=at,
                         validation_result_hash=validation_result_hash)
        else:
            extra.update(validated_by=lifecycle.validated_by,
                         validated_at=lifecycle.validated_at,
                         validation_result_hash=lifecycle.validation_result_hash)
        if new_status is RuleStatus.DEPRECATED:
            extra.update(deprecated_by=actor, deprecated_at=at,
                         deprecation_reason=reason)
        self._store.lifecycles[key] = RuleLifecycleRecord(
            rule_id=lifecycle.rule_id, status=new_status,
            version=lifecycle.version + 1, content_hash=lifecycle.content_hash,
            created_at=lifecycle.created_at, updated_at=at, **extra)
        return 1


class _Rulesets:
    def __init__(self, store: InMemoryRuleStore) -> None:
        self._store = store

    def add(self, ruleset: RulesetDefinition) -> None:
        key = ruleset.ruleset_id.to_json()
        if key in self._store.rulesets:
            raise KeyError("ruleset %s already exists" % key)
        self._store.rulesets[key] = ruleset

    def get(self, ruleset_id: RulesetVersionId) -> Optional[RulesetDefinition]:
        return self._store.rulesets.get(ruleset_id.to_json())

    def list_by_status(self, status: RulesetStatus,
                       limit: int = 100) -> Sequence[RulesetDefinition]:
        found = [item for item in self._store.rulesets.values()
                 if item.status is status]
        return tuple(sorted(found,
                            key=lambda item: item.public_id.to_json()))[:limit]

    def _replace(self, ruleset: RulesetDefinition, **changes: Any
                 ) -> RulesetDefinition:
        payload: Dict[str, Any] = {
            "ruleset_id": ruleset.ruleset_id, "public_id": ruleset.public_id,
            "status": ruleset.status, "version": ruleset.version,
            "created_by": ruleset.created_by, "created_at": ruleset.created_at,
            "members": ruleset.members, "manifest_hash": ruleset.manifest_hash,
            "ruleset_content_hash": ruleset.ruleset_content_hash,
            "frozen_at": ruleset.frozen_at, "frozen_by": ruleset.frozen_by,
            "retired_at": ruleset.retired_at, "retired_by": ruleset.retired_by,
            "retirement_reason": ruleset.retirement_reason,
            "updated_at": ruleset.updated_at,
        }
        payload.update(changes)
        return RulesetDefinition(**payload)

    def add_member(self, ruleset_id: RulesetVersionId, member: RulesetMember,
                   *, expected_version: int, actor: str,
                   at: _dt.datetime) -> int:
        ruleset = self._store.rulesets.get(ruleset_id.to_json())
        if ruleset is None or ruleset.version != expected_version:
            return 0
        ruleset.require_membership_open()
        if any(existing.rule_id == member.rule_id for existing in ruleset.members):
            return 0
        self._store.rulesets[ruleset_id.to_json()] = self._replace(
            ruleset, members=ruleset.members + (member,),
            version=ruleset.version + 1, updated_at=at)
        return 1

    def remove_member(self, ruleset_id: RulesetVersionId,
                      rule_id: ComputableRuleId, *, expected_version: int,
                      actor: str, at: _dt.datetime, reason: str) -> int:
        ruleset = self._store.rulesets.get(ruleset_id.to_json())
        if ruleset is None or ruleset.version != expected_version:
            return 0
        ruleset.require_membership_open()
        remaining = tuple(member for member in ruleset.members
                          if member.rule_id != rule_id)
        if len(remaining) == len(ruleset.members):
            return 0
        self._store.rulesets[ruleset_id.to_json()] = self._replace(
            ruleset, members=remaining, version=ruleset.version + 1,
            updated_at=at)
        return 1

    def guarded_status_update(self, ruleset_id: RulesetVersionId, *,
                              expected_status: RulesetStatus,
                              expected_version: int,
                              new_status: RulesetStatus,
                              actor: str,
                              at: _dt.datetime,
                              manifest_hash: Optional[str] = None,
                              ruleset_content_hash: Optional[str] = None,
                              reason: Optional[str] = None) -> int:
        ruleset = self._store.rulesets.get(ruleset_id.to_json())
        if ruleset is None:
            return 0
        if ruleset.status is not expected_status or \
                ruleset.version != expected_version:
            return 0
        changes: Dict[str, Any] = {
            "status": new_status, "version": ruleset.version + 1,
            "updated_at": at,
        }
        if new_status is RulesetStatus.FROZEN:
            changes.update(manifest_hash=manifest_hash,
                           ruleset_content_hash=ruleset_content_hash,
                           frozen_by=actor, frozen_at=at)
        if new_status is RulesetStatus.RETIRED:
            changes.update(retired_by=actor, retired_at=at,
                           retirement_reason=reason)
        self._store.rulesets[ruleset_id.to_json()] = self._replace(
            ruleset, **changes)
        return 1

    def record_build(self, record: RulesetBuildRecord) -> str:
        self._store.builds.append(record)
        return record.build_id.to_json()

    def record_approvals(self, ruleset_id: RulesetVersionId,
                         approvals: Sequence[RulesetApprovalRecord]) -> None:
        self._store.approvals[ruleset_id.to_json()] = tuple(approvals)


class _Audit:
    def __init__(self, store: InMemoryRuleStore) -> None:
        self._store = store

    def record(self, *, action: str, actor: str, object_type: str,
               object_id: str, occurred_at: _dt.datetime,
               reason: Optional[str] = None,
               metadata: Optional[Mapping[str, Any]] = None) -> str:
        event_id = self._store.next_id("AUDIT")
        self._store.audit.append({
            "audit_event_id": event_id, "action": action, "actor": actor,
            "object_type": object_type, "object_id": object_id,
            "occurred_at": occurred_at.isoformat().replace("+00:00", "Z"),
            "reason": reason, "metadata": dict(metadata or {}),
        })
        return event_id


class InMemoryRuleUnitOfWork:
    """One transaction over an :class:`InMemoryRuleStore`."""

    def __init__(self, store: InMemoryRuleStore) -> None:
        self._store = store
        self._snapshot: Optional[Mapping[str, Any]] = None
        self._committed = False
        self.rules = _Rules(store)
        self.rulesets = _Rulesets(store)
        self.audit = _Audit(store)

    def __enter__(self) -> "InMemoryRuleUnitOfWork":
        self._snapshot = self._store.snapshot()
        self._committed = False
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if not self._committed:
            self.rollback()

    def commit(self) -> None:
        self._committed = True
        self._snapshot = None

    def rollback(self) -> None:
        if self._snapshot is not None:
            self._store.restore(self._snapshot)
            self._snapshot = None
