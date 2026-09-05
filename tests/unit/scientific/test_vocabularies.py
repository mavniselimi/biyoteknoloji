# -*- coding: utf-8 -*-
"""The controlled vocabularies WP-05 is built on.

Each vocabulary is checked for the members that carry a *decision*, not for its
length. A test that only counted members would pass after somebody renamed
``PROHIBITED`` to ``NOT_ALLOWED`` and broke every caller matching on the string.

The two rules worth restating here, because everything downstream rests on
them: ``UNKNOWN`` is a member of the permission vocabulary rather than an
absence, and no vocabulary is ordered.
"""

from __future__ import annotations

import unittest

from pgx.scientific.models import (
    APPROVING_DECISIONS,
    APPROVING_STATUSES,
    AUTOMATED_ACQUISITION_MODES,
    PERMISSIVE_PERMISSIONS,
    REUSE_DIMENSIONS,
    SETTLED_CONFLICT_STATUSES,
    AcquisitionMode,
    ClaimCategory,
    ConflictMateriality,
    ConflictStatus,
    EvidenceType,
    EvidenceVerificationStatus,
    ReuseDimension,
    ReusePermission,
    ReviewDecision,
    SourcePolicyStatus,
)
from pgx.scientific.errors import SourcePolicyValidationError


class TestEveryVocabularyIsClosed(unittest.TestCase):
    """An unrecognised value is refused, never coerced to a default."""

    VOCABULARIES = (
        SourcePolicyStatus, AcquisitionMode, EvidenceType,
        EvidenceVerificationStatus, ClaimCategory, ReusePermission,
        ReuseDimension, ReviewDecision, ConflictStatus, ConflictMateriality,
    )

    def test_an_unknown_string_is_rejected(self):
        for vocabulary in self.VOCABULARIES:
            with self.subTest(vocabulary=vocabulary.__name__):
                with self.assertRaises(SourcePolicyValidationError):
                    vocabulary.parse("NOT-A-MEMBER", "field")

    def test_the_error_lists_the_permitted_values(self):
        with self.assertRaises(SourcePolicyValidationError) as caught:
            ReusePermission.parse("MAYBE", "reuse.LOCAL_STORAGE")
        message = str(caught.exception)
        for member in ReusePermission:
            self.assertIn(member.value, message)

    def test_a_non_string_is_rejected(self):
        with self.assertRaises(SourcePolicyValidationError):
            ReusePermission.parse(1, "field")

    def test_a_member_parses_to_itself(self):
        self.assertIs(ReusePermission.parse(ReusePermission.ALLOWED, "f"),
                      ReusePermission.ALLOWED)

    def test_no_vocabulary_is_ordered(self):
        """Comparing two governance states as magnitudes is a category error."""
        for vocabulary in self.VOCABULARIES:
            members = list(vocabulary)
            with self.subTest(vocabulary=vocabulary.__name__):
                with self.assertRaises(TypeError):
                    members[0] < members[-1]

    def test_every_member_serialises_to_its_own_name(self):
        for vocabulary in self.VOCABULARIES:
            for member in vocabulary:
                with self.subTest(member=member.value):
                    self.assertEqual(str(member), member.value)
                    self.assertEqual(member.value, member.name)


class TestThePermissionVocabulary(unittest.TestCase):

    def test_unknown_is_a_member_rather_than_an_absence(self):
        self.assertIn("UNKNOWN", {m.value for m in ReusePermission})

    def test_only_allowed_and_not_applicable_are_permissive(self):
        """RESTRICTED is not permissive: a condition nobody checked is not met."""
        self.assertEqual(
            set(PERMISSIVE_PERMISSIONS),
            {ReusePermission.ALLOWED, ReusePermission.NOT_APPLICABLE})
        self.assertNotIn(ReusePermission.RESTRICTED, PERMISSIVE_PERMISSIONS)
        self.assertNotIn(ReusePermission.UNKNOWN, PERMISSIVE_PERMISSIONS)
        self.assertNotIn(ReusePermission.PROHIBITED, PERMISSIVE_PERMISSIONS)


class TestTheReuseDimensions(unittest.TestCase):
    """Ten questions, because one yes/no has to lie about at least nine."""

    EXPECTED = (
        "LOCAL_STORAGE", "INTERNAL_ANALYSIS", "DERIVED_WORK_CREATION",
        "AGGREGATED_REDISTRIBUTION", "VERBATIM_REDISTRIBUTION",
        "COMMERCIAL_USE", "AUTOMATED_ACQUISITION", "BULK_DOWNLOAD",
        "THIRD_PARTY_SHARING", "PUBLIC_DISPLAY",
    )

    def test_every_expected_dimension_exists(self):
        self.assertEqual(set(self.EXPECTED), {d.value for d in ReuseDimension})

    def test_the_canonical_order_is_fixed(self):
        """A rendered matrix must read the same on every machine."""
        self.assertEqual(tuple(d.value for d in REUSE_DIMENSIONS), self.EXPECTED)

    def test_acquisition_and_use_are_separate_questions(self):
        """Obtaining records and using them are licensed independently."""
        self.assertIn(ReuseDimension.AUTOMATED_ACQUISITION, REUSE_DIMENSIONS)
        self.assertIn(ReuseDimension.INTERNAL_ANALYSIS, REUSE_DIMENSIONS)


