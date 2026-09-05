# -*- coding: utf-8 -*-
"""Packaging, compose and environment consistency (WP-02 corrective).

Four findings are proven here without a network, a build backend, or Docker.

**Console scripts.** ``[project.scripts]`` pointed at ``scripts.db_seed:main``,
but only the ``pgx`` package is put in the wheel, so ``pgx-db-seed`` would have
raised ``ModuleNotFoundError`` on any installed copy. The entry points must
resolve to modules that actually ship, and the module named must really define
``main``.

**README.** ``readme = "README.md"`` referenced a file that did not exist, which
makes the wheel unbuildable. Checked as a file on disk, not as a promise.

**No duplicated logic.** ``scripts/db_seed.py`` must be a thin wrapper, not a
second copy of the seed that can drift from the packaged one.

**Compose / .env agreement.** The compose file created only ``pgx_dev`` while
``.env.example`` pointed ``TEST_DATABASE_URL`` at ``pgx_test`` on a port nothing
published, so the documented test setup could not work. The two files are
parsed and compared here.

Standard library only. The TOML/YAML reads are deliberately narrow text and
``tomllib`` parses; no third-party parser is required.
"""

from __future__ import annotations

import ast
import io
import os
import re
import unittest

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # Python 3.10 - a narrow text parser is used instead
    tomllib = None

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))


def _read(relative: str) -> str:
    with io.open(os.path.join(REPO_ROOT, relative), encoding="utf-8") as handle:
        return handle.read()


def _exists(relative: str) -> bool:
    return os.path.isfile(os.path.join(REPO_ROOT, relative))


def _toml_section(name: str) -> dict:
    """Return one flat TOML table as ``{key: raw string}``.

    ``tomllib`` is used where available. On Python 3.10 a narrow text parser
    reads the same table, so this suite never *skips*: a skipped structural
    check is indistinguishable from a passing one in a report, and WP-02 is
    required to state real results.
    """
    if tomllib is not None:
        with io.open(os.path.join(REPO_ROOT, "pyproject.toml"), "rb") as handle:
            document = tomllib.load(handle)
        node = document
        for part in name.split("."):
            node = node.get(part, {})
        return node

    # Requirements contain both commas ("fastapi>=0.110,<1.0") and closing
    # brackets ("uvicorn[standard]"), so neither a comma split nor a search
    # for "]" can be used to read them. Quoted strings are extracted instead,
    # and an array ends at the first "]" that is *not* inside quotes. A
    # sloppier parser here would return a plausible-looking wrong list and
    # make the checks below pass without checking anything.
    _STRING = re.compile(r'"([^"]*)"|\'([^\']*)\'')

    def _strings(text: str) -> list:
        return [double or single
                for double, single in _STRING.findall(text)]

    def _unquoted(text: str) -> str:
        return _STRING.sub("", text).split("#")[0]

    values, in_section = {}, False
    pending_key, pending_text = None, ""
    for line in _read("pyproject.toml").splitlines():
        stripped = line.strip()

        if pending_key is not None:
            pending_text += " " + line
            if "]" in _unquoted(line):
                values[pending_key] = _strings(pending_text)
                pending_key, pending_text = None, ""
            continue

        if stripped.startswith("[") and stripped.endswith("]") \
                and "=" not in stripped:
            in_section = stripped == "[%s]" % name
            continue
        if not in_section or not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            continue
        key, _, raw = stripped.partition("=")
        key, raw = key.strip(), raw.strip()
        if raw.startswith("["):
            if "]" in _unquoted(raw[1:]):
                values[key] = _strings(raw)
            else:
                pending_key, pending_text = key, raw
        else:
            values[key] = raw.strip('"')
    return values


def _console_scripts() -> dict:
    return _toml_section("project.scripts")


def _strip_yaml_comments(text: str) -> str:
    """Drop ``#`` comments so prose about a directive is not mistaken for one."""
    cleaned = []
    for line in text.splitlines():
        out, quote = [], None
        for character in line:
            if quote:
                out.append(character)
                if character == quote:
                    quote = None
                continue
            if character in ("'", '"'):
                quote = character
                out.append(character)
                continue
            if character == "#":
                break
            out.append(character)
        cleaned.append("".join(out).rstrip())
    return "\n".join(cleaned)


def _yaml_block(text: str, header: str) -> str:
    """Return the indented block introduced by ``header`` (comments stripped)."""
    lines = _strip_yaml_comments(text).splitlines()
    for index, line in enumerate(lines):
        if line.strip() == header:
            indent = len(line) - len(line.lstrip())
            block = [line]
            for following in lines[index + 1:]:
                if following.strip() and (
                        len(following) - len(following.lstrip())) <= indent:
                    break
                block.append(following)
            return "\n".join(block)
    return ""


