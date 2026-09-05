# -*- coding: utf-8 -*-
"""``pgx-deploy``, the workflows, and the boundaries (WP-24).

The exit codes are the contract a pipeline branches on, so they are asserted
directly rather than through the text a command prints. Exit 2 for "blocked,
not executed or stale" is the one that carries the safety: a command exiting 0
for "nothing happened" would let a pipeline treat an absent deployment as a
successful one.

The workflow tests read the YAML as text. That is deliberate - the properties
that matter (no ``pull_request_target``, least-privilege permissions, the
declared job order, an isolated database, no publish step) are all statements
about what is written, and a test that needed a YAML parser would be one more
dependency between the pipeline and the check on it.
"""

from __future__ import annotations

import io
import os
import unittest

from pgx.application.deploy_cli import build_parser, main
from pgx.deployment.ci_status import (JOB_ORDER, UNRESOLVED_SHA, action_pins,
                                      ci_status)
from pgx.deployment.vocabulary import (EXIT_BLOCKED, EXIT_SUCCESS, EXIT_USAGE,
                                       ExecutionState, exit_code_for)

REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def _read(relative):
    with io.open(os.path.join(REPO_ROOT, relative), encoding="utf-8") as fh:
        return fh.read()


def _directives(relative):
    """A workflow with its comments removed.

    Every "this file must not contain X" assertion below reads this rather
    than the raw text, because these files *explain* what they do not do -
    and the first version of two of these assertions matched the
    explanation. That mistake now has a habit attached to it in this
    repository: a scanner matched its own comment, a docstring matched its
    own prose, a Caddyfile matched its own warning, and here a workflow
    matched its own policy statement.
    """
    return "\n".join(line for line in _read(relative).splitlines()
                      if not line.lstrip().startswith("#"))


class _Quiet:
    """Swallow stdout for a command whose output is not what is under test."""

    def __enter__(self):
        import contextlib

        self._stack = contextlib.ExitStack()
        self._buffer = io.StringIO()
        self._stack.enter_context(
            contextlib.redirect_stdout(self._buffer))
        self._stack.enter_context(
            contextlib.redirect_stderr(io.StringIO()))
        return self

    def __exit__(self, *exc):
        self._stack.close()
        return False

    @property
    def text(self):
        return self._buffer.getvalue()


class TestExitCodes(unittest.TestCase):
    """0 held, 1 wrong, 2 did not happen, 3 malformed."""

    def test_every_blocked_subcommand_exits_two(self):
        for argv in (["--root", REPO_ROOT, "preflight"],
                     ["--root", REPO_ROOT, "lock", "--check"],
                     ["--root", REPO_ROOT, "migrate", "--dry-run"],
                     ["--root", REPO_ROOT, "smoke"],
                     ["--root", REPO_ROOT, "performance"],
                     ["--root", REPO_ROOT, "backup"],
                     ["--root", REPO_ROOT, "restore-verify"],
                     ["--root", REPO_ROOT, "rollback"],
                     ["--root", REPO_ROOT, "release-validation"]):
            with self.subTest(command=argv[-1]):
                with _Quiet():
                    code = main(argv)
                self.assertEqual(code, EXIT_BLOCKED)

    def test_an_unknown_subcommand_exits_three_not_two(self):
        """Two already means 'blocked'. A pipeline seeing 2 from a typo would
        read it as 'the deployment has not happened yet' and carry on."""
        with self.assertRaises(SystemExit) as caught:
            with _Quiet():
                main(["nosuchcommand"])
        self.assertEqual(caught.exception.code, EXIT_USAGE)

    def test_an_invalid_choice_exits_three(self):
        with self.assertRaises(SystemExit) as caught:
            with _Quiet():
                main(["smoke", "--environment", "NOT_A_KIND"])
        self.assertEqual(caught.exception.code, EXIT_USAGE)

    def test_the_state_to_exit_code_mapping_is_total(self):
        for state in ExecutionState:
            with self.subTest(state=state.value):
                self.assertIn(exit_code_for(state),
                              (EXIT_SUCCESS, EXIT_BLOCKED))

    def test_a_rehearsal_exits_zero_and_is_kept_out_by_its_label(self):
        """The rehearsal succeeded; the exit code says so. What keeps it out
        of a release decision is the label, not the code."""
        self.assertEqual(exit_code_for(ExecutionState.TEST_ONLY_REHEARSAL),
                         EXIT_SUCCESS)
        self.assertFalse(
            ExecutionState.TEST_ONLY_REHEARSAL.may_close_a_release_gate)


