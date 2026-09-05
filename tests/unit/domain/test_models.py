# -*- coding: utf-8 -*-
"""Domain model invariants and the Evidence -> Rule -> Assessment boundary."""

from __future__ import annotations

import unittest

from tests.unit.domain._fixtures import (
    DIGEST, NAIVE, NOW, AttentionLevel, ComputableRuleId, CurationStatus,
    CuratedInterpretationId, DatasetPublicId, DatasetVersionId, DrugId,
    EvidenceRecordId, GeneId, Phenotype, RuleStatus, SourceRole,
    make_curated_interpretation, make_evidence, make_interpretation, make_rule,
    make_source_entry, make_validated_rule,
)

from pgx.domain.claims import OperationMode
from pgx.domain.enums import (
    CoverageReasonCode, CoverageStatus, DatasetStatus, ReleaseStatus, RulesetStatus,
)
from pgx.domain.errors import (
    DomainInvariantError, InvalidTemporalValueError, LifecycleError, TraceabilityError,
)
from pgx.domain.identifiers import (
    AssessmentId, ReleaseBundleId, ReleasePublicId, RulesetPublicId, RulesetVersionId,
)
from pgx.domain.models import (
    Assessment, AssessmentFinding, CoverageAssessment, DatasetVersion, Drug, Gene,
    ReleaseBundle, RulesetVersion,
)


class TestImmutabilityAndTemporalRules(unittest.TestCase):

    def test_models_are_frozen(self):
        entry = make_source_entry()
        with self.assertRaises(Exception):
            entry.source_key = "changed"

    def test_naive_datetimes_are_rejected_everywhere(self):
        with self.assertRaises(InvalidTemporalValueError):
            make_source_entry(created_at=NAIVE)
        with self.assertRaises(InvalidTemporalValueError):
            make_evidence(created_at=NAIVE)
        with self.assertRaises(InvalidTemporalValueError):
            make_interpretation(created_at=NAIVE)
        with self.assertRaises(InvalidTemporalValueError):
            make_rule(created_at=NAIVE)

    def test_aware_non_utc_datetimes_are_normalised_to_utc(self):
        import datetime as _dt
        istanbul = _dt.timezone(_dt.timedelta(hours=3))
        entry = make_source_entry(created_at=_dt.datetime(2026, 8, 29, 15, 0, tzinfo=istanbul))
        self.assertEqual(entry.created_at.utcoffset(), _dt.timedelta(0))
        self.assertEqual(entry.created_at.hour, 12)

    def test_mutable_collections_are_rejected(self):
        with self.assertRaises(DomainInvariantError):
            make_interpretation(evidence_record_ids=[EvidenceRecordId.new()])
        with self.assertRaises(DomainInvariantError):
            Gene(id=GeneId.new(), normalized_symbol="CYP2C19", preferred_name="CYP2C19",
                 created_at=NOW, aliases=["x"])


class TestSourceRegistryEntry(unittest.TestCase):

    def test_internal_system_source_cannot_be_release_eligible(self):
        with self.assertRaises(DomainInvariantError) as ctx:
            make_source_entry(role=SourceRole.INTERNAL_SYSTEM, release_eligible=True)
        self.assertIn("release-eligible", str(ctx.exception))

    def test_internal_system_source_is_allowed_when_not_release_eligible(self):
        entry = make_source_entry(role=SourceRole.INTERNAL_SYSTEM, release_eligible=False)
        self.assertIs(entry.role, SourceRole.INTERNAL_SYSTEM)

    def test_blank_fields_are_rejected(self):
        for field in ("source_key", "display_name", "version_policy",
                      "license_policy", "citation_policy"):
            with self.assertRaises(DomainInvariantError, msg=field):
                make_source_entry(**{field: "   "})


class TestDatasetAndCanonicalEntities(unittest.TestCase):

    def _dataset(self, **overrides):
        values = dict(
            id=DatasetVersionId.new(), public_id=DatasetPublicId("PGX-DATA-20260829-001"),
            status=DatasetStatus.BUILDING, manifest_hash=DIGEST, created_at=NOW)
        values.update(overrides)
        return DatasetVersion(**values)

    def test_published_dataset_requires_approval_metadata(self):
        with self.assertRaises(LifecycleError):
            self._dataset(status=DatasetStatus.PUBLISHED)
        with self.assertRaises(LifecycleError):
            self._dataset(status=DatasetStatus.PUBLISHED, approved_by="a")
        approved = self._dataset(status=DatasetStatus.PUBLISHED,
                                 approved_by="a", approved_at=NOW)
        self.assertIs(approved.status, DatasetStatus.PUBLISHED)

    def test_manifest_hash_must_be_a_canonical_digest(self):
        for bad in ("abc", "sha256:XYZ", "a" * 64, "sha1:" + "a" * 40):
            with self.assertRaises(DomainInvariantError, msg=bad):
                self._dataset(manifest_hash=bad)

    def test_gene_symbol_must_already_be_normalised(self):
        for bad in ("cyp2c19", " CYP2C19", "CYP2C19 "):
            with self.assertRaises(DomainInvariantError, msg=bad):
                Gene(id=GeneId.new(), normalized_symbol=bad, preferred_name="x",
                     created_at=NOW)

    def test_drug_name_must_already_be_normalised(self):
        for bad in ("Clopidogrel", " clopidogrel"):
            with self.assertRaises(DomainInvariantError, msg=bad):
                Drug(id=DrugId.new(), normalized_name=bad, preferred_name="x",
                     created_at=NOW)


