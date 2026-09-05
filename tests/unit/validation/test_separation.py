# -*- coding: utf-8 -*-
"""The eight ways a partition breaks, and that each is caught (WP-18).

``SAFETY-INV-009``. Each test below builds a case set that is wrong in exactly
one way, and asserts that the audit names that way. The point of doing them
one at a time is that the rules are not variations of each other: four of
these sets would pass every check but the one they target.
"""

from __future__ import annotations

import unittest

from pgx.validation.cases import ValidationCaseId
from pgx.validation.compatibility import ReleaseCompatibility, UNPINNED
from pgx.validation.errors import SeparationError
from pgx.validation.separation import (SEPARATION_AUDIT_VERSION,
                                       SeparationIssue, audit_partition,
                                       require_separation)
from pgx.validation.vocabulary import (SEPARATION_ISSUE_CODES,
                                       ValidationCaseRole)
from tests.fixtures.wp18.synthetic import (case, content, development_case,
                                           expert_holdout_case,
                                           internal_holdout_case, provenance)


class TestACleanPartitionIsClean(unittest.TestCase):

    def test_development_and_an_unrelated_holdout_pass(self):
        audit = audit_partition([development_case(),
                                 internal_holdout_case()])
        self.assertTrue(audit.is_clean, audit.issue_codes)

    def test_an_empty_set_is_clean_and_counted(self):
        audit = audit_partition([])
        self.assertTrue(audit.is_clean)
        self.assertEqual(audit.checked_case_count, 0)

    def test_the_audit_reads_no_payload(self):
        """So anyone may run it - including a rule author.

        An audit that required payload access could only be run by somebody
        allowed to see holdout, which is nobody on the authoring side, which
        would mean it never ran.

        Checked as a syntax tree rather than as text: the module's prose is
        full of the words "content" and "payload" because that is what it is
        about, and a substring search would fail on its own docstring - the
        same trap a documentation check falls into when it quotes the pattern
        it forbids.
        """
        import ast
        import inspect

        from pgx.validation import separation

        parsed = ast.parse(inspect.getsource(separation))

        imported = set()
        for node in ast.walk(parsed):
            if isinstance(node, ast.ImportFrom):
                imported.update(alias.name for alias in node.names)
        self.assertNotIn("RestrictedPayload", imported,
                         "the audit imports the payload type")

        attributes = {node.attr for node in ast.walk(parsed)
                      if isinstance(node, ast.Attribute)}
        for forbidden in ("content", "payload", "payload_hash",
                          "read_payload", "fingerprint"):
            self.assertNotIn(forbidden, attributes,
                             "the audit reads .%s from something" % forbidden)


class TestRoleOverlap(unittest.TestCase):

    def test_one_identifier_in_two_roles_is_refused(self):
        audit = audit_partition([
            case("PGX-VAL-BOTH-1", ValidationCaseRole.DEVELOPMENT,
                 prov=provenance(development=True)),
            case("PGX-VAL-BOTH-1", ValidationCaseRole.INTERNAL_HOLDOUT,
                 body=content(gene="GENE:TESTGENE2"),
                 prov=provenance(development=False))])
        self.assertIn("ROLE_OVERLAP", audit.issue_codes)

    def test_the_issue_names_the_case(self):
        audit = audit_partition([
            case("PGX-VAL-BOTH-2", ValidationCaseRole.DEVELOPMENT,
                 prov=provenance(development=True)),
            case("PGX-VAL-BOTH-2", ValidationCaseRole.EXPERT_HOLDOUT,
                 body=content(gene="GENE:TESTGENE2"),
                 prov=provenance(development=False))])
        overlap = [issue for issue in audit.issues
                   if issue.code == "ROLE_OVERLAP"]
        self.assertEqual(overlap[0].case_ids, ("PGX-VAL-BOTH-2",))


