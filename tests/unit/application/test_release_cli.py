# -*- coding: utf-8 -*-
"""``pgx-release``: argument contract, exit codes, and credential safety (WP-03).

The CLI is the operator-facing surface, so two things about it are worth
testing without a database, and both are tested here.

**Exit codes are an interface.** A deploy script branches on them. If
"incompatible release" and "database unreachable" shared a code, an operator
would retry the wrong thing. Each code is asserted distinct and stable.

**No credential reaches any output.** The CLI is run for real - argv in, stdout
and stderr captured - with an environment holding a password in the URL, and
the captured text is searched for it.

The infrastructure imports are deliberately inside functions in the CLI, which
is what lets these tests run with no SQLAlchemy installed.

Standard library only.
"""

from __future__ import annotations

import ast
import contextlib
import io
import os
import unittest

from pgx.application import release_cli
from pgx.application.release_cli import (
    EXIT_CONFIGURATION_FAILURE, EXIT_NOT_ACTIVATABLE, EXIT_OK,
    EXIT_RELEASE_NOT_FOUND, EXIT_STALE_POINTER, build_parser, main,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

PASSWORD = "cli-s3cret-pw"
QUERY_SECRET = "cli-qu3ry-secret"
URL = ("postgresql+psycopg://pgx_dev:%s@localhost:5432/pgx_dev?sslpassword=%s"
       % (PASSWORD, QUERY_SECRET))


def _run(argv, environment=None):
    """Run the CLI, returning ``(exit_code, combined output)``."""
    stdout, stderr = io.StringIO(), io.StringIO()
    previous = dict(os.environ)
    if environment is not None:
        os.environ.update(environment)
    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(argv)
    finally:
        os.environ.clear()
        os.environ.update(previous)
    return code, stdout.getvalue() + stderr.getvalue()


class TestTheArgumentContract(unittest.TestCase):

    def setUp(self):
        self.parser = build_parser()

    @contextlib.contextmanager
    def _quiet(self):
        """argparse prints usage to stderr on a rejection; keep it out of the
        test log so a passing run stays readable."""
        with contextlib.redirect_stderr(io.StringIO()):
            yield

    def test_every_declared_subcommand_exists(self):
        choices = self.parser._subparsers._group_actions[0].choices
        self.assertEqual(
            sorted(choices),
            ["activate", "history", "inspect", "register-legacy-baseline",
             "rollback", "show-active", "validate"])

    def test_a_subcommand_is_required(self):
        with self._quiet(), self.assertRaises(SystemExit):
            self.parser.parse_args([])

    def test_mutating_commands_require_an_actor_and_a_reason(self):
        for command in ("activate", "rollback"):
            with self.subTest(command=command):
                with self._quiet(), self.assertRaises(SystemExit):
                    self.parser.parse_args([command, "--public-id",
                                            "PGX-REL-20260829-001"])

    def test_a_release_must_be_named(self):
        for command in ("inspect", "validate"):
            with self.subTest(command=command):
                with self._quiet(), self.assertRaises(SystemExit):
                    self.parser.parse_args([command])

    def test_a_release_cannot_be_named_twice(self):
        with self._quiet(), self.assertRaises(SystemExit):
            self.parser.parse_args(["inspect", "--release-id", "x",
                                    "--public-id", "PGX-REL-20260829-001"])

    def test_the_database_url_is_never_an_argument(self):
        """A URL in argv lands in the shell history and the process list."""
        source = _cli_source()
        self.assertNotIn('"--database-url"', source)
        self.assertNotIn("'--database-url'", source)
        tree = ast.parse(source)
        options = {node.args[0].value for node in ast.walk(tree)
                   if isinstance(node, ast.Call)
                   and getattr(node.func, "attr", None) == "add_argument"
                   and node.args and isinstance(node.args[0], ast.Constant)}
        for option in options:
            self.assertNotIn("url", option.replace("url-env", ""),
                             "%s looks like it accepts a URL" % option)

    def test_only_environment_variable_names_are_accepted(self):
        arguments = self.parser.parse_args(
            ["--database-url-env", "TEST_DATABASE_URL", "show-active"])
        self.assertEqual(arguments.database_url_env, "TEST_DATABASE_URL")
        with self._quiet(), self.assertRaises(SystemExit):
            self.parser.parse_args(
                ["--database-url-env", "postgresql://u:p@h/d", "show-active"])


class TestExitCodesAreDistinct(unittest.TestCase):

    def test_every_code_is_unique(self):
        codes = [EXIT_OK, EXIT_NOT_ACTIVATABLE, EXIT_CONFIGURATION_FAILURE,
                 EXIT_RELEASE_NOT_FOUND, EXIT_STALE_POINTER]
        self.assertEqual(len(set(codes)), len(codes))

    def test_success_is_zero_and_nothing_else_is(self):
        self.assertEqual(EXIT_OK, 0)
        for code in (EXIT_NOT_ACTIVATABLE, EXIT_CONFIGURATION_FAILURE,
                     EXIT_RELEASE_NOT_FOUND, EXIT_STALE_POINTER):
            self.assertNotEqual(code, 0)

    def test_a_missing_database_url_is_a_configuration_failure(self):
        environment = {key: "" for key in ("DATABASE_URL", "TEST_DATABASE_URL")}
        code, _ = _run(["show-active"], environment)
        self.assertEqual(code, EXIT_CONFIGURATION_FAILURE)

    def test_a_rejected_url_is_a_configuration_failure(self):
        code, _ = _run(["show-active"], {"DATABASE_URL": "sqlite:///pgx.db"})
        self.assertEqual(code, EXIT_CONFIGURATION_FAILURE)

    def test_the_failure_output_is_machine_readable(self):
        import json

        _, output = _run(["show-active"], {"DATABASE_URL": "sqlite:///pgx.db"})
        document = json.loads(output.strip().splitlines()[-1])
        self.assertEqual(document["error"], "CONFIGURATION_FAILURE")
        self.assertIn("detail", document)


class TestNoCredentialReachesTheOutput(unittest.TestCase):
    """Run the CLI for real and search its output for the secret."""

    def test_a_configuration_failure_carries_no_credential(self):
        code, output = _run(["show-active"],
                            {"DATABASE_URL": URL.replace("+psycopg", "+asyncpg")})
        self.assertEqual(code, EXIT_CONFIGURATION_FAILURE)
        self.assertNotIn(PASSWORD, output)
        self.assertNotIn(QUERY_SECRET, output)

    def test_a_driver_failure_carries_no_credential(self):
        """psycopg is absent here, so this exercises the import-failure path."""
        code, output = _run(["show-active"], {"DATABASE_URL": URL})
        self.assertEqual(code, EXIT_CONFIGURATION_FAILURE)
        self.assertNotIn(PASSWORD, output)
        self.assertNotIn(QUERY_SECRET, output)

    def test_every_failure_path_routes_through_the_sanitizer(self):
        tree = ast.parse(_cli_source())
        unsanitized = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if getattr(node.func, "id", None) != "_fail":
                continue
            rendered = ast.unparse(node)
            if "sanitize_message" not in rendered:
                unsanitized.append(rendered.splitlines()[0])
        # The only exempt calls are those whose text is a fixed literal built
        # by the CLI itself, containing nothing from the environment.
        for call in unsanitized:
            self.assertTrue(
                any(token in call for token in ("RELEASE_NOT_FOUND",
                                                "UNKNOWN_COMMAND")),
                "unsanitized failure output: %s" % call)

    def test_the_cli_never_prints_the_raw_config_url(self):
        self.assertNotIn("config.url", _cli_source())


class TestTheCliDelegatesRatherThanReimplements(unittest.TestCase):
    """A CLI that re-implemented a rule would eventually disagree with the
    service, and the disagreement would surface as a release that validated on
    the command line and failed in production."""

    def test_it_defines_no_compatibility_logic(self):
        source = _cli_source()
        for token in ("CompatibilityCode.", "DatasetStatus.PUBLISHED",
                      "RulesetStatus.FROZEN", "RuleStatus.VALIDATED"):
            self.assertNotIn(token, source)

    def test_it_calls_the_service_for_every_mutating_command(self):
        tree = ast.parse(_cli_source())
        called = {node.func.attr for node in ast.walk(tree)
                  if isinstance(node, ast.Call)
                  and getattr(node.func, "attr", None)}
        for method in ("activate_release", "rollback_release", "validate_release",
                       "get_active_release", "release_history"):
            self.assertIn(method, called)

    def test_it_computes_no_manifest_digest_of_its_own(self):
        self.assertNotIn("sha256", _cli_source())

    def test_infrastructure_imports_stay_inside_functions(self):
        """That is what lets this suite run with no SQLAlchemy installed."""
        tree = ast.parse(_cli_source())
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = getattr(node, "module", "") or ""
                self.assertFalse(module.startswith("pgx.infrastructure"),
                                 "%s is imported at module level" % module)

    def test_the_wrapper_script_only_delegates(self):
        path = os.path.join(REPO_ROOT, "scripts", "release.py")
        with io.open(path, encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn("pgx.application.release_cli", source)
        lines = [line for line in source.splitlines()
                 if line.strip() and not line.strip().startswith("#")]
        self.assertLess(len(lines), 25)

    def test_the_console_entry_point_is_declared(self):
        path = os.path.join(REPO_ROOT, "pyproject.toml")
        with io.open(path, encoding="utf-8") as handle:
            source = handle.read()
        self.assertIn('pgx-release = "pgx.application.release_cli:main"', source)


def _cli_source() -> str:
    path = os.path.join(REPO_ROOT, "pgx", "application", "release_cli.py")
    with io.open(path, encoding="utf-8") as handle:
        return handle.read()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
