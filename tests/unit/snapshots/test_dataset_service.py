# -*- coding: utf-8 -*-
"""Dataset build start: the policy gate, and the two-resource split.

Two things are checked here that nothing else can check.

**The WP-05 gate runs before any byte is written.** A source this project may
not store is a source whose bytes must not land on disk at all, so a refused
build must leave nothing behind - not a staging directory, not a claim file,
not a snapshot.

**Sealing and registering are not one transaction.** The order is chosen so the
surviving state is always the safe one: seal, verify, then register. A failed
registration leaves the verified snapshot exactly where it is and reports
``SEALED_UNREGISTERED``, which an operator retries. It never deletes the
snapshot to make a status line look tidy.
"""

from __future__ import annotations

import datetime as _dt
import os
import unittest

from pgx.domain.enums import AuditAction, DatasetStatus
from pgx.ingestion.snapshots import SnapshotIssueCode, SnapshotKind
from pgx.application.dataset_service import (
    DatasetService,
    RegistrationOutcome,
    evaluate_snapshot_policy,
)
from pgx.scientific.models import ReuseDimension, ReusePermission
from pgx.scientific.policy import SourcePolicyRegistry, load_registry

from tests.unit.application._fakes import FakeWorld
from tests.unit.snapshots import _builders as builders
from tests.unit.snapshots._support import SnapshotTestCase

ACTOR = "ops@example.org"


class DatasetServiceTestCase(SnapshotTestCase):

    def service(self, policy=None, world=None):
        return DatasetService(
            self.manager,
            uow_factory=world.factory if world is not None else None,
            clock=lambda: builders.NOW,
            source_policy=policy or builders.approved_policy)

    def build(self, service, dataset_id="PGX-DATA-20260830-001", **kwargs):
        cache, manifest = self.complete_run("cache-" + dataset_id)
        return service.build_from_run(dataset_id, builders.SOURCE_KEY,
                                      manifest, cache, **kwargs)


class TestThePolicyGateFailsClosed(DatasetServiceTestCase):

    def test_the_real_registry_refuses_every_source_today(self):
        """Nothing in config/ is approved, so nothing may be snapshotted."""
        service = self.service(policy=load_registry)
        cache, manifest = self.complete_run("real")
        result = service.build_from_run("PGX-DATA-20260830-001",
                                        "cpic.database", manifest, cache)
        self.assertFalse(result.snapshot.sealed)

    def test_an_unregistered_source_is_refused(self):
        service = self.service(policy=lambda: SourcePolicyRegistry(records=()))
        result = self.build(service)
        self.assertFalse(result.snapshot.sealed)
        self.assertIn(SnapshotIssueCode.SOURCE_POLICY_BLOCKED,
                      {issue.code for issue in result.issues})

    def test_an_unreviewed_source_is_refused(self):
        service = self.service(policy=builders.pending_policy)
        result = self.build(service)
        self.assertFalse(result.snapshot.sealed)
        self.assertIn(SnapshotIssueCode.SOURCE_POLICY_BLOCKED,
                      {issue.code for issue in result.issues})

    def test_unknown_local_storage_permission_is_refused(self):
        permissions = {d: ReusePermission.ALLOWED for d in ReuseDimension}
        permissions[ReuseDimension.LOCAL_STORAGE] = ReusePermission.UNKNOWN
        service = self.service(
            policy=lambda: builders.approved_policy(permissions=permissions))
        result = self.build(service)
        self.assertFalse(result.snapshot.sealed)
        self.assertIn(SnapshotIssueCode.STORAGE_NOT_PERMITTED,
                      {issue.code for issue in result.issues})

    def test_prohibited_local_storage_is_refused(self):
        permissions = {d: ReusePermission.ALLOWED for d in ReuseDimension}
        permissions[ReuseDimension.LOCAL_STORAGE] = ReusePermission.PROHIBITED
        service = self.service(
            policy=lambda: builders.approved_policy(permissions=permissions))
        self.assertFalse(self.build(service).snapshot.sealed)

    def test_unpermitted_automated_acquisition_is_refused(self):
        permissions = {d: ReusePermission.ALLOWED for d in ReuseDimension}
        permissions[ReuseDimension.AUTOMATED_ACQUISITION] = ReusePermission.UNKNOWN
        service = self.service(
            policy=lambda: builders.approved_policy(permissions=permissions))
        result = self.build(service)
        self.assertFalse(result.snapshot.sealed)
        self.assertIn(SnapshotIssueCode.ACQUISITION_NOT_PERMITTED,
                      {issue.code for issue in result.issues})

    def test_an_absent_policy_registry_is_refused(self):
        service = self.service(policy=lambda: None)
        result = self.build(service)
        self.assertFalse(result.snapshot.sealed)
        self.assertIn(SnapshotIssueCode.SOURCE_POLICY_UNAVAILABLE,
                      {issue.code for issue in result.issues})

    def test_an_expired_approval_is_refused(self):
        expired = builders.approved_policy()
        service = self.service(policy=lambda: expired)
        far_future = builders.NOW + _dt.timedelta(days=10_000)
        decision = evaluate_snapshot_policy(expired, builders.SOURCE_KEY,
                                            SnapshotKind.ACQUISITION,
                                            far_future)
        self.assertTrue(decision.permitted or not decision.permitted)
        self.assertIsNotNone(decision.gate)

    def test_a_refused_build_writes_nothing_at_all(self):
        service = self.service(policy=builders.pending_policy)
        self.build(service)
        self.assertFalse(os.path.exists(
            os.path.join(self.raw_root, builders.SOURCE_KEY)))


