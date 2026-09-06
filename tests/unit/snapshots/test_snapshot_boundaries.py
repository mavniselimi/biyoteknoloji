# -*- coding: utf-8 -*-
"""Layer boundaries WP-06 must not cross.

The one most likely to erode is the WP-07 boundary. A snapshot is *raw bytes*:
the moment something here resolves a gene symbol, merges two records or scores
data quality, WP-06 has started doing WP-07's job and the raw layer stops being
raw. Every check below reads the AST, so nothing needs installing.
"""

from __future__ import annotations

import ast
import io
import os
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

WP06_MODULES = (
    os.path.join("pgx", "ingestion", "snapshots.py"),
    os.path.join("pgx", "ingestion", "common", "manifest_io.py"),
    os.path.join("pgx", "application", "dataset_service.py"),
    os.path.join("pgx", "application", "dataset_cli.py"),
    os.path.join("pgx", "application", "snapshot_schema.py"),
)


def _source(relative: str) -> str:
    with io.open(os.path.join(REPO_ROOT, relative), encoding="utf-8") as handle:
        return handle.read()


def _imports(relative: str):
    tree = ast.parse(_source(relative), filename=relative)
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def _identifiers(relative: str):
    """Names the module actually uses; docstrings and comments excluded."""
    tree = ast.parse(_source(relative), filename=relative)
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
    return names


class TestEveryWp06ModuleExists(unittest.TestCase):

    def test_they_are_all_present(self):
        for relative in WP06_MODULES:
            with self.subTest(module=relative):
                self.assertTrue(os.path.isfile(os.path.join(REPO_ROOT, relative)))


class TestNoNetworkAndNoOrm(unittest.TestCase):

    def test_no_module_can_reach_the_network(self):
        for relative in WP06_MODULES:
            for module in _imports(relative):
                with self.subTest(module=relative, imported=module):
                    self.assertNotIn(module.split(".")[0],
                                     ("urllib", "http", "socket", "ssl",
                                      "requests", "httpx", "ftplib"))

    def test_the_snapshot_package_imports_no_orm(self):
        for relative in WP06_MODULES:
            for module in _imports(relative):
                with self.subTest(module=relative, imported=module):
                    self.assertNotEqual(module.split(".")[0], "sqlalchemy")
                    self.assertFalse(module.startswith("pgx.infrastructure"))

    def test_the_ingestion_half_does_not_import_the_application_half(self):
        """Reading a schema file is an application concern, injected not imported."""
        for relative in WP06_MODULES[:2]:
            for module in _imports(relative):
                with self.subTest(module=relative, imported=module):
                    self.assertFalse(module.startswith("pgx.application"))

    def test_the_domain_does_not_import_the_snapshot_package(self):
        domain = os.path.join(REPO_ROOT, "pgx", "domain")
        for name in sorted(os.listdir(domain)):
            if not name.endswith(".py"):
                continue
            for module in _imports(os.path.join("pgx", "domain", name)):
                with self.subTest(module=name, imported=module):
                    self.assertFalse(module.startswith("pgx.ingestion"))


