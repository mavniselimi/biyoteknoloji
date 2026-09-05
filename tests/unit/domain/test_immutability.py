# -*- coding: utf-8 -*-
"""Proof that the domain's "immutable" claim is literally true (WP-02 corrective).

A ``@dataclass(frozen=True)`` only stops attribute *rebinding*. Before this
pass the models stored plain dicts, so ``model.metadata["k"] = "v"`` succeeded
and the documented immutability claim was false. These tests are the evidence
behind the claim: until they pass, the word "immutable" must not appear in the
WP-02 documentation.

Nine properties are proven here, each against real model instances rather than
against :mod:`pgx.domain.immutable` in isolation:

1. top-level key assignment on a metadata mapping fails;
2. nested mapping assignment fails;
3. nested list mutation fails;
4. deeply nested (3+ levels) mapping assignment fails;
5. mutating helpers (``update``/``pop``/``clear``/``setdefault``/``__delitem__``)
   are absent or refuse;
6. attribute assignment on the frozen mapping itself fails;
7. mutating the caller's original object after construction cannot reach the
   model (defensive copy);
8. non-JSON values are rejected at construction, not silently coerced;
9. the shared empty-metadata default is immutable, so one caller cannot
   poison every other model's default.

Standard library only.
"""

from __future__ import annotations

import math
import types
import unittest

from tests.unit.domain._fixtures import (
    NOW, make_evidence, make_rule,
)

from pgx.domain.identifiers import GeneId
from pgx.domain.models import Gene

from pgx.domain.errors import DomainInvariantError
from pgx.domain.hashing import sha256_digest
from pgx.domain.immutable import (
    EMPTY_MAPPING, FrozenMapping, MAX_JSON_DEPTH, freeze_json, is_frozen_json,
    thaw_json,
)
from pgx.domain import models as models_module


def _gene(external_ids=None) -> Gene:
    """A minimal valid gene; the only model carrying ``external_ids``."""
    values = dict(id=GeneId.new(), normalized_symbol="CYP2C19",
                  preferred_name="CYP2C19", created_at=NOW)
    if external_ids is not None:
        values["external_ids"] = external_ids
    return Gene(**values)


NESTED = {
    "outer": {"middle": {"inner": ["a", "b"], "flag": True}},
    "list_of_maps": [{"k": 1}, {"k": 2}],
    "scalar": 7,
}


class TestTopLevelAssignmentIsRejected(unittest.TestCase):
    """Proof 1: ``model.metadata["k"] = v`` must not succeed."""

    def test_evidence_metadata_rejects_item_assignment(self):
        record = make_evidence(evidence_metadata={"level": "1A"})
        with self.assertRaises(DomainInvariantError):
            record.evidence_metadata["level"] = "TAMPERED"
        self.assertEqual(record.evidence_metadata["level"], "1A")

    def test_publication_metadata_rejects_item_assignment(self):
        record = make_evidence(publication_metadata={"pmid": "1"})
        with self.assertRaises(DomainInvariantError):
            record.publication_metadata["pmid"] = "2"

    def test_external_ids_rejects_item_assignment(self):
        gene = _gene({"pharmgkb": "PA123"})
        with self.assertRaises(DomainInvariantError):
            gene.external_ids["pharmgkb"] = "PA999"
        self.assertEqual(gene.external_ids["pharmgkb"], "PA123")

    def test_rule_condition_rejects_item_assignment(self):
        rule = make_rule(condition={"gene": "CYP2C19"})
        with self.assertRaises(DomainInvariantError):
            rule.condition["gene"] = "CYP2D6"
        self.assertEqual(rule.condition["gene"], "CYP2C19")


class TestNestedMappingAssignmentIsRejected(unittest.TestCase):
    """Proof 2: freezing is recursive, not shallow."""

    def test_nested_mapping_rejects_assignment(self):
        rule = make_rule(condition={"match": {"gene": "CYP2C19"}})
        with self.assertRaises(DomainInvariantError):
            rule.condition["match"]["gene"] = "CYP2D6"
        self.assertEqual(rule.condition["match"]["gene"], "CYP2C19")

    def test_nested_mapping_is_a_frozen_mapping_not_a_dict(self):
        rule = make_rule(condition={"match": {"gene": "CYP2C19"}})
        self.assertIsInstance(rule.condition["match"], FrozenMapping)
        self.assertNotIsInstance(rule.condition["match"], dict)


