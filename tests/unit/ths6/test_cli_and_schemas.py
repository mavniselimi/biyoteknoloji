# -*- coding: utf-8 -*-
"""The command line means what it says, and the schemas refuse the lies.

The exit-code tests are the contract a pipeline branches on, so they are
asserted per subcommand rather than inferred. The distinction that matters:
``verify-pack`` and ``build-pack`` may exit 0 today because they ask whether
the *pack* is sound, and a sound pack honestly recording six blocked gates is
a success for them. Every other subcommand asks about the *programme* and
exits 2 while it is blocked.

The schema tests are negative by design. A schema that only described the
happy shape would accept a gate recorded PASS beside its own unmet
conditions, a sign-off row carrying a name, or a status asserting achievement
with three of four conditions false - so each of those is constructed and the
refusal asserted.
"""

from __future__ import annotations

import copy
import inspect
import io
import json
import os
import unittest

from pgx.application import ths6_cli
from pgx.application.ths6_schema import (SCHEMA_DIRECTORY, build_schemas,
                                         validate_claim_registry,
                                         validate_contingency_matrix,
                                         validate_definition_of_done,
                                         validate_demo_manifest,
                                         validate_demo_preflight,
                                         validate_evidence_item,
                                         validate_evidence_registry,
                                         validate_gate_matrix,
                                         validate_pack_manifest,
                                         validate_signoff_matrix,
                                         validate_ths6_status,
                                         validate_traceability_matrix)
from pgx.ths6.claim_registry import build_claim_registry
from pgx.ths6.contingency import build_contingency_matrix
from pgx.ths6.definition_of_done import build_definition_of_done
from pgx.ths6.demo import build_demo_manifest, run_demo_preflight
from pgx.ths6.evidence_registry import build_evidence_registry
from pgx.ths6.gate_matrix import build_gate_matrix
from pgx.ths6.signoff import build_signoff_matrix
from pgx.ths6.status import build_ths6_status
from pgx.ths6.traceability import build_traceability

_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", ".."))


class _Quiet(unittest.TestCase):
    """Runs a subcommand with stdout captured."""

    def run_command(self, *argv):
        import contextlib

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = ths6_cli.main(list(argv) + ["--root", _ROOT])
        return code, buffer.getvalue()


class TestExitCodes(_Quiet):

    def test_gates_exits_blocked(self):
        code, output = self.run_command("gates")
        self.assertEqual(code, 2)
        self.assertIn("BLOCKED", output)

    def test_demo_preflight_exits_blocked(self):
        code, _ = self.run_command("demo-preflight")
        self.assertEqual(code, 2)

    def test_status_exits_blocked(self):
        code, output = self.run_command("status")
        self.assertEqual(code, 2)
        self.assertIn("ths6_achieved", output)

    def test_dod_exits_blocked(self):
        code, _ = self.run_command("dod")
        self.assertEqual(code, 2)

    def test_claims_exits_blocked(self):
        code, _ = self.run_command("claims")
        self.assertEqual(code, 2)

    def test_traceability_exits_blocked(self):
        code, _ = self.run_command("traceability")
        self.assertEqual(code, 2)

    def test_inventory_exits_zero_while_no_artifact_is_invalid(self):
        """The exit code follows the artifacts, and they were repaired.

        When WP-25 built the pack this returned 1: ``data/web/
        wp17-real-gate-status.json`` recorded ``screenshot_evidence_status:
        "CAPTURED"`` while the schema WP-17 published in the same run admitted
        only ``"NONE"`` and ``"BROWSER_CAPTURED"``. WP-C00 gave the producer,
        the schema and the tests one spelling of that vocabulary, so the
        artifact now satisfies its own contract and there is nothing left for
        this command to fail on.

        The assertion is inverted rather than deleted. ``inventory`` must
        still exit 1 the moment any declared artifact stops validating, and a
        test that no longer looked would not notice.
        """
        code, _ = self.run_command("inventory")
        self.assertEqual(code, 0)

    def test_verify_pack_exits_zero_for_an_intact_pack(self):
        manifest = os.path.join(_ROOT, "data", "ths6",
                                "wp25-evidence-pack-manifest.json")
        if not os.path.isfile(manifest):
            self.skipTest("the pack has not been built in this tree")
        code, output = self.run_command("verify-pack")
        self.assertEqual(code, 0)
        self.assertIn("not the programme", output)

    def test_an_unknown_subcommand_is_a_usage_error(self):
        self.assertEqual(ths6_cli.main(["not-a-command"]), 3)

    def test_no_subcommand_prints_help_and_reports_usage(self):
        import contextlib

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = ths6_cli.main([])
        self.assertEqual(code, 3)
        self.assertIn("pgx-ths6", buffer.getvalue())

    def test_help_exits_success(self):
        import contextlib

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = ths6_cli.main(["--help"])
        self.assertEqual(code, 0)


