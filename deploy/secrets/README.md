# Deployment secrets

Every file in this directory is mounted into a container at
`/run/secrets/<name>` and **none of them is committed**. `.gitignore` excludes
`deploy/secrets/*` except this README, `.dockerignore` keeps the whole
directory out of every build context, and `pgx-security secret-scan` treats a
credential found here as a finding rather than an exception.

There are no defaults and no example values that would work. That is
deliberate: an example credential that happens to be valid is a credential,
and a deployment that starts with one is a deployment nobody had to configure.

## What to create

    deploy/secrets/database_url
        One line. The application DSN, e.g.
        postgresql+psycopg://<user>:<password>@postgres:5432/pgx_staging
        A bare postgresql:// URL is normalised to postgresql+psycopg://;
        any other driver, and any sqlite:// URL, is refused.

    deploy/secrets/postgres_user
    deploy/secrets/postgres_password
        One line each. Used by the postgres image's *_FILE variables so the
        password never appears in `docker inspect` or the process table.

Create them with restrictive permissions and no trailing content:

    umask 077
    printf '%s' 'postgresql+psycopg://...' > deploy/secrets/database_url

A single trailing newline is stripped when the file is read; nothing else is
trimmed, because silently altering a secret is worse than refusing it.

## What is *not* here

No CSRF deployment key. WP-23 keys CSRF tokens per session from
`SessionRecord.csrf_secret`, and the login form from the short-lived
`__Host-pgx_preauth` cookie the server just set. Neither derives from a
deployment-wide key, so requiring one would add a secret to rotate, mount and
leak that nothing verifies. `PGX_CSRF_SECRET` is still a declared variable so
that an operator who mounts one gets a clear answer, and so that setting both
it and `PGX_CSRF_SECRET_FILE` is refused as the configuration mistake it is.

No backup encryption key by default. `PGX_BACKUP_ENCRYPTION_KEY_FILE` is read
only by `pgx-deploy backup`, and only when a backup is actually being taken.

No TLS material. Certificates and keys go in `deploy/tls/`, which is ignored
by git and by Docker for the same reasons.
