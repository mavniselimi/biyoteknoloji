# -*- coding: utf-8 -*-
"""The inventory, the claims and the matrix describe this repository.

These tests are the ones that would catch a pack drifting away from the tree
it claims to describe: a declared artifact that no longer exists, a claim
whose refutation probe can never fire, a matrix citing a deleted module.

The probe test deserves its own note. While writing the claim registry, a
probe named ``state`` on an artifact whose field is
``dataset_lifecycle_state`` returned "no verdict" and the claim it guarded
reported as merely UNSUPPORTED rather than CONTRADICTED. A probe that can
never fire is worse than no probe, because it looks like diligence. So the
suite asserts every probe resolves against the committed tree.
"""

from __future__ import annotations

import os
import re
import tempfile
import unittest

from pgx.ths6.claim_registry import (CLAIMS, build_claim_registry,
                                     evaluate_claim, unresolvable_probes)
from pgx.ths6.evidence_registry import (DECLARED_EVIDENCE,
                                        FINAL_PACK_DOCUMENT_PREFIX,
                                        PRELIMINARY_THS6_DOCUMENTS,
                                        build_evidence_registry,
                                        declared_by_id, field_at,
                                        field_is_missing, read_document,
                                        resolve_evidence)
from pgx.ths6.models import EvidenceItem
from pgx.ths6.traceability import (GATE_IMPLEMENTATION_INDEX,
                                   IMPLEMENTATION_INDEX, build_traceability,
                                   dangling_references)
from pgx.ths6.vocabulary import ClaimSupport, EvidenceType

_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", ".."))


class TestTheDeclaration(unittest.TestCase):

    def test_identifiers_are_unique(self):
        self.assertEqual(len(declared_by_id()), len(DECLARED_EVIDENCE))

    def test_every_work_package_from_00_to_24_is_represented(self):
        """A gap would mean a work package whose output nobody inventoried."""
        packages = {item.work_package for item in DECLARED_EVIDENCE}
        expected = {"WP-%02d" % index for index in range(0, 25)}
        self.assertEqual(packages, expected)

    def test_the_identifier_encodes_its_work_package(self):
        for item in DECLARED_EVIDENCE:
            with self.subTest(item=item.evidence_id):
                self.assertTrue(
                    item.evidence_id.startswith(
                        "EV-%s-" % item.work_package.replace("-", "")),
                    "%s does not encode %s" % (item.evidence_id,
                                               item.work_package))

    def test_no_declared_path_is_absolute(self):
        for item in DECLARED_EVIDENCE:
            with self.subTest(item=item.evidence_id):
                self.assertFalse(item.path.startswith(("/", "~", "\\")))

    def test_every_declared_schema_path_exists(self):
        for item in DECLARED_EVIDENCE:
            if item.schema_path is None:
                continue
            with self.subTest(item=item.evidence_id):
                self.assertTrue(
                    os.path.isfile(os.path.join(_ROOT,
                                                *item.schema_path.split("/"))),
                    "%s declares a schema that is not there" %
                    item.evidence_id)

    def test_every_item_with_a_limitation_names_a_gap_owner(self):
        for item in DECLARED_EVIDENCE:
            if not item.limitations:
                continue
            with self.subTest(item=item.evidence_id):
                self.assertTrue((item.gap_owner or "").strip())

    def test_no_item_is_both_test_only_and_admissible(self):
        for item in DECLARED_EVIDENCE:
            with self.subTest(item=item.evidence_id):
                self.assertFalse(
                    item.test_only
                    and item.evidence_type.may_support_a_ths6_claim)

    def test_the_development_cases_are_typed_as_rehearsal(self):
        """Seven development fixtures must never read as validation cases."""
        index = declared_by_id()
        for evidence_id in ("EV-WP17-003", "EV-WP17-004", "EV-WP18-004"):
            with self.subTest(evidence_id=evidence_id):
                item = index[evidence_id]
                self.assertIs(item.evidence_type,
                              EvidenceType.TEST_ONLY_REHEARSAL)
                self.assertTrue(item.test_only)


