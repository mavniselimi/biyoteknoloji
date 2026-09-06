# -*- coding: utf-8 -*-
"""WP-C06: the named human decision about a dataset build.

WP-07 could already perform the transition an approval causes. It could not
record the decision: its request has no verdict, so a data owner who read the
report and said no had nowhere to put that, and nothing bound the decision to
the source policy in force. These tests cover the record that was missing.

Every reviewer here is the shouted synthetic identity the repository uses when
a mechanism needs a decision to exercise and no real person has made one. It
must never appear in a real artifact, and a test at the end checks that it
does not.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import io
import json
import os
import shutil
import tempfile
import unittest

from pgx.normalization.errors import QualityGateError
from pgx.normalization.quality_decision import (DECISION_LEDGER_VERSION,
                                                DatasetQualityDecision,
                                                DecisionOutcome,
                                                QualityDecision,
                                                append_decision, load_ledger,
                                                measure_binding,
                                                render_review_record,
                                                verify_decision)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

#: Never a real person. The repository's established convention for a
#: mechanism that needs a decision in order to be tested at all.
TEST_REVIEWER = "TEST_DATA_OWNER"
TEST_ROLE = "TEST_DATA_OWNER_ROLE"
DECIDED_AT = _dt.datetime(2026, 9, 6, 12, 0, tzinfo=_dt.timezone.utc)

DATASET = "PGX-DATA-TEST-0001"
BUILD_KEY = "PGX-DATA-TEST-0001/aaaabbbbccccdddd"


def _digest(text):
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


class _Tree(unittest.TestCase):
    """A synthetic build and source registry on disk, and nothing real."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="pgx-wpc06-")
        self.build = os.path.join(self.root, "build")
        os.makedirs(self.build)
        self.report_hash = _digest("dq-report-v1")
        self._write("dq-report.json", {"content_hash": self.report_hash,
                                       "dq_report_version": "test/1"})
        self._write("manifest.json", {"dataset_public_id": DATASET,
                                      "canonical_build_key": BUILD_KEY})
        self.registry = os.path.join(self.root, "sources.json")
        with io.open(self.registry, "w", encoding="utf-8",
                     newline="\n") as handle:
            handle.write('{"sources": []}\n')
        self.policy_hash = _digest('{"sources": []}\n')
        self.ledger = os.path.join(self.root, "decisions.ndjson")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _write(self, name, payload):
        with io.open(os.path.join(self.build, name), "w", encoding="utf-8",
                     newline="\n") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")

    def _decision(self, decision=QualityDecision.APPROVED, **overrides):
        fields = dict(
            dataset_public_id=DATASET, canonical_build_key=BUILD_KEY,
            decision=decision, reviewer_name=TEST_REVIEWER,
            reviewer_role=TEST_ROLE, decided_at=DECIDED_AT,
            rationale="synthetic decision for a mechanism test",
            dq_artifact_hash=self.report_hash,
            source_policy_hash=self.policy_hash)
        fields.update(overrides)
        return DatasetQualityDecision(**fields)


class TestADecisionCannotBeMadeAnonymously(_Tree):

    def test_a_reviewer_name_is_required(self):
        for field in ("reviewer_name", "reviewer_role", "rationale",
                      "dataset_public_id", "canonical_build_key"):
            for empty in ("", "   ", None):
                with self.subTest(field=field, value=repr(empty)):
                    with self.assertRaises(QualityGateError):
                        self._decision(**{field: empty})

    def test_there_is_no_default_reviewer(self):
        import inspect

        signature = inspect.signature(DatasetQualityDecision)
        for name in ("reviewer_name", "reviewer_role", "decided_at",
                     "rationale"):
            with self.subTest(field=name):
                self.assertIs(signature.parameters[name].default,
                              inspect.Parameter.empty)

    def test_a_naive_instant_is_refused(self):
        with self.assertRaises(QualityGateError):
            self._decision(decided_at=_dt.datetime(2026, 9, 6, 12, 0))

    def test_a_non_digest_binding_is_refused(self):
        for field in ("dq_artifact_hash", "source_policy_hash"):
            with self.subTest(field=field):
                with self.assertRaises(QualityGateError):
                    self._decision(**{field: "not-a-digest"})

    def test_the_decision_id_is_derived_not_supplied(self):
        first = self._decision()
        self.assertTrue(first.decision_id.startswith("DQD-"))
        self.assertEqual(first.decision_id, self._decision().decision_id)
        other = self._decision(rationale="a different reason")
        self.assertNotEqual(first.decision_id, other.decision_id)


