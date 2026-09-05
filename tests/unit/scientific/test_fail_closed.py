# -*- coding: utf-8 -*-
"""The rules that make missing information block rather than permit.

Each test names the way a project accidentally gives itself permission it never
obtained, and shows that this package refuses it:

* a configuration file that approves a source by asserting it is approved;
* a reuse question nobody answered reading as a yes;
* an unregistered source having no restrictions rather than no permissions;
* a failed retrieval being filed as evidence;
* an expired approval still counting.
"""

from __future__ import annotations

import datetime as _dt
import unittest

from pgx.domain.enums import SourceRole
from pgx.domain.errors import InvalidTemporalValueError
from pgx.scientific.errors import (
    ReviewIntegrityError,
    SourcePolicyValidationError,
    UnknownSourceError,
)
from pgx.scientific.models import (
    ClaimCategory,
    EvidenceType,
    EvidenceVerificationStatus,
    ReuseDimension,
    ReuseMatrix,
    ReusePermission,
    ReviewDecision,
    ReviewRecord,
    SourceEvidenceReference,
    SourcePolicyRecord,
    SourcePolicyStatus,
)
from pgx.scientific.validation import (
    PolicyIssueCode,
    blocking_issues,
    validate_source,
)

from tests.unit.scientific import _fixtures as fx


class TestAConfigurationFileCannotApproveASource(unittest.TestCase):
    """The single most important invariant in this package."""

    def test_an_approving_status_without_a_review_is_refused(self):
        with self.assertRaises(ReviewIntegrityError) as caught:
            SourcePolicyRecord(
                source_key="fixture.forged", display_name="Forged",
                role=SourceRole.PRIMARY_GUIDELINE,
                status=SourcePolicyStatus.APPROVED)
        self.assertIn("review", str(caught.exception).lower())

    def test_a_restricted_approval_needs_a_restricted_decision(self):
        with self.assertRaises(ReviewIntegrityError):
            SourcePolicyRecord(
                source_key="fixture.mismatch", display_name="Mismatch",
                role=SourceRole.PRIMARY_GUIDELINE,
                status=SourcePolicyStatus.APPROVED_WITH_RESTRICTIONS,
                evidence=(fx.verified_evidence(),),
                review=fx.approving_review())

    def test_an_approval_without_verified_evidence_is_refused(self):
        """A named reviewer is necessary and not sufficient: evidence too."""
        with self.assertRaises(ReviewIntegrityError):
            SourcePolicyRecord(
                source_key="fixture.noevidence", display_name="No evidence",
                role=SourceRole.PRIMARY_GUIDELINE,
                status=SourcePolicyStatus.APPROVED,
                evidence=(fx.blocked_evidence(),),
                review=fx.approving_review())

    def test_a_review_cannot_approve_without_citing_evidence(self):
        with self.assertRaises(ReviewIntegrityError):
            ReviewRecord(
                decision=ReviewDecision.APPROVE,
                reviewer_name=fx.TEST_SCIENTIFIC_REVIEWER,
                reviewer_role="fixture", decided_at=fx.NOW)

    def test_a_restricted_review_must_name_its_restrictions(self):
        with self.assertRaises(ReviewIntegrityError):
            ReviewRecord(
                decision=ReviewDecision.APPROVE_WITH_RESTRICTIONS,
                reviewer_name=fx.TEST_SCIENTIFIC_REVIEWER,
                reviewer_role="fixture", decided_at=fx.NOW,
                evidence_urls=(fx.FIXTURE_TERMS_URL,))

    def test_an_unapproved_record_may_not_claim_categories(self):
        """What a source may be cited for is decided at review, not before."""
        with self.assertRaises(ReviewIntegrityError):
            SourcePolicyRecord(
                source_key="fixture.early", display_name="Early",
                role=SourceRole.PRIMARY_GUIDELINE,
                permitted_claim_categories=(ClaimCategory.PHENOTYPE_MAPPING,))

    def test_internal_bookkeeping_can_never_be_scientific_evidence(self):
        with self.assertRaises(ReviewIntegrityError):
            SourcePolicyRecord(
                source_key="fixture.internal", display_name="Internal",
                role=SourceRole.INTERNAL_SYSTEM,
                status=SourcePolicyStatus.APPROVED,
                permitted_claim_categories=(ClaimCategory.PHENOTYPE_MAPPING,),
                evidence=(fx.verified_evidence(),),
                review=fx.approving_review())


