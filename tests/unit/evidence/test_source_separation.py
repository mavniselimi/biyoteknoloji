# -*- coding: utf-8 -*-
"""What a source stated, kept apart from what this project concluded (WP-08).

The rule under test is one-directional. Source wording is preserved exactly,
including wording that reads like clinical advice, because censoring a source
would make the citation false. What is prohibited is that wording, or any
project field, arriving in the *normalized* part of an evidence record where a
later stage would read it as this project's own claim.
"""

from __future__ import annotations

import ast
import io
import json
import os
import unittest

from pgx.evidence.errors import ProhibitedFieldError
from pgx.evidence.models import (PROHIBITED_METADATA_FIELDS,
                                 RAW_PAYLOAD_NAMESPACE, find_prohibited_fields)

from tests.unit.evidence._support import (REPO_ROOT,
                                          RealEvidenceBuildTestCase, draft,
                                          fragment, source)


class TestProjectFieldsCannotEnterNormalizedMetadata(unittest.TestCase):

    def test_a_prohibited_field_is_refused_at_construction(self):
        for name in PROHIBITED_METADATA_FIELDS:
            with self.subTest(field=name):
                with self.assertRaises(ProhibitedFieldError) as caught:
                    draft(normalized_metadata={name: "anything"})
                self.assertIn(name, str(caught.exception))

    def test_a_prohibited_field_is_refused_however_deeply_it_is_nested(self):
        """A nested dict is the obvious way to smuggle one past a flat check."""
        with self.assertRaises(ProhibitedFieldError):
            draft(normalized_metadata={"a": {"b": [{"risk_level": "HIGH"}]}})

    def test_the_error_names_the_path_so_a_caller_can_find_it(self):
        """A dotted path, not a bare name: a nested offender is otherwise
        reported in terms that do not say where to look."""
        with self.assertRaises(ProhibitedFieldError) as caught:
            draft(normalized_metadata={"outer": {"demo_risk_level": 3}})
        self.assertIn("outer.demo_risk_level", caught.exception.fields)

    def test_an_ordinary_field_is_untouched(self):
        record = draft(normalized_metadata={"payload_relation": "IDENTICAL"})
        self.assertEqual(record.normalized_metadata["payload_relation"],
                         "IDENTICAL")

    def test_the_raw_namespace_cannot_be_claimed_by_normalized_metadata(self):
        """One namespace, one meaning. Two would make the boundary unreadable."""
        with self.assertRaises(Exception):
            draft(normalized_metadata={RAW_PAYLOAD_NAMESPACE: {"id": 1}})


class TestSourceOwnedFieldsAreNotProjectFields(unittest.TestCase):
    """A source field named ``recommendation`` is the source's, not ours.

    The prohibition is about the normalized layer. Running the same name check
    over an opaque source payload would reject real source records for using
    ordinary English, and would quietly delete the evidence this project
    exists to cite.
    """

    def test_a_source_payload_may_carry_a_field_called_recommendation(self):
        record = draft(raw_payload={"id": "PA1", "recommendation": "Avoid.",
                                    "risk": "high"})
        self.assertEqual(record.raw_source_payload["recommendation"], "Avoid.")
        self.assertEqual(record.raw_source_payload["risk"], "high")

    def test_the_scan_is_not_run_over_the_raw_payload(self):
        """The same names in the raw payload do not raise; in metadata they do."""
        draft(raw_payload={"risk_level": "HIGH", "plain_language_mvp": "x"})
        with self.assertRaises(ProhibitedFieldError):
            draft(normalized_metadata={"risk_level": "HIGH"})

    def test_find_prohibited_fields_reports_rather_than_deletes(self):
        found = find_prohibited_fields({"a": {"risk_level": 1, "keep": 2}})
        self.assertEqual(found, ("a.risk_level",))


class TestSourceWordingIsPreservedExactly(unittest.TestCase):

    CLINICAL = ("Avoid clopidogrel in CYP2C19 poor metabolizers; consider "
                "prasugrel or ticagrelor at standard dose.")

    def test_clinical_sounding_source_text_is_stored_verbatim(self):
        piece = fragment(text=self.CLINICAL)
        self.assertEqual(piece.text, self.CLINICAL)

    def test_the_exact_hash_distinguishes_whitespace_the_other_hash_ignores(self):
        spaced = fragment(text="a  b")
        tight = fragment(text="a b")
        self.assertEqual(spaced.text_hash, tight.text_hash)
        self.assertNotEqual(spaced.exact_text_hash, tight.exact_text_hash)

    def test_an_empty_fragment_is_refused(self):
        """Nothing quoted is not a quotation, and would hash like every other."""
        with self.assertRaises(Exception):
            fragment(text="")

    def test_each_field_keeps_its_own_fragment(self):
        summary = fragment(field_name="summaryMarkdown.html", text="S")
        recommendation = fragment(field_name="recommendation", text="R")
        self.assertNotEqual(summary.field_name, recommendation.field_name)
        self.assertNotEqual(summary.text_hash, recommendation.text_hash)


