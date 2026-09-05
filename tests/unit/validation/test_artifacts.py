# -*- coding: utf-8 -*-
"""The committed WP-18 artifacts: current, deterministic and honest (WP-18).

Three questions, and the third is the one this work package exists to answer
carefully.

*Are they current?* Regenerating on an unchanged tree must reproduce the
committed bytes, or a diff is a diff of formatting.

*Do they satisfy their own schemas?* A generator emitting a document its own
schema rejects is publishing a constraint it does not keep.

*Do they tell the truth about how little exists?* Zero holdout cases, a P0
target of fifty, and the gap reported rather than closed. Null where nothing
was measured. No metric, no percentage, no denominator anywhere.
"""

from __future__ import annotations

import io
import json
import os
import unittest

from pgx.application.validation_cli import (ARTIFACT_PATHS, build_artifacts)
from pgx.application.validation_schema import (WP18_SCHEMA_PATHS, load_schema,
                                               validate_access_event,
                                               validate_case_manifest,
                                               validate_separation_audit,
                                               validate_validation_case,
                                               validate_wp18_gate_status)
from pgx.validation.manifests import P0_TARGET_CASE_COUNT

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))


def _read(relative):
    with io.open(os.path.join(REPO_ROOT, *relative.split("/")),
                 encoding="utf-8") as handle:
        return handle.read()


