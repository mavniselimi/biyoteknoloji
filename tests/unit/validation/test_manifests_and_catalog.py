# -*- coding: utf-8 -*-
"""Public manifests, and the WP-17 cases seen as development (WP-18).

Two things are being defended here.

A manifest is what gets committed and read by people who may not read the
cases it lists, so it must be incapable of carrying an answer - not merely
observed not to.

And the seven WP-17 catalogue cases must stay development forever. They
demonstrated the same rules they would be measured against; using them as
validation evidence would report memory as generalisation. The tests check
that they are development, that nothing copies them into holdout storage, and
that the sealed WP-17 artifact they come from is untouched.
"""

from __future__ import annotations

import io
import json
import os
import unittest

from pgx.validation.catalog import (DEVELOPMENT_CATALOG_PATH,
                                    development_cases,
                                    load_development_catalog)
from pgx.validation.errors import RestrictedContentError, ValidationCaseError
from pgx.validation.manifests import (P0_TARGET_CASE_COUNT,
                                      assert_public_manifest_is_safe,
                                      build_case_manifest,
                                      build_holdout_manifest)
from pgx.validation.separation import audit_partition
from pgx.validation.vocabulary import PayloadAvailability, ValidationCaseRole
from tests.fixtures.wp18.synthetic import (development_case,
                                           internal_holdout_case)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))


class TestTheDevelopmentCatalogIsDevelopmentOnly(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.cases = development_cases(REPO_ROOT)

    def test_there_are_seven_of_them(self):
        self.assertEqual(len(self.cases), 7)

    def test_every_one_is_development(self):
        for case in self.cases:
            with self.subTest(case=case.case_id.value):
                self.assertIs(case.role, ValidationCaseRole.DEVELOPMENT)

    def test_none_is_validation_evidence(self):
        for case in self.cases:
            with self.subTest(case=case.case_id.value):
                self.assertFalse(case.is_validation_evidence)
                self.assertFalse(case.is_holdout)

    def test_every_one_declares_itself_derived_from_development(self):
        """Which is what makes them unusable as holdout, permanently."""
        for case in self.cases:
            with self.subTest(case=case.case_id.value):
                self.assertTrue(case.provenance.derived_from_development)

    def test_none_carries_an_expected_result(self):
        for case in self.cases:
            rendered = json.dumps(case.to_json())
            for name in ("expected", "gold_standard", "ground_truth",
                         "answer", "score"):
                with self.subTest(case=case.case_id.value, field=name):
                    self.assertNotIn(name, rendered)

    def test_their_provenance_points_at_the_committed_source(self):
        catalog = load_development_catalog(REPO_ROOT)
        digest = catalog["source"]["source_file_sha256"]
        migrated = [case for case in self.cases
                    if case.extra.get("legacy_profile_key")]
        self.assertEqual(len(migrated), 6)
        for case in migrated:
            with self.subTest(case=case.case_id.value):
                self.assertEqual(case.provenance.source_digest, digest)

    def test_the_view_refuses_a_catalogue_that_changed_its_mind(self):
        """If a WP-17 entry ever claims holdout, this stops rather than guesses."""
        import tempfile
        import shutil

        temporary = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, temporary, True)
        os.makedirs(os.path.join(temporary, "data", "demo"))
        catalog = json.loads(json.dumps(load_development_catalog(REPO_ROOT)))
        catalog["cases"][0]["case_role"] = "INTERNAL_HOLDOUT"
        with io.open(os.path.join(temporary, *DEVELOPMENT_CATALOG_PATH
                                  .split("/")), "w",
                     encoding="utf-8") as handle:
            json.dump(catalog, handle)
        with self.assertRaises(ValidationCaseError):
            development_cases(temporary)

    def test_the_partition_is_clean(self):
        self.assertTrue(audit_partition(self.cases).is_clean)

    def test_the_sealed_wp17_artifact_is_not_modified_by_reading_it(self):
        path = os.path.join(REPO_ROOT, *DEVELOPMENT_CATALOG_PATH.split("/"))
        with io.open(path, "rb") as handle:
            before = handle.read()
        development_cases(REPO_ROOT)
        with io.open(path, "rb") as handle:
            self.assertEqual(handle.read(), before)

    def test_nothing_copies_them_into_holdout_storage(self):
        """A view, not a migration. One source, and it stays WP-17's.

        Read as a syntax tree. The module opens the catalogue to *read* it, so
        a text search for ``io.open`` finds the legitimate call and proves
        nothing - the check has to distinguish reading from writing, which
        means looking at the mode argument rather than at the characters.
        """
        import ast
        import inspect

        from pgx.validation import catalog

        parsed = ast.parse(inspect.getsource(catalog))

        names = {node.id for node in ast.walk(parsed)
                 if isinstance(node, ast.Name)}
        self.assertNotIn("INTERNAL_HOLDOUT", names)
        self.assertNotIn("EXPERT_HOLDOUT", names)

        for node in ast.walk(parsed):
            if not isinstance(node, ast.Call):
                continue
            target = getattr(node.func, "attr", getattr(node.func, "id", ""))
            # Qualified by module, because ``str.replace`` and ``os.replace``
            # share a name and only one of them writes to a disk. Matching on
            # the bare attribute would fail on the case-id rewrite two lines
            # into the loop below.
            module = getattr(getattr(node.func, "value", None), "id", "")
            if module in ("os", "shutil", "pathlib"):
                self.assertNotIn(target, ("makedirs", "mkdir", "replace",
                                          "rename", "unlink", "remove",
                                          "rmtree", "copy", "copyfile"),
                                 "the catalogue view calls %s.%s()"
                                 % (module, target))
            if target == "open":
                modes = [argument.value for argument in node.args[1:]
                         if isinstance(argument, ast.Constant)]
                modes += [keyword.value.value for keyword in node.keywords
                          if keyword.arg == "mode"
                          and isinstance(keyword.value, ast.Constant)]
                for mode in modes:
                    self.assertNotIn("w", str(mode))
                    self.assertNotIn("a", str(mode))


