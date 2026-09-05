# -*- coding: utf-8 -*-
"""Deterministic evaluation engines.

WP-12 owns exactly one of them: phenotype equality. Given a normalized
phenotype observation and a WP-11 phenotype condition, it answers whether the
one satisfies the other, and nothing else.

The package is deliberately narrow. Coverage aggregation is WP-13, assessment
and attention are WP-14, and report prose is WP-15. None of those exists here,
and the boundary tests assert their absence by name rather than by intention.
"""

from __future__ import annotations

#: The engine package's own version marker, bumped when a published contract
#: inside it changes. Individual contracts carry their own versions.
ENGINE_PACKAGE_VERSION = "pgx-engine/1"

__all__ = ["ENGINE_PACKAGE_VERSION"]
