# -*- coding: utf-8 -*-
"""Release pinning and the assessment service sequence (section B).

The property this file exists for is small and easy to lose: the active-release
pointer is read **once**, before calculation, and never again. Everything after
that point works from a value. An activation committing halfway through an
assessment therefore cannot change the answer, not because the service checks
for it but because there is nothing left to check - the running calculation
holds an object the pointer can no longer reach.

Everything else here is failing closed. A release that is not ACTIVE, a
manifest that does not hash to what the release pins, a coverage manifest
naming a different ruleset, two coverage manifests claiming the same ruleset:
each is a refusal with a stable code, and none of them produces a partial
result that a caller might read as a small answer rather than no answer.
"""

from __future__ import annotations

import dataclasses
import unittest

from pgx.application.assessment_models import PinnedAssessmentRelease
from pgx.application.assessment_service import (AssessmentService,
                                                ReleaseContextResolver)
from pgx.domain.claims import DEFAULT_CLAIM_BOUNDARY, OperationMode
from pgx.domain.enums import AttentionLevel, ReleaseStatus
from pgx.engine.risk_errors import (AssessmentArtifactError,
                                    AssessmentEngineError,
                                    AssessmentInputError,
                                    AssessmentReleaseError)
from tests.fixtures.wp13.synthetic import (DRUG_1, DRUG_2, GENE_1, GENE_2,
                                           synthetic_manifest)
from tests.fixtures.wp14.synthetic import (NOW, TEST_ACTOR,
                                           synthetic_claim_boundary,
                                           synthetic_release_bundle)
from tests.unit.application._assessment_support import SyntheticAssessmentWorld


class PinningCase(unittest.TestCase):

    def setUp(self):
        self.world = SyntheticAssessmentWorld()
        self.addCleanup(self.world.close)


class TestTheReleaseIsPinnedExactlyOnce(PinningCase):

    def test_one_execution_reads_the_pointer_once(self):
        self.world.execute(medications=[DRUG_1])
        self.assertEqual(self.world.resolver.pointer_reads, 1)

    def test_a_dry_run_reads_the_pointer_once(self):
        self.world.dry_run(medications=[DRUG_1])
        self.assertEqual(self.world.resolver.pointer_reads, 1)

    def test_a_multi_medication_run_still_reads_it_once(self):
        """Not once per medication, and not once per axis. If pinning happened
        inside the loop, two medications could be assessed against two
        different releases and the result would name only one of them."""
        self.world.execute(medications=[DRUG_1, DRUG_2])
        self.assertEqual(self.world.resolver.pointer_reads, 1)

    def test_the_pinned_generation_is_recorded(self):
        result = self.world.execute(medications=[DRUG_1])
        self.assertEqual(result.pinned.active_pointer_generation, 1)
        self.assertEqual(
            result.computation.provenance.active_pointer_generation, 1)


class TestAPointerMoveAfterPinningChangesNothing(PinningCase):

    def test_the_result_is_unchanged_when_the_pointer_moves_afterwards(self):
        first = self.world.execute(medications=[DRUG_1])
        self.world.resolver.move_pointer()
        second = self.world.execute(medications=[DRUG_1])
        # The calculated facts are identical; only the recorded generation
        # differs, because the second run pinned a later pointer.
        self.assertEqual(first.computation.overall_attention,
                         second.computation.overall_attention)
        self.assertEqual(first.computation.overall_coverage,
                         second.computation.overall_coverage)
        self.assertEqual(len(first.computation.findings),
                         len(second.computation.findings))
        self.assertEqual(second.pinned.active_pointer_generation, 2)

    def test_a_pinned_context_survives_the_pointer_moving_underneath_it(self):
        """The value the service holds is not a lookup. Once resolved, moving
        the pointer cannot reach it."""
        pinned = self.world.resolver.resolve()
        before = pinned.provenance.to_json()
        self.world.resolver.move_pointer(
            release=synthetic_release_bundle(status=ReleaseStatus.RETIRED))
        self.assertEqual(pinned.provenance.to_json(), before)
        self.assertEqual(pinned.active_pointer_generation, 1)

    def test_the_stored_assessment_names_the_release_pinned_at_start(self):
        result = self.world.execute(medications=[DRUG_1])
        pinned_id = result.pinned.release_public_id
        self.world.resolver.move_pointer()
        stored = self.world.store.row(result.assessment_id)
        self.assertEqual(stored["provenance"].release_public_id, pinned_id)
        self.assertEqual(stored["provenance"].active_pointer_generation, 1)


