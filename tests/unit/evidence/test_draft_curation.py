# -*- coding: utf-8 -*-
"""Legacy interpretations become proposals, never curations (WP-08).

Everything this project once concluded about the science - a risk level, a
patient-facing sentence, an effect direction - is read out of the legacy files
and written down as an unreviewed candidate, outside the evidence store, with
no author and no approval. A migration that produced a ``CuratedInterpretation``
would be asserting that somebody reviewed it.
"""

from __future__ import annotations

import ast
import io
import json
import os
import unittest

from pgx.evidence.draft_curation import (DRAFT_CURATION_VERSION,
                                         LEGACY_INTERPRETATION_FIELDS,
                                         PROPOSAL_STATUS, PROPOSAL_WARNINGS,
                                         DraftCurationProposal, ProposalOrigin,
                                         extract_draft_curation,
                                         read_manual_effect_hints)

from tests.unit.evidence._support import REPO_ROOT, source

ARTIFACT = os.path.join(REPO_ROOT, "data", "migration", "wp08",
                        "draft-curation-proposals.ndjson")


class TestLegacyCodeIsReadAndNeverExecuted(unittest.TestCase):
    """``MANUAL_EFFECT_HINTS`` lives in a script that writes files at import.

    Importing the module to read one constant would run every top-level
    statement in it, including its own file writing. The module is parsed and
    only that one assignment is evaluated, with ``ast.literal_eval``.
    """

    def test_the_hints_are_recovered_without_importing_the_module(self):
        hints, origin, line = read_manual_effect_hints(REPO_ROOT)
        if not hints:
            self.skipTest("clean_mvp_seed_dataset.py is not in this checkout")
        self.assertIsInstance(hints, dict)
        self.assertIsInstance(origin, ProposalOrigin)
        self.assertIsInstance(line, int)

    def test_the_module_is_never_imported_and_never_executed(self):
        """Read from identifiers: the docstring says the words on purpose."""
        tree = ast.parse(source(os.path.join("pgx", "evidence",
                                             "draft_curation.py")))
        called = set()
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name):
                    called.add(func.id)
                elif isinstance(func, ast.Attribute):
                    called.add(func.attr)
            elif isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported.add(node.module)
        for forbidden in ("exec", "eval", "compile", "import_module",
                          "__import__", "run_path", "spec_from_file_location"):
            self.assertNotIn(forbidden, called)
        self.assertNotIn("clean_mvp_seed_dataset", imported)
        self.assertIn("literal_eval", called)

    def test_it_opens_nothing_for_writing(self):
        tree = ast.parse(source(os.path.join("pgx", "evidence",
                                             "draft_curation.py")))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = getattr(node.func, "attr", getattr(node.func, "id", ""))
                if name not in ("open",):
                    continue
                modes = [arg.value for arg in node.args[1:]
                         if isinstance(arg, ast.Constant)]
                modes += [kw.value.value for kw in node.keywords
                          if kw.arg == "mode"
                          and isinstance(kw.value, ast.Constant)]
                for mode in modes:
                    self.assertNotIn("w", str(mode))
                    self.assertNotIn("a", str(mode))


class TestAProposalCannotPretendToBeCurated(unittest.TestCase):

    def _proposal(self, **overrides):
        # An origin is mandatory: a proposal that cannot say which file and
        # row it came from is an assertion with no provenance, which is the
        # thing this whole work package exists to prevent.
        payload = dict(proposal_id="p1", subject="PA1",
                       legacy_values={"demo_risk_level": "high"},
                       origins=(ProposalOrigin(
                           relative_path="phenotype_effect_rules.csv",
                           file_sha256="sha256:" + "ab" * 32,
                           row_number=1),),
                       linked_evidence=(), linked_record_uuids=())
        payload.update(overrides)
        return DraftCurationProposal(**payload)

    def test_a_proposal_with_no_origin_is_refused(self):
        with self.assertRaises(Exception):
            self._proposal(origins=())

    def test_the_status_is_fixed(self):
        self.assertEqual(self._proposal().status, PROPOSAL_STATUS)
        with self.assertRaises(Exception):
            self._proposal(status="APPROVED")

    def test_the_warnings_cannot_be_trimmed(self):
        self.assertEqual(self._proposal().warnings, PROPOSAL_WARNINGS)
        with self.assertRaises(Exception):
            self._proposal(warnings=("NOT_EVIDENCE",))

    def test_the_warnings_say_all_four_things(self):
        for warning in ("NOT_EVIDENCE", "NOT_SCIENTIFICALLY_REVIEWED",
                        "NOT_EXECUTABLE", "DO_NOT_USE_FOR_ASSESSMENT"):
            self.assertIn(warning, PROPOSAL_WARNINGS)

    def test_a_proposal_names_no_author_and_no_reviewer(self):
        payload = self._proposal().to_json()
        for forbidden in ("created_by", "reviewed_by", "reviewer",
                          "approved_by", "approved_at", "curator"):
            self.assertNotIn(forbidden, payload)


class TestExtractionOverTheRealLegacyFiles(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.result = extract_draft_curation(REPO_ROOT, ())
        if not cls.result.proposals:
            raise unittest.SkipTest("no legacy interpretation files here")

    def test_it_reads_the_files_it_says_it_reads(self):
        read = {item["relative_path"] for item in self.result.sources_read}
        self.assertTrue(read & set(LEGACY_INTERPRETATION_FIELDS))

    def test_the_project_vocabulary_is_what_it_extracted(self):
        for name in ("demo_risk_level", "plain_language_mvp",
                     "evidence_strength", "usable_for_mvp"):
            self.assertIn(name, self.result.field_categories)

    def test_two_runs_agree_exactly(self):
        again = extract_draft_curation(REPO_ROOT, ())
        self.assertEqual(again.content_hash(), self.result.content_hash())

    def test_every_proposal_carries_the_version_that_produced_it(self):
        for proposal in self.result.proposals[:20]:
            self.assertEqual(proposal.to_json()["draft_curation_version"],
                             DRAFT_CURATION_VERSION)


class TestTheWrittenArtifactStaysOutsideTheEvidenceStore(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not os.path.isfile(ARTIFACT):
            raise unittest.SkipTest("no draft-curation artifact in this "
                                    "checkout")
        with io.open(ARTIFACT, encoding="utf-8") as handle:
            cls.rows = [json.loads(line) for line in handle if line.strip()]

    def test_it_is_not_inside_a_sealed_evidence_build(self):
        self.assertNotIn(os.path.join("data", "evidence"), ARTIFACT)

    def test_every_row_is_unreviewed_and_says_so(self):
        for row in self.rows:
            self.assertEqual(row["status"], PROPOSAL_STATUS)
            self.assertEqual(tuple(row["warnings"]), PROPOSAL_WARNINGS)

    def test_linking_used_a_source_declared_identifier_or_nothing(self):
        """A proposal is attached to evidence by an identifier the source
        published, or it stays unlinked with a note. It is never attached to a
        plausible neighbour."""
        unlinked = [row for row in self.rows if not row.get("linked_evidence")]
        for row in unlinked:
            self.assertTrue(row.get("linkage_note"))

    def test_most_proposals_did_link_so_the_check_above_is_not_vacuous(self):
        linked = [row for row in self.rows if row.get("linked_evidence")]
        self.assertTrue(linked)