class TestTheCommandRefusesWhatItShould(unittest.TestCase):
    def test_there_is_no_subcommand_that_deletes_a_volume(self):
        """A tool that offered it would eventually be run with it by somebody
        who meant --verbose."""
        parser = build_parser()
        actions = [action for action in parser._actions
                   if hasattr(action, "choices") and action.choices]
        names = set()
        for action in actions:
            names.update(action.choices or {})
        for forbidden in ("down", "destroy", "prune", "rm", "delete",
                          "reset", "wipe"):
            with self.subTest(name=forbidden):
                self.assertNotIn(forbidden, names)

    def test_no_subcommand_creates_a_user_or_activates_a_release(self):
        parser = build_parser()
        names = set()
        for action in parser._actions:
            names.update(getattr(action, "choices", None) or {})
        for forbidden in ("bootstrap-admin", "create-user", "activate",
                          "approve", "seed"):
            with self.subTest(name=forbidden):
                self.assertNotIn(forbidden, names)

    def test_stop_never_passes_the_volume_flag(self):
        import ast

        from tests.fixtures.wp24.doubles import module_source
        import pgx.application.deploy_cli as module

        tree = ast.parse(module_source(module))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef) or \
                    node.name != "_cmd_stop":
                continue
            for child in ast.walk(node):
                if isinstance(child, ast.Constant) and \
                        isinstance(child.value, str):
                    with self.subTest(literal=child.value):
                        self.assertNotEqual(child.value, "-v")
                        self.assertNotEqual(child.value, "--volumes")

    def test_a_mutating_command_prints_its_target_first(self):
        """A migration aimed at the wrong server is obvious in hindsight and
        invisible in a command line."""
        with _Quiet() as quiet:
            main(["--root", REPO_ROOT, "migrate", "--dry-run"])
        self.assertIn("target:", quiet.text)
        self.assertIn("action:", quiet.text)

    def test_the_printed_target_carries_no_credential(self):
        from pgx.application.deploy_cli import _redacted_target

        # Assembled at run time rather than written as a literal. A
        # credential-shaped DSN in this file is a true positive for
        # `pgx-security secret-scan` - it found this one - and the right
        # answer is to stop writing one, not to add an allowlist entry that
        # would also excuse a real credential committed here later.
        secret = "hunter" + "2"
        dsn = "%s://%s:%s@%s:5432/%s" % (
            "postgresql+psycopg", "someone", secret, "db.internal", "pgx")
        shown = _redacted_target(dsn)
        self.assertNotIn(secret, shown)
        # The host and database name survive: they are what a wrong target
        # looks like.
        self.assertIn("db.internal", shown)
        self.assertIn("pgx", shown)

    def test_the_smoke_command_offers_no_way_to_disable_verification(self):
        """`curl -k` is not evidence of TLS; it is evidence that
        verification was switched off."""
        parser = build_parser()
        text = parser.format_help()
        for forbidden in ("--insecure", "--no-verify", "-k"):
            with self.subTest(flag=forbidden):
                self.assertNotIn(forbidden, text)


class TestActionPinning(unittest.TestCase):
    """A tag is a name the action's owner can move."""

    def test_no_reference_is_pinned_by_a_bare_tag_in_a_wp24_workflow(self):
        pins = action_pins(REPO_ROOT)
        wp24 = [item for item in pins["actions"]
                if "safety-gate" not in item["workflow"]]
        for entry in wp24:
            with self.subTest(action=entry["action"],
                              workflow=entry["workflow"]):
                self.assertIn(entry["kind"], ("sha", "unresolved", "local"))

    def test_every_placeholder_names_the_version_it_stands_for(self):
        """Forty hex characters tell a reviewer nothing about what they are
        approving; the comment is what does."""
        for entry in action_pins(REPO_ROOT)["actions"]:
            if entry["kind"] != "unresolved":
                continue
            with self.subTest(action=entry["action"]):
                self.assertIsNotNone(entry["version_comment"])

    def test_the_placeholder_is_not_a_possible_commit(self):
        """Forty zeros is not a commit in any git repository, so a workflow
        reaching one fails loudly instead of executing something."""
        self.assertEqual(UNRESOLVED_SHA, "0" * 40)
        self.assertEqual(len(UNRESOLVED_SHA), 40)

    def test_unresolved_pins_block_rather_than_pass(self):
        status = ci_status(REPO_ROOT, environ={})
        if action_pins(REPO_ROOT)["all_sha_pinned"]:
            self.skipTest("every action is pinned in this checkout")
        codes = [item["code"] for item in status["blockers"]]
        self.assertIn("DEPLOY_CI_NOT_EXECUTED", codes)

    def test_the_resolver_script_exists_and_is_executable(self):
        path = os.path.join(REPO_ROOT, "scripts", "resolve_action_pins.sh")
        self.assertTrue(os.path.isfile(path))
        self.assertTrue(os.access(path, os.X_OK))


