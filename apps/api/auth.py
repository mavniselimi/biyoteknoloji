# -*- coding: utf-8 -*-
"""The session-backed principal resolver (WP-23).

WP-16 declared :class:`~apps.api.security.PrincipalResolver` with two
implementations - one that refuses everything and one development fixture -
and a comment saying WP-23 would supply the real one. This is it.

**The credential's origin depends on the configured mode, and only on that.**
:class:`SessionAuthentication` reads the governed session cookie. It does not
also try the ``Authorization`` header, and it does not fall back to the static
resolver when the cookie is missing. A resolver that accepted both and used
whichever worked would mean a production deployment still honoured development
tokens - which is exactly the configuration that nobody notices until it is
used.

**Nothing here decides who anyone is.** The decision lives in
:class:`~pgx.security.service.AuthenticationService`, which validates the token
digest, the revocation state, both expiry bounds, the account status and the
auth generation. This class turns that answer into the immutable
:class:`~apps.api.security.Principal` the rest of the API already speaks, and
its whole contribution is that the value it converts came from a cookie the
server controls the interpretation of, never from a request body.
"""

from __future__ import annotations

from typing import Any, Optional

from apps.api.errors import NotReadyError, UnauthenticatedError
from apps.api.security import AuthMode, Principal, PrincipalResolver, Role

__all__ = ["SESSION_MECHANISM", "SessionAuthentication"]

#: The versioned mechanism label written to every audit row this resolver
#: produces. Versioned so that a future change to how sessions are validated
#: is visible in rows written before and after it.
SESSION_MECHANISM = "session/1"


class SessionAuthentication(PrincipalResolver):
    """Turn a validated server-side session into a principal.

    The service is injected rather than constructed, because composing one
    requires a database session that belongs to a request - and a resolver
    holding an application-scoped database session would share it across every
    concurrent request in the worker.
    """

    mode = AuthMode.SESSION

    def __init__(self, service: Optional[Any] = None) -> None:
        self._service = service

    @property
    def configured(self) -> bool:
        return self._service is not None

    def resolve(self, credential: Optional[str]) -> Principal:
        """A principal, or a typed refusal. Never a partial answer.

        Three outcomes, deliberately distinguished:

        * no service composed - 503, because the deployment is not ready
          rather than the caller being wrong;
        * no credential presented - 401;
        * a credential that does not validate - 401, identically to none.
          Presenting an expired session and presenting no session must look
          the same, or the difference measures which sessions once existed.
        """
        if self._service is None:
            raise NotReadyError(
                "AUTHENTICATION_NOT_CONFIGURED",
                details={"components": ["authentication"]})
        if not credential:
            raise UnauthenticatedError("UNAUTHENTICATED")
        from pgx.security.errors import SessionInvalid

        try:
            authenticated = self._service.authenticate(credential)
        except SessionInvalid:
            raise UnauthenticatedError("UNAUTHENTICATED") from None
        except Exception:  # noqa: BLE001 - a store that cannot answer is 503
            raise NotReadyError(
                "SESSION_STORE_UNAVAILABLE",
                details={"components": ["session_store"]}) from None
        return Principal(
            actor=authenticated.actor,
            role=Role(authenticated.role),
            authenticated_by=SESSION_MECHANISM,
            # The only place in the API layer that constructs SESSION
            # assurance, and it is reached only after the service validated a
            # stored digest for an ACTIVE user at the current generation.
            assurance="SESSION",
            session_reference=authenticated.session.session_reference())
