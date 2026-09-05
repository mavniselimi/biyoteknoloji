# -*- coding: utf-8 -*-
"""The P0 HTTP application layer (WP-16).

A thin shell around services that already exist. The direction is one way and
has no branches::

    HTTP request
        -> strict request contract
        -> request adapter
        -> one existing application service
        -> persisted immutable result
        -> strict response adapter
        -> JSON response

**Importing this package connects to nothing.** No engine is created, no
session is opened, no active release is resolved and no fixture is loaded at
import time. Everything an endpoint needs arrives through a typed dependency
provider, which is what makes the whole surface testable with in-memory ports
and what stops a misconfigured deployment from serving a half-working
assessment path.

**This package is split in two on purpose.**

*Framework-free* modules - the contract spec, the error envelope and its
status mapping, the security matrix, the settings reader, every adapter, the
catalogue cursor, the readiness checks and the OpenAPI builder - import only
the standard library and ``pgx``. They hold all of the decisions, and they are
executable and tested wherever Python runs.

*Framework-bound* modules - ``factory``, ``dependencies``, ``middleware``,
``routers`` and the Pydantic models - import FastAPI and Pydantic and hold no
decisions at all: they wire the first set to HTTP. An AST test asserts that
the routers match the declared route table and that the Pydantic models match
the declared contract spec, so the two halves cannot drift even in an
environment where the framework cannot be imported.
"""

from __future__ import annotations

__all__ = ["API_VERSION", "API_TITLE", "API_ROOT_PATH"]

#: The contract version this surface publishes. Bumped when a request or
#: response shape changes in a way a client would notice.
API_VERSION = "1.0.0"

API_TITLE = "PGx Platform V2 API"

#: Every governed route lives under this prefix. Health routes deliberately do
#: not: an orchestrator probing liveness must not have to know the API
#: version, and a version bump must not silently retire a probe.
API_ROOT_PATH = "/api/v1"