class TestTheStatusVocabulary(unittest.TestCase):

    def test_pending_review_exists_and_is_not_approving(self):
        self.assertNotIn(SourcePolicyStatus.PENDING_REVIEW, APPROVING_STATUSES)

    def test_exactly_two_statuses_permit_publication(self):
        self.assertEqual(
            set(APPROVING_STATUSES),
            {SourcePolicyStatus.APPROVED,
             SourcePolicyStatus.APPROVED_WITH_RESTRICTIONS})

    def test_a_withdrawn_approval_is_not_an_approval(self):
        self.assertNotIn(SourcePolicyStatus.SUSPENDED, APPROVING_STATUSES)

    def test_only_approving_decisions_can_back_an_approving_status(self):
        self.assertEqual(
            set(APPROVING_DECISIONS),
            {ReviewDecision.APPROVE, ReviewDecision.APPROVE_WITH_RESTRICTIONS})
        self.assertNotIn(ReviewDecision.REQUEST_MORE_INFORMATION,
                         APPROVING_DECISIONS)


class TestTheEvidenceVocabulary(unittest.TestCase):

    def test_there_is_no_member_for_a_non_authoritative_source(self):
        """No slot for a snippet, a blog or an encyclopaedia article.

        Giving one a member would invite its use as licensing authority.
        """
        members = {m.value for m in EvidenceType}
        for absent in ("SEARCH_RESULT", "BLOG_POST", "WIKIPEDIA",
                       "THIRD_PARTY_SUMMARY", "SNIPPET"):
            self.assertNotIn(absent, members)

    def test_every_obtainable_type_names_an_official_artefact(self):
        obtainable = {m.value for m in EvidenceType
                      if m is not EvidenceType.NOT_OBTAINED}
        for value in obtainable:
            with self.subTest(value=value):
                self.assertTrue(value.startswith("OFFICIAL_")
                                or value == "DIRECT_WRITTEN_PERMISSION", value)

    def test_a_failed_retrieval_has_its_own_state(self):
        self.assertIn(EvidenceVerificationStatus.BLOCKED,
                      set(EvidenceVerificationStatus))
        self.assertIsNot(EvidenceVerificationStatus.BLOCKED,
                         EvidenceVerificationStatus.VERIFIED)


class TestTheConflictVocabulary(unittest.TestCase):

    def test_undetermined_materiality_exists(self):
        """Deciding a disagreement is harmless must be a recorded decision."""
        self.assertIn(ConflictMateriality.UNDETERMINED, set(ConflictMateriality))

    def test_only_two_statuses_settle_a_conflict(self):
        self.assertEqual(
            set(SETTLED_CONFLICT_STATUSES),
            {ConflictStatus.RESOLVED, ConflictStatus.ACCEPTED_VARIANCE})
        self.assertNotIn(ConflictStatus.UNDER_REVIEW, SETTLED_CONFLICT_STATUSES)


class TestTheAcquisitionVocabulary(unittest.TestCase):

    def test_the_default_mode_decides_nothing(self):
        self.assertIn(AcquisitionMode.NOT_DETERMINED, set(AcquisitionMode))
        self.assertNotIn(AcquisitionMode.NOT_DETERMINED,
                         AUTOMATED_ACQUISITION_MODES)

    def test_a_manual_download_is_not_automated(self):
        self.assertNotIn(AcquisitionMode.MANUAL_DOWNLOAD,
                         AUTOMATED_ACQUISITION_MODES)

    def test_there_is_no_scraping_mode(self):
        """Scraping is not an acquisition mode this project offers."""
        members = {m.value for m in AcquisitionMode}
        for absent in ("SCRAPE", "SCRAPING", "WEB_SCRAPE", "CRAWL"):
            self.assertNotIn(absent, members)


class TestTheClaimCategories(unittest.TestCase):

    def test_a_guideline_recommendation_is_distinct_from_an_annotation(self):
        self.assertNotEqual(ClaimCategory.PRIMARY_GUIDELINE_RECOMMENDATION,
                            ClaimCategory.SUPPORTING_ANNOTATION)

    def test_internal_bookkeeping_is_a_category_of_its_own(self):
        self.assertIn(ClaimCategory.INTERNAL_BOOKKEEPING, set(ClaimCategory))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
