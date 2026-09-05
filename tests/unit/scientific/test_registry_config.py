# -*- coding: utf-8 -*-
"""The checked-in registry, and the state it must be in.

This is the test that keeps the repository honest. Every source in
``config/scientific-sources.json`` must be unapproved, with every reuse question
unanswered and no licence identifier, because nobody has done source review and
no official terms document has been retrieved. If somebody later fills one of
those fields in without a review record attached, the loader refuses the file
and this suite fails - which is the point.

It also checks the file is in canonical form and that the JSON schema shipped
beside it still matches the vocabularies the code uses, so a schema-valid file
can never fail to load for a reason the schema could have caught.
"""

from __future__ import annotations

import datetime as _dt
import io
import json
import os
import unittest

from pgx.domain.enums import SourceRole
from pgx.scientific.models import (
    REUSE_DIMENSIONS,
    AcquisitionMode,
    ClaimCategory,
    ConflictMateriality,
    ConflictStatus,
    EvidenceType,
    EvidenceVerificationStatus,
    ReusePermission,
    ReviewDecision,
    SourcePolicyStatus,
)
from pgx.scientific.policy import (
    SOURCE_REGISTRY_SCHEMA_VERSION,
    load_registry,
    registry_from_json,
    render_registry,
)
from pgx.scientific.validation import (
    PolicyIssueCode,
    approved_source_keys,
    blocking_issues,
    issue_summary,
    validate_registry,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
CONFIG_PATH = os.path.join(REPO_ROOT, "config", "scientific-sources.json")
SCHEMA_PATH = os.path.join(REPO_ROOT, "schemas",
                           "scientific-source-registry.schema.json")
NOW = _dt.datetime(2026, 8, 30, 12, 0, 0, tzinfo=_dt.timezone.utc)


def _read(path):
    with io.open(path, encoding="utf-8") as handle:
        return handle.read()


class TestTheCheckedInRegistryLoads(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.registry = load_registry(CONFIG_PATH)
        cls.raw = json.loads(_read(CONFIG_PATH))

    def test_it_declares_the_schema_version_this_build_understands(self):
        self.assertEqual(self.registry.schema_version,
                         SOURCE_REGISTRY_SCHEMA_VERSION)

    def test_it_carries_the_candidate_sources_wp05_asks_for(self):
        keys = set(self.registry.source_keys)
        for provider in ("clinpgx", "cpic", "dpwg", "druglabel", "internal"):
            with self.subTest(provider=provider):
                self.assertTrue(any(key.startswith(provider) for key in keys),
                                "no candidate entry for %s" % provider)

    def test_drug_labels_are_registered_per_jurisdiction(self):
        """A US label statement is not a Turkish one."""
        labels = [r for r in self.registry.records
                  if r.source_key.startswith("druglabel")]
        self.assertGreaterEqual(len(labels), 3)
        for record in labels:
            with self.subTest(source=record.source_key):
                self.assertIsNotNone(record.jurisdiction)
        self.assertEqual(len(labels),
                         len({r.jurisdiction for r in labels}))

    def test_the_file_is_in_canonical_form(self):
        """Rendering what was loaded reproduces the file byte for byte."""
        self.assertEqual(render_registry(self.registry), _read(CONFIG_PATH))

    def test_it_round_trips_without_changing_content(self):
        rebuilt = registry_from_json(self.registry.to_json())
        self.assertEqual(rebuilt.content_hash(), self.registry.content_hash())

    def test_source_keys_are_unique_and_sorted(self):
        keys = list(self.registry.source_keys)
        self.assertEqual(keys, sorted(set(keys)))


class TestTheDefaultStateApprovesNothing(unittest.TestCase):
    """No human has reviewed any source, so the project publishes nothing."""

    @classmethod
    def setUpClass(cls):
        cls.registry = load_registry(CONFIG_PATH)

    def test_no_source_is_approved(self):
        self.assertEqual(self.registry.approved_records, ())
        self.assertEqual(approved_source_keys(self.registry, NOW), ())

    def test_every_source_is_pending_review(self):
        for record in self.registry.records:
            with self.subTest(source=record.source_key):
                self.assertIs(record.status, SourcePolicyStatus.PENDING_REVIEW)

    def test_no_source_carries_a_review_record(self):
        for record in self.registry.records:
            with self.subTest(source=record.source_key):
                self.assertIsNone(record.review)

    def test_no_reviewer_name_appears_anywhere_in_the_file(self):
        """Including the synthetic one the tests use for their own fixtures."""
        text = _read(CONFIG_PATH)
        self.assertNotIn("TEST_SCIENTIFIC" + "_REVIEWER", text)
        self.assertNotIn('"reviewer_name"', text)

    def test_no_source_claims_a_licence_identifier(self):
        """Never guessed. No terms document has been read."""
        for record in self.registry.records:
            with self.subTest(source=record.source_key):
                self.assertIsNone(record.license_identifier)

    def test_no_source_claims_a_version_or_citation_policy(self):
        for record in self.registry.records:
            with self.subTest(source=record.source_key):
                self.assertIsNone(record.version_policy)
                self.assertIsNone(record.citation_policy)

    def test_every_reuse_question_is_unanswered(self):
        for record in self.registry.records:
            with self.subTest(source=record.source_key):
                self.assertEqual(len(record.reuse.unknown_dimensions),
                                 len(REUSE_DIMENSIONS))

    def test_no_source_names_a_permitted_claim_category(self):
        for record in self.registry.records:
            with self.subTest(source=record.source_key):
                self.assertEqual(record.permitted_claim_categories, ())

    def test_no_source_holds_verified_official_evidence(self):
        for record in self.registry.records:
            with self.subTest(source=record.source_key):
                self.assertFalse(record.has_official_evidence)

    def test_external_sources_have_no_decided_acquisition_mode(self):
        for record in self.registry.records:
            if record.role is SourceRole.INTERNAL_SYSTEM:
                continue
            with self.subTest(source=record.source_key):
                self.assertIs(record.acquisition_mode,
                              AcquisitionMode.NOT_DETERMINED)

    def test_every_source_says_what_is_outstanding(self):
        for record in self.registry.records:
            with self.subTest(source=record.source_key):
                self.assertTrue(record.blocking_reasons)

    def test_validation_reports_blockers_for_every_source(self):
        issues = validate_registry(self.registry, NOW)
        blocked = {issue.subject for issue in blocking_issues(issues)}
        for record in self.registry.records:
            if record.role is SourceRole.INTERNAL_SYSTEM:
                continue
            with self.subTest(source=record.source_key):
                self.assertIn(record.source_key, blocked)

    def test_the_summary_counts_every_severity_even_at_zero(self):
        counts = issue_summary(validate_registry(self.registry, NOW))
        self.assertEqual(set(counts), {"BLOCKER", "WARNING", "INFO"})
        self.assertGreater(counts["BLOCKER"], 0)


class TestTheClinPgxProbeIsRecordedAsBlockedNotApproved(unittest.TestCase):
    """Network failure must never have been converted into permission."""

    @classmethod
    def setUpClass(cls):
        cls.registry = load_registry(CONFIG_PATH)

    def test_the_clinpgx_entries_record_a_blocked_retrieval(self):
        for key in ("clinpgx.api", "clinpgx.website"):
            record = self.registry.require(key)
            with self.subTest(source=key):
                blocked = [item for item in record.evidence
                           if item.verification
                           is EvidenceVerificationStatus.BLOCKED]
                self.assertTrue(blocked, "no blocked retrieval recorded")
                self.assertTrue(all(item.blocked_reason for item in blocked))

    def test_a_blocked_retrieval_is_not_official_evidence(self):
        for key in ("clinpgx.api", "clinpgx.website"):
            with self.subTest(source=key):
                self.assertFalse(self.registry.require(key).has_official_evidence)

    def test_the_blocked_entries_still_block(self):
        codes = {issue.code for issue in validate_registry(self.registry, NOW)}
        self.assertIn(PolicyIssueCode.EVIDENCE_RETRIEVAL_BLOCKED, codes)


class TestLegacySourceValuesAllResolve(unittest.TestCase):
    """Every source name the frozen data cites has a policy record."""

    def test_the_named_legacy_bodies_are_registered(self):
        registry = load_registry(CONFIG_PATH)
        aliases = set()
        for record in registry.records:
            aliases.update(record.legacy_aliases)
        for legacy_value in ("CPIC", "DPWG", "RNPGx", "AHA", "AusNZ", "CPNDS",
                             "ClinPGx"):
            with self.subTest(value=legacy_value):
                self.assertIn(legacy_value, aliases)


class TestTheJsonSchemaMatchesTheCode(unittest.TestCase):
    """A schema-valid file must never fail to load for a schema-shaped reason."""

    @classmethod
    def setUpClass(cls):
        cls.schema = json.loads(_read(SCHEMA_PATH))

    def _enum_at(self, *path):
        node = self.schema
        for step in path:
            node = node[step]
        return set(node["enum"])

    def test_the_schema_version_constant_agrees(self):
        self.assertEqual(
            self.schema["properties"]["schema_version"]["const"],
            SOURCE_REGISTRY_SCHEMA_VERSION)

    def test_every_vocabulary_is_enumerated_completely(self):
        cases = (
            (("$defs", "permission"), ReusePermission),
            (("$defs", "source", "properties", "status"), SourcePolicyStatus),
            (("$defs", "source", "properties", "role"), SourceRole),
            (("$defs", "source", "properties", "acquisition_mode"),
             AcquisitionMode),
            (("$defs", "evidence", "properties", "evidence_type"), EvidenceType),
            (("$defs", "evidence", "properties", "verification"),
             EvidenceVerificationStatus),
            (("$defs", "review", "properties", "decision"), ReviewDecision),
            (("$defs", "conflict", "properties", "status"), ConflictStatus),
            (("$defs", "conflict", "properties", "materiality"),
             ConflictMateriality),
        )
        for path, vocabulary in cases:
            with self.subTest(path="/".join(path)):
                self.assertEqual(self._enum_at(*path),
                                 {m.value for m in vocabulary})

    def test_the_claim_categories_are_enumerated(self):
        node = self.schema["$defs"]["source"]["properties"][
            "permitted_claim_categories"]["items"]
        self.assertEqual(set(node["enum"]), {m.value for m in ClaimCategory})

    def test_every_reuse_dimension_has_a_property(self):
        node = self.schema["$defs"]["source"]["properties"]["reuse"]
        self.assertEqual(set(node["properties"]),
                         {d.value for d in REUSE_DIMENSIONS})
        self.assertFalse(node["additionalProperties"])

    def test_unknown_keys_are_refused_everywhere(self):
        for name in ("source", "evidence", "review", "conflict",
                     "interpretation"):
            with self.subTest(definition=name):
                self.assertFalse(self.schema["$defs"][name]["additionalProperties"])

    def test_the_generator_output_is_current(self):
        """The schema is generated; a stale copy would drift from the code."""
        import sys
        scripts = os.path.join(REPO_ROOT, "scripts")
        if scripts not in sys.path:
            sys.path.insert(0, scripts)
        from render_source_registry_schema import render
        self.assertEqual(render(), _read(SCHEMA_PATH))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
