# -*- coding: utf-8 -*-
"""The audited `BUILDING -> QUALITY_CHECKED` transition (WP-07).

This is the one state change WP-07 performs, and it is exercised here on a
**synthetic** dataset built from a synthetic snapshot, with a shouted synthetic
reviewer. The real dataset's gate is blocked and stays blocked; a companion test
asserts the service refuses it, naming every blocking code.

The unit of work is a fake that records what it was asked to do. That is enough
to check what matters — that the guard is applied, that the audit event is
appended, that a refusal writes nothing, and that nothing commits twice — and
it needs no database driver.
"""

from __future__ import annotations

import ast
import datetime as _dt
import io
import json
import os
import unittest

from pgx.application.canonical_service import (CanonicalDatasetService,
                                               QualityCheckRequest,
                                               TransitionOutcome)
from pgx.domain.enums import AuditAction, DatasetStatus
from pgx.normalization.build import (CanonicalBuildRequest,
                                     build_canonical_dataset, write_build)
from pgx.normalization.errors import QualityGateError
from pgx.normalization.quality import evaluate_quality

from tests.unit.normalization._snapshot import (REPO_ROOT, RealSnapshotTestCase,
                                                SyntheticSnapshotTestCase)

SERVICE = os.path.join("pgx", "application", "canonical_service.py")

#: The shouted synthetic identity WP-05 established for exactly this situation,
#: where a mechanism needs an approval to exercise and no real human has given
#: one. It must never appear in a real artifact.
TEST_REVIEWER = "TEST_SCIENTIFIC_REVIEWER"
REVIEWED_AT = _dt.datetime(2026, 8, 30, 15, 0, tzinfo=_dt.timezone.utc)


def _source(relative: str) -> str:
    with io.open(os.path.join(REPO_ROOT, relative), encoding="utf-8") as handle:
        return handle.read()


class _FakeDatasets:
    """Records the guarded transition without pretending to be a database."""

    def __init__(self, statuses):
        self.statuses = dict(statuses)
        self.calls = []

    def get_status(self, dataset_public_id):
        return self.statuses.get(dataset_public_id)

    def record_quality_check(self, **kwargs):
        expected = kwargs["expected_current_state"]
        public_id = kwargs["dataset_public_id"]
        # The guard an implementation must apply as a conditional UPDATE.
        if self.statuses.get(public_id) != expected:
            raise AssertionError("the guard was not applied by the caller")
        self.statuses[public_id] = DatasetStatus.QUALITY_CHECKED.value
        self.calls.append(kwargs)


class _FakeAudit:
    def __init__(self):
        self.events = []

    def append(self, event):
        self.events.append(event)


class _FakeUnitOfWork:
    def __init__(self, statuses):
        self.datasets = _FakeDatasets(statuses)
        self.audit = _FakeAudit()
        self.committed = 0
        self.rolled_back = 0
        self.entered = 0

    def __enter__(self):
        self.entered += 1
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.committed == 0:
            self.rolled_back += 1
        return False

    def commit(self):
        self.committed += 1

    def rollback(self):
        self.rolled_back += 1


class _Factory:
    """Hands out one unit of work, so a test can inspect it afterwards."""

    def __init__(self, statuses):
        self.uow = _FakeUnitOfWork(statuses)

    def __call__(self):
        return self.uow


class TestTheRequestCannotBeAnonymous(unittest.TestCase):

    def _request(self, **changes):
        kwargs = dict(dataset_public_id="PGX-DATA-20260830-001",
                      build_path="/tmp/x", reviewed_by=TEST_REVIEWER,
                      reviewed_at=REVIEWED_AT, rationale="a stated reason")
        kwargs.update(changes)
        return QualityCheckRequest(**kwargs)

    def test_a_reviewer_is_required(self):
        for value in ("", "   "):
            with self.subTest(value=value):
                with self.assertRaises(QualityGateError):
                    self._request(reviewed_by=value)

    def test_a_rationale_is_required(self):
        with self.assertRaises(QualityGateError):
            self._request(rationale="  ")

    def test_an_instant_is_required_and_must_be_aware(self):
        with self.assertRaises(Exception):
            self._request(reviewed_at=_dt.datetime(2026, 8, 30, 15, 0))

    def test_the_only_state_it_moves_from_is_building(self):
        for status in (DatasetStatus.QUALITY_CHECKED, DatasetStatus.PUBLISHED,
                       DatasetStatus.RETIRED):
            with self.subTest(status=status):
                with self.assertRaises(QualityGateError):
                    self._request(expected_current_state=status)

    def test_there_is_no_default_reviewer_anywhere_in_the_signature(self):
        fields = QualityCheckRequest.__dataclass_fields__
        import dataclasses
        for name in ("reviewed_by", "reviewed_at", "rationale"):
            with self.subTest(field=name):
                self.assertIs(fields[name].default, dataclasses.MISSING)


