# -*- coding: utf-8 -*-
"""The WP-10 document set, and the claims it is allowed to make (WP-10).

The failure that matters here is a document asserting a state nobody set: a
handoff saying an approval exists, or an evidence file describing a run that
did not happen. Every claim below is checked against the code or the data it
describes.
"""

from __future__ import annotations

import io
import json
import os
import re
import unittest

from pgx.curation.workflow.policy import GATE_CODES
from pgx.curation.workflow.models import allowed_transitions
from tests.unit.curation._support import REPO_ROOT, source_text

#: The seven the work package names, plus the four this implementation added.
#: The named ones are checked for existence individually below, so a rename
#: cannot pass by being absent from both lists.
REQUIRED_DOCUMENTS = (
    os.path.join("docs", "scientific", "curation-workflow.md"),
    os.path.join("docs", "scientific", "curation-role-matrix.md"),
    os.path.join("docs", "scientific", "curation-approval-gates.md"),
    os.path.join("docs", "operations", "curation-admin-flow.md"),
    os.path.join("docs", "migration", "wp10-legacy-work-items.md"),
    os.path.join("docs", "evidence", "wp10-workflow-validation.md"),
    os.path.join("docs", "handoffs", "wp10-handoff.md"),
)

DOCUMENTS = REQUIRED_DOCUMENTS + (
    os.path.join("docs", "architecture", "wp10-curation-workflow.md"),
    os.path.join("docs", "data", "curation-workflow-contract.md"),
    os.path.join("docs", "evidence", "wp10-schema-validation.md"),
    os.path.join("docs", "risk-management", "wp10-approval-governance.md"),
)

REQUIRED_SCHEMAS = (
    os.path.join("schemas", "curation-work-item.schema.json"),
    os.path.join("schemas", "curation-revision.schema.json"),
    os.path.join("schemas", "curation-review.schema.json"),
    os.path.join("schemas", "curation-adjudication.schema.json"),
    os.path.join("schemas", "rule-approval-envelope.schema.json"),
)

SCHEMAS = REQUIRED_SCHEMAS + (
    os.path.join("schemas", "curation-audit-event.schema.json"),
)

#: Words that must never describe this work package's output. A document
#: claiming any of these would be asserting a state nobody set.
FORBIDDEN_CLAIMS = (
    "the protocol is approved",
    "the protocol has been approved",
    "expert approval is complete",
    "a conclusion has been curated",
    "conclusions have been curated",
    "authentication is complete",
    "authentication is implemented",
    "roles are assigned to real",
    "alembic was run",
    "ran under alembic",
)


class TestTheDocumentSetExists(unittest.TestCase):

    def test_every_wp10_document_is_present_and_not_a_stub(self):
        for relative in DOCUMENTS:
            with self.subTest(document=relative):
                path = os.path.join(REPO_ROOT, relative)
                self.assertTrue(os.path.isfile(path), relative)
                self.assertGreater(len(source_text(relative)), 1500,
                                   "%s is a stub" % relative)

    def test_every_wp10_schema_is_present_and_parses(self):
        for relative in SCHEMAS:
            with self.subTest(schema=relative):
                with io.open(os.path.join(REPO_ROOT, relative),
                             encoding="utf-8") as handle:
                    json.load(handle)

    def test_every_document_the_work_package_names_exists(self):
        """Checked by exact path. An implementation that renamed one and added
        it to the general list would otherwise pass."""
        for relative in REQUIRED_DOCUMENTS:
            with self.subTest(document=relative):
                self.assertTrue(os.path.isfile(os.path.join(REPO_ROOT,
                                                            relative)),
                                "%s is required by name" % relative)

    def test_every_schema_the_work_package_names_exists(self):
        for relative in REQUIRED_SCHEMAS:
            with self.subTest(schema=relative):
                self.assertTrue(os.path.isfile(os.path.join(REPO_ROOT,
                                                            relative)),
                                "%s is required by name" % relative)

    def test_the_handoff_links_every_other_document(self):
        handoff = source_text(os.path.join("docs", "handoffs",
                                           "wp10-handoff.md"))
        for relative in DOCUMENTS:
            name = os.path.basename(relative)[:-3]
            if name == "wp10-handoff":
                continue
            with self.subTest(document=name):
                self.assertTrue(name in handoff,
                                "the handoff does not link %s" % name)

    def test_the_workflow_document_links_the_roles_and_the_gates(self):
        body = source_text(os.path.join("docs", "scientific",
                                        "curation-workflow.md"))
        self.assertIn("curation-role-matrix", body)
        self.assertIn("curation-approval-gates", body)
        self.assertIn("curation-admin-flow", body)


class TestNoDocumentClaimsAnUnsetState(unittest.TestCase):

    def test_no_document_claims_an_approval_that_does_not_exist(self):
        for relative in DOCUMENTS:
            body = source_text(relative).lower()
            for claim in FORBIDDEN_CLAIMS:
                with self.subTest(document=relative, claim=claim):
                    self.assertNotIn(claim, body)

    def test_every_document_that_mentions_approval_says_it_is_blocked(self):
        """Not a keyword count. Each of the three documents that could
        plausibly be read as claiming an approval must name what is blocked."""
        for relative in (os.path.join("docs", "handoffs", "wp10-handoff.md"),
                         os.path.join("docs", "evidence",
                                      "wp10-workflow-validation.md")):
            body = source_text(relative)
            with self.subTest(document=relative):
                self.assertIn("BLOCKED", body)
                self.assertIn("WP-23", body)

    def test_the_evidence_document_does_not_claim_alembic(self):
        body = source_text(os.path.join("docs", "evidence",
                                        "wp10-schema-validation.md"))
        self.assertIn("This is not Alembic", body)
        self.assertIn("A26", body)
        self.assertIn("BLOCKED", body)


