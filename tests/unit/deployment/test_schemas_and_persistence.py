# -*- coding: utf-8 -*-
"""Schemas, artifacts and the persistence seam (WP-24).

Two halves.

The **schema** half validates every document this package produces against its
published schema, and - the part that matters - proves the schemas *refuse*
the documents nobody should be able to publish: a performance result with a
zero p95 for a run that never started, a rehearsal serialised as staging, a
vulnerability scan marked VERIFIED with no scanner named, a restore marked
verified with one condition checked.

The **persistence** half covers the row-to-record seam and the PostgreSQL
rate-limit counter. Neither can run against a real server here, so what is
checked is what a server would not tell you anyway: that the counter is one
atomic statement rather than a read followed by a write, and that the adapters
never rewrite an identity.
"""

from __future__ import annotations

import io
import json
import os
import unittest

from pgx.application import deployment_schema as ds
from pgx.deployment.artifacts import (ARTIFACT_PATHS,
                                      DETERMINISTIC_ARTIFACT_PATHS,
                                      canonical_json)
from pgx.deployment.backup_execution import (backup_execution_status,
                                             evaluate_restore)
from pgx.deployment.performance import execute_run, target_registry
from pgx.deployment.rate_limit_store import (ATOMIC_HIT_SQL,
                                             SqlAlchemyRateLimitStore)
from pgx.deployment.reliability import drill_catalogue, run_drills
from pgx.deployment.smoke import smoke_check
from pgx.deployment.vocabulary import (REHEARSAL_LABEL,
                                       DeploymentEnvironmentKind,
                                       ExecutionState)

REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def _artifact(relative):
    with io.open(os.path.join(REPO_ROOT, relative), encoding="utf-8") as fh:
        return json.load(fh)


class TestEveryCommittedArtifactValidates(unittest.TestCase):
    def test_every_declared_artifact_exists(self):
        for relative in ARTIFACT_PATHS:
            with self.subTest(path=relative):
                self.assertTrue(
                    os.path.isfile(os.path.join(REPO_ROOT, relative)),
                    "%s is declared and absent" % relative)

    def test_the_committed_documents_validate(self):
        checks = (
            ("wp24-performance-targets.json",
             ds.validate_performance_targets),
            ("wp24-reliability-drills.json",
             ds.validate_reliability_catalogue),
            ("wp24-runtime-asset-manifest.json",
             ds.validate_runtime_asset_manifest),
            ("wp24-release-validation.json", ds.validate_release_validation),
            ("wp24-real-gate-status.json", ds.validate_wp24_gate_status),
            ("wp24-gate-e-status.json", ds.validate_gate_e_status),
            ("wp24-build-provenance.json", ds.validate_build_provenance),
        )
        for name, validator in checks:
            with self.subTest(document=name):
                errors = validator(_artifact("data/deployment/" + name))
                self.assertEqual(errors, [])

    def test_every_schema_is_committed(self):
        for relative in ds.build_schemas():
            with self.subTest(schema=relative):
                self.assertTrue(
                    os.path.isfile(os.path.join(REPO_ROOT, relative)))

    def test_the_committed_schemas_match_what_the_code_builds(self):
        for relative, schema in ds.build_schemas().items():
            with self.subTest(schema=relative):
                with io.open(os.path.join(REPO_ROOT, relative),
                             encoding="utf-8") as handle:
                    committed = handle.read()
                self.assertEqual(committed, canonical_json(schema))

    def test_the_deterministic_subset_excludes_environment_measurements(self):
        """A document that measures the machine is supposed to differ between
        machines; comparing one byte for byte would fail for everybody, which
        is the fastest way to teach a team to ignore a reproducibility
        check."""
        for relative in ("data/deployment/wp24-real-gate-status.json",
                         "data/deployment/wp24-release-validation.json",
                         "data/deployment/wp24-build-provenance.json"):
            with self.subTest(path=relative):
                self.assertNotIn(relative, DETERMINISTIC_ARTIFACT_PATHS)

    def test_the_deterministic_subset_is_actually_deterministic(self):
        for relative in DETERMINISTIC_ARTIFACT_PATHS:
            with self.subTest(path=relative):
                with io.open(os.path.join(REPO_ROOT, relative),
                             encoding="utf-8") as handle:
                    committed = handle.read()
                if relative.endswith("performance-targets.json"):
                    rebuilt = canonical_json(target_registry())
                elif relative.endswith("reliability-drills.json"):
                    rebuilt = canonical_json(drill_catalogue())
                else:
                    from pgx.deployment.artifacts import (
                        build_restore_conditions_document)
                    rebuilt = canonical_json(
                        build_restore_conditions_document())
                self.assertEqual(committed, rebuilt)