class TestOnlyTwoVerdictsExist(_Tree):
    """Three verdicts now, and the third is not a softer approval.

    ``ACCEPTED_FOR_CANDIDATE_USE`` was added for the candidate track. The
    assertions below are what stop it from becoming a back door: it must not
    permit the WP-07 transition, and it must be spelled so that nothing
    reading the ledger can mistake it for ``APPROVED``.
    """

    def test_the_vocabulary_is_exactly_these_three(self):
        self.assertEqual([item.value for item in QualityDecision],
                         ["APPROVED", "ACCEPTED_FOR_CANDIDATE_USE",
                          "REJECTED"])

    def test_only_an_approval_permits_the_transition(self):
        self.assertTrue(QualityDecision.APPROVED.permits_transition)
        self.assertFalse(QualityDecision.REJECTED.permits_transition)
        self.assertFalse(
            QualityDecision.ACCEPTED_FOR_CANDIDATE_USE.permits_transition,
            "candidate acceptance would publish a dataset on the governed "
            "path, which it has not earned")

    def test_candidate_acceptance_binds_a_candidate_release_only(self):
        self.assertTrue(QualityDecision.APPROVED.permits_candidate_release)
        self.assertTrue(QualityDecision.ACCEPTED_FOR_CANDIDATE_USE
                        .permits_candidate_release)
        self.assertFalse(QualityDecision.REJECTED.permits_candidate_release)

    def test_candidate_acceptance_is_not_spelled_like_an_approval(self):
        value = QualityDecision.ACCEPTED_FOR_CANDIDATE_USE.value
        self.assertNotIn("APPROV", value)
        self.assertIn("CANDIDATE", value)

    def test_a_rejection_records_and_moves_nothing(self):
        result = append_decision(self._decision(QualityDecision.REJECTED),
                                 self.build, self.registry, self.ledger)
        self.assertIs(result.outcome, DecisionOutcome.RECORDED)
        self.assertFalse(result.decision.decision.permits_transition)
        self.assertIn("not", result.detail.lower())
        self.assertFalse(result.decision.to_json()["permits_transition"])


class TestABindingIsRemeasuredNotTrusted(_Tree):

    def test_a_matching_decision_verifies(self):
        ok, problems = verify_decision(self._decision(), self.build,
                                       self.registry)
        self.assertTrue(ok, problems)
        self.assertEqual(problems, ())

    def test_a_regenerated_report_invalidates_the_decision(self):
        decision = self._decision()
        self._write("dq-report.json",
                    {"content_hash": _digest("dq-report-v2"),
                     "dq_report_version": "test/1"})
        ok, problems = verify_decision(decision, self.build, self.registry)
        self.assertFalse(ok)
        self.assertTrue(any("dq_artifact_hash" in item for item in problems))

    def test_a_changed_source_policy_invalidates_the_decision(self):
        decision = self._decision()
        with io.open(self.registry, "w", encoding="utf-8",
                     newline="\n") as handle:
            handle.write('{"sources": [{"source_key": "x"}]}\n')
        ok, problems = verify_decision(decision, self.build, self.registry)
        self.assertFalse(ok)
        self.assertTrue(any("source_policy_hash" in item
                            for item in problems))

    def test_the_problem_names_both_halves(self):
        decision = self._decision()
        self._write("dq-report.json", {"content_hash": _digest("v2")})
        _, problems = verify_decision(decision, self.build, self.registry)
        joined = " ".join(problems)
        self.assertIn("bound", joined)
        self.assertIn("measured", joined)

    def test_measure_binding_reads_what_the_build_publishes(self):
        measured = measure_binding(self.build, self.registry)
        self.assertEqual(measured["dataset_public_id"], DATASET)
        self.assertEqual(measured["canonical_build_key"], BUILD_KEY)
        self.assertEqual(measured["dq_artifact_hash"], self.report_hash)
        self.assertEqual(measured["source_policy_hash"], self.policy_hash)