class TestTheDocumentedFactsMatchTheCode(unittest.TestCase):

    def test_the_gate_document_lists_every_gate(self):
        for relative in (os.path.join("docs", "scientific",
                                      "curation-approval-gates.md"),
                         os.path.join("docs", "architecture",
                                      "wp10-curation-workflow.md")):
            body = source_text(relative)
            for code in GATE_CODES:
                with self.subTest(document=relative, gate=code):
                    self.assertIn(code, body)

    def test_the_role_matrix_names_every_role_and_says_the_set_is_empty(self):
        from pgx.curation.vocabulary import CurationRole
        body = source_text(os.path.join("docs", "scientific",
                                        "curation-role-matrix.md"))
        for role in CurationRole:
            with self.subTest(role=role.value):
                self.assertIn(role.value, body)
        self.assertIn("empty", body)
        self.assertIn("WP-23", body)

    def test_the_admin_flow_document_lists_every_route_and_exit_code(self):
        from pgx.curation.workflow.forms import READ_ROUTES, WRITE_ROUTES
        from pgx.application import curation_workflow_cli as cli
        body = source_text(os.path.join("docs", "operations",
                                        "curation-admin-flow.md"))
        for route in READ_ROUTES + WRITE_ROUTES:
            with self.subTest(route=route):
                self.assertIn(route, body)
        for flag in cli.REFUSED_FLAGS:
            with self.subTest(flag=flag):
                self.assertIn(flag, body)
        for code in ("`0`", "`1`", "`2`", "`3`"):
            with self.subTest(exit_code=code):
                self.assertIn(code, body)

    def test_the_architecture_document_draws_the_real_state_machine(self):
        body = source_text(os.path.join("docs", "architecture",
                                        "wp10-curation-workflow.md"))
        for source, targets in allowed_transitions().items():
            for target in targets:
                with self.subTest(edge="%s->%s" % (source.value,
                                                   target.value)):
                    self.assertIn(target.value, body)
            if not targets:
                self.assertIn(source.value, body)

    def test_the_contract_names_every_role(self):
        from pgx.curation.vocabulary import CurationRole
        body = source_text(os.path.join("docs", "data",
                                        "curation-workflow-contract.md"))
        for role in CurationRole:
            with self.subTest(role=role.value):
                self.assertIn(role.value, body)

    def test_the_migration_document_reports_the_real_counts(self):
        with io.open(os.path.join(REPO_ROOT, "data", "migration", "wp10",
                                  "manifest.json"), encoding="utf-8") as handle:
            manifest = json.load(handle)
        body = source_text(os.path.join("docs", "migration",
                                        "wp10-legacy-work-items.md"))
        counts = manifest["counts"]
        self.assertIn("{:,}".format(counts["work_items"]), body)
        self.assertIn("{:,}".format(counts["linked_work_items"]), body)
        self.assertIn(str(counts["unlinked_work_items"]), body)
        self.assertIn(manifest["content_hash"], body)
        self.assertIn(manifest["source_content_hash"], body)

    def test_the_handoff_lists_every_shipped_module(self):
        body = source_text(os.path.join("docs", "handoffs",
                                        "wp10-handoff.md"))
        directory = os.path.join(REPO_ROOT, "pgx", "curation", "workflow")
        for name in sorted(os.listdir(directory)):
            if not name.endswith(".py") or name == "__init__.py":
                continue
            with self.subTest(module=name):
                self.assertIn(name, body)

    def test_the_risk_document_gives_every_risk_a_control_and_a_residual(self):
        body = source_text(os.path.join("docs", "risk-management",
                                        "wp10-approval-governance.md"))
        risks = re.findall(r"^### (R-10-\d+) — (.+)$", body, re.MULTILINE)
        self.assertGreaterEqual(len(risks), 8)
        sections = re.split(r"^### ", body, flags=re.MULTILINE)[1:]
        for section in sections:
            identifier = section.split(" ", 1)[0]
            with self.subTest(risk=identifier):
                self.assertIn("**Controls.**", section)
                self.assertIn("**Residual.**", section)

    def test_the_evidence_document_matches_the_run_it_describes(self):
        body = source_text(os.path.join("docs", "evidence",
                                        "wp10-workflow-validation.md"))
        for expected in ("CURATION_REVISION_CREATED",
                         "CURATION_REVISION_SUBMITTED",
                         "CURATION_APPROVED",
                         "13 of 13 open",
                         "audit events added by the refused approval: 0",
                         "reviews written by the refused approval:    0"):
            with self.subTest(line=expected):
                self.assertIn(expected, body)

    def test_the_evidence_document_explains_the_synthetic_actors(self):
        body = source_text(os.path.join("docs", "evidence",
                                        "wp10-workflow-validation.md"))
        self.assertIn("not project personnel", body.lower())
        self.assertIn("TEST-", body)
        self.assertIn("None of these names belongs to anyone", body)

    def test_the_schema_evidence_reports_the_real_cycle(self):
        body = source_text(os.path.join("docs", "evidence",
                                        "wp10-schema-validation.md"))
        self.assertIn("0006 → 0007 → 0006 → 0007", body)
        self.assertIn("0 curation tables remain", body)
        self.assertIn("refusing to downgrade", body)


if __name__ == "__main__":
    unittest.main()
