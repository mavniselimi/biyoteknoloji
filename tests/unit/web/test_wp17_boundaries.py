# -*- coding: utf-8 -*-
"""Package boundaries: what the interface may and may not reach.

A page displays governed facts that WP-16 returned. It must not be able to
produce a second interpretation of them, and the way to guarantee that is to
make the second interpretation unreachable: no web module imports an engine, a
repository, an ORM, a legacy module or anything that opens a socket.

Read as syntax trees. A text search for ``pgx.engine`` would fail on the
docstrings that explain why it is absent, which is most of them.
"""

from __future__ import annotations

import ast
import io
import os
import unittest

from tests.unit.web._support import (FORBIDDEN_IMPORT_ROOTS,
                                     FORBIDDEN_PGX_PREFIXES,
                                     FRAMEWORK_BOUND_MODULES,
                                     FRAMEWORK_FREE_MODULES, REPO_ROOT,
                                     STATIC_DIR, TEMPLATE_DIR, identifiers_of,
                                     imports_of, module_path, source,
                                     template_paths, tree, web_modules)


class TestTheInterfaceReachesNothingItShouldNot(unittest.TestCase):

    #: The one module permitted to reach WP-12, and why.
    #:
    #: ``demo_migration`` canonicalises legacy phenotype spellings by calling
    #: WP-12's own normaliser. The alternative is a mapping table here, which
    #: would be a second place for ``rapid`` to start meaning ``ultrarapid``
    #: (SAFETY-INV-004) - the exact failure WP-12 exists to prevent. It is an
    #: offline migration tool: it runs in the artifact generator, never in a
    #: request, and ``test_no_runtime_module_imports_the_migration`` asserts
    #: that no module a page can reach imports it.
    MIGRATION_EXEMPTION = "demo_migration.py"

    def test_no_web_module_imports_an_engine_or_a_repository(self):
        for path in web_modules():
            relative = os.path.relpath(path, os.path.join(REPO_ROOT, "apps",
                                                          "web"))
            if relative == self.MIGRATION_EXEMPTION:
                continue
            with self.subTest(module=relative):
                for name in imports_of(path):
                    for prefix in FORBIDDEN_PGX_PREFIXES:
                        self.assertFalse(
                            name == prefix or name.startswith(prefix + "."),
                            "%s imports %s; a page reaches governed facts "
                            "through the API client, never by recomputing "
                            "them" % (relative, name))

    def test_the_migration_reaches_only_the_phenotype_normaliser(self):
        """Its exemption is one function, not the engine."""
        imported = imports_of(module_path(self.MIGRATION_EXEMPTION))
        engine_imports = {name for name in imported
                          if name.startswith("pgx.engine")}
        self.assertEqual(engine_imports,
                         {"pgx.engine.phenotype_normalization"})

    def test_no_runtime_module_imports_the_migration(self):
        """A page never runs the migration; it reads the sealed artifact."""
        runtime = set(FRAMEWORK_FREE_MODULES + FRAMEWORK_BOUND_MODULES)
        runtime -= {self.MIGRATION_EXEMPTION, "artifacts.py"}
        for relative in sorted(runtime):
            with self.subTest(module=relative):
                for name in imports_of(module_path(relative)):
                    self.assertNotIn("demo_migration", name)

    def test_no_web_module_imports_a_legacy_or_network_module(self):
        for path in web_modules():
            with self.subTest(module=os.path.relpath(path, REPO_ROOT)):
                for name in imports_of(path):
                    self.assertNotIn(name.split(".")[0],
                                     FORBIDDEN_IMPORT_ROOTS)

    def test_no_web_module_names_a_legacy_or_model_symbol(self):
        forbidden = {"RISK_LABEL_TR", "calculate_risk", "generate_report",
                     "rank_alternatives", "GEMINI_API_KEY",
                     "calculate_assessment", "evaluate_coverage",
                     "match_observation", "GenerativeModel"}
        for path in web_modules():
            with self.subTest(module=os.path.relpath(path, REPO_ROOT)):
                self.assertEqual(identifiers_of(path) & forbidden, set())

    def test_only_the_client_reaches_the_api_adapters(self):
        """One module consumes WP-16, and the rest consume that module.

        A view model that called an adapter directly would be a second place
        the response shape is known, and the two would drift.
        """
        for path in web_modules():
            relative = os.path.relpath(path, os.path.join(REPO_ROOT, "apps",
                                                          "web"))
            if relative in ("client.py", "gate_status.py"):
                continue
            imported = imports_of(path)
            with self.subTest(module=relative):
                for name in imported:
                    self.assertFalse(
                        name.startswith("apps.api.adapters"),
                        "%s imports %s; only the client consumes WP-16's "
                        "adapters" % (relative, name))

    def test_no_web_module_reads_the_environment_outside_configuration(self):
        for path in web_modules():
            relative = os.path.relpath(path, os.path.join(REPO_ROOT, "apps",
                                                          "web"))
            if relative == "config.py":
                continue
            attributes = {node.attr for node in ast.walk(tree(path))
                          if isinstance(node, ast.Attribute)}
            with self.subTest(module=relative):
                self.assertNotIn("environ", attributes)
                self.assertNotIn("getenv", attributes)

    def test_no_web_module_reads_the_legacy_seed_at_runtime(self):
        """Only the migration names the seed file, and it runs offline.

        A runtime that read ``clinpgx_mvp_seed/`` would depend on a file
        nobody versions as a runtime artifact and would pick up an edit to it
        without a migration having run.
        """
        for path in web_modules():
            relative = os.path.relpath(path, os.path.join(REPO_ROOT, "apps",
                                                          "web"))
            if relative == "demo_migration.py":
                continue
            # Docstrings excluded: several of these modules explain in prose
            # that they never read the seed, and a check that matched its own
            # explanation would be a check nobody could satisfy honestly.
            module = tree(path)
            # clean=False: ast.get_docstring() re-indents by default, so the
            # cleaned text does not equal the Constant it came from and the
            # subtraction below would remove nothing.
            docstrings = {ast.get_docstring(node, clean=False) or ""
                          for node in ast.walk(module)
                          if isinstance(node, (ast.Module, ast.ClassDef,
                                               ast.FunctionDef,
                                               ast.AsyncFunctionDef))}
            literals = {node.value for node in ast.walk(module)
                        if isinstance(node, ast.Constant)
                        and isinstance(node.value, str)} - docstrings
            with self.subTest(module=relative):
                self.assertFalse(
                    any("clinpgx_mvp_seed" in value for value in literals),
                    "%s names the legacy seed file" % relative)