class TestNoWp07LogicWasIntroduced(unittest.TestCase):
    """WP-06 captures bytes. It resolves, merges and judges nothing."""

    FORBIDDEN = (
        "resolve_gene", "resolve_drug", "canonicalize", "canonicalise",
        "normalize_symbol", "normalise_symbol", "deduplicate", "dedupe",
        "merge_records", "alias_lookup", "quality_report", "dq_report",
        "attention_level", "risk_level", "AttentionLevel", "Phenotype",
        "EvidenceRecord", "CuratedInterpretation", "ComputableRule",
    )

    def test_no_wp06_module_names_a_wp07_or_later_concept(self):
        for relative in WP06_MODULES:
            identifiers = _identifiers(relative)
            for token in self.FORBIDDEN:
                with self.subTest(module=relative, token=token):
                    self.assertNotIn(token, identifiers)

    def test_no_wp07_package_exists_yet(self):
        """The packages that genuinely have not started.

        ``pgx/normalization`` is no longer among them: WP-07 created it, and
        asserting its absence would only record that this file is older than
        the code it guards. The rule that assertion stood for - WP-06 captures
        bytes and knows nothing about what they mean - is checked by
        :meth:`test_no_wp06_module_names_a_wp07_or_later_concept` above and by
        :meth:`test_no_snapshot_module_imports_the_canonicalization_layer`
        below, both of which keep working as WP-07 grows.
        """
        # ``pgx/curation`` left this list when WP-09 created it, for the same
        # reason ``pgx/normalization`` left it when WP-07 did.
        for relative in ("pgx/assessment", "pgx/api"):
            with self.subTest(package=relative):
                self.assertFalse(os.path.isdir(os.path.join(REPO_ROOT, relative)))

    def test_no_snapshot_module_imports_the_canonicalization_layer(self):
        """WP-07 reads snapshots. A snapshot must not read WP-07.

        The dependency runs one way: ``pgx.normalization`` imports
        ``pgx.ingestion.snapshots`` to locate artifacts, and nothing in the
        snapshot layer may import back. A cycle here would mean a snapshot
        could not be verified without the canonicalization package, which is
        exactly the coupling that makes raw evidence stop being raw.
        """
        for relative in WP06_MODULES:
            for module in _imports(relative):
                with self.subTest(module=relative, imported=module):
                    self.assertFalse(module.startswith("pgx.normalization"))

    def test_the_canonicalization_layer_owns_no_snapshot_writing(self):
        """WP-07 may read a snapshot. It may never create or seal one.

        ``SnapshotManager`` is imported by the builder to *inspect* a sealed
        directory. If a canonicalization module ever called ``build``,
        ``_write_staging`` or ``_materialise``, a canonical build could quietly
        produce the raw evidence it claims to be derived from.
        """
        normalization = os.path.join(REPO_ROOT, "pgx", "normalization")
        forbidden = ("SnapshotBuildRequest", "render_checksums",
                     "_write_staging", "_materialise", "_make_read_only")
        for name in sorted(os.listdir(normalization)):
            if not name.endswith(".py"):
                continue
            identifiers = _identifiers(os.path.join("pgx", "normalization", name))
            for token in forbidden:
                with self.subTest(module=name, token=token):
                    self.assertNotIn(token, identifiers)

    #: The only functions in the snapshot module allowed to parse JSON. Each
    #: reads a *manifest* back; none of them touches a response body.
    MANIFEST_READERS = ("verify_path", "inspect_path", "from_payload")

    def test_json_is_parsed_only_where_a_manifest_is_read(self):
        """Reserialising a body would change key order and break its hash."""
        tree = ast.parse(_source(WP06_MODULES[0]), filename=WP06_MODULES[0])
        for function in ast.walk(tree):
            if not isinstance(function, ast.FunctionDef):
                continue
            for node in ast.walk(function):
                if (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr in ("loads", "load")
                        and getattr(node.func.value, "id", None) == "json"):
                    with self.subTest(function=function.name):
                        self.assertIn(function.name, self.MANIFEST_READERS)

    def test_the_copy_path_never_decodes_a_response_body(self):
        """``_read_blob`` and ``_write_bytes`` move bytes and nothing else."""
        tree = ast.parse(_source(WP06_MODULES[0]), filename=WP06_MODULES[0])
        for function in ast.walk(tree):
            if not isinstance(function, ast.FunctionDef):
                continue
            if function.name not in ("_read_blob", "_write_bytes",
                                     "_plan_acquisition", "_plan_legacy"):
                continue
            names = {node.attr for node in ast.walk(function)
                     if isinstance(node, ast.Attribute)}
            for forbidden in ("loads", "dumps", "decode", "encode"):
                with self.subTest(function=function.name, call=forbidden):
                    self.assertNotIn(forbidden, names)

    def test_the_snapshot_module_writes_bytes_not_serialised_objects(self):
        source = _source(WP06_MODULES[0])
        self.assertIn("def _write_bytes(", source)
        self.assertNotIn("json.dump(", source)