class TestConsoleScriptsResolveInsideThePackage(unittest.TestCase):

    def setUp(self):
        self.scripts = _console_scripts()

    def test_every_entry_point_is_declared(self):
        self.assertEqual(
            sorted(self.scripts),
            ["pgx-api",
             # WP-23.
             "pgx-audit", "pgx-auth",
             "pgx-benchmark", "pgx-curation-protocol",
             "pgx-dataset", "pgx-db-check", "pgx-db-seed",
             # WP-24. The one documented deployment command. Fifteen
             # subcommands, none of which deletes a volume, creates a user,
             # activates a release or approves anything.
             "pgx-deploy",
             "pgx-evidence",
             # WP-22.
             "pgx-expert-review",
             "pgx-ingest-clinpgx", "pgx-normalize", "pgx-release",
             "pgx-safety",
             # WP-23.
             "pgx-security",
             "pgx-source-policy",
             # WP-25. Reads the committed evidence and reports what it
             # supports. No subcommand signs, approves or executes anything,
             # and there is no override flag under any spelling.
             "pgx-ths6",
             "pgx-validation",
             "pgx-verify", "pgx-web"])

    def test_no_entry_point_targets_the_unpackaged_scripts_directory(self):
        for name, target in self.scripts.items():
            with self.subTest(script=name):
                self.assertFalse(
                    target.startswith("scripts."),
                    "%s targets %r, which is not in the wheel" % (name, target))

    def test_every_entry_point_targets_a_module_that_exists(self):
        """Every target is in a shipped package and is a real file.

        ``apps.`` joined ``pgx.`` here at WP-16: the API entry point starts the
        ASGI application, which lives in ``apps`` because ``apps`` may import
        ``pgx`` and never the reverse. Both are in the wheel, which is what
        makes either importable after an install.
        """
        shipped = tuple(_toml_section("tool.hatch.build.targets.wheel")
                        ["packages"])
        for name, target in self.scripts.items():
            with self.subTest(script=name):
                module = target.split(":", 1)[0]
                self.assertTrue(
                    module.startswith(tuple(package + "."
                                            for package in shipped)),
                    "%s targets %s, which is outside the shipped packages %s"
                    % (name, module, list(shipped)))
                self.assertTrue(_exists(module.replace(".", "/") + ".py"),
                                "%s: %s is not a file" % (name, module))

    def test_every_entry_point_function_is_actually_defined(self):
        for name, target in self.scripts.items():
            with self.subTest(script=name):
                module, _, function = target.partition(":")
                tree = ast.parse(_read(module.replace(".", "/") + ".py"))
                defined = {node.name for node in tree.body
                           if isinstance(node, ast.FunctionDef)}
                self.assertIn(function, defined,
                              "%s() is not defined in %s" % (function, module))

    def test_only_the_v2_packages_are_shipped(self):
        """``pgx`` and, since WP-16, ``apps``. Nothing else.

        The seven root-level legacy scripts stay out of the wheel, which is
        what stops any of them from being importable as a project module.
        """
        wheel = _toml_section("tool.hatch.build.targets.wheel")
        self.assertEqual(sorted(wheel["packages"]), ["apps", "pgx"])

    def test_the_api_entry_point_does_not_connect_at_import(self):
        """``pgx-api`` must be able to exist in a deployment with no database.

        Asserted by reading ``apps/api/main.py``: it may build the application
        at module scope, because ``create_app`` opens nothing, and it must
        import the ASGI server inside ``run()`` rather than at module scope, so
        that importing the module does not require a server to be installed.
        """
        tree = ast.parse(_read("apps/api/main.py"))
        top_level_imports = set()
        for node in tree.body:
            if isinstance(node, ast.Import):
                top_level_imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                top_level_imports.add(node.module)
        for forbidden in ("uvicorn", "sqlalchemy", "psycopg", "alembic"):
            self.assertNotIn(forbidden, top_level_imports)

    def test_the_web_entry_point_does_not_connect_at_import(self):
        """``pgx-web`` gets the same treatment, and needs it more.

        The interface has a case catalogue as well as a database, and reading
        the catalogue at import would mean a deployment whose sealed artifact
        is missing could not start at all - instead of starting and serving a
        page that says the catalogue is unavailable, which is the behaviour
        ``WebProvider.cases()`` exists to produce.
        """
        tree = ast.parse(_read("apps/web/main.py"))
        top_level_imports = set()
        for node in tree.body:
            if isinstance(node, ast.Import):
                top_level_imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                top_level_imports.add(node.module)
        for forbidden in ("uvicorn", "sqlalchemy", "psycopg", "alembic"):
            self.assertNotIn(forbidden, top_level_imports)

        # And no module-scope call reads the catalogue. The provider is given
        # the loader itself, so the read happens per request.
        loaders = {"load_development_cases", "parse_catalog", "build_catalog"}
        for node in tree.body:
            for inner in ast.walk(node) if not isinstance(
                    node, (ast.FunctionDef, ast.AsyncFunctionDef)) else ():
                if isinstance(inner, ast.Call) and isinstance(inner.func,
                                                              ast.Name):
                    self.assertNotIn(inner.func.id, loaders)