class TestASyntheticDatasetCanTransition(SyntheticSnapshotTestCase):
    """A clean synthetic dataset that genuinely passes every gate.

    Everything about it is fabricated on purpose and obviously so: a synthetic
    snapshot, an approved synthetic source policy status, and the shouted
    reviewer name. Nothing here touches the real registry or the real snapshot.
    """

    GENE_FILE = {"CYP2C19": {"objCls": "Gene", "id": "PA124",
                             "symbol": "CYP2C19", "name": "cytochrome P450 2C19"}}
    DRUG_FILE = {"clopidogrel": {"objCls": "Chemical", "id": "PA449053",
                                 "name": "clopidogrel"}}

    def _clean_build(self):
        """A build whose gate passes: sealed, acquisition-shaped, approved."""
        snapshot = self.seal({
            "responses/resolved_genes.json": self.GENE_FILE,
            "responses/resolved_chemicals.json": self.DRUG_FILE,
            "responses/pair_probe_raw.json": {
                "CYP2C19::clopidogrel": {"pair": {
                    "variantAnnotation": [{"id": 1, "value": "a"}]}}},
            "responses/variant_annotation_filtered_raw.json": {
                "CYP2C19": [{"id": 2, "accessionId": "PA1"}]},
        })
        root = self.output_root()
        build = build_canonical_dataset(CanonicalBuildRequest(
            snapshot_root=snapshot, output_root=root,
            allow_new_identities=True))
        # The synthetic snapshot is a LEGACY_IMPORT and QUARANTINED, exactly
        # like the real one; a clean dataset is modelled by overriding those
        # two facts here rather than by weakening the gate.
        clean = _replace_build(build, snapshot_state="SEALED",
                               snapshot_kind="ACQUISITION",
                               snapshot_complete=True)
        report = evaluate_quality(clean, source_policy_status="APPROVED")
        self.assertTrue(report.decision.passed,
                        report.decision.blocking_codes)
        result = write_build(clean, root, extra_documents={
            "dq-report.json": report.to_json()})
        return result, report

    def test_the_gate_passes_for_a_clean_synthetic_build(self):
        _, report = self._clean_build()
        self.assertTrue(report.decision.passed)
        self.assertEqual(report.decision.blocking_codes, ())

    def test_the_transition_succeeds_and_is_audited(self):
        result, report = self._clean_build()
        dataset_id = result.build.dataset_public_id
        factory = _Factory({dataset_id: DatasetStatus.BUILDING.value})
        service = CanonicalDatasetService(factory)

        outcome = service.record_quality_check(QualityCheckRequest(
            dataset_public_id=dataset_id, build_path=result.build_path,
            reviewed_by=TEST_REVIEWER, reviewed_at=REVIEWED_AT,
            rationale="synthetic drill; not a real curation decision"))

        self.assertIs(outcome.outcome, TransitionOutcome.QUALITY_CHECKED)
        self.assertEqual(factory.uow.datasets.statuses[dataset_id],
                         DatasetStatus.QUALITY_CHECKED.value)
        self.assertEqual(factory.uow.committed, 1)

        events = factory.uow.audit.events
        self.assertEqual(len(events), 1)
        self.assertIs(events[0].action, AuditAction.DATASET_QUALITY_CHECKED)
        self.assertEqual(events[0].actor, TEST_REVIEWER)
        self.assertEqual(events[0].object_id, dataset_id)

    def test_the_transition_records_the_report_it_was_checked_against(self):
        result, report = self._clean_build()
        dataset_id = result.build.dataset_public_id
        factory = _Factory({dataset_id: DatasetStatus.BUILDING.value})
        outcome = CanonicalDatasetService(factory).record_quality_check(
            QualityCheckRequest(
                dataset_public_id=dataset_id, build_path=result.build_path,
                reviewed_by=TEST_REVIEWER, reviewed_at=REVIEWED_AT,
                rationale="synthetic drill"))
        call = factory.uow.datasets.calls[0]
        self.assertEqual(call["dq_report_hash"], report.content_hash())
        self.assertTrue(call["dq_report_path"].endswith("dq-report.json"))
        self.assertEqual(call["canonical_build_key"], result.build.build_key)
        self.assertEqual(outcome.dq_report_hash, report.content_hash())

    def test_a_repeated_transition_is_refused(self):
        result, _ = self._clean_build()
        dataset_id = result.build.dataset_public_id
        factory = _Factory({dataset_id: DatasetStatus.BUILDING.value})
        service = CanonicalDatasetService(factory)
        request = QualityCheckRequest(
            dataset_public_id=dataset_id, build_path=result.build_path,
            reviewed_by=TEST_REVIEWER, reviewed_at=REVIEWED_AT,
            rationale="synthetic drill")

        self.assertTrue(service.record_quality_check(request).succeeded)
        second = service.record_quality_check(request)
        self.assertIs(second.outcome, TransitionOutcome.REFUSED_WRONG_STATE)
        self.assertEqual(factory.uow.committed, 1, "the second attempt wrote nothing")
        self.assertEqual(len(factory.uow.audit.events), 1)

    def test_an_unknown_dataset_is_refused_without_writing(self):
        result, _ = self._clean_build()
        factory = _Factory({})
        outcome = CanonicalDatasetService(factory).record_quality_check(
            QualityCheckRequest(
                dataset_public_id=result.build.dataset_public_id,
                build_path=result.build_path, reviewed_by=TEST_REVIEWER,
                reviewed_at=REVIEWED_AT, rationale="synthetic drill"))
        self.assertIs(outcome.outcome, TransitionOutcome.DATASET_NOT_FOUND)
        self.assertEqual(factory.uow.committed, 0)
        self.assertEqual(factory.uow.audit.events, [])

    def test_a_corrupted_build_is_refused(self):
        """The canonical corruption drill, on a disposable build."""
        result, _ = self._clean_build()
        target = os.path.join(result.build_path, "genes.ndjson")
        os.chmod(target, 0o600)
        with io.open(target, "ab") as handle:
            handle.write(b'{"canonical_key": "GENE:INVENTED"}\n')

        factory = _Factory({result.build.dataset_public_id:
                            DatasetStatus.BUILDING.value})
        outcome = CanonicalDatasetService(factory).record_quality_check(
            QualityCheckRequest(
                dataset_public_id=result.build.dataset_public_id,
                build_path=result.build_path, reviewed_by=TEST_REVIEWER,
                reviewed_at=REVIEWED_AT, rationale="synthetic drill"))
        self.assertIs(outcome.outcome,
                      TransitionOutcome.REFUSED_BUILD_UNVERIFIED)
        self.assertEqual(factory.uow.committed, 0)
        self.assertTrue(outcome.problems)

    def test_a_build_describing_another_dataset_is_refused(self):
        result, _ = self._clean_build()
        factory = _Factory({"PGX-DATA-20260830-777":
                            DatasetStatus.BUILDING.value})
        outcome = CanonicalDatasetService(factory).record_quality_check(
            QualityCheckRequest(
                dataset_public_id="PGX-DATA-20260830-777",
                build_path=result.build_path, reviewed_by=TEST_REVIEWER,
                reviewed_at=REVIEWED_AT, rationale="synthetic drill"))
        self.assertIs(outcome.outcome, TransitionOutcome.REFUSED_WRONG_STATE)
        self.assertEqual(factory.uow.committed, 0)