class TestEvidenceCarriesNoClinicalConclusion(unittest.TestCase):
    """EvidenceRecord is source truth and nothing more."""

    FORBIDDEN_FIELDS = (
        "attention_level", "attention", "risk_level", "risk", "severity", "score",
        "dose", "dosage", "treatment", "recommendation", "candidate_preference",
        "safer", "coverage",
    )

    def test_evidence_record_has_no_risk_or_treatment_field(self):
        fields = set(make_evidence().__slots__)
        for forbidden in self.FORBIDDEN_FIELDS:
            self.assertNotIn(forbidden, fields)

    def test_evidence_record_exposes_no_method_producing_a_finding(self):
        record = make_evidence()
        for attribute in dir(record):
            if attribute.startswith("_"):
                continue
            self.assertNotIn("finding", attribute.lower())
            self.assertNotIn("assessment", attribute.lower())

    def test_evidence_requires_a_canonical_raw_hash(self):
        with self.assertRaises(DomainInvariantError):
            make_evidence(raw_hash="not-a-digest")

    def test_evidence_rejects_a_wrong_identifier_type(self):
        from pgx.domain.errors import IdentifierTypeMismatchError
        with self.assertRaises(IdentifierTypeMismatchError):
            make_evidence(gene_id=DrugId.new())


class TestInterpretationRequiresEvidenceAndReview(unittest.TestCase):

    def test_interpretation_requires_at_least_one_evidence_record(self):
        with self.assertRaises(TraceabilityError):
            make_interpretation(evidence_record_ids=())

    def test_duplicate_evidence_references_are_rejected(self):
        shared = EvidenceRecordId.new()
        with self.assertRaises(DomainInvariantError):
            make_interpretation(evidence_record_ids=(shared, shared))

    def test_curated_requires_rationale_reviewer_and_review_time(self):
        for missing in ("rationale", "reviewed_by", "reviewed_at"):
            overrides = {"status": CurationStatus.CURATED,
                         "rationale": "reviewed", "reviewed_by": "r", "reviewed_at": NOW}
            overrides[missing] = None
            with self.assertRaises(LifecycleError, msg=missing):
                make_interpretation(**overrides)

    def test_blank_rationale_does_not_satisfy_curation(self):
        with self.assertRaises(LifecycleError):
            make_interpretation(status=CurationStatus.CURATED, rationale="   ",
                                reviewed_by="r", reviewed_at=NOW)

    def test_a_complete_curated_interpretation_is_accepted(self):
        interpretation = make_curated_interpretation()
        self.assertIs(interpretation.status, CurationStatus.CURATED)
        self.assertTrue(interpretation.is_usable_for_rule_construction)

    def test_only_curated_interpretations_may_back_a_rule(self):
        self.assertFalse(make_interpretation().is_usable_for_rule_construction)


class TestRuleApprovalAndTraceability(unittest.TestCase):

    def test_validated_rule_requires_approval_metadata(self):
        with self.assertRaises(LifecycleError):
            make_rule(status=RuleStatus.VALIDATED)
        with self.assertRaises(LifecycleError):
            make_rule(status=RuleStatus.VALIDATED, approved_by="a")
        with self.assertRaises(LifecycleError):
            make_rule(status=RuleStatus.VALIDATED, approved_at=NOW)

    def test_validated_rule_requires_evidence(self):
        with self.assertRaises((TraceabilityError, LifecycleError)):
            make_rule(status=RuleStatus.VALIDATED, approved_by="a", approved_at=NOW,
                      evidence_record_ids=())

    def test_a_complete_validated_rule_is_executable(self):
        rule = make_validated_rule()
        self.assertTrue(rule.is_executable)

    def test_draft_curated_and_deprecated_rules_are_not_executable(self):
        for status in (RuleStatus.DRAFT, RuleStatus.CURATED, RuleStatus.DEPRECATED):
            self.assertFalse(make_rule(status=status).is_executable, status.value)

    def test_rule_requires_an_interpretation_identity(self):
        from pgx.domain.errors import IdentifierTypeMismatchError
        with self.assertRaises(IdentifierTypeMismatchError):
            make_rule(interpretation_id=None)
        with self.assertRaises(IdentifierTypeMismatchError):
            make_rule(interpretation_id=ComputableRuleId.new())

    def test_condition_must_be_declarative_data_not_code(self):
        with self.assertRaises(DomainInvariantError):
            make_rule(condition="phenotype == 'POOR'")
        with self.assertRaises(DomainInvariantError):
            make_rule(condition=lambda phenotype: True)

    def test_rule_version_must_be_a_positive_integer(self):
        for bad in (0, -1, True, "1", 1.5):
            with self.assertRaises(DomainInvariantError, msg=repr(bad)):
                make_rule(rule_version=bad)


