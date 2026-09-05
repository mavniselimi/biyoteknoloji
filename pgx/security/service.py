# -*- coding: utf-8 -*-
"""The authentication service: login, session validation, logout (WP-23).

Everything the login path must do, in the order it must do it, in one place.
The order is the security content and is worth reading as a list:

1. **Rate limit first**, on the username digest and the origin digest, before
   the user is looked up. A limit applied after the lookup would be a limit an
   attacker measures the timing of.
2. **Look the user up, and pay the hashing cost either way.** An unknown
   username runs :meth:`~pgx.security.passwords.PasswordHasher.dummy_verify`,
   so the endpoint costs the same whether the account exists or not.
3. **Verify the password**, constant-time, through Argon2id.
4. **Check status**, and treat disabled and locked exactly like a wrong
   password from the outside.
5. **Rotate**: revoke every existing session for this user, then create a new
   one with new material. A login that reused the presented session id would
   be a session-fixation hole.
6. **Audit inside the same transaction**, so a login whose audit row fails
   does not produce a usable session.

Steps 2, 3 and 4 all end in the same :class:`AuthenticationFailed` with the
same code and empty details. The *service* knows which one happened and puts
it in the audit row on the server; the caller never learns.
"""

from __future__ import annotations

import datetime as _dt
import secrets
from typing import Any, Callable, Optional, Sequence, Tuple

from pgx.infrastructure.audit.service import AuditContext, GovernedAuditService
from pgx.infrastructure.audit.vocabulary import AuditOutcome, GovernedAction
from pgx.security.csrf import new_csrf_secret
from pgx.security.errors import (AuthenticationFailed, PasswordPolicyError,
                                 SessionInvalid, UserAdministrationError)
from pgx.security.passwords import Password, PasswordHasher
from pgx.security.rate_limit import RateLimiter
from pgx.security.sessions import (SessionPolicy, SessionRecord,
                                   build_session, matches_token,
                                   new_session_token, token_digest)
from pgx.security.users import UserRecord, canonical_username
from pgx.security.vocabulary import (AuthAssurance, AuthMechanism,
                                     SessionRevocationReason, UserStatus)

__all__ = [
    "AuthenticatedSession",
    "AuthenticationService",
    "LoginOutcome",
    "SessionStore",
    "UserStore",
]


class UserStore:
    """Port: read and replace user records. No delete."""

    def by_username(self, username: str
                    ) -> Optional[UserRecord]:  # pragma: no cover - protocol
        raise NotImplementedError

    def by_id(self, user_id: str
              ) -> Optional[UserRecord]:  # pragma: no cover - protocol
        raise NotImplementedError

    def save(self, user: UserRecord
             ) -> UserRecord:  # pragma: no cover - protocol
        raise NotImplementedError

    def count(self) -> int:  # pragma: no cover - protocol
        raise NotImplementedError


class SessionStore:
    """Port: create, read, replace and revoke sessions. No delete."""

    def by_token_digest(self, digest: str
                        ) -> Optional[SessionRecord]:  # pragma: no cover
        raise NotImplementedError

    def save(self, session: SessionRecord
             ) -> SessionRecord:  # pragma: no cover - protocol
        raise NotImplementedError

    def revoke_all_for_user(self, user_id: str, *, now: _dt.datetime,
                            reason: SessionRevocationReason
                            ) -> int:  # pragma: no cover - protocol
        raise NotImplementedError


class AuthenticatedSession:
    """A validated session and the user it belongs to, for one request."""

    __slots__ = ("user", "session")

    def __init__(self, user: UserRecord, session: SessionRecord) -> None:
        self.user = user
        self.session = session

    @property
    def actor(self) -> str:
        return self.user.username

    @property
    def role(self) -> str:
        return self.user.role

    def audit_context(self, request_id: Optional[str] = None
                      ) -> AuditContext:
        """The only place a SESSION assurance is constructed.

        Reached exactly when a server-side session validated against a stored
        digest for an ACTIVE user at the current generation. Nothing else in
        this codebase builds an ``AuthContext`` with
        :data:`AuthAssurance.SESSION`.
        """
        return AuditContext(
            actor_id=self.user.username, actor_role=self.user.role,
            auth_mechanism=AuthMechanism.SESSION,
            auth_assurance=AuthAssurance.SESSION,
            session_reference=self.session.session_reference(),
            request_id=request_id)

    def __repr__(self) -> str:  # pragma: no cover - fixed on purpose
        return ("<AuthenticatedSession actor=%s role=%s>"
                % (self.actor, self.role))


class LoginOutcome:
    """The result of a login, plus the raw token the caller must set once.

    The token is here and nowhere else. It is not on the session record, not
    in the store, not in the audit row and not in any log line - this object
    carries it from the service to the ``Set-Cookie`` header and is then
    discarded.
    """

    __slots__ = ("session", "user", "raw_token", "csrf_token")

    def __init__(self, *, session: SessionRecord, user: UserRecord,
                 raw_token: str, csrf_token: str) -> None:
        self.session = session
        self.user = user
        self.raw_token = raw_token
        self.csrf_token = csrf_token

    def __repr__(self) -> str:
        """Never prints the token. A dataclass repr would."""
        return "<LoginOutcome actor=%s session=%s>" % (
            self.user.username, self.session.session_id)


