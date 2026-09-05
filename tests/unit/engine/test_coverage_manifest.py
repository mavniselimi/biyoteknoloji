# -*- coding: utf-8 -*-
"""The ruleset coverage manifest (section A).

The manifest is the document that says what a governed ruleset can evaluate.
Two failures matter more than the rest, and most of this file is about them.

The first is a manifest that is not *true of* the artifacts it names - it
pins a ruleset that has since been rebuilt, or an axis whose rule is not a
member, or evidence that does not resolve. Every one of those is checked, and
a check that could not be run is reported as a failure rather than skipped.

The second is a manifest whose expected scope was derived rather than
declared. Copying WP-11's ``structural_axes`` produces a document that looks
complete and under which no drug can ever be incompletely covered, because
nothing is expected that is not already present. That is not a manifest with
a small mistake in it; it is a manifest that has quietly stopped being able
to detect the thing coverage exists to detect.
"""

from __future__ import annotations

import dataclasses
import unittest

from pgx.domain.enums import Phenotype
from pgx.engine.coverage_errors import CoverageManifestError
from pgx.engine.coverage_manifest import (COVERAGE_MANIFEST_SCHEMA_VERSION,
                                          CoverageDeclaration,
                                          CoverageManifestApproval,
                                          RulesetCoverageManifest,
                                          SupportedAxis,
                                          build_coverage_manifest)
from pgx.engine.coverage_validator import (MANIFEST_ISSUE_CODES,
                                           validate_coverage_manifest)
from tests.fixtures.wp13.synthetic import (GENE_1, GENE_2, GENE_3, DRUG_1,
                                           DRUG_2, SYNTHETIC_DRUG_CATALOGUE,
                                           SYNTHETIC_GENE_CATALOGUE,
                                           declarations_for,
                                           synthetic_approval,
                                           synthetic_evidence_resolver,
                                           synthetic_manifest)
from tests.unit.engine._coverage_support import SyntheticWorld


class CoverageManifestCase(unittest.TestCase):
    """One synthetic world per class, torn down after it."""

    EXTRA_GENE = True

    @classmethod
    def setUpClass(cls):
        cls.world = SyntheticWorld(expected_extra_gene=cls.EXTRA_GENE)

    @classmethod
    def tearDownClass(cls):
        cls.world.close()

    def build(self, **overrides):
        """Rebuild the manifest with altered raw declarations."""
        declarations = overrides.pop("declarations", None)
        if declarations is None:
            declarations = declarations_for(self.world.frozen,
                                            expected_extra_gene=True)
        return build_coverage_manifest(
            frozen_ruleset=overrides.pop("frozen", self.world.frozen),
            declarations=declarations,
            approval=overrides.pop("approval", synthetic_approval()),
            evidence_resolver=overrides.pop("evidence_resolver",
                                            self.world.resolver))

    def raw(self, **overrides):
        base = dict(declarations_for(self.world.frozen,
                                     expected_extra_gene=True)[0])
        base.update(overrides)
        return (base,)

    def validate(self, manifest=None, **overrides):
        return validate_coverage_manifest(
            manifest if manifest is not None else self.world.manifest,
            frozen_ruleset=overrides.pop("frozen_ruleset",
                                         self.world.frozen),
            evidence_resolver=overrides.pop("evidence_resolver",
                                            self.world.resolver),
            **overrides)


