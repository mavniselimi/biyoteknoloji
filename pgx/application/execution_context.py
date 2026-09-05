"""Who asked, over what channel, correlated by which request.

An assessment is a scientific calculation and an audited act. The calculation
is described entirely by :class:`~pgx.application.assessment_models.AssessmentInput`
and hashed into ``input_hash``. The act is described by this: the actor, the
role they held, the channel the request arrived on, and the correlation id
that ties an audit row to a log line and a client's bug report.

Keeping the two apart is the point.

- **Nothing here reaches a hash.** ``input_hash``, ``output_hash``,
  ``coverage_result_hash`` and every report hash cover the question and the
  answer. A request id mixed into any of them would make two runs of the same
  question look like different results, which would not make the system safer:
  it would make the determinism claim unfalsifiable.
- **Nothing here comes from a request body.** The API contract refuses
  ``actor``, ``role`` and ``principal`` as prohibited fields. This object is
  built from an authenticated principal on the server side, and the reason it
  is a separate type rather than three more keyword arguments is so that
  "where did this actor come from" has one answer with one place to check it.

It is transport-neutral on purpose. ``pgx.application`` must not import a web
framework, and a CLI, a scheduled job and a future queue consumer all need to
record who acted just as much as an HTTP request does. What arrives here is
already-verified data; how it was verified is somebody else's module.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, FrozenSet, Mapping, Optional

__all__ = [
    "ASSURANCE_LEVELS",
    "EXECUTION_CONTEXT_VERSION",
    "GOVERNED_ACTOR_ROLES",
    "ExecutionChannel",
    "ExecutionContext",
    "audit_context_fields",
]

EXECUTION_CONTEXT_VERSION = "pgx-execution-context/1"

#: The governed roles from architecture.md §13.
#:
#: Held here, in the layer that records them, rather than imported from the
#: transport that happens to produce them today. WP-23 will replace how a role
#: is established; it does not get to widen what an audit row may contain.
#: ``tests/unit/api/test_security_boundary.py`` asserts that the API's own
#: role enum is exactly this set, so the two cannot drift apart silently.
GOVERNED_ACTOR_ROLES: FrozenSet[str] = frozenset(
    {"DEMO_USER", "EXPERT_REVIEWER", "ADMIN"})

#: WP-23's assurance vocabulary, held here as strings for the same reason the
#: roles are: this layer records them and must not depend on the transport
#: that produces them. A test asserts the two spellings are one set.
ASSURANCE_LEVELS: FrozenSet[str] = frozenset(
    {"NONE", "TEST_STATIC_TOKEN", "SESSION"})

#: An actor identifier goes into an append-only row that people read. Bounded
#: and printable, with nothing that changes meaning when pasted into a log
#: viewer, a shell or a CSV.
_ACTOR_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{1,63}$")

#: Correlation ids are canonical lowercase UUIDs. The API generates one when a
#: caller sends none and refuses a malformed one, so anything reaching here is
#: already this shape; the check is what makes that a guarantee rather than a
#: convention.
_REQUEST_ID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

_MECHANISM_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,30}/[0-9]{1,3}$")


class ExecutionChannel(str, Enum):
    """How the request reached the application.

    Recorded because "an assessment was executed by ADMIN" reads differently
    depending on whether that happened through an authenticated API call or a
    shell on a production host, and an audit trail that cannot tell those
    apart cannot answer the question anyone actually asks of it.
    """

    API = "API"
    CLI = "CLI"
    INTERNAL = "INTERNAL"
    TEST = "TEST"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    """The audited circumstances of one call. Never part of any calculation."""

    actor: str
    role: str
    channel: ExecutionChannel
    request_id: Optional[str] = None
    authenticated_by: Optional[str] = None
    #: WP-23. How much the mechanism is worth, as a governed vocabulary value
    #: rather than a number. Only a validated server-side session may carry
    #: ``SESSION``; a static development token carries ``TEST_STATIC_TOKEN``
    #: forever, so a development run can never be mistaken for a person.
    assurance: str = "NONE"
    #: A stable, non-secret handle for the session. Never the cookie value and
    #: never its digest.
    session_reference: Optional[str] = None
    context_version: str = EXECUTION_CONTEXT_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.actor, str) or \
                _ACTOR_PATTERN.match(self.actor) is None:
            raise ValueError(
                "an execution context records a bounded printable actor "
                "identifier")
        if self.role not in GOVERNED_ACTOR_ROLES:
            raise ValueError(
                "an execution context records one of the governed roles: "
                + ", ".join(sorted(GOVERNED_ACTOR_ROLES)))
        if not isinstance(self.channel, ExecutionChannel):
            raise ValueError("an execution context names a known channel")
        if self.request_id is not None and (
                not isinstance(self.request_id, str)
                or _REQUEST_ID_PATTERN.match(self.request_id) is None):
            raise ValueError(
                "a correlation id is a canonical lowercase UUID, or absent")
        if self.authenticated_by is not None and (
                not isinstance(self.authenticated_by, str)
                or _MECHANISM_PATTERN.match(self.authenticated_by) is None):
            raise ValueError(
                "the authenticating mechanism is a versioned label such as "
                "'static-token/1', or absent")
        if self.assurance not in ASSURANCE_LEVELS:
            raise ValueError(
                "an execution context records one of the governed assurance "
                "levels: " + ", ".join(sorted(ASSURANCE_LEVELS)))
        # The pairing that keeps a fixture from becoming a person. A context
        # claiming session assurance with no session names nothing, and the
        # audit row built from it would assert that somebody was authenticated
        # without saying by what.
        if self.assurance == "SESSION" and not self.session_reference:
            raise ValueError(
                "a session-assured context names the session it acted in")

    def audit_metadata(self) -> Dict[str, Any]:
        """The fields an audit row records about the circumstances.

        Deliberately small and deliberately fixed. There is no free-form slot:
        a context that could carry arbitrary keys would eventually carry a
        medication list, because the place that builds it is the place that
        has one.
        """
        document: Dict[str, Any] = {
            "execution_context_version": self.context_version,
            "actor": self.actor,
            "role": self.role,
            "channel": self.channel.value,
        }
        if self.request_id is not None:
            document["request_id"] = self.request_id
        if self.authenticated_by is not None:
            document["authenticated_by"] = self.authenticated_by
        document["assurance"] = self.assurance
        if self.session_reference is not None:
            document["session_reference"] = self.session_reference
        return document

    @property
    def is_session_authenticated(self) -> bool:
        """Whether a validated server-side session established this actor.

        WP-22's review audit reads exactly this to decide whether
        ``actor_authenticated`` may be true.
        """
        return self.assurance == "SESSION"

    def with_request_id(self, request_id: Optional[str]) -> "ExecutionContext":
        """A copy correlated to a different request."""
        return ExecutionContext(
            actor=self.actor, role=self.role, channel=self.channel,
            request_id=request_id, authenticated_by=self.authenticated_by,
            assurance=self.assurance,
            session_reference=self.session_reference,
            context_version=self.context_version)


def audit_context_fields(context: Optional[ExecutionContext]
                         ) -> Mapping[str, Any]:
    """Audit fields for a context that may be absent.

    Absent is a real case: WP-14's CLI and every existing test execute without
    one, and those calls must keep working and keep auditing. An empty mapping
    is the honest answer - better than inventing ``actor="unknown"``, which
    would put a value into an audit row that nobody supplied.
    """
    return {} if context is None else context.audit_metadata()
