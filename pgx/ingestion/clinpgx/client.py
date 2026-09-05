# -*- coding: utf-8 -*-
"""ClinPGx transport configuration (WP-04).

Standard library only. This module builds a transport that may talk to ClinPGx
and nothing else; it performs no request itself, and importing it opens nothing.

The token is read from the environment at construction and handed to the
transport, which attaches it at send time. It is never placed on a request, so
it cannot reach a request key, a cache entry, a manifest, or a log line.
"""

from __future__ import annotations

import os
from typing import Mapping, Optional

from pgx.ingestion.clinpgx.catalog import CLINPGX_ALLOWED_HOSTS, CLINPGX_BASE_URL
from pgx.ingestion.common.errors import ConfigurationError
from pgx.ingestion.common.http import (
    DEFAULT_MAX_RESPONSE_BYTES, TransportPolicy, UrllibTransport,
)

__all__ = [
    "CLINPGX_TOKEN_ENV",
    "build_clinpgx_policy",
    "build_clinpgx_transport",
    "clinpgx_credential_headers",
]

#: Where the API token comes from, if one is used at all. ClinPGx's public
#: endpoints did not require one in the legacy probes; the hook exists so that
#: a token, if ever needed, has exactly one place to live.
CLINPGX_TOKEN_ENV = "CLINPGX_API_TOKEN"


def build_clinpgx_policy(
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
) -> TransportPolicy:
    """Return the transport policy for ClinPGx: HTTPS, one host, no drift."""
    return TransportPolicy(
        allowed_hosts=CLINPGX_ALLOWED_HOSTS,
        require_https=True,
        allow_cross_host_redirects=False,
        max_response_bytes=max_response_bytes)


def clinpgx_credential_headers(
    env: Optional[Mapping[str, str]] = None,
) -> Mapping[str, str]:
    """Return the credential headers, or an empty mapping when none is set.

    Absence is not an error: the endpoints the legacy probes used were public.
    The token is never accepted as an argument to a request-building function,
    so there is no path by which it could reach a cache key.
    """
    environment = os.environ if env is None else env
    token = (environment.get(CLINPGX_TOKEN_ENV) or "").strip()
    if not token:
        return {}
    return {"Authorization": "Bearer %s" % token}


def build_clinpgx_transport(
    env: Optional[Mapping[str, str]] = None,
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
) -> UrllibTransport:
    """Build the production transport for ClinPGx.

    Constructing it makes no request. The first network activity happens when a
    caller invokes ``send``, which only the acquisition path does.
    """
    if not CLINPGX_BASE_URL.startswith("https://"):  # pragma: no cover - guard
        raise ConfigurationError(
            "the ClinPGx base URL must be https://, got %r" % CLINPGX_BASE_URL)
    return UrllibTransport(
        policy=build_clinpgx_policy(max_response_bytes),
        credential_headers=clinpgx_credential_headers(env))
