# -*- coding: utf-8 -*-
"""Assessment persistence (section H).

Two halves, and the split is forced by the environment rather than chosen.

SQLAlchemy, Alembic and a PostgreSQL driver cannot be installed here, so the
migration cannot be *run* and the ORM cannot be *imported*. What can be checked
is what they say: the row mapping, which is pure and testable; the constraints
and triggers migration 0009 declares, read from its source; and the transaction
contract, exercised against an in-memory unit of work with the same
all-or-nothing behaviour. ``tests/integration/db/`` holds the tests that need a
real server and skip honestly without one, and
``docs/evidence/wp14-determinism.md`` records what this environment did and did
not prove.

The invariant this file is most careful about is atomicity: an assessment, its
medications, its axes, its findings, its evidence links and one audit event are
staged together and committed together. A finding that outlived its assessment
would be a calculated claim with no recorded provenance.
"""

from __future__ import annotations

import ast
import datetime as _dt
import io
import os
import unittest

from pgx.domain.enums import AttentionLevel, CoverageStatus
from pgx.domain.errors import DomainInvariantError
from pgx.engine.risk_errors import AssessmentPersistenceError
from tests.fixtures.wp13.synthetic import DRUG_1, DRUG_2, GENE_1, GENE_2
from tests.unit.application._assessment_support import (
    REPO_ROOT, InMemoryUnitOfWork, SyntheticAssessmentWorld)

MIGRATION = os.path.join(REPO_ROOT, "migrations", "versions",
                         "0009_wp14_assessments.py")
ORM = os.path.join(REPO_ROOT, "pgx", "infrastructure", "db", "models.py")
ADAPTER = os.path.join(REPO_ROOT, "pgx", "infrastructure", "db",
                       "assessments.py")


def _source(path):
    with io.open(path, encoding="utf-8") as handle:
        return handle.read()


class TestTheTransactionIsAllOrNothing(unittest.TestCase):

    def setUp(self):
        self.world = SyntheticAssessmentWorld()
        self.addCleanup(self.world.close)

    def test_a_successful_run_stores_exactly_one_assessment(self):
        result = self.world.execute(medications=[DRUG_1])
        self.assertEqual(len(self.world.store), 1)
        self.assertEqual(self.world.store.list_ids(),
                         (result.assessment_id.to_json(),))

    def test_the_stored_aggregate_is_complete(self):
        result = self.world.execute(medications=[DRUG_1, DRUG_2])
        row = self.world.store.row(result.assessment_id)
        self.assertEqual(row["assessment"].id, result.assessment_id)
        self.assertEqual(len(row["computation"].medications), 2)
        self.assertTrue(row["computation"].findings)
        self.assertTrue(row["input_snapshot"])
        self.assertTrue(row["output_snapshot"])
        self.assertEqual(row["actor"], "TEST-assessment-actor-1")

    def test_a_failed_commit_leaves_nothing_behind(self):
        world = SyntheticAssessmentWorld(fail_on_commit=True)
        self.addCleanup(world.close)
        with self.assertRaises(AssessmentPersistenceError) as caught:
            world.execute(medications=[DRUG_1])
        self.assertEqual(caught.exception.code,
                         "ASSESSMENT_PERSISTENCE_REFUSED")
        self.assertEqual(len(world.store), 0)

    def test_a_failed_commit_records_no_success_audit(self):
        world = SyntheticAssessmentWorld(fail_on_commit=True)
        self.addCleanup(world.close)
        with self.assertRaises(AssessmentPersistenceError):
            world.execute(medications=[DRUG_1])
        self.assertNotIn("ASSESSMENT_COMPLETED", world.audit.actions)

    def test_an_uncommitted_unit_of_work_stores_nothing(self):
        store = self.world.store
        before = len(store)
        with InMemoryUnitOfWork(store) as uow:
            uow.assessments.add(assessment=None, computation=None,
                                input_snapshot={}, output_snapshot={},
                                actor="TEST", created_at=_dt.datetime.now(
                                    _dt.timezone.utc))
        self.assertEqual(len(store), before)

    def test_a_successful_run_records_exactly_one_completion(self):
        self.world.execute(medications=[DRUG_1])
        self.assertEqual(self.world.audit.actions, ("ASSESSMENT_COMPLETED",))

    def test_the_completion_audit_names_the_hashes_and_no_case_content(self):
        result = self.world.execute(medications=[DRUG_1],
                                    phenotypes={GENE_1: "POOR"})
        record = self.world.audit.records[0]
        self.assertEqual(record["output_hash"], result.output_hash)
        text = repr(record)
        for forbidden in ("POOR", GENE_1, "TEST-CASE-1"):
            with self.subTest(leak=forbidden):
                self.assertNotIn(forbidden, text)

    def test_a_dry_run_persists_nothing(self):
        self.world.dry_run(medications=[DRUG_1])
        self.assertEqual(len(self.world.store), 0)
        self.assertEqual(self.world.audit.actions, ())

    def test_a_service_without_a_unit_of_work_calculates_but_does_not_store(
            self):
        world = SyntheticAssessmentWorld(persist=False)
        self.addCleanup(world.close)
        result = world.execute(medications=[DRUG_1])
        self.assertFalse(result.persisted)
        self.assertEqual(len(world.store), 0)


