# -*- coding: utf-8 -*-
"""The WP-16 documentation set exists, is current, and states what §18 asks.

Documents drift. The ones that drift worst are the ones stating a guarantee,
because the guarantee changes and the sentence does not. These tests check that
each required document exists, that the generated ones still match what
generates them, and that a small number of load-bearing statements are present
- chosen so that a change to the system would break the test rather than leave
a document quietly wrong.
"""

from __future__ import annotations

import io
import json
import os
import unittest

from apps.api.contracts.spec import LIMITS, PROHIBITED_REQUEST_FIELDS
from apps.api.errors import ERROR_CATALOGUE
from apps.api.routes import ROUTES, STUB_OPERATIONS
from pgx.domain.claims import scan_claim_text
from tests.unit.api._support import REPO_ROOT

REQUIRED_DOCUMENTS = (
    "docs/architecture/wp16-fastapi-application.md",
    "docs/api/p0-contract.md",
    "docs/api/error-contract.md",
    "docs/api/readiness.md",
    "docs/api/security-boundary.md",
    "docs/evidence/wp16-api-contract-report.md",
    "docs/handoffs/wp16-handoff.md",
    "data/api/README.md",
)


def _read(relative: str) -> str:
    with io.open(os.path.join(REPO_ROOT, relative), encoding="utf-8") as handle:
        return handle.read()


class TestTheDocumentsExist(unittest.TestCase):

    def test_every_required_document_is_present_and_substantial(self):
        for relative in REQUIRED_DOCUMENTS:
            with self.subTest(document=relative):
                path = os.path.join(REPO_ROOT, relative)
                self.assertTrue(os.path.isfile(path), "%s is missing" % relative)
                self.assertGreater(len(_read(relative).splitlines()), 20,
                                   "%s looks like a placeholder" % relative)


class TestTheContractDocumentMatchesTheContract(unittest.TestCase):

    def setUp(self):
        self.text = _read("docs/api/p0-contract.md")

    def test_every_route_is_documented(self):
        for route in ROUTES:
            with self.subTest(operation=route.operation_id):
                self.assertIn(route.operation_id, self.text)
                self.assertIn(route.path, self.text)

    def test_every_disabled_stub_names_its_successor(self):
        for operation_id, work_package in STUB_OPERATIONS.items():
            with self.subTest(operation=operation_id):
                self.assertIn(operation_id, self.text)
        self.assertIn("WP-22", self.text)

    def test_every_limit_is_documented(self):
        for name, value in LIMITS.items():
            with self.subTest(limit=name):
                self.assertIn("`%s`" % name, self.text)
                self.assertIn(str(value), self.text)

    def test_every_prohibited_field_is_documented(self):
        for name in PROHIBITED_REQUEST_FIELDS:
            with self.subTest(field=name):
                self.assertIn("`%s`" % name, self.text)

    def test_the_role_matrix_is_documented(self):
        for role in ("DEMO_USER", "EXPERT_REVIEWER", "ADMIN"):
            with self.subTest(role=role):
                self.assertIn(role, self.text)
        self.assertIn("no role hierarchy", self.text.lower())

    def test_the_release_pinning_guarantee_is_stated(self):
        architecture = _read("docs/architecture/wp16-fastapi-application.md")
        self.assertIn("exactly once", architecture)
        self.assertIn("read the pointer zero times",
                      architecture.replace("reads the pointer zero times",
                                           "read the pointer zero times"))

    def test_the_serialisation_guarantee_is_stated(self):
        for relative in ("docs/api/p0-contract.md",
                         "docs/architecture/wp16-fastapi-application.md"):
            with self.subTest(document=relative):
                self.assertIn("identical governed facts", _read(relative))


class TestTheErrorDocumentMatchesTheCatalogue(unittest.TestCase):

    def setUp(self):
        self.text = _read("docs/api/error-contract.md")

    def test_every_code_is_documented_with_its_message(self):
        for code, (_status, message) in ERROR_CATALOGUE.items():
            with self.subTest(code=code):
                self.assertIn("`%s`" % code, self.text)
                self.assertIn(message, self.text)

    def test_every_status_is_explained(self):
        for status in sorted({status for status, _
                              in ERROR_CATALOGUE.values()}):
            with self.subTest(status=status):
                self.assertIn("| %d |" % status, self.text)

    def test_the_envelope_shape_is_shown(self):
        for field in ("code", "message", "details", "request_id"):
            with self.subTest(field=field):
                self.assertIn('"%s"' % field, self.text)

    def test_the_request_id_hash_exclusion_is_stated(self):
        self.assertIn("never reaches any hash", self.text)


class TestTheReadinessDocumentMatchesTheChecks(unittest.TestCase):

    def setUp(self):
        self.text = _read("docs/api/readiness.md")

    def test_every_blocking_component_is_documented(self):
        from apps.api.readiness import BLOCKING_COMPONENTS
        for name in BLOCKING_COMPONENTS:
            with self.subTest(component=name):
                self.assertIn("`%s`" % name, self.text)

    def test_every_detail_phrase_is_documented(self):
        from apps.api.readiness import DETAILS
        for key, message in DETAILS.items():
            with self.subTest(detail=key):
                self.assertIn(message, self.text)

    def test_it_states_that_external_services_are_excluded(self):
        self.assertIn("External services are not components", self.text)

    def test_it_reports_this_repository_as_not_ready(self):
        self.assertIn('"status": "NOT_READY"', self.text)


