# -*- coding: utf-8 -*-
"""Recorded execution, and the four states it can be in.

WP-16's gate status used to hard-code ``asgi_runtime_tests_executed: False``
and an OpenAPI ``runtime_verification: BLOCKED``, with a note saying FastAPI
could not be installed. Both were true where WP-16 was built and went on being
asserted after they stopped being true, because a constant does not learn.

The tempting repair is the one these tests exist to forbid: reporting
execution from *dependency availability*. An importable FastAPI is not a test
that ran, and a gate status that cannot tell the two apart is not measuring
anything. So the flag comes from a recorded run, and every state that is not
"a passing run whose inputs still match" reads as blocked.

Four states, one test class each: absent, successful, failed, stale.
"""

from __future__ import annotations

import copy
import io
import json
import os
import shutil
import tempfile
import unittest

from apps.api.runtime_verification import (EVIDENCE_PATH,
                                           EVIDENCE_SCHEMA_VERSION,
                                           NO_EVIDENCE, REQUIRED_CHECKS, STALE,
                                           VERIFICATION_FAILED, VERIFIED,
                                           build_evidence, evidence_freshness,
                                           input_fingerprints, load_evidence,
                                           verified_runtime_status,
                                           write_evidence)
from tests.unit.api._support import REPO_ROOT


def _passing_checks():
    return [{"name": name, "passed": True, "detail": "synthetic"}
            for name in REQUIRED_CHECKS]


class _TreeCase(unittest.TestCase):
    """A throwaway copy of the parts of the tree the evidence fingerprints.

    Real files, because the fingerprint is over real files and a fake would
    only prove the fake behaves as written.
    """

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        shutil.copytree(os.path.join(REPO_ROOT, "apps"),
                        os.path.join(self.root, "apps"),
                        ignore=shutil.ignore_patterns("__pycache__"))
        os.makedirs(os.path.join(self.root, "schemas", "openapi"))
        shutil.copy(
            os.path.join(REPO_ROOT, "schemas", "openapi", "wp16-openapi.json"),
            os.path.join(self.root, "schemas", "openapi",
                         "wp16-openapi.json"))

    def evidence_file(self):
        return os.path.join(self.root, *EVIDENCE_PATH.split("/"))

    def write(self, evidence):
        return write_evidence(evidence, root=self.root)

    def build(self):
        return build_evidence(_passing_checks(), root=self.root)


class TestAbsentEvidence(_TreeCase):
    """The default state of a fresh checkout, and it must be the safe one."""

    def test_no_file_reads_as_blocked(self):
        self.assertIsNone(load_evidence(self.root))
        status, reason = evidence_freshness(None, self.root)
        self.assertEqual(status, NO_EVIDENCE)
        self.assertIn("no runtime-verification evidence", reason)

    def test_the_gate_fields_fail_closed(self):
        status = verified_runtime_status(self.root)
        self.assertFalse(status["asgi_runtime_tests_executed"])
        self.assertFalse(status["openapi_runtime_verified"])
        self.assertEqual(status["asgi_runtime_test_status"], NO_EVIDENCE)
        self.assertIsNone(status["runtime_verification_evidence"])

    def test_an_unreadable_file_is_treated_as_absent(self):
        os.makedirs(os.path.dirname(self.evidence_file()))
        with io.open(self.evidence_file(), "w", encoding="utf-8") as handle:
            handle.write("{ this is not json")
        self.assertIsNone(load_evidence(self.root))
        self.assertFalse(
            verified_runtime_status(self.root)["asgi_runtime_tests_executed"])

    def test_installed_dependencies_do_not_make_it_true(self):
        """The specific wrong repair, refused explicitly.

        FastAPI is importable in the environment these tests run in whenever
        the ASGI suite runs at all. If availability were ever wired into this
        flag, this assertion is where it would show up.
        """
        import importlib

        try:
            importlib.import_module("fastapi")
        except ImportError:
            self.skipTest("fastapi is not installed, so this cannot "
                          "distinguish availability from execution")
        self.assertFalse(
            verified_runtime_status(self.root)["asgi_runtime_tests_executed"],
            "an importable framework was treated as a test that ran")


