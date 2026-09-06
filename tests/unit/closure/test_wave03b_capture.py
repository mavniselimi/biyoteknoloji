# -*- coding: utf-8 -*-
"""Wave 3B capture vocabulary, snapshot and candidate dataset (WP-C05, C06)."""

from __future__ import annotations

import ast
import json
import os
import unittest

from pgx.closure.candidate_dq_criteria import (PERMITTED_BLOCKING_CODES,
                                               evaluate_candidate_criteria)
from pgx.closure.capture_payloads import (CAPTURE_LIMITATIONS,
                                          build_capture_files,
                                          build_capture_reads)
from pgx.domain.claims import (P0_CANDIDATE_CLAIM_BOUNDARY, P0_CLAIM_BOUNDARY,
                               ClaimBoundaryAuthority, OperationMode)
from pgx.ingestion.snapshots import SnapshotKind
from pgx.normalization.artifacts import role_of
from pgx.normalization.quality_decision import (LEDGER_PATH, QualityDecision,
                                                load_ledger, verify_decision)
from pgx.scientific.models import AUTOMATED_ACQUISITION_MODES, AcquisitionMode

REPO = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
DATASET_ID = "PGX-DATA-20260906-001"
SNAPSHOT = os.path.join(REPO, "data", "raw", "cpic-guideline-capture",
                        DATASET_ID)
BUILD = os.path.join(REPO, "data", "canonical", DATASET_ID)
MIGRATION = os.path.join(REPO, "migrations", "versions",
                         "0012_wave03b_candidate_capture.py")


def _migration_source():
    with open(MIGRATION, encoding="utf-8") as handle:
        return handle.read()


def _string_constants(tree):
    """Module-level ``NAME = "literal"`` bindings, annotated or not."""
    found = {}
    for node in tree.body:
        if isinstance(node, ast.AnnAssign):
            targets = [node.target]
        elif isinstance(node, ast.Assign):
            targets = node.targets
        else:
            continue
        if not isinstance(node.value, ast.Constant):
            continue
        if not isinstance(node.value.value, str):
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                found[target.id] = node.value.value
    return found


def _call_args(tree, function, attribute):
    """Positional args of every ``op.<attribute>(...)`` inside ``function``."""
    calls = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != function:
            continue
        for inner in ast.walk(node):
            if not isinstance(inner, ast.Call):
                continue
            func = inner.func
            if isinstance(func, ast.Attribute) and func.attr == attribute:
                calls.append(inner.args)
    return calls


class ClaimBoundaryTest(unittest.TestCase):
    """The candidate boundary must never become an approval."""

    def test_the_p0_boundary_is_unchanged_and_still_refuses(self):
        self.assertFalse(P0_CLAIM_BOUNDARY.is_approved)
        self.assertFalse(P0_CLAIM_BOUNDARY.is_provisional)
        for mode in OperationMode:
            self.assertFalse(P0_CLAIM_BOUNDARY.permits_execution(mode),
                             mode.value)

    def test_the_candidate_boundary_is_not_approved(self):
        self.assertFalse(P0_CANDIDATE_CLAIM_BOUNDARY.is_approved)
        self.assertTrue(P0_CANDIDATE_CLAIM_BOUNDARY.is_provisional)
        self.assertEqual(P0_CANDIDATE_CLAIM_BOUNDARY.execution_basis,
                         "PROJECT_TEAM_PROVISIONAL")

    def test_a_provisional_status_cannot_manufacture_an_approval(self):
        """The exact defect the authority check was added to close.

        ``is_approved`` was a substring test over free text. A provisional
        boundary whose status avoided the words "draft" and "awaiting" - as
        this one's does - reported itself as approved.
        """
        status = P0_CANDIDATE_CLAIM_BOUNDARY.status.upper()
        self.assertNotIn("DRAFT", status)
        self.assertNotIn("AWAITING", status)
        self.assertFalse(P0_CANDIDATE_CLAIM_BOUNDARY.is_approved)

    def test_a_provisional_boundary_cannot_unlock_pilot(self):
        self.assertFalse(
            P0_CANDIDATE_CLAIM_BOUNDARY.permits_execution(OperationMode.PILOT))

    def test_the_candidate_boundary_restricts_exactly_as_p0_does(self):
        self.assertEqual(P0_CANDIDATE_CLAIM_BOUNDARY.prohibited_categories,
                         P0_CLAIM_BOUNDARY.prohibited_categories)
        self.assertEqual(P0_CANDIDATE_CLAIM_BOUNDARY.permitted_input_kinds,
                         P0_CLAIM_BOUNDARY.permitted_input_kinds)
        self.assertEqual(P0_CANDIDATE_CLAIM_BOUNDARY.enabled_modes,
                         P0_CLAIM_BOUNDARY.enabled_modes)
        self.assertEqual(P0_CANDIDATE_CLAIM_BOUNDARY.warning_by_language,
                         P0_CLAIM_BOUNDARY.warning_by_language)

    def test_the_default_authority_preserves_the_old_meaning(self):
        from pgx.domain.claims import ClaimBoundary, ClaimPhase
        made = ClaimBoundary(phase=ClaimPhase.P0)
        self.assertIs(made.authority,
                      ClaimBoundaryAuthority.HUMAN_APPROVAL_REQUIRED)


