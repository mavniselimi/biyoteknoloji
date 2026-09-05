# -*- coding: utf-8 -*-
"""SQLAlchemy declarative base and naming convention (WP-02).

The naming convention matters for migrations: without it PostgreSQL invents
constraint names, Alembic cannot reliably drop them, and a downgrade leaves
debris behind. Fixing the convention here makes every index and constraint name
deterministic and therefore reversible.

Domain dataclasses never inherit from this base. ORM classes and domain models
are separate hierarchies joined only by the explicit functions in
:mod:`pgx.infrastructure.db.mappers`.
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

__all__ = ["Base", "NAMING_CONVENTION", "metadata"]

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base for every PGx ORM model.

    Every mapped class lives in :mod:`pgx.infrastructure.db.models`; no ORM
    class is defined anywhere else in the codebase.
    """

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


#: Metadata object Alembic targets.
metadata = Base.metadata
