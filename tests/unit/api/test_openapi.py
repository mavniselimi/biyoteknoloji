# -*- coding: utf-8 -*-
"""J. The OpenAPI artifact and the route surface.

The document is generated from the same declarations the routers register
from, so what is checked here is that the declarations cover the required
surface, that the generation is deterministic, that the committed artifact
matches it byte for byte, and that the artifact is honest about not having
been verified against a running application.
"""

from __future__ import annotations

import ast
import io
import json
import os
import re
import unittest

from apps.api import API_ROOT_PATH
from apps.api.contracts.spec import MODELS
from apps.api.errors import ERROR_CATALOGUE
from apps.api.openapi import (OPENAPI_VERSION, RUNTIME_VERIFICATION_BLOCKED,
                              build_document, canonical_json,
                              compare_documents, runtime_verification_status)
from apps.api.routes import ROUTES, ROUTES_BY_OPERATION
from tests.unit.api._support import (API_DIR, REPO_ROOT, module_path,
                                     route_decorators, source, tree)

ARTIFACT = os.path.join(REPO_ROOT, "schemas", "openapi", "wp16-openapi.json")

#: §7's surface, exactly.
REQUIRED_ROUTES = (
    ("POST", API_ROOT_PATH + "/assessments"),
    ("GET", API_ROOT_PATH + "/assessments/{assessment_id}"),
    ("GET", API_ROOT_PATH + "/drugs"),
    ("GET", API_ROOT_PATH + "/genes"),
    ("GET", API_ROOT_PATH + "/evidence/{evidence_id}"),
    ("GET", API_ROOT_PATH + "/system/version"),
    # WP-22 made the three stubs real and added three more operations the
    # workflow needs: list your assignments, read one's state, append a
    # correction.
    ("GET", API_ROOT_PATH + "/expert-reviews"),
    ("GET", API_ROOT_PATH + "/expert-reviews/{case_id}"),
    ("POST", API_ROOT_PATH + "/expert-reviews/{case_id}/expected"),
    ("POST", API_ROOT_PATH + "/expert-reviews/{case_id}/reveal"),
    ("POST", API_ROOT_PATH + "/expert-reviews/{case_id}/complete"),
    ("POST", API_ROOT_PATH + "/expert-reviews/{case_id}/corrections"),
    ("GET", "/health/live"),
    ("GET", "/health/ready"),
)


class TestTheDeclaredSurface(unittest.TestCase):

    def test_it_is_exactly_the_required_surface(self):
        declared = tuple((route.method, route.path) for route in ROUTES)
        self.assertEqual(sorted(declared), sorted(REQUIRED_ROUTES))

    def test_operation_ids_are_unique_and_stable(self):
        ids = [route.operation_id for route in ROUTES]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(sorted(ids), sorted(ROUTES_BY_OPERATION))

    def test_no_unrelated_administrative_endpoint_exists(self):
        for route in ROUTES:
            with self.subTest(operation=route.operation_id):
                for forbidden in ("/admin", "/debug", "/internal", "/metrics",
                                  "/shell", "/sql"):
                    self.assertNotIn(forbidden, route.path)

    def test_no_report_endpoint_exists(self):
        for route in ROUTES:
            with self.subTest(operation=route.operation_id):
                self.assertNotIn("report", route.path)

    def test_every_route_declares_bounded_parameters(self):
        for route in ROUTES:
            for parameter in route.parameters:
                with self.subTest(operation=route.operation_id,
                                  parameter=parameter.name):
                    if parameter.kind == "string":
                        self.assertIsNotNone(parameter.pattern)
                    else:
                        self.assertIsNotNone(parameter.minimum)
                        self.assertIsNotNone(parameter.maximum)