class VocabularyTest(unittest.TestCase):

    def test_agent_retrieval_is_never_automated_acquisition(self):
        self.assertNotIn(AcquisitionMode.AGENT_TARGETED_RETRIEVAL,
                         AUTOMATED_ACQUISITION_MODES)

    def test_the_new_values_fit_their_database_columns(self):
        # source_policies.acquisition_mode is String(32);
        # raw_snapshots.snapshot_kind is String(24).
        self.assertLessEqual(
            len(AcquisitionMode.AGENT_TARGETED_RETRIEVAL.value), 32)
        self.assertLessEqual(len(SnapshotKind.TRANSCRIPTION_CAPTURE.value), 24)

    def test_the_migration_widens_both_constraints(self):
        text = _migration_source()
        self.assertIn("AGENT_TARGETED_RETRIEVAL", text)
        self.assertIn("TRANSCRIPTION_CAPTURE", text)
        self.assertIn('down_revision: Union[str, None] = '
                      '"0011_wp23_auth_audit"', text)
        constants = _string_constants(ast.parse(text))
        # The full constraint names are composed, never written out. The
        # metadata naming convention is ``ck_%(table_name)s_%(constraint_name)
        # s``, so ``create_check_constraint`` prepends ``ck_<table>_`` itself
        # and must be given the suffix alone. An earlier version of this test
        # searched the source for the finished names and passed on the module
        # docstring, which quotes the double-prefixed mistake - so the
        # assertion is now on the composed value, which prose cannot satisfy.
        self.assertEqual(
            "ck_%s_%s" % ("source_policies",
                          constants["_ACQUISITION_CONSTRAINT_SUFFIX"]),
            "ck_" + "source_policies" + "_" + "acquisition_mode_enum")
        self.assertEqual(
            "ck_%s_%s" % ("raw_snapshots",
                          constants["_SNAPSHOT_KIND_CONSTRAINT_SUFFIX"]),
            "ck_" + "raw_snapshots" + "_" + "kind_enum")

    def test_the_migration_gives_alembic_the_suffix_and_not_the_full_name(self):
        """The defect a real PostgreSQL round-trip surfaced.

        ``drop_constraint`` takes the finished name; ``create_check_constraint``
        takes the suffix. Passing the finished name to both created
        ``ck_source_policies_ck_source_policies_acquisition_mode_enum``: the
        rule was still enforced, so nothing failed, but the name a later
        migration would drop no longer existed.
        """
        tree = ast.parse(_migration_source())
        dropped = _call_args(tree, "_replace_check", "drop_constraint")
        self.assertEqual(len(dropped), 1)
        composed = dropped[0][0]
        self.assertIsInstance(composed, ast.BinOp)
        self.assertIsInstance(composed.op, ast.Mod)
        self.assertEqual(composed.left.value, "ck_%s_%s")
        created = _call_args(tree, "_replace_check", "create_check_constraint")
        self.assertEqual(len(created), 1)
        self.assertIsInstance(created[0][0], ast.Name)
        self.assertEqual(created[0][0].id, "suffix")
        # Every call site passes a declared suffix constant, not a literal.
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Name):
                continue
            if node.func.id != "_replace_check":
                continue
            self.assertIsInstance(node.args[1], ast.Name)
            self.assertIn(node.args[1].id,
                          ("_ACQUISITION_CONSTRAINT_SUFFIX",
                           "_SNAPSHOT_KIND_CONSTRAINT_SUFFIX"))

    def test_the_migration_downgrade_refuses_to_destroy_provenance(self):
        self.assertIn("refusing to downgrade", _migration_source())


class CapturePayloadTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.files = build_capture_files()
        cls.reads = build_capture_reads()

    def test_every_capture_file_is_classified_as_evidence(self):
        for name in self.files:
            entry = role_of(name)
            self.assertTrue(entry.counts_as_evidence, name)
            self.assertEqual(entry.artifact_set, "cpic-guideline-capture")

    def test_the_capture_claims_no_external_accession_for_entities(self):
        """A CPIC recommendation table publishes none, so none is borrowed."""
        for name in ("capture_genes.json", "capture_chemicals.json"):
            payload = json.loads(self.files[name])
            for key, record in payload.items():
                self.assertNotIn("id", record, "%s/%s" % (name, key))

    def test_every_transcribed_row_carries_a_capture_local_identity(self):
        rows = json.loads(self.files["capture_recommendation_rows.json"])
        ids = [row["id"] for row in rows]
        self.assertEqual(len(set(ids)), len(ids))
        for value in ids:
            self.assertTrue(value.startswith("capture:row:"), value)

    def test_unrepresentable_rows_are_carried_into_the_capture(self):
        rows = json.loads(self.files["capture_recommendation_rows.json"])
        unrepresentable = [r for r in rows if r["project_phenotype"] is None]
        self.assertGreaterEqual(len(unrepresentable), 7)
        for row in unrepresentable:
            self.assertIn("unrepresentable_reason", row)

    def test_every_read_records_that_no_response_body_was_preserved(self):
        self.assertEqual(len(self.reads), 4)
        for read in self.reads:
            self.assertFalse(read["response_body_preserved"])
            self.assertEqual(read["acquisition_mode"],
                             "AGENT_TARGETED_RETRIEVAL")

    def test_the_payload_is_deterministic(self):
        self.assertEqual(build_capture_files(), self.files)

    def test_the_limitations_deny_what_a_reader_might_assume(self):
        joined = " ".join(CAPTURE_LIMITATIONS)
        self.assertIn("not backed by a WP-04 acquisition run", joined)
        self.assertIn("no byte-level hash", joined)


class SealedSnapshotTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        path = os.path.join(SNAPSHOT, "manifest.json")
        if not os.path.exists(path):
            raise unittest.SkipTest("no capture snapshot has been sealed")
        with open(path, encoding="utf-8") as handle:
            cls.manifest = json.load(handle)

    def test_it_is_a_sealed_transcription_capture(self):
        self.assertEqual(self.manifest["snapshot_kind"],
                         "TRANSCRIPTION_CAPTURE")
        self.assertEqual(self.manifest["snapshot_state"], "SEALED")

    def test_it_claims_no_acquisition_run(self):
        for field in ("acquisition_run_id", "acquisition_status",
                      "acquisition_content_hash",
                      "acquisition_manifest_hash"):
            self.assertIsNone(self.manifest[field], field)

    def test_it_does_not_assert_completeness(self):
        self.assertFalse(self.manifest["complete"])
        self.assertTrue(self.manifest["completeness_basis"])

    def test_it_is_not_publication_eligible(self):
        self.assertFalse(self.manifest["publication_eligible"])

    def test_it_states_its_limitations(self):
        self.assertGreaterEqual(len(self.manifest["limitations"]), 5)

    def test_every_artifact_digest_still_matches(self):
        import hashlib
        for item in self.manifest["artifacts"]:
            path = os.path.join(SNAPSHOT, item["relative_path"])
            with open(path, "rb") as handle:
                raw = handle.read()
            self.assertEqual("sha256:" + hashlib.sha256(raw).hexdigest(),
                             item["sha256"], item["relative_path"])


class CandidateDatasetTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not os.path.isdir(BUILD):
            raise unittest.SkipTest("no candidate dataset has been built")
        with open(os.path.join(BUILD, "manifest.json"),
                  encoding="utf-8") as handle:
            cls.manifest = json.load(handle)
        with open(os.path.join(BUILD, "dq-report.json"),
                  encoding="utf-8") as handle:
            cls.report = json.load(handle)
        with open(os.path.join(SNAPSHOT, "responses", "capture_axes.json"),
                  encoding="utf-8") as handle:
            cls.axes = tuple(sorted(json.load(handle)))

    def test_it_is_not_the_legacy_dataset(self):
        self.assertNotEqual(self.manifest["dataset_public_id"],
                            "PGX-DATA-20260830-900")

    def test_the_dq_gate_did_not_pass_and_says_so(self):
        """Acceptance is candidate-scoped; it never claims the gate passed."""
        self.assertFalse(self.report["decision"]["passed"])

    def test_every_blocking_issue_is_a_declared_exception(self):
        for code in self.report["decision"]["blocking_codes"]:
            self.assertIn(code, PERMITTED_BLOCKING_CODES, code)

    def test_every_candidate_criterion_is_met(self):
        results = evaluate_candidate_criteria(self.manifest, self.report,
                                              self.axes)
        failed = [item.criterion_id for item in results if not item.met]
        self.assertEqual(failed, [])
        self.assertGreaterEqual(len(results), 10)

    def test_all_five_first_release_axes_are_present(self):
        self.assertEqual(len(self.axes), 5)


class LedgerTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.ledger = load_ledger(os.path.join(REPO, LEDGER_PATH))
        cls.superseded = {row.supersedes for row in cls.ledger
                          if row.supersedes}

    def _current(self):
        return [row for row in self.ledger
                if row.decision_id not in self.superseded]

    def test_the_legacy_rejection_survives(self):
        rows = [row for row in self._current()
                if row.dataset_public_id == "PGX-DATA-20260830-900"]
        self.assertEqual(len(rows), 1)
        self.assertIs(rows[0].decision, QualityDecision.REJECTED)

    def test_the_candidate_dataset_is_accepted_for_candidate_use_only(self):
        rows = [row for row in self._current()
                if row.dataset_public_id == DATASET_ID]
        self.assertEqual(len(rows), 1)
        self.assertIs(rows[0].decision,
                      QualityDecision.ACCEPTED_FOR_CANDIDATE_USE)
        self.assertFalse(rows[0].decision.permits_transition)

    def test_the_acceptance_names_the_gate_it_accepted_over(self):
        rows = [row for row in self._current()
                if row.dataset_public_id == DATASET_ID]
        rationale = rows[0].rationale
        self.assertIn("DID NOT PASS", rationale)
        for code in PERMITTED_BLOCKING_CODES:
            self.assertIn(code, rationale)

    def test_every_supersession_states_a_reason(self):
        for row in self.ledger:
            if row.supersedes:
                self.assertTrue(row.supersedes_reason)
                self.assertGreater(len(row.supersedes_reason), 60)

    def test_a_supersession_names_a_decision_that_exists(self):
        known = {row.decision_id for row in self.ledger}
        for row in self.ledger:
            if row.supersedes:
                self.assertIn(row.supersedes, known)

    def test_every_current_decision_still_binds(self):
        for row in self._current():
            build = os.path.join(REPO, "data", "canonical",
                                 row.dataset_public_id)
            if not os.path.isdir(build):
                continue
            ok, problems = verify_decision(
                row, build,
                os.path.join(REPO, "config", "scientific-sources.json"))
            self.assertTrue(ok, "%s: %s" % (row.dataset_public_id,
                                            "; ".join(problems)))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