class TestNestedSequenceMutationIsRejected(unittest.TestCase):
    """Proof 3: lists become tuples all the way down."""

    def test_nested_list_becomes_a_tuple(self):
        rule = make_rule(condition={"alleles": ["*1", "*2"]})
        self.assertIsInstance(rule.condition["alleles"], tuple)

    def test_nested_list_rejects_item_assignment(self):
        rule = make_rule(condition={"alleles": ["*1", "*2"]})
        # A tuple raises TypeError; the point is that it does not succeed.
        with self.assertRaises((TypeError, DomainInvariantError)):
            rule.condition["alleles"][0] = "*17"
        self.assertEqual(rule.condition["alleles"], ("*1", "*2"))

    def test_nested_list_has_no_append(self):
        rule = make_rule(condition={"alleles": ["*1"]})
        with self.assertRaises((AttributeError, DomainInvariantError)):
            rule.condition["alleles"].append("*2")

    def test_mapping_inside_a_list_is_frozen(self):
        rule = make_rule(condition={"any_of": [{"gene": "CYP2C19"}]})
        with self.assertRaises(DomainInvariantError):
            rule.condition["any_of"][0]["gene"] = "CYP2D6"


class TestDeepNestingIsRejected(unittest.TestCase):
    """Proof 4: depth does not run out of freezing."""

    def test_three_levels_down_is_still_frozen(self):
        rule = make_rule(condition=NESTED)
        with self.assertRaises(DomainInvariantError):
            rule.condition["outer"]["middle"]["flag"] = False
        self.assertIs(rule.condition["outer"]["middle"]["flag"], True)

    def test_list_inside_three_levels_is_a_tuple(self):
        rule = make_rule(condition=NESTED)
        self.assertEqual(rule.condition["outer"]["middle"]["inner"], ("a", "b"))

    def test_every_branch_reports_frozen(self):
        rule = make_rule(condition=NESTED)
        self.assertTrue(is_frozen_json(rule.condition))

    def test_excessive_nesting_is_refused_rather_than_crashing(self):
        payload = current = {}
        for _ in range(MAX_JSON_DEPTH + 5):
            child = {}
            current["next"] = child
            current = child
        with self.assertRaises(DomainInvariantError):
            freeze_json(payload)


class TestMutatingHelpersAreAbsent(unittest.TestCase):
    """Proof 5: the ``MutableMapping`` API is not available by another name."""

    MUTATORS = ("update", "pop", "popitem", "clear", "setdefault")

    def test_mutating_methods_are_not_defined(self):
        record = make_evidence(evidence_metadata={"a": 1})
        for name in self.MUTATORS:
            self.assertFalse(
                hasattr(record.evidence_metadata, name),
                "FrozenMapping must not expose %s()" % name)

    def test_it_is_a_mapping_but_not_a_mutable_mapping(self):
        from collections.abc import Mapping, MutableMapping
        record = make_evidence(evidence_metadata={"a": 1})
        self.assertIsInstance(record.evidence_metadata, Mapping)
        self.assertNotIsInstance(record.evidence_metadata, MutableMapping)

    def test_delitem_is_refused(self):
        record = make_evidence(evidence_metadata={"a": 1})
        with self.assertRaises(DomainInvariantError):
            del record.evidence_metadata["a"]
        self.assertIn("a", record.evidence_metadata)


class TestFrozenMappingAttributesAreSealed(unittest.TestCase):
    """Proof 6: the storage behind the mapping cannot be swapped out."""

    def test_attribute_assignment_is_refused(self):
        mapping = freeze_json({"a": 1})
        with self.assertRaises(DomainInvariantError):
            mapping._data = {"a": 2}
        self.assertEqual(mapping["a"], 1)

    def test_attribute_deletion_is_refused(self):
        mapping = freeze_json({"a": 1})
        with self.assertRaises(DomainInvariantError):
            del mapping._data

    def test_no_instance_dict_to_smuggle_state_through(self):
        mapping = freeze_json({"a": 1})
        self.assertFalse(hasattr(mapping, "__dict__"))

    def test_model_attribute_rebinding_is_still_refused(self):
        record = make_evidence(evidence_metadata={"a": 1})
        with self.assertRaises(Exception):
            record.evidence_metadata = {"a": 2}