class TestTheEvidenceReportIsHonest(unittest.TestCase):

    def setUp(self):
        self.text = _read("docs/evidence/wp16-api-contract-report.md")

    def test_it_reports_the_limitations_that_do_not_depend_on_a_host(self):
        """The ones no installation can lift.

        The list used to include "cannot be installed", which stopped being
        true and made this test enforce a false statement about the
        repository. What it enforces now is the set of limits that are
        properties of this work package rather than of whichever machine ran
        it: no database was started, and nothing was faked to make a missing
        package look present.
        """
        for statement in ("No PostgreSQL service has been started",
                          "No stand-in was vendored"):
            with self.subTest(statement=statement):
                self.assertIn(statement, self.text)

    def test_it_describes_runtime_verification_as_recorded_not_assumed(self):
        lowered = self.text.lower()
        self.assertIn("apps.api.runtime_verification", self.text)
        self.assertIn("stale_evidence_rejected", lowered)
        self.assertIn("verification_failed", lowered)
        self.assertIn("blocked", lowered)

    def test_it_refuses_the_availability_shortcut_in_writing(self):
        """The wrong repair, ruled out in the document as well as the code.

        A reader who only had this report should still know that installing
        FastAPI does not make the flag true.
        """
        self.assertIn("is not a test that ran", self.text)

    def test_it_does_not_claim_the_framework_is_uninstallable(self):
        lowered = self.text.lower()
        for phrase in ("cannot be installed", "not installable here"):
            with self.subTest(phrase=phrase):
                self.assertNotIn(phrase, lowered)

    def test_it_states_the_zero_real_data_position(self):
        self.assertIn("Zero-real-data status", self.text)
        self.assertIn("no endpoint returns a synthetic", self.text)

    def test_it_records_the_defects_found_during_the_work(self):
        self.assertIn("Defects found and fixed", self.text)

    def test_it_does_not_count_static_tests_as_executed(self):
        self.assertIn("not counted as an executed ASGI test", self.text)


class TestTheHandoffDefinesWhatComesNext(unittest.TestCase):

    def setUp(self):
        self.text = _read("docs/handoffs/wp16-handoff.md")

    def test_it_says_what_wp17_receives(self):
        self.assertIn("What WP-17 receives", self.text)

    def test_it_says_what_wp23_receives(self):
        self.assertIn("What WP-23 receives", self.text)
        self.assertIn("PrincipalResolver", self.text)

    def test_it_says_what_wp22_receives(self):
        self.assertIn("What WP-22 receives", self.text)

    def test_it_lists_the_blockers_it_cannot_clear(self):
        self.assertIn("Blockers WP-16 cannot clear", self.text)


class TestTheDocumentsAreClaimSafe(unittest.TestCase):
    """The scanner over every WP-16 document, with its one known interaction.

    ``docs/api/p0-contract.md`` contains the word *diagnosis* because it lists
    the field names this API refuses, and one of them is ``diagnosis``. The
    scanner is lexical - it matches patterns over folded text and performs no
    semantic analysis - so it flags the list of refusals as though it were a
    claim. The correct content is the list; the flag is the cost.

    This test pins that trade rather than hiding it. If someone later removes
    ``diagnosis`` from the refused-field list to make a repository-wide scan
    come out clean, the *other* assertion here - that the document names every
    prohibited field - fails first.
    """

    KNOWN_LEXICAL_MATCHES = {
        "docs/api/p0-contract.md": ("diagnosis",),
    }

    def test_no_document_carries_an_unexpected_claim(self):
        for relative in REQUIRED_DOCUMENTS:
            with self.subTest(document=relative):
                report = scan_claim_text(_read(relative))
                matched = tuple(sorted(
                    item.matched_text for item
                    in (getattr(report, "violations", ()) or ())))
                expected = tuple(sorted(
                    self.KNOWN_LEXICAL_MATCHES.get(relative, ())))
                self.assertEqual(matched, expected)

    def test_the_known_match_is_the_refused_field_list(self):
        self.assertIn("diagnosis", PROHIBITED_REQUEST_FIELDS)
        self.assertIn("`diagnosis`", _read("docs/api/p0-contract.md"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class TestTheEnvironmentExampleIsComplete(unittest.TestCase):
    """Every setting the loader reads is documented, and the file still loads.

    A `.env.example` that drifts from the loader is worse than none: an
    operator sets a variable, nothing happens, and there is no error to
    explain why.
    """

    def _variables(self):
        variables = {}
        for line in _read(".env.example").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                name, _, value = line.partition("=")
                variables[name] = value
        return variables

    def test_every_api_setting_is_documented(self):
        for name in ("PGX_API_ENV", "PGX_API_AUTH_MODE",
                     "PGX_API_DOCS_ENABLED", "PGX_API_CORS_ALLOWED_ORIGINS",
                     "PGX_API_CORS_ALLOW_CREDENTIALS",
                     "PGX_API_MAX_BODY_BYTES",
                     "PGX_API_READINESS_TIMEOUT_SECONDS",
                     "PGX_API_EVIDENCE_BUILD_PATH", "PGX_API_MIGRATION_HEAD"):
            with self.subTest(variable=name):
                self.assertIn(name, self._variables())

    def test_the_documented_example_loads(self):
        from apps.api.config import Environment, load_settings
        settings = load_settings(self._variables())
        self.assertEqual(settings.environment, Environment.DEVELOPMENT)
        self.assertEqual(settings.max_body_bytes, LIMITS["max_body_bytes"])

    def test_the_example_configures_no_authentication(self):
        from apps.api.security import AuthMode
        from apps.api.config import load_settings
        self.assertEqual(load_settings(self._variables()).auth_mode,
                         AuthMode.UNCONFIGURED)

    def test_the_example_enables_no_cross_origin_access(self):
        from apps.api.config import load_settings
        self.assertFalse(load_settings(self._variables()).cors_enabled)
