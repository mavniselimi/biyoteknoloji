# -*- coding: utf-8 -*-
"""The committed HTML snapshots, and what they are allowed to claim.

Two jobs. First, keep them current: a template change that is not regenerated
fails here rather than leaving a stale file in the repository for someone to
read as the truth. Second, keep them honest: they are rendered template output
and they must never be describable, or mistakable, as browser captures.
"""

from __future__ import annotations

import io
import os
import unittest

from apps.web.claim_gate import scan_page
from pgx.domain.claims import canonical_clinical_warning
from tests.fixtures.wp17.snapshots import (BANNER, EXCLUDED_PAGES,
                                           SNAPSHOT_DIR, build_all_pages,
                                           build_snapshots)
from tests.unit.web._support import inspect


def _on_disk():
    if not os.path.isdir(SNAPSHOT_DIR):
        return {}
    found = {}
    for name in sorted(os.listdir(SNAPSHOT_DIR)):
        if not name.endswith(".html"):
            continue
        with io.open(os.path.join(SNAPSHOT_DIR, name),
                     encoding="utf-8") as handle:
            found[name] = handle.read()
    return found


class TestTheSnapshotsAreCurrent(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.rendered = build_snapshots()
        cls.stored = _on_disk()

    def test_every_rendered_page_has_a_committed_snapshot(self):
        self.assertEqual(sorted(self.stored), sorted(self.rendered),
                         "run: python -m tests.fixtures.wp17.snapshots")

    def test_each_snapshot_matches_what_the_templates_render_now(self):
        for name, html in sorted(self.rendered.items()):
            with self.subTest(page=name):
                self.assertEqual(
                    self.stored.get(name), html,
                    "%s is stale; run: python -m tests.fixtures.wp17.snapshots"
                    % name)

    def test_regenerating_twice_produces_the_same_bytes(self):
        self.assertEqual(build_snapshots(), self.rendered)

    def test_no_excluded_page_was_written_to_disk(self):
        for name in EXCLUDED_PAGES:
            self.assertNotIn(name, self.stored)


class TestTheExclusionsAreStillJustified(unittest.TestCase):
    """Each excluded page must actually vary. Otherwise, snapshot it.

    An exclusion nobody rechecks becomes a permanent gap in the evidence, so
    the claim behind it - "this page carries a value that is new on every
    run" - is tested rather than asserted in a comment. If a page here starts
    rendering identically twice, this fails and the page joins the committed
    set.
    """

    def test_every_excluded_page_differs_between_two_runs(self):
        first = build_all_pages()
        second = build_all_pages()
        for name in EXCLUDED_PAGES:
            with self.subTest(page=name):
                self.assertIn(name, first)
                self.assertNotEqual(
                    first[name], second[name],
                    "%s is stable now; commit it as a snapshot and remove it "
                    "from EXCLUDED_PAGES" % name)

    def test_the_excluded_pages_are_otherwise_identical(self):
        # The variance must be confined to the identifiers named in the
        # module docstring. If two runs differ in their prose, their status
        # codes or their structure, something larger is non-deterministic and
        # the exclusion is hiding it.
        import re

        uuid = re.compile(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            re.IGNORECASE)
        digest = re.compile(r"[0-9a-f]{64}", re.IGNORECASE)

        def normalised(text):
            return digest.sub("D", uuid.sub("U", text))

        first = build_all_pages()
        second = build_all_pages()
        for name in EXCLUDED_PAGES:
            with self.subTest(page=name):
                self.assertEqual(normalised(first[name]),
                                 normalised(second[name]))


class TestTheSnapshotsDoNotClaimToBeScreenshots(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.stored = _on_disk()

    def test_every_snapshot_says_what_it_is_in_its_first_bytes(self):
        for name, html in sorted(self.stored.items()):
            with self.subTest(page=name):
                self.assertTrue(html.startswith(BANNER), name)
                self.assertIn("Not a screenshot", html)

    def test_no_snapshot_is_an_image(self):
        for name in sorted(os.listdir(SNAPSHOT_DIR)):
            with self.subTest(entry=name):
                self.assertTrue(name.endswith(".html"),
                                "%s is not rendered HTML" % name)

    def test_the_gate_status_note_describes_these_files_accurately(self):
        """These files are template output. The note must keep saying so.

        It has to do that in both states of the host: when no browser has run
        and the note is about the absence of captures, and when one has and
        the note is about captures that exist. What must never happen is the
        two being described as one kind of artifact - which is exactly what a
        reader would conclude from a note that mentioned only "screenshots
        under tests/fixtures/wp17/".
        """
        from apps.web.gate_status import build_ui_gate_status

        status = build_ui_gate_status()
        note = status["screenshot_evidence_note"]
        self.assertIn("tests/fixtures/wp17/snapshots/", note)
        self.assertTrue("not browser captures" in note
                        or "not captures" in note, note)
        self.assertIn(status["screenshot_evidence_status"],
                      ("NONE", "CAPTURED"))
        if status["screenshot_evidence_status"] == "NONE":
            self.assertEqual(status["screenshot_evidence_count"], 0)


class TestTheSnapshotsSatisfyThePageContract(unittest.TestCase):
    """What is asserted of a live page is asserted of the committed bytes.

    A snapshot that passed review while the live page did not - or the other
    way round - would make the files misleading in the one way that matters,
    so the page contract is re-checked here against the files themselves.
    """

    @classmethod
    def setUpClass(cls):
        cls.stored = _on_disk()

    def test_every_snapshot_carries_the_canonical_warning(self):
        warning = canonical_clinical_warning("tr")
        for name, html in sorted(self.stored.items()):
            with self.subTest(page=name):
                self.assertIn(warning, html)

    def test_every_snapshot_passes_the_claim_gate(self):
        for name, html in sorted(self.stored.items()):
            with self.subTest(page=name):
                report = scan_page(html)
                self.assertTrue(
                    report.is_clean,
                    "%s: %s %s %s" % (name, report.rule_ids,
                                      report.structural_problems,
                                      report.unsafe_urls))

    def test_every_snapshot_has_one_h1_and_a_main_landmark(self):
        for name, html in sorted(self.stored.items()):
            with self.subTest(page=name):
                page = inspect(html)
                self.assertEqual(page.heading_levels.count(1), 1)
                self.assertEqual(len(page.find("main")), 1)
                for landmark in ("header", "nav", "main", "footer"):
                    self.assertIn(landmark, page.landmarks)

    def test_no_snapshot_references_a_remote_origin(self):
        for name, html in sorted(self.stored.items()):
            with self.subTest(page=name):
                lowered = html.lower()
                self.assertNotIn("http://", lowered)
                # https:// appears only in a schema identifier, never as a
                # fetched resource, so any occurrence is checked in context.
                for index, line in enumerate(html.splitlines(), 1):
                    if "https://" in line:
                        self.assertNotIn("src=", line, "%s:%d" % (name, index))
                        self.assertNotIn("href=", line,
                                         "%s:%d" % (name, index))


class TestTheWordingMatchesWhatTheArtifactsContain(unittest.TestCase):
    """Documentation checked against the files it describes.

    The captures and snapshots were described as containing "no real gene" -
    and two of them render CYP1A2, CYP2C19, CYP2C9, CYP2D6 and CYP3A4, because
    the migrated development cases name real genes and the migration kept
    those identities on purpose. The claim was false in a way nobody would
    catch by reading it, because it *sounds* like the careful thing to say.

    A gene symbol is published nomenclature, not data about a person, so the
    artifacts were fine and the sentence was not. These tests pin the accurate
    claim to the actual contents, so the two cannot drift again: if a document
    denies gene symbols while a committed artifact renders one, this fails.
    """

    #: Public gene symbols the migrated development cases carry.
    PUBLIC_GENE_SYMBOLS = ("CYP1A2", "CYP2C19", "CYP2C9", "CYP2D6", "CYP3A4")

    #: Every document that describes the captures or the snapshots.
    DOCUMENTS = (
        "docs/evidence/wp17-ui-verification.md",
        "tests/fixtures/wp17/snapshots.py",
        "tests/integration/web/test_browser_e2e.py",
    )

    def _repo_text(self, relative):
        import io as _io
        import os

        from tests.unit.web._support import REPO_ROOT

        with _io.open(os.path.join(REPO_ROOT, *relative.split("/")),
                      encoding="utf-8") as handle:
            return handle.read()

    def test_the_artifacts_really_do_carry_public_gene_symbols(self):
        """The premise, checked first. Otherwise the rest proves nothing."""
        stored = _on_disk()
        found = {symbol for symbol in self.PUBLIC_GENE_SYMBOLS
                 for html in stored.values() if symbol in html}
        self.assertTrue(
            found,
            "no committed snapshot carries a gene symbol; if the fixtures "
            "changed, the wording these tests defend should change with them")

    def test_no_document_denies_what_the_artifacts_show(self):
        import re

        denial = re.compile(
            r"no\s+(?:capture|snapshot|image)?\s*\w*\s*(?:shows|contains|is)?"
            r"[^.]{0,60}\breal gene\b", re.IGNORECASE)
        for relative in self.DOCUMENTS:
            with self.subTest(document=relative):
                match = denial.search(self._repo_text(relative))
                self.assertIsNone(
                    match,
                    "%s denies real genes while committed artifacts render "
                    "public gene symbols: %r"
                    % (relative, match.group(0) if match else ""))

    def test_every_document_states_the_accurate_position(self):
        """Three things, all of which are true and none of which is implied.

        Public identifiers may appear; the inputs are synthetic development
        fixtures; no real patient data or validation evidence is shown. A
        document that dropped the middle clause would leave a reader unsure
        whether the *cases* were real, which is the question that matters.
        """
        for relative in self.DOCUMENTS:
            text = self._repo_text(relative).lower()
            with self.subTest(document=relative):
                self.assertIn("gene symbol", text)
                self.assertTrue("development fixture" in text
                                or "synthetic" in text, relative)
                self.assertIn("no real patient data", text)
                self.assertIn("validation evidence", text)

    def test_the_snapshot_banner_says_it_too(self):
        for name, html in _on_disk().items():
            with self.subTest(page=name):
                header = html[:len(BANNER)]
                self.assertIn("Public gene symbols may appear", header)
                self.assertIn("No real patient data", header)

    def test_no_artifact_carries_a_synthetic_person_identifier(self):
        """What the claim actually rules out, checked rather than asserted."""
        stored = _on_disk()
        for name, html in stored.items():
            with self.subTest(page=name):
                lowered = html.lower()
                for token in ("mrn", "patient_name", "date_of_birth",
                              "national_id", "tckn"):
                    self.assertNotIn(token, lowered)