class TestAWellFormedManifestIsAccepted(CoverageManifestCase):

    def test_a_synthetic_manifest_builds(self):
        manifest = self.world.manifest
        self.assertEqual(manifest.coverage_schema_version,
                         COVERAGE_MANIFEST_SCHEMA_VERSION)
        self.assertEqual(manifest.declared_drug_keys, (DRUG_1,))
        self.assertEqual(manifest.supported_axis_count, 2)

    def test_it_validates_against_the_ruleset_it_pins(self):
        report = self.validate()
        self.assertTrue(report.passed, report.to_json())
        self.assertEqual(report.codes, ())

    def test_the_declared_scope_is_wider_than_the_supported_axes(self):
        """The property the whole design exists for.

        Three genes are expected and two have rules. If the expected scope had
        been derived from the rules, the third would not appear and the drug
        would look complete.
        """
        declaration = self.world.manifest.declaration_for(DRUG_1)
        self.assertEqual(declaration.expected_gene_keys,
                         (GENE_1, GENE_2, GENE_3))
        covered = {axis.gene_canonical_key
                   for axis in declaration.supported_axes}
        self.assertEqual(covered, {GENE_1, GENE_2})
        self.assertNotIn(GENE_3, covered)

    def test_every_supported_axis_carries_a_verified_rule_reference(self):
        for axis in self.world.manifest.declaration_for(DRUG_1).supported_axes:
            with self.subTest(axis=axis.axis_key):
                self.assertTrue(axis.is_verified)
                self.assertTrue(axis.rule_content_hash.startswith("sha256:"))
                self.assertTrue(axis.evidence_references)

    def test_the_manifest_pins_by_identity_and_by_hash(self):
        manifest = self.world.manifest
        for name in ("ruleset_content_hash", "canonical_build_content_hash",
                     "evidence_build_content_hash", "protocol_content_hash",
                     "source_policy_content_hash"):
            with self.subTest(field=name):
                self.assertTrue(getattr(manifest, name).startswith("sha256:"))
        for name in ("ruleset_public_id", "dataset_public_id",
                     "canonical_build_key", "evidence_build_key",
                     "protocol_version", "source_policy_version"):
            with self.subTest(field=name):
                self.assertTrue(getattr(manifest, name))


class TestTheManifestIsDeterministicAndImmutable(CoverageManifestCase):

    def test_two_builds_of_the_same_declaration_hash_identically(self):
        self.assertEqual(self.build().content_hash(),
                         self.build().content_hash())

    def test_the_hash_does_not_depend_on_declaration_order(self):
        forward = declarations_for(self.world.frozen, expected_extra_gene=True)
        second = dict(forward[0])
        second["drug_id"] = DRUG_2
        second["declaration_id"] = "TEST-COVERAGE-DECL-2"
        second["supported_axes"] = ()
        one = self.build(declarations=(forward[0], second))
        two = self.build(declarations=(second, forward[0]))
        self.assertEqual(one.content_hash(), two.content_hash())

    def test_the_hash_does_not_depend_on_expected_gene_order(self):
        forward = self.build(declarations=self.raw(
            expected_gene_keys=(GENE_1, GENE_2, GENE_3)))
        reversed_ = self.build(declarations=self.raw(
            expected_gene_keys=(GENE_3, GENE_2, GENE_1)))
        self.assertEqual(forward.content_hash(), reversed_.content_hash())

    def test_the_hash_does_not_depend_on_supported_axis_order(self):
        axes = list(declarations_for(self.world.frozen,
                                     expected_extra_gene=True)[0]
                    ["supported_axes"])
        forward = self.build(declarations=self.raw(
            supported_axes=tuple(axes)))
        backward = self.build(declarations=self.raw(
            supported_axes=tuple(reversed(axes))))
        self.assertEqual(forward.content_hash(), backward.content_hash())

    def test_the_hash_excludes_the_approval_metadata(self):
        """Who signed a claim is not part of what the claim says.

        A manifest re-approved by different people describes the same coverage,
        and a hash that moved would make the two look like different claims.
        The approval is carried in ``to_json`` and checked separately.
        """
        other = synthetic_approval(approved_by="TEST-coverage-approver-9")
        self.assertEqual(self.build().content_hash(),
                         self.build(approval=other).content_hash())
        self.assertNotEqual(self.build().to_json()["approval"],
                            self.build(approval=other).to_json()["approval"])

    def test_the_manifest_cannot_be_mutated(self):
        with self.assertRaises((dataclasses.FrozenInstanceError,
                                AttributeError)):
            self.world.manifest.ruleset_public_id = "PGX-RULESET-19700101-001"

    def test_a_declaration_cannot_be_mutated(self):
        declaration = self.world.manifest.declaration_for(DRUG_1)
        with self.assertRaises((dataclasses.FrozenInstanceError,
                                AttributeError)):
            declaration.expected_gene_keys = ()

    def test_mutating_the_input_afterwards_changes_nothing(self):
        declarations = [dict(declarations_for(self.world.frozen,
                                              expected_extra_gene=True)[0])]
        manifest = self.build(declarations=tuple(declarations))
        before = manifest.content_hash()
        declarations[0]["expected_gene_keys"] = (GENE_1,)
        declarations[0]["drug_id"] = "DRUG:something-else"
        self.assertEqual(manifest.content_hash(), before)

    def test_to_json_is_serialisable_and_carries_its_own_hash(self):
        import json
        payload = self.world.manifest.to_json()
        json.dumps(payload, sort_keys=True)
        self.assertEqual(payload["content_hash"],
                         self.world.manifest.content_hash())


