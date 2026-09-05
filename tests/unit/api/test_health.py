# -*- coding: utf-8 -*-
"""H. Liveness and readiness.

Liveness must stay healthy while everything else is down. Readiness must
report each component independently, must never leak a connection string or a
path, must never mutate anything, and must report this repository's real state
- which is not ready, because the claim boundary is unapproved.
"""

from __future__ import annotations

import ast
import json
import os
import time
import unittest

from apps.api.config import ApiSettings, Environment, load_settings
from apps.api.contracts.validate import validate_document
from apps.api.readiness import (ADVISORY_COMPONENTS, BLOCKING_COMPONENTS,
                                DETAILS, ReadinessProbes, evaluate_readiness,
                                liveness_document)
from apps.api.security import AuthMode
from pgx.domain.claims import DEFAULT_CLAIM_BOUNDARY, scan_claim_text
from tests.unit.api._support import API_DIR, identifiers_of, test_settings


class _Approved:
    """A boundary that is approved, for testing the ready path only."""
    is_approved = True

    class phase:
        value = "P0"


def _ok():
    return (True, "ok")


class TestLiveness(unittest.TestCase):

    def test_it_satisfies_the_contract(self):
        self.assertTrue(validate_document("LivenessResponse",
                                          liveness_document()))

    def test_it_reports_one_field_and_no_version(self):
        document = liveness_document()
        self.assertEqual(sorted(document), ["status"])
        self.assertEqual(document["status"], "LIVE")

    def test_it_stays_healthy_when_nothing_else_is(self):
        readiness = evaluate_readiness(load_settings({}),
                                       claim_boundary=DEFAULT_CLAIM_BOUNDARY)
        self.assertEqual(readiness["status"], "NOT_READY")
        self.assertEqual(liveness_document()["status"], "LIVE")

    def test_the_liveness_handler_takes_no_provider(self):
        """Read from the router: the liveness handler has no provider
        argument, so it has nothing to reach a database with."""
        from tests.unit.api._support import module_path, tree as parse
        module = parse(module_path("routers/health.py"))
        handlers = {node.name: node for node in ast.walk(module)
                    if isinstance(node, (ast.FunctionDef,
                                         ast.AsyncFunctionDef))}
        self.assertIn("get_liveness", handlers)
        arguments = {argument.arg
                     for argument in handlers["get_liveness"].args.args}
        self.assertEqual(arguments, {"principal"})
        self.assertIn("provider",
                      {argument.arg
                       for argument in handlers["get_readiness"].args.args})


class TestReadinessShape(unittest.TestCase):

    def setUp(self):
        self.document = evaluate_readiness(
            load_settings({}), claim_boundary=DEFAULT_CLAIM_BOUNDARY)

    def test_it_satisfies_the_contract(self):
        self.assertTrue(validate_document("ReadinessResponse", self.document))

    def test_every_declared_component_is_reported(self):
        reported = {item["component"] for item in self.document["components"]}
        for name in BLOCKING_COMPONENTS + ADVISORY_COMPONENTS:
            with self.subTest(component=name):
                self.assertIn(name, reported)

    def test_components_are_reported_independently(self):
        self.assertGreater(len(self.document["components"]), 1)
        for item in self.document["components"]:
            with self.subTest(component=item["component"]):
                self.assertEqual(sorted(item),
                                 ["blocking", "component", "detail", "ready"])

    def test_components_are_in_a_deterministic_order(self):
        names = [item["component"] for item in self.document["components"]]
        self.assertEqual(names, sorted(names))

    def test_every_detail_comes_from_the_fixed_catalogue(self):
        for item in self.document["components"]:
            with self.subTest(component=item["component"]):
                self.assertIn(item["detail"], set(DETAILS.values()))

    def test_no_detail_makes_a_prohibited_claim(self):
        for key, message in DETAILS.items():
            with self.subTest(detail=key):
                report = scan_claim_text(message)
                self.assertEqual(
                    list(getattr(report, "violations", ()) or ()), [])