class TestContentDuplicates(unittest.TestCase):

    def test_the_same_content_across_partitions_is_refused(self):
        """Copying a case and renaming it. Different id, same case."""
        body = content()
        audit = audit_partition([
            case("PGX-VAL-DEV-DUP1", ValidationCaseRole.DEVELOPMENT,
                 body=body, prov=provenance(development=True)),
            case("PGX-VAL-INT-DUP1", ValidationCaseRole.INTERNAL_HOLDOUT,
                 body=body,
                 prov=provenance(development=False,
                                 source="TEST-SOURCE/other"))])
        self.assertIn("CONTENT_DUPLICATE_ACROSS_PARTITIONS",
                      audit.issue_codes)

    def test_the_same_content_within_one_partition_is_refused(self):
        """Not a leak - a denominator that counts one case twice."""
        body = content()
        audit = audit_partition([
            case("PGX-VAL-INT-DUP2", ValidationCaseRole.INTERNAL_HOLDOUT,
                 body=body, prov=provenance(development=False)),
            case("PGX-VAL-INT-DUP3", ValidationCaseRole.INTERNAL_HOLDOUT,
                 body=body,
                 prov=provenance(development=False,
                                 source="TEST-SOURCE/other"))])
        self.assertIn("CONTENT_DUPLICATE_WITHIN_PARTITION", audit.issue_codes)

    def test_reordered_content_is_still_a_duplicate(self):
        """Because the fingerprint is canonical, not literal."""
        left = {"observations": [{"gene": "GENE:TESTGENE1", "value": "POOR"},
                                 {"gene": "GENE:TESTGENE2",
                                  "value": "NORMAL"}]}
        right = {"observations": list(reversed(left["observations"]))}
        audit = audit_partition([
            case("PGX-VAL-DEV-DUP4", ValidationCaseRole.DEVELOPMENT,
                 body=left, prov=provenance(development=True)),
            case("PGX-VAL-INT-DUP4", ValidationCaseRole.INTERNAL_HOLDOUT,
                 body=right,
                 prov=provenance(development=False,
                                 source="TEST-SOURCE/other"))])
        self.assertIn("CONTENT_DUPLICATE_ACROSS_PARTITIONS",
                      audit.issue_codes)

    def test_two_similar_but_distinct_cases_are_not_reported(self):
        """The false-collapse direction, checked at the audit level too."""
        audit = audit_partition([
            case("PGX-VAL-DEV-NEAR1", ValidationCaseRole.DEVELOPMENT,
                 body=content(value="POOR"),
                 prov=provenance(development=True)),
            case("PGX-VAL-INT-NEAR1", ValidationCaseRole.INTERNAL_HOLDOUT,
                 body=content(value="RAPID"),
                 prov=provenance(development=False,
                                 source="TEST-SOURCE/other"))])
        self.assertTrue(audit.is_clean, audit.issue_codes)


class TestDerivationFamilySplit(unittest.TestCase):
    """The pair no content fingerprint can catch.

    Different identifiers, different content, one source vignette, one method.
    Whoever wrote the development case has read the source the holdout came
    from, so the holdout is no longer independent - and nothing about the two
    documents looks alike.
    """

    def test_one_family_across_partitions_is_refused(self):
        family = provenance(development=False, source="TEST-VIGNETTE/7",
                            method="TEST manual transcription")
        audit = audit_partition([
            case("PGX-VAL-DEV-FAM1", ValidationCaseRole.DEVELOPMENT,
                 body=content(value="POOR"),
                 prov=provenance(development=True, source="TEST-VIGNETTE/7",
                                 method="TEST manual transcription")),
            case("PGX-VAL-INT-FAM1", ValidationCaseRole.INTERNAL_HOLDOUT,
                 body=content(gene="GENE:TESTGENE2", value="NORMAL"),
                 prov=family)])
        self.assertIn("DERIVATION_FAMILY_SPLIT", audit.issue_codes)

    def test_neither_content_nor_identifier_would_have_caught_it(self):
        left = case("PGX-VAL-DEV-FAM2", ValidationCaseRole.DEVELOPMENT,
                    body=content(value="POOR"),
                    prov=provenance(development=True,
                                    source="TEST-VIGNETTE/8",
                                    method="TEST transcription"))
        right = case("PGX-VAL-INT-FAM2", ValidationCaseRole.INTERNAL_HOLDOUT,
                     body=content(gene="GENE:TESTGENE2", value="NORMAL"),
                     prov=provenance(development=False,
                                     source="TEST-VIGNETTE/8",
                                     method="TEST transcription"))
        self.assertNotEqual(left.case_id.value, right.case_id.value)
        self.assertNotEqual(left.content_fingerprint,
                            right.content_fingerprint)
        self.assertIn("DERIVATION_FAMILY_SPLIT",
                      audit_partition([left, right]).issue_codes)

    def test_one_family_inside_one_partition_is_fine(self):
        """Two development cases from one source is ordinary work."""
        audit = audit_partition([
            case("PGX-VAL-DEV-FAM3", ValidationCaseRole.DEVELOPMENT,
                 body=content(value="POOR"),
                 prov=provenance(development=True, source="TEST-VIGNETTE/9")),
            case("PGX-VAL-DEV-FAM4", ValidationCaseRole.DEVELOPMENT,
                 body=content(value="RAPID"),
                 prov=provenance(development=True, source="TEST-VIGNETTE/9"))])
        self.assertTrue(audit.is_clean, audit.issue_codes)