class TestSuccessfulEvidence(_TreeCase):

    def test_a_passing_current_record_reads_as_verified(self):
        self.write(self.build())
        status, reason = evidence_freshness(load_evidence(self.root),
                                            self.root)
        self.assertEqual(status, VERIFIED)
        self.assertEqual(reason, "verified and current")

    def test_the_gate_fields_report_it(self):
        self.write(self.build())
        status = verified_runtime_status(self.root)
        self.assertTrue(status["asgi_runtime_tests_executed"])
        self.assertTrue(status["openapi_runtime_verified"])
        self.assertEqual(status["asgi_runtime_test_status"], VERIFIED)
        self.assertEqual(
            [check["name"]
             for check in status["runtime_verification_evidence"]["checks"]],
            sorted(REQUIRED_CHECKS))

    def test_the_record_names_the_stack_it_ran_on(self):
        evidence = self.build()
        environment = evidence["environment"]
        self.assertIn("python", environment)
        self.assertIn("system", environment)
        self.assertIn("machine", environment)
        self.assertIn("fastapi", environment["packages"])

    def test_the_record_carries_input_hashes(self):
        evidence = self.build()
        for key in ("api_source_sha256", "openapi_document_sha256",
                    "committed_openapi_sha256"):
            with self.subTest(key=key):
                self.assertTrue(str(evidence["inputs"][key]).startswith(
                    "sha256:"))


class TestFailedEvidence(_TreeCase):
    """A failed run must overwrite a successful one, not be silently dropped."""

    def test_a_failing_check_cannot_produce_a_verified_record(self):
        checks = _passing_checks()
        checks[2] = dict(checks[2], passed=False, detail="served 500")
        evidence = build_evidence(checks, root=self.root)
        self.assertFalse(evidence["verified"])

    def test_a_missing_check_cannot_produce_a_verified_record(self):
        """An incomplete run is not a passing run.

        Every required check must be reported. A run that stopped after two of
        them has said nothing about the other three, and "all reported checks
        passed" would be true and useless.
        """
        partial = _passing_checks()[:2]
        evidence = build_evidence(partial, root=self.root)
        self.assertFalse(evidence["verified"])
        self.assertEqual(sorted(evidence["checks_not_run"]),
                         sorted(set(REQUIRED_CHECKS)
                                - {check["name"] for check in partial}))

    def test_it_reads_as_failed_and_names_the_check(self):
        checks = _passing_checks()
        checks[4] = dict(checks[4], passed=False, detail="3 failures")
        self.write(build_evidence(checks, root=self.root))
        status, reason = evidence_freshness(load_evidence(self.root),
                                            self.root)
        self.assertEqual(status, VERIFICATION_FAILED)
        self.assertIn(REQUIRED_CHECKS[4], reason)

    def test_a_failed_run_replaces_a_previous_success(self):
        self.write(self.build())
        self.assertTrue(load_evidence(self.root)["verified"])

        checks = _passing_checks()
        checks[0] = dict(checks[0], passed=False, detail="fastapi absent")
        self.write(build_evidence(checks, root=self.root))

        self.assertFalse(load_evidence(self.root)["verified"])
        self.assertFalse(
            verified_runtime_status(self.root)["asgi_runtime_tests_executed"])


