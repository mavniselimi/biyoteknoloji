# -*- coding: utf-8 -*-
"""The committed WP-20 documents are what the code produces, and validate.

Plus the CI job's contract: it must branch on an exit code, never on output.
"""

from __future__ import annotations

import io
import json
import os
import unittest

from pgx.application.safety_schema import (
    CONTROLS_SCHEMA_PATH, EXECUTION_SCHEMA_PATH, GATE_STATUS_SCHEMA_PATH,
    REGISTRY_SCHEMA_PATH, REPORT_SCHEMA_PATH, WP20_SCHEMA_PATHS,
    build_schemas, load_schema, validate_invariant_registry,
    validate_negative_controls, validate_wp20_gate_status)
from pgx.application.snapshot_schema import validate_against_schema
from pgx.safety.artifacts import (CONTROLS_PATH, DETERMINISTIC_ARTIFACT_PATHS,
                                  REGISTRY_PATH, build_artifacts)
from tests.unit.safety._support import REPO_ROOT

_CI_WORKFLOW = os.path.join(REPO_ROOT, ".github", "workflows",
                            "safety-gate.yml")


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
                self.assertTrue(os.path.exists(
                    os.path.join(REPO_ROOT, *relative.split("/"))))

    def test_the_committed_bytes_equal_a_fresh_build(self):
        for relative, rendered in sorted(self.built.items()):
            with self.subTest(artifact=relative):
                self.assertEqual(_read(relative), rendered)

    def test_building_twice_gives_the_same_bytes(self):
        again = build_artifacts(REPO_ROOT)
        for relative in sorted(again):
            with self.subTest(artifact=relative):
                self.assertEqual(again[relative], self.built[relative])

    def test_the_rendering_is_canonical(self):
        for relative, rendered in sorted(self.built.items()):
            with self.subTest(artifact=relative):
                self.assertTrue(rendered.endswith("\n"))
                self.assertEqual(
                    json.dumps(json.loads(rendered), indent=2, sort_keys=True,
                               ensure_ascii=True) + "\n", rendered)

    def test_every_schema_is_committed_and_current(self):
        for relative, schema in sorted(build_schemas().items()):
            with self.subTest(schema=relative):
                self.assertEqual(load_schema(relative, REPO_ROOT), schema)


class TestTheArtifactsValidate(unittest.TestCase):

    def test_the_registry_validates(self):
        self.assertEqual(
            validate_invariant_registry(json.loads(_read(REGISTRY_PATH))), ())

    def test_the_controls_validate(self):
        self.assertEqual(
            validate_negative_controls(json.loads(_read(CONTROLS_PATH))), ())

    def test_the_registry_schema_admits_exactly_twelve(self):
        schema = build_schemas()[REGISTRY_SCHEMA_PATH]
        self.assertEqual(schema["properties"]["invariant_count"],
                         {"const": 12})
        self.assertEqual(schema["properties"]["invariants"]["minItems"], 12)
        self.assertEqual(schema["properties"]["invariants"]["maxItems"], 12)

    def test_a_thirteenth_invariant_is_refused_by_the_schema(self):
        document = json.loads(_read(REGISTRY_PATH))
        document["invariant_ids"].append("SAFETY-INV-013")
        self.assertTrue(validate_invariant_registry(document))

    def test_the_schema_requires_a_negative_control_per_invariant(self):
        schema = build_schemas()[REGISTRY_SCHEMA_PATH]
        item = schema["properties"]["invariants"]["items"]
        self.assertEqual(
            item["properties"]["negative_controls"]["minItems"], 1)

    def test_a_control_fixture_must_live_under_tests(self):
        """A control realised in production code would be a mutation of the
        shipped system rather than a double."""
        schema = build_schemas()[CONTROLS_SCHEMA_PATH]
        item = schema["properties"]["controls"]["items"]
        self.assertEqual(item["properties"]["fixture"]["pattern"],
                         "^tests\\.fixtures\\.")

    def test_the_gate_schema_pins_the_clinical_claims_to_false(self):
        """Two of the three are still pinned. The third stopped being a claim.

        ``validation_metrics_implemented`` was pinned ``False`` while WP-21
        did not exist, and unpinned at WP-21 together with the field and this
        test. It was always a statement about software, so once the software
        was built, pinning it false would have made the schema assert
        something untrue.

        The other two are not software statements at all: a clinical
        validation and an expert review are things people do. No work package
        can flip them, and they stay ``const``.
        """
        schema = build_schemas()[GATE_STATUS_SCHEMA_PATH]
        for field in ("clinical_validation_performed",
                      "expert_review_performed"):
            with self.subTest(field=field):
                self.assertEqual(schema["properties"][field],
                                 {"const": False})
        self.assertEqual(
            schema["properties"]["validation_metrics_implemented"],
            {"type": "boolean"})

    def test_the_report_schema_requires_the_disclaimer(self):
        schema = build_schemas()[REPORT_SCHEMA_PATH]
        self.assertIn("detector_evidence_disclaimer", schema["required"])
        self.assertEqual(
            schema["properties"]["detector_evidence_disclaimer"]["minLength"],
            80)

    def test_every_schema_uses_only_supported_keywords(self):
        for relative, schema in sorted(build_schemas().items()):
            with self.subTest(schema=relative):
                problems = validate_against_schema({}, schema)
                self.assertNotIn("unsupported", " ".join(problems).lower())

    def test_the_committed_gate_status_validates(self):
        """Asserted to exist rather than skipped when absent. Every other work
        package commits a gate status, and a missing one is a gap somebody
        should hear about rather than a reason to say nothing."""
        document = json.loads(_read("data/safety/wp20-real-gate-status.json"))
        self.assertEqual(validate_wp20_gate_status(document), ())
        self.assertEqual(document["work_package"], "WP-20")
        self.assertEqual(document["registered_invariant_count"], 12)

    def test_the_committed_report_validates(self):
        from pgx.application.safety_schema import validate_safety_report
        document = json.loads(_read("data/safety/wp20-safety-report.json"))
        self.assertEqual(validate_safety_report(document), ())
        self.assertEqual(len(document["invariants"]), 12)

    def test_the_committed_execution_record_validates(self):
        from pgx.application.safety_schema import validate_safety_execution
        document = json.loads(_read("data/safety/wp20-safety-execution.json"))
        self.assertEqual(validate_safety_execution(document), ())

    def test_a_blocked_gate_leaves_no_passing_evidence(self):
        """The record freshness is checked against is written only on PASS.
        A blocked or failing run replaces it with an explicit invalidation, so
        a failing build cannot inherit an earlier success."""
        document = json.loads(_read("data/safety/wp20-safety-execution.json"))
        status = json.loads(_read("data/safety/wp20-real-gate-status.json"))
        if status["safety_gate_status"] != "PASS":
            self.assertFalse(document.get("complete"))
            self.assertTrue(document.get("invalidated"))


