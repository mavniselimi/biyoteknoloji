# PGx Platform V2 - the one application image (WP-24).
#
# One image serves the API and the server-rendered interface, and the same
# image runs every one-shot operation: migration, ingestion, dataset and
# release builds, verification, safety, security and audit commands. That is
# not a convenience. An operational command run from a *different* image is a
# command whose dependency set nobody verified against the one serving
# traffic, and "the migration ran under a different psycopg" is a bad thing to
# discover from a production incident.
#
# What this file is careful about, and why:
#
#   * Two stages. The builder has a compiler because argon2-cffi and psycopg
#     may need one; the runtime has none. A compiler in a runtime image is a
#     tool an attacker who gets a shell no longer has to bring.
#
#   * A non-root user, created with a fixed uid so a mounted volume's
#     ownership is predictable across hosts.
#
#   * An explicit list of runtime assets, never `COPY data/`. The allowlist
#     lives in pgx/deployment/runtime_assets.py with a reason per file, and
#     `pgx-deploy build` fails when one is missing or its checksum disagrees.
#     `COPY data/` would ship the raw ClinPGx snapshot, the legacy baseline
#     and - the reason this matters - any restricted holdout payload a later
#     work package puts under data/.
#
#   * No secret, no .env, no certificate, no key. .dockerignore excludes them
#     and `pgx-deploy build` checks the built filesystem afterwards, because
#     an ignore file is a statement of intent and the check is a measurement.
#
#   * No migration on start-up. CMD serves. Migration is `pgx-deploy migrate`,
#     run by an operator, once. An image that upgraded its own schema would
#     apply 0011 from whichever replica booted first, concurrently, against a
#     database whose downgrade path refuses to run.
#
# Base image pinning: the tag below is exact down to the patch release. It is
# NOT pinned by digest, because the digest could not be resolved in the
# environment this file was written in (no registry was reachable) and writing
# a digest nobody resolved would be a fabricated pin. To pin properly:
#
#     docker pull python:3.11.9-slim-bookworm
#     docker inspect --format='{{index .RepoDigests 0}}' python:3.11.9-slim-bookworm
#
# then put that value in deploy/base-image.pin. `pgx-deploy build` reads it and
# records it in the build provenance; when the file is absent the provenance
# records base_image_digest: null, which is the truthful state and is visible
# rather than assumed.

# ---------------------------------------------------------------------------
# Stage 1 - builder
# ---------------------------------------------------------------------------
FROM python:3.11.9-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    SOURCE_DATE_EPOCH=1735689600

# Build dependencies for the two packages that may need to compile:
# argon2-cffi (through cffi) and psycopg. Present here and in no later stage.
RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        build-essential=12.9 \
        libpq-dev \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# uv, pinned. An unpinned installer is an unpinned build.
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

WORKDIR /src

# The lockfile is copied first and separately so that a dependency change
# invalidates this layer and a source change does not.
#
# `uv sync --frozen` REFUSES to proceed when uv.lock disagrees with
# pyproject.toml. That refusal is the point: a build that silently re-resolved
# would produce an image whose contents the lockfile does not describe, and
# the provenance document would then pin a lockfile hash that says nothing
# about what is installed.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project --extra web

# The project itself, installed into the same environment.
COPY pgx ./pgx
COPY apps ./apps
COPY migrations ./migrations
COPY alembic.ini ./alembic.ini
COPY config ./config
COPY schemas ./schemas
RUN uv sync --frozen --extra web

# Argon2 must be importable in the image that will hash passwords. Checked
# here, at build time, rather than discovered by a readiness probe in
# production: the WP-23 handoff is explicit that a build which cannot hash a
# password must fail rather than fall back, and this is where that fails.
RUN /src/.venv/bin/python -c "import argon2; print('argon2', argon2.__version__)"
RUN /src/.venv/bin/python -c "import psycopg; print('psycopg', psycopg.__version__)"

# ---------------------------------------------------------------------------
# Stage 2 - runtime
# ---------------------------------------------------------------------------
FROM python:3.11.9-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    PGX_API_ENV=STAGING \
    PGX_API_AUTH_MODE=UNCONFIGURED

# libpq only - the client library psycopg links against. No compiler, no
# headers, no build tooling.
RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        libpq5 \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 pgx \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin pgx

WORKDIR /app

COPY --from=builder --chown=root:root /src/.venv /app/.venv
COPY --chown=root:root pgx /app/pgx
COPY --chown=root:root apps /app/apps
COPY --chown=root:root migrations /app/migrations
COPY --chown=root:root alembic.ini /app/alembic.ini
COPY --chown=root:root config /app/config
COPY --chown=root:root schemas /app/schemas

# The runtime assets, named one directory at a time rather than as `data/`.
# Each of these directories holds only files the serving path reads; the
# allowlist in pgx/deployment/runtime_assets.py names them file by file with a
# reason, and `pgx-deploy build --verify-assets` checks the checksums.
COPY --chown=root:root data/demo /app/data/demo
COPY --chown=root:root data/api /app/data/api
COPY --chown=root:root data/web /app/data/web
COPY --chown=root:root data/safety /app/data/safety
COPY --chown=root:root data/security /app/data/security
COPY --chown=root:root data/validation /app/data/validation
COPY --chown=root:root data/verification /app/data/verification

# Owned by root, run as pgx: the application can read its code and its sealed
# artifacts and can modify neither. A container that cannot rewrite its own
# ruleset is one whose release identity means something.
USER 10001:10001

EXPOSE 8000

# Liveness only. It must not consult PostgreSQL, the active release, ClinPGx
# or any model: a container restarted because its database was briefly
# unreachable takes the deployment down for a reason that was going to resolve
# itself. Readiness is /health/ready, and an orchestrator uses that to stop
# sending traffic - not to kill the process.
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=2).status == 200 else 1)"]

# Serve. Nothing else. Every operational command is an explicit `docker
# compose run` against this same image - see docs/operations/.
CMD ["python", "-m", "uvicorn", "apps.web.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--no-server-header", "--proxy-headers", \
     "--forwarded-allow-ips", "*", \
     "--timeout-graceful-shutdown", "20"]
