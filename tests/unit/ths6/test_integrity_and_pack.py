# -*- coding: utf-8 -*-
"""Two levels of hash, no self-hash, and no path that leaks a machine.

The self-hash test is the one worth reading. A manifest containing a digest of
itself can never satisfy its own check - writing the digest changes the bytes
the digest describes - so a project that tries usually ends up excluding the
field from the comparison, at which point the manifest is covered by nothing.
The manifest here excludes itself from its member list and publishes the
level-two digest as the pack's identity, which a verifier recomputes.

The leak tests matter for a different reason: this pack is meant to
circulate. An absolute path in it names the machine it was built on and
whoever was logged in.

Nothing in this file writes to the repository. Build tests run against
temporary trees; verification tests read the committed pack.
"""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest

from pgx.ths6.artifacts import (ARTIFACT_PATHS, DETERMINISTIC_ARTIFACT_PATHS,
                                PACK_MEMBER_PATHS)
from pgx.ths6.integrity import (MANIFEST_MEMBER_PATH, build_pack_manifest,
                                canonical_json, member_digest, pack_digest,
                                verify_pack_manifest)
from pgx.ths6.pack import leaked_absolute_paths, verify_pack
from pgx.ths6.vocabulary import PACK_INTEGRITY_IS_NOT_ACHIEVEMENT

