# -*- coding: utf-8 -*-
"""The committed documents are what the code produces, and the schemas check.

An artifact that nothing regenerates goes stale silently. A schema whose
keywords the validator does not implement is a false assurance. These tests
hold both ends down.
"""

from __future__ import annotations

import io
import json
import os
import unittest

from pgx.application.snapshot_schema import validate_against_schema
from pgx.application.verification_schema import (
    GATE_STATUS_SCHEMA_PATH,
    MATRIX_SCHEMA_PATH,
    PLAN_SCHEMA_PATH,
    WP19_SCHEMA_PATHS,
    build_schemas,
    load_schema,
    validate_coverage_summary,
    validate_flaky_report,
    validate_reproducibility_report,
    validate_requirement_matrix,
    validate_verification_plan,
    validate_verification_result,
    validate_wp19_gate_status,
)
from pgx.verification.artifacts import (
    ARTIFACT_PATHS,
    DETERMINISTIC_ARTIFACT_PATHS,
    INVENTORY_PATH,
    MATRIX_PATH,
    PROFILES_PATH,
    build_artifacts,
    test_id_digest,
)
from pgx.verification.coverage_report import blocked_summary
from pgx.verification.discovery import discover
from pgx.verification.inventory import build_inventory
from pgx.verification.model import Outcome

from tests.unit.verification._support import (
    REPO_ROOT,
    entry,
    inventory,
    profile,
    report,
)


def _read(relative):
    with io.open(os.path.join(REPO_ROOT, *relative.split("/")), "r",
                 encoding="utf-8") as handle:
        return handle.read()