class TestRoutersMatchTheDeclaration(unittest.TestCase):
    """The routers cannot be imported here, so they are read.

    This is the check that keeps the framework-bound half honest: a router
    that registered an extra path, a different method or a hand-written path
    string would fail, and every registration must go through the route table.
    """

    ROUTER_MODULES = ("assessments", "catalogue", "evidence",
                      "expert_review", "health", "system")

    def _registered(self):
        found = []
        for name in self.ROUTER_MODULES:
            path = module_path(os.path.join("routers", name + ".py"))
            for decorator in route_decorators(path):
                found.append((name, decorator))
        return found

    def test_every_declared_route_is_registered_exactly_once(self):
        registered = self._registered()
        operation_ids = []
        for _module, decorator in registered:
            expression = decorator["keywords"].get("operation_id", "")
            match = re.match(r"^_([A-Z_]+)\.operation_id$", expression)
            self.assertIsNotNone(
                match, "operation id %r is not taken from the route table"
                % expression)
            operation_ids.append(expression)
        self.assertEqual(len(operation_ids), len(ROUTES))
        self.assertEqual(len(set((module, expression) for module, expression
                                 in zip([m for m, _ in registered],
                                        operation_ids))),
                         len(ROUTES))

    def test_no_router_writes_a_path_literal(self):
        """Paths come from the route table. A literal here would be a second
        place the surface is defined."""
        for name in self.ROUTER_MODULES:
            path = module_path(os.path.join("routers", name + ".py"))
            for decorator in route_decorators(path):
                with self.subTest(router=name, handler=decorator["handler"]):
                    self.assertIsNotNone(decorator["path_expression"])
                    self.assertRegex(decorator["path_expression"],
                                     r"^_[A-Z_]+\.path$")

    def test_every_router_takes_its_access_policy_from_the_table(self):
        for name in self.ROUTER_MODULES:
            path = module_path(os.path.join("routers", name + ".py"))
            text = source(path)
            with self.subTest(router=name):
                self.assertIn("require_access(", text)
                self.assertNotIn("roles(Role.", text)
                self.assertNotIn("AccessPolicy(", text)

    def test_every_router_addresses_the_table_by_operation_id(self):
        for name in self.ROUTER_MODULES:
            path = module_path(os.path.join("routers", name + ".py"))
            calls = [node for node in ast.walk(tree(path))
                     if isinstance(node, ast.Call)
                     and isinstance(node.func, ast.Name)
                     and node.func.id == "operation"]
            with self.subTest(router=name):
                self.assertTrue(calls)
                for call in calls:
                    self.assertTrue(call.args)
                    self.assertIsInstance(call.args[0], ast.Constant)
                    self.assertIn(call.args[0].value, ROUTES_BY_OPERATION)


