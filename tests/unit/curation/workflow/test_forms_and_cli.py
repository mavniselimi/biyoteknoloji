# -*- coding: utf-8 -*-
"""The internal console and the offline CLI (WP-10).

Neither is a web application. The console is a set of functions from data to
strings; the CLI reads files and prints JSON. What both must get right is the
same short list: escape everything, never mutate behind a read, never accept a
role from the caller, and never offer an approval control when a gate is shut.
"""

from __future__ import annotations

import ast
import io
import json
import os
import unittest

from pgx.application import curation_workflow_cli as cli
from pgx.curation.vocabulary import ConflictState
from pgx.curation.workflow import forms
from pgx.curation.workflow.models import LEGACY_MIGRATION_TAG, ReviewDecision
from tests.support.workflow_fixtures import (SYNTHETIC_EVIDENCE_UUIDS,
                                             TEST_CURATOR, TEST_REVIEWER,
                                             TEST_STEWARD, build_service,
                                             evidence_snapshot, raw_work_item,
                                             real_repository_policy, seed_raw,
                                             steward_verification)
from tests.unit.curation._support import REPO_ROOT

XSS = '<img src=x onerror="alert(1)">'
QUOTE_ATTACK = '" onmouseover="steal()'


class _Console(unittest.TestCase):

    def setUp(self):
        self.service, self.store = build_service(
            policy=real_repository_policy())
        self.item = seed_raw(self.store, raw_work_item(
            "TEST-WI-FORM", tags=(LEGACY_MIGRATION_TAG,),
            legacy_values={"legacy.note": XSS,
                           "legacy.claim": "reduce dose & monitor"}))

    def _get(self, route, **params):
        params.setdefault("work_item_id", self.item.work_item_id)
        return forms.handle(route, {"method": "GET", "params": params},
                            service=self.service)

    def _submitted(self):
        revision = self.service.create_revision(
            actor_id=TEST_CURATOR, work_item_id=self.item.work_item_id,
            expected_version=0, payload={"conclusion_state": "INSUFFICIENT"},
            evidence=evidence_snapshot())
        self.service.submit(actor_id=TEST_CURATOR,
                            work_item_id=self.item.work_item_id,
                            revision_id=revision.revision.revision_id,
                            expected_version=1)
        return revision


class TestEverythingIsEscaped(_Console):

    def test_upstream_text_never_reaches_a_page_unescaped(self):
        body = self._get("detail").body
        self.assertNotIn(XSS, body)
        self.assertIn("&lt;img src=x onerror=", body)

    def test_an_attribute_break_is_escaped_too(self):
        """quote=True, because values are interpolated into attributes as well
        as into text."""
        self.assertNotIn(QUOTE_ATTACK, forms.escape(QUOTE_ATTACK))
        self.assertIn("&quot;", forms.escape(QUOTE_ATTACK))

    def test_no_page_carries_a_script_tag(self):
        for route in ("detail", "editor", "history"):
            with self.subTest(route=route):
                self.assertNotIn("<script", self._get(route).body.lower())

    def test_rendering_is_deterministic(self):
        first = self._get("history").body
        second = self._get("history").body
        self.assertEqual(first, second)


class TestSourceTextIsSeparatedFromCuratorText(_Console):

    def test_legacy_values_are_labelled_as_unreviewed_upstream_text(self):
        body = self._get("detail").body
        self.assertIn("unreviewed upstream text", body)
        self.assertIn("source-block", body)

    def test_curator_text_carries_a_different_label_and_channel(self):
        self._submitted()
        body = self._get("detail").body
        self.assertIn("written by this project", body)
        self.assertIn("curator-block", body)

    def test_the_two_labels_are_never_the_same_string(self):
        self.assertNotEqual("unreviewed upstream text",
                            "written by this project")