class TestPreliminaryDocumentsArePreserved(unittest.TestCase):
    """The three WP-local notes predate this pack and are not part of it.

    WP-24's closing prose said no ``docs/ths6/`` directory existed. It did.
    These tests pin the correction so the distinction cannot be lost again.
    """

    def test_all_three_preliminary_documents_exist(self):
        for path in PRELIMINARY_THS6_DOCUMENTS:
            with self.subTest(path=path):
                self.assertTrue(
                    os.path.isfile(os.path.join(_ROOT, *path.split("/"))),
                    "%s must be preserved, not deleted or renamed" % path)

    def test_they_are_inventoried_as_document_only(self):
        by_path = {item.path: item for item in DECLARED_EVIDENCE}
        for path in PRELIMINARY_THS6_DOCUMENTS:
            with self.subTest(path=path):
                self.assertIn(path, by_path)
                self.assertIs(by_path[path].evidence_type,
                              EvidenceType.DOCUMENT_ONLY)

    def test_none_of_them_is_inside_the_final_pack_directory(self):
        for path in PRELIMINARY_THS6_DOCUMENTS:
            with self.subTest(path=path):
                self.assertFalse(path.startswith(FINAL_PACK_DOCUMENT_PREFIX))

    def test_the_registry_reports_the_wp24_prose_discrepancy(self):
        document = build_evidence_registry(_ROOT)
        codes = {item["code"] for item in document["findings"]}
        self.assertIn("THS6_PROSE_INVENTORY_DISCREPANCY", codes)

    def test_the_registry_reports_the_unreadable_source_documents(self):
        document = build_evidence_registry(_ROOT)
        codes = {item["code"] for item in document["findings"]}
        self.assertIn("THS6_SOURCE_DOCUMENT_UNAVAILABLE", codes)