class TestTheGeneratedDocument(unittest.TestCase):

    def setUp(self):
        self.document = build_document()

    def test_it_declares_openapi_three_one(self):
        self.assertEqual(self.document["openapi"], OPENAPI_VERSION)
        self.assertTrue(OPENAPI_VERSION.startswith("3.1"))

    def test_the_title_and_version_are_stable(self):
        self.assertEqual(self.document["info"]["title"],
                         "PGx Platform V2 API")
        self.assertEqual(self.document["info"]["version"], "1.0.0")

    def test_every_declared_operation_appears(self):
        found = {operation["operationId"]
                 for path in self.document["paths"].values()
                 for operation in path.values()}
        self.assertEqual(found, set(ROUTES_BY_OPERATION))

    def test_every_contract_model_is_a_schema(self):
        self.assertEqual(set(self.document["components"]["schemas"]),
                         set(MODELS))

    def test_every_reference_resolves(self):
        blob = json.dumps(self.document)
        referenced = set(re.findall(r"#/components/schemas/([A-Za-z]+)", blob))
        self.assertEqual(
            referenced - set(self.document["components"]["schemas"]), set())

    def test_no_schema_is_unreachable(self):
        blob = json.dumps(self.document["paths"])
        reachable, frontier = set(), list(
            re.findall(r"#/components/schemas/([A-Za-z]+)", blob))
        schemas = self.document["components"]["schemas"]
        while frontier:
            name = frontier.pop()
            if name in reachable:
                continue
            reachable.add(name)
            frontier.extend(re.findall(r"#/components/schemas/([A-Za-z]+)",
                                       json.dumps(schemas[name])))
        self.assertEqual(set(schemas) - reachable, set())

    def test_no_schema_accepts_extra_properties(self):
        for name, schema in self.document["components"]["schemas"].items():
            with self.subTest(schema=name):
                self.assertIs(schema["additionalProperties"], False)

    def test_no_item_schema_uses_an_invalid_type(self):
        """The item generator once emitted ``{"type": "enum"}``, which told a
        client that a governed vocabulary was an unconstrained string."""
        blob = json.dumps(self.document)
        for invalid in ("enum", "uuid", "digest", "object_"):
            with self.subTest(type=invalid):
                self.assertNotIn('"type": "%s"' % invalid, blob)

    def test_every_operation_documents_the_error_envelope(self):
        for path, operations in self.document["paths"].items():
            for method, operation in operations.items():
                with self.subTest(operation=operation["operationId"]):
                    rendered = json.dumps(operation["responses"])
                    self.assertIn("ErrorEnvelope", rendered)

    def test_every_documented_error_code_exists_in_the_catalogue(self):
        blob = json.dumps(self.document)
        for code in re.findall(r'"code": "([A-Z_]+)"', blob):
            with self.subTest(code=code):
                self.assertIn(code, ERROR_CATALOGUE)

    def test_the_security_scheme_is_labelled_a_stub(self):
        scheme = self.document["components"]["securitySchemes"]["PgxPrincipal"]
        self.assertIs(scheme["x-pgx-implemented"], False)
        self.assertEqual(scheme["x-pgx-owned-by"], "WP-23")

    def test_authenticated_operations_declare_their_roles(self):
        for path, operations in self.document["paths"].items():
            for operation in operations.values():
                route = ROUTES_BY_OPERATION[operation["operationId"]]
                with self.subTest(operation=operation["operationId"]):
                    if route.access.public:
                        self.assertEqual(operation["security"], [])
                    else:
                        self.assertEqual(operation["security"],
                                         [{"PgxPrincipal": []}])
                        self.assertEqual(
                            tuple(operation["x-pgx-required-roles"]),
                            route.access.role_names)

    def test_disabled_operations_are_marked_and_attributed(self):
        for path, operations in self.document["paths"].items():
            for operation in operations.values():
                route = ROUTES_BY_OPERATION[operation["operationId"]]
                if route.implemented:
                    continue
                with self.subTest(operation=operation["operationId"]):
                    self.assertIs(operation["x-pgx-not-implemented"], True)
                    self.assertEqual(operation["x-pgx-superseded-by"], "WP-22")

    def test_no_example_looks_like_a_real_record(self):
        blob = json.dumps(self.document)
        # An email-shaped run rather than a bare "@": the gene-key pattern
        # legitimately contains one inside a character class, and a needle
        # that matched it would be a test failing on a regex.
        self.assertEqual(re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
                                    blob), [])
        for needle in ("patient", "Patient", "MRN", "1990-", "1985-",
                       "@example.com", "Bearer ey"):
            with self.subTest(needle=needle):
                self.assertNotIn(needle, blob)
        self.assertIn("synthetic", self.document["info"]["description"])

    def test_the_only_example_identifier_is_an_obvious_placeholder(self):
        blob = json.dumps(self.document)
        for identifier in re.findall(
                r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}"
                r"-[0-9a-f]{12}", blob):
            with self.subTest(identifier=identifier):
                self.assertEqual(set(identifier) - set("-"), {"0", "4", "8"})

    def test_no_user_interface_route_is_documented(self):
        for path in self.document["paths"]:
            with self.subTest(path=path):
                self.assertFalse(path.endswith(".html"))
                self.assertNotIn("/ui", path)
                self.assertNotIn("/app", path)