class AuthenticationService:
    """Login, session validation and logout, with every dependency injected."""

    def __init__(self, *, users: UserStore, sessions: SessionStore,
                 hasher: PasswordHasher,
                 audit: GovernedAuditService,
                 policy: Optional[SessionPolicy] = None,
                 limiter: Optional[RateLimiter] = None,
                 clock: Optional[Callable[[], _dt.datetime]] = None,
                 id_factory: Optional[Callable[[str], str]] = None,
                 token_factory: Optional[Callable[[], str]] = None) -> None:
        self._users = users
        self._sessions = sessions
        self._hasher = hasher
        self._audit = audit
        self._policy = policy or SessionPolicy()
        self._limiter = limiter
        self._clock = clock or (lambda: _dt.datetime.now(_dt.timezone.utc))
        self._id_factory = id_factory or _uuid_id
        self._token_factory = token_factory or new_session_token

    @property
    def policy(self) -> SessionPolicy:
        return self._policy

    # -- login -----------------------------------------------------------

    def login(self, username: str, password: Password, *,
              origin_key: str = "unknown",
              request_id: Optional[str] = None) -> LoginOutcome:
        """Authenticate and issue a session, or raise the one failure."""
        now = self._clock()
        # 1. Limits, before the lookup. Both raise RateLimited, which the
        #    transport maps to 429 - a different answer from a failed login,
        #    and deliberately so: a client that is being throttled needs to
        #    know to stop, and the throttle reveals nothing about the account.
        if self._limiter is not None:
            self._limiter.check("LOGIN_PER_USERNAME", str(username).lower())
            self._limiter.check("LOGIN_PER_ORIGIN", origin_key)

        try:
            canonical = canonical_username(username)
        except UserAdministrationError:
            # A malformed username is not a different answer from a wrong one.
            # Pay the cost and refuse identically, so the username *format*
            # cannot be probed either.
            self._hasher.dummy_verify()
            self._record_login_failure(canonical=None, reason="MALFORMED",
                                       now=now, request_id=request_id)
            raise AuthenticationFailed() from None

        user = self._users.by_username(canonical)
        if user is None:
            # 2. The dummy verification. Without it, an unknown username
            #    returns in microseconds while a known one pays 64 MiB and
            #    three passes, and the difference is measurable from outside.
            self._hasher.dummy_verify()
            self._record_login_failure(canonical=canonical,
                                       reason="NO_SUCH_USER", now=now,
                                       request_id=request_id)
            raise AuthenticationFailed()

        # 3. Verify first, then check status. Deliberately this order: a
        #    disabled account that returned before verifying would answer
        #    faster than an active one, which is a status oracle.
        verified = self._hasher.verify(user.password_hash, password)
        permitted = user.may_authenticate_at(now)

        if not verified or not permitted:
            reason = ("WRONG_PASSWORD" if permitted else
                      ("DISABLED" if user.status is UserStatus.DISABLED
                       else "LOCKED"))
            if not verified:
                self._users.save(user.with_failed_login(now))
            self._record_login_failure(canonical=canonical, reason=reason,
                                       now=now, request_id=request_id,
                                       user_id=user.user_id)
            raise AuthenticationFailed()

        # 4. Replace an obsolete hash, after a successful verification and
        #    only then. Rehashing on failure would let an attacker drive the
        #    work; rehashing before verification would rehash a wrong
        #    password into the account.
        rehashed = False
        if self._hasher.needs_rehash(user.password_hash):
            try:
                user = user.with_password(self._hasher.hash(password), now)
                rehashed = True
            except PasswordPolicyError:  # pragma: no cover - defensive
                rehashed = False

        # 5. Rotate. Every existing session for this user goes first, so a
        #    fixated session cannot survive the login that was supposed to
        #    replace it.
        self._sessions.revoke_all_for_user(
            user.user_id, now=now,
            reason=SessionRevocationReason.ROTATED_ON_LOGIN)
        user = self._users.save(user.with_successful_login(now))

        token = self._token_factory()
        session = build_session(
            session_id=self._id_factory("SES"), user_id=user.user_id,
            role=user.role, token=token, csrf_secret=new_csrf_secret(),
            auth_generation=user.auth_generation, now=now,
            policy=self._policy)
        session = self._sessions.save(session)

        context = AuditContext(
            actor_id=user.username, actor_role=user.role,
            auth_mechanism=AuthMechanism.SESSION,
            auth_assurance=AuthAssurance.SESSION,
            session_reference=session.session_reference(),
            request_id=request_id)
        # 6. Both events inside the caller's transaction. If either fails the
        #    whole login rolls back and no cookie is set.
        self._audit.record(
            GovernedAction.LOGIN_SUCCEEDED, outcome=AuditOutcome.SUCCESS,
            result_code="LOGIN_SUCCEEDED", object_type="USER",
            object_id=user.user_id, context=context,
            metadata={"rehashed": rehashed})
        self._audit.record(
            GovernedAction.SESSION_CREATED, outcome=AuditOutcome.SUCCESS,
            result_code="SESSION_CREATED", object_type="SESSION",
            object_id=session.session_id, context=context,
            metadata={"session_reference": session.session_reference()})

        from pgx.security.csrf import SessionBoundCsrf
        csrf_token = SessionBoundCsrf().issue(
            binding=session.session_id, secret=session.csrf_secret, now=now)
        return LoginOutcome(session=session, user=user, raw_token=token,
                            csrf_token=csrf_token)

    def _record_login_failure(self, *, canonical: Optional[str], reason: str,
                              now: _dt.datetime,
                              request_id: Optional[str] = None,
                              user_id: Optional[str] = None) -> None:
        """Record the failure server-side, with the reason the caller never
        sees. Best-effort: an audit outage must not turn a refused login into
        a 500, which would itself be a signal."""
        del now
        self._audit.record_refusal(
            GovernedAction.LOGIN_FAILED, result_code="AUTHENTICATION_FAILED",
            object_type="USER", object_id=user_id or "unknown",
            context=AuditContext(actor_id=None, actor_role=None,
                                 request_id=request_id),
            metadata={"refusal_detail_code": reason})

    # -- session validation ----------------------------------------------

    def authenticate(self, raw_token: Optional[str], *,
                     request_id: Optional[str] = None
                     ) -> AuthenticatedSession:
        """Validate a presented cookie value into an authenticated session.

        Every check runs on every request. A session is not a fact established
        once at login: the user may have been disabled, re-roled or had their
        password changed a second after it was issued, and each of those must
        take effect on the next request rather than at the next expiry.
        """
        del request_id
        if not raw_token:
            raise SessionInvalid("no session was presented",
                                 code="SESSION_INVALID")
        now = self._clock()
        session = self._sessions.by_token_digest(token_digest(raw_token))
        if session is None or not matches_token(session, raw_token):
            raise SessionInvalid("no such session", code="SESSION_INVALID")
        if session.is_revoked:
            raise SessionInvalid("the session was revoked",
                                 code="SESSION_INVALID")
        if session.is_expired_at(now):
            reason = session.expiry_reason_at(now) or \
                SessionRevocationReason.IDLE_EXPIRED
            self._sessions.save(session.revoked(now, reason))
            self._audit.record_refusal(
                GovernedAction.SESSION_EXPIRED, result_code=reason.value,
                object_type="SESSION", object_id=session.session_id,
                outcome=AuditOutcome.REFUSED,
                metadata={"revocation_reason": reason.value})
            raise SessionInvalid("the session expired",
                                 code="SESSION_INVALID")

        user = self._users.by_id(session.user_id)
        if user is None or user.status is not UserStatus.ACTIVE:
            self._sessions.save(session.revoked(
                now, SessionRevocationReason.USER_DISABLED))
            raise SessionInvalid("the account is not active",
                                 code="SESSION_INVALID")
        # The generation check. One integer, and it is what makes a password
        # change, a role change, a disable and a lock all revoke every session
        # in a single write rather than a sweep that can be interrupted.
        if session.auth_generation != user.auth_generation:
            self._sessions.save(session.revoked(
                now, SessionRevocationReason.GENERATION_SUPERSEDED))
            raise SessionInvalid("the session was superseded",
                                 code="SESSION_INVALID")

        session = self._sessions.save(session.touched(now, self._policy))
        return AuthenticatedSession(user=user, session=session)

    # -- logout ------------------------------------------------------------

    def logout(self, raw_token: Optional[str], *,
               request_id: Optional[str] = None) -> bool:
        """Revoke server-side, then let the caller clear the cookie.

        Order matters and is the whole point: clearing the cookie first would
        leave a live session on the server that the user believes is closed,
        and anyone holding a copy of the token could keep using it.
        """
        if not raw_token:
            return False
        now = self._clock()
        session = self._sessions.by_token_digest(token_digest(raw_token))
        if session is None or not matches_token(session, raw_token):
            return False
        if not session.is_revoked:
            self._sessions.save(
                session.revoked(now, SessionRevocationReason.LOGOUT))
        user = self._users.by_id(session.user_id)
        self._audit.record_refusal(
            GovernedAction.LOGOUT, result_code="LOGOUT",
            outcome=AuditOutcome.SUCCESS, object_type="SESSION",
            object_id=session.session_id,
            context=AuditContext(
                actor_id=(user.username if user else None),
                actor_role=(user.role if user else None),
                auth_mechanism=AuthMechanism.SESSION,
                auth_assurance=AuthAssurance.SESSION,
                session_reference=session.session_reference(),
                request_id=request_id),
            metadata={"revocation_reason":
                      SessionRevocationReason.LOGOUT.value})
        return True


def _uuid_id(prefix: str = "SES") -> str:
    import uuid
    return "%s-%s" % (prefix, uuid.uuid4().hex)