class TestImportingTheInterfaceOpensNothing(unittest.TestCase):

    def test_every_framework_free_module_actually_imports(self):
        import importlib
        for relative in FRAMEWORK_FREE_MODULES:
            if relative.endswith("__init__.py"):
                continue
            dotted = "apps.web." + relative[:-3].replace(os.sep, ".")
            with self.subTest(module=dotted):
                importlib.import_module(dotted)

    def test_no_framework_free_module_imports_a_web_framework(self):
        for relative in FRAMEWORK_FREE_MODULES:
            with self.subTest(module=relative):
                for name in imports_of(module_path(relative)):
                    self.assertNotIn(name.split(".")[0],
                                     ("fastapi", "starlette", "uvicorn"))

    #: Operations that read, write, connect or resolve. A denylist rather
    #: than an allowlist of permitted calls: the permitted set is every value
    #: constructor the package declares and grows with each one, while the
    #: forbidden set is the small fixed list of things that constitute work.
    IO_CALLS = frozenset({
        "connect", "create_engine", "sessionmaker", "session", "cursor",
        "execute", "commit", "resolve", "require_release",
        "require_assessment_service", "require_assessment_reader",
        "require_evidence_repository", "load_development_cases",
        "build_catalog", "build_gate_status", "build_ui_gate_status",
        "render_page", "render_template", "environment", "get_template",
        "open", "read", "read_text", "read_bytes", "urlopen", "get", "post",
        "request", "listdir", "walk", "glob", "mkdir", "makedirs", "write",
        "run", "check_output", "Popen", "which",
    })

    def test_no_module_does_io_or_resolves_a_release_at_import(self):
        """Module-level statements are declarations, not work.

        Checked structurally over module-scope calls. ``import apps.web.main``
        must build an application without touching a database, resolving a
        release, reading the sealed catalogue or compiling a template - all of
        which happen per request, through the provider.
        """
        for path in web_modules():
            relative = os.path.relpath(path, os.path.join(REPO_ROOT, "apps",
                                                          "web"))
            module = tree(path)
            for node in module.body:
                if not isinstance(node, (ast.Assign, ast.AnnAssign,
                                         ast.Expr)):
                    continue
                for call in ast.walk(node):
                    if not isinstance(call, ast.Call):
                        continue
                    name = (call.func.id if isinstance(call.func, ast.Name)
                            else getattr(call.func, "attr", ""))
                    with self.subTest(module=relative, call=name):
                        self.assertNotIn(
                            name, self.IO_CALLS,
                            "%s calls %s() at module scope" % (relative, name))

    def test_importing_the_interface_reads_no_file(self):
        """Proved by importing with the filesystem watched, not by reading.

        ``builtins.open`` is wrapped for the duration of the import and any
        path under the repository is recorded. A module that read the sealed
        catalogue, a template or the legacy seed at import would appear here.
        """
        import builtins
        import importlib
        import sys

        for name in [key for key in sys.modules
                     if key.startswith("apps.web")]:
            del sys.modules[name]

        opened = []
        real_open = builtins.open

        def _watch(file, *args, **kwargs):
            try:
                if isinstance(file, str) and REPO_ROOT in os.path.abspath(file):
                    opened.append(os.path.relpath(os.path.abspath(file),
                                                  REPO_ROOT))
            except (TypeError, ValueError):  # pragma: no cover - defensive
                pass
            return real_open(file, *args, **kwargs)

        builtins.open = _watch
        try:
            for relative in FRAMEWORK_FREE_MODULES:
                if relative.endswith("__init__.py"):
                    continue
                importlib.import_module(
                    "apps.web." + relative[:-3].replace(os.sep, "."))
        finally:
            builtins.open = real_open

        # Python reads .py files through its own loader, not builtins.open,
        # so anything recorded here is a deliberate read by module code.
        data_reads = [name for name in opened if not name.endswith(".py")]
        self.assertEqual(data_reads, [],
                         "importing the interface read %s" % data_reads)