class TestCallerCannotReachInsideAfterConstruction(unittest.TestCase):
    """Proof 7: construction takes a defensive copy."""

    def test_mutating_the_source_dict_does_not_change_the_model(self):
        payload = {"gene": "CYP2C19", "nested": {"k": "v"}}
        rule = make_rule(condition=payload)
        payload["gene"] = "TAMPERED"
        payload["nested"]["k"] = "TAMPERED"
        payload["added"] = True
        self.assertEqual(rule.condition["gene"], "CYP2C19")
        self.assertEqual(rule.condition["nested"]["k"], "v")
        self.assertNotIn("added", rule.condition)

    def test_mutating_a_source_list_does_not_change_the_model(self):
        alleles = ["*1"]
        rule = make_rule(condition={"alleles": alleles})
        alleles.append("*2")
        self.assertEqual(rule.condition["alleles"], ("*1",))

    def test_thawing_produces_a_detached_copy(self):
        rule = make_rule(condition={"nested": {"k": "v"}})
        thawed = thaw_json(rule.condition)
        thawed["nested"]["k"] = "TAMPERED"
        self.assertEqual(rule.condition["nested"]["k"], "v")

    def test_thawing_returns_plain_json_containers(self):
        rule = make_rule(condition={"nested": {"k": ["v"]}})
        thawed = thaw_json(rule.condition)
        self.assertIsInstance(thawed, dict)
        self.assertIsInstance(thawed["nested"], dict)
        self.assertIsInstance(thawed["nested"]["k"], list)


class TestNonJsonValuesAreRejected(unittest.TestCase):
    """Proof 8: rejection at the boundary, never silent coercion."""

    def test_nan_is_rejected(self):
        with self.assertRaises(DomainInvariantError):
            make_rule(condition={"score": float("nan")})

    def test_infinity_is_rejected(self):
        with self.assertRaises(DomainInvariantError):
            make_rule(condition={"score": math.inf})

    def test_non_string_key_is_rejected(self):
        with self.assertRaises(DomainInvariantError):
            make_rule(condition={1: "one"})

    def test_set_is_rejected(self):
        with self.assertRaises(DomainInvariantError):
            make_rule(condition={"alleles": {"*1", "*2"}})

    def test_bytes_are_rejected(self):
        with self.assertRaises(DomainInvariantError):
            make_rule(condition={"blob": b"\x00"})

    def test_callable_is_rejected(self):
        with self.assertRaises(DomainInvariantError):
            make_rule(condition={"predicate": lambda genotype: True})

    def test_arbitrary_object_is_rejected(self):
        class Opaque:
            pass
        with self.assertRaises(DomainInvariantError):
            make_rule(condition={"thing": Opaque()})

    def test_nested_violation_names_its_path(self):
        with self.assertRaises(DomainInvariantError) as caught:
            freeze_json({"a": {"b": [1, float("inf")]}})
        self.assertIn("$.a.b[1]", str(caught.exception))

    def test_metadata_that_is_not_a_mapping_is_rejected(self):
        with self.assertRaises(DomainInvariantError):
            make_evidence(evidence_metadata=["not", "a", "mapping"])


class TestSharedEmptyDefaultIsImmutable(unittest.TestCase):
    """Proof 9: the default cannot be poisoned for every other instance."""

    def test_module_default_is_a_frozen_mapping(self):
        self.assertIsInstance(models_module._EMPTY_METADATA, FrozenMapping)
        self.assertNotIsInstance(models_module._EMPTY_METADATA, dict)

    def test_the_shared_default_refuses_mutation(self):
        with self.assertRaises(DomainInvariantError):
            EMPTY_MAPPING["poison"] = True
        self.assertEqual(len(EMPTY_MAPPING), 0)

    def test_poisoning_one_instance_default_cannot_reach_another(self):
        first = make_evidence()
        with self.assertRaises(DomainInvariantError):
            first.evidence_metadata["poison"] = True
        second = make_evidence()
        self.assertEqual(dict(second.evidence_metadata), {})
        self.assertEqual(len(EMPTY_MAPPING), 0)

    def test_defaults_are_empty_for_every_defaulted_field(self):
        record = make_evidence()
        gene = _gene()
        for value in (record.evidence_metadata, record.publication_metadata,
                      gene.external_ids):
            self.assertIsInstance(value, FrozenMapping)
            self.assertEqual(len(value), 0)


class TestFreezingDoesNotChangeIdentityOrHashing(unittest.TestCase):
    """Freezing must be invisible to equality and to the canonical digest."""

    def test_frozen_mapping_equals_the_dict_it_came_from(self):
        source = {"a": 1, "b": {"c": 2}}
        frozen = freeze_json(source)
        self.assertEqual(frozen, source)
        self.assertEqual(frozen["b"], source["b"])

    def test_canonical_hash_is_unchanged_by_freezing(self):
        source = {"b": 2, "a": {"d": [1, 2], "c": "x"}}
        self.assertEqual(sha256_digest(source), sha256_digest(freeze_json(source)))

    def test_key_order_does_not_change_the_digest(self):
        first = freeze_json({"a": 1, "b": 2})
        second = freeze_json({"b": 2, "a": 1})
        self.assertEqual(sha256_digest(first), sha256_digest(second))

    def test_frozen_mapping_is_hashable(self):
        self.assertIsInstance(hash(freeze_json({"a": 1, "b": [1, 2]})), int)

    def test_array_order_still_matters(self):
        self.assertNotEqual(
            sha256_digest(freeze_json({"a": [1, 2]})),
            sha256_digest(freeze_json({"a": [2, 1]})))