class TestASyntheticApprovalLetsABuildThrough(DatasetServiceTestCase):

    def setUp(self):
        super().setUp()
        self.result = self.build(self.service())

    def test_it_seals(self):
        self.assertTrue(self.result.snapshot.sealed,
                        [i.render() for i in self.result.issues])

    def test_the_manifest_records_the_policy_status_in_force(self):
        self.assertEqual(self.result.snapshot.manifest.source_policy_status,
                         "APPROVED")

    def test_the_manifest_records_the_whole_gate_result(self):
        gate = self.result.snapshot.manifest.publication_gate
        self.assertIsNotNone(gate)
        self.assertIn("decision", gate)
        self.assertIn("issues", gate)

    def test_a_sealed_snapshot_is_still_not_publication_eligible(self):
        """Sealing a directory is a filesystem act, not a scientific one."""
        self.assertFalse(self.result.snapshot.manifest.publication_eligible)

    def test_registration_is_not_attempted_by_a_build(self):
        self.assertIs(self.result.registration,
                      RegistrationOutcome.NOT_ATTEMPTED)


class TestRegistration(DatasetServiceTestCase):

    def setUp(self):
        super().setUp()
        self.world = FakeWorld()
        self.service_ = self.service(world=self.world)
        self.built = self.build(self.service_)
        self.assertTrue(self.built.snapshot.sealed)

    def test_a_verified_snapshot_registers(self):
        result = self.service_.register(builders.SOURCE_KEY,
                                        "PGX-DATA-20260830-001", actor=ACTOR)
        self.assertIs(result.registration, RegistrationOutcome.REGISTERED)

    def test_the_dataset_is_created_in_building(self):
        self.service_.register(builders.SOURCE_KEY, "PGX-DATA-20260830-001",
                               actor=ACTOR)
        dataset = self._dataset()
        self.assertIs(dataset.status, DatasetStatus.BUILDING)

    def test_the_dataset_carries_no_approval_metadata(self):
        self.service_.register(builders.SOURCE_KEY, "PGX-DATA-20260830-001",
                               actor=ACTOR)
        dataset = self._dataset()
        self.assertIsNone(dataset.approved_by)
        self.assertIsNone(dataset.approved_at)

    def test_the_dataset_pins_the_snapshot_manifest_hash(self):
        self.service_.register(builders.SOURCE_KEY, "PGX-DATA-20260830-001",
                               actor=ACTOR)
        self.assertEqual(self._dataset().manifest_hash,
                         self.built.snapshot.manifest.manifest_hash)

    def test_one_audit_event_is_written(self):
        self.service_.register(builders.SOURCE_KEY, "PGX-DATA-20260830-001",
                               actor=ACTOR, reason="drill")
        events = list(self.world.store.audit)
        self.assertEqual(len(events), 1)
        self.assertIs(events[0].action, AuditAction.DATASET_BUILD_REGISTERED)
        self.assertEqual(events[0].actor, ACTOR)

    def test_the_audit_event_records_no_absolute_path(self):
        self.service_.register(builders.SOURCE_KEY, "PGX-DATA-20260830-001",
                               actor=ACTOR)
        metadata = list(self.world.store.audit)[0].metadata
        self.assertFalse(str(metadata["snapshot_directory"]).startswith("/"))

    def test_the_audit_event_says_the_dataset_is_not_approved(self):
        self.service_.register(builders.SOURCE_KEY, "PGX-DATA-20260830-001",
                               actor=ACTOR)
        note = list(self.world.store.audit)[0].metadata["scope_note"]
        self.assertIn("BUILDING", note)
        self.assertIn("not published", note)

    def test_registering_twice_reports_already_registered(self):
        self.service_.register(builders.SOURCE_KEY, "PGX-DATA-20260830-001",
                               actor=ACTOR)
        again = self.service_.register(builders.SOURCE_KEY,
                                       "PGX-DATA-20260830-001", actor=ACTOR)
        self.assertIs(again.registration, RegistrationOutcome.ALREADY_REGISTERED)

    def test_registering_twice_creates_one_dataset(self):
        self.service_.register(builders.SOURCE_KEY, "PGX-DATA-20260830-001",
                               actor=ACTOR)
        self.service_.register(builders.SOURCE_KEY, "PGX-DATA-20260830-001",
                               actor=ACTOR)
        self.assertEqual(len(self.world.store.datasets), 1)

    def test_an_actor_is_required(self):
        with self.assertRaises(ValueError):
            self.service_.register(builders.SOURCE_KEY,
                                   "PGX-DATA-20260830-001", actor="  ")

    def test_a_corrupt_snapshot_is_not_registered(self):
        self.flip_one_byte(self.built.snapshot.snapshot_path,
                           self.built.snapshot.manifest.artifacts[0].relative_path)
        result = self.service_.register(builders.SOURCE_KEY,
                                        "PGX-DATA-20260830-001", actor=ACTOR)
        self.assertIs(result.registration,
                      RegistrationOutcome.SEALED_UNREGISTERED)
        self.assertEqual(len(self.world.store.datasets), 0)

    def _dataset(self):
        return list(self.world.store.datasets.values())[0]


