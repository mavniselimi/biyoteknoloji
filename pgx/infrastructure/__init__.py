"""Infrastructure layer for PGx Platform V2.

Everything framework-, driver-, or database-specific lives here. The dependency
direction is one-way: infrastructure imports :mod:`pgx.domain`, and the domain
never imports infrastructure.
"""
