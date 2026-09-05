# -*- coding: utf-8 -*-
"""The P1-P6 migration: what crossed, what did not, and what cannot.

The migration's whole job is to turn six legacy demonstration profiles into
inputs, without turning them into evidence. These tests check the second half
as carefully as the first.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import unittest

from apps.web.demo_cases import (CASE_CATALOG_SCHEMA_VERSION,
                                 DEVELOPMENT_CASES_PATH,
                                 FORBIDDEN_CASE_FIELDS, DemoCaseError,
                                 DevelopmentCase, PhenotypeObservationRecord,
                                 load_development_cases, parse_catalog)
from apps.web.demo_migration import (LEGACY_CASE_IDS, LEGACY_SEED_PATH,
                                     build_catalog, build_manifest,
                                     legacy_source_digest)
from pgx.domain.claims import scan_claim_text
from tests.unit.web._support import REPO_ROOT

#: The medicine names the legacy notes contain. None may survive: the
#: catalogue holds phenotypes, and associating a medicine with one is the
#: governed ruleset's job.
LEGACY_MEDICINE_NAMES = ("clopidogrel", "voriconazole", "codeine", "tamoxifen",
                         "amitriptyline", "warfarin")


class TestTheSourceIsRecorded(unittest.TestCase):

    def test_the_seed_file_is_present_and_hashed(self):
        digest = legacy_source_digest()
        self.assertEqual(digest["source_file"],
                         "clinpgx_mvp_seed/mvp_demo_profiles.json")
        self.assertTrue(digest["source_file_sha256"].startswith("sha256:"))
        with io.open(LEGACY_SEED_PATH, "rb") as handle:
            expected = hashlib.sha256(handle.read()).hexdigest()
        self.assertEqual(digest["source_file_sha256"], "sha256:" + expected)

    def test_every_case_records_the_source_hash(self):
        for case in build_catalog()["cases"]:
            if case["legacy_profile_key"] is None:
                continue
            with self.subTest(case=case["case_id"]):
                self.assertTrue(
                    case["source_file_sha256"].startswith("sha256:"))
                self.assertEqual(case["source_file"],
                                 "clinpgx_mvp_seed/mvp_demo_profiles.json")


class TestExactlySixProfilesMigrated(unittest.TestCase):

    def setUp(self):
        self.catalog = build_catalog()
        self.cases = parse_catalog(self.catalog)

    def test_six_are_migrated_and_one_is_authored(self):
        self.assertEqual(self.catalog["migrated_case_count"], 6)
        self.assertEqual(self.catalog["authored_case_count"], 1)
        self.assertEqual(len(self.cases), 7)

    def test_every_legacy_profile_has_exactly_one_case(self):
        migrated = {case.legacy_profile_key for case in self.cases
                    if case.legacy_profile_key}
        self.assertEqual(migrated, set(LEGACY_CASE_IDS))

    def test_the_authored_case_is_not_a_seventh_legacy_profile(self):
        authored = [case for case in self.cases
                    if case.legacy_profile_key is None]
        self.assertEqual(len(authored), 1)
        self.assertEqual(authored[0].case_id, "WP17-CASE-INSUFFICIENT")
        self.assertIsNone(authored[0].source_file)

    def test_a_seed_with_an_unexpected_profile_is_refused(self):
        """A migration that silently skipped or invented one would be a
        migration nobody could check."""
        import tempfile

        handle, path = tempfile.mkstemp(suffix=".json")
        os.close(handle)
        self.addCleanup(os.unlink, path)
        with io.open(path, "w", encoding="utf-8") as stream:
            json.dump({"P9_surprise": {"profile_name": "x",
                                       "phenotypes": {"CYP2C19": "normal"}}},
                      stream)
        with self.assertRaises(DemoCaseError):
            build_catalog(path)


class TestEveryCaseIsDevelopmentOnly(unittest.TestCase):

    def setUp(self):
        self.cases = parse_catalog(build_catalog())

    def test_every_case_is_labelled_development_and_synthetic(self):
        for case in self.cases:
            with self.subTest(case=case.case_id):
                self.assertEqual(case.case_role, "DEVELOPMENT")
                self.assertTrue(case.is_synthetic)

    def test_no_case_is_validation_evidence_or_holdout(self):
        for case in self.cases:
            with self.subTest(case=case.case_id):
                self.assertFalse(case.is_validation_evidence)
                self.assertFalse(case.is_holdout)

    def test_a_holdout_role_cannot_be_constructed(self):
        with self.assertRaises(DemoCaseError):
            DevelopmentCase(
                case_id="WP17-CASE-X", label="x", case_role="EXPERT_HOLDOUT",
                is_synthetic=True, is_validation_evidence=False,
                is_holdout=False,
                observations=(PhenotypeObservationRecord("GENE:A", "POOR"),),
                legacy_profile_key=None, source_file=None,
                source_file_sha256=None, migration_note="", demonstrates="",
                no_pii_assertion="")

    def test_a_case_claiming_to_be_validation_evidence_is_refused(self):
        with self.assertRaises(DemoCaseError):
            DevelopmentCase(
                case_id="WP17-CASE-X", label="x", case_role="DEVELOPMENT",
                is_synthetic=True, is_validation_evidence=True,
                is_holdout=False,
                observations=(PhenotypeObservationRecord("GENE:A", "POOR"),),
                legacy_profile_key=None, source_file=None,
                source_file_sha256=None, migration_note="", demonstrates="",
                no_pii_assertion="")

    def test_every_case_asserts_it_holds_no_personal_data(self):
        for case in self.cases:
            with self.subTest(case=case.case_id):
                self.assertTrue(case.no_pii_assertion)


class TestNoExpectedResultCanExist(unittest.TestCase):
    """A catalogue that cannot hold an expectation cannot be scored."""

    def test_the_case_type_has_no_field_for_an_expected_result(self):
        fields = set(DevelopmentCase.__dataclass_fields__)
        for name in ("expected_attention", "expected_coverage",
                     "expected_result", "gold_standard", "ground_truth"):
            with self.subTest(field=name):
                self.assertNotIn(name, fields)

    def test_a_catalogue_carrying_an_expectation_is_refused(self):
        catalog = build_catalog()
        catalog["cases"][0]["expected_attention"] = "HIGH"
        with self.assertRaises(DemoCaseError):
            parse_catalog(catalog)

    def test_every_forbidden_field_is_refused_at_any_depth(self):
        for name in FORBIDDEN_CASE_FIELDS:
            catalog = build_catalog()
            catalog["cases"][0]["observations"][0][name] = "x"
            with self.subTest(field=name):
                with self.assertRaises(DemoCaseError):
                    parse_catalog(catalog)


class TestNoLegacyProseWasPromoted(unittest.TestCase):

    def setUp(self):
        self.catalog = build_catalog()
        self.rendered = json.dumps(self.catalog, ensure_ascii=False)

    def test_no_demo_use_field_survives(self):
        self.assertNotIn("demo_use", self.rendered)

    def test_no_legacy_medicine_name_survives(self):
        lowered = self.rendered.lower()
        for name in LEGACY_MEDICINE_NAMES:
            with self.subTest(medicine=name):
                self.assertNotIn(name, lowered)

    def test_no_case_proposes_a_medication(self):
        for case in self.catalog["cases"]:
            with self.subTest(case=case["case_id"]):
                self.assertNotIn("medications", case)
                self.assertNotIn("recommended_medications", case)

    def test_every_migrated_label_passes_the_claim_scanner(self):
        for case in self.catalog["cases"]:
            with self.subTest(case=case["case_id"]):
                for value in (case["label"], case["demonstrates"],
                              case["migration_note"],
                              case["no_pii_assertion"]):
                    report = scan_claim_text(value)
                    self.assertEqual(
                        list(getattr(report, "violations", ()) or ()), [])


class TestPhenotypesAreCanonicalised(unittest.TestCase):

    def setUp(self):
        self.cases = {case.case_id: case
                      for case in parse_catalog(build_catalog())}

    def test_gene_keys_and_values_are_canonical(self):
        for case in self.cases.values():
            for observation in case.observations:
                with self.subTest(case=case.case_id, gene=observation.gene):
                    self.assertTrue(observation.gene.startswith("GENE:"))
                    self.assertEqual(observation.value,
                                     observation.value.upper())

    def test_ultrarapid_stayed_ultrarapid(self):
        """SAFETY-INV-004 in migration form."""
        case = self.cases["WP17-CASE-P4"]
        values = {item.gene: item.value for item in case.observations}
        self.assertEqual(values["GENE:CYP2D6"], "ULTRARAPID")
        self.assertNotEqual(values["GENE:CYP2D6"], "RAPID")

    def test_observations_are_stored_in_canonical_order(self):
        for case in self.cases.values():
            genes = [item.gene for item in case.observations]
            with self.subTest(case=case.case_id):
                self.assertEqual(genes, sorted(genes))

    def test_an_uncanonicalisable_value_fails_the_migration(self):
        import tempfile
        from apps.web.demo_migration import LEGACY_CASE_IDS as ids

        handle, path = tempfile.mkstemp(suffix=".json")
        os.close(handle)
        self.addCleanup(os.unlink, path)
        profiles = {key: {"profile_name": key,
                          "phenotypes": {"CYP2C19": "normal"}}
                    for key in ids}
        profiles["P1_normal"]["phenotypes"]["CYP2C19"] = "definitely-not-a-phenotype"
        with io.open(path, "w", encoding="utf-8") as stream:
            json.dump(profiles, stream)
        with self.assertRaises(DemoCaseError):
            build_catalog(path)


class TestTheArtifactIsSealedAndDeterministic(unittest.TestCase):

    def test_generation_is_deterministic(self):
        self.assertEqual(json.dumps(build_catalog(), sort_keys=True),
                         json.dumps(build_catalog(), sort_keys=True))

    def test_the_committed_artifact_matches_the_migration(self):
        self.assertTrue(os.path.isfile(DEVELOPMENT_CASES_PATH))
        with io.open(DEVELOPMENT_CASES_PATH, encoding="utf-8") as handle:
            committed = json.load(handle)
        self.assertEqual(committed, build_catalog())

    def test_the_manifest_hashes_the_catalogue(self):
        catalog = build_catalog()
        manifest = build_manifest(catalog)
        self.assertEqual(manifest["case_count"], catalog["case_count"])
        self.assertTrue(manifest["catalog_sha256"].startswith("sha256:"))
        self.assertEqual(manifest["validation_status"],
                         "NOT_VALIDATION_EVIDENCE")

    def test_the_manifest_declares_what_kind_of_artifact_it_is(self):
        manifest = build_manifest(build_catalog())
        self.assertEqual(manifest["artifact_kind"],
                         "SOURCE_DERIVED_AND_AUTHORED")
        self.assertIn("Nothing here is browser-generated",
                      manifest["artifact_note"])

    def test_the_sealed_catalogue_loads_through_the_contract(self):
        cases = load_development_cases()
        self.assertEqual(len(cases), 7)

    def test_a_catalogue_of_another_schema_version_is_refused(self):
        catalog = dict(build_catalog(), schema_version="something-else/9")
        with self.assertRaises(DemoCaseError):
            parse_catalog(catalog)

    def test_a_missing_catalogue_is_refused_not_treated_as_empty(self):
        with self.assertRaises(DemoCaseError):
            load_development_cases(os.path.join(REPO_ROOT, "data", "demo",
                                                "no-such-file.json"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class TestTheManifestCanBeCheckedAgainstTheFile(unittest.TestCase):
    """A hash a reader cannot reproduce is worse than no hash at all.

    The manifest carries two: one over a canonical serialisation of the
    content, which survives reformatting, and one over the exact bytes on
    disk, which is what ``sha256sum`` reports. Only the second can be checked
    with a shell command, and only the first survives a re-serialisation, so
    both are asserted here against the committed files.
    """

    @classmethod
    def setUpClass(cls):
        import io
        import json
        import os

        root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))))
        cls.catalog_path = os.path.join(root, "data", "demo",
                                        "wp17-development-cases.json")
        with io.open(os.path.join(root, "data", "demo",
                                  "wp17-demo-case-manifest.json"),
                     encoding="utf-8") as handle:
            cls.manifest = json.load(handle)
        with io.open(cls.catalog_path, "rb") as handle:
            cls.raw = handle.read()

    def test_the_file_hash_is_the_hash_of_the_committed_file(self):
        import hashlib

        self.assertEqual(
            self.manifest["catalog_file_sha256"],
            "sha256:" + hashlib.sha256(self.raw).hexdigest())
        self.assertEqual(self.manifest["catalog_file_bytes"], len(self.raw))

    def test_the_content_hash_survives_reserialisation(self):
        import hashlib
        import json

        # Reformatted with different indentation and key order handling: the
        # canonical hash must be unchanged, because it is over the content.
        catalog = json.loads(self.raw.decode("utf-8"))
        body = json.dumps(catalog, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True).encode("utf-8")
        self.assertEqual(self.manifest["catalog_sha256"],
                         "sha256:" + hashlib.sha256(body).hexdigest())

    def test_the_two_hashes_are_different_and_labelled(self):
        # If they were equal the distinction would be invisible and a reader
        # would learn nothing from having both.
        self.assertNotEqual(self.manifest["catalog_sha256"],
                            self.manifest["catalog_file_sha256"])
        self.assertIn("sha256sum", self.manifest["catalog_hash_note"])
        self.assertEqual(self.manifest["catalog_file_path"],
                         "data/demo/wp17-development-cases.json")