class TestOutputDiscipline(_Quiet):

    def test_every_command_prints_the_banner(self):
        for name in ("inventory", "claims", "traceability", "gates", "dod",
                     "demo-preflight", "status"):
            with self.subTest(command=name):
                _, output = self.run_command(name)
                self.assertIn("cannot approve, sign, execute or improve",
                              output)

    def test_json_output_is_parseable(self):
        for name in ("gates", "dod", "status", "claims"):
            with self.subTest(command=name):
                _, output = self.run_command(name, "--json")
                document = json.loads(output)
                self.assertIsInstance(document, dict)

    def test_json_output_omits_the_banner(self):
        _, output = self.run_command("gates", "--json")
        self.assertNotIn("cannot approve", output)

    def test_status_prints_both_results_separately(self):
        _, output = self.run_command("status")
        self.assertIn("evidence_pack_integrity", output)
        self.assertIn("ths6_achieved", output)

    def test_no_output_claims_the_pack_is_an_achievement(self):
        for name in ("verify-pack", "status"):
            with self.subTest(command=name):
                code, output = self.run_command(name)
                if "not been built" in output:
                    continue
                self.assertNotIn("THS 6 achieved", output)

    def test_gates_verbose_prints_owners(self):
        _, output = self.run_command("gates", "--verbose")
        self.assertIn("curation lead", output)

    def test_the_parser_declares_nine_subcommands(self):
        self.assertEqual(len(ths6_cli._COMMANDS), 9)
        self.assertEqual(
            sorted(ths6_cli._COMMANDS),
            ["build-pack", "claims", "demo-preflight", "dod", "gates",
             "inventory", "status", "traceability", "verify-pack"])

    def test_the_help_text_denies_an_override(self):
        source = inspect.getsource(ths6_cli)
        self.assertIn("no --force", source)


class TestSchemasArePublished(unittest.TestCase):

    def setUp(self):
        self.schemas = build_schemas()

    def test_there_are_twenty(self):
        self.assertEqual(len(self.schemas), 20)

    def test_every_schema_is_committed_and_matches_the_generator(self):
        from pgx.ths6.integrity import canonical_json

        for relative, schema in sorted(self.schemas.items()):
            path = os.path.join(_ROOT, *relative.split("/"))
            with self.subTest(path=relative):
                self.assertTrue(os.path.isfile(path), "%s is not committed"
                                % relative)
                with io.open(path, "r", encoding="utf-8") as handle:
                    self.assertEqual(handle.read(), canonical_json(schema))

    def test_every_schema_lives_under_the_declared_directory(self):
        for relative in self.schemas:
            with self.subTest(path=relative):
                self.assertTrue(relative.startswith(SCHEMA_DIRECTORY + "/"))

    def test_every_schema_has_a_title_and_a_description(self):
        for relative, schema in sorted(self.schemas.items()):
            with self.subTest(path=relative):
                self.assertTrue(schema.get("title"))
                self.assertTrue(schema.get("description"))