class TestFreezingIsIdempotent(unittest.TestCase):
    """Re-freezing an already frozen value is safe and stable."""

    def test_freezing_twice_is_equal(self):
        once = freeze_json(NESTED)
        twice = freeze_json(once)
        self.assertEqual(once, twice)
        self.assertTrue(is_frozen_json(twice))

    def test_a_model_built_from_a_frozen_condition_is_still_frozen(self):
        rule = make_rule(condition=freeze_json({"gene": "CYP2C19"}))
        with self.assertRaises(DomainInvariantError):
            rule.condition["gene"] = "CYP2D6"

    def test_is_frozen_json_rejects_unfrozen_containers(self):
        self.assertFalse(is_frozen_json({"a": 1}))
        self.assertFalse(is_frozen_json(["a"]))

    def test_the_public_constructor_produces_frozen_json(self):
        """It used to leave the caller's nested containers in place."""
        self.assertTrue(is_frozen_json(FrozenMapping({"a": {"b": 1}})))



class TestTheBackingStoreCannotBeReached(unittest.TestCase):
    """Proof 10: ``_data`` is a read-only view, not a live dictionary.

    An earlier revision stored a plain ``dict`` in the ``_data`` slot. Every
    guarantee above was therefore one attribute access from being false:
    ``mapping._data["k"] = v`` and ``mapping._data.update(...)`` both worked,
    and the cached hash silently went stale afterwards. These tests are the
    reason the claim can be made at all.
    """

    def setUp(self):
        self.mapping = freeze_json({"outer": {"value": 1}, "items": [1, 2]})

    def test_the_store_is_a_read_only_proxy(self):
        self.assertIsInstance(self.mapping._data, types.MappingProxyType)
        self.assertNotIsInstance(self.mapping._data, dict)

    def test_item_assignment_through_the_store_fails(self):
        with self.assertRaises(TypeError):
            self.mapping._data["new"] = "MUTATED"
        self.assertNotIn("new", self.mapping)

    def test_item_assignment_through_a_nested_store_fails(self):
        with self.assertRaises(TypeError):
            self.mapping["outer"]._data["value"] = 999
        self.assertEqual(self.mapping["outer"]["value"], 1)

    def test_item_deletion_through_the_store_fails(self):
        with self.assertRaises(TypeError):
            del self.mapping._data["outer"]
        self.assertIn("outer", self.mapping)

    def test_the_store_exposes_no_mutating_methods(self):
        for name in ("update", "clear", "pop", "popitem", "setdefault",
                     "__setitem__", "__delitem__"):
            with self.subTest(method=name):
                self.assertFalse(hasattr(self.mapping._data, name),
                                 "mappingproxy must not expose %s" % name)

    def test_calling_a_mutating_method_on_the_store_fails(self):
        for call in (lambda: self.mapping._data.update({"u": 1}),
                     lambda: self.mapping._data.clear(),
                     lambda: self.mapping._data.pop("outer")):
            with self.subTest(call=call):
                with self.assertRaises(AttributeError):
                    call()
        self.assertEqual(set(self.mapping), {"outer", "items"})

    def test_the_store_slot_cannot_be_rebound(self):
        with self.assertRaises(DomainInvariantError):
            self.mapping._data = {"replaced": True}
        self.assertNotIn("replaced", self.mapping)