class TestTheReleaseMustBeActiveAndVerified(PinningCase):

    def _expect(self, code, **kwargs):
        with self.assertRaises(AssessmentEngineError) as caught:
            self.world.execute(**kwargs)
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def test_no_active_release_is_refused(self):
        self.world.resolver.release = None
        self._expect("ASSESSMENT_ACTIVE_RELEASE_MISSING", medications=[DRUG_1])

    def test_a_draft_release_is_refused(self):
        self.world.resolver.release = synthetic_release_bundle(
            status=ReleaseStatus.DRAFT)
        self._expect("ASSESSMENT_RELEASE_NOT_ACTIVE", medications=[DRUG_1])

    def test_a_rolled_back_release_is_refused(self):
        self.world.resolver.release = synthetic_release_bundle(
            status=ReleaseStatus.ROLLED_BACK)
        self._expect("ASSESSMENT_RELEASE_NOT_ACTIVE", medications=[DRUG_1])

    def test_a_retired_release_is_refused(self):
        self.world.resolver.release = synthetic_release_bundle(
            status=ReleaseStatus.RETIRED)
        self._expect("ASSESSMENT_RELEASE_NOT_ACTIVE", medications=[DRUG_1])

    def test_an_explicitly_requested_active_release_is_accepted(self):
        result = self.world.execute(
            medications=[DRUG_1],
            release_id=self.world.release.public_id.to_json())
        self.assertEqual(result.pinned.release_public_id,
                         self.world.release.public_id.to_json())

    def test_requesting_a_release_that_is_not_active_is_refused(self):
        """Historical replay is not part of WP-14: a new assessment executes
        only against a release that is ACTIVE when pinned."""
        self._expect("ASSESSMENT_RELEASE_NOT_ACTIVE", medications=[DRUG_1],
                     release_id="PGX-REL-19700101-001")

    def test_a_tampered_manifest_is_refused(self):
        self.world.resolver.release = synthetic_release_bundle(
            manifest_hash="sha256:" + "a" * 64)
        self._expect("ASSESSMENT_RELEASE_MANIFEST_INVALID",
                     medications=[DRUG_1])

    def test_a_missing_coverage_manifest_is_refused(self):
        self.world.resolver.coverage_manifests = []
        self._expect("ASSESSMENT_COVERAGE_MANIFEST_MISSING",
                     medications=[DRUG_1])

    def test_two_coverage_manifests_for_one_ruleset_are_refused(self):
        """Which one governs is not a question a resolver may answer by
        picking the first."""
        other = synthetic_manifest(self.world.frozen,
                                   expected_extra_gene=False)
        self.world.resolver.coverage_manifests = [self.world.manifest, other]
        self._expect("ASSESSMENT_COVERAGE_MANIFEST_INVALID",
                     medications=[DRUG_1])

    def test_a_failed_pin_persists_nothing(self):
        self.world.resolver.release = None
        with self.assertRaises(AssessmentReleaseError):
            self.world.execute(medications=[DRUG_1])
        self.assertEqual(len(self.world.store), 0)

    def test_a_failed_pin_writes_a_refusal_audit_and_no_success(self):
        self.world.resolver.release = None
        with self.assertRaises(AssessmentReleaseError):
            self.world.execute(medications=[DRUG_1])
        self.assertEqual(self.world.audit.actions, ("ASSESSMENT_REFUSED",))
        self.assertNotIn("ASSESSMENT_COMPLETED", self.world.audit.actions)

    def test_a_refusal_audit_carries_a_code_and_no_case_content(self):
        self.world.resolver.release = None
        with self.assertRaises(AssessmentReleaseError):
            self.world.execute(medications=[DRUG_1],
                               phenotypes={GENE_1: "POOR"})
        record = self.world.audit.records[0]
        self.assertEqual(record["code"], "ASSESSMENT_ACTIVE_RELEASE_MISSING")
        text = repr(record)
        for forbidden in ("POOR", GENE_1, DRUG_1, "TEST-CASE-1"):
            with self.subTest(leak=forbidden):
                self.assertNotIn(forbidden, text)