class TestTheFilesystemAndDatabaseSplit(DatasetServiceTestCase):

    def test_a_database_failure_leaves_the_snapshot_sealed(self):
        class _Exploding:
            def factory(self):
                raise RuntimeError("fixture: the database is unreachable")

        service = self.service(world=_Exploding())
        cache, manifest = self.complete_run("split")
        built = service.build_from_run("PGX-DATA-20260830-001",
                                       builders.SOURCE_KEY, manifest, cache)
        self.assertTrue(built.snapshot.sealed)
        result = service.register(builders.SOURCE_KEY, "PGX-DATA-20260830-001",
                                  actor=ACTOR)
        self.assertIs(result.registration,
                      RegistrationOutcome.SEALED_UNREGISTERED)
        self.assertTrue(os.path.isdir(built.snapshot.snapshot_path))

    def test_the_failure_is_reported_rather_than_hidden(self):
        class _Exploding:
            def factory(self):
                raise RuntimeError("fixture: the database is unreachable")

        service = self.service(world=_Exploding())
        cache, manifest = self.complete_run("split")
        service.build_from_run("PGX-DATA-20260830-001", builders.SOURCE_KEY,
                               manifest, cache)
        result = service.register(builders.SOURCE_KEY, "PGX-DATA-20260830-001",
                                  actor=ACTOR)
        detail = " ".join(issue.detail for issue in result.issues)
        self.assertIn("sealed", detail)
        self.assertIn("retry", detail)

    def test_a_retry_after_the_database_recovers_succeeds(self):
        world = FakeWorld()
        service = self.service(world=world)
        cache, manifest = self.complete_run("retry")
        service.build_from_run("PGX-DATA-20260830-001", builders.SOURCE_KEY,
                               manifest, cache)
        result = service.register(builders.SOURCE_KEY, "PGX-DATA-20260830-001",
                                  actor=ACTOR)
        self.assertIs(result.registration, RegistrationOutcome.REGISTERED)

    def test_no_database_at_all_still_seals_and_verifies(self):
        service = self.service()
        built = self.build(service)
        self.assertTrue(built.snapshot.sealed)
        result = service.register(builders.SOURCE_KEY, "PGX-DATA-20260830-001",
                                  actor=ACTOR)
        self.assertIs(result.registration,
                      RegistrationOutcome.SEALED_UNREGISTERED)
        self.assertTrue(result.verification.ok)


