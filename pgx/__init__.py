"""PGx Platform V2 package root.

This package is created by WP-00 (Intended Purpose, Claims Boundary, and
Safety Contract). At WP-00 it contains only the claims/safety domain
contract. Application, ingestion, engine, reporting, validation, and
infrastructure subpackages are introduced by later work packages as
defined in ``architecture.md`` section 5.3.

WP-00 deliberately adds no package manifest, dependency, database, or
framework. Everything here must run on the Python standard library.
"""

__all__ = ["__version__"]

# Software identity is formally registered in WP-02/WP-03. This value is a
# pre-registry placeholder and must not be presented as a release version.
__version__ = "0.0.0+wp00"
