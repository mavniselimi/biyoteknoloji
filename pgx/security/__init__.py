# -*- coding: utf-8 -*-
"""Authentication, RBAC, sessions, CSRF, rate limiting and secret scanning.

WP-23. This package supplies the mechanisms behind ports that WP-16 and WP-17
deliberately left empty: :class:`~apps.api.security.PrincipalResolver` and
:class:`~apps.web.security.CsrfVerifier` both had fail-closed defaults and a
comment naming this work package. Nothing here changes what those ports mean;
it fills them in.

Three properties hold across every module in this package.

**Implemented is not configured, and configured is not operational.** The code
below is complete. This repository has no PostgreSQL, no HTTPS termination, no
secrets and no users, so nothing here is *composed* in any real deployment and
the security gate stays BLOCKED. Every status document reports those as
separate fields rather than collapsing them into one boolean, because the
collapsed version reads as "security: done".

**There is no weaker path.** Password hashing is Argon2id or it is an error.
There is no PBKDF2 branch, no scrypt branch, no SHA fallback and no
development mode that skips hashing. If ``argon2-cffi`` is not installed,
composing authentication fails and readiness says so - which is the outcome
that keeps a deployment honest, rather than one that silently downgrades the
algorithm and reports itself healthy.

**Secrets do not travel.** No module here places a password, a raw session
token, a CSRF token or a cookie value into a return value, a repr, an
exception message, a log line, an audit event or an artifact. Several classes
override ``__repr__`` for that reason alone.
"""

from __future__ import annotations

__all__ = ["SECURITY_PACKAGE_VERSION"]

SECURITY_PACKAGE_VERSION = "pgx-wp23-security/1"