class TestTheCommittedArtifactsMatchTheGenerator(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.built = build_artifacts(REPO_ROOT)

    def test_every_deterministic_artifact_is_committed(self):
        for relative in DETERMINISTIC_ARTIFACT_PATHS:
            with self.subTest(artifact=relative):
                self.assertTrue(
                    os.path.exists(os.path.join(REPO_ROOT,
                                                *relative.split("/"))))

    def test_the_committed_bytes_equal_a_fresh_build(self):
        """A stale inventory describes a suite that no longer exists."""
        for relative, rendered in sorted(self.built.items()):
            with self.subTest(artifact=relative):
                self.assertEqual(_read(relative), rendered)

    def test_building_twice_in_one_process_gives_the_same_bytes(self):
        again = build_artifacts(REPO_ROOT)
        self.assertEqual(sorted(again), sorted(self.built))
        for relative in sorted(again):
            with self.subTest(artifact=relative):
                self.assertEqual(again[relative], self.built[relative])

    def test_every_schema_is_committed_and_current(self):
        for relative, schema in sorted(build_schemas().items()):
            with self.subTest(schema=relative):
                self.assertEqual(load_schema(relative, REPO_ROOT), schema)

    def test_the_rendering_is_canonical(self):
        for relative, rendered in sorted(self.built.items()):
            with self.subTest(artifact=relative):
                self.assertTrue(rendered.endswith("\n"))
                self.assertEqual(json.dumps(json.loads(rendered), indent=2,
                                            sort_keys=True,
                                            ensure_ascii=True) + "\n",
                                 rendered)


class TestTheInventoryArtifact(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.document = json.loads(_read(INVENTORY_PATH))
        cls.discovery = discover(REPO_ROOT)
        cls.inventory = build_inventory(cls.discovery)

    def test_it_validates(self):
        self.assertEqual(validate_verification_plan(self.document), ())

    def test_the_count_matches_what_the_loader_finds_now(self):
        self.assertEqual(self.document["discovered_test_count"],
                         self.discovery.count)

    def test_every_suite_digest_matches_the_tests_in_it(self):
        """The reason the identifiers themselves are not listed: a test added,
        removed or renamed changes this digest, so the committed artifact goes
        stale and says so."""
        grouped = {}
        for item in self.inventory.entries:
            grouped.setdefault(item.module, []).append(item.test_id)
        for row in self.document["suites"]:
            with self.subTest(module=row["module"]):
                self.assertEqual(row["test_id_sha256"],
                                 test_id_digest(grouped[row["module"]]))
                self.assertEqual(row["test_count"],
                                 len(grouped[row["module"]]))

    def test_a_renamed_test_would_change_the_digest(self):
        original = test_id_digest(["a.B.test_one", "a.B.test_two"])
        renamed = test_id_digest(["a.B.test_one", "a.B.test_three"])
        self.assertNotEqual(original, renamed)

    def test_the_digest_does_not_depend_on_order(self):
        self.assertEqual(test_id_digest(["b", "a"]), test_id_digest(["a", "b"]))

    def test_the_counts_agree_with_each_other(self):
        self.assertEqual(
            sum(row["test_count"] for row in self.document["suites"]),
            self.document["inventoried_test_count"])

    def test_the_unmapped_list_is_present_and_empty(self):
        """Present, so a document that dropped the key cannot read as a
        document with nothing unmapped."""
        self.assertIn("unmapped_modules", self.document)
        self.assertEqual(self.document["unmapped_modules"], [])

    def test_it_carries_the_stdout_warning_for_a_later_ci_job(self):
        self.assertIn("CONFIGURATION_FAILURE", self.document["stdout_note"])


class TestTheMatrixArtifact(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.document = json.loads(_read(MATRIX_PATH))

    def test_it_validates(self):
        self.assertEqual(validate_requirement_matrix(self.document), ())

    def test_the_gap_fields_are_present(self):
        for field in ("uncovered_requirements", "unmapped_critical_modules",
                      "empty_categories", "unmapped_safety_invariants"):
            with self.subTest(field=field):
                self.assertIn(field, self.document)

    def test_no_category_claims_to_pass_before_anything_ran(self):
        for row in self.document["categories"]:
            with self.subTest(category=row["category"]):
                self.assertNotEqual(row["static_outcome"], Outcome.PASS.value)

    def test_the_safety_map_carries_its_disclaimer(self):
        self.assertIn("WP-20", self.document["safety_map_disclaimer"])


class TestTheSchemasCheckWhatTheyClaim(unittest.TestCase):

    def test_every_schema_uses_only_keywords_the_validator_implements(self):
        """A published constraint nothing enforces is a false assurance."""
        for relative, schema in sorted(build_schemas().items()):
            with self.subTest(schema=relative):
                problems = validate_against_schema({}, schema)
                self.assertNotIn("unsupported", " ".join(problems).lower())

    def test_every_schema_has_an_id_and_a_description(self):
        for relative, schema in sorted(build_schemas().items()):
            with self.subTest(schema=relative):
                self.assertTrue(schema.get("$id"))
                self.assertTrue(schema.get("title"))
                self.assertTrue(schema.get("description"))

    def test_the_paths_are_all_registered(self):
        self.assertEqual(sorted(build_schemas()), sorted(WP19_SCHEMA_PATHS))

    def test_the_coverage_schema_permits_null_and_forbids_a_stray_key(self):
        document = blocked_summary("absent").as_document()
        self.assertEqual(validate_coverage_summary(document), ())
        self.assertTrue(validate_coverage_summary(
            dict(document, invented_percentage=91.4)))

    def test_the_coverage_schema_refuses_a_percentage_over_a_hundred(self):
        document = dict(blocked_summary("absent").as_document(),
                        status="MEASURED", line_percent=140.0)
        self.assertTrue(validate_coverage_summary(document))

    def test_a_result_schema_refuses_an_invented_outcome_word(self):
        result = build_profile_document()
        self.assertEqual(validate_verification_result(result), ())
        self.assertTrue(validate_verification_result(
            dict(result, outcome="PROBABLY_FINE")))

    def test_a_gate_status_cannot_declare_scientific_validation(self):
        """Pinned by ``const``. Flipping it would need a published schema to
        change in the open."""
        schema = load_schema(GATE_STATUS_SCHEMA_PATH, REPO_ROOT)
        self.assertEqual(
            schema["properties"]["scientific_validation_performed"],
            {"const": False})
        self.assertEqual(schema["properties"]["safety_invariant_map_only"],
                         {"type": "boolean"})

    def test_a_flaky_report_cannot_list_a_test_that_agreed_with_itself(self):
        """``minItems: 2`` on ``distinct_outcomes``."""
        schema = build_schemas()[
            "schemas/wp19/flaky-report.schema.json"]
        item = schema["properties"]["flaky_tests"]["items"]
        self.assertEqual(item["properties"]["distinct_outcomes"]["minItems"], 2)

    def test_a_plan_document_missing_its_gap_field_is_refused(self):
        document = json.loads(_read(INVENTORY_PATH))
        document.pop("unmapped_modules")
        self.assertTrue(validate_verification_plan(document))


def build_profile_document():
    from pgx.verification.results import build_profile_result
    result = build_profile_result(
        profile(), report({"m.C.test_a": {"outcome": "PASS", "reason": ""}}),
        inventory(entry("m.C.test_a")), 1)
    return result.as_document(include_outcomes=True)


class TestTheReportSchemasAcceptRealDocuments(unittest.TestCase):

    def test_a_reproducibility_report_validates(self):
        from pgx.verification.reproducibility import check_generators
        document = check_generators(REPO_ROOT).as_document()
        self.assertEqual(validate_reproducibility_report(document), ())

    def test_a_flaky_report_validates(self):
        from pgx.verification.flaky import compare_runs
        from pgx.verification.results import build_profile_result
        runs = [build_profile_result(
            profile(), report({"m.C.test_a": {"outcome": "PASS",
                                              "reason": ""}}),
            inventory(entry("m.C.test_a")), 1) for _ in range(3)]
        document = compare_runs("flaky", runs, "1").as_document()
        self.assertEqual(validate_flaky_report(document), ())

    def test_a_verification_result_validates(self):
        self.assertEqual(
            validate_verification_result(build_profile_document()), ())