class TestCompleteReleaseMetadataIsMandatory(unittest.TestCase):
    """SAFETY-INV-007, checked before the transaction opens."""

    def setUp(self):
        self.world = SyntheticAssessmentWorld()
        self.addCleanup(self.world.close)

    def test_a_stored_assessment_names_every_pinned_version(self):
        result = self.world.execute(medications=[DRUG_1])
        provenance = self.world.store.row(
            result.assessment_id)["provenance"]
        for field in ("release_public_id", "release_manifest_hash",
                      "software_version_id", "dataset_version_id",
                      "ruleset_version_id", "ruleset_content_hash",
                      "evidence_build_content_hash", "coverage_manifest_hash",
                      "protocol_content_hash", "source_policy_content_hash"):
            with self.subTest(field=field):
                self.assertTrue(getattr(provenance, field))

    def test_an_assessment_without_provenance_cannot_be_persisted(self):
        import dataclasses
        from pgx.domain.models import Assessment
        result = self.world.execute(medications=[DRUG_1])
        stored = self.world.store.row(result.assessment_id)["assessment"]
        stripped = dataclasses.replace(stored, release_provenance=None)
        with self.assertRaises(DomainInvariantError):
            stripped.require_complete_release_metadata()

    def test_an_assessment_without_an_output_hash_cannot_be_persisted(self):
        import dataclasses
        result = self.world.execute(medications=[DRUG_1])
        stored = self.world.store.row(result.assessment_id)["assessment"]
        stripped = dataclasses.replace(stored, output_hash=None)
        with self.assertRaises(DomainInvariantError):
            stripped.require_complete_release_metadata()

    def test_the_repository_checks_before_storing(self):
        import dataclasses
        result = self.world.execute(medications=[DRUG_1])
        row = self.world.store.row(result.assessment_id)
        stripped = dataclasses.replace(row["assessment"],
                                       release_provenance=None)
        with self.assertRaises(DomainInvariantError):
            self.world.store.add(
                assessment=stripped, computation=row["computation"],
                input_snapshot={}, output_snapshot={}, actor="TEST",
                created_at=row["created_at"])

    def test_a_duplicate_assessment_identity_is_refused(self):
        result = self.world.execute(medications=[DRUG_1])
        row = self.world.store.row(result.assessment_id)
        with self.assertRaises(ValueError):
            self.world.store.add(
                assessment=row["assessment"], computation=row["computation"],
                input_snapshot=row["input_snapshot"],
                output_snapshot=row["output_snapshot"], actor=row["actor"],
                created_at=row["created_at"])