class TestTheSchemasRefuseWhatTheyShould(unittest.TestCase):
    """The negative constraints are where the content is."""

    def test_a_zero_latency_for_an_unrun_measurement_is_refused(self):
        document = dict(execute_run())
        document.update({"attempted": 0, "latency_p50_ms": 0.0,
                         "latency_p95_ms": 0.0, "throughput_rps": 0.0,
                         "error_rate": 0.0})
        errors = ds.validate_performance_result(document)
        self.assertTrue(errors, "a false-zero measurement was accepted")

    def test_a_rehearsal_without_its_label_is_refused(self):
        document = dict(smoke_check(None))
        document["rehearsal_label"] = None
        self.assertTrue(ds.validate_smoke_result(document))

    def test_a_rehearsal_relabelled_as_staging_still_needs_the_label(self):
        document = dict(smoke_check(None))
        document["rehearsal_label"] = "STAGING"
        self.assertTrue(ds.validate_smoke_result(document))

    def test_a_staging_result_may_omit_the_rehearsal_label(self):
        document = dict(smoke_check(
            None, environment=DeploymentEnvironmentKind.STAGING))
        self.assertEqual(ds.validate_smoke_result(document), [])

    def test_a_disabled_tls_verification_cannot_be_reported(self):
        document = dict(smoke_check(None))
        document["tls_verification_disabled"] = True
        self.assertTrue(ds.validate_smoke_result(document))

    def test_a_measured_run_must_name_its_release(self):
        document = dict(execute_run())
        document.update({"state": ExecutionState.EXECUTED.value,
                         "attempted": 1000, "completed": 1000, "failed": 0,
                         "latency_p50_ms": 10.0, "latency_p95_ms": 20.0,
                         "throughput_rps": 50.0, "error_rate": 0.0})
        errors = ds.validate_performance_result(document)
        self.assertTrue(errors,
                        "a measurement with no pinned release was accepted")

    def test_a_root_user_in_an_image_result_is_refused(self):
        document = {"image_result_version": "pgx-wp24-image-result/1",
                    "state": ExecutionState.EXECUTED.value,
                    "reference": "pgx-platform:local",
                    "image_id": "sha256:" + "a" * 64,
                    "image_digest": None, "user": "root"}
        self.assertTrue(ds.validate_image_result(document))

    def test_a_verified_scan_must_name_its_scanner_and_database(self):
        from pgx.deployment.supply_chain import (SEVERITY_POLICY,
                                                 scan_vulnerabilities)

        document = dict(scan_vulnerabilities())
        document.update({"state": ExecutionState.VERIFIED.value})
        errors = ds.validate_supply_chain_result(
            {"supply_chain_version": "pgx-wp24-supply-chain/1",
             "sbom": {"state": "BLOCKED", "generator": None,
                      "source": None},
             "vulnerability_scan": document})
        self.assertTrue(errors,
                        "a VERIFIED scan with no scanner was accepted")

    def test_a_restore_verified_with_unsatisfied_conditions_is_refused(self):
        document = dict(backup_execution_status())
        document["restore_verified"] = True
        self.assertTrue(ds.validate_backup_execution(document))

    def test_an_operational_backup_to_a_temporary_path_is_refused(self):
        satisfied = evaluate_restore(
            separate_target=True, restored_head="h", expected_head="h",
            chain_verified=True, restored_event_count=1,
            exported_head_sequence=1, unresolved_manifest_hashes=[])
        document = dict(backup_execution_status(
            destination="/var/backups/pgx", backup_taken=True,
            restore=satisfied))
        document["destination_kind"] = "temporary"
        self.assertTrue(ds.validate_backup_execution(document))

    def test_a_release_may_not_proceed_while_gates_are_unmet(self):
        from pgx.deployment.release_validation import build_release_validation

        document = dict(build_release_validation(REPO_ROOT))
        document["release_may_proceed"] = True
        self.assertTrue(ds.validate_release_validation(document),
                        "a document asserting both was accepted")

    def test_gate_e_pass_requires_both_halves_and_real_evidence(self):
        from pgx.deployment.gate_status import (build_gate_e_status,
                                                build_wp24_gate_status)

        gate = build_wp24_gate_status(REPO_ROOT)
        document = dict(build_gate_e_status(REPO_ROOT, wp24=gate))
        document["gate_e_status"] = "PASS"
        self.assertTrue(ds.validate_gate_e_status(document))

    def test_a_published_image_cannot_be_declared(self):
        from pgx.deployment.gate_status import (build_gate_e_status,
                                                build_wp24_gate_status)

        gate = build_wp24_gate_status(REPO_ROOT)
        document = dict(build_gate_e_status(REPO_ROOT, wp24=gate))
        document["image_published"] = True
        self.assertTrue(ds.validate_gate_e_status(document))

    def test_an_undeclared_blocker_code_is_refused(self):
        document = dict(run_drills())
        document["blockers"] = [{"code": "DEPLOY_INVENTED", "detail": "x",
                                 "owner": "y", "blocking": True}]
        self.assertTrue(ds.validate_reliability_result(document))

    def test_a_blocker_without_an_owner_is_refused_by_the_schema(self):
        document = dict(run_drills())
        document["blockers"] = [{"code": "DEPLOY_IMAGE_NOT_BUILT",
                                 "detail": "x", "blocking": True}]
        self.assertTrue(ds.validate_reliability_result(document))

    def test_a_rollback_verified_after_a_downgrade_is_refused(self):
        from pgx.deployment.rollback import image_rollback_drill

        document = dict(image_rollback_drill())
        document.update({"state": ExecutionState.VERIFIED.value,
                         "database_downgraded": True})
        self.assertTrue(ds.validate_rollback_result(document))