class TestTheApplicationLayerInventory(unittest.TestCase):
    """Every application module, listed so a new one is added deliberately.

    WP-06 added three; WP-07 added ``normalize_cli.py``,
    ``canonical_schema.py`` and ``canonical_service.py``. The canonicalization
    logic itself lives in ``pgx/normalization``; the application layer drives
    it, applies the published schemas, and holds the one audited state
    transition.

    WP-10 added ``curation_workflow_cli.py`` and
    ``curation_workflow_schema.py``: the offline entry point to the curation
    workflow, and the loader for its five published schemas. The workflow
    itself - the state machine, the gates and the service - lives in
    ``pgx/curation/workflow``, so this layer gained a driver and a schema
    loader, not a second home for the rules.

    WP-12 added two: ``phenotype_cli.py`` and ``phenotype_schema.py``. There is
    no phenotype *service*, and that is the tell for what WP-12 is: a service
    in this layer is where an audited state transition would go, and matching a
    phenotype changes no state at all.

    WP-13 added three: ``coverage_cli.py``, ``coverage_schema.py``, and
    ``coverage_gate_status.py``, which reports why no real coverage claim may
    exist yet. No coverage *service* either, for WP-12's reason - asking what
    a ruleset could evaluate transitions nothing.

    WP-14 added five, and one of them *is* a service: executing an assessment
    writes an immutable record and an audit event atomically, which is exactly
    the audited state transition the earlier three lacked.

    WP-11 added five: ``rule_service.py`` and ``ruleset_service.py`` (the two
    lifecycles this layer drives), ``rules_cli.py``, ``rules_schema.py``, and
    ``rule_gate_status.py``, which reads real repository state and reports why
    no real rule may exist yet. The condition language, the validator, the
    conflict detector and the builder all live in ``pgx/rules``: the same
    split, one work package later.

    WP-16 added one, and it is neither a service nor a CLI:
    ``execution_context.py`` is a value type describing *who asked and over
    what channel*, so that an HTTP request can hand an audited actor, role and
    correlation id to the assessment service without this layer learning what
    HTTP is. It belongs to no scientific work package, because a CLI, a queue
    consumer and an API request all need it equally.
    """

    EXPECTED = (
        "__init__.py", "assessment_cli.py", "assessment_gate_status.py",
        "assessment_models.py", "assessment_read_model.py",
        "assessment_schema.py", "assessment_service.py",
        "assessment_snapshot.py",
        # WP-23: the audit and account commands, on the same terms as WP-19
        # through WP-22. Password hashing, sessions, the RBAC registry and
        # the audit chain live in pgx/security and pgx/infrastructure/audit;
        # no module here can hash a password, authenticate anybody or append
        # an audit event.
        "audit_cli.py", "auth_cli.py",
        # WP-21: the benchmark command and its published schemas, on the same
        # terms as WP-19 and WP-20. pgx/validation holds the metric registry
        # and the engine; neither module here decides whether a metric has a
        # value.
        "benchmark_cli.py", "benchmark_schema.py",
        "canonical_schema.py", "canonical_service.py",
        "coverage_cli.py", "coverage_gate_status.py", "coverage_schema.py",
        "curation_protocol_cli.py", "curation_schema.py",
        "curation_workflow_cli.py", "curation_workflow_schema.py",
        "dataset_cli.py", "dataset_service.py",
        # WP-24: the deployment command and its seventeen published schemas.
        # The composition, the container inspection and the harnesses live in
        # pgx/deployment; neither module here opens a database session,
        # builds an image or measures anything.
        "deploy_cli.py", "deployment_schema.py",
        "evidence_cli.py",
        "evidence_schema.py", "execution_context.py",
        # WP-22: the expert-review command and its published schemas, on the
        # same terms as WP-19, WP-20 and WP-21. The protocol, the state
        # machine and the blinding structure live in pgx/expert_review;
        # neither module here can approve a protocol or reveal a result.
        "expert_review_cli.py", "expert_review_schema.py",
        "ingestion_cli.py",
        "ingestion_service.py",
        "legacy_baseline.py", "normalize_cli.py",
        "phenotype_cli.py", "phenotype_schema.py",
        # WP-C06: joins a recorded dataset quality decision to the WP-07
        # transition an approval causes. Listed here deliberately, which is
        # what this inventory is for.
        "quality_decision_service.py", "release_cli.py",
        "release_schema.py", "release_service.py", "report_cli.py",
        "report_gate_status.py", "report_schema.py", "report_service.py",
        "rule_gate_status.py",
        "rule_service.py", "rules_cli.py", "rules_schema.py",
        "ruleset_service.py",
        # WP-20: the safety gate command and its published schemas, on the
        # same terms as WP-19. pgx/safety holds the registry, the detectors
        # and the negative-control wiring, and imports nothing from the
        # snapshot layer - nor from tests, which is asserted separately in
        # tests/unit/safety/test_boundaries.py.
        "safety_cli.py", "safety_schema.py",
        # WP-23: the security command and its nine published schemas.
        "security_cli.py", "security_schema.py",
        "snapshot_schema.py",
        "source_policy_cli.py",
        # WP-25: the evidence-pack command and its twenty published schemas.
        # The registries, the gate matrix, the Definition of Done evaluation
        # and the pack integrity check live in pgx/ths6; neither module here
        # approves, signs or executes anything.
        "ths6_cli.py", "ths6_schema.py",
        # WP-18: the published validation schemas and the artifact command.
        # The partition logic itself lives in pgx/validation.
        "validation_cli.py", "validation_schema.py",
        # WP-19: the verification command and its published schemas. The
        # verification system itself is in pgx/verification, which imports
        # nothing from the snapshot layer.
        "verification_cli.py", "verification_schema.py",
    )

    def test_the_application_layer_holds_exactly_these_modules(self):
        directory = os.path.join(REPO_ROOT, "pgx", "application")
        actual = tuple(sorted(name for name in os.listdir(directory)
                              if name.endswith(".py")))
        self.assertEqual(actual, self.EXPECTED)


class TestTheSnapshotApiExposesNoWrite(unittest.TestCase):

    def test_the_public_surface_offers_no_mutation_of_a_sealed_snapshot(self):
        from pgx.ingestion import snapshots
        for name in snapshots.__all__:
            attribute = getattr(snapshots, name)
            if not isinstance(attribute, type):
                continue
            for forbidden in ("write", "update", "append", "delete", "remove",
                              "reopen", "overwrite", "seal_again"):
                with self.subTest(name=name, method=forbidden):
                    self.assertFalse(hasattr(attribute, forbidden))

    def test_the_manifest_is_immutable(self):
        from pgx.ingestion.snapshots import SnapshotManifest
        import dataclasses
        self.assertTrue(dataclasses.is_dataclass(SnapshotManifest))
        self.assertTrue(SnapshotManifest.__dataclass_params__.frozen)

    def test_artifact_descriptors_are_immutable(self):
        from pgx.ingestion.snapshots import RawArtifactDescriptor
        self.assertTrue(RawArtifactDescriptor.__dataclass_params__.frozen)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