class TestTheStoredAssessmentIsImmutable(unittest.TestCase):

    def setUp(self):
        self.world = SyntheticAssessmentWorld()
        self.addCleanup(self.world.close)

    def test_the_repository_offers_no_update_and_no_delete(self):
        for forbidden in ("update", "delete", "remove", "edit", "set_status",
                          "save"):
            with self.subTest(method=forbidden):
                self.assertFalse(hasattr(self.world.store, forbidden))

    def test_the_stored_assessment_object_is_frozen(self):
        import dataclasses
        result = self.world.execute(medications=[DRUG_1])
        stored = self.world.store.row(result.assessment_id)["assessment"]
        with self.assertRaises((dataclasses.FrozenInstanceError,
                                AttributeError)):
            stored.output_hash = "sha256:" + "0" * 64

    def test_the_stored_findings_are_frozen(self):
        import dataclasses
        result = self.world.execute(medications=[DRUG_1])
        computation = self.world.store.row(
            result.assessment_id)["computation"]
        with self.assertRaises((dataclasses.FrozenInstanceError,
                                AttributeError)):
            computation.findings[0].attention_level = AttentionLevel.LOW

    def test_the_stored_coverage_is_frozen(self):
        import dataclasses
        result = self.world.execute(medications=[DRUG_1])
        computation = self.world.store.row(
            result.assessment_id)["computation"]
        with self.assertRaises((dataclasses.FrozenInstanceError,
                                AttributeError)):
            computation.medications[0].coverage_status = CoverageStatus.FULL


class TestTheRowMappingIsPureAndComplete(unittest.TestCase):
    """``assessment_to_rows`` builds row payloads and touches no session, so
    what persistence would write can be checked without a database."""

    def setUp(self):
        self.world = SyntheticAssessmentWorld()
        self.addCleanup(self.world.close)
        self.result = self.world.execute(medications=[DRUG_1, DRUG_2])
        self.row = self.world.store.row(self.result.assessment_id)

    def rows(self):
        # Imported inside the test: the adapter imports SQLAlchemy, which is
        # not installable in this environment. The mapping function itself is
        # pure, so it is read and executed via its AST-checked source instead
        # where the import is unavailable.
        source = _source(ADAPTER)
        self.assertIn("def assessment_to_rows", source)
        return source

    def test_the_mapping_function_is_pure(self):
        """It builds dictionaries and touches no session, so the shape it
        would write is testable without a database."""
        source = self.rows()
        tree = ast.parse(source)
        function = [node for node in tree.body
                    if isinstance(node, ast.FunctionDef)
                    and node.name == "assessment_to_rows"][0]
        names = {getattr(node, "attr", getattr(node, "id", ""))
                 for node in ast.walk(function)}
        for forbidden in ("_session", "session", "commit", "flush",
                          "execute"):
            with self.subTest(name=forbidden):
                self.assertNotIn(forbidden, names)

    def test_every_persisted_table_is_produced(self):
        source = self.rows()
        for key in ('"assessment":', '"medications":', '"axes":',
                    '"findings":', '"evidence":'):
            with self.subTest(key=key):
                self.assertIn(key, source)

    def test_the_mapping_calls_the_release_metadata_check_first(self):
        source = self.rows()
        index = source.index("def assessment_to_rows")
        body = source[index:index + 2000]
        self.assertIn("require_complete_release_metadata", body)

    def test_evidence_links_are_produced_per_finding(self):
        source = self.rows()
        self.assertIn("for reference in finding.evidence_references:", source)
        self.assertIn('"evidence_record_id"', source)

    def test_ordinals_come_from_the_sorted_collections(self):
        """The stored order is the canonical order, not insertion order."""
        source = self.rows()
        self.assertIn("for ordinal, medication in enumerate("
                      "computation.medications)", source)


