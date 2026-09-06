# -*- coding: utf-8 -*-
"""Layer boundaries the release registry must not cross (WP-03).

Three rules, each with a concrete failure it prevents.

**The service imports no infrastructure.** If it reached for a SQLAlchemy
session, the fourteen compatibility rules could not be exercised without a
database - and they are the part of this system that most needs exercising.

**The audit port offers no update or delete.** The absence *is* the contract.
A test is the only thing that stops a well-meaning refactor from adding one.

**Every new port is typed and one-per-entity**, matching the WP-02 rule that a
repository owns exactly one domain type.

Standard library only; every check reads the AST, so nothing needs installing.
"""

from __future__ import annotations

import ast
import inspect
import io
import os
import unittest

from pgx.domain import ports as ports_module
from pgx.domain.ports import (
    ActiveReleaseRepository, AuditEventRepository, DatasetVersionRepository,
    ReleaseBundleRepository, RulesetVersionRepository, SoftwareVersionRepository,
    UnitOfWork,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

SERVICE_PATH = os.path.join(REPO_ROOT, "pgx", "application", "release_service.py")
PORTS_PATH = os.path.abspath(ports_module.__file__)

WP03_PORTS = (
    SoftwareVersionRepository, DatasetVersionRepository, RulesetVersionRepository,
    ReleaseBundleRepository, ActiveReleaseRepository, AuditEventRepository,
)


def _source(path: str) -> str:
    with io.open(path, encoding="utf-8") as handle:
        return handle.read()


class TestTheServiceIsInfrastructureFree(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tree = ast.parse(_source(SERVICE_PATH))

    def _imported(self):
        modules = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module)
        return modules

    def test_it_never_imports_sqlalchemy(self):
        for module in self._imported():
            self.assertFalse(module.split(".")[0] == "sqlalchemy",
                             "the release service must not import SQLAlchemy")

    def test_it_never_imports_pgx_infrastructure(self):
        for module in self._imported():
            self.assertFalse(module.startswith("pgx.infrastructure"),
                             "%s is an infrastructure import" % module)

    def test_it_never_imports_pydantic_or_a_web_framework(self):
        for module in self._imported():
            self.assertNotIn(module.split(".")[0],
                             ("pydantic", "fastapi", "starlette", "flask",
                              "django", "requests", "httpx"))

    def test_it_imports_only_the_domain_and_the_standard_library(self):
        allowed_roots = {
            "__future__", "dataclasses", "datetime", "enum", "typing", "pgx",
        }
        for module in self._imported():
            self.assertIn(module.split(".")[0], allowed_roots, module)

    def test_it_talks_to_ports_not_to_sessions(self):
        source = _source(SERVICE_PATH)
        for token in ("Session", "session.", "engine", "execute(", "select("):
            self.assertNotIn(token, source, "%r looks like direct SQL access" % token)

    def test_the_service_can_be_constructed_without_a_database(self):
        from pgx.application.release_service import ReleaseService

        service = ReleaseService(lambda: None)
        self.assertIsNotNone(service)


class TestTheAuditPortIsAppendOnly(unittest.TestCase):

    def test_the_protocol_declares_no_mutating_method(self):
        for forbidden in ("update", "delete", "remove", "edit", "purge",
                          "set", "replace", "clear"):
            self.assertFalse(hasattr(AuditEventRepository, forbidden),
                             "AuditEventRepository must not declare %s" % forbidden)

    def test_the_protocol_declares_exactly_the_expected_methods(self):
        declared = {name for name in vars(AuditEventRepository)
                    if not name.startswith("_")}
        self.assertEqual(declared, {"append", "list_for_object", "list_recent"})

    def test_the_sqlalchemy_repository_declares_no_mutating_method(self):
        path = os.path.join(REPO_ROOT, "pgx", "infrastructure", "db",
                            "repositories.py")
        tree = ast.parse(_source(path))
        for node in ast.walk(tree):
            if (isinstance(node, ast.ClassDef)
                    and node.name == "SqlAlchemyAuditEventRepository"):
                methods = {child.name for child in node.body
                           if isinstance(child, ast.FunctionDef)
                           and not child.name.startswith("_")}
                self.assertEqual(methods,
                                 {"append", "list_for_object", "list_recent"})
                return
        self.fail("SqlAlchemyAuditEventRepository is not defined")

    def test_the_migration_installs_a_database_level_guard(self):
        """Application promises do not survive a psql prompt; the trigger does."""
        path = os.path.join(REPO_ROOT, "migrations", "versions",
                            "0002_wp03_release_registry.py")
        source = _source(path)
        self.assertIn("trg_audit_events_append_only", source)
        self.assertIn("BEFORE UPDATE OR DELETE ON audit_events", source)
        self.assertIn("RAISE EXCEPTION", source)

    def test_the_downgrade_removes_the_trigger_and_its_function(self):
        """A leftover function makes the next upgrade fail on CREATE FUNCTION."""
        path = os.path.join(REPO_ROOT, "migrations", "versions",
                            "0002_wp03_release_registry.py")
        tree = ast.parse(_source(path))
        downgrade = next(node for node in tree.body
                         if isinstance(node, ast.FunctionDef)
                         and node.name == "downgrade")
        rendered = ast.unparse(downgrade)
        self.assertIn("DROP TRIGGER IF EXISTS trg_audit_events_append_only", rendered)
        self.assertIn("DROP FUNCTION IF EXISTS pgx_audit_events_append_only",
                      rendered)


class TestTheNewPortsAreTypedAndNarrow(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tree = ast.parse(_source(PORTS_PATH))

    def _class(self, name):
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ClassDef) and node.name == name:
                return node
        raise AssertionError("%s is not declared in ports.py" % name)

    def test_every_new_port_is_a_runtime_checkable_protocol(self):
        for port in WP03_PORTS:
            with self.subTest(port=port.__name__):
                self.assertTrue(issubclass(port, object))
                node = self._class(port.__name__)
                bases = {ast.unparse(base) for base in node.bases}
                self.assertIn("Protocol", bases)

    def test_no_new_port_declares_a_generic_save(self):
        for port in WP03_PORTS:
            with self.subTest(port=port.__name__):
                methods = {child.name for child in self._class(port.__name__).body
                           if isinstance(child, ast.FunctionDef)}
                for forbidden in ("save", "store", "persist", "put"):
                    self.assertNotIn(forbidden, methods)

    def test_no_new_port_mentions_an_orm_or_session_type(self):
        for port in WP03_PORTS:
            with self.subTest(port=port.__name__):
                rendered = ast.unparse(self._class(port.__name__))
                for token in ("Session", "ORM", "Engine", "Connection", "select"):
                    self.assertNotIn(token, rendered)

    def test_every_parameter_of_every_new_port_is_annotated(self):
        for port in WP03_PORTS:
            for node in ast.walk(self._class(port.__name__)):
                if not isinstance(node, ast.FunctionDef):
                    continue
                for argument in node.args.args:
                    if argument.arg in ("self", "cls"):
                        continue
                    with self.subTest(port=port.__name__, method=node.name,
                                      argument=argument.arg):
                        self.assertIsNotNone(argument.annotation)
                        self.assertNotEqual(
                            ast.unparse(argument.annotation), "object")

    def test_the_unit_of_work_exposes_every_new_repository(self):
        annotations = {child.target.id
                       for child in self._class("UnitOfWork").body
                       if isinstance(child, ast.AnnAssign)}
        for name in ("software_versions", "dataset_versions", "ruleset_versions",
                     "releases", "active_release", "audit"):
            self.assertIn(name, annotations)

    def test_the_active_release_port_separates_reading_from_locking(self):
        methods = {child.name for child in self._class("ActiveReleaseRepository").body
                   if isinstance(child, ast.FunctionDef)}
        self.assertEqual(methods, {"get", "get_for_update", "update"})

    def test_the_update_method_requires_an_expected_generation(self):
        for node in ast.walk(self._class("ActiveReleaseRepository")):
            if isinstance(node, ast.FunctionDef) and node.name == "update":
                names = {argument.arg for argument in node.args.args}
                self.assertIn("expected_generation", names)
                return
        self.fail("ActiveReleaseRepository.update is not declared")

    def test_the_release_port_offers_no_general_update(self):
        """A release's pinned content is immutable after registration."""
        methods = {child.name for child in self._class("ReleaseBundleRepository").body
                   if isinstance(child, ast.FunctionDef)}
        self.assertEqual(methods, {"add", "get", "get_by_public_id",
                                   "set_status", "list_all"})


class TestTheSqlAlchemyRepositoriesImplementThePorts(unittest.TestCase):
    """Structural conformance, checked without importing SQLAlchemy."""

    PAIRS = (
        ("SqlAlchemySoftwareVersionRepository", SoftwareVersionRepository),
        ("SqlAlchemyDatasetVersionRepository", DatasetVersionRepository),
        ("SqlAlchemyRulesetVersionRepository", RulesetVersionRepository),
        ("SqlAlchemyReleaseBundleRepository", ReleaseBundleRepository),
        ("SqlAlchemyActiveReleaseRepository", ActiveReleaseRepository),
        ("SqlAlchemyAuditEventRepository", AuditEventRepository),
    )

    @classmethod
    def setUpClass(cls):
        path = os.path.join(REPO_ROOT, "pgx", "infrastructure", "db",
                            "repositories.py")
        cls.tree = ast.parse(_source(path))

    def test_each_repository_declares_every_port_method(self):
        classes = {node.name: node for node in ast.walk(self.tree)
                   if isinstance(node, ast.ClassDef)}
        for name, port in self.PAIRS:
            with self.subTest(repository=name):
                self.assertIn(name, classes)
                declared = {child.name for child in classes[name].body
                            if isinstance(child, ast.FunctionDef)}
                required = {method for method in vars(port)
                            if not method.startswith("_")}
                self.assertTrue(required <= declared,
                                "%s is missing %s" % (name, required - declared))

    def test_no_repository_commits(self):
        """Transaction control belongs to the unit of work alone."""
        classes = {node.name: node for node in ast.walk(self.tree)
                   if isinstance(node, ast.ClassDef)}
        for name, _ in self.PAIRS:
            rendered = ast.unparse(classes[name])
            self.assertNotIn(".commit()", rendered)
            self.assertNotIn(".rollback()", rendered)


class TestReleaseAndIngestionStaySeparate(unittest.TestCase):
    """WP-04 built ``pgx/ingestion``, so "it does not exist" is obsolete.

    These tests replaced three that asserted the ingestion package was absent.
    That assertion was correct for WP-03 and became false-by-design the moment
    WP-04 legitimately created the package. What was worth keeping is the
    *separation*, so that is what is asserted now: the release registry does
    not depend on ingestion, ingestion does not activate releases or invent
    scientific records, and neither reaches into a work package that has not
    started.
    """

    RELEASE_MODULES = ("release_service.py", "release_cli.py",
                       "release_schema.py", "legacy_baseline.py")
    INGESTION_MODULES = ("ingestion_service.py", "ingestion_cli.py")
    SCIENTIFIC_MODULES = ("source_policy_cli.py",)
    SNAPSHOT_MODULES = ("dataset_service.py", "dataset_cli.py",
                        "snapshot_schema.py")

    #: WP-07. A CLI, the published-schema loader, and one service holding the
    #: single audited state transition this project performs. The
    #: canonicalization logic itself lives in ``pgx/normalization``.
    # WP-C06 adds quality_decision_service.py here: it records a dataset
    # quality decision and hands an approval to the WP-07 transition, which
    # is the canonicalization lifecycle. Listed deliberately, which is what
    # this inventory is for.
    CANONICALIZATION_MODULES = ("normalize_cli.py", "canonical_schema.py",
                                "quality_decision_service.py",
                                "canonical_service.py")

    #: WP-08. A CLI and the published-schema loader. The evidence logic lives
    #: in ``pgx/evidence``, and there is deliberately no evidence *service*
    #: here: a service in this layer is where an audited state transition would
    #: go, and WP-08 performs none.
    EVIDENCE_MODULES = ("evidence_cli.py", "evidence_schema.py")

    #: WP-09 and WP-10. Two CLIs and the published-schema loader. The protocol
    #: and the workflow both live in ``pgx/curation``; this layer drives them.
    #:
    #: There is still no curation *service* module here, and that remains
    #: deliberate. WP-10's ``CurationWorkflowService`` sits in
    #: ``pgx/curation/workflow`` beside the state machine it enforces, because
    #: it is the workflow, not an orchestration of one. What lives here is the
    #: offline entry point.
    CURATION_MODULES = ("curation_protocol_cli.py", "curation_schema.py",
                        "curation_workflow_cli.py",
                        "curation_workflow_schema.py")

    #: WP-11. Two services, a CLI, the published-schema loader, and the
    #: gate-status builder. There *are* services here, unlike WP-08 and WP-10,
    #: because WP-11 performs audited state transitions: a rule and a ruleset
    #: each move through a lifecycle, and this layer is where that is driven.
    #: ``rule_gate_status.py`` is not a service - it reads real repository
    #: state and reports why no real rule may be created, and it transitions
    #: nothing.
    RULES_MODULES = ("rule_gate_status.py", "rule_service.py",
                     "rules_cli.py", "rules_schema.py", "ruleset_service.py")

    #: WP-12. A CLI and the published-schema loader. There is no phenotype
    #: *service*: the engine performs no audited state transition, because it
    #: changes no state at all. Matching is a pure function of its inputs.
    ENGINE_MODULES = ("phenotype_cli.py", "phenotype_schema.py")

    #: WP-13. A CLI, the published-schema loader, and a gate-status builder
    #: that reads real repository state and reports why no real coverage claim
    #: may exist yet. There is no coverage *service*, for WP-12's reason:
    #: evaluating coverage transitions nothing. ``coverage_gate_status.py``
    #: is the counterpart of ``rule_gate_status.py`` one work package later,
    #: and like it, it refuses rather than records.
    COVERAGE_MODULES = ("coverage_cli.py", "coverage_gate_status.py",
                        "coverage_schema.py")

    #: WP-14. A CLI, the published-schema loader, a gate-status builder, the
    #: input and pinned-release contracts, and - unlike WP-12 and WP-13 - a
    #: real *service*, because executing an assessment does transition state:
    #: it writes an immutable record and an audit event, atomically.
    #: WP-14, plus the two candidate-track modules. Those two execute a
    #: candidate release rather than a governed one, which is a different
    #: artifact with different provenance, but the same layer: they resolve a
    #: release, check the claim boundary, and hand the work to the engine.
    ASSESSMENT_MODULES = ("assessment_cli.py", "assessment_gate_status.py",
                          "assessment_models.py", "assessment_read_model.py",
                          "assessment_schema.py", "assessment_service.py",
                          "assessment_snapshot.py",
                          "candidate_assessment_service.py",
                          "candidate_release.py")

    #: WP-15. The same four shapes again: a service, a CLI, the schema loader
    #: and a gate-status builder. The reporting *logic* lives in
    #: ``pgx/reporting``, on the same split every work package since WP-11 has
    #: used.
    REPORT_MODULES = ("report_cli.py", "report_gate_status.py",
                      "report_schema.py", "report_service.py")

    #: WP-16. Not a service and not a CLI: one small transport-neutral value
    #: type describing *who asked and over what channel*, so that the API can
    #: hand an audited actor, role and correlation id to the assessment
    #: service without the application layer learning what HTTP is. Listed on
    #: its own because it belongs to no scientific work package - a CLI, a
    #: queue consumer and an HTTP request all need it equally.
    TRANSPORT_MODULES = ("execution_context.py",)

    #: WP-18. A schema module and a CLI, on the split every work package since
    #: WP-11 has used: the validation *logic* - roles, fingerprints,
    #: separation, access, the import boundary - lives in ``pgx/validation``,
    #: and the application layer holds only the published schemas and the
    #: command that writes the artifacts. Neither computes a metric; WP-21
    #: owns those, and a boundary test in tests/unit/validation fails the
    #: build if a quotient appears anywhere in the package.
    VALIDATION_MODULES = ("validation_cli.py", "validation_schema.py")

    #: WP-19. Same shape and the same reason: the verification system lives in
    #: ``pgx/verification`` and the application layer holds only its published
    #: schemas and the command that drives it. Neither runs a test - the CLI
    #: starts a subprocess and reads its report - so neither belongs any
    #: deeper than here.
    VERIFICATION_MODULES = ("verification_cli.py", "verification_schema.py")

    #: WP-20, on the same terms as WP-19: the published safety schemas and
    #: the command that drives the gate. The registry, the detectors and the
    #: negative controls live in ``pgx/safety``; neither module here decides
    #: whether an invariant holds.
    SAFETY_MODULES = ("safety_cli.py", "safety_schema.py")

    #: WP-21, on the same terms: the published benchmark schemas and the
    #: command that drives them. The metric registry, the engine and the
    #: public report live in ``pgx/validation``, next to the partition a
    #: metric may not violate.
    BENCHMARK_MODULES = ("benchmark_cli.py", "benchmark_schema.py")

    #: WP-22, on the same terms: the published review schemas and the command
    #: that drives them. The protocol, the state machine, the blinding
    #: structure and the audit chain live in ``pgx/expert_review``; neither
    #: module here can approve a protocol or reveal a result.
    EXPERT_REVIEW_MODULES = ("expert_review_cli.py", "expert_review_schema.py")

    #: WP-23, on the same terms: the published security schemas and the three
    #: commands that drive them. The password policy, the session model, the
    #: RBAC registry and the audit chain live in ``pgx/security`` and
    #: ``pgx/infrastructure/audit``; none of the modules here can hash a
    #: password, create a session or append an audit event.
    SECURITY_MODULES = ("auth_cli.py", "audit_cli.py", "security_cli.py",
                        "security_schema.py")

    #: WP-24, on the same terms again: the deployment command and its
    #: published schemas. The composition, the container inspection, the
    #: harnesses and the gate live in ``pgx/deployment``; neither module here
    #: opens a database session, builds an image or measures anything.
    DEPLOYMENT_MODULES = ("deploy_cli.py", "deployment_schema.py")

    #: WP-25, on the same terms once more: the evidence-pack command and its
    #: twenty published schemas. The registries, the gate matrix, the
    #: Definition of Done evaluation and the pack integrity check live in
    #: ``pgx/ths6``; neither module here approves, signs or executes
    #: anything, and neither can - there is no code path in the package that
    #: could.
    THS6_MODULES = ("ths6_cli.py", "ths6_schema.py")

    def _imports_of(self, relative: str):
        tree = ast.parse(_source(os.path.join(REPO_ROOT, relative)))
        modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module)
        return modules

    def test_no_release_module_imports_ingestion(self):
        """A release must not depend on how its data was acquired."""
        for name in self.RELEASE_MODULES:
            with self.subTest(module=name):
                for module in self._imports_of(
                        os.path.join("pgx", "application", name)):
                    self.assertFalse(module.startswith("pgx.ingestion"),
                                     "%s imports %s" % (name, module))

    def test_no_ingestion_module_imports_the_release_service(self):
        """Acquisition must not be able to activate anything."""
        for root, _dirs, files in os.walk(os.path.join(REPO_ROOT, "pgx",
                                                       "ingestion")):
            if "__pycache__" in root:
                continue
            for name in files:
                if not name.endswith(".py"):
                    continue
                relative = os.path.relpath(os.path.join(root, name), REPO_ROOT)
                with self.subTest(module=relative):
                    for module in self._imports_of(relative):
                        self.assertNotIn("release_service", module)
                        self.assertNotIn("release_cli", module)

    def test_ingestion_never_creates_a_scientific_record(self):
        """Evidence, interpretations and rules are WP-08 to WP-11.

        ``DatasetVersion`` left this list when WP-06 landed: a snapshot is
        built *for* a dataset build and names one, which is a lifecycle fact
        rather than a scientific record. Constructing one is still the
        application layer's job, and the check below reads identifiers rather
        than prose so a module that merely mentions the type in a docstring is
        not mistaken for one that builds it.
        """
        forbidden = ("CuratedInterpretation", "ComputableRule", "EvidenceRecord",
                     "RulesetVersion", "ReleaseBundle", "Assessment")
        for root, _dirs, files in os.walk(os.path.join(REPO_ROOT, "pgx",
                                                       "ingestion")):
            if "__pycache__" in root:
                continue
            for name in files:
                if not name.endswith(".py"):
                    continue
                relative = os.path.relpath(os.path.join(root, name), REPO_ROOT)
                identifiers = self._identifiers_of(relative)
                for token in forbidden:
                    with self.subTest(module=relative, token=token):
                        self.assertNotIn(token, identifiers)

    def test_ingestion_constructs_no_dataset_version(self):
        """Naming a dataset is WP-06; creating the row is the service's job."""
        for root, _dirs, files in os.walk(os.path.join(REPO_ROOT, "pgx",
                                                       "ingestion")):
            if "__pycache__" in root:
                continue
            for name in files:
                if not name.endswith(".py"):
                    continue
                relative = os.path.relpath(os.path.join(root, name), REPO_ROOT)
                with self.subTest(module=relative):
                    self.assertNotIn("DatasetVersion",
                                     self._identifiers_of(relative))

    def _identifiers_of(self, relative: str):
        """Names a module uses, with docstrings and comments excluded."""
        tree = ast.parse(_source(os.path.join(REPO_ROOT, relative)))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                names.add(node.name)
            elif isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                names.add(node.attr)
            elif isinstance(node, ast.alias):
                names.add(node.asname or node.name)
        return names

    def test_ingestion_needs_no_database(self):
        for root, _dirs, files in os.walk(os.path.join(REPO_ROOT, "pgx",
                                                       "ingestion")):
            if "__pycache__" in root:
                continue
            for name in files:
                if not name.endswith(".py"):
                    continue
                relative = os.path.relpath(os.path.join(root, name), REPO_ROOT)
                with self.subTest(module=relative):
                    for module in self._imports_of(relative):
                        self.assertNotEqual(module.split(".")[0], "sqlalchemy")

    def test_the_release_service_still_imports_no_infrastructure(self):
        """The WP-03 guarantee, re-asserted after WP-04 landed."""
        for module in self._imports_of(
                os.path.join("pgx", "application", "release_service.py")):
            self.assertFalse(module.startswith("pgx.infrastructure"))

    def test_the_application_layer_holds_only_release_and_ingestion_modules(self):
        directory = os.path.join(REPO_ROOT, "pgx", "application")
        modules = sorted(name for name in os.listdir(directory)
                         if name.endswith(".py"))
        self.assertEqual(
            modules,
            sorted(("__init__.py",) + self.RELEASE_MODULES
                   + self.INGESTION_MODULES + self.SCIENTIFIC_MODULES
                   + self.SNAPSHOT_MODULES + self.CANONICALIZATION_MODULES
                   + self.EVIDENCE_MODULES + self.CURATION_MODULES
                   + self.RULES_MODULES + self.ENGINE_MODULES
                   + self.COVERAGE_MODULES + self.ASSESSMENT_MODULES
                   + self.REPORT_MODULES + self.TRANSPORT_MODULES
                   + self.VALIDATION_MODULES + self.VERIFICATION_MODULES
                   + self.SAFETY_MODULES + self.BENCHMARK_MODULES
                   + self.EXPERT_REVIEW_MODULES + self.SECURITY_MODULES
                   + self.DEPLOYMENT_MODULES + self.THS6_MODULES))