class TestDeterminismAndTheCommittedArtifact(unittest.TestCase):

    def test_generation_is_deterministic(self):
        self.assertEqual(canonical_json(build_document()),
                         canonical_json(build_document()))

    def test_the_committed_artifact_matches_the_generator(self):
        with io.open(ARTIFACT, encoding="utf-8") as handle:
            committed = handle.read()
        self.assertEqual(
            committed, canonical_json(build_document()),
            "schemas/openapi/wp16-openapi.json is stale; regenerate it")

    def test_the_committed_artifact_is_valid_json(self):
        with io.open(ARTIFACT, encoding="utf-8") as handle:
            json.load(handle)

    def test_the_artifact_records_that_runtime_verification_is_blocked(self):
        with io.open(ARTIFACT, encoding="utf-8") as handle:
            committed = json.load(handle)
        status = committed["x-pgx-runtime-verification"]
        self.assertEqual(status["status"], RUNTIME_VERIFICATION_BLOCKED)
        self.assertEqual(sorted(status["blocked_on"]),
                         ["fastapi", "pydantic"])

    def test_the_verification_status_is_never_claimed_by_default(self):
        self.assertEqual(runtime_verification_status(False)["status"],
                         RUNTIME_VERIFICATION_BLOCKED)
        self.assertEqual(runtime_verification_status(True)["status"],
                         "VERIFIED")

    def test_the_comparison_ignores_only_the_verification_status(self):
        identical, differences = compare_documents(
            build_document(runtime_verified=True), build_document())
        self.assertTrue(identical)
        self.assertEqual(differences, [])

    def test_the_comparison_detects_a_real_difference(self):
        altered = build_document()
        altered["paths"] = dict(altered["paths"])
        altered["paths"].pop(API_ROOT_PATH + "/drugs")
        identical, differences = compare_documents(altered, build_document())
        self.assertFalse(identical)
        self.assertTrue(differences)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class TestTheCommittedArtifacts(unittest.TestCase):
    """Every published WP-16 artifact is generated, not maintained by hand."""

    def setUp(self):
        from apps.api.artifacts import ARTIFACT_PATHS, build_artifacts
        self.paths = ARTIFACT_PATHS
        self.generated = build_artifacts()

    def test_the_declared_paths_are_exactly_what_is_generated(self):
        self.assertEqual(sorted(self.paths), sorted(self.generated))

    def test_every_artifact_is_committed_and_current(self):
        for relative in sorted(self.paths):
            path = os.path.join(REPO_ROOT, relative)
            with self.subTest(artifact=relative):
                self.assertTrue(os.path.isfile(path), "%s is missing" % relative)
                with io.open(path, encoding="utf-8") as handle:
                    self.assertEqual(
                        handle.read(), self.generated[relative],
                        "%s is stale; run python -m apps.api.artifacts"
                        % relative)

    def test_generation_is_deterministic(self):
        from apps.api.artifacts import build_artifacts
        self.assertEqual(build_artifacts(), self.generated)

    def test_every_artifact_is_valid_json(self):
        for relative, text in sorted(self.generated.items()):
            with self.subTest(artifact=relative):
                json.loads(text)

    def test_the_gate_status_reports_the_nine_questions_separately(self):
        document = json.loads(
            self.generated["data/api/wp16-real-gate-status.json"])
        for field in ("implementation_status", "api_dependencies_available",
                      "asgi_runtime_tests_executed",
                      "postgresql_runtime_available",
                      "claim_boundary_approved", "authentication_implemented",
                      "active_release_available", "real_assessment_count",
                      "real_api_assessment_count", "real_report_count",
                      "synthetic_fixture_count", "wp17_started", "blockers"):
            with self.subTest(field=field):
                self.assertIn(field, document)
        self.assertIn("runtime_verification", document["openapi"])

    def test_the_gate_status_claims_nothing_it_did_not_measure(self):
        document = json.loads(
            self.generated["data/api/wp16-real-gate-status.json"])
        self.assertFalse(document["may_serve_real_traffic"])
        self.assertEqual(document["real_assessment_count"], 0)
        self.assertEqual(document["real_api_assessment_count"], 0)
        self.assertIs(document["postgresql_runtime_available"], False)

        # Runtime execution is no longer pinned to False here, and pinning it
        # was the defect rather than the safeguard: the constant went on
        # saying "not executed" after the ASGI suite had been run and passed.
        # What survives is the property that made the constant look right -
        # the flag may never claim more than the evidence behind it - so the
        # two are compared instead.
        from apps.api.runtime_verification import (VERIFIED, load_evidence,
                                                   verified_runtime_status)

        recorded = verified_runtime_status(REPO_ROOT)
        self.assertIs(document["asgi_runtime_tests_executed"],
                      recorded["asgi_runtime_tests_executed"])
        self.assertIs(document["openapi"]["generated_from_running_application"],
                      recorded["openapi_runtime_verified"])
        if document["asgi_runtime_tests_executed"]:
            evidence = load_evidence(REPO_ROOT)
            self.assertIsNotNone(
                evidence, "the gate status reports executed runtime tests "
                          "with no evidence file behind it")
            self.assertTrue(evidence["verified"])
            self.assertEqual(document["asgi_runtime_test_status"], VERIFIED)
            self.assertEqual(document["openapi"]["runtime_verification"],
                             VERIFIED)
        else:
            self.assertNotEqual(document["asgi_runtime_test_status"], VERIFIED)
            self.assertNotEqual(document["openapi"]["runtime_verification"],
                                VERIFIED)
        for field in ("real_assessment_count_source",
                      "real_api_assessment_count_source",
                      "real_report_count_source",
                      "synthetic_fixture_count_source"):
            with self.subTest(field=field):
                self.assertTrue(document[field])

    def test_the_runtime_flag_is_never_derived_from_installed_packages(self):
        """The specific wrong repair, refused at the artifact level.

        Replacing the hard-coded ``False`` with dependency availability would
        have made this document say "executed" on any host with FastAPI
        installed. Where the two answers differ - packages present, nothing
        run - the flag must follow the evidence.
        """
        document = json.loads(
            self.generated["data/api/wp16-real-gate-status.json"])
        from apps.api.runtime_verification import load_evidence

        if document["api_dependencies_available"] and \
                load_evidence(REPO_ROOT) is None:
            self.assertFalse(
                document["asgi_runtime_tests_executed"],
                "installed dependencies were reported as executed tests")

    def test_the_wp17_flag_is_measured_rather_than_asserted(self):
        """It reported ``False`` while WP-16 was the current work package and
        reports ``True`` now that WP-17 has created ``apps/web``.

        That change is the flag working. What this asserts is the property
        that survives: the boolean agrees with the filesystem, so it can never
        be a constant somebody set. A test pinning it to ``False`` would have
        had to be deleted the moment the next package started, which is the
        opposite of what a gate status is for.
        """
        import os
        document = json.loads(
            self.generated["data/api/wp16-real-gate-status.json"])
        present = [relative for relative in document["wp17_markers_found"]
                   if os.path.isdir(os.path.join(REPO_ROOT, relative))]
        self.assertEqual(present, document["wp17_markers_found"])
        self.assertEqual(document["wp17_started"],
                         bool(document["wp17_markers_found"]))

    def test_the_published_contract_covers_every_model(self):
        contract = json.loads(
            self.generated["schemas/wp16/api-contract.schema.json"])
        self.assertEqual(set(contract["$defs"]), set(MODELS))

    def test_the_published_route_surface_matches_the_table(self):
        surface = json.loads(
            self.generated["schemas/wp16/route-surface.schema.json"])
        published = {entry["operation_id"] for entry
                     in surface["x-pgx-routes"]}
        self.assertEqual(published, set(ROUTES_BY_OPERATION))

    def test_the_published_error_contract_covers_every_code(self):
        contract = json.loads(
            self.generated["schemas/wp16/error-contract.schema.json"])
        self.assertEqual(set(contract["x-pgx-error-catalogue"]),
                         set(ERROR_CATALOGUE))


