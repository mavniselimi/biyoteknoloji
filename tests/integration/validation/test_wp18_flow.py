# -*- coding: utf-8 -*-
"""One partition, end to end, over a real filesystem (WP-18).

Not skipped and needing nothing: no framework, no database, no network, no
browser. Everything WP-18 does is standard library and ``pgx``, which is why
this suite runs wherever the repository does.

The flow is the one a curator would actually perform: read the development
cases, author an independent holdout, audit, attempt an authoring read and be
refused, import a payload into restricted storage, and publish two manifests
that give nothing away. Each step is a place the partition could leak, and the
assertions are about the leak rather than about the happy path.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import unittest

from pgx.application.validation_schema import (validate_case_manifest,
                                               validate_separation_audit)
from pgx.validation.access import (AccessContext, AccessLedger)
from pgx.validation.catalog import development_cases
from pgx.validation.errors import AccessDeniedError, SeparationError
from pgx.validation.manifests import (build_case_manifest,
                                      build_holdout_manifest)
from pgx.validation.restricted_import import import_restricted_payload
from pgx.validation.separation import audit_partition, require_separation
from pgx.validation.vocabulary import (AccessAction, AccessContextKind,
                                       PayloadAvailability,
                                       ValidationCaseRole)
from pgx.validation.cases import RestrictedPayload
from tests.fixtures.wp18.synthetic import (content, internal_holdout_case,
                                           provenance)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))


def _read_json(name):
    with io.open(os.path.join(REPO_ROOT, "data", "validation", name),
                 encoding="utf-8") as handle:
        return json.load(handle)


class TestTheWholePartitionFlow(unittest.TestCase):

    def setUp(self):
        self.storage = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.storage, True)
        self.ledger = AccessLedger()
        self.author = AccessContext("TEST-rule-author",
                                    AccessContextKind.RULE_AUTHORING)
        self.runner = AccessContext("TEST-validation-run",
                                    AccessContextKind.VALIDATION_RUN)

    def test_the_flow(self):
        # 1. The development cases exist and are not evidence.
        development = development_cases(REPO_ROOT)
        self.assertEqual(len(development), 7)
        self.assertTrue(all(case.role is ValidationCaseRole.DEVELOPMENT
                            for case in development))
        self.assertFalse(any(case.is_validation_evidence
                             for case in development))

        # 2. An independent holdout is authored. Its content differs and its
        #    source is not a development fixture.
        body = content(gene="GENE:TESTGENE3", value="POOR")
        payload = RestrictedPayload(body)
        holdout = internal_holdout_case(
            "PGX-VAL-INT-FLOW-1", body=body,
            payload_hash=payload.payload_hash,
            prov=provenance(development=False,
                            source="TEST-SYNTHETIC-VIGNETTE/flow-1"))

        # 3. The audit is clean, and it read no payload to say so.
        audit = require_separation(list(development) + [holdout])
        self.assertTrue(audit.is_clean)
        self.assertEqual(audit.development_count, 7)
        self.assertEqual(audit.internal_holdout_count, 1)
        self.assertEqual(validate_separation_audit(audit.to_json()), ())

        # 4. A rule author asks for the holdout payload and is refused. The
        #    attempt is recorded; the payload loader never runs.
        touched = []
        with self.assertRaises(AccessDeniedError):
            self.ledger.read_payload(holdout, self.author,
                                     lambda: touched.append(1))
        self.assertEqual(touched, [])
        refusal = self.ledger.events_for(holdout.case_id.value)[0]
        self.assertFalse(refusal.allowed)
        self.assertEqual(refusal.actor, "TEST-rule-author")

        # 5. The same author reads a development payload and is allowed.
        self.ledger.read_payload(development[0], self.author,
                                 lambda: {"ok": True})
        self.assertEqual(
            self.ledger.who_has_seen(development[0].case_id.value),
            ("TEST-rule-author",))

        # 6. The payload is imported into restricted storage, atomically.
        result = import_restricted_payload(
            storage_root=self.storage, case=holdout, payload_document=body,
            existing_cases=list(development))
        self.assertTrue(result.separation_clean)
        self.assertEqual(sorted(os.listdir(self.storage)),
                         ["PGX-VAL-INT-FLOW-1.json"])

        # 7. A validation run may read it. The ledger records who.
        def _load_stored():
            with io.open(os.path.join(self.storage,
                                      "PGX-VAL-INT-FLOW-1.json"),
                         encoding="utf-8") as handle:
                return json.load(handle)

        stored = self.ledger.read_payload(holdout, self.runner, _load_stored)
        self.assertEqual(stored["case_id"], "PGX-VAL-INT-FLOW-1")
        self.assertIn("TEST-validation-run",
                      self.ledger.who_has_seen(holdout.case_id.value))

        # 8. Two manifests are published, and neither gives anything away.
        development_manifest = build_case_manifest(
            development, partition="DEVELOPMENT", note="development fixtures")
        holdout_manifest = build_case_manifest(
            [holdout], partition="HOLDOUT",
            payload_availability=PayloadAvailability.CONFIGURED_PRESENT,
            note="one synthetic holdout, authored in this test")
        for document in (development_manifest, holdout_manifest):
            self.assertEqual(validate_case_manifest(document), ())
        rendered = json.dumps(holdout_manifest)
        self.assertNotIn("TESTGENE3", rendered)
        self.assertNotIn("observations", rendered)

        # 9. The holdout manifest still reports the gap to the P0 target.
        self.assertEqual(holdout_manifest["case_count"], 1)
        self.assertEqual(holdout_manifest["target_shortfall"], 49)
        self.assertFalse(holdout_manifest["meets_p0_target"])

        # 10. The access history is append-only and intact throughout.
        intact, index = self.ledger.verify_chain()
        self.assertTrue(intact, "chain broken at %s" % index)

    def test_a_holdout_copied_from_development_never_reaches_storage(self):
        """The copy-and-rename mistake, driven all the way to the disk.

        The content is taken from a real WP-17 catalogue entry rather than
        guessed, so the duplicate is genuine: same canonical content, fresh
        identifier, and a provenance claiming an independent source. Only the
        fingerprint catches it, and it must catch it before anything is
        written.
        """
        from pgx.validation.catalog import load_development_catalog
        from pgx.validation.errors import ImportRefusedError

        development = development_cases(REPO_ROOT)
        entry = load_development_catalog(REPO_ROOT)["cases"][1]
        body = {"observations": [dict(item) for item in
                                 entry["observations"]]}
        payload = RestrictedPayload(body)
        clone = internal_holdout_case(
            "PGX-VAL-INT-CLONE", body=body,
            payload_hash=payload.payload_hash,
            prov=provenance(development=False, source="TEST-CLAIMED-SOURCE"))

        # The premise: it really is a duplicate of a committed development
        # case. If this ever stops holding, the test below proves nothing.
        matching = [case for case in development
                    if case.content_fingerprint == clone.content_fingerprint]
        self.assertEqual(len(matching), 1)
        self.assertNotEqual(matching[0].case_id.value, clone.case_id.value)

        with self.assertRaises(ImportRefusedError) as caught:
            import_restricted_payload(storage_root=self.storage, case=clone,
                                      payload_document=body,
                                      existing_cases=list(development))
        self.assertIn("SEPARATION_VIOLATION", caught.exception.issue_codes)
        self.assertEqual(os.listdir(self.storage), [])


class TestTheCommittedStateIsEmptyAndSaysSo(unittest.TestCase):

    def test_the_repository_has_no_holdout_case(self):
        document = _read_json("wp18-holdout-case-manifest.json")
        self.assertEqual(document["case_count"], 0)
        self.assertEqual(document["cases"], [])

    def test_the_committed_audit_covers_the_development_cases(self):
        document = _read_json("wp18-separation-audit.json")
        self.assertTrue(document["is_clean"])
        self.assertEqual(document["development_count"], 7)
        self.assertEqual(document["internal_holdout_count"], 0)
        self.assertEqual(document["expert_holdout_count"], 0)

    def test_no_restricted_payload_is_committed(self):
        validation = os.path.join(REPO_ROOT, "data", "validation")
        for name in os.listdir(validation):
            with self.subTest(entry=name):
                self.assertTrue(name.endswith(".json") or name == "README.md")
                self.assertNotIn("payload", name)
                self.assertNotIn("expert", name)