class TestResolution(unittest.TestCase):

    def setUp(self):
        self.document = build_evidence_registry(_ROOT)

    def test_the_counts_agree_with_the_items(self):
        items = self.document["items"]
        self.assertEqual(len(items), self.document["declared_count"])
        self.assertEqual(sum(1 for item in items if item["present"]),
                         self.document["present_count"])

    def test_an_absent_item_carries_no_digest(self):
        for item in self.document["items"]:
            if item["present"]:
                continue
            with self.subTest(item=item["evidence_id"]):
                self.assertIsNone(item["sha256"])
                self.assertEqual(item["evidence_type"], "UNAVAILABLE")

    def test_every_present_item_has_a_sha256(self):
        for item in self.document["items"]:
            if not item["present"] or item["evidence_type"] == "INVALID":
                continue
            with self.subTest(item=item["evidence_id"]):
                self.assertRegex(str(item["sha256"]), r"^sha256:[0-9a-f]{64}$")

    def test_every_declared_schema_validated_but_the_known_defect(self):
        """One artifact fails its own schema; the rest satisfy theirs.

        The exception is named rather than tolerated by a wildcard, so a
        second failure would be a test failure rather than a number that
        crept up.
        """
        known_defect = "EV-WP17-001"
        for item in self.document["items"]:
            if not item["schema_path"] or not item["present"]:
                continue
            if item["evidence_id"] == known_defect:
                continue
            with self.subTest(item=item["evidence_id"]):
                self.assertIn(item["validation_result"],
                              ("VALID", "VALID_ANNOTATIONS_SKIPPED"))

    def test_a_vendor_annotation_is_skipped_visibly_not_silently(self):
        """``x-`` keys are stripped before validation, and the verdict says so.

        WP-16 and WP-17 publish route tables and forbidden-property lists as
        ``x-pgx-*`` annotations. This project's validator refuses any keyword
        it does not implement, on the principle that an unchecked published
        constraint is a false assurance. WP-25 keeps that principle by
        recording a different verdict rather than the same word.
        """
        skipped = [item["evidence_id"] for item in self.document["items"]
                   if item["validation_result"] == "VALID_ANNOTATIONS_SKIPPED"]
        self.assertTrue(skipped)
        for item in self.document["items"]:
            with self.subTest(item=item["evidence_id"]):
                self.assertNotEqual(item["validation_result"],
                                    "VALIDATOR_ERROR: SchemaSupportError")

    def test_the_known_wp17_defect_is_repaired_and_the_finding_retired(self):
        """WP-25 found a real defect; WP-C00 fixed it, so it is gone.

        What WP-25 found, and what was true at that time:
        ``data/web/wp17-real-gate-status.json`` recorded
        ``screenshot_evidence_status: "CAPTURED"``, while its own published
        schema, built by ``apps/web/artifacts.py`` in the same run, permitted
        only ``"NONE"`` and ``"BROWSER_CAPTURED"``. The producer, the tests
        and the schema were never compared with each other, so the
        disagreement survived WP-17 through WP-24 unseen. WP-25 recorded it
        rather than repairing another work package's artifact, and said that
        whoever fixed it should retire the finding rather than leave a stale
        one in the pack.

        WP-C00 section A.6 fixed it, at the level of the class rather than
        the instance: the vocabulary now has one home,
        ``apps.web.gate_status.SCREENSHOT_EVIDENCE_STATUSES``, which the
        producer, the published schema and the tests all read, and
        ``tests/unit/web/test_snapshots.py`` now validates the committed
        artifact against the committed schema on every run - the comparison
        nobody had been making. This test is the retirement: it asserts the
        repaired state, so a regression re-fails it.
        """
        invalid = [item for item in self.document["items"]
                   if item["evidence_type"] == "INVALID"]
        self.assertEqual([item["evidence_id"] for item in invalid], [])
        wp17 = [item for item in self.document["items"]
                if item["evidence_id"] == "EV-WP17-001"]
        self.assertEqual(len(wp17), 1)
        self.assertNotIn("INVALID", str(wp17[0]["validation_result"]))

    def test_no_invalid_artifact_finding_remains(self):
        """A retired finding is absent, not present-and-empty."""
        findings = {item["code"]: item
                    for item in self.document["findings"]}
        self.assertNotIn("THS6_EVIDENCE_INVALID", findings)
        for finding in self.document["findings"]:
            if finding["blocking"]:
                self.assertTrue(finding["references"], finding["code"])

    def test_an_invalid_artifact_supports_nothing(self):
        for item in self.document["items"]:
            if item["evidence_type"] != "INVALID":
                continue
            with self.subTest(item=item["evidence_id"]):
                self.assertIs(item["may_support_a_ths6_claim"], False)
                self.assertIsNone(item["sha256"])

    def test_resolution_never_upgrades_a_classification(self):
        """A document does not become real evidence by being present."""
        for declared in DECLARED_EVIDENCE:
            resolved = resolve_evidence(_ROOT, declared)
            if declared.evidence_type.may_support_a_ths6_claim:
                continue
            with self.subTest(item=declared.evidence_id):
                self.assertFalse(
                    resolved.evidence_type.may_support_a_ths6_claim)

    def test_an_absent_artifact_resolves_to_unavailable(self):
        item = EvidenceItem(
            evidence_id="EV-WP00-999", title="t", work_package="WP-00",
            evidence_type=EvidenceType.REAL_EXECUTED,
            path="data/ths6/definitely-not-here.json",
            observed_or_executed=True)
        resolved = resolve_evidence(_ROOT, item)
        self.assertIs(resolved.evidence_type, EvidenceType.UNAVAILABLE)
        self.assertFalse(resolved.observed_or_executed)
        self.assertIsNone(resolved.sha256)

    def test_a_symlink_is_refused_rather_than_hashed(self):
        with tempfile.TemporaryDirectory() as directory:
            target = os.path.join(directory, "real.json")
            with open(target, "w", encoding="utf-8") as handle:
                handle.write("{}\n")
            os.makedirs(os.path.join(directory, "docs"))
            link = os.path.join(directory, "docs", "linked.json")
            try:
                os.symlink(target, link)
            except (OSError, NotImplementedError):  # pragma: no cover
                self.skipTest("this platform does not support symlinks")
            item = EvidenceItem(
                evidence_id="EV-WP00-998", title="t",
                work_package="WP-00",
                evidence_type=EvidenceType.DOCUMENT_ONLY,
                path="docs/linked.json")
            resolved = resolve_evidence(directory, item)
        self.assertIs(resolved.evidence_type, EvidenceType.INVALID)
        self.assertEqual(resolved.validation_result, "SYMLINK_REFUSED")
        self.assertIsNone(resolved.sha256)

    def test_the_admissible_set_is_a_small_minority(self):
        """Most of this repository is implementation, not evidence."""
        self.assertLess(self.document["admissible_count"],
                        self.document["declared_count"] / 2)