class TestHoldoutObligations(unittest.TestCase):

    def test_a_holdout_derived_from_development_cannot_be_built(self):
        """Refused at construction, so the audit never sees one."""
        from pgx.validation.errors import ProvenanceError

        with self.assertRaises(ProvenanceError):
            internal_holdout_case(prov=provenance(development=True))

    def test_a_holdout_without_provenance_cannot_be_built(self):
        from pgx.validation.errors import ProvenanceError

        with self.assertRaises(ProvenanceError):
            internal_holdout_case(prov=provenance(development=False,
                                                  citation=None, digest=None))

    def test_the_audit_still_reports_them_if_one_appears(self):
        """Belt and braces: the audit does not rely on the constructor.

        A case could reach an audit from a file, a future adapter or a
        deserialiser that has not been written yet.
        """
        self.assertIn("HOLDOUT_DERIVED_FROM_DEVELOPMENT",
                      SEPARATION_ISSUE_CODES)
        self.assertIn("HOLDOUT_PROVENANCE_MISSING", SEPARATION_ISSUE_CODES)


class TestRelabelling(unittest.TestCase):
    """Invisible in a single snapshot - so the audit takes a previous record."""

    def test_development_becoming_holdout_is_refused(self):
        audit = audit_partition(
            [internal_holdout_case("PGX-VAL-INT-RELABEL")],
            previous_roles={"PGX-VAL-INT-RELABEL": "DEVELOPMENT"})
        self.assertIn("DEVELOPMENT_RELABELLED_AS_HOLDOUT", audit.issue_codes)

    def test_any_other_role_change_is_an_overlap(self):
        audit = audit_partition(
            [internal_holdout_case("PGX-VAL-INT-RELABEL2")],
            previous_roles={"PGX-VAL-INT-RELABEL2": "EXPERT_HOLDOUT"})
        self.assertIn("ROLE_OVERLAP", audit.issue_codes)

    def test_an_unchanged_role_is_not_reported(self):
        audit = audit_partition(
            [internal_holdout_case("PGX-VAL-INT-SAME")],
            previous_roles={"PGX-VAL-INT-SAME": "INTERNAL_HOLDOUT"})
        self.assertTrue(audit.is_clean, audit.issue_codes)

    def test_a_case_absent_from_the_previous_record_is_not_reported(self):
        audit = audit_partition([internal_holdout_case("PGX-VAL-INT-NEW")],
                                previous_roles={"PGX-VAL-OTHER-1":
                                                "DEVELOPMENT"})
        self.assertTrue(audit.is_clean, audit.issue_codes)


class TestReleaseCompatibilityConflicts(unittest.TestCase):

    def test_two_pinned_and_different_rulesets_conflict(self):
        audit = audit_partition([
            case("PGX-VAL-INT-REL1", ValidationCaseRole.INTERNAL_HOLDOUT,
                 body=content(value="POOR"),
                 prov=provenance(development=False, source="TEST-A"),
                 compatibility=ReleaseCompatibility(
                     ruleset_public_id="PGX-RULESET-29991231-001")),
            case("PGX-VAL-INT-REL2", ValidationCaseRole.INTERNAL_HOLDOUT,
                 body=content(value="RAPID"),
                 prov=provenance(development=False, source="TEST-B"),
                 compatibility=ReleaseCompatibility(
                     ruleset_public_id="PGX-RULESET-29991231-002"))])
        self.assertIn("RELEASE_COMPATIBILITY_CONFLICT", audit.issue_codes)

    def test_silence_is_not_a_conflict(self):
        """One case saying less is not two cases disagreeing."""
        audit = audit_partition([
            case("PGX-VAL-INT-REL3", ValidationCaseRole.INTERNAL_HOLDOUT,
                 body=content(value="POOR"),
                 prov=provenance(development=False, source="TEST-A"),
                 compatibility=ReleaseCompatibility(
                     ruleset_public_id="PGX-RULESET-29991231-001")),
            case("PGX-VAL-INT-REL4", ValidationCaseRole.INTERNAL_HOLDOUT,
                 body=content(value="RAPID"),
                 prov=provenance(development=False, source="TEST-B"),
                 compatibility=UNPINNED("1.0.0"))])
        self.assertTrue(audit.is_clean, audit.issue_codes)

    def test_partitions_are_checked_separately(self):
        """Development and holdout may legitimately differ."""
        audit = audit_partition([
            case("PGX-VAL-DEV-REL5", ValidationCaseRole.DEVELOPMENT,
                 body=content(value="POOR"),
                 prov=provenance(development=True),
                 compatibility=ReleaseCompatibility(
                     ruleset_public_id="PGX-RULESET-29991231-001")),
            case("PGX-VAL-INT-REL5", ValidationCaseRole.INTERNAL_HOLDOUT,
                 body=content(gene="GENE:TESTGENE2", value="RAPID"),
                 prov=provenance(development=False, source="TEST-B"),
                 compatibility=ReleaseCompatibility(
                     ruleset_public_id="PGX-RULESET-29991231-002"))])
        self.assertNotIn("RELEASE_COMPATIBILITY_CONFLICT", audit.issue_codes)