class TestTheCiJobBlocksOnExitCodes(unittest.TestCase):
    """The job is the thing a release actually depends on."""

    @classmethod
    def setUpClass(cls):
        cls.text = _read(".github/workflows/safety-gate.yml")
        # The workflow's header explains at length what it must not do, so a
        # substring scan over the whole file finds its own prose. Everything
        # below scans the executable half: lines that are not comments and not
        # blank. This is the same correction the verification tests needed.
        cls.directives = "\n".join(
            line for line in cls.text.splitlines()
            if line.strip() and not line.strip().startswith("#"))

    def test_it_exists(self):
        self.assertTrue(os.path.exists(_CI_WORKFLOW))

    def test_it_invokes_the_authoritative_gate(self):
        self.assertIn("safety_cli check", self.directives)

    def test_it_does_not_grep_stdout(self):
        """Several tests print CONFIGURATION_FAILURE while passing."""
        for forbidden in ("grep", "awk", "sed -n", "tee ", "| head"):
            with self.subTest(pattern=forbidden):
                self.assertNotIn(forbidden, self.directives)

    def test_the_exit_code_contract_is_documented(self):
        """A later maintainer has to be able to see why there is no `if`."""
        self.assertIn("exit code", self.text.lower())
        for code in ("0  PASS", "1  FAIL", "2  BLOCKED"):
            with self.subTest(code=code):
                self.assertIn(code, self.text)

    def test_it_installs_no_third_party_dependency(self):
        """A dependency would mean the gate could not run where a release is
        actually built."""
        self.assertNotIn("pip install", self.directives)
        self.assertNotIn("uv sync", self.directives)

    def test_it_uploads_the_machine_readable_report(self):
        self.assertIn("wp20-safety-report.json", self.directives)

    def test_it_does_not_implement_the_wp24_pipeline(self):
        for forbidden in ("deploy", "docker build", "publish", "twine",
                          "registry.push"):
            with self.subTest(step=forbidden):
                self.assertNotIn(forbidden, self.directives.lower())

    def test_it_is_reported_configured_not_executed(self):
        from pgx.safety.gate_status import _ci_job
        facts = _ci_job(REPO_ROOT)
        self.assertTrue(facts["ci_job_configured"])
        self.assertFalse(facts["ci_job_executed"])
        self.assertIn("CONFIGURED, not EXECUTED",
                      facts["ci_job_execution_note"])
