# -*- coding: utf-8 -*-
"""Shared test scaffolding.

Deliberately under ``tests/`` and not under ``pgx/``. The approved-world
fixtures here construct a protocol that is APPROVED and an evidence build that
is not quarantined - neither of which is true of this repository - so keeping
them out of the shipped package means production code has no route to build
that world by accident.
"""