class TestEveryDocumentValidates(unittest.TestCase):

    def test_the_ten_built_documents_satisfy_their_schemas(self):
        checks = (
            (validate_evidence_registry, build_evidence_registry(_ROOT)),
            (validate_claim_registry, build_claim_registry(_ROOT)),
            (validate_traceability_matrix, build_traceability(_ROOT)),
            (validate_gate_matrix, build_gate_matrix(_ROOT)),
            (validate_definition_of_done, build_definition_of_done(_ROOT)),
            (validate_demo_manifest, build_demo_manifest(_ROOT)),
            (validate_demo_preflight, run_demo_preflight(_ROOT)),
            (validate_contingency_matrix, build_contingency_matrix()),
            (validate_signoff_matrix, build_signoff_matrix()),
            (validate_ths6_status,
             build_ths6_status(_ROOT, pack_integrity=True)),
        )
        for validator, document in checks:
            with self.subTest(validator=validator.__name__):
                self.assertEqual(list(validator(document)), [])

    def test_the_committed_pack_manifest_validates(self):
        path = os.path.join(_ROOT, "data", "ths6",
                            "wp25-evidence-pack-manifest.json")
        if not os.path.isfile(path):
            self.skipTest("the pack has not been built in this tree")
        with io.open(path, "r", encoding="utf-8") as handle:
            manifest = json.load(handle)
        self.assertEqual(list(validate_pack_manifest(manifest)), [])