class TestTheAuditReportsEverythingAtOnce(unittest.TestCase):

    def test_several_faults_are_all_named(self):
        body = content()
        audit = audit_partition([
            case("PGX-VAL-DEV-MULTI", ValidationCaseRole.DEVELOPMENT,
                 body=body, prov=provenance(development=True,
                                            source="TEST-SHARED")),
            case("PGX-VAL-INT-MULTI", ValidationCaseRole.INTERNAL_HOLDOUT,
                 body=body, prov=provenance(development=False,
                                            source="TEST-SHARED"))])
        self.assertIn("CONTENT_DUPLICATE_ACROSS_PARTITIONS",
                      audit.issue_codes)
        self.assertIn("DERIVATION_FAMILY_SPLIT", audit.issue_codes)

    def test_it_returns_rather_than_raising(self):
        """Somebody repairing a dataset wants the list, not a round trip."""
        audit = audit_partition([
            case("PGX-VAL-DEV-R1", ValidationCaseRole.DEVELOPMENT,
                 prov=provenance(development=True)),
            case("PGX-VAL-DEV-R1", ValidationCaseRole.INTERNAL_HOLDOUT,
                 body=content(gene="GENE:TESTGENE2"),
                 prov=provenance(development=False))])
        self.assertFalse(audit.is_clean)

    def test_require_separation_raises_for_write_paths(self):
        with self.assertRaises(SeparationError) as caught:
            require_separation([
                case("PGX-VAL-DEV-R2", ValidationCaseRole.DEVELOPMENT,
                     prov=provenance(development=True)),
                case("PGX-VAL-DEV-R2", ValidationCaseRole.INTERNAL_HOLDOUT,
                     body=content(gene="GENE:TESTGENE2"),
                     prov=provenance(development=False))])
        self.assertIn("ROLE_OVERLAP", caught.exception.issue_codes)

    def test_an_unknown_issue_code_cannot_be_reported(self):
        with self.assertRaises(SeparationError):
            SeparationIssue("MADE_UP_CODE", ("PGX-VAL-X-1",), "")


class TestTheAuditCarriesNoContent(unittest.TestCase):
    """It is read by people who may not read the cases it describes."""

    def test_the_rendered_audit_names_identifiers_only(self):
        body = {"observations": [{"gene": "GENE:TESTGENE1",
                                  "value": "TEST-SECRET-VALUE"}]}
        audit = audit_partition([
            case("PGX-VAL-DEV-S1", ValidationCaseRole.DEVELOPMENT, body=body,
                 prov=provenance(development=True, source="TEST-SHARED2")),
            case("PGX-VAL-INT-S1", ValidationCaseRole.INTERNAL_HOLDOUT,
                 body=body, prov=provenance(development=False,
                                            source="TEST-SHARED2"))])
        import json

        rendered = json.dumps(audit.to_json())
        self.assertNotIn("TEST-SECRET-VALUE", rendered)
        self.assertIn("PGX-VAL-INT-S1", rendered)

    def test_it_names_its_version_and_the_rules_it_checked(self):
        document = audit_partition([]).to_json()
        self.assertEqual(document["audit_version"], SEPARATION_AUDIT_VERSION)
        self.assertEqual(sorted(document["checked_rules"]),
                         sorted(SEPARATION_ISSUE_CODES))