class TestAPublicManifestCannotCarryAnAnswer(unittest.TestCase):

    def test_a_manifest_with_an_expected_result_is_refused(self):
        with self.assertRaises(RestrictedContentError):
            assert_public_manifest_is_safe({"cases": [
                {"case_id": "PGX-VAL-INT-1", "expected_result": "HIGH"}]})

    def test_a_manifest_with_a_payload_is_refused(self):
        with self.assertRaises(RestrictedContentError):
            assert_public_manifest_is_safe({"payload": {"observations": []}})

    def test_a_manifest_with_observations_is_refused(self):
        """Even inputs. A manifest lists cases; it does not reproduce them."""
        with self.assertRaises(RestrictedContentError):
            assert_public_manifest_is_safe(
                {"cases": [{"observations": [{"gene": "GENE:TESTGENE1"}]}]})

    def test_the_refusal_names_the_field_and_not_the_value(self):
        with self.assertRaises(RestrictedContentError) as caught:
            assert_public_manifest_is_safe(
                {"expected_result": "TEST-SECRET-ANSWER"})
        self.assertNotIn("TEST-SECRET-ANSWER", str(caught.exception))

    def test_a_built_manifest_passes_its_own_check(self):
        document = build_case_manifest([development_case()],
                                       partition="DEVELOPMENT", note="x")
        assert_public_manifest_is_safe(document)

    def test_a_partition_may_not_list_the_other_side(self):
        with self.assertRaises(RestrictedContentError):
            build_case_manifest([internal_holdout_case()],
                                partition="DEVELOPMENT", note="x")
        with self.assertRaises(RestrictedContentError):
            build_case_manifest([development_case()],
                                partition="HOLDOUT", note="x")


class TestTheTargetIsNotTheCount(unittest.TestCase):

    def test_the_holdout_manifest_reports_zero_and_the_target_separately(self):
        document = build_holdout_manifest()
        self.assertEqual(document["case_count"], 0)
        self.assertEqual(document["target_case_count"], P0_TARGET_CASE_COUNT)
        self.assertEqual(document["target_shortfall"], P0_TARGET_CASE_COUNT)
        self.assertFalse(document["meets_p0_target"])

    def test_the_note_says_why_it_is_empty(self):
        note = build_holdout_manifest()["note"]
        self.assertIn("No holdout case exists", note)
        self.assertIn("scientific work", note)

    def test_an_empty_manifest_is_a_document_not_an_absence(self):
        """'The structure exists and holds nothing' is a real statement.

        A missing file would say something different and weaker.
        """
        document = build_holdout_manifest()
        self.assertEqual(document["partition"], "HOLDOUT")
        self.assertTrue(document["is_validation_evidence"])
        self.assertEqual(document["payload_availability"],
                         PayloadAvailability.NOT_CONFIGURED.value)

    def test_the_development_manifest_declares_it_is_not_evidence(self):
        document = build_case_manifest(development_cases(REPO_ROOT),
                                       partition="DEVELOPMENT", note="x")
        self.assertFalse(document["is_validation_evidence"])
        for entry in document["cases"]:
            with self.subTest(case=entry["case_id"]):
                self.assertFalse(entry["is_validation_evidence"])
