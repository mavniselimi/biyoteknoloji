# -*- coding: utf-8 -*-
"""Engine and session factories (WP-02).

Importing this module creates nothing and connects to nothing. There is no
module-level engine, no global session, and no implicit connection: every
caller passes a :class:`~pgx.infrastructure.db.config.DatabaseConfig` and
receives an object it owns and disposes of.

Sync SQLAlchemy 2.x is sufficient for P0. Async adds no benefit to CLI jobs and
a server-rendered UI, and would complicate the transaction boundary.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator, Optional

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from pgx.infrastructure.db.config import DatabaseConfig, load_database_config

__all__ = [
    "create_database_engine",
    "create_session_factory",
    "session_scope",
    "verify_connectivity",
]


def create_database_engine(config: Optional[DatabaseConfig] = None) -> Engine:
    """Create a new :class:`Engine`. The caller owns and disposes of it.

    ``pool_pre_ping`` is enabled so a connection recycled by the server is
    detected on checkout instead of failing mid-transaction.
    """
    settings = load_database_config() if config is None else config
    return create_engine(
        settings.url,
        echo=settings.echo,
        pool_size=settings.pool_size,
        max_overflow=settings.max_overflow,
        pool_timeout=settings.pool_timeout_seconds,
        pool_recycle=settings.pool_recycle_seconds,
        pool_pre_ping=True,
        future=True,
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create a session factory bound to ``engine``.

    ``expire_on_commit=False`` is deliberate: repositories convert ORM rows to
    domain objects, and those plain dataclasses must stay readable after the
    transaction closes, without a lazy refresh reaching back to a dead session.
    """
    return sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Yield a session that rolls back unless the body completes.

    A low-level helper. Application code uses
    :class:`~pgx.infrastructure.db.unit_of_work.SqlAlchemyUnitOfWork`, which
    also enforces cross-row invariants before committing.
    """
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def verify_connectivity(engine: Engine) -> str:
    """Return the server version, proving a real connection was established.

    Used by ``scripts/db_check.py``. It runs one trivial statement and writes
    nothing.
    """
    with engine.connect() as connection:
        return str(connection.execute(text("SELECT version()")).scalar_one())
