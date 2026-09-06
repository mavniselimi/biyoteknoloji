# -*- coding: utf-8 -*-
"""The candidate track, asked of the real composition root (Wave 4B).

Every assertion here goes through ``apps.api.main.build_provider`` - the
function an ASGI server calls at import - rather than constructing a provider
or a service directly. That distinction is the whole reason this file exists.

Wave 3B's G8 gate constructed a ``CandidateAssessmentService`` itself and
asked that object what release it resolved. It answered correctly and the gate
read PASS, while the deployed application could not reach the candidate
release at all: ``build_deployment_provider`` filled in the WP-23 security
capabilities and left ``assessment_service`` and ``release_resolver`` at
``None``. The browser evidence from the same wave shows the consequence -
``/system`` reporting no active release beside a gate reading PASS.

A test that constructs the object under test cannot catch that. These do.
"""

from __future__ import annotations

import os
import unittest

from apps.api.config import ApiConfigurationError, load_settings
from apps.api.main import build_provider
from pgx.application.runtime_track import RuntimeTrack
from pgx.domain.claims import OperationMode, PermittedInputKind
from pgx.domain.enums import Phenotype
from pgx.engine.phenotype_models import PhenotypeObservation, PhenotypeProfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))


def _settings(track=None):
    """Settings from an explicit mapping, never from process state."""
    environment = {"PGX_API_ENV": "DEVELOPMENT"}
    if track is not None:
        environment["PGX_RUNTIME_TRACK"] = track
    environment["PGX_CANDIDATE_REPO_ROOT"] = REPO
    return load_settings(environment)


def _input(medications, *, care_setting=None, **genes):
    from pgx.application.assessment_models import AssessmentInput

    return AssessmentInput(
        mode=OperationMode.DEMO,
        input_kind=PermittedInputKind.SYNTHETIC_PHENOTYPE_PROFILE,
        profile=PhenotypeProfile(
            observations=tuple(
                PhenotypeObservation(gene_canonical_key="GENE:" + name,
                                     status="NORMALIZED", phenotype=value)
                for name, value in sorted(genes.items())),
            input_contract_version="pgx-wave04b-integration/1"),
        medications=tuple(medications),
        care_setting=care_setting)


class TestTheDefaultDeploymentIsGoverned(unittest.TestCase):
    """A deployment that says nothing runs the approved track."""

    def test_an_unset_variable_composes_the_governed_track(self):
        provider = build_provider(_settings())
        self.assertIs(provider.runtime_track, RuntimeTrack.GOVERNED)

    def test_a_governed_deployment_refuses_the_candidate_capabilities(self):
        provider = build_provider(_settings())
        for accessor in ("require_candidate_release",
                         "require_candidate_assessment_service"):
            with self.subTest(accessor=accessor):
                with self.assertRaises(Exception) as caught:
                    getattr(provider, accessor)()
                self.assertEqual(caught.exception.code,
                                 "RUNTIME_TRACK_MISMATCH")
                self.assertEqual(
                    caught.exception.details["composed_track"], "GOVERNED")

    def test_the_governed_track_is_unchanged_by_the_candidate_track(self):
        """Requirement 12, asserted rather than assumed.

        The governed accessor's failure mode must still be the one it always
        had: no governed release is registered in this repository, so the
        answer is ``ACTIVE_RELEASE_UNAVAILABLE`` - not a track error, and not
        a candidate release standing in.
        """
        provider = build_provider(_settings())
        with self.assertRaises(Exception) as caught:
            provider.require_release()
        self.assertEqual(caught.exception.code, "ACTIVE_RELEASE_UNAVAILABLE")


