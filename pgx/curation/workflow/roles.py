# -*- coding: utf-8 -*-
"""Who an actor is, and what that lets them do (WP-10).

Two rules shape this module.

**A role is never an argument.** It is looked up for an actor by an injected
:class:`RoleProvider`. A CLI flag, a form field or a function parameter that
carried a role would be self-elevation with extra steps: the caller asserting
their own permission and the system believing them. ``ActorContext`` can only
be built through a provider, and the constructor refuses roles handed to it
directly.

**The default assignment set is empty.** ``StaticRoleProvider()`` with no
arguments knows nobody. That is the honest state of this repository: no real
curator, reviewer or adjudicator identity exists, so nothing here can act.
Tests supply explicitly synthetic ``TEST-`` actors, which the provider marks
as such so a synthetic decision can never be mistaken for a real one.

This is **not authentication**. A role provider says what an identity is
allowed to do once you know the identity; establishing the identity securely
is WP-23's, and nothing here should be deployed as if it were not.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, Mapping, Optional, Sequence, Tuple

from pgx.curation.vocabulary import SCIENTIFIC_APPROVAL_ROLES, CurationRole
from pgx.curation.workflow.errors import ActorError, RoleViolationError

__all__ = [
    "EMPTY_ROLE_ASSIGNMENTS",
    "SYNTHETIC_ACTOR_PREFIX",
    "ActorContext",
    "RoleProvider",
    "StaticRoleProvider",
    "require_role",
]

#: The production assignment set. Empty, and it stays empty: this repository
#: has no real curator, reviewer or adjudicator, and inventing one to make the
#: workflow runnable would be the exact failure WP-09 and WP-10 exist to stop.
EMPTY_ROLE_ASSIGNMENTS: Mapping[str, FrozenSet[CurationRole]] = {}

#: Actors a test may create. The prefix is checked, not merely conventional,
#: so a synthetic approval carries a permanent mark rather than depending on
#: whoever reads it noticing the name.
SYNTHETIC_ACTOR_PREFIX = "TEST-"


@dataclass(frozen=True)
class ActorContext:
    """One identified actor and the roles a provider says they hold.

    ``_provider_token`` exists to make construction from outside a provider
    impossible in practice. It is not security - a determined caller can pass
    it - but it turns "I forgot roles come from a provider" from a silent bug
    into an error at the call site.
    """

    actor_id: str
    display_name: str
    roles: FrozenSet[CurationRole]
    synthetic: bool = False
    _provider_token: Any = None

    #: Names that look like a person and are not one. Reused from WP-09's
    #: signature check for the same reason: a decision attributed to 'system'
    #: names nobody who can be asked about it.
    PLACEHOLDER_IDS = (
        "test", "todo", "tbd", "team", "admin", "user", "system", "automated",
        "auto", "anonymous", "anon", "none", "nobody", "someone", "unknown",
        "reviewer", "curator", "approver", "ai", "llm", "claude", "gpt",
        "assistant", "model", "bot", "placeholder", "example", "sample",
        "dummy", "xxx", "n/a", "na",
    )

    def __post_init__(self) -> None:
        actor_id = str(self.actor_id or "").strip()
        if not actor_id:
            raise ActorError("an actor must be identified; anonymous actions "
                             "cannot be attributed and are refused")
        object.__setattr__(self, "actor_id", actor_id)
        if not str(self.display_name or "").strip():
            raise ActorError("actor %s has no display name" % actor_id)
        if self._provider_token is None:
            raise ActorError(
                "an ActorContext is issued by a RoleProvider, not constructed "
                "with roles. A role supplied by the caller is the caller "
                "asserting their own permission.")
        bare = actor_id[len(SYNTHETIC_ACTOR_PREFIX):] if self.synthetic \
            else actor_id
        if bare.strip().lower() in self.PLACEHOLDER_IDS:
            raise ActorError(
                "%r is a placeholder, not a person. A decision recorded "
                "against it names nobody who can be asked about it." % actor_id)
        if self.synthetic != actor_id.startswith(SYNTHETIC_ACTOR_PREFIX):
            raise ActorError(
                "actor %r and synthetic=%s disagree; a synthetic actor is "
                "named %s* so a synthetic decision is permanently marked"
                % (actor_id, self.synthetic, SYNTHETIC_ACTOR_PREFIX))
        object.__setattr__(self, "roles", frozenset(self.roles))
        for role in self.roles:
            if not isinstance(role, CurationRole):
                raise ActorError("roles hold CurationRole members; %r is not"
                                 % (role,))

    def has(self, role: CurationRole) -> bool:
        return role in self.roles

    @property
    def may_approve_science(self) -> bool:
        """Whether any held role may approve a scientific conclusion.

        Reads from WP-09's ``SCIENTIFIC_APPROVAL_ROLES`` rather than
        re-listing them, so the two cannot drift.
        """
        return bool(self.roles & SCIENTIFIC_APPROVAL_ROLES)

    def to_json(self) -> Dict[str, Any]:
        return {
            "actor_id": self.actor_id,
            "display_name": self.display_name,
            "roles": sorted(role.value for role in self.roles),
            "synthetic": self.synthetic,
        }


class RoleProvider:
    """Where an actor's roles come from.

    A protocol, deliberately narrow: one method, no mutation. WP-23 will
    supply an implementation backed by real identity; until then the only
    implementation is the static one below, whose production assignment set is
    empty.
    """

    def for_actor(self, actor_id: str) -> ActorContext:
        raise NotImplementedError


_TOKEN = object()


class StaticRoleProvider(RoleProvider):
    """Roles from an explicit in-memory map.

    Constructed with nothing, it knows nobody and every lookup fails. That is
    the production configuration, and it is why no real workflow can run in
    this repository.
    """

    def __init__(self,
                 assignments: Optional[Mapping[str, Sequence[CurationRole]]] = None,
                 display_names: Optional[Mapping[str, str]] = None) -> None:
        source = assignments if assignments is not None \
            else EMPTY_ROLE_ASSIGNMENTS
        self._assignments: Dict[str, FrozenSet[CurationRole]] = {
            str(key): frozenset(value) for key, value in source.items()}
        self._display_names = dict(display_names or {})

    def __len__(self) -> int:
        return len(self._assignments)

    @property
    def is_empty(self) -> bool:
        return not self._assignments

    def for_actor(self, actor_id: str) -> ActorContext:
        key = str(actor_id or "").strip()
        if key not in self._assignments:
            raise ActorError(
                "no roles are assigned to %r. This repository's production "
                "role assignment set is empty: no real curator, reviewer or "
                "adjudicator identity exists, so no real workflow can run."
                % key)
        return ActorContext(
            actor_id=key,
            display_name=self._display_names.get(key, key),
            roles=self._assignments[key],
            synthetic=key.startswith(SYNTHETIC_ACTOR_PREFIX),
            _provider_token=_TOKEN)


def require_role(actor: ActorContext, role: CurationRole, act: str) -> None:
    """Refuse ``act`` unless ``actor`` holds ``role``.

    The message names the act rather than the role, because "you may not
    approve this" is what the reader needs, and the role they lack is a detail
    of why.
    """
    if not isinstance(actor, ActorContext):
        raise ActorError("an ActorContext is required to %s" % act)
    if role not in actor.roles:
        raise RoleViolationError(
            "%s may not %s: it requires the %s role, and this actor holds %s"
            % (actor.actor_id, act, role.value,
               ", ".join(sorted(item.value for item in actor.roles)) or "none"))
