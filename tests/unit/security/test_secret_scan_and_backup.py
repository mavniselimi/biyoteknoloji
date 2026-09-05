# -*- coding: utf-8 -*-
"""The secret scanner and the backup plan (WP-23).

Two properties dominate this file.

**Every rule has a negative control, and every control fires.** A rule with no
fixture proving it detects anything is a rule nobody has run, and the first
time anyone finds out is when it fails to catch a real secret. The test
enumerates the rules rather than the controls, so a *new* rule with no control
fails here rather than passing unnoticed.

**No matched value ever appears.** Asserted against the report, the rendered
artifact and the command output, because a scanner that printed what it found
would be the same disclosure it exists to prevent, arriving through the tool.
"""

from __future__ import annotations

import io
import json
import os
import unittest

from pgx.application.security_schema import (validate_backup_status,
                                             validate_secret_scan_report)
from pgx.security.backup import (BACKUP_SCOPE, OperationalStatus,
                                 backup_status, preflight)
from pgx.security.secret_scan import (ALLOWLIST, NEGATIVE_FIXTURES, RULES,
                                      scan_repository, scan_text)
from tests.fixtures.wp23.negative_controls import (NEGATIVE_CONTROLS,
                                                   controls_for_rule)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                         "..", "..", ".."))

#: Rules whose finding is a file's *presence*, so they have no text control.
_PRESENCE_ONLY = frozenset({"SEC-006-COMMITTED-ENV-FILE"})


class TestEveryRuleHasAProvenControl(unittest.TestCase):

    def test_every_rule_declares_a_negative_control(self):
        """Enumerated from the rules, not from the controls.

        A new rule with no control fails here. The reverse listing would let
        one be added and never proven.
        """
        for rule in RULES:
            if rule.rule_id in _PRESENCE_ONLY:
                continue
            with self.subTest(rule=rule.rule_id):
                self.assertIn(rule.rule_id, NEGATIVE_CONTROLS)
                self.assertTrue(controls_for_rule(rule.rule_id))

    def test_every_control_makes_its_rule_fire(self):
        for rule_id, samples in NEGATIVE_CONTROLS.items():
            for index, sample in enumerate(samples):
                with self.subTest(rule=rule_id, sample=index):
                    fired = {finding.rule_id
                             for finding in scan_text(sample,
                                                      relative="probe.py")}
                    self.assertIn(rule_id, fired)

    def test_ordinary_source_does_not_fire(self):
        """A scanner that fired on normal code would be turned off."""
        benign = (
            "def resolve(credential):\n"
            "    return provider.principals.resolve(credential)\n"
            "PASSWORD_MIN_LENGTH = 12\n"
            "url = 'postgresql://localhost:5432/pgx_test'\n"
            "note = 'the session cookie is Secure and HttpOnly'\n")
        self.assertEqual(scan_text(benign, relative="probe.py"), [])

    def test_a_rule_with_no_rationale_would_be_unreviewable(self):
        for rule in RULES:
            with self.subTest(rule=rule.rule_id):
                self.assertGreater(len(rule.rationale), 40)


class TestTheScannerNeverPrintsAValue(unittest.TestCase):

    def test_a_finding_carries_no_matched_text(self):
        sample = controls_for_rule("SEC-002-CLOUD-TOKEN")[0]
        findings = scan_text(sample, relative="probe.py")
        self.assertTrue(findings)
        for finding in findings:
            rendered = json.dumps(finding.to_json())
            with self.subTest(rule=finding.rule_id):
                self.assertNotIn(sample, rendered)
                self.assertNotIn("value", finding.to_json())
                self.assertNotIn("match", finding.to_json())
                self.assertNotIn("snippet", finding.to_json())
                # The length, so a reviewer can size a false positive.
                self.assertGreater(finding.matched_length, 0)

    def test_the_repr_carries_no_matched_text(self):
        sample = controls_for_rule("SEC-001-PRIVATE-KEY")[0]
        for finding in scan_text(sample, relative="probe.py"):
            with self.subTest(rule=finding.rule_id):
                self.assertNotIn("PRIVATE KEY", repr(finding))

    def test_the_published_rules_do_not_include_their_patterns(self):
        """A published regex describes what the scanner does not catch."""
        for rule in RULES:
            with self.subTest(rule=rule.rule_id):
                self.assertNotIn("pattern", rule.to_json())