class TestTheRealDatasetIsRefused(RealSnapshotTestCase):

    def test_the_service_refuses_it_and_names_every_blocking_code(self):
        root = self.temp_output()
        build = build_canonical_dataset(CanonicalBuildRequest(
            snapshot_root=self.snapshot_path, output_root=root,
            allow_new_identities=True))
        report = evaluate_quality(build)
        result = write_build(build, root, extra_documents={
            "dq-report.json": report.to_json()})

        factory = _Factory({build.dataset_public_id:
                            DatasetStatus.BUILDING.value})
        outcome = CanonicalDatasetService(factory).record_quality_check(
            QualityCheckRequest(
                dataset_public_id=build.dataset_public_id,
                build_path=result.build_path, reviewed_by=TEST_REVIEWER,
                reviewed_at=REVIEWED_AT,
                rationale="attempting the real dataset, which must be refused"))

        self.assertIs(outcome.outcome, TransitionOutcome.REFUSED_GATE_BLOCKED)
        self.assertEqual(sorted(outcome.blocking_codes),
                         ["SNAPSHOT_NOT_ACQUIRED", "SNAPSHOT_QUARANTINED",
                          "SOURCE_POLICY_MISSING"])
        self.assertEqual(factory.uow.committed, 0)
        self.assertEqual(factory.uow.audit.events, [])
        self.assertEqual(factory.uow.datasets.statuses[build.dataset_public_id],
                         DatasetStatus.BUILDING.value)

    def test_the_checked_in_build_is_still_building(self):
        path = os.path.join(REPO_ROOT, "data", "canonical",
                            "PGX-DATA-20260830-900", "manifest.json")
        if not os.path.isfile(path):
            self.skipTest("the canonical build has not been generated")
        with io.open(path, encoding="utf-8") as handle:
            manifest = json.load(handle)
        self.assertEqual(manifest["dataset_lifecycle_state"], "BUILDING")