class TestReadHandlersCannotMutate(_Console):

    def test_a_read_route_reports_that_it_mutated_nothing(self):
        for route in forms.READ_ROUTES:
            with self.subTest(route=route):
                params = {"work_item_id": self.item.work_item_id}
                if route == "list":
                    params["items"] = []
                response = forms.handle(route,
                                        {"method": "GET", "params": params},
                                        service=self.service)
                self.assertFalse(response.mutated)

    def test_the_read_view_exposes_no_mutation(self):
        view = forms.ReadOnlyWorkflowView(self.service)
        for name in ("create_revision", "submit", "review", "adjudicate",
                     "import_legacy_work_item",
                     "record_provenance_verification"):
            with self.subTest(method=name):
                self.assertFalse(hasattr(view, name))

    def test_a_write_route_reached_by_a_get_is_refused(self):
        for route in forms.WRITE_ROUTES:
            with self.subTest(route=route):
                response = forms.handle(route,
                                        {"method": "GET", "params": {}},
                                        service=self.service)
                self.assertEqual(response.status, 405)
                self.assertFalse(response.mutated)

    def test_no_read_page_contains_a_get_form(self):
        for route in ("detail", "history"):
            with self.subTest(route=route):
                body = self._get(route).body
                self.assertNotIn("method=\"get\"", body.lower())


class TestTheFormSuppliesNoRole(_Console):

    def test_no_field_dictionary_entry_names_a_role(self):
        for name in forms.FORM_FIELDS:
            with self.subTest(field=name):
                self.assertNotIn("role", name)

    def test_no_rendered_page_carries_a_role_input(self):
        for route in ("editor", "review-form"):
            with self.subTest(route=route):
                body = self._get(route).body
                for spelling in ('name="role"', 'name="roles"',
                                 'name="as_role"', 'name="actor_roles"'):
                    self.assertNotIn(spelling, body)

    def test_a_role_supplied_anyway_is_refused(self):
        for spelling in ("role", "roles", "as_role", "actor_roles"):
            with self.subTest(field=spelling):
                response = forms.handle(
                    "save-revision",
                    {"method": "POST",
                     "params": {"actor_id": TEST_CURATOR,
                                "work_item_id": self.item.work_item_id,
                                "expected_version": 0, "payload_json": "{}",
                                spelling: "ADJUDICATOR"}},
                    service=self.service)
                self.assertEqual(response.status, 400)
                self.assertIn("injected provider", response.data["detail"])

    def test_an_override_flag_supplied_by_a_form_is_refused(self):
        for spelling in ("force", "skip_gates", "approved_by", "status"):
            with self.subTest(field=spelling):
                response = forms.handle(
                    "save-revision",
                    {"method": "POST",
                     "params": {"actor_id": TEST_CURATOR,
                                "work_item_id": self.item.work_item_id,
                                "expected_version": 0, "payload_json": "{}",
                                spelling: "yes"}},
                    service=self.service)
                self.assertEqual(response.status, 400)


class TestTheExpectedVersionIsRequired(_Console):

    def test_a_missing_version_is_refused_rather_than_defaulted(self):
        response = forms.handle(
            "save-revision",
            {"method": "POST",
             "params": {"actor_id": TEST_CURATOR,
                        "work_item_id": self.item.work_item_id,
                        "payload_json": "{}"}},
            service=self.service)
        self.assertEqual(response.status, 400)
        self.assertIn("whatever the version is now", response.data["detail"])

    def test_every_mutating_form_renders_the_version_it_was_built_from(self):
        body = self._get("editor").body
        self.assertIn('name="expected_version" value="0"', body)

    def test_a_stale_version_is_refused(self):
        self.service.create_revision(
            actor_id=TEST_CURATOR, work_item_id=self.item.work_item_id,
            expected_version=0, payload={"c": 1}, evidence=evidence_snapshot())
        response = forms.handle(
            "save-revision",
            {"method": "POST",
             "params": {"actor_id": TEST_CURATOR,
                        "work_item_id": self.item.work_item_id,
                        "expected_version": 0, "payload_json": "{}",
                        "evidence_included": list(SYNTHETIC_EVIDENCE_UUIDS)}},
            service=self.service)
        self.assertEqual(response.status, 400)
        self.assertEqual(response.data["error"], "ConcurrencyError")