class TestTheEvidenceLayerNamesNoProjectConcept(unittest.TestCase):
    """Read from identifiers, not prose.

    Every module in this package explains in its docstring what it refuses to
    do, and those docstrings contain the very words a substring search would
    flag. Parsing the AST asks the question that matters: does any *name* in
    this package refer to a project interpretation?
    """

    PACKAGE = os.path.join("pgx", "evidence")
    FORBIDDEN = ("risk_level", "demo_risk_level", "attention_level",
                 "plain_language_mvp", "evidence_strength", "usable_for_mvp",
                 "normalized_phenotype_group", "candidate_score",
                 "treatment_selection", "CuratedInterpretation",
                 "ComputableRule", "RulesetVersion", "AssessmentFinding")

    def _identifiers(self, relative):
        tree = ast.parse(source(relative), filename=relative)
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                names.add(node.attr)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                   ast.ClassDef)):
                names.add(node.name)
            elif isinstance(node, ast.arg):
                names.add(node.arg)
        return names

    def test_no_module_defines_or_reads_a_project_interpretation_name(self):
        directory = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.dirname(os.path.abspath(__file__))))), self.PACKAGE)
        for name in sorted(os.listdir(directory)):
            if not name.endswith(".py"):
                continue
            relative = os.path.join(self.PACKAGE, name)
            with self.subTest(module=relative):
                identifiers = self._identifiers(relative)
                for token in self.FORBIDDEN:
                    # PROHIBITED_METADATA_FIELDS holds these as *strings* on
                    # purpose - that is the denylist. What must not exist is an
                    # identifier by that name.
                    self.assertNotIn(token, identifiers,
                                     "%s names %r" % (relative, token))


class TestTheRealBuildKeepsTheTwoLayersApart(RealEvidenceBuildTestCase):

    def test_no_stored_record_has_a_project_field_in_its_normalized_metadata(self):
        offences = []
        for row in self.rows("evidence-records.ndjson"):
            found = find_prohibited_fields(row.get("normalized_metadata") or {})
            if found:
                offences.append((row["natural_key"]["natural_key"], found))
        self.assertEqual(offences, [])

    def test_every_stored_record_keeps_its_raw_payload_under_the_namespace(self):
        rows = self.rows("evidence-records.ndjson")
        self.assertTrue(rows)
        for row in rows:
            self.assertIn(RAW_PAYLOAD_NAMESPACE, row)

    def test_the_project_vocabulary_exists_and_is_kept_out_of_the_store(self):
        """The separation is only meaningful if the vocabulary really exists.

        It does, in the legacy CSVs this project wrote: demo_risk_level,
        plain_language_mvp, evidence_strength and the rest are its own
        conclusions about the science. WP-08 reads them into unreviewed
        proposals stored outside the evidence build. So the assertion has two
        halves - the words are found where they belong, and nowhere in the
        evidence store - and neither half can pass vacuously.
        """
        proposals = os.path.join(REPO_ROOT, "data", "migration", "wp08",
                                 "draft-curation-proposals.ndjson")
        if not os.path.isfile(proposals):
            self.skipTest("no draft-curation artifact; run "
                          "pgx-evidence extract-draft-curation")
        with io.open(proposals, encoding="utf-8") as handle:
            found = set()
            for line in handle:
                if not line.strip():
                    continue
                for name in json.loads(line).get("legacy_values") or {}:
                    if name in PROHIBITED_METADATA_FIELDS:
                        found.add(name)
        self.assertTrue(
            found,
            "the legacy project vocabulary was not found in the draft "
            "curation artifact, so the exclusion asserted below proves "
            "nothing")

        # And not one of those names reaches a stored evidence record.
        offences = []
        for row in self.rows("evidence-records.ndjson"):
            metadata = row.get("normalized_metadata") or {}
            for name in sorted(found):
                if name in metadata:
                    offences.append((row["natural_key"]["natural_key"], name))
        self.assertEqual(offences, [])