class TestTheServiceHasNoOtherTransition(unittest.TestCase):

    def test_it_defines_no_publish_activate_or_retire(self):
        tree = ast.parse(_source(SERVICE), filename=SERVICE)
        names = {node.name for node in ast.walk(tree)
                 if isinstance(node, ast.FunctionDef)}
        for forbidden in ("publish", "activate", "retire", "rollback",
                          "approve", "auto_approve", "force_quality_check"):
            with self.subTest(function=forbidden):
                self.assertNotIn(forbidden, names)

    def test_it_writes_no_published_or_release_state(self):
        tree = ast.parse(_source(SERVICE), filename=SERVICE)
        constants = {node.value for node in ast.walk(tree)
                     if isinstance(node, ast.Constant)
                     and isinstance(node.value, str)}
        for forbidden in ("PUBLISHED", "ACTIVE", "RELEASE_ACTIVATED"):
            with self.subTest(constant=forbidden):
                self.assertNotIn(forbidden, constants)

    def test_it_has_no_override_or_force_argument(self):
        tree = ast.parse(_source(SERVICE), filename=SERVICE)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                names = {argument.arg for argument in node.args.args}
                names |= {argument.arg for argument in node.args.kwonlyargs}
                for forbidden in ("force", "override", "skip_gate",
                                  "ignore_blocking", "allow_blocked"):
                    with self.subTest(function=node.name, argument=forbidden):
                        self.assertNotIn(forbidden, names)

    def test_the_cli_cannot_reach_it(self):
        """`pgx-normalize` computes the gate and stops."""
        cli = _source(os.path.join("pgx", "application", "normalize_cli.py"))
        self.assertNotIn("CanonicalDatasetService", cli)
        self.assertNotIn("record_quality_check", cli)
        self.assertNotIn("canonical_service", cli)


def _replace_build(build, **changes):
    """Copy a build with a few provenance facts overridden.

    Used only to model a clean synthetic dataset. It changes what the snapshot
    *was*, never what the gate *does*: every check still runs, and the build
    still has to pass all of them.
    """
    from dataclasses import fields, replace
    return replace(build, **changes)


if __name__ == "__main__":
    unittest.main()