class TestTheAtomicRateLimitCounter(unittest.TestCase):
    """One statement, or the losing side of the race is an unmetered login."""

    def test_the_statement_is_a_single_upsert_with_returning(self):
        statement = " ".join(ATOMIC_HIT_SQL.split()).upper()
        self.assertIn("INSERT INTO", statement)
        self.assertIn("ON CONFLICT", statement)
        self.assertIn("DO UPDATE SET", statement)
        self.assertIn("RETURNING", statement)
        # One statement. A semicolon would mean two, and two is the race.
        self.assertEqual(ATOMIC_HIT_SQL.count(";"), 0)

    def test_there_is_no_select_before_the_write(self):
        """A read-then-write interleaves as read(4), read(4), write(5),
        write(5), and the fifth and sixth attempts both pass a limit of
        five."""
        self.assertNotIn("SELECT", " ".join(ATOMIC_HIT_SQL.split()).upper())

    def test_the_new_count_is_derived_from_the_stored_row(self):
        """Not from EXCLUDED: the proposed value is always 1, so an
        EXCLUDED-based increment would reset the counter on every conflict."""
        statement = " ".join(ATOMIC_HIT_SQL.split())
        self.assertIn("security_rate_limit_counters.hit_count + 1", statement)
        self.assertNotIn("EXCLUDED.hit_count", statement)

    def test_the_store_takes_a_factory_and_commits_for_itself(self):
        """A refused login must still be counted after its transaction rolls
        back."""
        from tests.fixtures.wp24.doubles import CountingSessionFactory

        factory = CountingSessionFactory()
        store = SqlAlchemyRateLimitStore(factory)
        import datetime as dt

        store.hit(policy_id="LOGIN_PER_USERNAME", key="sha256:x",
                  window_start=dt.datetime(2026, 1, 1,
                                           tzinfo=dt.timezone.utc))
        calls = factory.sessions[0].calls
        self.assertIn("commit", calls)
        self.assertIn("close", calls)

    def test_a_failing_backend_propagates_so_the_limiter_denies(self):
        """RateLimiter turns any exception into RATE_LIMIT_UNAVAILABLE and
        refuses. A store that swallowed the error would wave the attempt
        through."""
        import datetime as dt

        class _Broken:
            def __call__(self):
                return self

            def execute(self, *a, **k):
                raise RuntimeError("connection refused")

            def rollback(self):
                pass

            def close(self):
                pass

        store = SqlAlchemyRateLimitStore(_Broken())
        with self.assertRaises(RuntimeError):
            store.hit(policy_id="LOGIN_PER_USERNAME", key="sha256:x",
                      window_start=dt.datetime(2026, 1, 1,
                                               tzinfo=dt.timezone.utc))


class TestTheRowRecordSeam(unittest.TestCase):
    """The adapters never rewrite an identity."""

    def test_a_user_update_does_not_copy_the_username_or_id(self):
        """Every audit row already written names this actor; rewriting the
        identity under them would silently reattribute their history."""
        import ast

        import pgx.deployment.stores as module
        from tests.fixtures.wp24.doubles import module_source

        tree = ast.parse(module_source(module))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef) or \
                    node.name != "_apply_user_record":
                continue
            assigned = {
                target.attr
                for statement in node.body
                if isinstance(statement, ast.Assign)
                for target in statement.targets
                if isinstance(target, ast.Attribute)}
            self.assertNotIn("user_id", assigned)
            self.assertNotIn("username", assigned)
            self.assertIn("auth_generation", assigned)

    def test_the_audit_store_offers_no_mutation(self):
        from pgx.deployment.stores import SqlAlchemyAuditStore

        for name in ("update", "delete", "remove", "truncate"):
            with self.subTest(method=name):
                self.assertFalse(hasattr(SqlAlchemyAuditStore, name))

    def test_a_naive_timestamp_is_normalised_to_utc(self):
        """A driver returning naive values would make every expiry comparison
        in SessionRecord raise."""
        import datetime as dt

        from pgx.deployment.stores import _aware

        naive = dt.datetime(2026, 1, 1, 12, 0)
        self.assertEqual(_aware(naive).tzinfo, dt.timezone.utc)
        aware = naive.replace(tzinfo=dt.timezone.utc)
        self.assertIs(_aware(aware), aware)
        self.assertIsNone(_aware(None))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