class TestScopeIsDeclaredNeverDerived(CoverageManifestCase):

    def test_a_drug_with_no_expected_gene_is_refused(self):
        with self.assertRaises(CoverageManifestError) as caught:
            self.build(declarations=self.raw(expected_gene_keys=()))
        self.assertEqual(caught.exception.code,
                         "COVERAGE_MANIFEST_SCOPE_EMPTY")

    def test_a_repeated_expected_gene_is_refused(self):
        with self.assertRaises(CoverageManifestError) as caught:
            self.build(declarations=self.raw(
                expected_gene_keys=(GENE_1, GENE_2, GENE_1)))
        self.assertEqual(caught.exception.code,
                         "COVERAGE_MANIFEST_DUPLICATE_GENE")

    def test_an_axis_outside_the_expected_scope_is_refused(self):
        with self.assertRaises(CoverageManifestError) as caught:
            self.build(declarations=self.raw(expected_gene_keys=(GENE_1,)))
        self.assertEqual(caught.exception.code,
                         "COVERAGE_MANIFEST_AXIS_OUT_OF_SCOPE")

    def test_an_axis_belonging_to_another_drug_is_refused(self):
        with self.assertRaises(CoverageManifestError) as caught:
            CoverageDeclaration(
                drug_canonical_key=DRUG_1,
                expected_gene_keys=(GENE_1,),
                supported_axes=(SupportedAxis(
                    drug_canonical_key=DRUG_2, gene_canonical_key=GENE_1,
                    phenotype=Phenotype.POOR),),
                declaration_id="TEST-DECL", declared_by="TEST-someone",
                declaration_provenance="SYNTHETIC TEST ONLY: a wrong drug.")
        self.assertEqual(caught.exception.code,
                         "COVERAGE_MANIFEST_AXIS_OUT_OF_SCOPE")

    def test_the_same_axis_declared_twice_is_refused(self):
        axis = SupportedAxis(drug_canonical_key=DRUG_1,
                             gene_canonical_key=GENE_1,
                             phenotype=Phenotype.POOR)
        with self.assertRaises(CoverageManifestError) as caught:
            CoverageDeclaration(
                drug_canonical_key=DRUG_1, expected_gene_keys=(GENE_1,),
                supported_axes=(axis, axis), declaration_id="TEST-DECL",
                declared_by="TEST-someone",
                declaration_provenance="SYNTHETIC TEST ONLY: declared twice.")
        self.assertEqual(caught.exception.code,
                         "COVERAGE_MANIFEST_DUPLICATE_AXIS")

    def test_two_scopes_for_one_drug_are_refused(self):
        first = declarations_for(self.world.frozen, expected_extra_gene=True)[0]
        second = dict(first)
        second["declaration_id"] = "TEST-COVERAGE-DECL-2"
        with self.assertRaises(CoverageManifestError) as caught:
            self.build(declarations=(first, second))
        self.assertEqual(caught.exception.code,
                         "COVERAGE_MANIFEST_DUPLICATE_DRUG")

    def test_a_manifest_declaring_nothing_is_refused(self):
        with self.assertRaises(CoverageManifestError) as caught:
            self.build(declarations=())
        self.assertEqual(caught.exception.code, "COVERAGE_MANIFEST_EMPTY")

    def test_the_builder_adds_no_gene_the_caller_did_not_declare(self):
        """Two rules exist; the declaration expects one gene and claims one
        axis. The manifest must contain exactly that."""
        axes = ({"gene_id": GENE_1, "phenotype": "POOR"},)
        manifest = self.build(declarations=self.raw(
            expected_gene_keys=(GENE_1,), supported_axes=axes))
        declaration = manifest.declaration_for(DRUG_1)
        self.assertEqual(declaration.expected_gene_keys, (GENE_1,))
        self.assertEqual(len(declaration.supported_axes), 1)
        self.assertNotIn(GENE_2, declaration.expected_gene_keys)

    def test_the_builder_adds_no_axis_the_caller_did_not_declare(self):
        manifest = self.build(declarations=self.raw(supported_axes=()))
        self.assertEqual(manifest.declaration_for(DRUG_1).supported_axes, ())
        self.assertEqual(manifest.supported_axis_count, 0)

    def test_a_declaration_needs_a_named_declarer_and_a_provenance(self):
        for field, value in (("declared_by", ""),
                             ("declaration_provenance", "too short"),
                             ("declaration_id", "  ")):
            with self.subTest(field=field):
                with self.assertRaises(CoverageManifestError) as caught:
                    self.build(declarations=self.raw(**{field: value}))
                self.assertEqual(caught.exception.code,
                                 "COVERAGE_MANIFEST_FIELD_INVALID")