class TestTheLedgerIsAppendOnly(_Tree):

    def test_a_recorded_decision_is_readable_back(self):
        result = append_decision(self._decision(), self.build, self.registry,
                                 self.ledger)
        self.assertIs(result.outcome, DecisionOutcome.RECORDED)
        rows = load_ledger(self.ledger)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].decision_id, result.decision.decision_id)
        self.assertEqual(rows[0].reviewer_name, TEST_REVIEWER)

    def test_a_replay_is_refused_and_names_the_standing_decision(self):
        append_decision(self._decision(), self.build, self.registry,
                        self.ledger)
        again = append_decision(self._decision(QualityDecision.REJECTED),
                                self.build, self.registry, self.ledger)
        self.assertIs(again.outcome, DecisionOutcome.REFUSED_REPLAY)
        self.assertIsNotNone(again.existing)
        self.assertEqual(again.existing.decision, QualityDecision.APPROVED)
        self.assertEqual(len(load_ledger(self.ledger)), 1)

    def test_a_stale_decision_is_refused_and_writes_nothing(self):
        decision = self._decision()
        self._write("dq-report.json", {"content_hash": _digest("v2")})
        result = append_decision(decision, self.build, self.registry,
                                 self.ledger)
        self.assertIs(result.outcome, DecisionOutcome.REFUSED_STALE_BINDING)
        self.assertEqual(load_ledger(self.ledger), ())
        self.assertFalse(os.path.exists(self.ledger))

    def test_a_missing_build_is_refused(self):
        shutil.rmtree(self.build)
        result = append_decision(self._decision(), self.build, self.registry,
                                 self.ledger)
        self.assertIs(result.outcome, DecisionOutcome.REFUSED_BUILD_MISSING)
        self.assertEqual(load_ledger(self.ledger), ())

    def test_a_new_report_admits_a_new_decision(self):
        """A changed report is a different question, and may be answered."""
        append_decision(self._decision(), self.build, self.registry,
                        self.ledger)
        second_hash = _digest("dq-report-v2")
        self._write("dq-report.json", {"content_hash": second_hash})
        result = append_decision(self._decision(dq_artifact_hash=second_hash),
                                 self.build, self.registry, self.ledger)
        self.assertIs(result.outcome, DecisionOutcome.RECORDED)
        self.assertEqual(len(load_ledger(self.ledger)), 2)

    def test_the_ledger_is_never_rewritten_in_place(self):
        append_decision(self._decision(), self.build, self.registry,
                        self.ledger)
        with io.open(self.ledger, encoding="utf-8") as handle:
            first = handle.read()
        second_hash = _digest("dq-report-v2")
        self._write("dq-report.json", {"content_hash": second_hash})
        append_decision(self._decision(QualityDecision.REJECTED,
                                       dq_artifact_hash=second_hash),
                        self.build, self.registry, self.ledger)
        with io.open(self.ledger, encoding="utf-8") as handle:
            self.assertTrue(handle.read().startswith(first))


class TestTheReviewRecord(_Tree):

    def test_an_empty_ledger_says_nobody_has_decided(self):
        rendered = render_review_record(())
        self.assertIn("No decision has been recorded", rendered)
        self.assertIn("never a substitute", rendered)

    def test_a_recorded_decision_appears_with_its_reviewer_and_role(self):
        append_decision(self._decision(), self.build, self.registry,
                        self.ledger)
        rendered = render_review_record(load_ledger(self.ledger))
        for fragment in (TEST_REVIEWER, TEST_ROLE, DATASET, "APPROVED"):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, rendered)