class TestCoverageAndAttentionSeparation(unittest.TestCase):

    def test_non_full_coverage_requires_a_reason_code(self):
        with self.assertRaises(DomainInvariantError):
            CoverageAssessment(drug_id=DrugId.new(), status=CoverageStatus.PARTIAL)

    def test_full_coverage_must_carry_no_reason_code(self):
        with self.assertRaises(DomainInvariantError):
            CoverageAssessment(
                drug_id=DrugId.new(), status=CoverageStatus.FULL,
                reason_codes=(CoverageReasonCode.SOME_AXES_NOT_COVERED,))

    def test_only_full_coverage_permits_no_active_attention(self):
        full = CoverageAssessment(drug_id=DrugId.new(), status=CoverageStatus.FULL)
        self.assertTrue(full.permits_no_active_attention())
        for status in (CoverageStatus.PARTIAL, CoverageStatus.INSUFFICIENT,
                       CoverageStatus.UNSUPPORTED_DRUG,
                       CoverageStatus.UNSUPPORTED_PHENOTYPE,
                       CoverageStatus.SOURCE_CONFLICT):
            coverage = CoverageAssessment(
                drug_id=DrugId.new(), status=status,
                reason_codes=(CoverageReasonCode.SOME_AXES_NOT_COVERED,))
            self.assertFalse(coverage.permits_no_active_attention(), status.value)


class TestFindingTraceability(unittest.TestCase):

    def _finding(self, **overrides):
        values = dict(
            gene_id=GeneId.new(), drug_id=DrugId.new(), phenotype=Phenotype.POOR,
            attention_level=AttentionLevel.HIGH,
            rationale_reference="TEST-CURATION-REVISION-1",
            effect_code="DECREASED_ACTIVATION",
            explanation_code="REDUCED_RESPONSE_ATTENTION", rule_id=ComputableRuleId.new(),
            rule_version=1, evidence_record_ids=(EvidenceRecordId.new(),))
        values.update(overrides)
        return AssessmentFinding(**values)

    def test_finding_requires_evidence(self):
        with self.assertRaises(TraceabilityError):
            self._finding(evidence_record_ids=())

    def test_finding_requires_a_rule_identity(self):
        from pgx.domain.errors import IdentifierTypeMismatchError
        with self.assertRaises(IdentifierTypeMismatchError):
            self._finding(rule_id=CuratedInterpretationId.new())

    def test_finding_cannot_be_not_assessed(self):
        with self.assertRaises(DomainInvariantError):
            self._finding(attention_level=AttentionLevel.NOT_ASSESSED)

    def test_finding_has_no_dose_or_candidate_preference_field(self):
        fields = set(self._finding().__slots__)
        for forbidden in ("dose", "dosage", "treatment", "recommendation",
                          "alternative", "safer", "preferred", "score"):
            self.assertNotIn(forbidden, fields)

    def test_a_finding_names_the_reasoning_behind_its_level(self):
        """WP-14 reconciliation. ``rationale_reference`` points at the approved
        curated interpretation whose reasoning justifies the attention level.
        It is what WP-11's governed outcome actually carries, so it is what a
        finding is required to carry."""
        self.assertEqual(self._finding().rationale_reference,
                         "TEST-CURATION-REVISION-1")
        with self.assertRaises(DomainInvariantError):
            self._finding(rationale_reference="")

    def test_the_scientific_codes_are_optional_and_default_to_absent(self):
        """The governed rule outcome carries no effect or explanation code, so
        a finding computed from one states their absence rather than carrying
        an invented value."""
        finding = self._finding(effect_code=None, explanation_code=None)
        self.assertIsNone(finding.effect_code)
        self.assertIsNone(finding.explanation_code)

    def test_a_supplied_scientific_code_may_not_be_blank(self):
        """Absent and present-but-blank must not be confusable."""
        for field in ("effect_code", "explanation_code"):
            with self.subTest(field=field):
                with self.assertRaises(DomainInvariantError):
                    self._finding(**{field: "   "})

    def test_there_is_no_helper_building_a_finding_from_evidence(self):
        import inspect

        from pgx.domain import models

        source = inspect.getsource(models)
        for forbidden in ("def from_evidence", "def to_finding", "def as_finding",
                          "def build_finding"):
            self.assertNotIn(forbidden, source)