class TestADeclarationMustBeTrueOfTheRuleset(CoverageManifestCase):

    def test_an_axis_no_member_rule_covers_is_refused(self):
        with self.assertRaises(CoverageManifestError) as caught:
            self.build(declarations=self.raw(
                supported_axes=({"gene_id": GENE_3, "phenotype": "POOR"},)))
        self.assertEqual(caught.exception.code,
                         "COVERAGE_MANIFEST_AXIS_UNSUPPORTED")

    def test_a_phenotype_no_member_rule_covers_is_refused(self):
        """The rules are keyed on POOR. Declaring RAPID supported is a claim
        about the ruleset that is not true of it."""
        with self.assertRaises(CoverageManifestError) as caught:
            self.build(declarations=self.raw(
                supported_axes=({"gene_id": GENE_1, "phenotype": "RAPID"},)))
        self.assertEqual(caught.exception.code,
                         "COVERAGE_MANIFEST_AXIS_UNSUPPORTED")

    def test_a_value_that_is_not_a_phenotype_is_refused(self):
        with self.assertRaises(CoverageManifestError) as caught:
            self.build(declarations=self.raw(
                supported_axes=({"gene_id": GENE_1,
                                 "phenotype": "poor metabolizer"},)))
        self.assertEqual(caught.exception.code,
                         "COVERAGE_MANIFEST_AXIS_INVALID")

    def test_indeterminate_may_not_key_an_axis(self):
        """``INDETERMINATE`` is a statement that no determination was made. An
        axis keyed on it would be a claim to cover the absence of a value."""
        with self.assertRaises(CoverageManifestError) as caught:
            SupportedAxis(drug_canonical_key=DRUG_1,
                          gene_canonical_key=GENE_1,
                          phenotype=Phenotype.INDETERMINATE)
        self.assertEqual(caught.exception.code,
                         "COVERAGE_MANIFEST_AXIS_INVALID")

    def test_unresolvable_evidence_refuses_the_build(self):
        with self.assertRaises(CoverageManifestError) as caught:
            self.build(evidence_resolver=lambda reference: False)
        self.assertEqual(caught.exception.code,
                         "COVERAGE_MANIFEST_EVIDENCE_UNRESOLVABLE")

    def test_a_key_without_its_canonical_prefix_is_refused(self):
        for field, value in (("drug_id", "testdrug-alpha"),):
            with self.subTest(field=field):
                with self.assertRaises(CoverageManifestError) as caught:
                    self.build(declarations=self.raw(**{field: value}))
                self.assertEqual(caught.exception.code,
                                 "COVERAGE_MANIFEST_KEY_INVALID")
        with self.assertRaises(CoverageManifestError) as caught:
            self.build(declarations=self.raw(
                supported_axes=({"gene_id": "TESTGENE1",
                                 "phenotype": "POOR"},)))
        self.assertEqual(caught.exception.code,
                         "COVERAGE_MANIFEST_KEY_INVALID")