class TestTheAllowlistIsExactAndExplained(unittest.TestCase):

    def test_every_entry_names_one_path_and_one_rule(self):
        known = {rule.rule_id for rule in RULES}
        for entry in ALLOWLIST:
            with self.subTest(path=entry.path):
                self.assertIn(entry.rule_id, known)
                self.assertNotIn("*", entry.path)
                self.assertFalse(entry.path.endswith("/"))
                self.assertGreater(len(entry.reason), 40)

    def test_no_entry_excludes_tests_or_fixtures_broadly(self):
        """An excluded directory is one where a real secret can later be
        committed unnoticed."""
        for entry in ALLOWLIST:
            with self.subTest(path=entry.path):
                for broad in ("tests", "tests/", "fixtures", "docs", "."):
                    self.assertNotEqual(entry.path, broad)

    def test_the_development_credential_exception_is_exactly_scoped(self):
        entries = [item for item in ALLOWLIST
                   if item.path == "docker-compose.yml"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].rule_id, "SEC-004-PASSWORD-ASSIGNMENT")
        self.assertIn("development", entries[0].reason.lower())

    def test_negative_fixtures_are_named_individually_with_a_reason(self):
        """Classified, not ignored: each file says what it is proving."""
        for fixture in NEGATIVE_FIXTURES:
            with self.subTest(path=fixture.path):
                self.assertTrue(fixture.path.endswith(".py"))
                self.assertGreater(len(fixture.reason), 40)
                self.assertTrue(os.path.exists(
                    os.path.join(REPO_ROOT, *fixture.path.split("/"))))

    def test_a_classified_finding_is_still_reported(self):
        """The difference between classifying and ignoring."""
        report = scan_repository(REPO_ROOT)
        self.assertGreater(report["classified_finding_count"], 0)
        self.assertTrue(report["classified_findings"])