class TestTheWebExtraDeclaresItsRenderingStack(unittest.TestCase):
    """WP-17. What the interface needs, and what it deliberately does not.

    The interface renders HTML on the server. That makes Jinja2 and, because
    Starlette parses form bodies with it, python-multipart hard requirements
    of the ``web`` extra rather than optional conveniences: a POST route
    without python-multipart fails at request time, which is the worst moment
    to discover a missing package.

    What is *not* here is the point of the rest: no CSS framework, no bundler,
    no JavaScript package and no browser. The two static assets are files in
    the repository, and the browser driver is in the dev group because no
    deployment needs one.
    """

    def setUp(self):
        self.extras = _toml_section("project.optional-dependencies")
        self.dev = _toml_section("dependency-groups")["dev"]

    @staticmethod
    def _names(requirements):
        found = set()
        for entry in requirements:
            name = entry.split(";")[0].strip()
            for separator in ("[", ">", "<", "=", "!", "~", " "):
                name = name.split(separator)[0]
            found.add(name.strip().lower())
        return found

    def test_the_web_extra_exists_and_pins_its_renderer(self):
        self.assertIn("web", self.extras)
        names = self._names(self.extras["web"])
        self.assertIn("jinja2", names)
        self.assertIn("python-multipart", names)

    def test_the_web_extra_can_serve_the_api_it_wraps(self):
        # The combined deployment is one process. Anything the API extra needs
        # to run, the web extra needs too, or `pgx-web` starts an application
        # whose API half cannot answer.
        self.assertLessEqual(self._names(self.extras["api"]),
                             self._names(self.extras["web"]))

    def test_the_web_extra_declares_no_frontend_toolchain(self):
        names = self._names(self.extras["web"])
        for forbidden in ("playwright", "selenium", "node", "nodeenv",
                          "tailwindcss", "django", "flask", "htmx"):
            self.assertNotIn(forbidden, names)

    def test_the_browser_driver_is_a_development_dependency_only(self):
        dev = self._names(self.dev)
        self.assertIn("playwright", dev)
        for extra, requirements in self.extras.items():
            with self.subTest(extra=extra):
                self.assertNotIn("playwright", self._names(requirements))


class TestReadmeExists(unittest.TestCase):
    """``readme = "README.md"`` must point at a real file."""

    def test_the_declared_readme_is_on_disk(self):
        declared = _toml_section("project")["readme"]
        self.assertTrue(_exists(declared), "%s does not exist" % declared)

    def test_the_readme_is_not_a_placeholder(self):
        text = _read("README.md")
        self.assertGreater(len(text.splitlines()), 20)
        self.assertIn("PGx", text)

    def test_the_readme_states_the_prototype_boundary(self):
        lowered = _read("README.md").lower()
        self.assertTrue(
            any(term in lowered for term in ("not a medical device",
                                             "intended purpose",
                                             "safety contract")),
            "README must not read as a clinical product page")