class TestRoutersEnforceTheDeclaredParameters(unittest.TestCase):
    """Declared parameter constraints are what the routers actually apply.

    The route table declares a pattern or a numeric range for every parameter,
    and the OpenAPI document is generated from those declarations. A router
    that typed a path parameter as a bare ``str`` would document a constraint
    it does not enforce - and the symptom is not cosmetic: a malformed
    identifier would reach the domain parser and come back as a 500 rather
    than the 4xx the contract promises.
    """

    ROUTER_MODULES = ("assessments", "catalogue", "evidence", "expert_review")

    def test_every_declared_parameter_is_bound_through_the_route_table(self):
        for name in self.ROUTER_MODULES:
            path = module_path(os.path.join("routers", name + ".py"))
            module = tree(path)
            bound = set()
            for node in ast.walk(module):
                if not isinstance(node, ast.Call):
                    continue
                if not (isinstance(node.func, ast.Name)
                        and node.func.id == "parameter"):
                    continue
                self.assertEqual(len(node.args), 2)
                self.assertIsInstance(node.args[1], ast.Constant)
                bound.add(node.args[1].value)
            declared = set()
            for node in ast.walk(module):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                        and node.func.id == "operation":
                    route = ROUTES_BY_OPERATION[node.args[0].value]
                    declared.update(item.name for item in route.parameters)
            with self.subTest(router=name):
                self.assertEqual(bound, declared)

    def test_no_router_writes_its_own_parameter_constraints(self):
        """Otherwise the document and the enforcement are two contracts."""
        for name in self.ROUTER_MODULES:
            text = source(module_path(os.path.join("routers", name + ".py")))
            with self.subTest(router=name):
                self.assertNotIn("Query(", text)
                self.assertNotIn("Path(", text)
                self.assertNotIn('LIMITS["', text)


