# -*- coding: utf-8 -*-
"""Typed identifier contracts (WP-02)."""

from __future__ import annotations

import datetime as _dt
import unittest
import uuid

from tests.unit.domain._fixtures import (  # noqa: F401
    DatasetPublicId, DrugId, EvidenceRecordId, GeneId, SourceRegistryEntryId,
)

from pgx.domain.errors import (
    IdentifierTypeMismatchError, InvalidIdentifierError, InvalidPublicIdentifierError,
)
from pgx.domain.identifiers import (
    AssessmentId, ComputableRuleId, CuratedInterpretationId, DatasetVersionId,
    EntityId, PublicIdentifier, ReleaseBundleId, ReleasePublicId, RulesetPublicId,
    RulesetVersionId, ValidationPublicId, require_id,
)

ALL_ID_TYPES = (
    SourceRegistryEntryId, DatasetVersionId, GeneId, DrugId, EvidenceRecordId,
    CuratedInterpretationId, ComputableRuleId, RulesetVersionId, ReleaseBundleId,
    AssessmentId,
)


class TestIdentifierTypes(unittest.TestCase):

    def test_all_ten_required_identifier_types_exist(self):
        self.assertEqual(len(ALL_ID_TYPES), 10)
        for id_type in ALL_ID_TYPES:
            self.assertTrue(issubclass(id_type, EntityId), id_type.__name__)

    def test_identifiers_of_different_types_are_never_equal(self):
        shared = uuid.uuid4()
        for index, first in enumerate(ALL_ID_TYPES):
            for second in ALL_ID_TYPES[index + 1:]:
                self.assertNotEqual(first(shared), second(shared),
                                    "%s must not equal %s" % (first.__name__, second.__name__))

    def test_same_type_same_value_is_equal_and_hashable(self):
        shared = uuid.uuid4()
        self.assertEqual(GeneId(shared), GeneId(shared))
        self.assertEqual(len({GeneId(shared), GeneId(shared)}), 1)

    def test_wrong_identifier_type_is_rejected_by_require_id(self):
        drug = DrugId.new()
        with self.assertRaises(IdentifierTypeMismatchError) as ctx:
            require_id(drug, GeneId, "gene_id")
        self.assertIn("GeneId", str(ctx.exception))
        self.assertIn("DrugId", str(ctx.exception))

    def test_require_id_accepts_the_exact_type(self):
        gene = GeneId.new()
        self.assertIs(require_id(gene, GeneId, "gene_id"), gene)

    def test_raw_uuid_is_not_accepted_where_a_typed_id_is_required(self):
        with self.assertRaises(IdentifierTypeMismatchError):
            require_id(uuid.uuid4(), GeneId, "gene_id")

    def test_identifier_requires_a_real_uuid(self):
        for bad in ("not-a-uuid", 42, None, uuid.uuid4().hex):
            with self.assertRaises(InvalidIdentifierError, msg=repr(bad)):
                GeneId(bad)

    def test_identifiers_are_immutable(self):
        gene = GeneId.new()
        with self.assertRaises(Exception):
            gene.value = uuid.uuid4()

    def test_parse_is_explicit_and_validated(self):
        raw = str(uuid.uuid4())
        self.assertEqual(GeneId.parse(raw).to_json(), raw)
        with self.assertRaises(InvalidIdentifierError):
            GeneId.parse("nope")
        with self.assertRaises(InvalidIdentifierError):
            GeneId.parse(123)

    def test_new_is_the_only_source_of_randomness(self):
        self.assertNotEqual(GeneId.new(), GeneId.new())

    def test_derive_is_deterministic_and_type_scoped(self):
        first = SourceRegistryEntryId.derive("pgx-internal-system")
        second = SourceRegistryEntryId.derive("pgx-internal-system")
        self.assertEqual(first, second)
        self.assertNotEqual(first, SourceRegistryEntryId.derive("other"))
        with self.assertRaises(InvalidIdentifierError):
            SourceRegistryEntryId.derive("")

    def test_json_representation_is_stable(self):
        value = uuid.uuid4()
        self.assertEqual(GeneId(value).to_json(), str(value))
        self.assertEqual(str(GeneId(value)), str(value))


class TestPublicIdentifiers(unittest.TestCase):

    VALID = {
        DatasetPublicId: "PGX-DATA-20260829-001",
        RulesetPublicId: "PGX-RULESET-20260829-042",
        ReleasePublicId: "PGX-REL-20260829-999",
        ValidationPublicId: "PGX-VAL-20260101-007",
    }

    def test_each_public_identifier_accepts_its_own_format(self):
        for id_type, value in self.VALID.items():
            self.assertEqual(id_type(value).to_json(), value)

    def test_a_public_identifier_rejects_another_families_prefix(self):
        for id_type, value in self.VALID.items():
            for other_type, other_value in self.VALID.items():
                if other_type is id_type:
                    continue
                with self.assertRaises(InvalidPublicIdentifierError,
                                       msg="%s accepted %s" % (id_type.__name__, other_value)):
                    id_type(other_value)

    def test_malformed_values_are_rejected(self):
        bad_values = (
            "PGX-DATA-20260829-000",     # sequence must start at 001
            "PGX-DATA-20261332-001",     # impossible date
            "PGX-DATA-2026829-001",      # short date
            "PGX-DATA-20260829-1",       # short sequence
            "PGX-DATA-20260829-0001",    # long sequence
            "pgx-data-20260829-001",     # lower case
            " PGX-DATA-20260829-001",    # leading space
            "PGX-DATA-20260829-001 ",    # trailing space
            "",
        )
        for value in bad_values:
            with self.assertRaises(InvalidPublicIdentifierError, msg=repr(value)):
                DatasetPublicId(value)

    def test_non_string_is_rejected(self):
        for bad in (None, 20260829, uuid.uuid4()):
            with self.assertRaises(InvalidPublicIdentifierError):
                DatasetPublicId(bad)

    def test_compose_round_trips(self):
        composed = DatasetPublicId.compose(_dt.date(2026, 8, 29), 7)
        self.assertEqual(composed.value, "PGX-DATA-20260829-007")
        self.assertEqual(composed.issued_on, _dt.date(2026, 8, 29))
        self.assertEqual(composed.sequence, 7)

    def test_compose_rejects_out_of_range_sequences(self):
        for sequence in (0, -1, 1000, True, "1"):
            with self.assertRaises(InvalidPublicIdentifierError, msg=repr(sequence)):
                DatasetPublicId.compose(_dt.date(2026, 8, 29), sequence)

    def test_public_identifiers_are_immutable(self):
        identifier = DatasetPublicId("PGX-DATA-20260829-001")
        with self.assertRaises(Exception):
            identifier.value = "PGX-DATA-20260829-002"

    def test_base_public_identifier_has_a_documented_format_hint(self):
        self.assertEqual(PublicIdentifier.format_hint(), "PGX-YYYYMMDD-NNN")
        self.assertEqual(DatasetPublicId.format_hint(), "PGX-DATA-YYYYMMDD-NNN")


if __name__ == "__main__":
    unittest.main(verbosity=2)