class TestModuleInventory(unittest.TestCase):

    def test_every_module_is_classified(self):
        expected = {module_path(relative) for relative
                    in FRAMEWORK_FREE_MODULES + FRAMEWORK_BOUND_MODULES}
        self.assertEqual(set(web_modules()), expected)


class TestNoExternalAssets(unittest.TestCase):
    """Everything the browser loads comes from this origin."""

    def test_no_template_references_an_external_resource(self):
        for path in template_paths():
            text = source(path)
            with self.subTest(template=os.path.basename(path)):
                for marker in ("http://", "https://", "//cdn", "//fonts",
                               "unpkg", "jsdelivr", "cdnjs", "googleapis",
                               "gstatic"):
                    self.assertNotIn(marker, text)

    def test_no_stylesheet_or_script_references_an_external_resource(self):
        for directory in ("css", "js"):
            folder = os.path.join(STATIC_DIR, directory)
            for name in sorted(os.listdir(folder)):
                text = source(os.path.join(folder, name))
                with self.subTest(asset=name):
                    for marker in ("http://", "https://", "@import url(",
                                   "cdn", "googleapis", "gstatic"):
                        self.assertNotIn(marker, text)

    def test_the_stylesheet_uses_a_local_font_stack(self):
        text = source(os.path.join(STATIC_DIR, "css", "app.css"))
        self.assertNotIn("@font-face", text)
        self.assertIn("-apple-system", text)

    def test_the_script_makes_no_network_call(self):
        """Comments stripped first.

        The file's own header lists the APIs it does not use, so a scan of the
        raw text matches its own explanation. Stripping comments is what makes
        this a check on the code rather than on the prose about the code.
        """
        import re

        text = source(os.path.join(STATIC_DIR, "js", "app.js"))
        code = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
        code = re.sub(r"//[^\n]*", " ", code)
        for marker in ("fetch(", "XMLHttpRequest", "WebSocket", "eval(",
                       "innerHTML", "document.write", "import(",
                       "outerHTML", "insertAdjacentHTML"):
            with self.subTest(marker=marker):
                self.assertNotIn(marker, code)
        # And the comment really did explain rather than hide something.
        self.assertIn("textContent", text)

    def test_no_vendored_framework_directory_exists(self):
        """The one repair nobody should make: a look-alike package."""
        for name in ("fastapi", "starlette", "jinja2", "playwright",
                     "uvicorn", "httpx"):
            with self.subTest(package=name):
                self.assertFalse(os.path.isdir(os.path.join(REPO_ROOT, name)))