class TestApprovalIsSeparatedAndNamed(CoverageManifestCase):

    def test_three_distinct_people_are_required(self):
        for overrides in ({"reviewed_by": "TEST-coverage-declarer-1"},
                          {"approved_by": "TEST-coverage-declarer-1"},
                          {"approved_by": "TEST-coverage-reviewer-1"}):
            with self.subTest(**overrides):
                with self.assertRaises(CoverageManifestError) as caught:
                    synthetic_approval(**overrides)
                self.assertEqual(caught.exception.code,
                                 "COVERAGE_MANIFEST_SEPARATION")

    def test_case_does_not_make_one_person_into_two(self):
        with self.assertRaises(CoverageManifestError) as caught:
            synthetic_approval(reviewed_by="test-COVERAGE-declarer-1")
        self.assertEqual(caught.exception.code,
                         "COVERAGE_MANIFEST_SEPARATION")

    def test_every_approval_field_must_be_present(self):
        for field in ("declared_by", "reviewed_by", "approved_by",
                      "approved_at", "approval_reference"):
            with self.subTest(field=field):
                with self.assertRaises(CoverageManifestError) as caught:
                    synthetic_approval(**{field: "  "})
                self.assertEqual(caught.exception.code,
                                 "COVERAGE_MANIFEST_FIELD_INVALID")

    def test_a_synthetic_approval_says_so(self):
        self.assertTrue(synthetic_approval().is_synthetic)
        self.assertTrue(self.world.manifest.to_json()["approval"]["synthetic"])

    def test_an_approval_naming_real_looking_actors_is_not_marked_synthetic(self):
        """The flag reports what the names look like; it grants nothing.

        Nothing accepts a manifest *because* the flag is false - whether the
        people named exist and hold the roles claimed is WP-23's work - so
        this asserts only that the flag stops claiming the document is a test
        fixture once it stops looking like one.
        """
        approval = CoverageManifestApproval(
            declared_by="a.curator", reviewed_by="b.reviewer",
            approved_by="c.approver", approved_at="2099-01-04T10:00:00Z",
            approval_reference="REF-1")
        self.assertFalse(approval.is_synthetic)

    def test_a_manifest_without_approval_metadata_is_refused(self):
        with self.assertRaises(CoverageManifestError) as caught:
            dataclasses.replace(self.world.manifest, approval=None)
        self.assertEqual(caught.exception.code,
                         "COVERAGE_MANIFEST_UNAPPROVED")


class TestTheManifestFieldsThemselves(CoverageManifestCase):

    def test_another_schema_version_is_not_reinterpreted(self):
        with self.assertRaises(CoverageManifestError) as caught:
            dataclasses.replace(self.world.manifest,
                                coverage_schema_version="pgx-something/2")
        self.assertEqual(caught.exception.code,
                         "COVERAGE_MANIFEST_SCHEMA_VERSION")

    def test_a_pin_that_is_not_a_digest_is_refused(self):
        for field in ("ruleset_content_hash", "canonical_build_content_hash",
                      "evidence_build_content_hash", "protocol_content_hash",
                      "source_policy_content_hash"):
            with self.subTest(field=field):
                with self.assertRaises(CoverageManifestError) as caught:
                    dataclasses.replace(self.world.manifest,
                                        **{field: "not-a-digest"})
                self.assertEqual(caught.exception.code,
                                 "COVERAGE_MANIFEST_DIGEST_INVALID")

    def test_an_empty_identity_is_refused(self):
        for field in ("ruleset_public_id", "dataset_public_id",
                      "canonical_build_key", "evidence_build_key",
                      "protocol_version", "source_policy_version"):
            with self.subTest(field=field):
                with self.assertRaises(CoverageManifestError) as caught:
                    dataclasses.replace(self.world.manifest, **{field: "  "})
                self.assertEqual(caught.exception.code,
                                 "COVERAGE_MANIFEST_FIELD_INVALID")

    def test_a_ruleset_version_below_one_is_refused(self):
        for value in (0, -1, True, "1"):
            with self.subTest(value=value):
                with self.assertRaises(CoverageManifestError) as caught:
                    dataclasses.replace(self.world.manifest,
                                        ruleset_version=value)
                self.assertEqual(caught.exception.code,
                                 "COVERAGE_MANIFEST_FIELD_INVALID")