class TestScriptWrappersDoNotDuplicateLogic(unittest.TestCase):
    """The packaged module is the only implementation."""

    WRAPPERS = {"scripts/db_seed.py": "pgx.infrastructure.db.cli_seed",
                "scripts/db_check.py": "pgx.infrastructure.db.cli_check"}

    def test_each_wrapper_delegates_to_the_package(self):
        for wrapper, module in self.WRAPPERS.items():
            with self.subTest(wrapper=wrapper):
                self.assertIn(module, _read(wrapper))

    def test_each_wrapper_is_short(self):
        for wrapper in self.WRAPPERS:
            with self.subTest(wrapper=wrapper):
                lines = [line for line in _read(wrapper).splitlines()
                         if line.strip() and not line.strip().startswith("#")]
                self.assertLess(len(lines), 30,
                                "%s looks like a second implementation" % wrapper)

    def test_no_wrapper_redefines_the_seed_payload(self):
        forbidden = ("_canonical_seed_payload", "SEED_EPOCH", "_COMPARED_FIELDS")
        for wrapper in self.WRAPPERS:
            source = _read(wrapper)
            tree = ast.parse(source)
            defined = {node.name for node in tree.body
                       if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
            assigned = {target.id for node in tree.body
                        if isinstance(node, ast.Assign)
                        for target in node.targets
                        if isinstance(target, ast.Name)}
            for name in forbidden:
                with self.subTest(wrapper=wrapper, name=name):
                    self.assertNotIn(name, defined | assigned)


class TestComposeAndEnvironmentAgree(unittest.TestCase):
    """The documented test setup must be one the compose file can provide."""

    @classmethod
    def setUpClass(cls):
        cls.raw_compose = _read("docker-compose.yml")
        # Directives only: a comment explaining why `container_name:` is absent
        # must not be read as a `container_name:` directive.
        cls.compose = _strip_yaml_comments(cls.raw_compose)
        cls.env = _read(".env.example")

    def _env_value(self, key: str) -> str:
        match = re.search(r"^%s=(.*)$" % re.escape(key), self.env, re.MULTILINE)
        self.assertIsNotNone(match, "%s missing from .env.example" % key)
        return match.group(1).strip()

    def test_a_dedicated_test_service_exists(self):
        self.assertIn("postgres-test:", self.compose)

    def test_the_test_service_creates_a_database_whose_name_marks_it_a_test(self):
        self.assertIn("pgx_test", self.compose)
        match = re.search(r"POSTGRES_DB:\s*\$\{TEST_POSTGRES_DB:-([a-z_]+)\}",
                          self.compose)
        self.assertIsNotNone(match)
        self.assertIn("test", match.group(1))

    def test_the_test_url_targets_the_database_compose_creates(self):
        url = self._env_value("TEST_DATABASE_URL")
        self.assertTrue(url.endswith("/pgx_test"), url)

    def test_the_test_url_targets_the_port_compose_publishes(self):
        url = self._env_value("TEST_DATABASE_URL")
        published = re.search(
            r'"\$\{TEST_POSTGRES_HOST_PORT:-(\d+)\}:5432"', self.compose)
        self.assertIsNotNone(published, "test service publishes no host port")
        self.assertIn(":%s/" % published.group(1), url)

    def test_the_two_services_do_not_share_a_port(self):
        ports = re.findall(r'"\$\{[A-Z_]*POSTGRES_HOST_PORT:-(\d+)\}:5432"',
                           self.compose)
        self.assertEqual(len(ports), 2)
        self.assertNotEqual(ports[0], ports[1])

    def test_the_application_and_test_urls_are_different_databases(self):
        self.assertNotEqual(self._env_value("DATABASE_URL"),
                            self._env_value("TEST_DATABASE_URL"))

    def test_both_urls_name_the_psycopg3_driver(self):
        for key in ("DATABASE_URL", "TEST_DATABASE_URL"):
            with self.subTest(variable=key):
                self.assertTrue(
                    self._env_value(key).startswith("postgresql+psycopg://"))

    def test_the_test_service_uses_disposable_storage(self):
        section = _yaml_block(self.raw_compose, "postgres-test:")
        self.assertTrue(section, "postgres-test service not found")
        self.assertIn("tmpfs:", section)
        self.assertNotIn("pgx_postgres_data", section,
                         "the test service must never mount the dev volume")
        self.assertNotIn("volumes:", section)

    def test_no_container_name_is_pinned(self):
        self.assertNotIn("container_name:", self.compose)

    def test_the_volume_is_not_globally_named(self):
        volumes = _yaml_block(self.raw_compose, "volumes:")
        self.assertTrue(volumes)
        self.assertNotIn("name:", volumes,
                         "a global volume name breaks Compose project isolation")

    def test_no_application_service_is_implied(self):
        for absent in ("fastapi", "uvicorn", "app:", "api:"):
            with self.subTest(token=absent):
                self.assertNotIn(absent, self.compose.lower())

    def test_migrations_are_not_a_container_start_up_side_effect(self):
        self.assertNotIn("command:", self.compose)
        self.assertNotIn("entrypoint:", self.compose)

    def test_the_server_image_is_pinned(self):
        images = re.findall(r"image:\s*(\S+)", self.compose)
        self.assertTrue(images)
        for image in images:
            with self.subTest(image=image):
                self.assertNotIn(":latest", image)
                self.assertRegex(image, r":\d+")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