_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def _tree(directory, files):
    for relative, text in files.items():
        path = os.path.join(directory, *relative.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with io.open(path, "w", encoding="utf-8") as handle:
            handle.write(text)


class TestCanonicalJson(unittest.TestCase):

    def test_keys_are_sorted_and_ascii(self):
        rendered = canonical_json({"b": 1, "a": "\u00e7"})
        self.assertTrue(rendered.startswith('{\n  "a"'))
        self.assertIn("\\u00e7", rendered)

    def test_it_ends_with_a_newline(self):
        self.assertTrue(canonical_json({"a": 1}).endswith("\n"))

    def test_the_same_document_renders_identically(self):
        document = {"a": [1, 2], "b": {"c": None}}
        self.assertEqual(canonical_json(document), canonical_json(document))


class TestTwoLevelHashing(unittest.TestCase):

    def test_a_member_digest_is_over_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            _tree(directory, {"a.txt": "hello\n"})
            digest = member_digest(os.path.join(directory, "a.txt"))
        self.assertRegex(digest, r"^sha256:[0-9a-f]{64}$")

    def test_the_pack_digest_covers_paths_and_digests_only(self):
        """Sizes and observations must not enter the pack identity."""
        first = pack_digest([{"path": "a", "sha256": "sha256:" + "0" * 64,
                              "bytes": 10}])
        second = pack_digest([{"path": "a", "sha256": "sha256:" + "0" * 64,
                               "bytes": 999999}])
        self.assertEqual(first, second)

    def test_the_pack_digest_changes_when_a_member_changes(self):
        first = pack_digest([{"path": "a", "sha256": "sha256:" + "0" * 64}])
        second = pack_digest([{"path": "a", "sha256": "sha256:" + "1" * 64}])
        self.assertNotEqual(first, second)

    def test_the_pack_digest_changes_when_a_member_is_added(self):
        first = pack_digest([{"path": "a", "sha256": "sha256:" + "0" * 64}])
        second = pack_digest([{"path": "a", "sha256": "sha256:" + "0" * 64},
                              {"path": "b", "sha256": "sha256:" + "0" * 64}])
        self.assertNotEqual(first, second)

    def test_the_pack_digest_is_order_independent(self):
        entries = [{"path": "b", "sha256": "sha256:" + "1" * 64},
                   {"path": "a", "sha256": "sha256:" + "0" * 64}]
        self.assertEqual(pack_digest(entries),
                         pack_digest(list(reversed(entries))))


class TestManifestExcludesItself(unittest.TestCase):

    def setUp(self):
        self.directory = tempfile.mkdtemp()
        _tree(self.directory, {"data/ths6/a.json": "{}\n",
                               "data/ths6/b.json": "{\"x\": 1}\n"})
        self.manifest = build_pack_manifest(
            self.directory,
            ["data/ths6/a.json", "data/ths6/b.json", MANIFEST_MEMBER_PATH],
            pack_version="test/1")

    def test_the_manifest_is_not_one_of_its_own_members(self):
        paths = {item["path"] for item in self.manifest["members"]}
        self.assertNotIn(MANIFEST_MEMBER_PATH, paths)

    def test_there_is_no_self_hash(self):
        self.assertIsNone(self.manifest["manifest_self_hash"])
        self.assertIs(self.manifest["manifest_excludes_itself"], True)

    def test_the_self_hash_absence_is_explained(self):
        self.assertIn("could never satisfy its own check",
                      self.manifest["manifest_self_hash_note"])

    def test_it_carries_the_integrity_disclaimer(self):
        self.assertEqual(self.manifest["integrity_note"],
                         PACK_INTEGRITY_IS_NOT_ACHIEVEMENT)

    def tearDown(self):
        import shutil

        shutil.rmtree(self.directory, ignore_errors=True)


class TestVerification(unittest.TestCase):

    def setUp(self):
        self.directory = tempfile.mkdtemp()
        _tree(self.directory, {"data/ths6/a.json": "{}\n",
                               "data/ths6/b.json": "{\"x\": 1}\n"})
        self.members = ["data/ths6/a.json", "data/ths6/b.json"]
        self.manifest = build_pack_manifest(self.directory, self.members,
                                            pack_version="test/1")

    def tearDown(self):
        import shutil

        shutil.rmtree(self.directory, ignore_errors=True)

    def test_an_unchanged_pack_is_intact(self):
        result = verify_pack_manifest(self.directory, self.manifest)
        self.assertIs(result["intact"], True)
        self.assertEqual(result["changed_members"], [])

    def test_a_changed_member_is_reported_with_both_digests(self):
        _tree(self.directory, {"data/ths6/a.json": "{\"changed\": true}\n"})
        result = verify_pack_manifest(self.directory, self.manifest)
        self.assertIs(result["intact"], False)
        self.assertEqual(len(result["changed_members"]), 1)
        entry = result["changed_members"][0]
        self.assertNotEqual(entry["expected"], entry["observed"])

    def test_a_deleted_member_is_reported(self):
        os.remove(os.path.join(self.directory, "data", "ths6", "b.json"))
        result = verify_pack_manifest(self.directory, self.manifest)
        self.assertIs(result["intact"], False)
        self.assertEqual(result["absent_member_paths"], ["data/ths6/b.json"])

    def test_the_pack_digest_is_recomputed_not_trusted(self):
        forged = dict(self.manifest)
        forged["pack_sha256"] = "sha256:" + "f" * 64
        result = verify_pack_manifest(self.directory, forged)
        self.assertIs(result["pack_digest_matches"], False)
        self.assertIs(result["intact"], False)

    def test_verification_reports_rather_than_raises(self):
        os.remove(os.path.join(self.directory, "data", "ths6", "a.json"))
        result = verify_pack_manifest(self.directory, self.manifest)
        self.assertIn("absent_member_paths", result)

    def test_it_carries_the_achievement_disclaimer(self):
        result = verify_pack_manifest(self.directory, self.manifest)
        self.assertIn("says nothing about", result["achievement_note"])


class TestAbsolutePathLeakDetection(unittest.TestCase):

    def test_a_posix_home_directory_is_detected(self):
        found = leaked_absolute_paths('{"path": "/Users/somebody/x.json"}')
        self.assertTrue(found)
        self.assertEqual(found[0]["pattern"], "posix_home")

    def test_a_linux_home_directory_is_detected(self):
        self.assertTrue(leaked_absolute_paths('"/home/somebody/repo"'))

    def test_a_windows_drive_letter_is_detected(self):
        self.assertTrue(leaked_absolute_paths('"C:\\\\Users\\\\x"'))

    def test_an_absolute_system_root_is_detected(self):
        self.assertTrue(leaked_absolute_paths('"/opt/pw-browsers/chromium"'))
        self.assertTrue(leaked_absolute_paths('"/etc/passwd"'))

    def test_a_repository_relative_path_is_not_flagged(self):
        self.assertEqual(
            leaked_absolute_paths('{"path": "data/ths6/wp25-status.json"}'),
            ())

    def test_a_url_path_is_not_flagged(self):
        self.assertEqual(
            leaked_absolute_paths('"https://json-schema.org/draft/2020-12"'),
            ())

    def test_the_report_gives_a_location_not_the_value(self):
        """A leak report that quoted the leak would be a second copy of it."""
        found = leaked_absolute_paths('x\n{"p": "/Users/somebody/x"}\n')
        self.assertEqual(found[0]["line"], 2)
        self.assertNotIn("somebody", json.dumps(found))


class TestTheCommittedPack(unittest.TestCase):
    """Read-only checks against the pack this repository ships."""

    def setUp(self):
        self.path = os.path.join(_ROOT, *MANIFEST_MEMBER_PATH.split("/"))
        if not os.path.isfile(self.path):
            self.skipTest("the pack has not been built in this tree")
        with io.open(self.path, "r", encoding="utf-8") as handle:
            self.manifest = json.load(handle)

    def test_the_committed_pack_is_intact(self):
        result = verify_pack_manifest(_ROOT, self.manifest)
        self.assertIs(result["intact"], True,
                      "the committed pack no longer describes this tree; "
                      "run `pgx-ths6 build-pack`")

    def test_verify_pack_exits_zero_for_an_intact_blocked_programme(self):
        """An honest pack about a blocked programme is a successful pack."""
        result = verify_pack(_ROOT)
        self.assertIs(result["pack_integrity_pass"], True)
        self.assertEqual(result["exit_code"], 0)
        self.assertIs(result["ths6_achieved"], False)

    def test_the_pack_reports_the_programme_separately(self):
        result = verify_pack(_ROOT)
        self.assertNotEqual(result["exit_code"],
                            result["ths6_status_exit_code"])
        self.assertEqual(result["ths6_status_exit_code"], 2)

    def test_no_member_path_is_absolute(self):
        for entry in self.manifest["members"]:
            with self.subTest(path=entry["path"]):
                self.assertFalse(entry["path"].startswith(("/", "~", "\\")))

    def test_every_declared_artifact_is_a_member(self):
        paths = {entry["path"] for entry in self.manifest["members"]}
        for relative in sorted(ARTIFACT_PATHS):
            if relative == MANIFEST_MEMBER_PATH:
                continue
            with self.subTest(path=relative):
                self.assertIn(relative, paths)

    def test_the_schemas_and_final_documents_are_members(self):
        paths = {entry["path"] for entry in self.manifest["members"]}
        self.assertTrue(any(item.startswith("schemas/wp25/")
                            for item in paths))
        self.assertTrue(any(item.startswith("docs/ths6/final/")
                            for item in paths))

    def test_no_preliminary_document_is_a_pack_member(self):
        from pgx.ths6.evidence_registry import PRELIMINARY_THS6_DOCUMENTS

        paths = {entry["path"] for entry in self.manifest["members"]}
        for relative in PRELIMINARY_THS6_DOCUMENTS:
            with self.subTest(path=relative):
                self.assertNotIn(relative, paths)

    def test_the_pack_has_no_absolute_path_or_secret(self):
        result = verify_pack(_ROOT)
        self.assertEqual(result["scan"]["absolute_path_leak_count"], 0)
        self.assertEqual(result["scan"]["secret_finding_count"], 0)
        self.assertIs(result["scan"]["scanner_available"], True)

    def test_the_member_discovery_covers_the_three_roots(self):
        members = PACK_MEMBER_PATHS(_ROOT)
        self.assertTrue(any(item.startswith("data/ths6/")
                            for item in members))
        self.assertTrue(any(item.startswith("schemas/wp25/")
                            for item in members))
        self.assertTrue(any(item.startswith("docs/ths6/final/")
                            for item in members))


class TestDeterministicSubset(unittest.TestCase):

    def test_only_declarations_are_offered_for_byte_comparison(self):
        """A document that measures the tree must not be compared byte for
        byte between machines."""
        self.assertEqual(
            set(DETERMINISTIC_ARTIFACT_PATHS),
            {"data/ths6/wp25-contingency-matrix.json",
             "data/ths6/wp25-demo-manifest.json",
             "data/ths6/wp25-signoff-matrix.json"})

    def test_the_measuring_documents_are_excluded(self):
        from pgx.verification.reproducibility import ENVIRONMENT_DEPENDENT

        for relative in sorted(ARTIFACT_PATHS):
            if relative in DETERMINISTIC_ARTIFACT_PATHS:
                continue
            with self.subTest(path=relative):
                self.assertIn(relative, ENVIRONMENT_DEPENDENT)

    def test_no_deterministic_artifact_is_also_excluded(self):
        from pgx.verification.reproducibility import ENVIRONMENT_DEPENDENT

        for relative in DETERMINISTIC_ARTIFACT_PATHS:
            with self.subTest(path=relative):
                self.assertNotIn(relative, ENVIRONMENT_DEPENDENT)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class TestTheFinalDocumentation(unittest.TestCase):
    """The pack's prose is a public surface and is checked like one."""

    def setUp(self):
        self.directory = os.path.join(_ROOT, "docs", "ths6", "final")
        if not os.path.isdir(self.directory):
            self.skipTest("the final documentation has not been written")
        self.names = sorted(name for name in os.listdir(self.directory)
                            if name.endswith(".md"))

    def test_there_are_at_least_twenty_documents(self):
        self.assertGreaterEqual(len(self.names), 20)

    def test_the_named_documents_all_exist(self):
        for name in ("README.md", "executive-summary.md", "demo-runbook.md",
                     "evidence-index.md", "definition-of-done.md",
                     "claim-boundary.md", "traceability.md",
                     "contingency-plan.md", "human-signoff.md",
                     "open-blockers.md", "findings-and-discrepancies.md",
                     "what-remains.md", "verification-instructions.md",
                     "limitations-and-scope.md", "pack-integrity.md",
                     "vocabulary.md"):
            with self.subTest(name=name):
                self.assertIn(name, self.names)

    def test_there_is_one_document_per_gate(self):
        for letter, slug in (("a", "scientific-data"), ("b", "rules"),
                             ("c", "core-safety"), ("d", "validation"),
                             ("e", "operational"), ("f", "ths6")):
            with self.subTest(gate=letter):
                self.assertIn("gate-%s-%s.md" % (letter, slug), self.names)

    def test_the_executive_summary_and_runbook_are_in_turkish(self):
        """Two documents must be readable by a Turkish-speaking reviewer."""
        for name, marker in (("executive-summary.md", "Yönetici özeti"),
                             ("demo-runbook.md", "Gösterim el kitabı")):
            with self.subTest(name=name):
                with io.open(os.path.join(self.directory, name), "r",
                             encoding="utf-8") as handle:
                    text = handle.read()
                self.assertIn(marker, text)

    def test_no_document_contains_an_absolute_path(self):
        for name in self.names:
            with io.open(os.path.join(self.directory, name), "r",
                         encoding="utf-8") as handle:
                text = handle.read()
            with self.subTest(name=name):
                self.assertEqual(leaked_absolute_paths(text), ())

    def test_no_document_makes_a_prohibited_claim(self):
        """WP-15's scanner, applied to this pack's own public prose.

        Governance prose is not report text, so a hit here is usually a
        negation or a quotation rather than a claim - which is precisely why
        it is checked rather than assumed. Seven sentences were reworded
        during WP-25 to clear this scan without weakening what they said.
        """
        from pgx.reporting.gate import scan_report_text

        for name in self.names:
            with io.open(os.path.join(self.directory, name), "r",
                         encoding="utf-8") as handle:
                text = handle.read()
            with self.subTest(name=name):
                violations = scan_report_text(text).violations
                self.assertEqual(
                    [(item.rule_id, item.matched_text)
                     for item in violations], [])

    def test_no_committed_artifact_makes_a_prohibited_claim(self):
        from pgx.reporting.gate import scan_report_text

        directory = os.path.join(_ROOT, "data", "ths6")
        for name in sorted(os.listdir(directory)):
            path = os.path.join(directory, name)
            if not os.path.isfile(path):
                continue
            with io.open(path, "r", encoding="utf-8") as handle:
                text = handle.read()
            with self.subTest(name=name):
                self.assertEqual(scan_report_text(text).violations, ())

    def test_the_readme_states_both_results_separately(self):
        with io.open(os.path.join(self.directory, "README.md"), "r",
                     encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("An intact pack is not an achieved standard", text)
        self.assertIn("`ths6_achieved`", text)

    def test_the_repository_readme_distinguishes_the_two(self):
        with io.open(os.path.join(_ROOT, "README.md"), "r",
                     encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("WP-25 implementation complete is not THS 6 complete",
                      text)