class TestValidationAgainstTheArtifactsItPins(CoverageManifestCase):

    def test_a_manifest_naming_another_ruleset_is_reported(self):
        other = dataclasses.replace(self.world.manifest,
                                    ruleset_public_id="PGX-RULESET-29991231-002")
        self.assertIn("COVERAGE_RULESET_IDENTITY_MISMATCH",
                      self.validate(other).codes)

    def test_a_ruleset_that_was_rebuilt_is_reported(self):
        other = dataclasses.replace(self.world.manifest,
                                    ruleset_content_hash="sha256:" + "9" * 64)
        self.assertIn("COVERAGE_RULESET_HASH_MISMATCH",
                      self.validate(other).codes)

    def test_a_different_dataset_is_reported(self):
        for field in ("dataset_public_id", "canonical_build_content_hash"):
            value = ("PGX-DATA-19700101-001" if field == "dataset_public_id"
                     else "sha256:" + "8" * 64)
            with self.subTest(field=field):
                other = dataclasses.replace(self.world.manifest,
                                            **{field: value})
                self.assertIn("COVERAGE_DATASET_MISMATCH",
                              self.validate(other).codes)

    def test_a_different_evidence_build_is_reported(self):
        other = dataclasses.replace(
            self.world.manifest,
            evidence_build_content_hash="sha256:" + "7" * 64)
        self.assertIn("COVERAGE_EVIDENCE_BUILD_MISMATCH",
                      self.validate(other).codes)

    def test_a_different_protocol_or_source_policy_is_reported(self):
        for field, code in (
                ("protocol_content_hash", "COVERAGE_PROTOCOL_MISMATCH"),
                ("source_policy_content_hash",
                 "COVERAGE_SOURCE_POLICY_MISMATCH")):
            with self.subTest(field=field):
                other = dataclasses.replace(self.world.manifest,
                                            **{field: "sha256:" + "6" * 64})
                self.assertIn(code, self.validate(other).codes)

    def test_a_declared_content_hash_that_disagrees_is_reported(self):
        report = self.validate(declared_content_hash="sha256:" + "5" * 64)
        self.assertIn("COVERAGE_CONTENT_HASH_MISMATCH", report.codes)

    def test_the_manifests_own_hash_verifies(self):
        report = self.validate(
            declared_content_hash=self.world.manifest.content_hash())
        self.assertNotIn("COVERAGE_CONTENT_HASH_MISMATCH", report.codes)

    def test_no_evidence_resolver_is_a_failure_not_a_pass(self):
        report = validate_coverage_manifest(self.world.manifest,
                                            frozen_ruleset=self.world.frozen)
        self.assertFalse(report.passed)
        self.assertIn("COVERAGE_EVIDENCE_RESOLVER_MISSING", report.codes)

    def test_evidence_that_does_not_resolve_is_reported(self):
        report = self.validate(evidence_resolver=lambda reference: False)
        self.assertIn("COVERAGE_AXIS_EVIDENCE_MISSING", report.codes)

    def test_an_axis_with_no_evidence_at_all_is_reported(self):
        declaration = self.world.manifest.declaration_for(DRUG_1)
        stripped = dataclasses.replace(
            declaration,
            supported_axes=tuple(
                dataclasses.replace(axis, evidence_references=())
                for axis in declaration.supported_axes))
        manifest = dataclasses.replace(self.world.manifest,
                                       declarations=(stripped,))
        self.assertIn("COVERAGE_AXIS_EVIDENCE_MISSING",
                      self.validate(manifest).codes)

    def test_a_rule_that_is_not_a_member_is_reported(self):
        declaration = self.world.manifest.declaration_for(DRUG_1)
        altered = dataclasses.replace(
            declaration,
            supported_axes=tuple(
                dataclasses.replace(
                    axis, rule_id="00000000-0000-4000-8000-000000000000")
                for axis in declaration.supported_axes))
        manifest = dataclasses.replace(self.world.manifest,
                                       declarations=(altered,))
        self.assertIn("COVERAGE_AXIS_RULE_NOT_A_MEMBER",
                      self.validate(manifest).codes)

    def test_a_rule_whose_content_changed_is_reported(self):
        declaration = self.world.manifest.declaration_for(DRUG_1)
        altered = dataclasses.replace(
            declaration,
            supported_axes=tuple(
                dataclasses.replace(axis,
                                    rule_content_hash="sha256:" + "4" * 64)
                for axis in declaration.supported_axes))
        manifest = dataclasses.replace(self.world.manifest,
                                       declarations=(altered,))
        codes = self.validate(manifest).codes
        self.assertIn("COVERAGE_AXIS_RULE_HASH_MISMATCH", codes)

    def test_a_rule_with_no_validation_evidence_is_reported(self):
        """Membership is not validation (SAFETY-INV-003).

        The frozen artifact carries an approval record per member rule. A
        manifest resting on a rule with no such record rests on something
        nobody is recorded as having validated, and this validator will not
        infer the approval from the membership.
        """
        stripped = dataclasses.replace(self.world.frozen, approvals=())
        report = validate_coverage_manifest(
            self.world.manifest, frozen_ruleset=stripped,
            evidence_resolver=self.world.resolver)
        self.assertIn("COVERAGE_AXIS_RULE_NOT_VALIDATED", report.codes)

    def test_a_drug_outside_the_pinned_catalogue_is_reported(self):
        report = self.validate(drug_catalogue=(DRUG_2,))
        self.assertIn("COVERAGE_DRUG_NOT_IN_CATALOGUE", report.codes)

    def test_a_gene_outside_the_pinned_catalogue_is_reported(self):
        report = self.validate(gene_catalogue=(GENE_1, GENE_2))
        self.assertIn("COVERAGE_GENE_NOT_IN_CATALOGUE", report.codes)

    def test_a_catalogue_that_contains_everything_reports_nothing(self):
        report = self.validate(drug_catalogue=SYNTHETIC_DRUG_CATALOGUE,
                               gene_catalogue=SYNTHETIC_GENE_CATALOGUE)
        self.assertTrue(report.passed, report.to_json())

    def test_every_issue_is_reported_not_only_the_first(self):
        """An author fixing one problem per round-trip is an author who
        gives up. Distinct digests here, so no substituted value can
        accidentally equal the one it was meant to differ from."""
        broken = dataclasses.replace(
            self.world.manifest,
            ruleset_public_id="PGX-RULESET-29991231-002",
            ruleset_content_hash="sha256:" + "a" * 64,
            evidence_build_content_hash="sha256:" + "b" * 64,
            protocol_content_hash="sha256:" + "c" * 64,
            source_policy_content_hash="sha256:" + "d" * 64)
        report = validate_coverage_manifest(broken,
                                            frozen_ruleset=self.world.frozen)
        self.assertEqual(
            set(report.codes),
            {"COVERAGE_RULESET_IDENTITY_MISMATCH",
             "COVERAGE_RULESET_HASH_MISMATCH",
             "COVERAGE_EVIDENCE_BUILD_MISMATCH",
             "COVERAGE_PROTOCOL_MISMATCH",
             "COVERAGE_SOURCE_POLICY_MISMATCH",
             "COVERAGE_EVIDENCE_RESOLVER_MISSING"})

    def test_a_report_is_serialisable_and_hashable(self):
        import json
        report = self.validate()
        json.dumps(report.to_json(), sort_keys=True)
        self.assertTrue(report.result_hash().startswith("sha256:"))

    def test_every_published_issue_code_carries_a_meaning(self):
        for code, meaning in MANIFEST_ISSUE_CODES.items():
            with self.subTest(code=code):
                self.assertEqual(code, code.upper())
                self.assertGreater(len(meaning), 20)


