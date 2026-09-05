# -*- coding: utf-8 -*-
"""Nothing machine-specific, secret or clinical reaches a committed artifact.

Verification evidence is committed, which makes it a document that can leak the
machine that produced it and the data the software was pointed at. Both have
happened to other projects by accident. These tests are the ones that would
have caught it.
"""

from __future__ import annotations

import json
import os
import unittest

from pgx.verification.errors import ScrubRefusal
from pgx.verification.scrub import (
    FORBIDDEN_PATTERNS,
    reject_sensitive,
    safe_render,
    scrub_document,
    scrub_text,
)

from tests.unit.verification._support import REPO_ROOT


class TestKnownPathsAreRewritten(unittest.TestCase):

    def test_the_repository_root_becomes_a_placeholder(self):
        text = os.path.join(REPO_ROOT, "tests", "unit", "x.py")
        self.assertEqual(scrub_text(text, REPO_ROOT), "<repo>/tests/unit/x.py")

    def test_a_temporary_directory_becomes_a_placeholder(self):
        self.assertEqual(scrub_text("/tmp/pgx-wp06-abc123/manifest.json",
                                    REPO_ROOT),
                         "<tmp>/pgx-wp06-abc123/manifest.json")

    def test_the_home_directory_becomes_a_placeholder(self):
        environ = {"HOME": "/home/someone"}
        self.assertEqual(
            scrub_text("/home/someone/Projects/x", REPO_ROOT, environ),
            "<home>/Projects/x")

    def test_the_longest_path_wins(self):
        """The repository is usually inside the home directory. Rewriting the
        home first would turn the root into ``<home>/Projects/...`` and hide
        the fact that it was the repository at all."""
        environ = {"HOME": os.path.dirname(REPO_ROOT)}
        scrubbed = scrub_text(os.path.join(REPO_ROOT, "pgx"), REPO_ROOT,
                              environ)
        self.assertEqual(scrubbed, "<repo>/pgx")

    def test_keys_are_scrubbed_as_well_as_values(self):
        """A dictionary keyed by absolute path would otherwise leak the
        machine in the one place a value-only scrubber never looks."""
        document = {os.path.join(REPO_ROOT, "a.py"): {"ok": True}}
        scrubbed = scrub_document(document, REPO_ROOT)
        self.assertEqual(list(scrubbed), ["<repo>/a.py"])

    def test_nested_structures_are_scrubbed_throughout(self):
        document = {"a": [{"b": [os.path.join(REPO_ROOT, "x")]}]}
        self.assertEqual(scrub_document(document, REPO_ROOT),
                         {"a": [{"b": ["<repo>/x"]}]})

    def test_non_strings_pass_through_unchanged(self):
        self.assertEqual(scrub_document({"n": 1, "b": True, "z": None},
                                        REPO_ROOT),
                         {"n": 1, "b": True, "z": None})


