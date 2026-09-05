# -*- coding: utf-8 -*-
"""``pgx-source-policy``: what it reports, and what it cannot do.

The most important assertion in this file is a negative one: there is no
subcommand that approves a source. Approval is a human decision recorded in a
reviewed file, in a commit with an author against it, and a command-line flag
is not that.

Exit codes are asserted directly, because CI branches on them: 0 means clean, 1
means blocking findings exist, and 1 is what the repository returns today.
"""

from __future__ import annotations

import ast
import contextlib
import io
import json
import os
import unittest

from pgx.application import source_policy_cli as cli

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
CLI_PATH = os.path.abspath(cli.__file__)
AS_OF = ("--as-of", "2026-08-30T12:00:00Z")


def _run(*argv):
    """Run the CLI, returning (exit_code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class TestValidate(unittest.TestCase):

    def test_it_reports_blocking_findings_and_exits_one(self):
        code, out, _ = _run("validate", *AS_OF)
        self.assertEqual(code, cli.EXIT_BLOCKED)
        document = json.loads(out)
        self.assertGreater(document["summary"]["BLOCKER"], 0)

    def test_it_reports_that_nothing_is_approved(self):
        _, out, _ = _run("validate", *AS_OF)
        self.assertEqual(json.loads(out)["approved_source_count"], 0)

    def test_it_names_the_registry_content_hash(self):
        _, out, _ = _run("validate", *AS_OF)
        self.assertTrue(
            json.loads(out)["registry_content_hash"].startswith("sha256:"))

    def test_the_text_report_is_stable_between_runs(self):
        first = _run("validate", "--text", *AS_OF)[1]
        second = _run("validate", "--text", *AS_OF)[1]
        self.assertEqual(first, second)

    def test_a_missing_registry_is_a_configuration_failure(self):
        code, _, err = _run("validate", "--config",
                            os.path.join(REPO_ROOT, "no-such-file.json"))
        self.assertEqual(code, cli.EXIT_CONFIGURATION_FAILURE)
        self.assertEqual(json.loads(err)["error"], "configuration_failure")


class TestShow(unittest.TestCase):

    def test_it_lists_every_registered_key(self):
        code, out, _ = _run("show", *AS_OF)
        self.assertEqual(code, cli.EXIT_OK)
        document = json.loads(out)
        self.assertIn("cpic.database", document["source_keys"])
        self.assertEqual(document["approved_source_keys"], [])

    def test_it_prints_one_source_with_its_findings(self):
        code, out, _ = _run("show", "cpic.database", *AS_OF)
        self.assertEqual(code, cli.EXIT_BLOCKED)
        document = json.loads(out)
        self.assertEqual(document["source"]["status"], "PENDING_REVIEW")
        self.assertFalse(document["is_approved"])
        self.assertGreater(document["summary"]["BLOCKER"], 0)

    def test_an_unregistered_key_exits_not_found(self):
        code, _, err = _run("show", "no.such.source")
        self.assertEqual(code, cli.EXIT_NOT_FOUND)
        self.assertEqual(json.loads(err)["error"], "source_not_found")

    def test_the_text_form_prints_all_ten_reuse_dimensions(self):
        _, out, _ = _run("show", "cpic.database", "--text", *AS_OF)
        from pgx.scientific.models import REUSE_DIMENSIONS
        for dimension in REUSE_DIMENSIONS:
            self.assertIn(dimension.value, out)


class TestEvaluatePublication(unittest.TestCase):

    def test_a_dataset_on_the_current_policy_is_blocked(self):
        code, out, _ = _run("evaluate-publication", "--dataset", "PGX-DS-TEST",
                            "--source", "cpic.database", *AS_OF)
        self.assertEqual(code, cli.EXIT_BLOCKED)
        self.assertEqual(json.loads(out)["decision"], "BLOCKED")

    def test_the_verdict_carries_a_digest_and_the_intent(self):
        _, out, _ = _run("evaluate-publication", "--dataset", "d",
                         "--source", "cpic.database", *AS_OF)
        document = json.loads(out)
        self.assertTrue(document["eligibility_digest"].startswith("sha256:"))
        self.assertEqual(document["intent"]["source_keys"], ["cpic.database"])

    def test_the_intent_flags_widen_the_required_dimensions(self):
        _, plain, _ = _run("evaluate-publication", "--dataset", "d",
                           "--source", "cpic.database", *AS_OF)
        _, wide, _ = _run("evaluate-publication", "--dataset", "d",
                          "--source", "cpic.database", "--commercial-use", *AS_OF)
        self.assertLess(
            len(json.loads(plain)["intent"]["required_dimensions"]),
            len(json.loads(wide)["intent"]["required_dimensions"]))

    def test_an_unknown_claim_category_is_a_bad_argument(self):
        code, _, err = _run("evaluate-publication", "--dataset", "d",
                            "--claim", "NOT_A_CATEGORY")
        self.assertEqual(code, cli.EXIT_CONFIGURATION_FAILURE)
        self.assertEqual(json.loads(err)["error"], "policy_failure")

    def test_two_runs_produce_the_same_document(self):
        first = _run("evaluate-publication", "--dataset", "d",
                     "--source", "cpic.database", *AS_OF)[1]
        second = _run("evaluate-publication", "--dataset", "d",
                      "--source", "cpic.database", *AS_OF)[1]
        self.assertEqual(first, second)


class TestInventoryLegacy(unittest.TestCase):

    def test_the_checked_in_artefacts_are_current(self):
        code, _, err = _run("inventory-legacy", "--check")
        self.assertEqual(code, cli.EXIT_OK, err)

    def test_it_reports_the_values_it_found(self):
        code, out, _ = _run("inventory-legacy")
        self.assertEqual(code, cli.EXIT_OK)
        document = json.loads(out)
        self.assertGreater(document["totals"]["distinct_values"], 0)
        self.assertEqual(document["unregistered_values"], [])

    def test_it_never_writes_unless_asked(self):
        before = os.path.getmtime(os.path.join(
            REPO_ROOT, "data", "migration", "legacy-source-inventory.json"))
        _run("inventory-legacy")
        after = os.path.getmtime(os.path.join(
            REPO_ROOT, "data", "migration", "legacy-source-inventory.json"))
        self.assertEqual(before, after)


class TestReviewChecklist(unittest.TestCase):

    def test_it_prints_the_steps_a_human_works_through(self):
        code, out, _ = _run("review-checklist")
        self.assertEqual(code, cli.EXIT_OK)
        steps = json.loads(out)["steps"]
        self.assertGreaterEqual(len(steps), 8)
        for step in steps:
            self.assertTrue(step["name"].strip())
            self.assertTrue(step["detail"].strip())

    def test_it_says_the_tool_cannot_approve_anything(self):
        _, out, _ = _run("review-checklist")
        self.assertIn("human act", json.loads(out)["note"])

    def test_the_checklist_puts_evidence_before_the_decision(self):
        _, out, _ = _run("review-checklist")
        details = " ".join(s["detail"] for s in json.loads(out)["steps"])
        self.assertIn("BLOCKED", details)
        self.assertIn("not licensing authority", details)


class TestTheToolCannotApproveASource(unittest.TestCase):
    """The absence is the contract."""

    @classmethod
    def setUpClass(cls):
        with io.open(CLI_PATH, encoding="utf-8") as handle:
            cls.tree = ast.parse(handle.read(), filename=CLI_PATH)

    def _subcommands(self):
        names = set()
        for node in ast.walk(self.tree):
            if (isinstance(node, ast.Call)
                    and getattr(node.func, "attr", None) == "add_parser"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)):
                names.add(node.args[0].value)
        return names

    def test_the_subcommands_are_exactly_the_read_only_five(self):
        self.assertEqual(
            self._subcommands(),
            {"validate", "show", "inventory-legacy", "evaluate-publication",
             "review-checklist"})

    def test_no_subcommand_mutates_policy(self):
        for forbidden in ("approve", "review", "reject", "set-status",
                          "resolve", "grant"):
            with self.subTest(subcommand=forbidden):
                self.assertNotIn(forbidden, self._subcommands())

    def test_the_parser_offers_no_approval_flag(self):
        flags = set()
        for node in ast.walk(self.tree):
            if (isinstance(node, ast.Call)
                    and getattr(node.func, "attr", None) == "add_argument"):
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        flags.add(arg.value)
        for forbidden in ("--approve", "--approved-by", "--reviewer",
                          "--force", "--license", "--set-status"):
            with self.subTest(flag=forbidden):
                self.assertNotIn(forbidden, flags)

    def test_it_makes_no_network_call(self):
        """Retrieving official evidence is a deliberate, recorded human act."""
        imported = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        for forbidden in ("urllib", "urllib.request", "http", "http.client",
                          "socket", "requests", "httpx", "ssl"):
            with self.subTest(module=forbidden):
                self.assertNotIn(forbidden, imported)

    def test_it_needs_no_database(self):
        imported = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        for module in imported:
            with self.subTest(module=module):
                self.assertNotEqual(module.split(".")[0], "sqlalchemy")
                self.assertFalse(module.startswith("pgx.infrastructure"))


class TestTheWrapperScriptDelegates(unittest.TestCase):

    def test_the_root_script_holds_no_logic_of_its_own(self):
        path = os.path.join(REPO_ROOT, "scripts", "source_policy.py")
        with io.open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), filename=path)
        defined = [node.name for node in ast.walk(tree)
                   if isinstance(node, (ast.FunctionDef, ast.ClassDef))]
        self.assertEqual(defined, [],
                         "the wrapper must delegate, not re-implement")

    def test_the_entry_point_targets_the_package_module(self):
        path = os.path.join(REPO_ROOT, "pyproject.toml")
        with io.open(path, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("pgx.application.source_policy_cli:main", text)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