class TestTheServiceReverifiesWhatTheResolverAsserted(PinningCase):
    """The resolver is an injected port. A test double, a future
    implementation or a refactor could weaken it, and this is the layer that
    must not execute on artifacts that disagree."""

    def _pinned_with(self, **overrides):
        pinned = self.world.resolver.resolve()
        provenance = dataclasses.replace(pinned.provenance, **overrides)
        return dataclasses.replace(pinned, provenance=provenance)

    def _service_refuses(self, pinned, code):
        class Fixed(ReleaseContextResolver):
            def resolve(self, *, requested_release_public_id=None):
                return pinned

        service = AssessmentService(
            release_resolver=Fixed(), uow_factory=None,
            claim_boundary=self.world.boundary, clock=lambda: NOW)
        with self.assertRaises(AssessmentEngineError) as caught:
            service.dry_run(self.world.input(medications=[DRUG_1]))
        self.assertEqual(caught.exception.code, code)

    def test_a_coverage_manifest_naming_another_ruleset_is_refused(self):
        self._service_refuses(
            self._pinned_with(ruleset_public_id="PGX-RULESET-19700101-001"),
            "ASSESSMENT_VERSION_MISMATCH")

    def test_a_coverage_manifest_naming_another_dataset_is_refused(self):
        self._service_refuses(
            self._pinned_with(dataset_public_id="PGX-DATA-19700101-001"),
            "ASSESSMENT_VERSION_MISMATCH")

    def test_a_coverage_manifest_naming_another_evidence_build_is_refused(self):
        self._service_refuses(
            self._pinned_with(evidence_build_content_hash="sha256:" + "b" * 64),
            "ASSESSMENT_VERSION_MISMATCH")

    def test_a_coverage_manifest_hash_that_disagrees_is_refused(self):
        self._service_refuses(
            self._pinned_with(coverage_manifest_hash="sha256:" + "c" * 64),
            "ASSESSMENT_COVERAGE_MANIFEST_INVALID")

    def test_a_ruleset_hash_that_disagrees_is_refused(self):
        self._service_refuses(
            self._pinned_with(ruleset_content_hash="sha256:" + "d" * 64),
            "ASSESSMENT_VERSION_MISMATCH")

    def test_a_resolver_returning_the_wrong_type_is_refused(self):
        class Wrong(ReleaseContextResolver):
            def resolve(self, *, requested_release_public_id=None):
                return {"release": "PGX-REL-29991231-001"}

        service = AssessmentService(
            release_resolver=Wrong(), claim_boundary=self.world.boundary,
            clock=lambda: NOW)
        with self.assertRaises(AssessmentReleaseError) as caught:
            service.dry_run(self.world.input(medications=[DRUG_1]))
        self.assertEqual(caught.exception.code,
                         "ASSESSMENT_RELEASE_NOT_ACTIVE")

    def test_a_resolver_returning_none_is_refused(self):
        class Empty(ReleaseContextResolver):
            def resolve(self, *, requested_release_public_id=None):
                return None

        service = AssessmentService(
            release_resolver=Empty(), claim_boundary=self.world.boundary,
            clock=lambda: NOW)
        with self.assertRaises(AssessmentReleaseError) as caught:
            service.dry_run(self.world.input(medications=[DRUG_1]))
        self.assertEqual(caught.exception.code,
                         "ASSESSMENT_ACTIVE_RELEASE_MISSING")


