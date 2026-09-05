# -*- coding: utf-8 -*-
"""Deployable applications built on top of the governed ``pgx`` packages.

Nothing under ``apps`` may be imported by ``pgx``. The dependency runs one
way: an application composes services, and a service knows nothing about the
transport that called it.
"""

from __future__ import annotations

__all__: list = []