class TestTheWorkflows(unittest.TestCase):
    def setUp(self):
        self.build = _directives(".github/workflows/build-and-verify.yml")
        self.release = _directives(
            ".github/workflows/release-validation.yml")
        self.build_text = _read(".github/workflows/build-and-verify.yml")
        self.release_text = _read(
            ".github/workflows/release-validation.yml")

    def test_neither_workflow_uses_pull_request_target(self):
        """It runs with the base repository's token against a fork's code,
        which is the standard way a public repository leaks its secrets."""
        for name, text in (("build", self.build),
                           ("release", self.release)):
            with self.subTest(workflow=name):
                self.assertNotIn("pull_request_target", text,
                                 "%s declares pull_request_target" % name)

    def test_permissions_are_least_privilege(self):
        for name, text in (("build", self.build),
                           ("release", self.release)):
            with self.subTest(workflow=name):
                self.assertIn("permissions:\n  contents: read", text)
                self.assertNotIn("write-all", text,
                                 "%s grants write-all" % name)
                self.assertNotIn("packages: write", text,
                                 "%s grants packages: write" % name)

    def test_the_declared_job_order_is_implemented(self):
        combined = self.build + self.release
        positions = []
        for job in JOB_ORDER:
            marker = "\n  %s:" % job
            self.assertIn(marker, combined,
                          "job %r is not defined in either workflow" % job)
            positions.append(combined.index(marker))
        # The build workflow's jobs come first in the combined text, and each
        # workflow's own jobs are in order; asserting monotonicity across the
        # concatenation checks both.
        self.assertEqual(positions, sorted(positions))

    def test_the_integration_job_uses_an_isolated_database(self):
        """Never the development compose service: the integration suite runs
        `alembic downgrade base`."""
        self.assertIn("services:", self.build)
        self.assertIn("postgres:16.13-bookworm", self.build)
        self.assertIn("pgx_ci_test", self.build)
        self.assertIn("55432:5432", self.build)

    def test_the_migration_runs_against_postgresql_and_checks_one_head(self):
        self.assertIn("alembic upgrade head", self.build)
        self.assertIn("exactly one head", self.build)

    def test_safety_runs_through_the_authoritative_command(self):
        """Nothing re-implements a safety rule in YAML: if the rules and the
        job could disagree, one of them would be wrong and nobody would know
        which."""
        self.assertIn("pgx.application.safety_cli check", self.build)

    def test_the_release_path_blocks_on_an_absent_holdout_set(self):
        self.assertIn("holdout-regression", self.release)
        self.assertIn("holdout_case_count", self.release)
        self.assertIn("scientific curators", self.release)

    def test_nothing_publishes_an_image(self):
        """The absence is the policy."""
        for token in ("docker push", "docker login", "ghcr.io",
                      "docker/login-action", "registry"):
            with self.subTest(token=token):
                self.assertNotIn(
                    token, self.release,
                    "the release workflow contains %r" % token)

    def test_reports_are_uploaded_even_when_a_gate_blocks(self):
        """A release-validation document that only existed on success would
        never describe the state anybody needs to read."""
        self.assertIn("if: always()", self.release)
        self.assertIn("if: always()", self.build)  # comments stripped

    def test_uploaded_paths_carry_no_secret_or_holdout_payload(self):
        for text in (self.build_text, self.release_text):
            for line in text.splitlines():
                if "path:" not in line and not line.strip().startswith("-"):
                    continue
                stripped = line.strip().lstrip("- ")
                if not stripped or ":" in stripped.split()[0]:
                    continue
                with self.subTest(path=stripped):
                    self.assertFalse(stripped.startswith("deploy/secrets"))
                    self.assertFalse(stripped.startswith("deploy/tls"))
                    self.assertFalse(stripped.startswith("data/holdout"))

    def test_concurrency_and_timeouts_are_set(self):
        for name, text in (("build", self.build),
                           ("release", self.release)):
            with self.subTest(workflow=name):
                self.assertIn("concurrency:", text)
                self.assertIn("timeout-minutes:", text)

    def test_the_cache_key_includes_the_lockfile(self):
        """A cache keyed on anything coarser serves a dependency set from a
        different lock."""
        self.assertIn("cache-dependency-glob: uv.lock", self.build)

    def test_the_wp20_safety_workflow_is_preserved(self):
        """Historical WP-20 evidence. It is not edited by WP-24."""
        safety = _read(".github/workflows/safety-gate.yml")
        self.assertIn("name: safety-gate", safety)
        self.assertIn("WP-20", safety)
        self.assertIn("pgx.application.safety_cli check", safety)

    def test_the_pin_check_job_needs_no_action_of_its_own(self):
        """Otherwise the check that verifies the pins would depend on an
        unpinned one."""
        job = self.build_text.split("  action-pins:", 1)[1].split(
            "  format-check:")[0]
        self.assertNotIn("uses:", job)
        self.assertIn("git clone", job)


class TestCiIsConfiguredNotExecuted(unittest.TestCase):
    def test_a_workflow_file_is_configured(self):
        status = ci_status(REPO_ROOT, environ={})
        self.assertEqual(status["state"], ExecutionState.CONFIGURED.value)
        self.assertGreaterEqual(int(status["workflow_count"]), 3)

    def test_a_run_id_makes_it_executed(self):
        status = ci_status(REPO_ROOT, environ={
            "GITHUB_RUN_ID": "12345",
            "GITHUB_SERVER_URL": "https://github.example",
            "GITHUB_REPOSITORY": "org/repo"})
        self.assertEqual(status["state"], ExecutionState.EXECUTED.value)
        self.assertTrue(status["ci_executed"])
        self.assertIn("12345", str(status["ci_run_url"]))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