class TestTheApiSurfaceIsUnchanged(unittest.TestCase):
    """Adding an interface changed no API path and no API document."""

    def test_the_api_route_table_carries_no_page_route(self):
        """WP-17 added an interface; it must never have added an API path.

        The count moved from eleven to fourteen when WP-22 replaced three
        expert-review stubs, each of which answered 501, with six real
        operations and added a listing and a corrections path. Freezing the
        number was the wrong way to state the boundary: it made a later work
        package's legitimate API work look like a WP-17 violation. The
        boundary WP-17 owns is that no HTML page ever becomes an API route,
        and that the API surface is exactly the enumerated one - so the
        successor enumerates it, and the count follows from the list.
        """
        from apps.api.routes import ROUTES
        paths = sorted(route.path for route in ROUTES)
        self.assertEqual(paths, sorted([
            "/api/v1/assessments", "/api/v1/assessments/{assessment_id}",
            "/api/v1/drugs", "/api/v1/evidence/{evidence_id}",
            "/api/v1/expert-reviews",
            "/api/v1/expert-reviews/{case_id}",
            "/api/v1/expert-reviews/{case_id}/complete",
            "/api/v1/expert-reviews/{case_id}/corrections",
            "/api/v1/expert-reviews/{case_id}/expected",
            "/api/v1/expert-reviews/{case_id}/reveal",
            "/api/v1/genes", "/api/v1/system/version",
            "/health/live", "/health/ready"]))
        self.assertEqual(len(ROUTES), len(paths))

    def test_the_openapi_document_carries_no_html_route(self):
        from apps.api.openapi import build_document
        from apps.web.routes import WEB_ROUTES

        document = build_document()
        for route in WEB_ROUTES:
            with self.subTest(page=route.name):
                self.assertNotIn(route.path, document["paths"])

    def test_no_web_path_shadows_an_api_path(self):
        from apps.api.routes import ROUTES
        from apps.web.routes import WEB_ROUTES

        api_paths = {route.path for route in ROUTES}
        for route in WEB_ROUTES:
            with self.subTest(page=route.name):
                self.assertNotIn(route.path, api_paths)
                self.assertFalse(route.path.startswith("/api/"))
                self.assertFalse(route.path.startswith("/health/"))

    def test_the_web_application_publishes_no_openapi_document(self):
        text = source(module_path("factory.py"))
        self.assertIn("openapi_url=None", text)