class TestNoWp05OrWp06SurfaceWasStarted(unittest.TestCase):
    """The next boundary. WP-04 acquires; it does not approve or publish."""

    #: ``pgx/curation`` left this list when WP-09 created it. What it stood
    #: for - the release registry knows nothing about scientific curation - is
    #: checked by the import-direction test below.
    #: ``pgx/reporting`` left this list when WP-15 created it, on the same
    #: terms ``pgx/curation`` left it at WP-09: the package now exists because
    #: a work package built it, and what the entry stood for - that no layer
    #: renders anything to a person yet - is asserted directly by WP-15's own
    #: boundary tests instead of by the absence of a directory.
    FORBIDDEN_PACKAGES = ("pgx/api", "pgx/web", "pgx/assessment")

    def test_no_later_work_package_package_exists(self):
        for relative in self.FORBIDDEN_PACKAGES:
            with self.subTest(package=relative):
                self.assertFalse(os.path.isdir(os.path.join(REPO_ROOT, relative)))

    #: Modules exempt from the rule below, because curation is what they are
    #: *for*. Named explicitly rather than matched on the filename: WP-11's
    #: rule modules legitimately read the curation vocabulary and would not
    #: have matched a substring test, and a boundary whose exemptions are
    #: implicit is a boundary that erodes by naming.
    CURATION_AWARE_MODULES = (
        TestReleaseAndIngestionStaySeparate.CURATION_MODULES
        + TestReleaseAndIngestionStaySeparate.RULES_MODULES
        + TestReleaseAndIngestionStaySeparate.ENGINE_MODULES
        + TestReleaseAndIngestionStaySeparate.COVERAGE_MODULES
        + TestReleaseAndIngestionStaySeparate.ASSESSMENT_MODULES
        + TestReleaseAndIngestionStaySeparate.REPORT_MODULES)

    def test_no_release_module_imports_the_curation_or_rules_layer(self):
        """A release bundles what was approved; it does not curate or rule.

        WP-09 defines how a human reaches a conclusion and WP-11 defines what
        may be executed once one has. The release registry must import
        neither, or deciding what to publish would become entangled with
        deciding what is true.

        WP-11's own modules are exempt from the curation half by name: a rule
        pins the exact curated revision it descends from, so ``pgx.rules``
        depending on ``pgx.curation`` is the dependency running in the correct
        direction. Nothing is exempt from the rules half except the rule
        modules themselves.
        """
        directory = os.path.join(REPO_ROOT, "pgx", "application")
        for name in sorted(os.listdir(directory)):
            if not name.endswith(".py"):
                continue
            relative = os.path.join("pgx", "application", name)
            tree = ast.parse(_source(os.path.join(REPO_ROOT, relative)))
            imported = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module)
            forbidden = ["pgx.rules"]
            if name not in self.CURATION_AWARE_MODULES:
                forbidden.append("pgx.curation")
            if name in (TestReleaseAndIngestionStaySeparate.RULES_MODULES
                        + TestReleaseAndIngestionStaySeparate.ENGINE_MODULES
                        + TestReleaseAndIngestionStaySeparate.COVERAGE_MODULES
                        + TestReleaseAndIngestionStaySeparate.ASSESSMENT_MODULES
                        + TestReleaseAndIngestionStaySeparate.REPORT_MODULES):
                # WP-12 consumes WP-11's condition types directly rather than
                # redefining them, and WP-13 consumes WP-11's frozen ruleset
                # registry for the same reason: a coverage claim is a claim
                # about a specific frozen ruleset, so it must read the real
                # one rather than a copy of its shape. WP-15's gate status
                # reads it for a third: "how many frozen rulesets exist" is a
                # count it must not assert, so it counts the real ones. All
                # three are the dependency running in the correct direction.
                forbidden.remove("pgx.rules")
            with self.subTest(module=relative):
                for module in imported:
                    for prefix in forbidden:
                        self.assertFalse(module.startswith(prefix),
                                         "%s imports %s" % (relative, module))

    def test_no_migration_creates_an_ingestion_or_snapshot_table(self):
        """Persisting acquisitions is WP-06 and WP-08."""
        directory = os.path.join(REPO_ROOT, "migrations", "versions")
        created = []
        for name in sorted(os.listdir(directory)):
            if not name.endswith(".py"):
                continue
            tree = ast.parse(_source(os.path.join(directory, name)))
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call)
                        and getattr(node.func, "attr", None) == "create_table"
                        and node.args):
                    created.append(node.args[0].value)
        # WP-05 added source-policy tables and WP-06 added snapshot tables, so
        # neither set is forbidden any more. What is still ahead is WP-07's
        # canonical and data-quality storage, and WP-08's evidence migration: a
        # table for those appearing now would mean a work package started early.
        for forbidden in ("canonical_genes", "canonical_drugs",
                          "resolution_queue", "dq_reports",
                          "evidence_migrations", "ingestion_runs"):
            self.assertNotIn(forbidden, created)

    WP06_TABLES = ("raw_snapshots", "raw_artifacts")

    def test_the_snapshot_tables_belong_to_the_wp06_migration_alone(self):
        """0001 to 0003 are untouched: 0004 adds, it does not rewrite."""
        directory = os.path.join(REPO_ROOT, "migrations", "versions")
        owners = {}
        for name in sorted(os.listdir(directory)):
            if not name.endswith(".py"):
                continue
            tree = ast.parse(_source(os.path.join(directory, name)))
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call)
                        and getattr(node.func, "attr", None) == "create_table"
                        and node.args):
                    owners.setdefault(node.args[0].value, name)
        for table in self.WP06_TABLES:
            with self.subTest(table=table):
                self.assertEqual(owners.get(table), "0004_wp06_raw_snapshots.py")

    WP05_TABLES = ("source_policies", "source_policy_evidence",
                   "source_policy_reviews", "source_conflicts",
                   "dataset_publication_evaluations")

    def test_the_source_policy_tables_belong_to_the_wp05_migration_alone(self):
        """0001 and 0002 are untouched: 0003 adds, it does not rewrite."""
        directory = os.path.join(REPO_ROOT, "migrations", "versions")
        owners = {}
        for name in sorted(os.listdir(directory)):
            if not name.endswith(".py"):
                continue
            tree = ast.parse(_source(os.path.join(directory, name)))
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call)
                        and getattr(node.func, "attr", None) == "create_table"
                        and node.args):
                    owners.setdefault(node.args[0].value, name)
        for table in self.WP05_TABLES:
            with self.subTest(table=table):
                self.assertEqual(owners.get(table), "0003_wp05_source_policy.py")

    def test_nothing_asserts_source_licensing_approval(self):
        """Deciding a source may back a release is WP-05."""
        for root, _dirs, files in os.walk(os.path.join(REPO_ROOT, "pgx",
                                                       "ingestion")):
            if "__pycache__" in root:
                continue
            for name in files:
                if not name.endswith(".py"):
                    continue
                source = _source(os.path.join(root, name))
                with self.subTest(module=name):
                    for token in ("release_eligible = True",
                                  "license_approved", "approve_source"):
                        self.assertNotIn(token, source)

    def test_ingestion_publishes_no_dataset(self):
        for root, _dirs, files in os.walk(os.path.join(REPO_ROOT, "pgx",
                                                       "ingestion")):
            if "__pycache__" in root:
                continue
            for name in files:
                if not name.endswith(".py"):
                    continue
                source = _source(os.path.join(root, name))
                with self.subTest(module=name):
                    # DatasetPublicId left this list when WP-06 landed: a
                    # snapshot directory is named by an explicit dataset ID, and
                    # naming one is not publishing one.
                    for token in ("PUBLISHED", "publish_dataset",
                                  "QUALITY_CHECKED", "approved_by"):
                        self.assertNotIn(token, source)

    def test_the_acquisition_manifest_states_its_own_scope(self):
        """A reader must not mistake acquisition for validation."""
        from pgx.ingestion.common.manifest import AcquisitionManifest
        import inspect as _inspect

        source = _inspect.getsource(AcquisitionManifest)
        self.assertIn("scope_note", source)
        self.assertIn("asserts scientific validity", source)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
