"""Settings, read from the environment, holding no connection and no secret.

Constructing :class:`ApiSettings` reads environment variables and nothing
else. It opens no socket, imports no driver, resolves no release and never
touches ``DATABASE_URL``'s contents. That is what makes ``import apps.api``
safe: a module that connected while being configured would make the import
graph depend on a running database, and every test of the layers above it
would need one.

The DSN is deliberately absent from this object. Readiness needs a database
connection, so it calls :func:`pgx.infrastructure.db.config.load_database_config`
at check time; settings record only *whether* the variable is set. A settings
object that carried the DSN would be a settings object that appears in a
repr, a log line and an exception - which is exactly how credentials leak.
Where a configuration message must name what went wrong, it goes through
:func:`pgx.infrastructure.db.config.sanitize_message` first, reusing the
redaction WP-02 already wrote rather than adding a second one that would drift.

**Production defaults fail closed.** In ``PRODUCTION`` the default is: no
authentication provider (so every authenticated route reports 503 and readiness
is blocking-failed), no interactive documentation, no CORS origin, and no
static development tokens - the last is refused outright rather than merely
defaulted off, because a development convenience that can be switched on by an
environment variable will eventually be switched on by an environment
variable.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Optional, Tuple

from apps.api.contracts.spec import LIMITS
from pgx.application.runtime_track import (DEFAULT_RUNTIME_TRACK,
                                           RUNTIME_TRACK_VARIABLE,
                                           RuntimeTrack, RuntimeTrackError,
                                           parse_runtime_track)
from apps.api.security import AuthMode

__all__ = [
    "ApiSettings",
    "ApiConfigurationError",
    "Environment",
    "load_settings",
]

_ENV_PREFIX = "PGX_API_"

#: An origin is a scheme and an authority, nothing else. A trailing path in an
#: allowed origin never matches anything a browser sends, so accepting one
#: would silently produce a CORS policy that does not do what it reads as.
_ORIGIN_PATTERN = re.compile(r"^https?://[A-Za-z0-9.\-]{1,253}(:[0-9]{1,5})?$")

_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"0", "false", "no", "off"})


class ApiConfigurationError(RuntimeError):
    """A deployment is misconfigured, described without quoting the value.

    The message names the variable and what was wrong with it. It does not
    include the value: the variables this reads include one whose value is a
    connection string, and an error class that sometimes quotes values is one
    that eventually quotes that one.
    """

    def __init__(self, variable: str, problem: str) -> None:
        from pgx.infrastructure.db.config import sanitize_message

        self.variable = variable
        super().__init__(sanitize_message("%s: %s" % (variable, problem)))


class Environment(str, Enum):
    """Which deployment this is. Only ``PRODUCTION`` changes any default."""

    PRODUCTION = "PRODUCTION"
    STAGING = "STAGING"
    DEVELOPMENT = "DEVELOPMENT"
    TEST = "TEST"

    @property
    def is_production(self) -> bool:
        return self is Environment.PRODUCTION


@dataclass(frozen=True, slots=True)
class ApiSettings:
    """Everything the application layer needs to be composed, and no secret."""

    environment: Environment = Environment.PRODUCTION
    auth_mode: AuthMode = AuthMode.UNCONFIGURED
    docs_enabled: bool = False
    cors_allowed_origins: Tuple[str, ...] = ()
    cors_allow_credentials: bool = False
    max_body_bytes: int = LIMITS["max_body_bytes"]
    readiness_timeout_seconds: float = 2.0
    database_url_configured: bool = False
    evidence_build_path: Optional[str] = None
    expected_migration_head: Optional[str] = None
    #: Wave 4B. Which release track this deployment serves. Read from
    #: ``PGX_RUNTIME_TRACK`` - not prefixed ``PGX_API_``, because the same
    #: choice governs the interface and any CLI composed from the same
    #: environment, and two variables that must agree eventually disagree.
    runtime_track: RuntimeTrack = DEFAULT_RUNTIME_TRACK
    #: Where the candidate release artifacts are read from. Only meaningful on
    #: the candidate track.
    candidate_repo_root: str = "."

    def __post_init__(self) -> None:
        if self.max_body_bytes < 1024 or self.max_body_bytes > 1_048_576:
            raise ApiConfigurationError(
                _ENV_PREFIX + "MAX_BODY_BYTES",
                "a request body limit between 1 KiB and 1 MiB; the assessment "
                "contract bounds every field, so a larger limit buys nothing "
                "and costs a memory-exhaustion surface")
        if self.readiness_timeout_seconds <= 0 or \
                self.readiness_timeout_seconds > 10:
            raise ApiConfigurationError(
                _ENV_PREFIX + "READINESS_TIMEOUT_SECONDS",
                "a readiness budget above zero and at most 10 seconds; a "
                "readiness probe that can hang is one an orchestrator cannot "
                "act on")
        if self.cors_allow_credentials and "*" in self.cors_allowed_origins:
            raise ApiConfigurationError(
                _ENV_PREFIX + "CORS_ALLOW_CREDENTIALS",
                "credentials are never sent to a wildcard origin")
        if self.environment.is_production:
            if self.auth_mode is AuthMode.STATIC_TOKEN:
                raise ApiConfigurationError(
                    _ENV_PREFIX + "AUTH_MODE",
                    "static development tokens are refused in production; "
                    "session authentication is the production-capable mode")
            if self.docs_enabled:
                raise ApiConfigurationError(
                    _ENV_PREFIX + "DOCS_ENABLED",
                    "interactive documentation is not served in production")
            if "*" in self.cors_allowed_origins:
                raise ApiConfigurationError(
                    _ENV_PREFIX + "CORS_ALLOWED_ORIGINS",
                    "a wildcard origin is refused in production")

    @property
    def cors_enabled(self) -> bool:
        """Whether any cross-origin policy is installed at all."""
        return bool(self.cors_allowed_origins)

    @property
    def authentication_configured(self) -> bool:
        """Whether a principal resolver other than the refusing one exists.

        Configured is not the same as production-capable, and the two are
        reported separately below. A deployment running with static
        development tokens has authentication *configured* and is not
        authenticating anybody.
        """
        return self.auth_mode is not AuthMode.UNCONFIGURED

    @property
    def production_authentication_available(self) -> bool:
        """Whether this deployment can authenticate a person.

        Only ``SESSION`` qualifies. This is the field WP-22's gate reads to
        decide whether ``EXPERT_REVIEW_NO_PRODUCTION_AUTHENTICATION`` still
        blocks, so it must never be true for a fixture.
        """
        return self.auth_mode.is_production_capable

    def public_summary(self) -> Mapping[str, object]:
        """A description safe to log at start-up and to place in a document.

        Booleans and governed enum values only. Nothing here is derived from a
        value that could contain a credential.
        """
        return {
            "environment": self.environment.value,
            "auth_mode": self.auth_mode.value,
            "authentication_configured": self.authentication_configured,
            "production_authentication_available":
                self.production_authentication_available,
            "docs_enabled": self.docs_enabled,
            "cors_enabled": self.cors_enabled,
            "cors_origin_count": len(self.cors_allowed_origins),
            "cors_allow_credentials": self.cors_allow_credentials,
            "max_body_bytes": self.max_body_bytes,
            "readiness_timeout_seconds": self.readiness_timeout_seconds,
            "database_url_configured": self.database_url_configured,
            "evidence_build_configured": self.evidence_build_path is not None,
            "migration_head_pinned": self.expected_migration_head is not None,
        }


def _flag(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = env.get(_ENV_PREFIX + name)
    if raw is None or raw == "":
        return default
    lowered = raw.strip().lower()
    if lowered in _TRUE:
        return True
    if lowered in _FALSE:
        return False
    raise ApiConfigurationError(_ENV_PREFIX + name,
                                "a boolean such as true or false")


def _integer(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(_ENV_PREFIX + name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw.strip())
    except ValueError:
        raise ApiConfigurationError(_ENV_PREFIX + name,
                                    "a whole number") from None


def _decimal(env: Mapping[str, str], name: str, default: float) -> float:
    raw = env.get(_ENV_PREFIX + name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw.strip())
    except ValueError:
        raise ApiConfigurationError(_ENV_PREFIX + name,
                                    "a number of seconds") from None


def _origins(env: Mapping[str, str]) -> Tuple[str, ...]:
    raw = env.get(_ENV_PREFIX + "CORS_ALLOWED_ORIGINS")
    if raw is None or not raw.strip():
        return ()
    parts = tuple(part.strip() for part in raw.split(",") if part.strip())
    for part in parts:
        if part == "*":
            continue
        if _ORIGIN_PATTERN.match(part) is None:
            raise ApiConfigurationError(
                _ENV_PREFIX + "CORS_ALLOWED_ORIGINS",
                "a comma-separated list of origins, each a scheme, then a\n"
                "host, then an optional port - and no path")
    if len(parts) > 16:
        raise ApiConfigurationError(
            _ENV_PREFIX + "CORS_ALLOWED_ORIGINS",
            "at most 16 origins; a longer list is a policy nobody reviews")
    return parts


def _bounded_path(env: Mapping[str, str], name: str) -> Optional[str]:
    raw = env.get(_ENV_PREFIX + name)
    if raw is None or not raw.strip():
        return None
    value = raw.strip()
    if len(value) > 512 or "\x00" in value:
        raise ApiConfigurationError(_ENV_PREFIX + name,
                                    "a bounded filesystem path")
    return value


def _runtime_track(source: Mapping[str, str]) -> RuntimeTrack:
    """The release track, refusing anything it does not recognise.

    Wrapped here so an unusable value becomes the same ``ApiConfigurationError``
    every other bad variable produces, and so the message never quotes the
    value - a configuration error that echoes its input is a log line that
    eventually echoes a secret.
    """
    try:
        return parse_runtime_track(source.get(RUNTIME_TRACK_VARIABLE))
    except RuntimeTrackError:
        raise ApiConfigurationError(
            RUNTIME_TRACK_VARIABLE,
            "one of " + ", ".join(item.value for item in RuntimeTrack)
            + "; an unrecognised track is refused rather than resolved to a "
              "default, because the default is the approved track and the "
              "other one must be asked for") from None


def load_settings(env: Optional[Mapping[str, str]] = None) -> ApiSettings:
    """Build settings from an environment mapping.

    Args:
        env: the mapping to read. Defaults to ``os.environ``. Taking it as an
            argument is what lets every configuration test run without
            mutating process state, and what lets the factory be handed a
            settings object in a test without any environment at all.

    Raises:
        ApiConfigurationError: a variable is present and unusable, or a
            production deployment asks for something production refuses. The
            message never quotes the offending value.
    """
    source: Mapping[str, str] = os.environ if env is None else env

    raw_environment = (source.get(_ENV_PREFIX + "ENV")
                       or Environment.PRODUCTION.value).strip().upper()
    try:
        environment = Environment(raw_environment)
    except ValueError:
        raise ApiConfigurationError(
            _ENV_PREFIX + "ENV",
            "one of " + ", ".join(item.value for item in Environment)) from None

    raw_auth = (source.get(_ENV_PREFIX + "AUTH_MODE")
                or AuthMode.UNCONFIGURED.value).strip().upper()
    try:
        auth_mode = AuthMode(raw_auth)
    except ValueError:
        raise ApiConfigurationError(
            _ENV_PREFIX + "AUTH_MODE",
            "one of " + ", ".join(item.value for item in AuthMode)) from None

    return ApiSettings(
        environment=environment,
        auth_mode=auth_mode,
        docs_enabled=_flag(source, "DOCS_ENABLED",
                           not environment.is_production),
        cors_allowed_origins=_origins(source),
        cors_allow_credentials=_flag(source, "CORS_ALLOW_CREDENTIALS", False),
        max_body_bytes=_integer(source, "MAX_BODY_BYTES",
                                LIMITS["max_body_bytes"]),
        readiness_timeout_seconds=_decimal(source, "READINESS_TIMEOUT_SECONDS",
                                           2.0),
        # Production deployments use the file form so the DSN never appears
        # in ``docker inspect``.  Readiness only needs to know that a source
        # was configured; the deployment composition is responsible for
        # opening and validating the file without exposing its contents.
        database_url_configured=bool(
            (source.get("DATABASE_URL") or "").strip()
            or (source.get("DATABASE_URL_FILE") or "").strip()),
        evidence_build_path=_bounded_path(source, "EVIDENCE_BUILD_PATH"),
        expected_migration_head=(
            (source.get(_ENV_PREFIX + "MIGRATION_HEAD") or "").strip() or None),
        runtime_track=_runtime_track(source),
        candidate_repo_root=(
            (source.get("PGX_CANDIDATE_REPO_ROOT") or "").strip() or "."),
    )