class TestTheRequestCannotOverrideThePinnedVersions(PinningCase):
    """Version metadata comes from the release context, never from the
    request. A caller who could name their own ruleset hash could make a
    stored assessment claim provenance it never had."""

    def test_the_input_contract_has_no_version_field(self):
        import dataclasses as _dc
        from pgx.application.assessment_models import AssessmentInput
        names = {field.name for field in _dc.fields(AssessmentInput)}
        for forbidden in ("software_version", "dataset_version",
                          "ruleset_version", "release_manifest_hash",
                          "coverage_manifest_hash", "evidence_build_hash",
                          "ruleset_content_hash", "output_hash"):
            with self.subTest(field=forbidden):
                self.assertNotIn(forbidden, names)

    def test_the_only_release_field_a_caller_may_set_is_which_one(self):
        import dataclasses as _dc
        from pgx.application.assessment_models import AssessmentInput
        names = {field.name for field in _dc.fields(AssessmentInput)}
        release_fields = {name for name in names if "release" in name}
        self.assertEqual(release_fields, {"requested_release_public_id"})

    def test_the_versions_come_from_the_pinned_context(self):
        result = self.world.execute(medications=[DRUG_1])
        provenance = result.computation.provenance
        self.assertEqual(provenance.ruleset_content_hash,
                         self.world.frozen.ruleset_content_hash)
        self.assertEqual(provenance.coverage_manifest_hash,
                         self.world.manifest.content_hash())
        self.assertEqual(provenance.release_manifest_hash,
                         self.world.release.manifest_hash)

    def test_every_pinned_version_is_present(self):
        provenance = self.world.execute(
            medications=[DRUG_1]).computation.provenance.to_json()
        for field in ("release_public_id", "release_manifest_hash",
                      "active_pointer_generation", "software_version_id",
                      "software_version", "software_source_tree_hash",
                      "dataset_version_id", "dataset_public_id",
                      "canonical_build_content_hash", "ruleset_version_id",
                      "ruleset_public_id", "ruleset_content_hash",
                      "evidence_build_key", "evidence_build_content_hash",
                      "coverage_manifest_hash", "protocol_version",
                      "protocol_content_hash", "source_policy_version",
                      "source_policy_content_hash"):
            with self.subTest(field=field):
                self.assertIn(field, provenance)
                self.assertIsNotNone(provenance[field])


class TestTheDefaultServiceRefuses(unittest.TestCase):

    def test_the_default_claim_boundary_stops_execution(self):
        world = SyntheticAssessmentWorld()
        self.addCleanup(world.close)
        service = AssessmentService(
            release_resolver=world.resolver, uow_factory=None,
            claim_boundary=DEFAULT_CLAIM_BOUNDARY, clock=lambda: NOW)
        with self.assertRaises(AssessmentInputError) as caught:
            service.dry_run(world.input(medications=[DRUG_1]))
        self.assertEqual(caught.exception.code,
                         "ASSESSMENT_CLAIM_BOUNDARY_NOT_APPROVED")

    def test_it_refuses_before_reading_the_pointer(self):
        """Nothing is read from a repository before the product is allowed to
        answer at all."""
        world = SyntheticAssessmentWorld()
        self.addCleanup(world.close)
        service = AssessmentService(
            release_resolver=world.resolver, uow_factory=None,
            claim_boundary=DEFAULT_CLAIM_BOUNDARY, clock=lambda: NOW)
        with self.assertRaises(AssessmentInputError):
            service.dry_run(world.input(medications=[DRUG_1]))
        self.assertEqual(world.resolver.pointer_reads, 0)

    def test_the_gate_state_names_the_refusal(self):
        world = SyntheticAssessmentWorld()
        self.addCleanup(world.close)
        service = AssessmentService(
            release_resolver=world.resolver,
            claim_boundary=DEFAULT_CLAIM_BOUNDARY, clock=lambda: NOW)
        state = service.gate_state()
        self.assertFalse(state["may_execute"])
        self.assertEqual(state["refusal_code"],
                         "ASSESSMENT_CLAIM_BOUNDARY_NOT_APPROVED")
        self.assertIn("DRAFT", state["claim_boundary_status"])

    def test_a_synthetic_boundary_permits_execution(self):
        world = SyntheticAssessmentWorld()
        self.addCleanup(world.close)
        self.assertTrue(world.service.gate_state()["may_execute"])
        self.assertIsNone(world.service.gate_state()["refusal_code"])

    def test_pilot_is_disabled_even_in_the_synthetic_boundary(self):
        self.assertNotIn(
            OperationMode.PILOT, synthetic_claim_boundary().enabled_modes)


if __name__ == "__main__":
    unittest.main()
