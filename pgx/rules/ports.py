# -*- coding: utf-8 -*-
"""Persistence and registry ports for the rule layer (WP-11).

Structural ``Protocol`` contracts, in the WP-02 style. Two things about their
shape are deliberate.

**No port returns an unvalidated rule for execution.** ``RuleRepository`` can
list by status because a curator and a CLI need to see drafts, but the
*engine-facing* port - :class:`ExecutableRulesetRegistry` - has one method, and
it returns a fully verified frozen ruleset or raises. There is no
``get_rules()`` an engine could reach for.

**Append-only records offer no update.** ``RuleAuditSink`` has ``record`` and
nothing else. The method a caller reaches for and finds absent is a better
guarantee than a method that exists and is documented not to be used.
"""

from __future__ import annotations

import datetime as _dt
from typing import (Any, Mapping, Optional, Protocol, Sequence, Tuple,
                    runtime_checkable)

from pgx.domain.enums import RuleStatus, RulesetStatus
from pgx.domain.identifiers import ComputableRuleId, RulesetVersionId
from pgx.rules.models import (ComputableRuleDefinition, FrozenRuleset,
                              RuleLifecycleRecord, RulesetApprovalRecord,
                              RulesetBuildRecord, RulesetDefinition,
                              RulesetMember)

__all__ = [
    "ExecutableRulesetRegistry",
    "RuleAuditSink",
    "RuleRepository",
    "RuleWorkflowUnitOfWork",
    "RulesetRepository",
]


@runtime_checkable
class RuleRepository(Protocol):
    """Persistence for rule definitions and their lifecycle records."""

    def add(self, definition: ComputableRuleDefinition,
            lifecycle: RuleLifecycleRecord) -> None:
        """Store a new rule version and its initial lifecycle state."""

    def get(self, rule_id: ComputableRuleId
            ) -> Optional[Tuple[ComputableRuleDefinition, RuleLifecycleRecord]]:
        """Return one rule's definition and lifecycle, or ``None``."""

    def list_by_status(self, status: RuleStatus,
                       limit: int = 100) -> Sequence[ComputableRuleDefinition]:
        """Rules in one lifecycle state, for curators and reporting.

        Explicitly not an execution path: the engine reads
        :class:`ExecutableRulesetRegistry`, which cannot return anything that
        is not in a frozen ruleset.
        """

    def list_family(self, family_id: str
                    ) -> Sequence[Tuple[ComputableRuleDefinition,
                                        RuleLifecycleRecord]]:
        """Every version in one lineage, oldest first."""

    def count_by_status(self) -> Mapping[str, int]:
        """How many rules are in each state."""

    def guarded_status_update(self, rule_id: ComputableRuleId, *,
                              expected_status: RuleStatus,
                              expected_version: int,
                              new_status: RuleStatus,
                              content_hash: str,
                              actor: str,
                              at: _dt.datetime,
                              validation_result_hash: Optional[str] = None,
                              reason: Optional[str] = None) -> int:
        """Advance one rule, returning the number of rows changed.

        Exactly one means success. Zero means somebody moved it first - which
        the caller must distinguish from "it did not exist", because those need
        different answers.
        """


@runtime_checkable
class RulesetRepository(Protocol):
    """Persistence for rulesets, their membership and their builds."""

    def add(self, ruleset: RulesetDefinition) -> None:
        """Store a new BUILDING ruleset."""

    def get(self, ruleset_id: RulesetVersionId) -> Optional[RulesetDefinition]:
        """Return one ruleset, or ``None``."""

    def list_by_status(self, status: RulesetStatus,
                       limit: int = 100) -> Sequence[RulesetDefinition]:
        """Rulesets in one lifecycle state."""

    def add_member(self, ruleset_id: RulesetVersionId, member: RulesetMember,
                   *, expected_version: int, actor: str,
                   at: _dt.datetime) -> int:
        """Pin one rule into a BUILDING ruleset."""

    def remove_member(self, ruleset_id: RulesetVersionId,
                      rule_id: ComputableRuleId, *, expected_version: int,
                      actor: str, at: _dt.datetime, reason: str) -> int:
        """Unpin one rule from a BUILDING ruleset."""

    def guarded_status_update(self, ruleset_id: RulesetVersionId, *,
                              expected_status: RulesetStatus,
                              expected_version: int,
                              new_status: RulesetStatus,
                              actor: str,
                              at: _dt.datetime,
                              manifest_hash: Optional[str] = None,
                              ruleset_content_hash: Optional[str] = None,
                              reason: Optional[str] = None) -> int:
        """Advance one ruleset, returning the number of rows changed."""

    def record_build(self, record: RulesetBuildRecord) -> str:
        """Append one build attempt. Builds are never updated in place."""

    def record_approvals(self, ruleset_id: RulesetVersionId,
                         approvals: Sequence[RulesetApprovalRecord]) -> None:
        """Store the approval list a validation attempt captured."""


@runtime_checkable
class RuleAuditSink(Protocol):
    """Append-only audit events for rule and ruleset state changes."""

    def record(self, *, action: str, actor: str, object_type: str,
               object_id: str, occurred_at: _dt.datetime,
               reason: Optional[str] = None,
               metadata: Optional[Mapping[str, Any]] = None) -> str:
        """Append one event, in the caller's transaction."""


@runtime_checkable
class RuleWorkflowUnitOfWork(Protocol):
    """One transaction across rules, rulesets and the audit trail.

    The audit event and the change it describes commit together or not at all.
    A trail describing a transition that rolled back would be worse than no
    trail, because somebody would believe it.
    """

    rules: RuleRepository
    rulesets: RulesetRepository
    audit: RuleAuditSink

    def __enter__(self) -> "RuleWorkflowUnitOfWork": ...

    def __exit__(self, exc_type, exc, tb) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


@runtime_checkable
class ExecutableRulesetRegistry(Protocol):
    """The only thing an engine is ever handed.

    One method, and it returns a fully verified :class:`FrozenRuleset` or
    raises. There is deliberately no way to ask for a rule, a draft, a
    ``BUILDING`` set, or a ruleset whose checksums have not been checked: the
    absence of the method is the guarantee.
    """

    def list_executable(self) -> Sequence[str]:
        """Identities of the frozen rulesets this registry can serve."""

    def load(self, public_id: str) -> FrozenRuleset:
        """Load and fully verify one frozen ruleset, or raise."""