class TestTheCommittedArtifacts(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.generated = build_artifacts(REPO_ROOT)

    def test_every_artifact_is_committed(self):
        for relative in ARTIFACT_PATHS:
            with self.subTest(artifact=relative):
                self.assertTrue(
                    os.path.isfile(os.path.join(REPO_ROOT,
                                                *relative.split("/"))),
                    "%s is missing; run python -m "
                    "pgx.application.validation_cli artifacts" % relative)

    def test_every_artifact_is_current(self):
        for relative in ARTIFACT_PATHS:
            with self.subTest(artifact=relative):
                self.assertEqual(
                    _read(relative), self.generated[relative],
                    "%s is stale; run python -m "
                    "pgx.application.validation_cli artifacts" % relative)

    def test_regenerating_twice_produces_the_same_bytes(self):
        self.assertEqual(build_artifacts(REPO_ROOT), self.generated)

    def test_the_generator_owns_exactly_these_paths(self):
        self.assertEqual(sorted(self.generated), sorted(ARTIFACT_PATHS))

    def test_no_artifact_carries_a_timestamp_that_moves(self):
        """Determinism, checked the other way round.

        A generated document containing "now" would pass the equality test
        above only if two runs landed in the same second.
        """
        import re

        stamp = re.compile(r"20\d\d-\d\d-\d\dT\d\d:\d\d:\d\dZ")
        for relative in ARTIFACT_PATHS:
            if not relative.startswith("data/"):
                continue
            with self.subTest(artifact=relative):
                for found in stamp.findall(self.generated[relative]):
                    # The only timestamps permitted are the WP-17 migration
                    # date carried by the development cases, which is fixed.
                    self.assertTrue(found.startswith("2026-08-29"), found)


class TestEveryDocumentSatisfiesItsSchema(unittest.TestCase):

    def test_the_schemas_are_committed(self):
        for path in WP18_SCHEMA_PATHS:
            with self.subTest(schema=os.path.basename(path)):
                self.assertTrue(os.path.isfile(path))

    def test_the_development_manifest_validates(self):
        document = json.loads(
            _read("data/validation/wp18-development-case-manifest.json"))
        self.assertEqual(validate_case_manifest(document), ())

    def test_the_holdout_manifest_validates(self):
        document = json.loads(
            _read("data/validation/wp18-holdout-case-manifest.json"))
        self.assertEqual(validate_case_manifest(document), ())

    def test_the_separation_audit_validates(self):
        document = json.loads(
            _read("data/validation/wp18-separation-audit.json"))
        self.assertEqual(validate_separation_audit(document), ())

    def test_the_gate_status_validates(self):
        document = json.loads(
            _read("data/validation/wp18-real-gate-status.json"))
        self.assertEqual(validate_wp18_gate_status(document), ())

    def test_every_development_case_validates(self):
        from pgx.validation.catalog import development_cases

        for case in development_cases(REPO_ROOT):
            with self.subTest(case=case.case_id.value):
                self.assertEqual(validate_validation_case(case.to_json()), ())

    def test_a_case_document_with_an_answer_fails_the_schema(self):
        """The schema refuses the field, rather than merely not listing it."""
        from pgx.validation.catalog import development_cases

        document = dict(development_cases(REPO_ROOT)[0].to_json())
        document["expected_result"] = "HIGH"
        self.assertNotEqual(validate_validation_case(document), ())

    def test_an_access_event_may_not_claim_authentication(self):
        from pgx.validation.access import ACCESS_EVENT_VERSION

        event = {
            "schema_version": ACCESS_EVENT_VERSION,
            "case_id": "PGX-VAL-INT-1", "case_role": "INTERNAL_HOLDOUT",
            "actor": "TEST-somebody", "actor_authenticated": True,
            "context_kind": "VALIDATION_RUN", "action": "READ_PAYLOAD",
            "allowed": True, "reason_code": "",
            "occurred_at": "2026-03-01T00:00:00Z",
            "manifest_hash": "sha256:" + "a" * 64}
        self.assertNotEqual(validate_access_event(event), ())
        event["actor_authenticated"] = False
        self.assertEqual(validate_access_event(event), ())


class TestTheGateStatusIsHonest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.status = json.loads(
            _read("data/validation/wp18-real-gate-status.json"))

    def test_it_reports_the_actual_counts(self):
        self.assertEqual(self.status["development_case_count"], 7)
        self.assertEqual(self.status["internal_holdout_case_count"], 0)
        self.assertEqual(self.status["expert_holdout_case_count"], 0)
        self.assertEqual(self.status["holdout_case_count"], 0)

    def test_the_p0_target_is_not_rendered_as_an_achievement(self):
        """Fifty is the target. Zero is the count. They are separate fields."""
        self.assertEqual(self.status["p0_target_case_count"],
                         P0_TARGET_CASE_COUNT)
        self.assertFalse(self.status["p0_target_met"])
        self.assertEqual(self.status["p0_target_shortfall"],
                         P0_TARGET_CASE_COUNT)

    def test_unmeasurable_counts_are_null_and_not_zero(self):
        """'Nobody looked' and 'we looked and found none' differ."""
        for field in ("restricted_payload_count", "validation_metric_count",
                      "expert_reviewed_case_count"):
            with self.subTest(field=field):
                self.assertIsNone(self.status[field])
                self.assertIn("null rather than zero",
                              self.status[field + "_source"])

    def test_the_real_patient_count_is_structurally_zero(self):
        self.assertEqual(self.status["real_patient_case_count"], 0)
        self.assertIn("structurally zero",
                      self.status["real_patient_case_count_source"])

    def test_no_metric_or_percentage_appears_anywhere(self):
        rendered = _read("data/validation/wp18-real-gate-status.json")
        for forbidden in ("concordance", "accuracy", "pass_rate", "%",
                          "precision", "recall", "f1", "auc"):
            with self.subTest(term=forbidden):
                self.assertNotIn(forbidden, rendered.lower())

    def test_it_reports_the_governance_blockers(self):
        codes = {blocker["code"] for blocker in self.status["blockers"]}
        for expected in ("VALIDATION_NO_HOLDOUT_CASES",
                         "VALIDATION_BELOW_P0_CASE_TARGET",
                         "VALIDATION_NO_ACTIVE_RELEASE",
                         "VALIDATION_CLAIM_BOUNDARY_NOT_APPROVED",
                         # Replaced at WP-21: the metrics exist now, and the
                         # honest blocker is that no benchmark has been run.
                         "VALIDATION_BENCHMARK_NOT_PASSING",
                         # Replaced at WP-22 for the same reason: the review
                         # module exists now, so "not implemented" is false.
                         # The blocker itself did not go away - no expert has
                         # completed a review - so the code was renamed
                         # rather than removed.
                         "VALIDATION_NO_COMPLETED_EXPERT_REVIEWS"):
            with self.subTest(code=expected):
                self.assertIn(expected, codes)

    def test_every_blocker_names_an_owner(self):
        for blocker in self.status["blockers"]:
            with self.subTest(code=blocker["code"]):
                self.assertTrue(blocker["owner"])

    def test_it_may_not_report_a_validation_result(self):
        self.assertFalse(self.status["may_report_validation_result"])

    def test_it_does_not_activate_or_invent_a_release(self):
        self.assertFalse(self.status["active_release_available"])

    def test_it_does_not_approve_the_claim_boundary(self):
        self.assertFalse(self.status["claim_boundary_approved"])


class TestLaterPackagesAreReportedHonestly(unittest.TestCase):
    """The flags follow the tree; they are not pinned to a convenient value.

    This class used to assert ``wp19_started is False``. WP-19 then started,
    which made that assertion false for the best possible reason - and it is
    worth being precise about what was actually being protected. It was never
    "WP-19 has not begun", which is a fact with a shelf life. It was "this
    document reports the truth about what has begun", which does not.

    So the assertion moved to agreement with the filesystem, the same
    correction WP-17 made to ``wp17_started`` when it started. WP-21 and WP-22
    are still pinned unstarted, because they still are.
    """

    #: What each flag is measured from, mirroring
    #: ``pgx/validation/gate_status.py``. Written out here so this test fails
    #: if the two ever disagree, rather than following whatever the code says
    #: and therefore agreeing with it by construction.
    MARKERS = {
        "wp19": ("pgx/verification",
                 "docs/architecture/wp19-verification.md"),
        # Corrected at WP-21, in step with the generator. WP-18 guessed two
        # package names that were never built: the metric engine lives in
        # ``pgx/validation`` because it depends on the partition it must not
        # violate. A marker list that keeps guessing reports a finished work
        # package as unstarted forever.
        "wp21": ("pgx/validation/benchmark.py", "pgx/validation/metrics.py",
                 "docs/architecture/wp21-validation-metrics.md"),
        # Corrected at WP-22, in step with the generator, and for the same
        # reason WP-21's was: a bare package directory would have reported
        # started for an empty ``__init__.py``. The protocol document is in
        # the list because a review module without its protocol is not one.
        "wp22": ("pgx/expert_review/service.py",
                 "pgx/expert_review/protocol.py",
                 "docs/validation/expert-protocol.md",
                 "docs/architecture/wp22-expert-review.md"),
    }

    @classmethod
    def setUpClass(cls):
        cls.status = json.loads(
            _read("data/validation/wp18-real-gate-status.json"))

    def _present(self, package):
        """The markers that exist, as a set.

        A set rather than a list: the generator reports them in the order it
        declares them, which is deterministic but is not sorted, and pinning
        that order here would make this test fail if somebody reordered a
        tuple without changing what it means.
        """
        return {path for path in self.MARKERS[package]
                if os.path.exists(os.path.join(REPO_ROOT,
                                               *path.split("/")))}

    def test_each_flag_agrees_with_the_filesystem(self):
        """The property a pinned constant was standing in for."""
        for package in sorted(self.MARKERS):
            with self.subTest(package=package):
                present = self._present(package)
                self.assertEqual(
                    set(self.status["%s_markers_found" % package]), present)
                self.assertEqual(self.status["%s_started" % package],
                                 bool(present))

    def test_the_marker_list_is_deterministic(self):
        """Whatever the order is, it is the same order every time - otherwise
        the artifact would change on a rebuild for no reason."""
        from pgx.validation.gate_status import build_wp18_gate_status
        first = build_wp18_gate_status(REPO_ROOT)
        second = build_wp18_gate_status(REPO_ROOT)
        for package in sorted(self.MARKERS):
            field = "%s_markers_found" % package
            with self.subTest(package=package):
                self.assertEqual(first[field], second[field])

    def test_wp22_started_and_produced_no_expert_review(self):
        """WP-22 started. No amount of review machinery makes a review exist.

        This assertion used to read ``wp22_started is False``, which was true
        until it was not - the same shelf life ``wp19_started`` and
        ``wp21_started`` had before it. The pair below is the durable claim:
        the work package began, and the human act it exists to record has
        still not happened.
        """
        self.assertTrue(self.status["wp22_started"])
        self.assertTrue(self.status["wp22_markers_found"])
        self.assertFalse(self.status["expert_review_performed"])
        self.assertIsNone(self.status["expert_reviewed_case_count"])

    def test_wp21_started_and_produced_no_validation_result(self):
        """The two facts this document must keep apart.

        ``wp21_started`` is now true and every result field is still empty.
        A reader who conflated them would conclude that metrics existing
        means metrics were computed.
        """
        self.assertTrue(self.status["wp21_started"])
        self.assertTrue(self.status["validation_metrics_implemented"])
        self.assertIsNone(self.status["validation_metric_count"])
        self.assertEqual(self.status["numeric_validation_metric_count"], 0)
        self.assertFalse(self.status["benchmark_executed"])
        self.assertNotEqual(self.status["benchmark_gate_status"], "PASS")
        self.assertFalse(self.status["may_report_validation_result"])

    def test_the_review_module_existing_reports_no_review(self):
        """``pgx/expert_review`` and the protocol document have now left the
        forbidden list too, and this is the third time this class has had to
        make the same correction.

        The list once held ``pgx/verification``, then the WP-21 metric
        modules, then these. Each time the assertion was "this software does
        not exist", and each time it was built - because each of them was
        always buildable. The property actually worth defending was never
        absence. It is that **software existing reports no human act**: a
        review module can be implemented in full and the number of reviews an
        expert has performed is still zero, because that number is not a
        function of any file in this repository.

        So the successor asserts the separation directly. The module is
        present, the flag that says so is true, and every field that would
        describe a review having happened is false or null.
        """
        for present in ("pgx/expert_review/service.py",
                        "pgx/expert_review/protocol.py",
                        "docs/validation/expert-protocol.md"):
            with self.subTest(path=present):
                self.assertTrue(
                    os.path.exists(os.path.join(REPO_ROOT,
                                                *present.split("/"))))
        self.assertTrue(self.status["expert_review_implemented"])
        self.assertFalse(self.status["expert_review_protocol_approved"])
        self.assertFalse(self.status["expert_review_performed"])
        # Null, not zero. Implementing the module did not turn "nobody
        # looked at a store" into "a store was looked at and held none".
        self.assertIsNone(self.status["expert_reviewed_case_count"])
        self.assertFalse(self.status["may_report_validation_result"])

    def test_no_review_package_appears_under_another_name(self):
        """The half of the original assertion that is still meaningful.

        WP-22 built exactly one review module in one place. A second package
        called ``pgx/review`` would be an ungoverned copy of the workflow,
        outside the protocol, the audit chain and the blinding structure.
        """
        for forbidden in ("pgx/review", "pgx/expert_reviews",
                          "pgx/validation/expert_review.py"):
            with self.subTest(path=forbidden):
                self.assertFalse(
                    os.path.exists(os.path.join(REPO_ROOT,
                                                *forbidden.split("/"))))

    def test_wp19_starting_changed_nothing_about_the_validation_partition(self):
        """A software verification system does not create a validation case.

        The counts below are WP-18's, and they read the same after WP-19 and
        after WP-21 as before either: seven development cases, no holdout, no
        computed metric, no expert review. WP-21 built the machinery that
        would compute one; it did not create a case for it to run on.
        """
        self.assertEqual(self.status["development_case_count"], 7)
        self.assertEqual(self.status["holdout_case_count"], 0)
        self.assertIsNone(self.status["validation_metric_count"])
        self.assertIsNone(self.status["expert_reviewed_case_count"])
        self.assertFalse(self.status["may_report_validation_result"])
