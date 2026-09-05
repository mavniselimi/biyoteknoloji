# -*- coding: utf-8 -*-
"""The restricted import boundary, exercised against a real filesystem (WP-18).

Nothing has ever passed through this boundary in the repository - there is no
restricted storage and no expert payload exists. These tests build a temporary
root and drive it, because a fail-closed boundary that has never been made to
fail is not known to be fail-closed.

The payloads here are obviously synthetic TESTGENE/testdrug content. None of
them is, or resembles, an expert answer: there is no field for one, and the
importer refuses every name one could be given.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import unittest

from pgx.validation.errors import ImportRefusedError
from pgx.validation.restricted_import import (IMPORT_ISSUE_CODES,
                                              MAX_PAYLOAD_BYTES,
                                              import_restricted_payload,
                                              resolve_within)
from pgx.validation.cases import RestrictedPayload
from pgx.validation.vocabulary import ValidationCaseRole
from tests.fixtures.wp18.synthetic import (case, content, development_case,
                                           expert_holdout_case,
                                           internal_holdout_case, provenance)


class _RootCase(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)

    def stored(self):
        return sorted(name for name in os.listdir(self.root)
                      if not name.startswith("."))

    def holdout(self, case_id="PGX-VAL-INT-IMPORT", body=None):
        body = body or content()
        payload = RestrictedPayload(body)
        return internal_holdout_case(case_id, body=body,
                                     payload_hash=payload.payload_hash), body


class TestASuccessfulImport(_RootCase):

    def test_it_writes_one_file_and_reports_what_it_did(self):
        item, body = self.holdout()
        result = import_restricted_payload(storage_root=self.root, case=item,
                                           payload_document=body)
        self.assertEqual(self.stored(), ["PGX-VAL-INT-IMPORT.json"])
        self.assertEqual(result.case_id, "PGX-VAL-INT-IMPORT")
        self.assertTrue(result.separation_clean)

    def test_the_hash_is_computed_here_not_trusted(self):
        """A declared digest that nobody recomputes is decorative."""
        item, body = self.holdout()
        result = import_restricted_payload(storage_root=self.root, case=item,
                                           payload_document=body)
        self.assertEqual(result.payload_hash,
                         RestrictedPayload(body).payload_hash)

    def test_a_declared_hash_that_disagrees_is_refused(self):
        body = content()
        item = internal_holdout_case("PGX-VAL-INT-BADHASH", body=body,
                                     payload_hash="sha256:" + "9" * 64)
        with self.assertRaises(ImportRefusedError) as caught:
            import_restricted_payload(storage_root=self.root, case=item,
                                      payload_document=body)
        self.assertIn("DECLARED_HASH_MISMATCH", caught.exception.issue_codes)
        self.assertEqual(self.stored(), [])

    def test_a_fingerprint_that_disagrees_is_refused(self):
        """Checked even when no payload hash was declared.

        The case is built without one so the declared-hash rule cannot fire
        first: what is under test here is that a payload which is not the case
        the metadata describes is refused on its own account.
        """
        item = internal_holdout_case("PGX-VAL-INT-FPRINT", body=content())
        self.assertIsNone(item.payload_hash)
        with self.assertRaises(ImportRefusedError) as caught:
            import_restricted_payload(
                storage_root=self.root, case=item,
                payload_document=content(value="RAPID"))
        self.assertIn("FINGERPRINT_MISMATCH", caught.exception.issue_codes)
        self.assertEqual(self.stored(), [])

    def test_the_result_carries_no_payload_content(self):
        item, body = self.holdout(
            body={"observations": [{"gene": "GENE:TESTGENE1",
                                    "value": "TEST-SECRET"}]})
        result = import_restricted_payload(storage_root=self.root, case=item,
                                           payload_document=body)
        self.assertNotIn("TEST-SECRET", json.dumps(result.to_json()))


class TestItFailsClosed(_RootCase):

    def test_no_storage_root_is_refused(self):
        item, body = self.holdout()
        with self.assertRaises(ImportRefusedError) as caught:
            import_restricted_payload(storage_root=None, case=item,
                                      payload_document=body)
        self.assertIn("STORAGE_NOT_CONFIGURED", caught.exception.issue_codes)

    def test_a_development_case_may_not_be_imported(self):
        with self.assertRaises(ImportRefusedError) as caught:
            import_restricted_payload(storage_root=self.root,
                                      case=development_case(),
                                      payload_document=content())
        self.assertIn("ROLE_NOT_HOLDOUT", caught.exception.issue_codes)
        self.assertEqual(self.stored(), [])

    def test_a_malformed_payload_is_refused(self):
        item, _body = self.holdout()
        for bad in (None, [], "", {}, 7):
            with self.subTest(payload=repr(bad)):
                with self.assertRaises(ImportRefusedError):
                    import_restricted_payload(storage_root=self.root,
                                              case=item, payload_document=bad)
        self.assertEqual(self.stored(), [])

    def test_an_oversized_payload_is_refused(self):
        body = {"observations": [{"gene": "GENE:TESTGENE1", "value": "POOR"}],
                "context": ["x" * 4000 for _ in range(400)]}
        payload = RestrictedPayload(body)
        item = internal_holdout_case("PGX-VAL-INT-BIG", body=body,
                                     payload_hash=payload.payload_hash)
        with self.assertRaises(ImportRefusedError) as caught:
            import_restricted_payload(storage_root=self.root, case=item,
                                      payload_document=body)
        self.assertIn("PAYLOAD_TOO_LARGE", caught.exception.issue_codes)
        self.assertEqual(self.stored(), [])

    def test_a_prohibited_field_is_refused(self):
        item, _body = self.holdout()
        for name in ("genotype", "vcf", "patient_name", "expected_result"):
            with self.subTest(field=name):
                with self.assertRaises(ImportRefusedError) as caught:
                    import_restricted_payload(
                        storage_root=self.root, case=item,
                        payload_document={"observations": [], name: "x"})
                self.assertIn("PROHIBITED_FIELD",
                              caught.exception.issue_codes)
        self.assertEqual(self.stored(), [])

    def test_a_duplicate_identifier_is_refused(self):
        item, body = self.holdout()
        with self.assertRaises(ImportRefusedError) as caught:
            import_restricted_payload(storage_root=self.root, case=item,
                                      payload_document=body,
                                      existing_cases=[item])
        self.assertIn("DUPLICATE_CASE_ID", caught.exception.issue_codes)

    def test_a_separation_violation_is_refused(self):
        """A holdout duplicating a development case never lands."""
        body = content()
        payload = RestrictedPayload(body)
        existing = development_case("PGX-VAL-DEV-CLASH", body=body)
        incoming = internal_holdout_case(
            "PGX-VAL-INT-CLASH", body=body,
            payload_hash=payload.payload_hash,
            prov=provenance(development=False, source="TEST-OTHER"))
        with self.assertRaises(ImportRefusedError) as caught:
            import_restricted_payload(storage_root=self.root, case=incoming,
                                      payload_document=body,
                                      existing_cases=[existing])
        self.assertIn("SEPARATION_VIOLATION", caught.exception.issue_codes)
        self.assertEqual(self.stored(), [])

    def test_every_refusal_uses_a_declared_issue_code(self):
        item, _body = self.holdout()
        with self.assertRaises(ImportRefusedError) as caught:
            import_restricted_payload(storage_root=self.root, case=item,
                                      payload_document={"genotype": "x"})
        for code in caught.exception.issue_codes:
            self.assertIn(code, IMPORT_ISSUE_CODES)

    def test_a_refusal_leaks_no_path(self):
        item, _body = self.holdout()
        with self.assertRaises(ImportRefusedError) as caught:
            import_restricted_payload(storage_root=self.root, case=item,
                                      payload_document={},
                                      relative_path="../escape.json")
        self.assertNotIn(self.root, str(caught.exception))


class TestPathContainment(_RootCase):

    def test_traversal_is_refused(self):
        for relative in ("../escape.json", "a/../../escape.json",
                         "./../escape.json"):
            with self.subTest(path=relative):
                with self.assertRaises(ImportRefusedError) as caught:
                    resolve_within(self.root, relative)
                self.assertIn("PATH_ESCAPES_ROOT",
                              caught.exception.issue_codes)

    def test_an_absolute_path_is_refused(self):
        with self.assertRaises(ImportRefusedError):
            resolve_within(self.root, "/etc/passwd")

    def test_a_symlink_on_the_way_in_is_refused(self):
        """Even one that lands inside the root.

        It is a link somebody can repoint later, and this boundary must not
        depend on nobody doing that.
        """
        inside = os.path.join(self.root, "real")
        os.makedirs(inside)
        link = os.path.join(self.root, "link")
        os.symlink(inside, link)
        with self.assertRaises(ImportRefusedError) as caught:
            resolve_within(self.root, "link/payload.json")
        self.assertIn("SYMLINK_IN_PATH", caught.exception.issue_codes)

    def test_a_symlink_escaping_the_root_is_refused(self):
        outside = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, outside, True)
        os.symlink(outside, os.path.join(self.root, "out"))
        with self.assertRaises(ImportRefusedError):
            resolve_within(self.root, "out/payload.json")

    def test_an_ordinary_nested_path_is_allowed(self):
        resolved = resolve_within(self.root, "expert/PGX-VAL-EXP-1.json")
        self.assertTrue(resolved.startswith(os.path.realpath(self.root)))


class TestTheWriteIsAtomic(_RootCase):

    def test_a_failed_import_leaves_the_previous_file_untouched(self):
        item, body = self.holdout()
        import_restricted_payload(storage_root=self.root, case=item,
                                  payload_document=body)
        path = os.path.join(self.root, "PGX-VAL-INT-IMPORT.json")
        with io.open(path, encoding="utf-8") as handle:
            before = handle.read()

        with self.assertRaises(ImportRefusedError):
            import_restricted_payload(
                storage_root=self.root, case=item,
                payload_document={"observations": [], "genotype": "x"})

        with io.open(path, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), before)

    def test_no_temporary_file_is_left_behind_on_success(self):
        item, body = self.holdout()
        import_restricted_payload(storage_root=self.root, case=item,
                                  payload_document=body)
        leftovers = [name for name in os.listdir(self.root)
                     if name.startswith(".import-")]
        self.assertEqual(leftovers, [])

    def test_no_partial_file_is_left_behind_on_refusal(self):
        item, _body = self.holdout()
        with self.assertRaises(ImportRefusedError):
            import_restricted_payload(storage_root=self.root, case=item,
                                      payload_document={"genotype": "x"})
        self.assertEqual(os.listdir(self.root), [])

    def test_the_written_file_is_the_payload_and_nothing_else(self):
        item, body = self.holdout()
        import_restricted_payload(storage_root=self.root, case=item,
                                  payload_document=body)
        with io.open(os.path.join(self.root, "PGX-VAL-INT-IMPORT.json"),
                     encoding="utf-8") as handle:
            document = json.load(handle)
        self.assertEqual(sorted(document),
                         ["case_id", "content", "schema_version"])


class TestNoExpertPayloadIsCommitted(unittest.TestCase):

    def test_the_repository_holds_no_restricted_payload_directory(self):
        root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))))
        for forbidden in ("data/holdout", "data/validation/expert",
                          "data/validation/restricted",
                          "data/validation/payloads"):
            with self.subTest(path=forbidden):
                self.assertFalse(
                    os.path.exists(os.path.join(root, *forbidden.split("/"))),
                    "%s exists; an expert payload must not be committed "
                    "beside the rules it tests" % forbidden)

    def test_the_size_limit_is_small_enough_to_catch_a_mistake(self):
        """A sequencing file or an archive is refused on size, before parsing."""
        self.assertLessEqual(MAX_PAYLOAD_BYTES, 4 * 1024 * 1024)