class TestUnknownBlocksExactlyAsProhibitedDoes(unittest.TestCase):

    def test_an_absent_dimension_reads_as_unknown(self):
        matrix = ReuseMatrix({ReuseDimension.LOCAL_STORAGE:
                              ReusePermission.ALLOWED})
        self.assertIs(matrix.permission(ReuseDimension.COMMERCIAL_USE),
                      ReusePermission.UNKNOWN)

    def test_the_default_matrix_answers_nothing(self):
        matrix = ReuseMatrix.unknown()
        self.assertEqual(len(matrix.unknown_dimensions), len(ReuseDimension))
        self.assertFalse(matrix.is_fully_answered)

    def test_unknown_is_not_permitted(self):
        self.assertFalse(ReuseMatrix.unknown().is_permitted(
            ReuseDimension.LOCAL_STORAGE))

    def test_the_matrix_cannot_be_edited_after_construction(self):
        """A frozen dataclass holding a plain dict is not immutable.

        ``matrix.permissions[d] = ALLOWED`` would be a licensing decision made
        by assignment, so the mapping is stored behind a read-only proxy.
        """
        matrix = ReuseMatrix.unknown()
        with self.assertRaises(TypeError):
            matrix.permissions[ReuseDimension.LOCAL_STORAGE] = \
                ReusePermission.ALLOWED
        self.assertIs(matrix.permission(ReuseDimension.LOCAL_STORAGE),
                      ReusePermission.UNKNOWN)

    def test_the_matrix_does_not_alias_the_mapping_it_was_given(self):
        source = {ReuseDimension.LOCAL_STORAGE: ReusePermission.ALLOWED}
        matrix = ReuseMatrix(source)
        source[ReuseDimension.LOCAL_STORAGE] = ReusePermission.PROHIBITED
        self.assertIs(matrix.permission(ReuseDimension.LOCAL_STORAGE),
                      ReusePermission.ALLOWED)

    def test_restricted_is_not_permitted_either(self):
        matrix = ReuseMatrix({ReuseDimension.LOCAL_STORAGE:
                              ReusePermission.RESTRICTED})
        self.assertFalse(matrix.is_permitted(ReuseDimension.LOCAL_STORAGE))

    def test_unknown_and_prohibited_both_block_a_source(self):
        unknown = fx.approved_source(
            source_key="fixture.unknown",
            reuse=ReuseMatrix({ReuseDimension.LOCAL_STORAGE:
                               ReusePermission.ALLOWED}))
        prohibited = fx.approved_source(
            source_key="fixture.prohibited",
            reuse=ReuseMatrix({d: ReusePermission.PROHIBITED
                               for d in ReuseDimension}))
        for record in (unknown, prohibited):
            with self.subTest(source=record.source_key):
                self.assertTrue(blocking_issues(validate_source(record, fx.NOW)))

    def test_the_two_are_reported_under_different_codes(self):
        """Same effect, different next step for the reviewer."""
        unknown = fx.approved_source(
            source_key="fixture.u",
            reuse=ReuseMatrix({ReuseDimension.LOCAL_STORAGE:
                               ReusePermission.ALLOWED}))
        prohibited = fx.approved_source(
            source_key="fixture.p",
            reuse=ReuseMatrix({d: ReusePermission.PROHIBITED
                               for d in ReuseDimension}))
        unknown_codes = {i.code for i in validate_source(unknown, fx.NOW)}
        prohibited_codes = {i.code for i in validate_source(prohibited, fx.NOW)}
        self.assertIn(PolicyIssueCode.REUSE_PERMISSION_UNKNOWN, unknown_codes)
        self.assertIn(PolicyIssueCode.REUSE_PERMISSION_PROHIBITED,
                      prohibited_codes)
        self.assertNotIn(PolicyIssueCode.REUSE_PERMISSION_PROHIBITED,
                         unknown_codes)


class TestAnUnregisteredSourceHasNoPermissions(unittest.TestCase):

    def setUp(self):
        self.registry = fx.registry(fx.approved_source())

    def test_get_returns_none_rather_than_a_default_record(self):
        self.assertIsNone(self.registry.get("fixture.absent"))

    def test_require_raises_and_names_the_key(self):
        with self.assertRaises(UnknownSourceError) as caught:
            self.registry.require("fixture.absent")
        self.assertEqual(caught.exception.source_key, "fixture.absent")

    def test_an_unregistered_source_answers_unknown_not_allowed(self):
        self.assertIs(
            self.registry.permission("fixture.absent", ReuseDimension.LOCAL_STORAGE),
            ReusePermission.UNKNOWN)

    def test_it_supports_no_claim_category(self):
        self.assertEqual(
            self.registry.sources_supporting(
                ClaimCategory.PHENOTYPE_MAPPING, fx.NOW), ())


