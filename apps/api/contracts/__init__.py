# -*- coding: utf-8 -*-
"""The API boundary contracts (WP-16).

``spec`` declares every request and response shape as data. ``validate``
enforces that declaration with the standard library alone. ``models`` restates
the same shapes as Pydantic v2 classes for FastAPI to bind and document.

There is one declaration and two consumers, not two declarations. A test reads
``models`` with :mod:`ast` and asserts that its classes carry exactly the
fields ``spec`` names - which is a check that runs in an environment where
Pydantic cannot even be imported, and is therefore the check that actually
holds the two halves together here.
"""

from __future__ import annotations

__all__: list = []