class TestDocumentReaders(unittest.TestCase):

    def test_a_missing_field_is_distinguished_from_a_null_one(self):
        document = read_document(
            _ROOT, "data/expert-review/wp22-real-gate-status.json")
        self.assertIsNotNone(document)
        self.assertIsNone(field_at(document, "completed_review_count"))
        self.assertFalse(
            field_is_missing(field_at(document, "completed_review_count")))
        self.assertTrue(field_is_missing(field_at(document, "not_a_field")))

    def test_a_dotted_field_resolves(self):
        document = read_document(_ROOT,
                                 "data/rulesets/wp11-real-gate-status.json")
        self.assertEqual(
            field_at(document, "upstream_state.source_registry_approved"), 0)

    def test_an_absent_artifact_reads_as_none(self):
        self.assertIsNone(read_document(_ROOT, "data/ths6/nothing.json"))


class TestClaimRegistry(unittest.TestCase):

    def setUp(self):
        self.document = build_claim_registry(_ROOT)

    def test_every_probe_resolves_against_this_tree(self):
        """A probe that can never fire looks like diligence and is not."""
        self.assertEqual(unresolvable_probes(_ROOT), ())

    def test_every_claim_names_required_evidence(self):
        for claim in CLAIMS:
            with self.subTest(claim=claim.claim_id):
                self.assertTrue(claim.required_evidence_ids)

    def test_every_required_evidence_id_is_declared(self):
        known = set(declared_by_id())
        for claim in CLAIMS:
            for evidence_id in claim.required_evidence_ids:
                with self.subTest(claim=claim.claim_id, ref=evidence_id):
                    self.assertIn(evidence_id, known)

    def test_claim_identifiers_are_unique(self):
        identifiers = [item.claim_id for item in CLAIMS]
        self.assertEqual(len(identifiers), len(set(identifiers)))

    def test_no_claim_is_supported_in_this_repository(self):
        self.assertEqual(self.document["supported_claim_ids"], [])

    def test_most_claims_are_refuted_by_this_repository_itself(self):
        self.assertGreaterEqual(len(self.document["contradicted_claim_ids"]),
                                20)

    def test_a_contradicted_claim_names_what_refuted_it(self):
        for claim in self.document["claims"]:
            if claim["support"] != "CONTRADICTED":
                continue
            with self.subTest(claim=claim["claim_id"]):
                self.assertIn("refuted by", claim["notes"])

    def test_support_is_never_rounded_up(self):
        for claim in self.document["claims"]:
            with self.subTest(claim=claim["claim_id"]):
                if claim["missing_evidence_ids"]:
                    self.assertNotEqual(claim["support"], "SUPPORTED")

    def test_sufficient_agrees_with_support(self):
        for claim in self.document["claims"]:
            with self.subTest(claim=claim["claim_id"]):
                self.assertEqual(claim["sufficient"],
                                 claim["support"] == "SUPPORTED")

    def test_there_is_no_aggregate_verdict_field(self):
        """Only a gate may draw a conjunction."""
        for name in ("all_supported", "passed", "ok", "verdict"):
            with self.subTest(name=name):
                self.assertNotIn(name, self.document)

    def test_every_dod_bullet_is_cited_by_at_least_one_claim(self):
        from pgx.ths6.definition_of_done import DOD_SPECS

        cited = {dod_id for claim in CLAIMS for dod_id in claim.dod_ids}
        for spec in DOD_SPECS:
            with self.subTest(dod=spec.dod_id):
                self.assertIn(spec.dod_id, cited)

    def test_an_evaluation_with_no_admissible_evidence_is_unsupported(self):
        record = evaluate_claim(_ROOT, CLAIMS[3], admissible={})
        self.assertIn(record.support, (ClaimSupport.UNSUPPORTED,
                                       ClaimSupport.CONTRADICTED))


