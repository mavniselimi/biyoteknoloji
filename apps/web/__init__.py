"""The server-rendered demonstration interface (WP-17).

A presentation layer over the closed WP-16 application contract, and nothing
else. The permitted direction is one way:

    WP-16 response contract
      -> verified web client response
      -> immutable presentation view model
      -> server-rendered HTML template
      -> HTML claim-safety gate
      -> browser

Nothing in this package calculates. It does not evaluate a phenotype, select a
rule, aggregate coverage, resolve a release, count findings to infer severity,
or choose which medication matters most. Every governed fact it displays was
decided by WP-13/WP-14 and returned by WP-16; this layer's whole contribution
is to show those facts without losing, reordering or reinterpreting any of
them.

**The split, and why this one differs from WP-16's.** As in the API package,
the modules that decide anything import no web framework. Unlike WP-16,
*templates render here*: Jinja2 is installed in this environment, so the HTML
this layer produces is really produced, really scanned for prohibited claims,
and really parsed to check its structure. What remains unavailable is FastAPI -
so the routers are still wiring covered by static assertions - and any browser
at all, so no screenshot in this repository is a browser capture, and none is
claimed to be.

**The one label vocabulary.** Attention codes, coverage codes, coverage reason
codes, observation states, modes and input kinds all have controlled tr/en
labels in :mod:`pgx.reporting.templates`, written for WP-15's reports. This
layer reuses them rather than writing a second set. A UI vocabulary that
drifted from the report vocabulary would mean a reader who saw a screen and a
report of the same assessment could reasonably conclude they described
different results.
"""

from __future__ import annotations

WEB_VERSION = "1.0.0"
WEB_TITLE = "PGx Platform V2 - Araştırma/Prototip Arayüzü"

#: The primary interface locale. English is supported only through the same
#: controlled label tables, with the same safety properties; nothing is
#: translated on the fly and no locale falls back to another.
DEFAULT_LOCALE = "tr"
SUPPORTED_LOCALES = ("tr", "en")

#: Web pages live at the application root. The API keeps ``/api/v1`` and the
#: health routes keep ``/health``; a web route may never claim either.
WEB_ROOT_PATH = ""

#: Reserved prefixes a web route must never occupy. Enforced at import by
#: :mod:`apps.web.routes`, so a page cannot shadow an API path by accident.
RESERVED_PATH_PREFIXES = ("/api/", "/health/", "/openapi", "/docs", "/redoc")