class TestStaleEvidence(_TreeCase):
    """Evidence that outlived its subject is worse than none: it looks real."""

    def setUp(self):
        super().setUp()
        self.write(self.build())
        self.assertEqual(
            verified_runtime_status(self.root)["asgi_runtime_test_status"],
            VERIFIED)

    def test_changing_an_api_source_file_invalidates_it(self):
        path = os.path.join(self.root, "apps", "api", "middleware.py")
        with io.open(path, "a", encoding="utf-8") as handle:
            handle.write("\n# a change the runtime could observe\n")
        status, reason = evidence_freshness(load_evidence(self.root),
                                            self.root)
        self.assertEqual(status, STALE)
        self.assertIn("api_source_sha256", reason)

    def test_editing_the_committed_artifact_invalidates_it(self):
        path = os.path.join(self.root, "schemas", "openapi",
                            "wp16-openapi.json")
        with io.open(path, encoding="utf-8") as handle:
            document = json.load(handle)
        document["paths"]["/api/v1/invented"] = {}
        with io.open(path, "w", encoding="utf-8") as handle:
            json.dump(document, handle)
        status, reason = evidence_freshness(load_evidence(self.root),
                                            self.root)
        self.assertEqual(status, STALE)
        self.assertIn("committed_openapi_sha256", reason)

    def test_an_older_schema_version_is_rejected(self):
        evidence = load_evidence(self.root)
        evidence["schema_version"] = "pgx-wp16-runtime-verification/0"
        self.write(evidence)
        status, _reason = evidence_freshness(load_evidence(self.root),
                                             self.root)
        self.assertEqual(status, STALE)

    def test_stale_evidence_fails_closed_in_the_gate_fields(self):
        with io.open(os.path.join(self.root, "apps", "api", "errors.py"), "a",
                     encoding="utf-8") as handle:
            handle.write("\n# changed\n")
        status = verified_runtime_status(self.root)
        self.assertFalse(status["asgi_runtime_tests_executed"])
        self.assertFalse(status["openapi_runtime_verified"])
        self.assertEqual(status["asgi_runtime_test_status"], STALE)

    def test_marking_the_document_verified_does_not_invalidate_it(self):
        """The one change that must *not* count as staleness.

        The verification block is metadata about the document, not part of
        the surface. If it were fingerprinted, recording a successful
        verification would invalidate the evidence for that verification -
        and the status could never settle.
        """
        from apps.api.openapi import build_document, canonical_json

        path = os.path.join(self.root, "schemas", "openapi",
                            "wp16-openapi.json")
        with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(canonical_json(build_document(runtime_verified=True)))
        status, reason = evidence_freshness(load_evidence(self.root),
                                            self.root)
        self.assertEqual(status, VERIFIED, reason)


class TestTheRecordCarriesNothingItShouldNot(_TreeCase):
    """Check names, counts, versions, hashes. Nothing else."""

    def test_no_absolute_path_reaches_the_record(self):
        rendered = json.dumps(self.build())
        for fragment in ("/Users/", "/home/", "/root/", "/tmp/", "C:\\"):
            self.assertNotIn(fragment, rendered)

    def test_it_refuses_a_record_carrying_a_path(self):
        evidence = self.build()
        evidence["checks"][0]["detail"] = "failed reading /Users/someone/repo"
        with self.assertRaises(ValueError):
            self.write(evidence)

    def test_it_refuses_a_record_carrying_a_clinical_identifier(self):
        evidence = self.build()
        evidence["checks"][0]["detail"] = "axis GENE:CYP2C19 was not covered"
        with self.assertRaises(ValueError):
            self.write(evidence)

    def test_it_refuses_a_record_carrying_a_credential(self):
        evidence = self.build()
        evidence["checks"][0]["detail"] = "sent Authorization: Bearer abc"
        with self.assertRaises(ValueError):
            self.write(evidence)

    def test_a_refused_record_is_not_written(self):
        evidence = self.build()
        evidence["note"] = "wrote /root/secret"
        with self.assertRaises(ValueError):
            self.write(evidence)
        self.assertFalse(os.path.isfile(self.evidence_file()))

    def test_the_timestamp_is_utc_and_second_precision(self):
        stamp = self.build()["verified_at"]
        self.assertTrue(stamp.endswith("Z"), stamp)
        self.assertNotIn(".", stamp)


class TestTheGateStatusConsumesOnlyValidEvidence(unittest.TestCase):
    """The committed gate status must agree with the committed evidence."""

    def test_the_two_artifacts_tell_the_same_story(self):
        from apps.api.gate_status import build_gate_status

        status = build_gate_status(root=REPO_ROOT)
        expected = verified_runtime_status(REPO_ROOT)
        self.assertEqual(status["asgi_runtime_tests_executed"],
                         expected["asgi_runtime_tests_executed"])
        self.assertEqual(status["asgi_runtime_test_status"],
                         expected["asgi_runtime_test_status"])
        self.assertEqual(
            status["openapi"]["generated_from_running_application"],
            expected["openapi_runtime_verified"])

    def test_the_openapi_block_never_claims_more_than_the_evidence(self):
        from apps.api.gate_status import build_gate_status

        status = build_gate_status(root=REPO_ROOT)
        if status["openapi"]["runtime_verification"] == VERIFIED:
            self.assertTrue(status["asgi_runtime_tests_executed"])
            evidence = load_evidence(REPO_ROOT)
            self.assertIsNotNone(evidence)
            self.assertTrue(evidence["verified"])

    def test_a_blocker_names_the_missing_verification(self):
        from apps.api.gate_status import build_gate_status

        status = build_gate_status(root=REPO_ROOT)
        codes = [blocker["code"] for blocker in status["blockers"]]
        if status["asgi_runtime_tests_executed"]:
            self.assertNotIn("API_RUNTIME_NOT_VERIFIED", codes)
        else:
            self.assertIn("API_RUNTIME_NOT_VERIFIED", codes)

    def test_the_evidence_schema_version_is_pinned(self):
        self.assertEqual(EVIDENCE_SCHEMA_VERSION,
                         "pgx-wp16-runtime-verification/1")