class TestSchemasRefuseTheLies(unittest.TestCase):
    """Each test constructs the dishonest document and asserts a refusal."""

    def test_a_test_result_may_not_claim_to_support_a_claim(self):
        item = {"evidence_id": "EV-WP20-001", "title": "t",
                "work_package": "WP-20",
                "evidence_type": "IMPLEMENTATION_TEST", "path": "a.json",
                "present": True, "sha256": "sha256:" + "0" * 64,
                "test_only": False, "observed_or_executed": False,
                "may_support_a_ths6_claim": True,
                "contains_numeric_claim": False, "supported_claim_ids": [],
                "gate_ids": [], "limitations": []}
        self.assertTrue(validate_evidence_item(item))

    def test_a_test_only_item_may_not_be_admissible(self):
        item = {"evidence_id": "EV-WP17-003", "title": "t",
                "work_package": "WP-17",
                "evidence_type": "REAL_EXECUTED", "path": "a.json",
                "present": True, "sha256": "sha256:" + "0" * 64,
                "test_only": True, "observed_or_executed": False,
                "may_support_a_ths6_claim": True,
                "contains_numeric_claim": False, "supported_claim_ids": [],
                "gate_ids": [], "limitations": []}
        self.assertTrue(validate_evidence_item(item))

    def test_an_absent_item_may_not_carry_a_digest(self):
        item = {"evidence_id": "EV-WP16-005", "title": "t",
                "work_package": "WP-16", "evidence_type": "UNAVAILABLE",
                "path": "a.json", "present": False,
                "sha256": "sha256:" + "0" * 64, "test_only": False,
                "observed_or_executed": False,
                "may_support_a_ths6_claim": False,
                "contains_numeric_claim": False, "supported_claim_ids": [],
                "gate_ids": [], "limitations": []}
        self.assertTrue(validate_evidence_item(item))

    def test_an_absolute_path_is_refused_by_the_schema(self):
        item = {"evidence_id": "EV-WP00-001", "title": "t",
                "work_package": "WP-00", "evidence_type": "DOCUMENT_ONLY",
                "path": "/Users/somebody/architecture.md", "present": True,
                "sha256": "sha256:" + "0" * 64, "test_only": False,
                "observed_or_executed": False,
                "may_support_a_ths6_claim": False,
                "contains_numeric_claim": False, "supported_claim_ids": [],
                "gate_ids": [], "limitations": []}
        self.assertTrue(validate_evidence_item(item))

    def _forged_gate_matrix(self):
        document = copy.deepcopy(build_gate_matrix(_ROOT))
        gate = document["gates"][0]
        gate["result"] = "PASS"
        gate["is_pass"] = True
        return document

    def test_a_gate_recorded_pass_with_unmet_conditions_is_refused(self):
        self.assertTrue(validate_gate_matrix(self._forged_gate_matrix()))

    def test_a_matrix_claiming_an_override_is_refused(self):
        document = copy.deepcopy(build_gate_matrix(_ROOT))
        document["override_available"] = True
        self.assertTrue(validate_gate_matrix(document))

    def test_all_gates_pass_with_blocking_gates_listed_is_refused(self):
        document = copy.deepcopy(build_gate_matrix(_ROOT))
        document["all_gates_pass"] = True
        self.assertTrue(validate_gate_matrix(document))

    def test_a_supported_claim_with_missing_evidence_is_refused(self):
        document = copy.deepcopy(build_claim_registry(_ROOT))
        claim = document["claims"][0]
        claim["support"] = "SUPPORTED"
        claim["sufficient"] = True
        claim["missing_evidence_ids"] = ["EV-WP20-001"]
        self.assertTrue(validate_claim_registry(document))

    def test_an_unresolvable_probe_is_refused(self):
        document = copy.deepcopy(build_claim_registry(_ROOT))
        document["unresolvable_probes"] = [{"claim_id": "THS6-CLAIM-001"}]
        self.assertTrue(validate_claim_registry(document))

    def test_a_dod_registry_of_fourteen_items_is_refused(self):
        """The count is pinned so a merge could not pass validation."""
        document = copy.deepcopy(build_definition_of_done(_ROOT))
        document["items"] = document["items"][:14]
        document["enumerated_count"] = 14
        self.assertTrue(validate_definition_of_done(document))

    def test_an_unsatisfied_dod_item_without_an_owner_is_refused(self):
        document = copy.deepcopy(build_definition_of_done(_ROOT))
        document["items"][0]["owner"] = None
        self.assertTrue(validate_definition_of_done(document))

    def test_a_signed_signoff_row_is_refused(self):
        document = copy.deepcopy(build_signoff_matrix())
        document["roles"][0]["signed"] = True
        document["roles"][0]["signatory"] = "somebody"
        self.assertTrue(validate_signoff_matrix(document))

    def test_a_signature_mechanism_is_refused(self):
        document = copy.deepcopy(build_signoff_matrix())
        document["signature_mechanism"] = "pgx-ths6 sign"
        self.assertTrue(validate_signoff_matrix(document))

    def test_a_blocked_preflight_claiming_execution_is_refused(self):
        document = copy.deepcopy(run_demo_preflight(_ROOT))
        document["demo_executed"] = True
        self.assertTrue(validate_demo_preflight(document))

    def test_achievement_with_an_unmet_condition_is_refused(self):
        document = copy.deepcopy(build_ths6_status(_ROOT,
                                                   pack_integrity=True))
        document["ths6_achieved"] = True
        self.assertTrue(validate_ths6_status(document))

    def test_a_release_permitted_without_achievement_is_refused(self):
        document = copy.deepcopy(build_ths6_status(_ROOT,
                                                   pack_integrity=True))
        document["release_may_proceed"] = True
        self.assertTrue(validate_ths6_status(document))

    def test_pack_integrity_cannot_stand_in_for_achievement(self):
        """An intact pack beside a blocked programme is a valid document."""
        document = build_ths6_status(_ROOT, pack_integrity=True)
        self.assertEqual(list(validate_ths6_status(document)), [])
        self.assertIs(document["ths6_achieved"], False)

    def test_a_manifest_with_a_self_hash_is_refused(self):
        path = os.path.join(_ROOT, "data", "ths6",
                            "wp25-evidence-pack-manifest.json")
        if not os.path.isfile(path):
            self.skipTest("the pack has not been built in this tree")
        with io.open(path, "r", encoding="utf-8") as handle:
            manifest = json.load(handle)
        manifest["manifest_self_hash"] = "sha256:" + "0" * 64
        self.assertTrue(validate_pack_manifest(manifest))

    def test_a_contingency_row_without_does_not_prove_is_refused(self):
        document = copy.deepcopy(build_contingency_matrix())
        document["scenarios"][0]["does_not_prove"] = ""
        self.assertTrue(validate_contingency_matrix(document))

    def test_a_traceability_gap_without_an_owner_is_refused(self):
        document = copy.deepcopy(build_traceability(_ROOT))
        for row in document["rows"]:
            if row["result"] != "SUPPORTED":
                row["gap_owner"] = None
                break
        self.assertTrue(validate_traceability_matrix(document))

    def test_dod_014_satisfied_with_a_dangling_reference_is_refused(self):
        document = copy.deepcopy(build_traceability(_ROOT))
        document["p0_dod_014_satisfied"] = True
        document["has_dangling_reference"] = True
        self.assertTrue(validate_traceability_matrix(document))

    def test_an_evidence_registry_with_no_preliminary_documents_is_refused(
            self):
        document = copy.deepcopy(build_evidence_registry(_ROOT))
        document["preliminary_ths6_documents"] = []
        self.assertTrue(validate_evidence_registry(document))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