class TestAFailedRetrievalIsNotEvidence(unittest.TestCase):

    def test_a_blocked_reference_must_say_why(self):
        with self.assertRaises(SourcePolicyValidationError):
            SourceEvidenceReference(
                evidence_type=EvidenceType.OFFICIAL_TERMS_PAGE,
                official_url=fx.FIXTURE_TERMS_URL,
                verification=EvidenceVerificationStatus.BLOCKED)

    def test_nothing_unobtained_can_be_verified(self):
        with self.assertRaises(SourcePolicyValidationError):
            SourceEvidenceReference(
                evidence_type=EvidenceType.NOT_OBTAINED,
                official_url=fx.FIXTURE_TERMS_URL, retrieved_at=fx.NOW,
                verification=EvidenceVerificationStatus.VERIFIED)

    def test_a_verified_reference_must_name_what_and_when(self):
        with self.assertRaises(SourcePolicyValidationError):
            SourceEvidenceReference(
                evidence_type=EvidenceType.OFFICIAL_TERMS_PAGE,
                verification=EvidenceVerificationStatus.VERIFIED)

    def test_a_blocked_retrieval_is_reported_as_a_blocker(self):
        codes = {i.code for i in blocking_issues(
            validate_source(fx.pending_source(), fx.NOW))}
        self.assertIn(PolicyIssueCode.EVIDENCE_RETRIEVAL_BLOCKED, codes)

    def test_a_record_whose_only_evidence_is_blocked_reports_both_problems(self):
        """The block must surface even though no official artefact is named."""
        codes = {i.code for i in validate_source(fx.pending_source(), fx.NOW)}
        self.assertIn(PolicyIssueCode.MISSING_OFFICIAL_EVIDENCE, codes)
        self.assertIn(PolicyIssueCode.EVIDENCE_RETRIEVAL_BLOCKED, codes)

    def test_an_http_url_is_refused(self):
        with self.assertRaises(SourcePolicyValidationError):
            SourceEvidenceReference(
                evidence_type=EvidenceType.OFFICIAL_TERMS_PAGE,
                official_url="http://fixture.invalid/terms")

    def test_the_source_text_itself_is_not_storable(self):
        """Summaries are short by construction; a pasted terms page is not."""
        with self.assertRaises(SourcePolicyValidationError):
            SourceEvidenceReference(
                evidence_type=EvidenceType.OFFICIAL_TERMS_PAGE,
                official_url=fx.FIXTURE_TERMS_URL,
                summary="x" * 1001)


class TestAnExpiredApprovalIsNoApproval(unittest.TestCase):

    def setUp(self):
        self.record = fx.approved_source(expires_at=fx.LATER)

    def test_it_is_approved_before_expiry(self):
        self.assertIs(self.record.effective_status(fx.NOW),
                      SourcePolicyStatus.APPROVED)
        self.assertTrue(self.record.may_support_claim(
            ClaimCategory.PRIMARY_GUIDELINE_RECOMMENDATION, fx.NOW))

    def test_it_reverts_to_pending_after_expiry(self):
        after = fx.LATER + _dt.timedelta(seconds=1)
        self.assertIs(self.record.effective_status(after),
                      SourcePolicyStatus.PENDING_REVIEW)

    def test_it_supports_no_claim_after_expiry(self):
        after = fx.LATER + _dt.timedelta(seconds=1)
        self.assertFalse(self.record.may_support_claim(
            ClaimCategory.PRIMARY_GUIDELINE_RECOMMENDATION, after))

    def test_expiry_is_reported_with_its_own_code(self):
        after = fx.LATER + _dt.timedelta(seconds=1)
        codes = {i.code for i in validate_source(self.record, after)}
        self.assertIn(PolicyIssueCode.REVIEW_EXPIRED, codes)

    def test_a_review_expiring_before_it_was_decided_is_refused(self):
        with self.assertRaises(ReviewIntegrityError):
            ReviewRecord(
                decision=ReviewDecision.APPROVE,
                reviewer_name=fx.TEST_SCIENTIFIC_REVIEWER,
                reviewer_role="fixture", decided_at=fx.LATER,
                evidence_urls=(fx.FIXTURE_TERMS_URL,), expires_at=fx.NOW)


class TestAnInactiveSourceBacksNothing(unittest.TestCase):

    def test_deactivating_an_approved_source_stops_it_supporting_claims(self):
        approved = fx.approved_source()
        inactive = SourcePolicyRecord(
            source_key=approved.source_key, display_name=approved.display_name,
            role=approved.role, status=approved.status,
            acquisition_mode=approved.acquisition_mode,
            version_policy=approved.version_policy,
            citation_policy=approved.citation_policy,
            license_identifier=approved.license_identifier,
            reuse=approved.reuse,
            permitted_claim_categories=approved.permitted_claim_categories,
            evidence=approved.evidence, review=approved.review, active=False)
        self.assertFalse(inactive.may_support_claim(
            ClaimCategory.PRIMARY_GUIDELINE_RECOMMENDATION, fx.NOW))
        codes = {i.code for i in validate_source(inactive, fx.NOW)}
        self.assertIn(PolicyIssueCode.SOURCE_INACTIVE, codes)


class TestNaiveTimestampsAreRefused(unittest.TestCase):
    """An instant without an offset names a different moment per machine."""

    def test_a_naive_review_instant_is_refused(self):
        with self.assertRaises(InvalidTemporalValueError):
            ReviewRecord(
                decision=ReviewDecision.REJECT,
                reviewer_name=fx.TEST_SCIENTIFIC_REVIEWER,
                reviewer_role="fixture",
                decided_at=_dt.datetime(2026, 8, 30, 12, 0, 0))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