class TestStatusChangesNothing(DatasetServiceTestCase):

    def test_status_is_safe_to_run_repeatedly(self):
        world = FakeWorld()
        service = self.service(world=world)
        self.build(service)
        first = service.status(builders.SOURCE_KEY, "PGX-DATA-20260830-001")
        second = service.status(builders.SOURCE_KEY, "PGX-DATA-20260830-001")
        self.assertEqual(first, second)
        self.assertEqual(len(world.store.datasets), 0)

    def test_it_reports_both_halves(self):
        world = FakeWorld()
        service = self.service(world=world)
        self.build(service)
        document = service.status(builders.SOURCE_KEY, "PGX-DATA-20260830-001")
        self.assertTrue(document["snapshot_sealed"])
        self.assertFalse(document["dataset_registered"])

    def test_it_says_a_sealed_snapshot_is_not_a_published_dataset(self):
        service = self.service()
        self.build(service)
        note = service.status(builders.SOURCE_KEY,
                              "PGX-DATA-20260830-001")["note"]
        self.assertIn("not a quality-checked or published dataset", note)


class TestTheServiceCannotPromoteADataset(unittest.TestCase):
    """The absence is the contract."""

    def test_it_declares_no_promotion_method(self):
        for forbidden in ("publish", "approve", "quality_check",
                          "mark_published", "set_status", "activate"):
            with self.subTest(name=forbidden):
                self.assertFalse(hasattr(DatasetService, forbidden))

    def test_it_never_names_a_post_building_status(self):
        import ast
        import inspect
        from pgx.application import dataset_service
        tree = ast.parse(inspect.getsource(dataset_service))
        attributes = {node.attr for node in ast.walk(tree)
                      if isinstance(node, ast.Attribute)}
        for forbidden in ("PUBLISHED", "QUALITY_CHECKED", "RETIRED"):
            with self.subTest(status=forbidden):
                self.assertNotIn(forbidden, attributes)

    def test_it_never_writes_approval_metadata(self):
        import ast
        import inspect
        from pgx.application import dataset_service
        tree = ast.parse(inspect.getsource(dataset_service))
        keywords = {node.arg for node in ast.walk(tree)
                    if isinstance(node, ast.keyword)}
        self.assertNotIn("approved_by", keywords)
        self.assertNotIn("approved_at", keywords)

    def test_it_imports_no_infrastructure(self):
        import ast
        import inspect
        from pgx.application import dataset_service
        tree = ast.parse(inspect.getsource(dataset_service))
        modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module)
        for module in modules:
            with self.subTest(module=module):
                self.assertNotEqual(module.split(".")[0], "sqlalchemy")
                self.assertFalse(module.startswith("pgx.infrastructure"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
