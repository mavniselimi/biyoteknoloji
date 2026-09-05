"""FastAPI routers. Wiring only.

Each module here registers the routes :mod:`apps.api.routes` declares, calls
one adapter or one application service per route, and maps the outcome to a
status code. No router validates a phenotype, selects a release, inspects a
rule, resolves evidence in order to calculate with it, aggregates coverage or
attention, regenerates a stored assessment, or writes a sentence.

That is not a stylistic preference. FastAPI could not be installed in the
environment this was written in, so no line in this package can be executed
here - and a decision that cannot be executed cannot be tested. Everything
that decides anything therefore lives in the framework-free half
(:mod:`apps.api.adapters`, :mod:`apps.api.contracts`, :mod:`apps.api.errors`,
:mod:`apps.api.catalog`, :mod:`apps.api.readiness`), which is fully executable
and fully tested here.
``TestRoutersMatchTheDeclaration`` in :mod:`tests.unit.api.test_openapi` reads
these modules as syntax trees and asserts that the routes they register are
exactly the declared ones, addressed by operation id, with no hand-written
path and no locally-built access policy.
"""