class TestWhatSurvivesTheScrubberIsRefused(unittest.TestCase):
    """Refused, not deleted. A document with text quietly removed from it is
    no longer the evidence it claims to be.

    These exercise the refusal layer directly rather than through
    ``safe_render``. The two layers have different jobs and the scrubber runs
    first, so a path that happens to be *this* machine's home is rewritten
    rather than refused - correct behaviour, and it would make an end-to-end
    assertion here depend on where the suite is checked out.
    ``TestTheRefusalAlsoFiresThroughSafeRender`` covers the pipeline.
    """

    def _refuses(self, payload):
        rendered = json.dumps(payload)
        with self.assertRaises(ScrubRefusal) as raised:
            reject_sensitive(rendered)
        return raised.exception

    def test_a_home_path_on_another_machine(self):
        self._refuses({"path": "/Users/someone/Projects/pgx"})

    def test_a_root_path(self):
        self._refuses({"path": "/root/work/whatever"})

    def test_a_windows_user_path(self):
        self._refuses({"path": "C:\\Users\\someone\\pgx"})

    def test_a_database_url_carrying_a_password(self):
        self._refuses({"url": "postgresql://pgx:hunter2@localhost/pgx_test"})

    def test_a_credential_assignment(self):
        for text in ("password=hunter2", "api_key: abc123",
                     "ACCESS_TOKEN = xyz", "secret: s3cr3t"):
            with self.subTest(text=text):
                self._refuses({"note": text})

    def test_a_bearer_token(self):
        self._refuses({"header": "Bearer abcdefghijklmnop"})

    def test_a_private_key_block(self):
        self._refuses({"key": "-----BEGIN RSA PRIVATE KEY-----"})

    def test_a_clinical_payload_field_as_a_key(self):
        for field in ("patient_name", "patient_id", "mrn", "date_of_birth",
                      "diplotype", "star_allele", "vcf"):
            with self.subTest(field=field):
                self._refuses({field: "anything"})

    def test_a_clinical_payload_field_embedded_in_a_string(self):
        """A skip reason that quoted a payload would arrive JSON-escaped, and
        a pattern that only matched a real key would miss it."""
        self._refuses({"reason": json.dumps({"patient_name": "x"})})

    def test_the_refusal_does_not_quote_the_whole_secret(self):
        """An error message that printed the credential would put it in a
        build log, which is the same disclosure by another route."""
        exception = self._refuses(
            {"url": "postgresql://pgx:averylongsecretpassword@host/db"})
        self.assertNotIn("averylongsecretpassword", str(exception))

    def test_the_refusal_names_what_it_found(self):
        exception = self._refuses({"note": "password=hunter2"})
        self.assertIn("credential", str(exception))

    def test_every_pattern_has_a_readable_name(self):
        for name, pattern in FORBIDDEN_PATTERNS:
            with self.subTest(name=name):
                self.assertTrue(name and name[0].islower())
                self.assertTrue(pattern.pattern)


class TestTheRefusalAlsoFiresThroughSafeRender(unittest.TestCase):
    """The pipeline, on something no scrubber replacement can rewrite."""

    def test_a_credential_survives_scrubbing_and_is_then_refused(self):
        with self.assertRaises(ScrubRefusal):
            safe_render({"note": "password=hunter2"}, REPO_ROOT)

    def test_a_clinical_field_survives_scrubbing_and_is_then_refused(self):
        with self.assertRaises(ScrubRefusal):
            safe_render({"patient_id": "P-1"}, REPO_ROOT)

    def test_a_foreign_home_path_survives_scrubbing_and_is_then_refused(self):
        """``/Users/...`` is nobody's home on a Linux build machine, so the
        scrubber leaves it and the refusal catches it."""
        with self.assertRaises(ScrubRefusal):
            safe_render({"path": "/Users/someone/Projects/pgx"},
                        REPO_ROOT, environ={"HOME": "/nonexistent"})


class TestAnHonestDocumentPassesThrough(unittest.TestCase):

    def test_test_identifiers_are_not_mistaken_for_paths(self):
        document = {"test_id": "tests.unit.domain.test_hashing.T.test_x",
                    "outcome": "PASS"}
        rendered = safe_render(document, REPO_ROOT)
        self.assertIn("tests.unit.domain.test_hashing", rendered)

    def test_the_rendering_is_the_project_canonical_form(self):
        rendered = safe_render({"b": 1, "a": 2}, REPO_ROOT)
        self.assertEqual(rendered, '{\n  "a": 2,\n  "b": 1\n}\n')

    def test_the_real_artifacts_survive_it(self):
        """The end-to-end version of every test above."""
        from pgx.verification.artifacts import build_artifacts
        for relative, rendered in build_artifacts(REPO_ROOT).items():
            with self.subTest(artifact=relative):
                reject_sensitive(rendered)
                self.assertTrue(rendered.endswith("\n"))