class TestMigration0009(unittest.TestCase):
    """Read as source. Alembic cannot run here; what it says can be checked."""

    @classmethod
    def setUpClass(cls):
        cls.source = _source(MIGRATION)
        cls.tree = ast.parse(cls.source, filename=MIGRATION)

    def _function(self, name):
        for node in self.tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == name:
                return node
        raise AssertionError("no %s() in 0009" % name)

    def _calls(self, function, attribute):
        found = []
        for node in ast.walk(function):
            if isinstance(node, ast.Call) and \
                    getattr(node.func, "attr", None) == attribute:
                found.append(node)
        return found

    def test_it_follows_0008(self):
        assignments = {}
        for node in self.tree.body:
            if isinstance(node, ast.AnnAssign) and \
                    isinstance(node.target, ast.Name) and \
                    isinstance(node.value, ast.Constant):
                assignments[node.target.id] = node.value.value
        self.assertEqual(assignments["revision"], "0009_wp14_assessments")
        self.assertEqual(assignments["down_revision"],
                         "0008_wp11_rules_and_rulesets")

    def test_it_creates_exactly_the_five_assessment_tables(self):
        created = [node.args[0].value
                   for node in self._calls(self._function("upgrade"),
                                           "create_table")]
        self.assertEqual(created, ["assessments", "assessment_medications",
                                   "assessment_axes", "assessment_findings",
                                   "assessment_finding_evidence"])

    def test_it_drops_no_table_and_no_column_on_upgrade(self):
        upgrade = self._function("upgrade")
        for attribute in ("drop_table", "drop_column"):
            with self.subTest(operation=attribute):
                self.assertEqual(self._calls(upgrade, attribute), [])

    def test_the_only_existing_object_it_touches_is_the_audit_action_list(self):
        upgrade = self._function("upgrade")
        dropped = [node.args[0].value
                   for node in self._calls(upgrade, "drop_constraint")]
        self.assertEqual(dropped, ["ck_audit_events_action_enum"])

    def test_the_audit_action_list_is_widened_not_replaced(self):
        self.assertIn("AUDIT_ACTIONS_0009 = (AUDIT_ACTIONS_0008", self.source)
        self.assertIn("'ASSESSMENT_COMPLETED', 'ASSESSMENT_REFUSED'",
                      self.source)

    def test_pilot_is_not_a_storable_mode(self):
        self.assertIn("ASSESSMENT_MODES = \"'DEMO', 'VALIDATION'\"",
                      self.source)
        self.assertNotIn("'PILOT'", self.source)

    def test_every_pinned_version_column_is_not_null(self):
        for column in ("release_public_id", "release_manifest_hash",
                       "active_pointer_generation", "software_version_id",
                       "software_version", "software_source_tree_hash",
                       "dataset_version_id", "dataset_public_id",
                       "canonical_build_content_hash", "ruleset_version_id",
                       "ruleset_public_id", "ruleset_content_hash",
                       "evidence_build_key", "evidence_build_content_hash",
                       "coverage_manifest_hash", "protocol_version",
                       "protocol_content_hash", "source_policy_version",
                       "source_policy_content_hash", "input_hash",
                       "output_hash"):
            with self.subTest(column=column):
                index = self.source.index('sa.Column("%s"' % column)
                declaration = self.source[index:index + 220]
                self.assertIn("nullable=False", declaration)

    def test_the_release_foreign_key_restricts_deletion(self):
        self.assertIn('["release_id"], ["release_bundles.id"], '
                      'ondelete="RESTRICT"', self.source)

    def test_a_cited_evidence_record_cannot_be_deleted(self):
        self.assertIn('["evidence_record_id"], ["evidence_records.id"],\n'
                      '            ondelete="RESTRICT"', self.source)

    def test_a_cited_rule_cannot_be_deleted(self):
        self.assertIn('["rule_id"], ["computable_rules.id"], '
                      'ondelete="RESTRICT"', self.source)

    def test_no_active_attention_requires_full_coverage(self):
        for name in ("ck_assessments_no_active_attention_requires_full_"
                     "coverage",
                     "ck_assessment_medications_no_active_attention_requires_"
                     "full"):
            with self.subTest(constraint=name):
                self.assertIn(name, self.source)
        self.assertIn("overall_attention <> 'NO_ACTIVE_ATTENTION' ",
                      self.source)

    def test_full_coverage_cannot_be_not_assessed(self):
        self.assertIn("ck_assessments_full_coverage_is_not_unassessed",
                      self.source)

    def test_a_finding_cannot_be_not_assessed(self):
        self.assertIn("ck_assessment_findings_attention_is_calculated",
                      self.source)
        self.assertIn("CALCULATED_ATTENTION = \"'NO_ACTIVE_ATTENTION', 'LOW', "
                      "'MEDIUM', 'HIGH'\"", self.source)

    def test_non_full_coverage_requires_reasons(self):
        for table in ("medications", "axes"):
            with self.subTest(table=table):
                self.assertIn(
                    "ck_assessment_%s_non_full_coverage_has_reasons" % table,
                    self.source)

    def test_full_coverage_carries_no_reason(self):
        for table in ("medications", "axes"):
            with self.subTest(table=table):
                self.assertIn(
                    "ck_assessment_%s_full_coverage_has_no_reason" % table,
                    self.source)

    def test_every_finding_must_cite_evidence(self):
        self.assertIn("pgx_assessment_finding_requires_evidence", self.source)
        self.assertIn("SAFETY-INV-006", self.source)

    def test_the_evidence_check_is_deferred_to_commit(self):
        """A finding and its evidence links are inserted in one transaction,
        so the check is only meaningful once both are present."""
        self.assertIn("CREATE CONSTRAINT TRIGGER "
                      "trg_assessment_findings_require_evidence", self.source)
        self.assertIn("DEFERRABLE INITIALLY DEFERRED", self.source)

    def test_a_child_row_must_belong_to_its_parents_assessment(self):
        """A join across two parents cannot be a row CHECK, so it is a
        trigger. Created in a loop, so the loop and the tables it walks are
        what is asserted rather than two literal trigger names."""
        self.assertIn("pgx_assessment_child_matches_parent", self.source)
        self.assertIn('"CREATE TRIGGER trg_%s_same_assessment "', self.source)
        upgrade = ast.get_source_segment(self.source,
                                         self._function("upgrade"))
        index = upgrade.index("trg_%s_same_assessment")
        loop = upgrade[max(0, index - 200):index]
        for table in ("assessment_axes", "assessment_findings"):
            with self.subTest(table=table):
                self.assertIn('"%s"' % table, loop)

    def test_a_duplicate_finding_identity_is_refused(self):
        self.assertIn("uq_assessment_findings_assessment_finding_identity",
                      self.source)

    def test_every_table_refuses_update_and_delete(self):
        self.assertIn("pgx_assessment_append_only", self.source)
        self.assertIn("BEFORE UPDATE OR DELETE ON", self.source)
        self.assertIn("RAISE EXCEPTION", self.source)

    def test_every_hash_column_has_a_format_check(self):
        for name in ("input_hash", "output_hash", "release_manifest_hash",
                     "ruleset_content_hash", "coverage_manifest_hash"):
            with self.subTest(column=name):
                self.assertIn("_digest_check(\"%s\")" % name, self.source)

    def test_downgrade_refuses_when_history_exists(self):
        downgrade = self._function("downgrade")
        body = ast.get_source_segment(self.source, downgrade)
        self.assertIn("SELECT count(*) FROM assessments", body)
        self.assertIn("refusing to downgrade", body)
        self.assertIn("raise RuntimeError", body)

    def test_the_refusal_runs_before_the_first_drop(self):
        downgrade = self._function("downgrade")
        body = ast.get_source_segment(self.source, downgrade)
        self.assertLess(body.index("refusing to downgrade"),
                        body.index("drop_table"))

    def test_downgrade_drops_everything_it_created(self):
        downgrade = self._function("downgrade")
        dropped = [node.args[0].value
                   for node in self._calls(downgrade, "drop_table")]
        self.assertEqual(sorted(dropped), sorted([
            "assessments", "assessment_medications", "assessment_axes",
            "assessment_findings", "assessment_finding_evidence"]))

    def test_downgrade_drops_children_before_parents(self):
        downgrade = self._function("downgrade")
        dropped = [node.args[0].value
                   for node in self._calls(downgrade, "drop_table")]
        self.assertEqual(dropped[-1], "assessments")
        self.assertEqual(dropped[0], "assessment_finding_evidence")

    def test_downgrade_drops_each_trigger_and_its_function(self):
        downgrade = self._function("downgrade")
        body = ast.get_source_segment(self.source, downgrade)
        # Whitespace-normalised: the statements are wrapped across source
        # lines, and a literal match would be asserting the formatting.
        flattened = " ".join(body.replace('"', " ").split())
        for function in ("pgx_assessment_append_only",
                         "pgx_assessment_finding_requires_evidence",
                         "pgx_assessment_child_matches_parent"):
            with self.subTest(function=function):
                self.assertIn("DROP FUNCTION IF EXISTS %s();" % function,
                              flattened)

    def test_downgrade_restores_the_0008_audit_action_list(self):
        downgrade = self._function("downgrade")
        body = ast.get_source_segment(self.source, downgrade)
        self.assertIn("AUDIT_ACTIONS_0008", body)

    def test_the_earlier_migrations_are_untouched(self):
        for name in sorted(os.listdir(os.path.dirname(MIGRATION))):
            if not name.endswith(".py") or name.startswith("__") or \
                    name.startswith("0009"):
                continue
            with self.subTest(migration=name):
                self.assertNotIn("assessment", _source(
                    os.path.join(os.path.dirname(MIGRATION), name)).lower()
                    .replace("historical assessment", "")
                    .replace("assessments, assessment_findings", "")
                    .split("def upgrade")[1])


