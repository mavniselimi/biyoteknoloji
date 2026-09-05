# -*- coding: utf-8 -*-
"""Runtime rejection of boundary violations (WP-02).

The dependency tests prove the *static* layering. These prove the boundary also
holds at runtime, for callers with no type checker: a repository handed the
wrong domain object raises rather than storing it.

The repository classes import SQLAlchemy. Where it is unavailable, the runtime
half is exercised through the shared guard function that every repository uses,
and the wiring is verified from the AST - so the suite reports a real result
either way and never silently skips the boundary.
"""

from __future__ import annotations

import ast
import io
import os
import unittest

from tests.unit.domain._fixtures import (
    NOW, make_evidence, make_rule, make_source_entry, make_validated_rule,
)

from pgx.domain.claims import OperationMode
from pgx.domain.errors import RepositoryTypeError
from pgx.domain.identifiers import AssessmentId, ReleaseBundleId
from pgx.domain.models import Assessment, EvidenceRecord

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _source(relative: str) -> str:
    with io.open(os.path.join(REPO_ROOT, relative),
                 encoding="utf-8") as handle:
        return handle.read()
REPOSITORIES_PATH = os.path.join(REPO_ROOT, "pgx", "infrastructure", "db", "repositories.py")

try:  # pragma: no cover - depends on the environment
    import sqlalchemy  # noqa: F401
    SQLALCHEMY_AVAILABLE = True
except ImportError:  # pragma: no cover
    SQLALCHEMY_AVAILABLE = False


def _assessment() -> Assessment:
    return Assessment(
        id=AssessmentId.new(), release_bundle_id=ReleaseBundleId.new(), mode=OperationMode.DEMO,
        input_hash="sha256:" + "c" * 64, created_at=NOW)


class TestRepositoryTypeGuard(unittest.TestCase):
    """The guard every repository delegates to must reject foreign types."""

    def _guard(self):
        # Imported lazily and directly so the guard is testable without a driver.
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "_wp02_repo_guard_probe", REPOSITORIES_PATH)
        if SQLALCHEMY_AVAILABLE:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module._require_exact
        # Rebuild the guard from its own source so the behaviour under test is
        # the shipped code, not a reimplementation.
        with io.open(REPOSITORIES_PATH, encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), filename=REPOSITORIES_PATH)
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == "_require_exact":
                namespace: dict = {"RepositoryTypeError": RepositoryTypeError}
                exec(compile(ast.Module(body=[node], type_ignores=[]),
                             REPOSITORIES_PATH, "exec"), namespace)
                return namespace["_require_exact"]
        self.fail("_require_exact not found in repositories.py")

    def test_evidence_repository_guard_rejects_an_assessment(self):
        guard = self._guard()
        with self.assertRaises(RepositoryTypeError) as ctx:
            guard(_assessment(), EvidenceRecord, "EvidenceRepository.add")
        message = str(ctx.exception)
        self.assertIn("EvidenceRecord", message)
        self.assertIn("Assessment", message)

    def test_guard_accepts_the_exact_owned_type(self):
        guard = self._guard()
        record = make_evidence()
        self.assertIs(guard(record, EvidenceRecord, "EvidenceRepository.add"), record)

    def test_guard_rejects_a_subclass(self):
        """Exact type, not isinstance: a subclass could smuggle extra state."""
        guard = self._guard()

        class SneakyEvidence(EvidenceRecord):
            pass

        with self.assertRaises(RepositoryTypeError):
            guard(SneakyEvidence(**{
                field: getattr(make_evidence(), field)
                for field in EvidenceRecord.__slots__}),
                EvidenceRecord, "EvidenceRepository.add")

    def test_guard_rejects_none_and_primitives(self):
        guard = self._guard()
        for bad in (None, "evidence", 42, {"id": 1}):
            with self.assertRaises(RepositoryTypeError, msg=repr(bad)):
                guard(bad, EvidenceRecord, "EvidenceRepository.add")