class TestCopyingStructuralAxesIsDetected(CoverageManifestCase):
    """WP-11's ``structural_axes`` is a membership inventory, and a coverage
    manifest built out of it is the failure this whole module exists to
    prevent - so it is detected rather than trusted not to happen."""

    EXTRA_GENE = False

    def test_the_wp11_manifest_still_says_it_is_not_a_coverage_claim(self):
        note = self.world.frozen.manifest.to_json().get("note", "")
        self.assertIn("structural", note.lower())
        self.assertTrue(self.world.frozen.manifest.structural_axes)

    def test_a_scope_matching_the_rules_exactly_is_reported(self):
        manifest = synthetic_manifest(self.world.frozen,
                                      expected_extra_gene=False)
        report = validate_coverage_manifest(
            manifest, frozen_ruleset=self.world.frozen,
            evidence_resolver=self.world.resolver)
        self.assertIn("COVERAGE_STRUCTURAL_AXES_COPIED", report.codes)
        self.assertFalse(report.passed)

    def test_a_scope_wider_than_the_rules_is_not_reported(self):
        manifest = synthetic_manifest(self.world.frozen,
                                      expected_extra_gene=True)
        report = validate_coverage_manifest(
            manifest, frozen_ruleset=self.world.frozen,
            evidence_resolver=self.world.resolver)
        self.assertNotIn("COVERAGE_STRUCTURAL_AXES_COPIED", report.codes)

    def test_under_a_copied_scope_the_drug_can_never_be_partial(self):
        """Why the tell matters, stated as the consequence rather than the
        shape: every expected gene already has a rule, so no axis can be
        missing and PARTIAL becomes unreachable."""
        manifest = synthetic_manifest(self.world.frozen,
                                      expected_extra_gene=False)
        declaration = manifest.declaration_for(DRUG_1)
        self.assertEqual(
            set(declaration.expected_gene_keys),
            {axis.gene_canonical_key for axis in declaration.supported_axes})


if __name__ == "__main__":
    unittest.main()