class TestReadinessReportsTheRealState(unittest.TestCase):
    """This repository is not ready, and that is the correct answer."""

    def test_the_unapproved_claim_boundary_blocks_readiness(self):
        document = evaluate_readiness(load_settings({}),
                                      claim_boundary=DEFAULT_CLAIM_BOUNDARY)
        self.assertIn("claim_boundary", document["blocking_failures"])
        self.assertEqual(document["status"], "NOT_READY")

    def test_the_gate_is_described_as_a_gate_not_a_fault(self):
        document = evaluate_readiness(load_settings({}),
                                      claim_boundary=DEFAULT_CLAIM_BOUNDARY)
        detail = [item["detail"] for item in document["components"]
                  if item["component"] == "claim_boundary"][0]
        self.assertIn("governance gate", detail)

    def test_unconfigured_authentication_blocks_readiness(self):
        document = evaluate_readiness(load_settings({}),
                                      claim_boundary=_Approved())
        self.assertIn("authentication", document["blocking_failures"])

    def test_it_is_ready_only_when_every_blocking_component_is(self):
        """Every blocking probe must answer, and WP-23 added four of them.

        The assertion is unchanged in meaning: readiness is the conjunction
        of every blocking component. What changed is the size of the
        conjunction - password hashing, the session store, the governed audit
        sink and the rate limiter all block now, because a deployment that
        cannot hash a password, store a session, record a governed act or
        meter a login must not serve authenticated routes.
        """
        settings = test_settings()
        document = evaluate_readiness(
            settings, claim_boundary=_Approved(),
            probes=ReadinessProbes(database=_ok, migrations=_ok,
                                   active_release=_ok, evidence_build=_ok,
                                   password_hashing=_ok, session_store=_ok,
                                   governed_audit=_ok, rate_limiter=_ok))
        self.assertEqual(document["status"], "READY")
        self.assertEqual(document["blocking_failures"], [])

    def test_an_advisory_failure_does_not_block(self):
        document = evaluate_readiness(
            test_settings(), claim_boundary=_Approved(),
            probes=ReadinessProbes(database=_ok, migrations=_ok,
                                   active_release=_ok, password_hashing=_ok,
                                   session_store=_ok, governed_audit=_ok,
                                   rate_limiter=_ok))
        self.assertEqual(document["status"], "READY")
        advisory = [item for item in document["components"]
                    if item["component"] == "evidence_build"][0]
        self.assertFalse(advisory["ready"])
        self.assertFalse(advisory["blocking"])

    def test_each_security_dependency_blocks_on_its_own(self):
        """Reported by name, so an operator learns which one is missing
        rather than that "security" is unavailable."""
        every = dict(database=_ok, migrations=_ok, active_release=_ok,
                     evidence_build=_ok, password_hashing=_ok,
                     session_store=_ok, governed_audit=_ok, rate_limiter=_ok)
        for component in ("password_hashing", "session_store",
                          "governed_audit", "rate_limiter"):
            with self.subTest(component=component):
                probes = dict(every)
                probes[component] = None
                document = evaluate_readiness(
                    test_settings(), claim_boundary=_Approved(),
                    probes=ReadinessProbes(**probes))
                self.assertEqual(document["status"], "NOT_READY")
                self.assertEqual(document["blocking_failures"], [component])

    def test_the_default_unconfigured_deployment_fails_closed(self):
        """A31. Nothing about WP-23 made an unconfigured deployment ready."""
        document = evaluate_readiness(load_settings({}),
                                      claim_boundary=DEFAULT_CLAIM_BOUNDARY)
        self.assertEqual(document["status"], "NOT_READY")
        for component in ("authentication", "password_hashing",
                          "session_store", "governed_audit", "rate_limiter"):
            with self.subTest(component=component):
                self.assertIn(component, document["blocking_failures"])


class TestReadinessLeaksNothing(unittest.TestCase):

    def test_a_raising_probe_never_leaks_its_message(self):
        secret = "postgresql://pgx:hunter2@db.internal:5432/pgx"

        def _explode():
            raise RuntimeError("could not connect to %s (/var/run/pg.sock)"
                               % secret)

        document = evaluate_readiness(
            test_settings(), claim_boundary=_Approved(),
            probes=ReadinessProbes(database=_explode, migrations=_ok,
                                   active_release=_ok))
        rendered = json.dumps(document)
        self.assertNotIn(secret, rendered)
        self.assertNotIn("hunter2", rendered)
        self.assertNotIn("/var/run", rendered)
        self.assertIn("database", document["blocking_failures"])

    def test_a_missing_driver_is_reported_as_such(self):
        def _missing():
            raise ImportError("No module named 'sqlalchemy'")

        document = evaluate_readiness(
            test_settings(), claim_boundary=_Approved(),
            probes=ReadinessProbes(database=_missing, migrations=_ok,
                                   active_release=_ok))
        detail = [item["detail"] for item in document["components"]
                  if item["component"] == "database"][0]
        self.assertEqual(detail, DETAILS["driver_missing"])

    def test_no_component_name_is_a_connection_string(self):
        document = evaluate_readiness(load_settings({}),
                                      claim_boundary=DEFAULT_CLAIM_BOUNDARY)
        for item in document["components"]:
            with self.subTest(component=item["component"]):
                self.assertNotIn(":", item["component"])
                self.assertNotIn("/", item["component"])


class TestReadinessDoesNotMutateOrAssess(unittest.TestCase):

    def test_the_module_never_executes_an_assessment(self):
        path = os.path.join(API_DIR, "readiness.py")
        names = identifiers_of(path)
        for forbidden in ("execute", "AssessmentService", "AssessmentInput",
                          "commit", "add", "activate_release", "migrate"):
            with self.subTest(name=forbidden):
                self.assertNotIn(forbidden, names)

    def test_probes_run_within_a_budget(self):
        def _slow():
            time.sleep(0.05)
            return (True, "ok")

        started = time.monotonic()
        evaluate_readiness(test_settings(), claim_boundary=_Approved(),
                           probes=ReadinessProbes(database=_slow,
                                                  migrations=_slow,
                                                  active_release=_slow),
                           budget_seconds=1.0)
        self.assertLess(time.monotonic() - started, 1.0)

    def test_an_exhausted_budget_reports_rather_than_hangs(self):
        document = evaluate_readiness(
            test_settings(), claim_boundary=_Approved(),
            probes=ReadinessProbes(database=_ok, migrations=_ok,
                                   active_release=_ok),
            budget_seconds=0.000001)
        self.assertEqual(document["status"], "NOT_READY")


class TestReadinessIgnoresExternalServices(unittest.TestCase):
    """§14: no third party may affect P0 readiness."""

    def test_no_external_service_is_a_component(self):
        names = set(BLOCKING_COMPONENTS + ADVISORY_COMPONENTS)
        for forbidden in ("clinpgx", "gemini", "llm", "network", "internet",
                          "openai", "anthropic"):
            with self.subTest(component=forbidden):
                self.assertNotIn(forbidden, names)

    def test_the_module_imports_nothing_that_reaches_a_network(self):
        from tests.unit.api._support import imports_of, module_path
        for name in imports_of(module_path("readiness.py")):
            with self.subTest(module=name):
                self.assertNotIn(name.split(".")[0],
                                 ("socket", "http", "urllib", "requests",
                                  "httpx", "ssl"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