class TestTheGateStatusIsMeasuredAfterTheRepositoryIsFinal(unittest.TestCase):
    """Regenerating into a clean tree produces a tree that passes its own test.

    The gate status reads the committed OpenAPI artifact and reports whether it
    matches the generator. Producing it before that artifact is written makes
    it report a mismatch the same call is about to fix — so a fresh
    regeneration would fail its own freshness check. Written into a temporary
    tree, because the point is the ordering rather than the contents of this
    repository.
    """

    def test_a_regenerated_tree_is_self_consistent(self):
        import shutil
        import tempfile

        from apps.api.artifacts import GATE_STATUS_PATH, write_artifacts

        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        written = write_artifacts(root)
        for relative, text in sorted(written.items()):
            with io.open(os.path.join(root, relative), encoding="utf-8") as h:
                with self.subTest(artifact=relative):
                    self.assertEqual(h.read(), text)

        # And the gate status describes the tree it was written into, not the
        # repository it was generated from: the counts come out of the
        # temporary tree, which holds no fixtures.
        gate = json.loads(written[GATE_STATUS_PATH])
        self.assertTrue(gate["openapi"]["artifact_committed"])
        self.assertTrue(gate["openapi"]["artifact_matches_generator"])
        self.assertEqual(gate["synthetic_fixture_count"], 0)
        self.assertFalse(gate["wp17_started"])

    def test_a_gate_status_measures_the_tree_it_is_given(self):
        """Otherwise it would describe one repository while living in another."""
        import shutil
        import tempfile

        from apps.api.gate_status import build_gate_status

        empty = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, empty, True)
        elsewhere = build_gate_status(root=empty)
        here = build_gate_status()
        self.assertEqual(elsewhere["synthetic_fixture_count"], 0)
        self.assertGreater(here["synthetic_fixture_count"], 0)
        self.assertFalse(elsewhere["openapi"]["artifact_committed"])
        self.assertTrue(here["openapi"]["artifact_committed"])


class TestThereIsOneArtifactReader(unittest.TestCase):
    """One loader, one path constant, no second way to read the same file.

    ``tests/integration/web/test_asgi_web.py`` imported
    ``load_openapi_document`` from ``apps.api.artifacts`` before it existed,
    which is how this came up - but the import was right and the module was
    wrong. Three places already read the committed OpenAPI document, each with
    its own ``open`` and its own idea of the path, and the thing they were
    comparing is an artifact whose entire purpose is that two parties agree on
    it byte for byte.
    """

    def test_the_loader_exists_and_returns_the_committed_document(self):
        from apps.api.artifacts import load_openapi_document

        document = load_openapi_document()
        self.assertIsInstance(document, dict)
        self.assertIn("openapi", document)
        self.assertIn("paths", document)

    def test_the_loader_agrees_with_the_generator(self):
        from apps.api.artifacts import load_openapi_document
        from apps.api.openapi import build_document, canonical_json

        self.assertEqual(canonical_json(load_openapi_document()),
                         canonical_json(build_document()))

    def test_it_refuses_a_path_it_does_not_own(self):
        from apps.api.artifacts import load_artifact

        with self.assertRaises(KeyError):
            load_artifact("pyproject.toml")

    def test_the_path_is_declared_once(self):
        from apps.api.artifacts import ARTIFACT_PATHS, OPENAPI_PATH
        from apps.api.gate_status import OPENAPI_RELATIVE_PATH

        self.assertEqual(OPENAPI_PATH, OPENAPI_RELATIVE_PATH)
        self.assertIn(OPENAPI_PATH, ARTIFACT_PATHS)

    def test_no_module_outside_the_owner_opens_the_artifact_by_hand(self):
        """Read as source, because the point is that the call is not made.

        ``apps/api/gate_status.py`` is the one exception and is named: it
        measures the repository, so it cannot import the module that writes
        it without a cycle. It shares the path constant instead.
        """
        import io as _io

        permitted = {os.path.join("apps", "api", "gate_status.py"),
                     os.path.join("apps", "api", "artifacts.py")}
        offenders = []
        for base, dirs, files in os.walk(os.path.join(REPO_ROOT, "apps")):
            dirs[:] = [name for name in dirs if name != "__pycache__"]
            for name in sorted(files):
                if not name.endswith(".py"):
                    continue
                path = os.path.join(base, name)
                relative = os.path.relpath(path, REPO_ROOT)
                if relative in permitted:
                    continue
                with _io.open(path, encoding="utf-8") as handle:
                    text = handle.read()
                if "wp16-openapi.json" in text:
                    offenders.append(relative)
        self.assertEqual(offenders, [])
