# -*- coding: utf-8 -*-
"""Database configuration (WP-02).

Reading configuration never connects to anything. A missing or unusable URL is
reported as an explicit configuration error rather than a late connection
failure, and no secret is ever logged or included in an exception message.

PostgreSQL is the only supported backend. A ``sqlite://`` URL is rejected
outright: passing an integration test against SQLite would prove nothing about
the JSONB, TIMESTAMPTZ, deferred-constraint and check-constraint behaviour this
schema depends on.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
import re
from typing import Mapping, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

__all__ = [
    "APPLICATION_DATABASE_URL_ENV",
    "CREDENTIAL_PARAMETER_NAMES",
    "REDACTED",
    "REQUIRED_DRIVER_PREFIX",
    "TEST_DATABASE_URL_ENV",
    "DatabaseConfig",
    "DatabaseConfigurationError",
    "load_database_config",
    "normalize_driver",
    "redact_url",
    "sanitize_message",
]

APPLICATION_DATABASE_URL_ENV = "DATABASE_URL"
TEST_DATABASE_URL_ENV = "TEST_DATABASE_URL"

#: The one driver this project supports. psycopg 3 is a hard requirement: a
#: bare ``postgresql://`` URL makes SQLAlchemy fall back to psycopg2, which is
#: not a dependency here and behaves differently around JSONB adaptation and
#: connection handling. Rather than fail obscurely at connect time, a bare URL
#: is normalised to this prefix and the normalisation is recorded.
REQUIRED_DRIVER_PREFIX = "postgresql+psycopg://"

#: Accepted input spellings. ``postgresql://`` is accepted then normalised;
#: any other explicit driver is rejected.
_BARE_POSTGRES_PREFIX = "postgresql://"
_EXPLICIT_OTHER_DRIVERS = (
    "postgresql+psycopg2://", "postgresql+pg8000://", "postgresql+asyncpg://",
    "postgresql+pygresql://", "postgresql+psycopg2cffi://",
)

#: Rejected outright, with an explanation rather than a silent downgrade.
_REJECTED_PREFIXES = ("sqlite:", "mysql:", "mariadb:", "mssql:", "oracle:")

_DEFAULT_POOL_SIZE = 5
_DEFAULT_MAX_OVERFLOW = 5
_DEFAULT_POOL_TIMEOUT_SECONDS = 30
_DEFAULT_POOL_RECYCLE_SECONDS = 1800


class DatabaseConfigurationError(RuntimeError):
    """Raised when database configuration is absent or unusable.

    This is an infrastructure error, never a domain error: the domain has no
    opinion about connection strings.
    """


#: What a masked value is replaced with, everywhere.
REDACTED = "***"

#: Parameter names whose value is a credential, in a URL query string or in a
#: libpq/DSN ``key=value`` error message. Compared case-insensitively.
#:
#: A URI's userinfo password is only one of the places a secret travels.
#: psycopg accepts ``?sslpassword=`` in the URL and ``password=`` in a DSN, and
#: driver errors quote both back verbatim, so masking userinfo alone left the
#: real secret in the log line next to it.
CREDENTIAL_PARAMETER_NAMES = (
    "access_token", "api_key", "apikey", "auth_token", "authorization",
    "client_secret", "pass", "passfile", "password", "passwd", "pwd",
    "refresh_token", "secret", "session_token", "sslpassword", "token",
)

_CREDENTIAL_LOOKUP = frozenset(CREDENTIAL_PARAMETER_NAMES)

# Longest first, so ``sslpassword`` is never matched as ``password`` with a
# stray prefix left in front of it.
_CREDENTIAL_ALTERNATION = "|".join(
    re.escape(name) for name in
    sorted(CREDENTIAL_PARAMETER_NAMES, key=len, reverse=True))

#: libpq / DSN style: ``password=x``, ``password = x``, ``password='x'``,
#: ``password="x"``. The value runs to the next whitespace, comma or semicolon
#: when it is unquoted.
_DSN_CREDENTIAL = re.compile(
    r"(?i)\b(%s)(\s*=\s*)('[^']*'|\"[^\"]*\"|[^\s,;]*)" % _CREDENTIAL_ALTERNATION)

#: Any ``scheme://...`` token. Trailing sentence punctuation is trimmed back so
#: a URL at the end of a sentence is still parsed as a URL.
_URL_TOKEN = re.compile(r"\b[a-z][a-z0-9+.\-]*://[^\s'\"<>]+", re.IGNORECASE)

_URL_TRAILING_PUNCTUATION = ".,;:!?)]}"


def _is_credential_parameter(name: str) -> bool:
    """True when a query or DSN key names a credential. Case-insensitive."""
    return name.strip().lower() in _CREDENTIAL_LOOKUP


def _redact_query(query: str) -> str:
    """Mask credential-bearing query parameters, preserving order and shape."""
    if not query:
        return ""
    # An opaque segment carries no key to judge it by - it may be the secret
    # itself - so a query that is not entirely ``key=value`` shaped is withheld
    # whole rather than echoed on the assumption that it is harmless.
    if any("=" not in segment
           for segment in re.split(r"[&;]", query) if segment):
        return REDACTED
    try:
        pairs = parse_qsl(query, keep_blank_values=True)
    except ValueError:  # pragma: no cover - defensive
        return REDACTED
    if not pairs:
        return REDACTED
    # ``safe`` keeps the placeholder readable instead of percent-encoding it.
    return urlencode(
        [(key, REDACTED if _is_credential_parameter(key) else value)
         for key, value in pairs], safe="*")


def sanitize_message(message: str) -> str:
    """Strip anything credential-shaped from text before it is printed.

    Two distinct shapes carry secrets in driver output, and both are handled:

    * full URLs (``postgresql+psycopg://user:pw@host/db?sslpassword=...``),
      redacted through :func:`redact_url`;
    * libpq / DSN fragments (``password=secret``, ``sslpassword='secret'``),
      which are not URLs at all and were previously passed through untouched.

    Every occurrence is masked, not just the first. The function never raises:
    text that cannot be parsed is redacted rather than echoed, because failing
    open would print the secret this function exists to hide.
    """
    if not isinstance(message, str):
        try:
            message = str(message)
        except Exception:  # pragma: no cover - defensive
            return "<unprintable-message>"

    def _replace_url(match: "re.Match[str]") -> str:
        token = match.group(0)
        trailing = ""
        while token and token[-1] in _URL_TRAILING_PUNCTUATION:
            trailing = token[-1] + trailing
            token = token[:-1]
        return redact_url(token) + trailing

    try:
        redacted = _URL_TOKEN.sub(_replace_url, message)
        return _DSN_CREDENTIAL.sub(
            lambda match: "%s%s%s" % (match.group(1), match.group(2), REDACTED),
            redacted)
    except Exception:  # pragma: no cover - fail safe, never echo the input
        return "<message withheld: could not be sanitized>"


def redact_url(url: str) -> str:
    """Return ``url`` with every credential it carries replaced by ``***``.

    Masked: the userinfo password, credential-bearing query parameters (see
    :data:`CREDENTIAL_PARAMETER_NAMES`), and the fragment, which is dropped
    outright — nothing in a database URL needs one, and it is a convenient
    place for a secret to hide.

    Every log line and error message uses this. A raw URL with credentials must
    never reach stdout, a log file, or an exception. The function is fail-safe:
    anything it cannot parse comes back as a placeholder, never as the input.
    """
    if not isinstance(url, str) or "://" not in url:
        return "<invalid-url>"
    try:
        parts = urlsplit(url)
    except ValueError:
        return "<unparsable-url>"
    if not parts.scheme:
        return "<invalid-url>"

    try:
        host = parts.hostname or ""
        if ":" in host:  # IPv6 literal
            host = "[%s]" % host
        netloc = host
        try:
            port = parts.port
        except ValueError:
            port = None
        if port is not None:
            netloc = "%s:%d" % (netloc, port)
        if parts.username:
            userinfo = parts.username
            if parts.password is not None:
                userinfo = "%s:%s" % (userinfo, REDACTED)
            netloc = "%s@%s" % (userinfo, netloc)
        # The fragment is dropped, never carried into the safe form.
        return urlunsplit(
            (parts.scheme, netloc, parts.path, _redact_query(parts.query), ""))
    except Exception:  # pragma: no cover - fail safe
        return "<unparsable-url>"


def _read_int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise DatabaseConfigurationError(
            "%s must be an integer, got %r" % (name, raw)) from exc
    if value < 0:
        raise DatabaseConfigurationError("%s must not be negative, got %d" % (name, value))
    return value


def _read_bool(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = env.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class DatabaseConfig:
    """Validated connection settings.

    ``url`` holds the real connection string. Never print it directly; use
    :attr:`safe_url` or :func:`redact_url`.
    """

    url: str
    driver_was_normalized: bool = False
    pool_size: int = _DEFAULT_POOL_SIZE
    max_overflow: int = _DEFAULT_MAX_OVERFLOW
    pool_timeout_seconds: int = _DEFAULT_POOL_TIMEOUT_SECONDS
    pool_recycle_seconds: int = _DEFAULT_POOL_RECYCLE_SECONDS
    echo: bool = False
    source_env_var: str = APPLICATION_DATABASE_URL_ENV

    @property
    def safe_url(self) -> str:
        """Password-redacted URL, safe for logs and error messages."""
        return redact_url(self.url)

    @property
    def database_name(self) -> str:
        """Database name from the URL path, or an empty string."""
        return urlsplit(self.url).path.lstrip("/")

    def __repr__(self) -> str:
        # Overridden so an accidental repr() in a log never leaks a password.
        return "DatabaseConfig(url=%r, database=%r, pool_size=%d)" % (
            self.safe_url, self.database_name, self.pool_size)

    __str__ = __repr__


def normalize_driver(url: str) -> Tuple[str, bool]:
    """Return ``(url, was_normalised)`` with psycopg 3 as the driver.

    A bare ``postgresql://`` URL is rewritten to ``postgresql+psycopg://`` so it
    can never silently resolve to psycopg2. Any other explicitly named driver is
    rejected by the caller rather than rewritten: a URL that asks for asyncpg
    means the author expected different behaviour, and quietly changing it would
    hide that.
    """
    if url.lower().startswith(REQUIRED_DRIVER_PREFIX):
        return url, False
    if url.lower().startswith(_BARE_POSTGRES_PREFIX):
        return REQUIRED_DRIVER_PREFIX + url[len(_BARE_POSTGRES_PREFIX):], True
    return url, False


def _validate_url(url: Optional[str], env_var: str) -> Tuple[str, bool]:
    if url is None or not url.strip():
        raise DatabaseConfigurationError(
            "%s is not set. Set it to a PostgreSQL URL, for example "
            "postgresql+psycopg://USER:PASSWORD@HOST:5432/DBNAME "
            "(see .env.example)." % env_var)
    candidate = url.strip()
    lowered = candidate.lower()
    for rejected in _REJECTED_PREFIXES:
        if lowered.startswith(rejected):
            raise DatabaseConfigurationError(
                "%s points at %s, but PGx Platform V2 requires PostgreSQL. The "
                "schema depends on JSONB, TIMESTAMPTZ and deferrable constraints, "
                "so results from another engine would not be evidence of correct "
                "behaviour." % (env_var, rejected.rstrip(":")))
    for other in _EXPLICIT_OTHER_DRIVERS:
        if lowered.startswith(other):
            raise DatabaseConfigurationError(
                "%s names the driver %r, but this project requires psycopg 3 "
                "(%s). It is not rewritten automatically: an explicitly chosen "
                "driver signals an expectation this project does not meet."
                % (env_var, other.rstrip(":/"), REQUIRED_DRIVER_PREFIX.rstrip(":/")))

    if not lowered.startswith((REQUIRED_DRIVER_PREFIX, _BARE_POSTGRES_PREFIX)):
        raise DatabaseConfigurationError(
            "%s must start with %s (a bare %s is accepted and normalised), got %r"
            % (env_var, REQUIRED_DRIVER_PREFIX, _BARE_POSTGRES_PREFIX,
               redact_url(candidate)))

    normalised, was_normalised = normalize_driver(candidate)
    if not urlsplit(normalised).path.lstrip("/"):
        raise DatabaseConfigurationError(
            "%s does not name a database: %s" % (env_var, redact_url(normalised)))
    return normalised, was_normalised


def load_database_config(
    env: Optional[Mapping[str, str]] = None,
    *,
    use_test_database: bool = False,
) -> DatabaseConfig:
    """Build a validated :class:`DatabaseConfig` from the environment.

    Args:
        env: Environment mapping; defaults to ``os.environ``.
        use_test_database: Read ``TEST_DATABASE_URL`` instead of
            ``DATABASE_URL``. Integration tests always pass ``True`` so they
            can never operate on the application database.

    Raises:
        DatabaseConfigurationError: if the URL is missing, non-PostgreSQL, or
            malformed. The message never contains a password.
    """
    environment = os.environ if env is None else env
    env_var = TEST_DATABASE_URL_ENV if use_test_database else APPLICATION_DATABASE_URL_ENV
    url, was_normalised = _validate_url(environment.get(env_var), env_var)
    return DatabaseConfig(
        url=url,
        driver_was_normalized=was_normalised,
        pool_size=_read_int(environment, "PGX_DB_POOL_SIZE", _DEFAULT_POOL_SIZE),
        max_overflow=_read_int(environment, "PGX_DB_MAX_OVERFLOW", _DEFAULT_MAX_OVERFLOW),
        pool_timeout_seconds=_read_int(
            environment, "PGX_DB_POOL_TIMEOUT_SECONDS", _DEFAULT_POOL_TIMEOUT_SECONDS),
        pool_recycle_seconds=_read_int(
            environment, "PGX_DB_POOL_RECYCLE_SECONDS", _DEFAULT_POOL_RECYCLE_SECONDS),
        echo=_read_bool(environment, "PGX_DB_ECHO", False),
        source_env_var=env_var,
    )