class TestTheRepositoryScansClean(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.report = scan_repository(REPO_ROOT)

    def test_the_report_validates(self):
        self.assertEqual(validate_secret_scan_report(self.report), [])

    def test_there_is_no_unclassified_finding(self):
        self.assertEqual(
            self.report["finding_count"], 0,
            "unclassified findings at: %s"
            % [f["path"] + ":" + str(f["line"])
               for f in self.report["findings"]])
        self.assertEqual(self.report["status"], "CLEAN")

    def test_no_committed_artifact_carries_a_secret(self):
        """Published documents are scanned rather than skipped: a document
        read outside the project is the worst place for a credential."""
        for directory in ("data", "schemas"):
            root = os.path.join(REPO_ROOT, directory)
            for base, _dirs, files in os.walk(root):
                for name in sorted(files):
                    if not name.endswith(".json"):
                        continue
                    path = os.path.join(base, name)
                    relative = os.path.relpath(path, REPO_ROOT)
                    with io.open(path, encoding="utf-8") as handle:
                        text = handle.read()
                    with self.subTest(artifact=relative):
                        self.assertEqual(
                            scan_text(text, relative=relative), [])

    def test_no_artifact_contains_a_session_or_auth_header(self):
        for base, _dirs, files in os.walk(os.path.join(REPO_ROOT, "data")):
            for name in sorted(files):
                if not name.endswith(".json"):
                    continue
                with io.open(os.path.join(base, name),
                             encoding="utf-8") as handle:
                    text = handle.read()
                with self.subTest(artifact=name):
                    for marker in ("__Host-pgx_session=", "Bearer ",
                                   "$argon2id$v="):
                        self.assertNotIn(marker, text)


class TestBackupAndRestoreRemainUnexecuted(unittest.TestCase):

    def setUp(self):
        self.status = backup_status(REPO_ROOT, {})

    def test_the_document_validates(self):
        self.assertEqual(validate_backup_status(self.status), [])

    def test_the_procedure_is_documented(self):
        self.assertTrue(self.status["backup_procedure_documented"])
        self.assertTrue(os.path.exists(os.path.join(
            REPO_ROOT, *self.status["runbook"].split("/"))))

    def test_nothing_has_been_executed(self):
        """A25. Three separate facts, all false, none a placeholder."""
        self.assertFalse(self.status["backup_executed"])
        self.assertFalse(self.status["restore_executed"])
        self.assertFalse(self.status["restore_verified"])
        self.assertIn(self.status["operational_status"],
                      (OperationalStatus.BLOCKED,
                       OperationalStatus.NOT_EXECUTED))

    def test_the_vocabulary_has_no_pass(self):
        """One would eventually be assigned by a caller who meant "the
        configuration looks right"."""
        self.assertNotIn("PASS", OperationalStatus.ALL)

    def test_the_preflight_runs_nothing(self):
        """A preflight that shelled out would be a backup wearing a check's
        name.

        Checked by reading the module's imports and call targets from its
        syntax tree, not by searching its text. The docstring says "it runs
        no ``pg_dump``" in as many words, so a substring search matches the
        sentence promising the opposite of what it is looking for - the same
        trap that a search for "throughput" hits in the rate-limit policy's
        own disclaimer.
        """
        import ast

        path = os.path.join(REPO_ROOT, "pgx", "security", "backup.py")
        with io.open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())

        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0]
                                for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
        for forbidden in ("subprocess", "psycopg", "sqlalchemy", "shutil",
                          "socket", "requests", "httpx"):
            with self.subTest(imported=forbidden):
                self.assertNotIn(forbidden, imported)

        # And no call to anything that could execute or copy.
        called = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            target = node.func
            if isinstance(target, ast.Name):
                called.add(target.id)
            elif isinstance(target, ast.Attribute):
                called.add(target.attr)
        for forbidden in ("system", "popen", "run", "check_output", "spawn",
                          "copyfile", "copytree", "connect", "execute"):
            with self.subTest(call=forbidden):
                self.assertNotIn(forbidden, called)

        # The only filesystem calls it makes are read-only observations.
        self.assertTrue({"isdir", "get", "join"} & called)

    def test_the_preflight_reports_what_is_missing(self):
        checks = preflight(REPO_ROOT, {})
        self.assertFalse(checks["ready_to_execute"])
        self.assertIn("DATABASE_CONFIGURED", checks["unmet_check_ids"])
        self.assertIn("RESTORE_TARGET_CONFIGURED", checks["unmet_check_ids"])

    def test_the_scope_covers_the_database_and_the_artifacts(self):
        """Restoring one without the other produces a system whose audit rows
        reference releases it cannot resolve."""
        kinds = {item.kind for item in BACKUP_SCOPE}
        self.assertIn("POSTGRESQL", kinds)
        self.assertIn("ARTIFACT", kinds)
        self.assertIn("RESTRICTED", kinds)

    def test_every_scope_item_says_what_losing_it_costs(self):
        for item in BACKUP_SCOPE:
            with self.subTest(item=item.item_id):
                self.assertGreater(len(item.loss_consequence), 40)
                self.assertGreaterEqual(item.retention_days, 1)

    def test_sensitive_scope_items_require_encryption(self):
        for item in BACKUP_SCOPE:
            if item.kind in ("POSTGRESQL", "RESTRICTED"):
                with self.subTest(item=item.item_id):
                    self.assertTrue(item.encrypted_at_rest_required)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
