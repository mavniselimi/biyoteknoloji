"""FastAPI routers for the interface. Wiring only.

Every handler does the same four things: resolve its dependencies, call one
page-assembly function from :mod:`apps.web.pages`, and return the HTML with
that function's status and headers. No handler builds a view model, calls a
template, or decides anything.

FastAPI was not installable in the environment this was written in, so nothing
here can execute; that is exactly why nothing here decides. The page
assembly, the view models, the client, the claim gate and the templates are
all framework-free and all really run - see ``tests/unit/web/``.
``tests/unit/web/test_routes.py`` reads these modules as syntax trees and
asserts that the routes they register are exactly the declared ones.
"""