class TestAssessmentRequiresRelease(unittest.TestCase):

    def _assessment(self, **overrides):
        values = dict(
            id=AssessmentId.new(), release_bundle_id=ReleaseBundleId.new(),
            mode=OperationMode.DEMO, input_hash=DIGEST, created_at=NOW)
        values.update(overrides)
        return Assessment(**values)

    def test_assessment_requires_a_release_bundle(self):
        from pgx.domain.errors import IdentifierTypeMismatchError
        with self.assertRaises(IdentifierTypeMismatchError):
            self._assessment(release_bundle_id=None)
        with self.assertRaises(IdentifierTypeMismatchError):
            self._assessment(release_bundle_id=AssessmentId.new())

    def test_assessment_requires_a_canonical_input_hash(self):
        with self.assertRaises(DomainInvariantError):
            self._assessment(input_hash="nope")

    def test_assessment_cannot_be_assembled_from_evidence(self):
        with self.assertRaises(DomainInvariantError):
            self._assessment(findings=(make_evidence(),))

    def test_overall_attention_is_not_assessed_when_there_is_no_finding(self):
        self.assertIs(self._assessment().overall_attention,
                      AttentionLevel.NOT_ASSESSED)

    def test_overall_attention_picks_the_highest_calculated_level(self):
        def finding(level):
            return AssessmentFinding(
                gene_id=GeneId.new(), drug_id=DrugId.new(), phenotype=Phenotype.POOR,
                attention_level=level, rationale_reference="TEST-REV-1",
                effect_code="E", explanation_code="X",
                rule_id=ComputableRuleId.new(), rule_version=1,
                evidence_record_ids=(EvidenceRecordId.new(),))
        assessment = self._assessment(
            findings=(finding(AttentionLevel.LOW), finding(AttentionLevel.HIGH),
                      finding(AttentionLevel.MEDIUM)))
        self.assertIs(assessment.overall_attention, AttentionLevel.HIGH)


class TestRulesetAndReleaseValueObjects(unittest.TestCase):

    def test_validated_ruleset_requires_approval(self):
        with self.assertRaises(LifecycleError):
            RulesetVersion(id=RulesetVersionId.new(),
                           public_id=RulesetPublicId("PGX-RULESET-20260829-001"),
                           status=RulesetStatus.VALIDATED, manifest_hash=DIGEST,
                           created_at=NOW)

    def test_release_bundle_requires_dataset_and_ruleset_identities(self):
        from pgx.domain.errors import IdentifierTypeMismatchError
        from pgx.domain.identifiers import SoftwareVersionId
        with self.assertRaises(IdentifierTypeMismatchError):
            ReleaseBundle(id=ReleaseBundleId.new(),
                          public_id=ReleasePublicId("PGX-REL-20260829-001"),
                          software_version_id=SoftwareVersionId.new(),
                          dataset_version_id=RulesetVersionId.new(),
                          ruleset_version_id=RulesetVersionId.new(),
                          manifest={}, manifest_hash=DIGEST,
                          status=ReleaseStatus.DRAFT, created_at=NOW)

    def test_release_bundle_pins_software_by_identity_not_by_string(self):
        """WP-02 held the software as free text, so two builds declaring the
        same version were indistinguishable and nothing joined a release to a
        registered build."""
        from pgx.domain.errors import IdentifierTypeMismatchError
        from pgx.domain.identifiers import SoftwareVersionId
        annotations = ReleaseBundle.__annotations__
        self.assertIn("software_version_id", annotations)
        self.assertNotIn("software_version", annotations)
        with self.assertRaises(IdentifierTypeMismatchError):
            ReleaseBundle(id=ReleaseBundleId.new(),
                          public_id=ReleasePublicId("PGX-REL-20260829-001"),
                          software_version_id="0.3.0.dev0",
                          dataset_version_id=DatasetVersionId.new(),
                          ruleset_version_id=RulesetVersionId.new(),
                          manifest={}, manifest_hash=DIGEST,
                          status=ReleaseStatus.DRAFT, created_at=NOW)


if __name__ == "__main__":
    unittest.main(verbosity=2)