class TestApprovalDisappearsWhenAGateIsShut(_Console):

    def test_approve_is_absent_from_the_review_form_under_the_real_policy(self):
        self._submitted()
        self.service.record_provenance_verification(
            actor_id=TEST_STEWARD, work_item_id=self.item.work_item_id,
            verification=steward_verification())
        body = self._get("review-form", reviewer_actor_id=TEST_REVIEWER,
                         conflict_state=ConflictState.NONE_IDENTIFIED,
                         rationale_complete=True).body
        self.assertNotIn('<option value="APPROVE">', body)

    def test_the_other_decisions_remain_available(self):
        self._submitted()
        body = self._get("review-form", reviewer_actor_id=TEST_REVIEWER).body
        for decision in ("REJECT", "REQUEST_CHANGES",
                         "REFER_TO_ADJUDICATION"):
            with self.subTest(decision=decision):
                self.assertIn('<option value="%s">' % decision, body)

    def test_the_blockers_are_listed_with_their_owners(self):
        self._submitted()
        body = self._get("review-form", reviewer_actor_id=TEST_REVIEWER).body
        self.assertIn("approval gates are shut", body)
        self.assertIn("GATE_PROTOCOL_NOT_APPROVED", body)

    def test_approve_returns_when_every_gate_is_open(self):
        service, store = build_service()
        item = seed_raw(store, raw_work_item("TEST-WI-OPEN"))
        revision = service.create_revision(
            actor_id=TEST_CURATOR, work_item_id=item.work_item_id,
            expected_version=0, payload={"c": 1}, evidence=evidence_snapshot())
        service.record_provenance_verification(
            actor_id=TEST_STEWARD, work_item_id=item.work_item_id,
            verification=steward_verification())
        service.submit(actor_id=TEST_CURATOR, work_item_id=item.work_item_id,
                       revision_id=revision.revision.revision_id,
                       expected_version=1)
        body = forms.handle(
            "review-form",
            {"method": "GET",
             "params": {"work_item_id": item.work_item_id,
                        "reviewer_actor_id": TEST_REVIEWER,
                        "conflict_state": ConflictState.NONE_IDENTIFIED,
                        "rationale_complete": True}},
            service=service).body
        self.assertIn('<option value="APPROVE">', body)


class TestTheConsoleStartsNoServer(unittest.TestCase):

    def test_no_console_module_imports_a_web_framework_or_a_socket(self):
        for relative in (os.path.join("pgx", "curation", "workflow",
                                      "forms.py"),
                         os.path.join("pgx", "application",
                                      "curation_workflow_cli.py")):
            with io.open(os.path.join(REPO_ROOT, relative),
                         encoding="utf-8") as handle:
                tree = ast.parse(handle.read(), filename=relative)
            imported = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name.split(".")[0]
                                    for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module.split(".")[0])
            for forbidden in ("fastapi", "starlette", "flask", "django",
                              "uvicorn", "socket", "socketserver", "asyncio",
                              "wsgiref", "http", "aiohttp"):
                with self.subTest(module=relative, imported=forbidden):
                    self.assertNotIn(forbidden, imported)

    def test_no_console_module_binds_or_listens(self):
        for relative in (os.path.join("pgx", "curation", "workflow",
                                      "forms.py"),
                         os.path.join("pgx", "application",
                                      "curation_workflow_cli.py")):
            with io.open(os.path.join(REPO_ROOT, relative),
                         encoding="utf-8") as handle:
                tree = ast.parse(handle.read(), filename=relative)
            called = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func = node.func
                    called.add(getattr(func, "attr", None)
                               or getattr(func, "id", None))
            for forbidden in ("bind", "listen", "serve_forever", "run_app",
                              "create_server"):
                with self.subTest(module=relative, call=forbidden):
                    self.assertNotIn(forbidden, called)


