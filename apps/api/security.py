"""Who is acting, and what a route lets that actor reach.

WP-23 owns authentication. This module is deliberately not it: there is no
password hashing here, no session, no signup, no token minting, no JWT, no
cookie, no CSRF token and no Argon2 parameter. What P0 needs from
authentication is narrower than authentication - it needs a *trusted actor and
role for the audit trail*, and a place where a route can say which roles may
reach it. Those two things are defined here so that WP-23 can replace the
mechanism behind them without touching a router.

Three decisions in this module are load-bearing.

**A principal is produced by a resolver, never by a request body.** §8 of the
work package requires the audited actor and role to come from the
authenticated principal rather than from anything the caller wrote. The
contract layer already refuses ``actor``, ``role`` and ``principal`` as
prohibited request fields; this module is the other half - the only way a
router obtains a :class:`Principal` is by asking a
:class:`PrincipalResolver`, and the only implementations are one that fails
closed and one that is refused outside development.

**The unconfigured default refuses, and it refuses as unavailability.**
:class:`UnconfiguredAuthentication` raises ``AUTHENTICATION_NOT_CONFIGURED``,
which maps to 503. It does not invent a demo principal, and it does not answer
401 either: an operator who has not configured authentication has a server
that is not ready, not a caller who presented bad credentials. The status code
is the difference between a deployment defect that pages someone and a client
error that does not.

**Role sets are explicit, with no hierarchy.** ``ADMIN`` does not implicitly
satisfy an ``EXPERT_REVIEWER`` check. A hierarchy is convenient right until
someone adds a role in the middle of it, and then a gate that was written to
mean "only a reviewer" silently means "a reviewer or anyone above one". Every
route names the exact set it permits, in :mod:`apps.api.routes`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import FrozenSet, Iterable, Mapping, Optional

from apps.api.errors import (ForbiddenError, NotReadyError,
                             UnauthenticatedError)

__all__ = [
    "AccessPolicy",
    "AuthMode",
    "PUBLIC",
    "Principal",
    "PrincipalResolver",
    "Role",
    "StaticTokenAuthentication",
    "UnconfiguredAuthentication",
    "authorize",
    "roles",
]

#: An actor identifier is written to an append-only audit row and read back by
#: people. Bounded, printable, and free of anything that changes meaning when
#: pasted into a log viewer or a shell.
_ACTOR_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{1,63}$")

#: The mechanism that vouched for a principal, recorded so an audit row says
#: not only who acted but on what basis the server believed it.
_MECHANISM_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,30}/[0-9]{1,3}$")

#: Assurance levels, held as strings so this module does not import
#: ``pgx.security`` - the API layer must remain composable without it, and a
#: test asserts the two vocabularies are the same set.
_ASSURANCE_VALUES = frozenset({"NONE", "TEST_STATIC_TOKEN", "SESSION"})


class Role(str, Enum):
    """The governed roles. Adding one is an architecture change, not a config.

    Named exactly as architecture.md §13 names them, because these strings
    reach audit rows that outlive this code.
    """

    DEMO_USER = "DEMO_USER"
    EXPERT_REVIEWER = "EXPERT_REVIEWER"
    ADMIN = "ADMIN"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


class AuthMode(str, Enum):
    """How this deployment obtains principals.

    ``UNCONFIGURED`` is the default and the production-safe value. It is not a
    disabled-authentication mode: it is a mode in which every authenticated
    route reports that the server is not ready.

    ``SESSION`` arrived with WP-23 and is the only production-capable value.
    The mode decides *where the credential is read from*, and that is the
    point of having a mode at all: under ``SESSION`` the resolver reads the
    governed session cookie and nothing else; under ``STATIC_TOKEN`` it reads
    the bearer header and nothing else. Accepting both and using whichever
    works would mean a production deployment still honoured development
    tokens, which is precisely the configuration nobody would notice.
    """

    UNCONFIGURED = "UNCONFIGURED"
    STATIC_TOKEN = "STATIC_TOKEN"
    SESSION = "SESSION"

    @property
    def is_production_capable(self) -> bool:
        return self is AuthMode.SESSION

    @property
    def reads_bearer_token(self) -> bool:
        """Only the development mode reads an Authorization header."""
        return self is AuthMode.STATIC_TOKEN

    @property
    def reads_session_cookie(self) -> bool:
        return self is AuthMode.SESSION


@dataclass(frozen=True, slots=True)
class Principal:
    """The trusted answer to "who is making this request".

    Carries no display name, no email address and no group membership: none of
    those are needed to authorise a P0 route or to fill an audit row, and each
    would be one more piece of personal data travelling through a layer that
    has no reason to hold it.
    """

    actor: str
    role: Role
    authenticated_by: str
    #: How much the mechanism is worth, as a governed vocabulary value rather
    #: than a number. Only a validated server-side session may carry
    #: ``SESSION``; a development token carries ``TEST_STATIC_TOKEN`` forever.
    #: WP-22's review audit reads exactly this to decide whether
    #: ``actor_authenticated`` may be true, so a fixture cannot become a
    #: person by being renamed.
    assurance: str = "NONE"
    #: A stable, non-secret handle for the session this principal acted in.
    #: Never the cookie value and never its digest: a digest in an audit row
    #: would be a verifier for the cookie.
    session_reference: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.actor, str) or \
                _ACTOR_PATTERN.match(self.actor) is None:
            raise ValueError(
                "a principal's actor is a bounded printable identifier that "
                "can be written to an audit row unescaped")
        if not isinstance(self.role, Role):
            raise ValueError("a principal's role is a governed Role")
        if not isinstance(self.authenticated_by, str) or \
                _MECHANISM_PATTERN.match(self.authenticated_by) is None:
            raise ValueError(
                "a principal records the versioned mechanism that vouched "
                "for it, such as 'static-token/1'")
        if self.assurance not in _ASSURANCE_VALUES:
            raise ValueError(
                "a principal's assurance is one of " +
                ", ".join(sorted(_ASSURANCE_VALUES)))
        # The pairing that stops a fixture claiming to be a person. Checked
        # here as well as in the audit event, because this object is what the
        # audit context is built from and catching it later would mean the
        # wrong value already travelled through three layers.
        if self.assurance == "SESSION" and not self.session_reference:
            raise ValueError(
                "a session-assured principal names the session it acted in")

    @property
    def is_session_authenticated(self) -> bool:
        """Whether a validated server-side session established this actor."""
        return self.assurance == "SESSION"

    def audit_fields(self) -> Mapping[str, str]:
        """What an audit row records about the actor, and nothing more."""
        fields = {"actor": self.actor, "role": self.role.value,
                  "authenticated_by": self.authenticated_by,
                  "assurance": self.assurance}
        if self.session_reference is not None:
            fields["session_reference"] = self.session_reference
        return fields


@dataclass(frozen=True, slots=True)
class AccessPolicy:
    """Which principals a route accepts.

    Two shapes only: public, or an explicit non-empty role set. There is no
    third shape meaning "authenticated, any role", because a route that does
    not care which role reached it has not decided yet, and an undecided route
    is the one that turns out to have been reachable by a demo user.
    """

    public: bool
    permitted_roles: FrozenSet[Role]

    def __post_init__(self) -> None:
        if self.public and self.permitted_roles:
            raise ValueError("a public route names no roles")
        if not self.public and not self.permitted_roles:
            raise ValueError(
                "a non-public route names at least one permitted role")

    @property
    def role_names(self) -> tuple:
        """Permitted role names, sorted, safe to place in an error detail."""
        return tuple(sorted(role.value for role in self.permitted_roles))


def roles(*permitted: Role) -> AccessPolicy:
    """An access policy admitting exactly these roles."""
    return AccessPolicy(public=False, permitted_roles=frozenset(permitted))


#: Health and system-version are reachable without a principal. Both are
#: covered by §13's "health may be public" and "system version may be public";
#: neither reveals a case, an assessment or an actor.
PUBLIC = AccessPolicy(public=True, permitted_roles=frozenset())


def authorize(policy: AccessPolicy, principal: Optional[Principal],
              *, operation_id: str) -> Optional[Principal]:
    """Enforce one route's access policy.

    Returns the principal so the caller can use the return value rather than
    the argument it passed in, which makes "I checked" and "I used the checked
    one" the same line of code.

    Raises:
        UnauthenticatedError: the route requires a principal and none was
            resolved.
        ForbiddenError: a principal was resolved and its role is not permitted
            here. The error names the required roles, which is safe: the role
            names are a fixed governed vocabulary, not information about the
            caller or about any case.
    """
    if policy.public:
        return principal
    if principal is None:
        raise UnauthenticatedError("UNAUTHENTICATED")
    if principal.role not in policy.permitted_roles:
        raise ForbiddenError(
            "FORBIDDEN_ROLE",
            details={"required_role": list(policy.role_names)})
    del operation_id  # named for call-site readability; never placed in a body
    return principal


class PrincipalResolver:
    """Port: turn a presented credential into a trusted principal.

    The credential is opaque here on purpose. P0 does not know or care whether
    WP-23 will present a bearer token, a session cookie or a mutual-TLS
    subject; it cares that whatever arrives is interpreted in exactly one
    place, and that the place is replaceable.
    """

    mode: AuthMode = AuthMode.UNCONFIGURED

    def resolve(self, credential: Optional[str]
                ) -> Principal:  # pragma: no cover - protocol
        raise NotImplementedError


class UnconfiguredAuthentication(PrincipalResolver):
    """The default. Refuses every request for a principal.

    This is what a production deployment gets until WP-23 lands, and what a
    misconfigured one gets forever. It answers 503, not 401, and it never
    returns a principal - not a demo one, not an anonymous one, not an admin
    one for local convenience. A resolver that returns *something* when it has
    verified *nothing* is the single failure this class exists to make
    impossible.
    """

    mode = AuthMode.UNCONFIGURED

    def resolve(self, credential: Optional[str]) -> Principal:
        del credential  # never inspected: there is nothing here to check it against
        raise NotReadyError(
            "AUTHENTICATION_NOT_CONFIGURED",
            details={"components": ["authentication"]})


class StaticTokenAuthentication(PrincipalResolver):
    """A development-only resolver mapping fixed opaque tokens to principals.

    Exists so the framework-bound layer can be exercised end to end without
    WP-23, and so tests have something to override *with* rather than around.
    It is refused in production by :mod:`apps.api.config`, which is where that
    refusal belongs: a resolver cannot know which environment it was
    constructed in, and a check it performed on itself would be one an
    operator could satisfy by setting the wrong variable.

    Token comparison is constant-time. The tokens are not secrets worth
    protecting - they are fixtures - but a timing-variable comparison copied
    out of here into WP-23 would be.
    """

    mode = AuthMode.STATIC_TOKEN

    def __init__(self, tokens: Mapping[str, Principal]) -> None:
        if not tokens:
            raise ValueError(
                "a static-token resolver with no tokens would refuse every "
                "request while reporting that authentication is configured")
        for token, principal in tokens.items():
            if not isinstance(token, str) or len(token) < 16:
                raise ValueError(
                    "a static development token is at least 16 characters, so "
                    "that a fixture is never mistaken for a credential")
            if not isinstance(principal, Principal):
                raise ValueError("a static token maps to a Principal")
        self._tokens = dict(tokens)

    def resolve(self, credential: Optional[str]) -> Principal:
        if not credential:
            raise UnauthenticatedError("UNAUTHENTICATED")
        import hmac

        for token, principal in self._tokens.items():
            if hmac.compare_digest(token, credential):
                if principal.assurance == "SESSION":  # pragma: no cover
                    # Defensive. A fixture that claimed session assurance
                    # would let a development run write audit rows that look
                    # like a person acted.
                    raise ValueError(
                        "a static development token may not produce a "
                        "session-assured principal")
                return principal
        raise UnauthenticatedError("UNAUTHENTICATED")


def summarise_roles(permitted: Iterable[Role]) -> str:
    """A stable comma-separated role list, for documentation generation."""
    return ", ".join(sorted(role.value for role in permitted))
