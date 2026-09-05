# -*- coding: utf-8 -*-
"""Application services (WP-03).

This layer orchestrates domain objects through repository *ports*. It imports
nothing from :mod:`pgx.infrastructure`: a service that reached for a SQLAlchemy
session could not be exercised without a database, and the release rules are
exactly the part that most needs testing offline.

WP-03 ships one service, :mod:`pgx.application.release_service`. Assessment,
ingestion and reporting services belong to their own work packages.
"""