class TestTheCli(unittest.TestCase):

    def _run(self, argv):
        import contextlib
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = cli.main(argv)
        return code, buffer.getvalue()

    def test_import_legacy_reports_the_counts_and_creates_nothing(self):
        code, output = self._run(["import-legacy"])
        self.assertEqual(code, cli.EXIT_OK)
        payload = json.loads(output)
        self.assertEqual(payload["counts"]["work_items"], 1559)
        self.assertEqual(payload["counts"]["curated"], 0)
        self.assertEqual(payload["counts"]["approvals"], 0)

    def test_output_is_json_by_default(self):
        _code, output = self._run(["list", "--limit", "1"])
        json.loads(output)

    def test_an_unknown_work_item_exits_not_found(self):
        code, output = self._run(["show", "CWI-LEGACY-doesnotexist"])
        self.assertEqual(code, cli.EXIT_NOT_FOUND)
        self.assertEqual(json.loads(output)["code"], "NOT_FOUND")

    def test_a_real_work_item_is_blocked_with_structured_reasons(self):
        _code, listing = self._run(["list", "--limit", "1"])
        work_item_id = json.loads(listing)["work_items"][0]["work_item_id"]
        code, output = self._run(["gate-status", work_item_id])
        self.assertEqual(code, cli.EXIT_REFUSED)
        payload = json.loads(output)
        self.assertFalse(payload["passed"])
        self.assertTrue(payload["blockers"])
        for blocker in payload["blockers"]:
            with self.subTest(code=blocker["code"]):
                self.assertTrue(blocker["owner"].strip())

    def test_a_mutating_command_refuses_because_no_actor_holds_a_role(self):
        _code, listing = self._run(["list", "--limit", "1"])
        work_item_id = json.loads(listing)["work_items"][0]["work_item_id"]
        code, output = self._run(["submit", work_item_id, "--revision",
                                  "REV-1", "--expected-version", "0",
                                  "--actor", "TEST-curator-1"])
        self.assertEqual(code, cli.EXIT_REFUSED)
        payload = json.loads(output)
        self.assertTrue(payload["refused"])
        self.assertEqual(payload["code"], "ActorError")

    def test_every_self_elevation_flag_is_refused_by_name(self):
        for flag in cli.REFUSED_FLAGS:
            with self.subTest(flag=flag):
                code, output = self._run(["list", flag, "ADJUDICATOR"])
                self.assertEqual(code, cli.EXIT_REFUSED)
                payload = json.loads(output)
                self.assertEqual(payload["code"], "RoleViolationError")
                self.assertIn(flag, payload["detail"])

    def test_abbreviation_cannot_smuggle_a_flag_the_tool_lacks(self):
        """`--role` must not be absorbed as a prefix of `--roles`. Argparse
        does that by default, and it turned a refused flag into an accepted
        one whose value was read as a filename."""
        parser = cli.build_parser()
        self.assertFalse(parser.allow_abbrev)

    def test_a_role_file_naming_a_person_is_refused(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".json",
                                         delete=False) as handle:
            json.dump({"real.person": ["SCIENTIFIC_CURATOR"]}, handle)
            path = handle.name
        try:
            code, output = self._run(["list", "--roles", path, "--limit", "1"])
            self.assertEqual(code, cli.EXIT_CONFIGURATION_FAILURE)
            self.assertIn("not a synthetic actor", json.loads(output)["error"])
        finally:
            os.unlink(path)

    def test_the_parser_offers_no_approval_or_rule_command(self):
        parser = cli.build_parser()
        actions = [action for action in parser._actions
                   if hasattr(action, "choices") and action.choices]
        commands = set()
        for action in actions:
            if isinstance(action.choices, dict):
                commands.update(action.choices)
        for forbidden in ("approve", "approve-protocol", "create-rule",
                          "validate-rule", "publish-dataset", "curate",
                          "auto-review", "resolve-conflict"):
            with self.subTest(command=forbidden):
                self.assertNotIn(forbidden, commands)

    def test_render_form_writes_html_and_returns_ok(self):
        _code, listing = self._run(["list", "--limit", "1"])
        work_item_id = json.loads(listing)["work_items"][0]["work_item_id"]
        code, output = self._run(["render-form", "detail",
                                  "--work-item", work_item_id])
        self.assertEqual(code, cli.EXIT_OK)
        self.assertTrue(output.startswith("<!DOCTYPE html>"))
        self.assertIn("served by nothing", output)


if __name__ == "__main__":
    unittest.main()
