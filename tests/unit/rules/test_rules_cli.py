# -*- coding: utf-8 -*-
"""The ``pgx-rules`` command line (WP-11).

Everything this tool does is read-only or refuses. It inspects rules, reports
validation issues, classifies conflicts, verifies a frozen artifact, lists
what the registry can serve, and says why no real rule may exist. It approves
nothing, promotes nothing and forces nothing.

The refused-flag tests matter more than they look. Somebody under deadline
pressure will eventually type ``--force``, and the difference between argparse
saying "unrecognized arguments" and this tool saying "there is no override for
a failed validation" is the difference between looking for another flag and
understanding why there isn't one.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout

from pgx.application.rules_cli import (EXIT_CONFIGURATION_FAILURE, EXIT_OK,
                                       EXIT_REFUSED, REFUSED_FLAGS,
                                       build_parser, main)
from tests.fixtures.wp11.synthetic import frozen_ruleset, synthetic_rule
from tests.unit.rules._support import DEFAULT_REGISTRY_ROOT, REPO_ROOT


def _run(*argv):
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = main(list(argv))
    return code, buffer.getvalue()


def _json_run(*argv):
    code, output = _run(*argv)
    return code, json.loads(output)


class TestTheToolRefusesSelfElevation(unittest.TestCase):

    def test_every_refused_flag_is_refused_by_name(self):
        for flag in REFUSED_FLAGS:
            with self.subTest(flag=flag):
                code, payload = _json_run(flag, "gate-status")
                self.assertEqual(code, EXIT_REFUSED)
                self.assertIn(flag, json.dumps(payload))

    def test_each_refusal_explains_why_the_flag_does_not_exist(self):
        for flag, reason in REFUSED_FLAGS.items():
            with self.subTest(flag=flag):
                _code, payload = _json_run(flag, "gate-status")
                self.assertIn(reason, json.dumps(payload))

    def test_a_refused_flag_with_a_value_is_still_refused(self):
        code, _payload = _json_run("--role=ADJUDICATOR", "gate-status")
        self.assertEqual(code, EXIT_REFUSED)

    def test_abbreviations_are_not_accepted(self):
        """``allow_abbrev=False``: ``--fo`` must not become ``--force``, and
        no prefix of a real flag may silently mean something else."""
        parser = build_parser()
        self.assertFalse(parser.allow_abbrev)


class TestTheCommandSurfaceIsReadOnly(unittest.TestCase):

    EXPECTED = ("build-attempt", "detect-conflicts", "gate-status",
                "inspect-rule", "inspect-ruleset", "legacy-inventory",
                "list-executable", "list-issue-codes", "validate-rule",
                "verify-ruleset")

    def _commands(self):
        parser = build_parser()
        for action in parser._actions:  # noqa: SLF001 - argparse has no API
            if hasattr(action, "choices") and action.choices:
                return tuple(sorted(action.choices))
        return ()

    def test_exactly_these_commands_exist(self):
        self.assertEqual(self._commands(), self.EXPECTED)

    def test_no_command_approves_promotes_or_forces(self):
        for command in self._commands():
            with self.subTest(command=command):
                for forbidden in ("approve", "promote", "force", "grant",
                                  "assign", "freeze", "create", "delete",
                                  "skip"):
                    self.assertNotIn(forbidden, command)


class TestReadOnlyCommandsOnRealData(unittest.TestCase):

    def test_gate_status_reports_the_blockers_and_zero_rules(self):
        """Exit 1, not 0: the gates are shut, and a tool that exited zero on
        a closed gate would let a pipeline treat "blocked" as "fine"."""
        code, payload = _json_run("gate-status", "--repo-root", REPO_ROOT)
        self.assertEqual(code, EXIT_REFUSED)
        self.assertTrue(payload["blockers"])
        self.assertEqual(payload["rule_state"]["real_validated_rules"], 0)

    def test_build_attempt_reports_a_refusal(self):
        code, payload = _json_run("build-attempt", "--repo-root", REPO_ROOT)
        self.assertEqual(code, EXIT_REFUSED)
        self.assertTrue(payload["blockers"])
        self.assertEqual(payload["executable_rulesets"], [])
        self.assertTrue(payload["stopped_at"])

    def test_legacy_inventory_reports_no_eligible_candidate(self):
        code, payload = _json_run("legacy-inventory", "--repo-root",
                                  REPO_ROOT)
        self.assertIn(code, (EXIT_OK, EXIT_REFUSED))
        self.assertEqual(payload["counts"]["eligible_for_rule_creation"], 0)
        self.assertEqual(payload["counts"]["rules_created"], 0)

    def test_legacy_inventory_verify_matches_the_published_file(self):
        code, _payload = _json_run("legacy-inventory", "--verify",
                                   "--repo-root", REPO_ROOT)
        self.assertEqual(code, EXIT_OK)

    def test_list_executable_on_the_production_root_is_empty(self):
        code, payload = _json_run("list-executable", "--root",
                                  DEFAULT_REGISTRY_ROOT)
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(payload["executable_rulesets"], [])
        self.assertEqual(payload["count"], 0)

    def test_list_issue_codes_documents_every_layer(self):
        code, payload = _json_run("list-issue-codes")
        self.assertEqual(code, EXIT_OK)
        layers = {entry["layer"] for entry in payload["issue_codes"].values()}
        self.assertEqual(layers, {"A", "B", "C", "D", "E"})

    def test_list_issue_codes_also_documents_the_conflict_kinds(self):
        _code, payload = _json_run("list-issue-codes")
        self.assertEqual(len(payload["conflict_kinds"]), 8)


class TestRuleAndArtifactCommands(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.rule_path = os.path.join(self.tmp, "rule.json")
        definition = synthetic_rule()
        with io.open(self.rule_path, "w", encoding="utf-8") as handle:
            json.dump(definition.to_json(), handle)
        self.definition = definition

    def test_inspect_rule_prints_the_document(self):
        code, payload = _json_run("inspect-rule", self.rule_path)
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(payload["rule_id"], self.definition.rule_id.to_json())
        self.assertEqual(payload["content_hash"],
                         self.definition.content_hash())

    def test_validate_rule_passes_a_well_formed_document(self):
        code, payload = _json_run("validate-rule", self.rule_path)
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(payload["issues"], [])

    def test_validate_rule_reports_every_issue_at_once(self):
        broken = os.path.join(self.tmp, "broken.json")
        document = self.definition.to_json()
        document["condition"]["gene_id"] = "*"
        document["outcome"]["dose"] = "50 mg"
        with io.open(broken, "w", encoding="utf-8") as handle:
            json.dump(document, handle)
        code, payload = _json_run("validate-rule", broken)
        self.assertEqual(code, EXIT_REFUSED)
        self.assertGreaterEqual(len(payload["issues"]), 2)

    def test_detect_conflicts_reports_a_disagreement_without_resolving_it(self):
        from pgx.domain.enums import AttentionLevel
        paths = []
        for index, level in enumerate((AttentionLevel.LOW,
                                       AttentionLevel.HIGH)):
            path = os.path.join(self.tmp, "rule-%d.json" % index)
            with io.open(path, "w", encoding="utf-8") as handle:
                json.dump(synthetic_rule(attention=level).to_json(), handle)
            paths.append(path)
        code, payload = _json_run("detect-conflicts", *paths)
        self.assertEqual(code, EXIT_REFUSED)
        self.assertTrue(payload["findings"])
        self.assertNotIn("winner", json.dumps(payload))

    def test_verify_ruleset_accepts_a_clean_artifact(self):
        destination = os.path.join(self.tmp, "PGX-RULESET-29991231-001")
        frozen_ruleset(destination, count=2)
        code, payload = _json_run("verify-ruleset", destination)
        self.assertEqual(code, EXIT_OK)
        self.assertTrue(payload["verified"])

    def test_verify_ruleset_refuses_a_tampered_artifact(self):
        destination = os.path.join(self.tmp, "PGX-RULESET-29991231-002")
        frozen_ruleset(destination, count=2)
        with io.open(os.path.join(destination, "rules.ndjson"), "a",
                     encoding="utf-8") as handle:
            handle.write("\n")
        code, _payload = _json_run("verify-ruleset", destination)
        self.assertNotEqual(code, EXIT_OK)

    def test_inspect_ruleset_prints_the_manifest(self):
        destination = os.path.join(self.tmp, "PGX-RULESET-29991231-003")
        frozen_ruleset(destination, count=2)
        code, payload = _json_run("inspect-ruleset", destination)
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(payload["member_count"], 2)
        self.assertIn("not a claim of clinical coverage", payload["note"])

    def test_a_missing_file_is_a_configuration_failure_not_a_crash(self):
        code, _payload = _json_run("inspect-rule",
                                   os.path.join(self.tmp, "absent.json"))
        self.assertEqual(code, EXIT_CONFIGURATION_FAILURE)


class TestTheToolNeedsNoNetworkAndNoDatabase(unittest.TestCase):

    def test_the_cli_module_imports_no_client_library(self):
        from tests.unit.rules._support import APPLICATION_DIR, imports_of
        imported = imports_of(os.path.join(APPLICATION_DIR, "rules_cli.py"))
        for forbidden in ("requests", "httpx", "urllib.request", "socket",
                          "sqlalchemy", "psycopg2"):
            with self.subTest(module=forbidden):
                self.assertNotIn(forbidden, imported)


if __name__ == "__main__":
    unittest.main()
