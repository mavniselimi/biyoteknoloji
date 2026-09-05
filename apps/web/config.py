"""Web settings. Reads the environment, connects to nothing.

Layered on :class:`apps.api.config.ApiSettings` rather than replacing it: the
web application runs beside the API in one image, so the environment, the body
limit and the authentication mode are one decision, not two that can disagree.
What is added here is presentation and the two protections the API does not
need - a CSRF verifier and a redirect allowlist.

**Production defaults refuse.** State-changing web routes are unavailable
until a CSRF verifier exists, and no environment variable turns that off. That
is not caution for its own sake: a form that posts without CSRF verification
in a deployment that has just gained cookie sessions is a cross-site request
away from acting as whoever is logged in, and the deployment that gains
sessions is WP-23's, not this one's.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Mapping, Optional, Tuple

from apps.api.config import ApiConfigurationError, ApiSettings, Environment, \
    load_settings as load_api_settings
from apps.web import DEFAULT_LOCALE, SUPPORTED_LOCALES

__all__ = [
    "WebSettings",
    "load_web_settings",
]

_ENV_PREFIX = "PGX_WEB_"

_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"0", "false", "no", "off"})

#: An internal redirect target: an absolute path, no scheme, no authority, no
#: backslash, no protocol-relative form. Checked here as well as in
#: :func:`apps.web.security.safe_redirect` because a pattern in one place is a
#: pattern somebody edits without seeing the other.
_INTERNAL_PATH = re.compile(r"^/(?!/)[A-Za-z0-9._~!$&'()*+,;=:@/-]{0,255}$")


@dataclass(frozen=True, slots=True)
class WebSettings:
    """Everything the interface needs, and no secret."""

    api: ApiSettings
    locale: str = DEFAULT_LOCALE
    csrf_configured: bool = False
    static_asset_version: str = "1"
    max_form_bytes: int = 16 * 1024
    max_selected_medications: int = 32
    show_dependency_banner: bool = True

    def __post_init__(self) -> None:
        if self.locale not in SUPPORTED_LOCALES:
            raise ApiConfigurationError(
                _ENV_PREFIX + "LOCALE",
                "one of " + ", ".join(SUPPORTED_LOCALES))
        if self.max_form_bytes < 512 or self.max_form_bytes > 65536:
            raise ApiConfigurationError(
                _ENV_PREFIX + "MAX_FORM_BYTES",
                "a form limit between 512 bytes and 64 KiB; every field this "
                "interface submits is bounded, so a larger limit buys nothing")
        if not re.match(r"^[A-Za-z0-9._-]{1,32}$", self.static_asset_version):
            raise ApiConfigurationError(
                _ENV_PREFIX + "ASSET_VERSION",
                "a short alphanumeric version tag")
        # WP-17 refused ``csrf_configured`` in production outright, because
        # the only verifier that existed was a fixture holding one
        # process-global token - and a deployment declaring that configured
        # would have been declaring a defence it did not have. WP-23 supplies
        # a session-bound verifier, so the refusal moves to what is actually
        # unsafe: declaring CSRF configured without session authentication.
        # A CSRF token has to be bound to something, and without a session
        # there is nothing to bind it to.
        if self.csrf_configured and not self.api.authentication_configured:
            raise ApiConfigurationError(
                _ENV_PREFIX + "CSRF_CONFIGURED",
                "CSRF protection is bound to a session, so it cannot be "
                "declared configured while no authentication provider is; "
                "there would be nothing to bind a token to")
        if self.csrf_configured and self.api.environment.is_production and \
                not self.api.production_authentication_available:
            raise ApiConfigurationError(
                _ENV_PREFIX + "CSRF_CONFIGURED",
                "in production a CSRF token is bound to a real session; "
                "static development tokens cannot carry one")

    @property
    def environment(self) -> Environment:
        return self.api.environment

    @property
    def state_changing_routes_available(self) -> bool:
        """Whether a form on this deployment may actually be submitted.

        Both conditions, and both are somebody else's to satisfy: a principal
        must be establishable, and a CSRF verifier must exist. Either missing
        means the form renders as unavailable rather than as a control that
        will fail after the user fills it in.
        """
        return bool(self.api.authentication_configured and
                    self.csrf_configured)

    @property
    def production_forms_available(self) -> bool:
        """Whether a form on this deployment may be submitted *by a person*.

        Reported separately from :attr:`state_changing_routes_available`
        because a development deployment running on static tokens can submit
        forms and is not authenticating anybody. WP-22's page reads this to
        decide whether a review control may be enabled at all.
        """
        return bool(self.api.production_authentication_available and
                    self.csrf_configured)

    def public_summary(self) -> Mapping[str, object]:
        """Safe to log at start-up and to place in a document."""
        return {
            "environment": self.environment.value,
            "locale": self.locale,
            "csrf_configured": self.csrf_configured,
            "authentication_configured": self.api.authentication_configured,
            "production_authentication_available":
                self.api.production_authentication_available,
            "state_changing_routes_available":
                self.state_changing_routes_available,
            "production_forms_available": self.production_forms_available,
            "static_asset_version": self.static_asset_version,
            "max_form_bytes": self.max_form_bytes,
            "max_selected_medications": self.max_selected_medications,
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


def load_web_settings(env: Optional[Mapping[str, str]] = None,
                      api: Optional[ApiSettings] = None) -> WebSettings:
    """Build web settings from an environment mapping.

    Args:
        env: the mapping to read. Defaults to ``os.environ``; taken as an
            argument so configuration tests mutate no process state.
        api: pre-built API settings, when the caller already has them. The
            combined application builds them once and passes them here, so the
            two halves cannot end up describing different environments.
    """
    source: Mapping[str, str] = os.environ if env is None else env
    api_settings = api if api is not None else load_api_settings(source)

    locale = (source.get(_ENV_PREFIX + "LOCALE")
              or DEFAULT_LOCALE).strip().lower()

    return WebSettings(
        api=api_settings,
        locale=locale,
        # Never read from the environment. There is no CSRF verifier to
        # configure, and a variable that could claim otherwise would be a
        # variable somebody sets.
        csrf_configured=False,
        static_asset_version=(source.get(_ENV_PREFIX + "ASSET_VERSION")
                              or "1").strip(),
        max_form_bytes=_integer(source, "MAX_FORM_BYTES", 16 * 1024),
        max_selected_medications=_integer(source, "MAX_MEDICATIONS", 32),
        show_dependency_banner=_flag(source, "DEPENDENCY_BANNER", True),
    )
