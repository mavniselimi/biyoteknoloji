"""What a page needs, injected, with a fail-closed default for each.

The same arrangement as the API's provider and for the same reasons: one
container, every field optional, and asking for something this deployment does
not have produces a typed refusal rather than ``None``.

Two web-specific capabilities join the API client. The **case catalogue** is a
callable so a test can supply cases without writing a file, and so a
deployment whose sealed artifact is missing gets a page that says so. The
**CSRF verifier** defaults to the one that refuses, which is what makes every
state-changing route unavailable until WP-23 supplies a real one.

There is no field here for a principal. Principals come from WP-16's
resolver, through the API's own security module, so the interface cannot
establish an identity the API would not.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Sequence, Tuple

from apps.web.client import PgxApiClient, UnavailableApiClient
from apps.web.config import WebSettings
from apps.web.security import CsrfVerifier, UnconfiguredCsrf

__all__ = ["WebProvider"]


@dataclass(frozen=True, slots=True)
class WebProvider:
    """Everything the interface may need, and none that it must have."""

    settings: WebSettings
    client: PgxApiClient = field(default_factory=UnavailableApiClient)
    #: The process-wide fallback. WP-17 kept a verifier here because the only
    #: one that existed held a single process-global token; WP-23's verifier
    #: is bound to one request's session, so the *factory* below is what a
    #: composed deployment supplies and this field is what an uncomposed one
    #: falls back to - a verifier that refuses everything.
    csrf: CsrfVerifier = field(default_factory=UnconfiguredCsrf)
    #: WP-23. ``(binding, secret) -> CsrfVerifier``, called per request with
    #: the current session's material. A factory rather than an instance
    #: because a verifier holding one session's key would either verify every
    #: request against that session or need mutable state shared across
    #: concurrent requests, and both are worse than no verifier at all.
    csrf_factory: Optional[Callable[[str, str], CsrfVerifier]] = None
    #: ``() -> AuthenticationService``. A factory for the same reason: the
    #: service holds a database session, and a session belongs to one request.
    authentication_service: Optional[Callable[[], Any]] = None
    case_catalog: Optional[Callable[[], Sequence[Any]]] = None
    principals: Optional[Any] = None
    #: WP-22's blind review service. ``None`` in this repository and in any
    #: deployment without a review store; the page then renders its
    #: controlled unavailable state and every form is inert.
    expert_review_service: Optional[Any] = None

    def expert_review(self, *, case_id: str, actor: str,
                      role: str) -> Tuple[Optional[Any], Optional[Any]]:
        """``(view, protocol)`` for this reviewer, or ``(None, protocol)``.

        Returns a pair rather than raising, and returns ``None`` for every
        refusal - no assignment, wrong case, unapproved protocol, absent
        service. The page must not distinguish them: a reviewer who could
        tell "no such case" from "not yours" would have an enumeration tool
        for the holdout set, and the difference would show up as different
        rendered bytes however carefully the template was written.
        """
        service = self.expert_review_service
        if service is None:
            return None, None
        protocol = getattr(service, "protocol", None)
        try:
            return service.view(case_id=case_id, actor=actor,
                                role=role), protocol
        except Exception:  # noqa: BLE001 - every refusal renders alike
            return None, protocol

    def cases(self) -> Tuple[Tuple[Any, ...], bool]:
        """The development cases, and whether a catalogue was readable.

        Returns the pair rather than raising, because an unreadable catalogue
        is a page that says the catalogue is unavailable - which is different
        from a catalogue that is present and empty, and the two must not look
        alike.
        """
        if self.case_catalog is None:
            return (), False
        try:
            return tuple(self.case_catalog()), True
        except Exception:  # noqa: BLE001 - reported as unavailable, not raised
            return (), False

    def case(self, case_id: str) -> Optional[Any]:
        """One case by identity, or ``None`` if the catalogue has no such id."""
        cases, available = self.cases()
        if not available:
            return None
        for entry in cases:
            if entry.case_id == case_id:
                return entry
        return None

    def csrf_for(self, session: Optional[Any]) -> CsrfVerifier:
        """The verifier for this request, bound to this request's session.

        Returns the refusing verifier when there is no session or no factory.
        That is the fail-closed default and it is what makes an unauthenticated
        page render its forms as unavailable rather than as controls that will
        be refused after the operator has filled them in.
        """
        if self.csrf_factory is None or session is None:
            return self.csrf
        binding = getattr(session, "session_id", None)
        secret = getattr(session, "csrf_secret", None)
        if not binding or not secret:
            return self.csrf
        return self.csrf_factory(binding, secret)

    def authenticate(self, raw_token: Optional[str]) -> Optional[Any]:
        """The authenticated session for this request, or ``None``.

        Returns ``None`` for every refusal - absent, expired, revoked,
        superseded, disabled account, or no service composed. The page must
        not distinguish them: a visitor who could tell "expired" from "never
        existed" could measure which sessions once did.
        """
        if self.authentication_service is None or not raw_token:
            return None
        try:
            return self.authentication_service().authenticate(raw_token)
        except Exception:  # noqa: BLE001 - every refusal renders alike
            return None

    @property
    def forms_available(self) -> bool:
        """Whether a state-changing form may be offered at all.

        Both dependencies, and both belong to somebody else: a principal must
        be establishable, and a CSRF verifier must exist. Either missing means
        the form is rendered disabled with the reason stated, rather than
        rendered live and failing after the operator has filled it in.
        """
        return bool(self.settings.state_changing_routes_available
                    and self.csrf.configured)