class TestThePublicConstructorFreezes(unittest.TestCase):
    """Proof 11: ``FrozenMapping(...)`` is safe on its own.

    It used to copy only the top level, so a nested list or dict handed to it
    stayed shared with the caller: ``FrozenMapping({"items": []})`` followed by
    ``original["items"].append(...)`` changed the "immutable" mapping.
    """

    def test_a_nested_list_is_converted_to_a_tuple(self):
        self.assertIsInstance(FrozenMapping({"items": [1, 2]})["items"], tuple)

    def test_a_nested_mapping_is_converted_to_a_frozen_mapping(self):
        nested = FrozenMapping({"outer": {"k": "v"}})["outer"]
        self.assertIsInstance(nested, FrozenMapping)
        self.assertNotIsInstance(nested, dict)

    def test_mutating_the_source_list_afterwards_changes_nothing(self):
        original = {"items": []}
        mapping = FrozenMapping(original)
        original["items"].append("mutation")
        self.assertEqual(mapping["items"], ())

    def test_mutating_a_source_nested_dict_afterwards_changes_nothing(self):
        original = {"nested": {"k": "v"}}
        mapping = FrozenMapping(original)
        original["nested"]["k"] = "MUTATED"
        original["added"] = True
        self.assertEqual(mapping["nested"]["k"], "v")
        self.assertNotIn("added", mapping)

    def test_it_leaves_no_mutable_container_anywhere(self):
        mapping = FrozenMapping(
            {"a": {"b": [{"c": [1, 2]}]}, "d": [[3], {"e": 4}]})
        self.assertTrue(is_frozen_json(mapping))

    def test_it_rejects_the_same_values_freeze_json_rejects(self):
        for payload in ({"n": float("nan")}, {"s": {"x"}}, {"b": b"\x00"},
                        {1: "int key"}, {"f": lambda: None}):
            with self.subTest(payload=payload):
                with self.assertRaises(DomainInvariantError):
                    FrozenMapping(payload)

    def test_it_rejects_a_non_mapping(self):
        for payload in ([1, 2], "text", 7, None):
            with self.subTest(payload=payload):
                with self.assertRaises(DomainInvariantError):
                    FrozenMapping(payload)

    def test_constructor_and_freeze_json_agree(self):
        payload = {"a": {"b": [1, 2]}, "c": "x"}
        self.assertEqual(FrozenMapping(payload), freeze_json(payload))
        self.assertEqual(hash(FrozenMapping(payload)), hash(freeze_json(payload)))

    def test_freezing_an_existing_frozen_mapping_returns_it_unchanged(self):
        """Idempotent and cheap: no second walk, no double-freeze."""
        mapping = freeze_json({"a": {"b": [1]}})
        self.assertIs(freeze_json(mapping), mapping)


class TestTheHashCacheCannotGoStale(unittest.TestCase):
    """Proof 12: there is no mutation the cached hash could miss."""

    def test_the_hash_slot_cannot_be_rebound(self):
        mapping = freeze_json({"a": 1})
        hash(mapping)
        with self.assertRaises(DomainInvariantError):
            mapping._hash = 0
        self.assertEqual(hash(mapping), hash(freeze_json({"a": 1})))

    def test_the_cached_hash_still_describes_the_content(self):
        mapping = freeze_json({"a": 1})
        first = hash(mapping)
        for attempt in (lambda: mapping._data.__setitem__("a", 2),
                        lambda: mapping._data.update({"a": 2})):
            with self.assertRaises((TypeError, AttributeError)):
                attempt()
        self.assertEqual(hash(mapping), first)
        self.assertEqual(first, hash(FrozenMapping({"a": 1})))
        self.assertNotEqual(first, hash(FrozenMapping({"a": 2})))

    def test_equal_mappings_hash_equal_whatever_built_them(self):
        payload = {"b": 2, "a": {"c": [1, 2]}}
        built = (FrozenMapping(payload), freeze_json(payload),
                 freeze_json(FrozenMapping(payload)))
        self.assertEqual(len({hash(item) for item in built}), 1)
        self.assertEqual(len({item for item in built}), 1)


class TestNonFiniteFloatsAreNotFrozenJson(unittest.TestCase):
    """Proof 13: ``is_frozen_json`` agreed with nothing it claimed."""

    def test_nan_is_not_frozen_json(self):
        self.assertFalse(is_frozen_json(float("nan")))

    def test_positive_infinity_is_not_frozen_json(self):
        self.assertFalse(is_frozen_json(float("inf")))

    def test_negative_infinity_is_not_frozen_json(self):
        self.assertFalse(is_frozen_json(float("-inf")))

    def test_ordinary_floats_are_frozen_json(self):
        for value in (0.0, -1.5, 3.14, 1e300):
            with self.subTest(value=value):
                self.assertTrue(is_frozen_json(value))

    def test_a_non_finite_float_nested_in_a_tuple_is_not_frozen_json(self):
        self.assertFalse(is_frozen_json((1.0, float("inf"))))

    def test_is_frozen_json_agrees_with_what_freeze_json_accepts(self):
        """The two must not disagree: one reports, the other enforces."""
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                self.assertFalse(is_frozen_json(value))
                with self.assertRaises(DomainInvariantError):
                    freeze_json(value)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()