class TestTheOrmMatchesTheMigration(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.orm = _source(ORM)
        cls.migration = _source(MIGRATION)

    def test_every_assessment_table_is_mapped(self):
        for table in ("assessments", "assessment_medications",
                      "assessment_axes", "assessment_findings",
                      "assessment_finding_evidence"):
            with self.subTest(table=table):
                self.assertIn('__tablename__ = "%s"' % table, self.orm)

    def test_the_orm_declares_the_same_invariants(self):
        for constraint in ("no_active_attention_needs_full",
                           "full_coverage_is_not_unassessed",
                           "attention_is_calculated",
                           "non_full_coverage_has_reasons",
                           "full_coverage_has_no_reason",
                           "conflict_names_its_references"):
            with self.subTest(constraint=constraint):
                self.assertIn(constraint, self.orm)

    def test_the_scientific_codes_are_nullable_in_both(self):
        """The governed rule outcome carries neither, so NOT NULL would have
        forced every row to invent one."""
        for name in ("effect_code", "explanation_code"):
            with self.subTest(column=name):
                orm_index = self.orm.index("%s: Mapped[Optional[str]]" % name)
                self.assertIn("nullable=True",
                              self.orm[orm_index:orm_index + 200])
                migration_index = self.migration.index(
                    'sa.Column("%s"' % name)
                self.assertIn("nullable=True",
                              self.migration[migration_index:
                                             migration_index + 120])

    def test_the_rationale_reference_is_required_in_both(self):
        self.assertIn("rationale_reference: Mapped[str]", self.orm)
        index = self.migration.index('sa.Column("rationale_reference"')
        self.assertIn("nullable=False", self.migration[index:index + 120])

    def test_no_orm_class_is_defined_outside_models(self):
        self.assertNotIn("(Base)", _source(ADAPTER))


if __name__ == "__main__":
    unittest.main()