class TestTraceability(unittest.TestCase):

    def setUp(self):
        self.document = build_traceability(_ROOT)

    def test_nothing_dangles(self):
        dangling = dangling_references(_ROOT)
        for key, value in sorted(dangling.items()):
            with self.subTest(key=key):
                self.assertEqual(list(value), [],
                                 "a matrix citing something absent asserts "
                                 "coverage it does not have")

    def test_every_dod_item_has_a_row(self):
        from pgx.ths6.definition_of_done import DOD_SPECS

        rows = {row["row_id"] for row in self.document["rows"]}
        for spec in DOD_SPECS:
            with self.subTest(dod=spec.dod_id):
                self.assertIn("TRACE-%s" % spec.dod_id, rows)

    def test_every_gate_has_a_row(self):
        rows = {row["row_id"] for row in self.document["rows"]}
        for gate_id in sorted(GATE_IMPLEMENTATION_INDEX):
            with self.subTest(gate=gate_id):
                self.assertIn("TRACE-%s" % gate_id, rows)

    def test_every_row_short_of_supported_names_a_gap_and_an_owner(self):
        for row in self.document["rows"]:
            if row["result"] == "SUPPORTED":
                continue
            with self.subTest(row=row["row_id"]):
                self.assertTrue(row["gap"].strip())
                self.assertTrue((row["gap_owner"] or "").strip())

    def test_every_implementation_path_exists(self):
        for _, (implementations, tests) in sorted(
                IMPLEMENTATION_INDEX.items()):
            for path in tuple(implementations) + tuple(tests):
                with self.subTest(path=path):
                    self.assertTrue(
                        os.path.exists(os.path.join(_ROOT,
                                                    *path.rstrip("/")
                                                    .split("/"))))

    def test_p0_dod_014_is_decided_rather_than_asserted(self):
        self.assertIs(self.document["p0_dod_014_satisfied"], True)
        self.assertIs(self.document["has_dangling_reference"], False)
        self.assertTrue(self.document["p0_dod_014_basis"].strip())

    def test_no_gate_row_is_supported_while_its_gate_is_not_pass(self):
        """Gate rows follow their gate; requirement rows follow themselves.

        The first version of this test applied the gate's verdict to every
        row, which made all twenty-one read UNSUPPORTED - a matrix that
        distinguishes nothing is one nobody can use to find the next thing to
        fix. The conjunction belongs in the gate matrix and is asserted
        there; here it is asserted only of the rows that *are* gates.
        """
        from pgx.ths6.gate_matrix import build_gate_matrix

        results = build_gate_matrix(_ROOT)["results"]
        for row in self.document["rows"]:
            if not row["row_id"].startswith("TRACE-GATE-"):
                continue
            gate_id = row["row_id"][len("TRACE-"):]
            with self.subTest(row=row["row_id"]):
                self.assertEqual(row["result"] == "SUPPORTED",
                                 results[gate_id] == "PASS")

    def test_a_requirement_row_is_supported_only_if_its_bullet_is(self):
        from pgx.ths6.definition_of_done import build_definition_of_done

        satisfied = {item["dod_id"] for item
                     in build_definition_of_done(_ROOT)["items"]
                     if item["satisfied"] is True}
        for row in self.document["rows"]:
            if not row["row_id"].startswith("TRACE-P0-DOD-"):
                continue
            dod_id = row["row_id"][len("TRACE-"):]
            with self.subTest(row=row["row_id"]):
                self.assertEqual(row["result"] == "SUPPORTED",
                                 dod_id in satisfied)

    def test_exactly_one_requirement_row_is_supported(self):
        """The one WP-25 can discharge by itself, and no other."""
        supported = [row["row_id"] for row in self.document["rows"]
                     if row["result"] == "SUPPORTED"]
        self.assertEqual(supported, ["TRACE-P0-DOD-014"])

    def test_the_gap_owners_are_named_roles_not_the_team(self):
        for owner in self.document["gap_owners"]:
            with self.subTest(owner=owner):
                self.assertNotIn("team", owner.lower())
                self.assertNotEqual(owner.strip(), "")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