class TestTheInterfaceShipsNoValidationArchitecture(unittest.TestCase):
    """WP-17 ships an interface. The validation dataset is somebody else's.

    This class used to assert that ``pgx/validation`` did not exist. That was
    true while WP-17 was the current work package and became false the day
    WP-18 started - the same way a pinned ``wp17_started: False`` became false
    the day ``apps/web`` appeared. A test that has to be deleted when the next
    package begins was pinning the calendar, not a property.

    What survives, and is what WP-17 actually owes: **the interface layer
    contains no validation dataset code and imports none.** The page may
    report that a validation architecture exists; it may not become one.
    """

    def test_no_validation_package_lives_under_apps(self):
        for relative in ("apps/validation", "apps/web/validation",
                         "apps/web/holdout", "data/holdout"):
            with self.subTest(path=relative):
                self.assertFalse(
                    os.path.exists(os.path.join(REPO_ROOT, relative)))

    def test_no_web_module_imports_the_validation_package(self):
        """The interface renders an empty state; it does not read the dataset.

        WP-21 owns showing a metric and WP-22 owns showing a review. Until
        then a page that could read holdout metadata is a page that could
        start displaying it.
        """
        for path in web_modules():
            relative = os.path.relpath(path, REPO_ROOT)
            for name in imports_of(path):
                with self.subTest(module=relative, imported=name):
                    self.assertNotEqual(name.split(".")[:2],
                                        ["pgx", "validation"])

    def test_no_web_module_names_a_validation_case_identifier(self):
        for path in web_modules():
            relative = os.path.relpath(path, REPO_ROOT)
            literals = {node.value for node in ast.walk(tree(path))
                        if isinstance(node, ast.Constant)
                        and isinstance(node.value, str)}
            with self.subTest(module=relative):
                self.assertFalse([value for value in literals
                                  if value.startswith("PGX-VAL-")])

    def test_no_web_module_stores_a_case_role_other_than_development(self):
        """The interface holds no holdout *case*. It may name the partitions.

        Before WP-21 this asserted that the two holdout role names appeared
        nowhere in ``apps/web``, which was the right shape while the
        interface had no validation architecture to talk about. WP-21 gives
        the page a public aggregate feed with one section per partition, so
        the page must be able to write the section headings.

        The assertion therefore moves to what it was always defending: no web
        module may hold a holdout *case*, identifier or payload. Naming a
        partition in a heading leaks nothing; holding one of its cases does.
        The neighbouring tests -
        ``test_no_web_module_names_a_validation_case_identifier`` and
        ``test_the_interface_cannot_read_a_restricted_payload`` - are the ones
        that enforce it, and they are unchanged.
        """
        forbidden = {"INTERNAL_HOLDOUT", "EXPERT_HOLDOUT"}
        #: Modules allowed to name a partition, and why.
        permitted = {
            "gate_status.py": "reports which blockers stand",
            "labels.py": "holds the section headings the page renders",
            os.path.join("view_models", "pages.py"):
                "maps a feed section to its heading",
            "validation_feed.py": "reads the committed public feed",
        }
        for path in web_modules():
            relative = os.path.relpath(path, REPO_ROOT)
            tail = relative.split(os.sep, 2)[-1]
            if tail in permitted:
                continue
            literals = {node.value for node in ast.walk(tree(path))
                        if isinstance(node, ast.Constant)
                        and isinstance(node.value, str)}
            with self.subTest(module=relative):
                self.assertEqual(literals & forbidden, set())

    def test_the_interface_holds_no_holdout_case_or_payload(self):
        """The successor assertion, stated directly.

        Naming a partition is allowed. Holding a case from one is not, and
        neither is being able to fetch one: the feed adapter reads a committed
        aggregate file and has no client, no port and no storage root.
        """
        import apps.web.validation_feed as adapter
        feed = adapter.load_dashboard_feed()
        self.assertIsNotNone(feed)
        payload = repr(feed)
        for forbidden in ("case_id", "payload", "phenotype", "medication",
                          "expected_"):
            with self.subTest(term=forbidden):
                self.assertNotIn(forbidden, payload)
        for imported in identifiers_of(module_path("validation_feed.py")):
            with self.subTest(identifier=imported):
                self.assertNotIn("restricted", imported.lower())

    def test_no_metric_is_computed_anywhere_in_the_interface(self):
        forbidden = {"concordance", "accuracy", "pass_rate", "precision",
                     "recall", "f1_score", "percentage", "percent"}
        for path in web_modules():
            with self.subTest(module=os.path.relpath(path, REPO_ROOT)):
                self.assertEqual(identifiers_of(path) & forbidden, set())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class TestTheSyntheticWorldIsOwnedExplicitly(unittest.TestCase):
    """Who closes the world, and how the answer stays visible.

    ``SyntheticAssessmentWorld`` allocates a temporary directory in its
    constructor and frees it in ``close()``. It is a plain object with a
    lifetime, not a context manager, and every call site in this repository
    registers the cleanup on the test case instead:

        world = synthetic_world()
        self.addCleanup(world.close)

    Fourteen tests in ``tests/integration/web/test_asgi_web.py`` were written
    as ``with synthetic_world() as world:``. That is not a smaller mistake
    than a leak - it is a TypeError at the top of every one of them, so all
    fourteen errored without ever reaching the assertion they existed to make,
    and the file looked like a suite while testing nothing.

    The repair was to use the idiom the other twenty call sites already use.
    These tests keep it that way: the ``with`` form fails here, at the file
    that introduced it, rather than fourteen times somewhere else. The fix for
    a failure here is the two-line idiom above - **not** adding ``__enter__``
    and ``__exit__`` to the world, which would make one shared fixture support
    two ownership models and leave nobody able to tell which one a given test
    is relying on.
    """

    #: Every module that builds a synthetic world, from either support module.
    ROOTS = ("tests/unit", "tests/integration", "tests/fixtures")

    def _test_sources(self):
        found = []
        for root in self.ROOTS:
            base = os.path.join(REPO_ROOT, *root.split("/"))
            for directory, dirs, files in os.walk(base):
                dirs[:] = [name for name in dirs if name != "__pycache__"]
                for name in sorted(files):
                    if name.endswith(".py"):
                        path = os.path.join(directory, name)
                        with io.open(path, encoding="utf-8") as handle:
                            found.append((path, handle.read()))
        return found

    def test_the_world_is_not_a_context_manager(self):
        from tests.unit.web._support import synthetic_world

        world = synthetic_world()
        self.addCleanup(world.close)
        self.assertTrue(hasattr(world, "close"))
        self.assertFalse(hasattr(world, "__enter__"),
                         "the world grew a context-manager protocol; either "
                         "this test or every call site is now wrong")
        self.assertFalse(hasattr(world, "__exit__"))

    def test_no_test_module_uses_it_as_a_context_manager(self):
        """Read as syntax trees, not as text.

        A textual scan fails on this very file, which has to name the pattern
        in order to forbid it - the same trap that a docstring explaining a
        prohibition sets for every other check in this module. So the ``with``
        items are read from the AST and the call target is matched by name.
        """
        offenders = []
        for path, text in self._test_sources():
            try:
                parsed = ast.parse(text, filename=path)
            except SyntaxError:  # pragma: no cover - would fail elsewhere
                continue
            for node in ast.walk(parsed):
                if not isinstance(node, (ast.With, ast.AsyncWith)):
                    continue
                for item in node.items:
                    call = item.context_expr
                    if isinstance(call, ast.Call) and isinstance(
                            call.func, ast.Name) and \
                            call.func.id == "synthetic_world":
                        offenders.append("%s:%d" % (
                            os.path.relpath(path, REPO_ROOT), node.lineno))
        self.assertEqual(offenders, [],
                         "use the factory plus addCleanup(world.close) "
                         "instead")

    def test_no_test_module_drives_the_protocol_by_hand(self):
        """``world.__enter__()`` is the same mistake wearing a disguise."""
        offenders = []
        for path, text in self._test_sources():
            try:
                parsed = ast.parse(text, filename=path)
            except SyntaxError:  # pragma: no cover
                continue
            for node in ast.walk(parsed):
                if isinstance(node, ast.Attribute) and node.attr in (
                        "__enter__", "__exit__"):
                    offenders.append("%s:%d" % (
                        os.path.relpath(path, REPO_ROOT), node.lineno))
        self.assertEqual(offenders, [])

    def test_every_module_that_builds_one_also_closes_it(self):
        """A world built and never closed leaves a temporary directory behind.

        Checked per module rather than per call, because a module may build
        several worlds in one helper. What matters is that a module which
        constructs one also names ``close`` somewhere.
        """
        for path, text in self._test_sources():
            if "synthetic_world(" not in text:
                continue
            relative = os.path.relpath(path, REPO_ROOT)
            if relative.endswith("_support.py"):
                continue  # defines the factory; does not own an instance
            with self.subTest(module=relative):
                self.assertIn("close", text,
                              "%s builds a synthetic world and never closes "
                              "one" % relative)
