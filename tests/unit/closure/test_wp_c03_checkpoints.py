# -*- coding: utf-8 -*-
"""WP-C03: the human decision checkpoint packages.

Four decisions block the first release, and the packages exist so a person
can make them. Almost every test here is about what the packages must *not*
say: no approval, no name, no date, no status that has moved. A generated
governance package that quietly approved something would be worse than no
package at all, because it would look like a record.
"""

from __future__ import annotations

import csv
import io
import os
import shutil
import tempfile
import unittest

from pgx.closure.checkpoints import (CHECKPOINTS, PACKAGE_FILES, _approval_form,
                                     build_all)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
CHECKPOINT_ROOT = os.path.join(REPO_ROOT, "docs", "closure", "checkpoints")

EXPECTED_CHECKPOINTS = 4
EXPECTED_REGISTRY_SOURCES = 20


def _baseline():
    from scripts.build_closure_wave01_checkpoints import baseline_facts
    return baseline_facts(REPO_ROOT)


def _read(path):
    with io.open(path, encoding="utf-8") as handle:
        return handle.read()


def _rows(text):
    return list(csv.DictReader(io.StringIO(text)))


class TestThePackagesAreComplete(unittest.TestCase):

    def test_there_are_four_checkpoints(self):
        self.assertEqual(len(CHECKPOINTS), EXPECTED_CHECKPOINTS)

    def test_every_checkpoint_has_every_file(self):
        for checkpoint in CHECKPOINTS:
            directory = os.path.join(CHECKPOINT_ROOT, checkpoint["id"])
            for name in PACKAGE_FILES:
                with self.subTest(checkpoint=checkpoint["id"], file=name):
                    self.assertTrue(os.path.isfile(
                        os.path.join(directory, name)))

    def test_the_index_links_every_checkpoint(self):
        index = _read(os.path.join(CHECKPOINT_ROOT, "README.md"))
        for checkpoint in CHECKPOINTS:
            self.assertIn(checkpoint["id"], index)

    def test_no_file_is_empty(self):
        for checkpoint in CHECKPOINTS:
            for name in PACKAGE_FILES:
                path = os.path.join(CHECKPOINT_ROOT, checkpoint["id"], name)
                with self.subTest(file=path):
                    self.assertTrue(_read(path).strip())


class TestNothingIsApproved(unittest.TestCase):
    """The property the whole package shape exists to protect."""

    def test_every_proposed_decision_is_pending_review(self):
        for checkpoint in CHECKPOINTS:
            path = os.path.join(CHECKPOINT_ROOT, checkpoint["id"],
                                "proposed-decisions.csv")
            rows = _rows(_read(path))
            self.assertTrue(rows, checkpoint["id"])
            for row in rows:
                with self.subTest(decision=row["decision_id"]):
                    self.assertEqual(row["target_status"], "PENDING_REVIEW")

    def test_every_decision_names_a_human_owner(self):
        for checkpoint in CHECKPOINTS:
            path = os.path.join(CHECKPOINT_ROOT, checkpoint["id"],
                                "proposed-decisions.csv")
            for row in _rows(_read(path)):
                with self.subTest(decision=row["decision_id"]):
                    self.assertTrue(row["decision_owner"].strip())

    def test_every_decision_id_is_unique_within_its_package(self):
        for checkpoint in CHECKPOINTS:
            path = os.path.join(CHECKPOINT_ROOT, checkpoint["id"],
                                "proposed-decisions.csv")
            ids = [row["decision_id"] for row in _rows(_read(path))]
            self.assertEqual(len(ids), len(set(ids)), checkpoint["id"])

    def test_every_approval_form_on_disk_is_the_blank_template(self):
        """A filled form is a decision. A generated one must be empty.

        The comparison is against the template rather than a scan for words
        like "approved": the template itself offers APPROVED as one of the
        verdicts to choose, so a substring rule here would match its own
        instructions and prove nothing.
        """
        for checkpoint in CHECKPOINTS:
            path = os.path.join(CHECKPOINT_ROOT, checkpoint["id"],
                                "approval-form.md")
            with self.subTest(checkpoint=checkpoint["id"]):
                self.assertEqual(_read(path), _approval_form(checkpoint))

    def test_the_blank_form_has_no_value_in_any_decision_field(self):
        for checkpoint in CHECKPOINTS:
            form = _approval_form(checkpoint)
            for field in ("Reviewer name", "Reviewer role", "Date (UTC",
                          "Qualification relied on"):
                with self.subTest(checkpoint=checkpoint["id"], field=field):
                    line = [row for row in form.splitlines()
                            if row.startswith("| %s" % field)]
                    self.assertEqual(len(line), 1, field)
                    self.assertEqual(line[0].rstrip().rstrip("|").split("|")[-1]
                                     .strip(), "")

    def test_every_form_says_what_it_does_not_cover(self):
        for checkpoint in CHECKPOINTS:
            self.assertTrue(checkpoint["not_covered"], checkpoint["id"])
            form = _approval_form(checkpoint)
            for item in checkpoint["not_covered"]:
                self.assertIn(item, form)