class TestTheCandidateDeploymentRunsTheCandidateRelease(unittest.TestCase):

    def setUp(self):
        self.provider = build_provider(_settings("CANDIDATE"))

    def test_the_composition_root_composes_the_candidate_track(self):
        self.assertIs(self.provider.runtime_track, RuntimeTrack.CANDIDATE)
        self.assertIsNotNone(self.provider.candidate_release_resolver)
        self.assertIsNotNone(self.provider.candidate_assessment_service)

    def test_it_resolves_the_active_candidate_release(self):
        pinned = self.provider.require_candidate_release()
        self.assertEqual(pinned.release_public_id,
                         "PGX-CANDIDATE-REL-20260906-001")
        self.assertEqual(pinned.manifest["status"], "ACTIVE")
        self.assertEqual(pinned.manifest["authority_state"],
                         "PROJECT_TEAM_PROVISIONAL")
        self.assertEqual(pinned.manifest["review_state"],
                         "PENDING_EXTERNAL_EXPERT_REVIEW")

    def test_the_composed_boundary_reports_itself_unapproved(self):
        """Composition is plumbing, not promotion."""
        self.assertFalse(self.provider.claim_boundary.is_approved)
        self.assertIn("PROVISIONAL", self.provider.claim_boundary.status)

    def test_an_assessment_executes_through_the_composed_service(self):
        service = self.provider.require_candidate_assessment_service()
        result = service.execute(
            _input(("DRUG:clopidogrel",), care_setting="ACS_OR_PCI",
                   CYP2C19=Phenotype.POOR))
        document = result.evaluation.to_json()
        self.assertEqual(document["release_public_id"],
                         "PGX-CANDIDATE-REL-20260906-001")
        self.assertEqual(
            sum(len(m["axes"]) for m in document["medications"]), 1)
        self.assertEqual(document["attention_level"], "HIGH")
        self.assertFalse(result.claim_boundary_is_approved)

    def test_the_composed_service_still_fails_closed(self):
        """The refusals are the release's, not the composition's.

        A composition that quietly answered a question the ruleset refuses
        would be worse than no composition at all.
        """
        service = self.provider.require_candidate_assessment_service()
        document = service.execute(
            _input(("DRUG:clopidogrel",), CYP2C19=Phenotype.POOR)
        ).evaluation.to_json()
        codes = {code for medication in document["medications"]
                 for code in medication["reason_codes"]}
        self.assertIn("CARE_SETTING_NOT_DECLARED", codes)

    def test_a_candidate_deployment_refuses_the_governed_capabilities(self):
        """No silent fallback, in the direction that matters most.

        A candidate deployment that fell back to the governed release would
        serve an approved answer from a deployment nobody approved.
        """
        with self.assertRaises(Exception) as caught:
            self.provider.require_release()
        self.assertEqual(caught.exception.code, "RUNTIME_TRACK_MISMATCH")
        self.assertEqual(caught.exception.details["composed_track"],
                         "CANDIDATE")
        with self.assertRaises(Exception) as caught:
            self.provider.require_assessment_service()
        self.assertEqual(caught.exception.code, "RUNTIME_TRACK_MISMATCH")


class TestAnUnusableTrackIsRefused(unittest.TestCase):

    def test_an_unrecognised_track_never_resolves_to_a_default(self):
        """A near-miss is refused, not rounded to the safe-looking answer.

        ``candidate`` in lower case is refused rather than accepted, and
        ``PILOT`` is refused rather than falling back to ``GOVERNED``. Both
        matter: the first would let a typo select the unapproved track, and
        the second would let one select the approved track by accident.
        """
        for value in ("candidate", "Candidate", "PILOT", "governed",
                      "CANDIDATE,GOVERNED"):
            with self.subTest(value=value):
                with self.assertRaises(ApiConfigurationError):
                    load_settings({"PGX_RUNTIME_TRACK": value})

    def test_surrounding_whitespace_is_tolerated_deliberately(self):
        """One tolerance, chosen and asserted rather than incidental.

        ``PGX_RUNTIME_TRACK="CANDIDATE "`` is what a shell produces from a
        quoting slip, and the trailing space carries no meaning. Nothing else
        is forgiven.
        """
        self.assertIs(load_settings({"PGX_RUNTIME_TRACK": " CANDIDATE "}
                                    ).runtime_track, RuntimeTrack.CANDIDATE)

    def test_the_refusal_never_quotes_the_value(self):
        try:
            load_settings({"PGX_RUNTIME_TRACK": "s3cret-looking-value"})
        except ApiConfigurationError as error:
            self.assertNotIn("s3cret-looking-value", str(error))
        else:  # pragma: no cover - the assertion above is the test
            self.fail("an unusable track was accepted")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