class TestRepositoryWiringUsesTheGuard(unittest.TestCase):
    """Every ``add`` really calls the guard with its own domain type."""

    EXPECTED = {
        "SqlAlchemySourceRegistryRepository": "SourceRegistryEntry",
        "SqlAlchemyGeneRepository": "Gene",
        "SqlAlchemyDrugRepository": "Drug",
        "SqlAlchemyEvidenceRepository": "EvidenceRecord",
        "SqlAlchemyInterpretationRepository": "CuratedInterpretation",
        "SqlAlchemyRuleRepository": "ComputableRule",
    }

    @classmethod
    def setUpClass(cls):
        with io.open(REPOSITORIES_PATH, encoding="utf-8") as handle:
            cls.tree = ast.parse(handle.read(), filename=REPOSITORIES_PATH)

    def test_every_add_method_guards_its_exact_type(self):
        checked = {}
        for node in self.tree.body:
            if not isinstance(node, ast.ClassDef) or node.name not in self.EXPECTED:
                continue
            for item in node.body:
                if not (isinstance(item, ast.FunctionDef) and item.name == "add"):
                    continue
                guarded = False
                for call in ast.walk(item):
                    if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) \
                            and call.func.id == "_require_exact":
                        expected_type = call.args[1]
                        self.assertIsInstance(expected_type, ast.Name)
                        self.assertEqual(expected_type.id, self.EXPECTED[node.name])
                        guarded = True
                self.assertTrue(guarded, "%s.add is unguarded" % node.name)
                checked[node.name] = True
        self.assertEqual(sorted(checked), sorted(self.EXPECTED))

    def test_no_repository_accepts_an_assessment(self):
        for node in ast.walk(self.tree):
            if isinstance(node, ast.FunctionDef):
                for argument in node.args.args[1:]:
                    if argument.annotation is None:
                        continue
                    names = {child.id for child in ast.walk(argument.annotation)
                             if isinstance(child, ast.Name)}
                    self.assertNotIn("Assessment", names,
                                     "%s accepts an Assessment" % node.name)

    def test_no_repository_calls_commit(self):
        for node in self.tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            for call in ast.walk(node):
                if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute):
                    self.assertNotEqual(
                        call.func.attr, "commit",
                        "%s must not control the transaction" % node.name)

    def test_no_public_repository_method_returns_an_orm_type(self):
        """No ORM instance crosses the repository boundary.

        Public methods only. A private helper that fetches a row is how every
        repository works internally - the boundary is what callers can reach,
        and a rule that forbade the helper would forbid the pattern rather than
        the leak. Leading-underscore methods are inside the boundary; anything
        without one is the boundary itself.
        """
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.FunctionDef) or node.returns is None:
                continue
            if node.name.startswith("_"):
                continue
            names = {child.id for child in ast.walk(node.returns)
                     if isinstance(child, ast.Name)}
            for name in names:
                self.assertFalse(name.endswith("ORM"),
                                 "%s returns %s" % (node.name, name))

    def test_a_private_orm_helper_never_leaks_through_a_public_method(self):
        """The helpers that do touch ORM rows are used only internally."""
        private_orm_helpers = set()
        for node in ast.walk(self.tree):
            if (isinstance(node, ast.FunctionDef) and node.name.startswith("_")
                    and node.returns is not None):
                names = {child.id for child in ast.walk(node.returns)
                         if isinstance(child, ast.Name)}
                if any(name.endswith("ORM") for name in names):
                    private_orm_helpers.add(node.name)
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.FunctionDef) or node.name.startswith("_"):
                continue
            for inner in ast.walk(node):
                if (isinstance(inner, ast.Return) and inner.value is not None
                        and isinstance(inner.value, ast.Call)
                        and getattr(inner.value.func, "attr", None)
                        in private_orm_helpers):
                    self.fail("%s returns the raw result of %s"
                              % (node.name, inner.value.func.attr))