class TestH01CarriesTheSourceResearch(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.directory = os.path.join(CHECKPOINT_ROOT, "H01-source-policy")
        cls.proposals = _rows(_read(os.path.join(cls.directory,
                                                 "proposed-decisions.csv")))

    def _registry_keys(self):
        import json
        with io.open(os.path.join(REPO_ROOT, "config",
                                  "scientific-sources.json"),
                     encoding="utf-8") as handle:
            return sorted(entry["source_key"]
                          for entry in json.load(handle)["sources"])

    def test_every_registered_source_gets_exactly_one_proposal(self):
        keys = [row["source_key"] for row in self.proposals]
        self.assertEqual(sorted(keys), self._registry_keys())
        self.assertEqual(len(keys), EXPECTED_REGISTRY_SOURCES)
        self.assertEqual(len(keys), len(set(keys)))

    def test_no_source_moves_out_of_pending_review(self):
        for row in self.proposals:
            with self.subTest(source=row["source_key"]):
                self.assertEqual(row["current_status"], "PENDING_REVIEW")
                self.assertEqual(row["target_status"], "PENDING_REVIEW")

    def test_non_target_sources_are_deferred_not_rejected(self):
        from pgx.closure.research_findings import TARGET_SOURCE_KEYS

        for row in self.proposals:
            if row["source_key"] in TARGET_SOURCE_KEYS:
                continue
            with self.subTest(source=row["source_key"]):
                self.assertEqual(row["proposed_disposition"],
                                 "DEFER_OUTSIDE_FIRST_RELEASE_SCOPE")

    def test_a_source_with_a_conflict_is_escalated(self):
        from pgx.closure.research_findings import SOURCE_FINDINGS

        conflicted = {item["source_key"] for item in SOURCE_FINDINGS
                      if item.get("conflict")}
        self.assertTrue(conflicted)
        for row in self.proposals:
            if row["source_key"] in conflicted:
                with self.subTest(source=row["source_key"]):
                    self.assertEqual(row["proposed_disposition"],
                                     "ESCALATE_BEFORE_ANY_ACQUISITION")

    def test_an_unknown_licence_stays_unknown(self):
        from pgx.closure.research_findings import SOURCE_FINDINGS

        for item in SOURCE_FINDINGS:
            if item["licence"] != "UNKNOWN":
                continue
            row = [r for r in self.proposals
                   if r["source_key"] == item["source_key"]][0]
            with self.subTest(source=item["source_key"]):
                self.assertEqual(row["licence_as_read"], "UNKNOWN")
                self.assertEqual(
                    row["reuse_dimensions_the_licence_would_support"],
                    "none established")

    def test_the_evidence_table_covers_every_registered_source(self):
        text = _read(os.path.join(self.directory, "evidence-table.csv"))
        first = text.split("\n\n", 1)[0]
        keys = [row["source_key"] for row in _rows(first)]
        self.assertEqual(sorted(keys), self._registry_keys())

    def test_the_coverage_block_names_every_first_release_axis(self):
        from pgx.closure.research_findings import FIRST_RELEASE_AXES

        text = _read(os.path.join(self.directory, "evidence-table.csv"))
        second = text.split("\n\n", 1)[1]
        axes = {row["first_release_axis"] for row in _rows(second)}
        self.assertEqual(axes, set(FIRST_RELEASE_AXES))


class TestH02CarriesTheScopeContradictions(unittest.TestCase):

    def test_every_contradiction_becomes_a_decision(self):
        from pgx.closure.research_findings import SCOPE_CONTRADICTIONS

        path = os.path.join(CHECKPOINT_ROOT, "H02-curation-protocol",
                            "proposed-decisions.csv")
        subjects = {row["subject"] for row in _rows(_read(path))}
        for item in SCOPE_CONTRADICTIONS:
            with self.subTest(contradiction=item["id"]):
                self.assertIn(item["subject"], subjects)

    def test_every_contradiction_is_explained_to_the_reviewer(self):
        from pgx.closure.research_findings import SCOPE_CONTRADICTIONS

        text = _read(os.path.join(CHECKPOINT_ROOT, "H02-curation-protocol",
                                  "unresolved-questions.md"))
        for item in SCOPE_CONTRADICTIONS:
            with self.subTest(contradiction=item["id"]):
                self.assertIn(item["id"], text)
                self.assertIn(item["decision_needed"], text)

    def test_the_protocol_state_is_read_not_asserted(self):
        import json

        with io.open(os.path.join(REPO_ROOT, "config", "curation",
                                  "protocol-v1.json"),
                     encoding="utf-8") as handle:
            protocol = json.load(handle)
        rows = {row["fact"]: row["value"] for row in _rows(_read(
            os.path.join(CHECKPOINT_ROOT, "H02-curation-protocol",
                         "evidence-table.csv")))}
        self.assertEqual(rows["protocol_status"], protocol["status"])
        self.assertEqual(rows["expert_approved"],
                         str(protocol["expert_approved"]))


class TestH03ReadsTheLiveClaimBoundary(unittest.TestCase):

    def test_the_boundary_values_are_the_ones_the_code_enforces(self):
        from pgx.domain.claims import DEFAULT_CLAIM_BOUNDARY as boundary

        rows = {row["fact"]: row["value"] for row in _rows(_read(
            os.path.join(CHECKPOINT_ROOT, "H03-claims-boundary",
                         "evidence-table.csv")))}
        self.assertEqual(rows["claim_boundary_status"], boundary.status)
        self.assertEqual(rows["claim_boundary_version"], boundary.version)
        self.assertEqual(
            len(rows["prohibited_claim_categories"].split("; ")),
            len(boundary.prohibited_categories))

    def test_no_clinical_mode_is_claimed(self):
        rows = {row["fact"]: row["value"] for row in _rows(_read(
            os.path.join(CHECKPOINT_ROOT, "H03-claims-boundary",
                         "evidence-table.csv")))}
        self.assertEqual(sorted(rows["enabled_modes"].split("; ")),
                         ["DEMO", "VALIDATION"])


class TestH00ReportsTheMeasuredBaseline(unittest.TestCase):

    def test_the_baseline_facts_are_the_repositorys_own(self):
        """Compared against Git, where Git is there to compare against.

        The table records what Git said when the package was generated, so
        the check is a comparison with Git and not with a copy of the answer.
        A checkout without Git metadata - an exported tree, a build context,
        a container that copied the files but not the history - can say
        nothing about whether the table is right, and a test that failed
        there would be reporting the absence of Git as a defect in the
        table. It skips instead, and says which fact it could not check.
        """
        baseline = _baseline()
        if baseline["commit"] == "UNKNOWN":
            self.skipTest("no Git metadata in this tree, so the recorded "
                          "baseline cannot be compared with its source")
        rows = {row["fact"]: row["value"] for row in _rows(_read(
            os.path.join(CHECKPOINT_ROOT, "H00-repository-identity",
                         "evidence-table.csv")))}
        for key in ("commit", "tree", "tag", "branch"):
            with self.subTest(fact=key):
                self.assertEqual(rows[key], str(baseline[key]))

    def test_publication_is_an_open_decision(self):
        rows = {row["decision_id"]: row for row in _rows(_read(
            os.path.join(CHECKPOINT_ROOT, "H00-repository-identity",
                         "proposed-decisions.csv")))}
        self.assertIn("H00-D03", rows)
        self.assertEqual(rows["H00-D03"]["target_status"], "PENDING_REVIEW")


class TestTheProducer(unittest.TestCase):

    def test_the_committed_files_are_what_the_producer_writes(self):
        baseline = _baseline()
        if baseline["commit"] == "UNKNOWN":
            self.skipTest("no Git metadata in this tree, so the H00 package "
                          "cannot be regenerated for comparison")
        for relative, text in build_all(REPO_ROOT, baseline).items():
            path = os.path.join(REPO_ROOT, *relative.split("/"))
            with self.subTest(file=relative):
                self.assertEqual(_read(path), text)

    def test_rebuilding_produces_identical_text(self):
        baseline = _baseline()
        self.assertEqual(build_all(REPO_ROOT, baseline),
                         build_all(REPO_ROOT, baseline))

    def test_a_filled_in_approval_form_is_never_overwritten(self):
        """Regenerating over somebody's decision would destroy the record."""
        from scripts.build_closure_wave01_checkpoints import main

        root = tempfile.mkdtemp(prefix="pgx-checkpoint-test-")
        try:
            for relative in ("config/scientific-sources.json",
                             "config/curation/protocol-v1.json",
                             "data/closure/"
                             "wp-c00-legacy-candidate-dispositions.json"):
                source = os.path.join(REPO_ROOT, *relative.split("/"))
                target = os.path.join(root, *relative.split("/"))
                os.makedirs(os.path.dirname(target), exist_ok=True)
                shutil.copyfile(source, target)
            form = os.path.join(root, "docs", "closure", "checkpoints",
                                "H01-source-policy", "approval-form.md")
            os.makedirs(os.path.dirname(form), exist_ok=True)
            with io.open(form, "w", encoding="utf-8", newline="\n") as handle:
                handle.write("a reviewer wrote this\n")

            argv = ["build_closure_wave01_checkpoints.py", "--repo-root", root]
            import sys as _sys
            saved, _sys.argv = _sys.argv, argv
            try:
                self.assertEqual(main(), 0)
            finally:
                _sys.argv = saved
            self.assertEqual(_read(form), "a reviewer wrote this\n")
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