class TestNoRealDecisionExistsInThisRepository(unittest.TestCase):
    """What the committed ledger may and may not contain.

    This class asserted an empty ledger when WP-C06 shipped the mechanism, and
    that assertion was correct for exactly as long as nothing had been decided.
    Wave 3 recorded the first decision, so the assertion has been replaced
    rather than deleted: the property that actually matters was never
    "the ledger is empty" but "no row in it claims more than happened".
    """

    LEDGER = os.path.join(REPO_ROOT, "data", "canonical",
                          "dataset-quality-decisions.ndjson")

    def test_no_committed_decision_approves_a_dataset(self):
        """The property, not the proxy.

        This asserted that every row was ``REJECTED``, which was the same
        thing while ``APPROVED`` and ``REJECTED`` were the only verdicts. A
        third verdict exists now, so the assertion is stated as what it always
        meant: no row carries the governed approval, and no row permits the
        WP-07 transition.
        """
        for row in load_ledger(self.LEDGER):
            self.assertIsNot(
                row.decision, QualityDecision.APPROVED,
                "%s carries a committed APPROVED decision. An approval moves "
                "a dataset towards release, and none has been earned."
                % row.dataset_public_id)
            self.assertFalse(row.decision.permits_transition,
                             row.dataset_public_id)

    def test_an_automated_reviewer_says_so_in_its_own_name(self):
        for row in load_ledger(self.LEDGER):
            lowered = row.reviewer_name.lower()
            if "automated" in lowered or "pass" in lowered:
                self.assertIn(
                    "NOT A HUMAN REVIEWER", row.reviewer_name,
                    "%r reads like a process but does not say so where a "
                    "reader of the rendered table would see it"
                    % row.reviewer_name)
                self.assertEqual(row.reviewer_role,
                                 "AUTOMATED_PROJECT_TEAM_PASS")

    def test_every_current_decision_still_describes_its_build(self):
        """Superseded rows are exempt, and only superseded rows.

        A superseded decision is a record of what was believed at the time;
        re-binding it to today's artifacts would destroy exactly the
        information it is kept for. A *current* decision that no longer
        describes what is on disk is a defect, and still fails here.
        """
        ledger = load_ledger(self.LEDGER)
        superseded = {row.supersedes for row in ledger if row.supersedes}
        for row in ledger:
            if row.decision_id in superseded:
                continue
            build = os.path.join(REPO_ROOT, "data", "canonical",
                                 row.dataset_public_id)
            if not os.path.isdir(build):
                continue
            ok, problems = verify_decision(
                row, build,
                os.path.join(REPO_ROOT, "config", "scientific-sources.json"))
            self.assertTrue(ok, "%s: %s" % (row.dataset_public_id,
                                            "; ".join(problems)))

    def test_the_synthetic_reviewer_is_in_no_committed_artifact(self):
        """A shouted test identity that reached a real file is a defect."""
        offenders = []
        for directory in ("data", "docs", "config"):
            base = os.path.join(REPO_ROOT, directory)
            for path, dirs, names in os.walk(base):
                dirs[:] = [item for item in dirs if item != "__pycache__"]
                for name in names:
                    if not name.endswith((".json", ".ndjson", ".csv", ".md")):
                        continue
                    full = os.path.join(path, name)
                    try:
                        with io.open(full, encoding="utf-8",
                                     errors="replace") as handle:
                            body = handle.read()
                    except OSError:  # pragma: no cover
                        continue
                    if TEST_REVIEWER in body:
                        offenders.append(os.path.relpath(full, REPO_ROOT))
        self.assertEqual(offenders, [])

    def test_the_ledger_version_is_pinned(self):
        self.assertEqual(DECISION_LEDGER_VERSION,
                         "pgx-wpc06-dataset-quality-decision/1")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class _FakeTransition:
    """Stands in for the WP-07 service, recording what it was handed."""

    class _Outcome:
        def __init__(self, value):
            self.value = value

    def __init__(self, outcome="QUALITY_CHECKED"):
        self.outcome = self._Outcome(outcome)
        self.detail = "fake transition"
        self.calls = []

    def record_quality_check(self, request):
        self.calls.append(request)
        return self


class TestTheApprovalPathReachesTheTransition(_Tree):
    """The join that did not exist: a decision, then what follows from it."""

    def _run(self, decision, service=None):
        from pgx.application.quality_decision_service import (
            record_dataset_quality_decision)

        return record_dataset_quality_decision(
            decision, self.build, self.registry, self.ledger,
            canonical_service=service,
            quality_check_request=object() if service else None)

    def test_an_approval_calls_the_transition_once(self):
        service = _FakeTransition()
        result = self._run(self._decision(), service)
        self.assertTrue(result.recorded)
        self.assertTrue(result.transitioned)
        self.assertEqual(len(service.calls), 1)

    def test_a_rejection_never_calls_the_transition(self):
        service = _FakeTransition()
        result = self._run(self._decision(QualityDecision.REJECTED), service)
        self.assertTrue(result.recorded)
        self.assertFalse(result.transitioned)
        self.assertEqual(service.calls, [])
        self.assertIn("not release-eligible", result.transition_detail)

    def test_a_refused_decision_never_calls_the_transition(self):
        service = _FakeTransition()
        self._write("dq-report.json", {"content_hash": _digest("v2")})
        result = self._run(self._decision(), service)
        self.assertFalse(result.recorded)
        self.assertEqual(service.calls, [])
        self.assertIsNone(result.transition_outcome)

    def test_a_replay_does_not_transition_a_second_time(self):
        service = _FakeTransition()
        self._run(self._decision(), service)
        again = self._run(self._decision(), service)
        self.assertFalse(again.recorded)
        self.assertEqual(len(service.calls), 1)

    def test_no_service_means_not_attempted_rather_than_refused(self):
        """"Nobody tried" and "it was refused" are different facts."""
        result = self._run(self._decision(), None)
        self.assertTrue(result.recorded)
        self.assertIsNone(result.transition_outcome)
        self.assertFalse(result.to_json()["transition_attempted"])
        self.assertIn("not attempted", result.transition_detail)

    def test_a_refused_transition_is_reported_not_swallowed(self):
        service = _FakeTransition(outcome="REFUSED_WRONG_STATE")
        result = self._run(self._decision(), service)
        self.assertTrue(result.recorded)
        self.assertFalse(result.transitioned)
        self.assertEqual(result.transition_outcome, "REFUSED_WRONG_STATE")