class TestNoAssessmentPersistenceWasInvented(unittest.TestCase):
    """Assessment persistence may exist only once it has something to record.

    This class used to assert that ``AssessmentORM`` was physically absent.
    That assertion is obsolete: WP-14 built the assessment engine, so a
    calculated result now exists to persist and the tables arrive with it in
    migration 0009. What the assertion stood for has not moved, and is checked
    here instead - the table may exist, and it may not exist *without* the
    release identity that makes a stored result reproducible
    (``SAFETY-INV-007``). Tables belonging to work packages that have not
    happened are still refused by name.
    """

    def _orm_classes(self):
        path = os.path.join(REPO_ROOT, "pgx", "infrastructure", "db",
                            "models.py")
        with io.open(path, encoding="utf-8") as handle:
            return ast.parse(handle.read(), filename=path)

    def test_no_later_work_package_orm_model_exists(self):
        tree = self._orm_classes()
        names = {node.name for node in tree.body
                 if isinstance(node, ast.ClassDef)}
        for forbidden in ("ValidationCaseORM", "ExpertReviewORM",
                          "IngestionRunORM", "RawArtifactORM", "UserORM",
                          "SessionORM", "StructuredReportORM", "ReportORM"):
            self.assertNotIn(forbidden, names,
                             "%s belongs to a later work package" % forbidden)

    def test_the_assessment_table_cannot_exist_without_a_release(self):
        """The invariant the old absence assertion was protecting.

        An assessment that cannot name the software, dataset and ruleset it
        ran against is not reproducible, cannot be audited and cannot be
        retracted. Every one of those columns is NOT NULL and the release is a
        real foreign key, so the table cannot hold a result whose provenance
        was never recorded.
        """
        source = _source(os.path.join("pgx", "infrastructure", "db",
                                      "models.py"))
        start = source.index("class AssessmentORM(Base):")
        end = source.index("class AssessmentMedicationORM(Base):")
        body = source[start:end]
        for required in ("release_id", "software_version_id",
                         "dataset_version_id", "ruleset_version_id",
                         "release_manifest_hash", "coverage_manifest_hash",
                         "evidence_build_content_hash", "input_hash",
                         "output_hash"):
            with self.subTest(column=required):
                self.assertIn(required, body)
                self.assertNotIn("%s: Mapped[Optional" % required, body)
        self.assertIn('ForeignKey("release_bundles.id", ondelete="RESTRICT")',
                      body)

    def test_the_assessment_tables_are_append_only(self):
        """A completed assessment is a record of what was calculated. Editing
        one would make the audit trail describe a calculation that never
        happened, so the database refuses UPDATE and DELETE outright."""
        source = _source(os.path.join("migrations", "versions",
                                      "0009_wp14_assessments.py"))
        self.assertIn("pgx_assessment_append_only", source)
        self.assertIn("BEFORE UPDATE OR DELETE ON", source)
        # The triggers are created in a loop over ASSESSMENT_TABLES, so the
        # check is that the loop exists and that the tuple it walks names
        # every table - not that five literal trigger names appear.
        self.assertIn('"CREATE TRIGGER trg_%s_append_only "', source)
        start = source.index("ASSESSMENT_TABLES = (")
        end = source.index(")", start)
        declared = source[start:end]
        for table in ("assessments", "assessment_medications",
                      "assessment_axes", "assessment_findings",
                      "assessment_finding_evidence"):
            with self.subTest(table=table):
                self.assertIn('"%s"' % table, declared)

    def test_the_assessment_repository_offers_no_update_or_delete(self):
        source = _source(os.path.join("pgx", "infrastructure", "db",
                                      "assessments.py"))
        tree = ast.parse(source)
        methods = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name.endswith(
                    "AssessmentRepository"):
                methods.update(item.name for item in node.body
                               if isinstance(item, ast.FunctionDef))
        self.assertIn("add", methods)
        for forbidden in ("update", "delete", "remove", "edit", "set_status"):
            with self.subTest(method=forbidden):
                self.assertNotIn(forbidden, methods)

    def test_the_release_registry_models_are_present(self):
        """The other half of the same boundary: WP-03 did add these."""
        path = os.path.join(REPO_ROOT, "pgx", "infrastructure", "db", "models.py")
        with io.open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), filename=path)
        names = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}
        for expected in ("SoftwareVersionORM", "RulesetVersionORM", "RulesetRuleORM",
                         "ReleaseBundleORM", "ActiveReleaseORM", "AuditEventORM"):
            self.assertIn(expected, names)

    def test_migration_creates_no_assessment_or_release_table(self):
        path = os.path.join(REPO_ROOT, "migrations", "versions",
                            "0001_wp02_foundation.py")
        with io.open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), filename=path)
        created = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                    and node.func.attr == "create_table" and node.args:
                created.append(node.args[0].value)
        # 0001 is the WP-02 foundation and is frozen: it must still create
        # exactly the eleven tables it always did, and nothing WP-03 added.
        for forbidden in ("assessments", "assessment_findings", "release_bundles",
                          "active_release", "ruleset_versions", "ruleset_rules",
                          "software_versions", "audit_events",
                          "users", "sessions", "validation_cases", "expert_reviews",
                          "ingestion_runs", "raw_artifacts"):
            self.assertNotIn(forbidden, created,
                             "%s is not a 0001 table" % forbidden)
        self.assertEqual(len(created), 11)

    def test_no_migration_creates_a_table_beyond_wp03(self):
        """Neither migration may reach into WP-04 or later."""
        created = []
        for revision in ("0001_wp02_foundation.py", "0002_wp03_release_registry.py"):
            path = os.path.join(REPO_ROOT, "migrations", "versions", revision)
            with io.open(path, encoding="utf-8") as handle:
                tree = ast.parse(handle.read(), filename=path)
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "create_table" and node.args):
                    created.append(node.args[0].value)
        for forbidden in ("assessments", "assessment_findings", "coverage_assessments",
                          "users", "sessions", "roles", "user_roles",
                          "validation_cases", "expert_reviews",
                          "ingestion_runs", "raw_artifacts", "resolution_queue"):
            self.assertNotIn(forbidden, created,
                             "%s belongs to a later work package" % forbidden)

    def test_validated_rule_still_requires_evidence_at_the_domain_level(self):
        rule = make_validated_rule()
        self.assertTrue(rule.evidence_record_ids)
        self.assertTrue(rule.is_executable)
        self.assertFalse(make_rule().is_executable)

    def test_source_entry_helper_still_rejects_release_eligible_internal_source(self):
        from pgx.domain.enums import SourceRole
        from pgx.domain.errors import DomainInvariantError
        with self.assertRaises(DomainInvariantError):
            make_source_entry(role=SourceRole.INTERNAL_SYSTEM, release_eligible=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