class TestNoHardCodedRuntimeClaimRemains(unittest.TestCase):
    """Read as source: the constants that caused this must not come back."""

    @classmethod
    def setUpClass(cls):
        with io.open(os.path.join(REPO_ROOT, "apps", "api", "gate_status.py"),
                     encoding="utf-8") as handle:
            cls.source = handle.read()

    def test_the_flag_is_not_a_literal(self):
        self.assertNotIn('"asgi_runtime_tests_executed": False', self.source)
        self.assertNotIn('"asgi_runtime_tests_executed": True', self.source)

    def test_the_status_is_not_derived_from_availability(self):
        self.assertNotIn(
            '"BLOCKED" if not api_dependencies_available else "AVAILABLE"',
            self.source)

    def test_no_text_claims_the_framework_cannot_be_installed(self):
        lowered = self.source.lower()
        for phrase in ("fastapi cannot be installed",
                       "cannot be installed here"):
            self.assertNotIn(phrase, lowered)


class TestEvidenceDoesNotTravel(_TreeCase):
    """A record from another machine is not evidence about this one.

    Without this the mechanism has a hole big enough to drive a build server
    through. The input fingerprints are all properties of the *repository*, so
    a verification run on one host produces a record that stays "current" in
    every checkout of that same source — including checkouts on machines where
    nothing was ever run. The file would arrive saying VERIFIED and the gate
    status would repeat it.

    So the host is fingerprinted too, and a mismatch is rejected like any other
    staleness. What is fingerprinted is the *kind* of machine and the stack —
    OS, architecture, interpreter, package versions — and never a hostname, a
    username or a path, because those are facts about a person and this file is
    committed.
    """

    def setUp(self):
        super().setUp()
        self.write(self.build())

    def test_a_record_from_another_operating_system_is_rejected(self):
        evidence = load_evidence(self.root)
        evidence["environment"]["system"] = "Plan9"
        self.write(evidence)
        status, reason = evidence_freshness(load_evidence(self.root),
                                            self.root)
        self.assertEqual(status, STALE)
        self.assertIn("different host", reason)

    def test_a_record_from_another_interpreter_is_rejected(self):
        evidence = load_evidence(self.root)
        evidence["environment"]["python"] = "3.99.0"
        self.write(evidence)
        self.assertEqual(
            evidence_freshness(load_evidence(self.root), self.root)[0], STALE)

    def test_a_record_from_another_package_stack_is_rejected(self):
        evidence = load_evidence(self.root)
        evidence["environment"]["packages"]["fastapi"] = "0.0.1-not-this-one"
        self.write(evidence)
        self.assertEqual(
            evidence_freshness(load_evidence(self.root), self.root)[0], STALE)

    def test_the_gate_fields_fail_closed_for_foreign_evidence(self):
        evidence = load_evidence(self.root)
        evidence["environment"]["machine"] = "s390x"
        self.write(evidence)
        status = verified_runtime_status(self.root)
        self.assertFalse(status["asgi_runtime_tests_executed"])
        self.assertFalse(status["openapi_runtime_verified"])

    def test_the_host_fingerprint_identifies_a_stack_not_a_person(self):
        from apps.api.runtime_verification import host_fingerprint

        fingerprint = host_fingerprint()
        self.assertEqual(sorted(fingerprint),
                         ["implementation", "machine", "packages", "python",
                          "system"])
        rendered = json.dumps(fingerprint)
        import getpass
        import socket

        for private in (socket.gethostname(), getpass.getuser()):
            if private and len(private) > 3:
                self.assertNotIn(private, rendered)
