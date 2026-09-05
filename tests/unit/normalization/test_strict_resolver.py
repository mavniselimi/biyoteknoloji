# -*- coding: utf-8 -*-
"""The strict five-step resolver (WP-07).

The legacy resolver took ``results[0]``. Everything below exists to make that
impossible to reintroduce without a test going red: the stage order, the
three-way decision at every stage, and the refusal to rank, score, guess or
mint.
"""

from __future__ import annotations

import ast
import io
import os
import unittest

from pgx.normalization.models import (RESOLUTION_STAGES, EntityType,
                                      ReasonCode, ResolutionMethod,
                                      ResolutionStatus)
from pgx.normalization.resolver import (RESOLVER_POLICY_VERSION,
                                        CanonicalCatalog, EntityResolver)

from tests.unit.normalization._support import (REPO_ROOT, approved_alias,
                                               clinpgx, drug, gene, locator,
                                               pending_alias)

RESOLVER = os.path.join("pgx", "normalization", "resolver.py")


def _source(relative: str) -> str:
    with io.open(os.path.join(REPO_ROOT, relative), encoding="utf-8") as handle:
        return handle.read()


class TestStageOrder(unittest.TestCase):

    def test_the_documented_order_is_the_one_the_code_declares(self):
        self.assertEqual(
            [stage.value for stage in RESOLUTION_STAGES],
            ["EXTERNAL_ID", "PREFERRED_NAME", "APPROVED_ALIAS",
             "CROSS_REFERENCE"])

    def test_an_external_id_wins_over_a_name_that_points_elsewhere(self):
        """Stage one runs first, so a name collision downstream never matters."""
        catalog = CanonicalCatalog((
            gene("CYP2C19", external_ids=(clinpgx("PA124"),)),
            gene("CYP2D6", external_ids=(clinpgx("PA128"),)),
        ))
        outcome = EntityResolver(catalog).resolve(
            EntityType.GENE, "CYP2D6", external_id=("clinpgx", "PA124"))
        self.assertIs(outcome.status, ResolutionStatus.RESOLVED)
        self.assertIs(outcome.method, ResolutionMethod.EXTERNAL_ID)
        self.assertEqual(outcome.canonical_key, "GENE:CYP2C19")

    def test_a_preferred_name_wins_over_an_approved_alias(self):
        catalog = CanonicalCatalog((
            gene("CYP2C19"),
            gene("CYP2D6", aliases=(approved_alias("CYP2C19"),)),
        ))
        outcome = EntityResolver(catalog).resolve(EntityType.GENE, "cyp2c19")
        self.assertIs(outcome.method, ResolutionMethod.PREFERRED_NAME)
        self.assertEqual(outcome.canonical_key, "GENE:CYP2C19")


class TestEachStageResolves(unittest.TestCase):

    def test_stage_one_matches_an_exact_namespaced_external_id(self):
        catalog = CanonicalCatalog((gene("CYP2C19",
                                         external_ids=(clinpgx("PA124"),)),))
        outcome = EntityResolver(catalog).resolve(
            EntityType.GENE, "anything", external_id=("clinpgx", "PA124"))
        self.assertIs(outcome.status, ResolutionStatus.RESOLVED)
        self.assertIs(outcome.reason, ReasonCode.MATCHED_EXTERNAL_ID)

    def test_stage_one_does_not_match_the_same_value_in_another_namespace(self):
        catalog = CanonicalCatalog((gene("CYP2C19",
                                         external_ids=(clinpgx("PA124"),)),))
        outcome = EntityResolver(catalog).resolve(
            EntityType.GENE, "unknownsymbolx", external_id=("drugbank", "PA124"))
        self.assertIsNot(outcome.status, ResolutionStatus.RESOLVED)

    def test_stage_two_matches_the_normalised_symbol(self):
        catalog = CanonicalCatalog((gene("CYP2C19"),))
        outcome = EntityResolver(catalog).resolve(EntityType.GENE, "  cyp2c19 ")
        self.assertIs(outcome.status, ResolutionStatus.RESOLVED)
        self.assertIs(outcome.reason, ReasonCode.MATCHED_PREFERRED_NAME)

    def test_stage_two_matches_the_normalised_drug_name(self):
        catalog = CanonicalCatalog((drug("clopidogrel"),))
        outcome = EntityResolver(catalog).resolve(EntityType.DRUG, "Clopidogrel")
        self.assertIs(outcome.status, ResolutionStatus.RESOLVED)
        self.assertEqual(outcome.canonical_key, "DRUG:clopidogrel")

    def test_stage_three_matches_only_an_approved_alias(self):
        catalog = CanonicalCatalog((gene("CYP2C19",
                                         aliases=(approved_alias("P450IIC19"),)),))
        outcome = EntityResolver(catalog).resolve(EntityType.GENE, "P450IIC19")
        self.assertIs(outcome.status, ResolutionStatus.RESOLVED)
        self.assertIs(outcome.reason, ReasonCode.MATCHED_APPROVED_ALIAS)

    def test_stage_four_matches_a_bare_external_value(self):
        catalog = CanonicalCatalog((gene("CYP2C19",
                                         external_ids=(clinpgx("PA124"),)),))
        outcome = EntityResolver(catalog).resolve(EntityType.GENE, "PA124")
        self.assertIs(outcome.status, ResolutionStatus.RESOLVED)
        self.assertIs(outcome.reason, ReasonCode.MATCHED_CROSS_REFERENCE)


class TestAmbiguityIsNeverSettled(unittest.TestCase):

    def _shared_alias_catalog(self):
        return CanonicalCatalog((
            gene("CYP2C19", aliases=(approved_alias("SHAREDNAME"),)),
            gene("CYP2D6", aliases=(approved_alias("SHAREDNAME"),)),
        ))

    def test_two_candidates_stop_the_search_as_ambiguous(self):
        outcome = EntityResolver(self._shared_alias_catalog()).resolve(
            EntityType.GENE, "SHAREDNAME")
        self.assertIs(outcome.status, ResolutionStatus.AMBIGUOUS)
        self.assertIsNone(outcome.canonical_key)

    def test_an_ambiguous_outcome_carries_every_candidate(self):
        outcome = EntityResolver(self._shared_alias_catalog()).resolve(
            EntityType.GENE, "SHAREDNAME")
        self.assertEqual(list(outcome.candidate_keys),
                         ["GENE:CYP2C19", "GENE:CYP2D6"])

    def test_a_later_stage_never_breaks_an_earlier_ambiguity(self):
        """The trap this guards against.

        Two genes share an approved alias (stage three is ambiguous), and only
        one of them carries that string as an external value (stage four would
        be unique). A resolver that carried on would 'resolve' the collision by
        coincidence. This one stops at stage three.
        """
        catalog = CanonicalCatalog((
            gene("CYP2C19", aliases=(approved_alias("PA124"),),
                 external_ids=(clinpgx("PA124"),)),
            gene("CYP2D6", aliases=(approved_alias("PA124"),)),
        ))
        outcome = EntityResolver(catalog).resolve(EntityType.GENE, "PA124")
        self.assertIs(outcome.status, ResolutionStatus.AMBIGUOUS)
        self.assertIs(outcome.method, ResolutionMethod.APPROVED_ALIAS)
        self.assertEqual(len(outcome.candidate_keys), 2)

    def test_an_ambiguous_external_id_is_reported_at_stage_one(self):
        catalog = CanonicalCatalog((
            gene("CYP2C19", external_ids=(clinpgx("PA999"),)),
            gene("CYP2D6", external_ids=(clinpgx("PA999"),)),
        ))
        outcome = EntityResolver(catalog).resolve(
            EntityType.GENE, "CYP2C19", external_id=("clinpgx", "PA999"))
        self.assertIs(outcome.status, ResolutionStatus.AMBIGUOUS)
        self.assertIs(outcome.reason, ReasonCode.AMBIGUOUS_EXTERNAL_ID)

    def test_the_catalog_never_maps_a_key_to_a_single_entity(self):
        """Every index returns a tuple, so there is nowhere to choose."""
        catalog = self._shared_alias_catalog()
        self.assertEqual(catalog.by_approved_alias(EntityType.GENE, "SHAREDNAME"),
                         ("GENE:CYP2C19", "GENE:CYP2D6"))
        self.assertIsInstance(
            catalog.by_normalized_value(EntityType.GENE, "CYP2C19"), tuple)


class TestOnlyApprovedAliasesResolve(unittest.TestCase):

    def test_a_pending_alias_resolves_nothing(self):
        catalog = CanonicalCatalog((gene("CYP2C19",
                                         aliases=(pending_alias("P450IIC19"),)),))
        outcome = EntityResolver(catalog).resolve(EntityType.GENE, "P450IIC19")
        self.assertIs(outcome.status, ResolutionStatus.UNRESOLVED)

    def test_a_pending_alias_is_not_even_in_the_index(self):
        catalog = CanonicalCatalog((gene("CYP2C19",
                                         aliases=(pending_alias("P450IIC19"),)),))
        self.assertEqual(
            catalog.by_approved_alias(EntityType.GENE, "P450IIC19"), ())

    def test_a_rejected_alias_resolves_nothing(self):
        from pgx.normalization.models import AliasProposal, AliasStatus
        rejected = AliasProposal("P450IIC19", "P450IIC19",
                                 status=AliasStatus.REJECTED)
        catalog = CanonicalCatalog((gene("CYP2C19", aliases=(rejected,)),))
        outcome = EntityResolver(catalog).resolve(EntityType.GENE, "P450IIC19")
        self.assertIs(outcome.status, ResolutionStatus.UNRESOLVED)

    def test_a_deprecated_alias_resolves_nothing(self):
        """Deprecated means "was approved once". It stops resolving the moment
        it is deprecated, rather than lingering as a quiet match."""
        from pgx.normalization.models import AliasProposal, AliasStatus
        deprecated = AliasProposal("P450IIC19", "P450IIC19",
                                   status=AliasStatus.DEPRECATED)
        catalog = CanonicalCatalog((gene("CYP2C19", aliases=(deprecated,)),))
        outcome = EntityResolver(catalog).resolve(EntityType.GENE, "P450IIC19")
        self.assertIs(outcome.status, ResolutionStatus.UNRESOLVED)

    def test_only_approved_is_in_the_resolving_status_set(self):
        from pgx.normalization.models import (RESOLVING_ALIAS_STATUSES,
                                              AliasStatus)
        self.assertEqual(RESOLVING_ALIAS_STATUSES, (AliasStatus.APPROVED,))

    def test_two_pending_aliases_do_not_even_create_an_ambiguity(self):
        catalog = CanonicalCatalog((
            gene("CYP2C19", aliases=(pending_alias("SHAREDNAME"),)),
            gene("CYP2D6", aliases=(pending_alias("SHAREDNAME"),)),
        ))
        outcome = EntityResolver(catalog).resolve(EntityType.GENE, "SHAREDNAME")
        self.assertIs(outcome.status, ResolutionStatus.UNRESOLVED)


class TestUnresolvableInput(unittest.TestCase):

    def test_a_blank_value_is_invalid_input_not_unresolved(self):
        outcome = EntityResolver(CanonicalCatalog(())).resolve(
            EntityType.GENE, "   ")
        self.assertIs(outcome.status, ResolutionStatus.INVALID_INPUT)
        self.assertIs(outcome.reason, ReasonCode.MISSING_VALUE)

    def test_an_unnormalisable_symbol_is_invalid_input(self):
        outcome = EntityResolver(CanonicalCatalog(())).resolve(
            EntityType.GENE, "***")
        self.assertIs(outcome.status, ResolutionStatus.INVALID_INPUT)
        self.assertIs(outcome.reason, ReasonCode.NOT_NORMALIZABLE)

    def test_an_unknown_value_is_unresolved_and_names_no_candidate(self):
        outcome = EntityResolver(CanonicalCatalog((gene("CYP2C19"),))).resolve(
            EntityType.GENE, "CYP3A5")
        self.assertIs(outcome.status, ResolutionStatus.UNRESOLVED)
        self.assertEqual(outcome.candidate_keys, ())
        self.assertIsNone(outcome.canonical_key)

    def test_the_submitted_value_survives_verbatim(self):
        outcome = EntityResolver(CanonicalCatalog(())).resolve(
            EntityType.GENE, "  cyp3a5  ")
        self.assertEqual(outcome.submitted_value, "  cyp3a5  ")


class TestBrokenReferences(unittest.TestCase):

    def test_a_reference_to_an_absent_entity_is_a_broken_reference(self):
        outcome = EntityResolver(CanonicalCatalog((gene("CYP2C19"),))) \
            .resolve_reference(EntityType.GENE, "CYP3A5")
        self.assertIs(outcome.status, ResolutionStatus.BROKEN_REFERENCE)
        self.assertIs(outcome.reason, ReasonCode.REFERENCED_ENTITY_ABSENT)

    def test_a_broken_reference_never_creates_the_entity_it_names(self):
        catalog = CanonicalCatalog((gene("CYP2C19"),))
        before = catalog.canonical_keys
        EntityResolver(catalog).resolve_reference(EntityType.GENE, "CYP3A5")
        self.assertEqual(catalog.canonical_keys, before)

    def test_an_ambiguous_reference_stays_ambiguous_not_broken(self):
        catalog = CanonicalCatalog((
            gene("CYP2C19", aliases=(approved_alias("SHAREDNAME"),)),
            gene("CYP2D6", aliases=(approved_alias("SHAREDNAME"),)),
        ))
        outcome = EntityResolver(catalog).resolve_reference(
            EntityType.GENE, "SHAREDNAME")
        self.assertIs(outcome.status, ResolutionStatus.AMBIGUOUS)


class TestTheResolverHasNoSideEffects(unittest.TestCase):

    def test_resolving_twice_returns_the_same_answer(self):
        catalog = CanonicalCatalog((gene("CYP2C19"),))
        resolver = EntityResolver(catalog)
        first = resolver.resolve(EntityType.GENE, "CYP2C19")
        second = resolver.resolve(EntityType.GENE, "CYP2C19")
        self.assertEqual(first.to_json(), second.to_json())

    def test_the_catalog_is_unchanged_by_an_unresolved_lookup(self):
        catalog = CanonicalCatalog((gene("CYP2C19"),))
        self.assertEqual(len(catalog), 1)
        EntityResolver(catalog).resolve(EntityType.GENE, "CYP3A5")
        self.assertEqual(len(catalog), 1)

    def test_the_module_mints_no_identity(self):
        """A resolver that could mint would create the entity it failed to find.

        Read from identifiers rather than from the file's prose, because the
        module's docstring says the word 'uuid' while the code must not use it.
        """
        tree = ast.parse(_source(RESOLVER), filename=RESOLVER)
        identifiers = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                identifiers.add(node.id)
            elif isinstance(node, ast.Attribute):
                identifiers.add(node.attr)
            elif isinstance(node, ast.Import):
                identifiers.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                identifiers.add(node.module)
        for token in ("uuid", "uuid4", "uuid5", "new", "derive", "allocate",
                      "allocate_identities"):
            with self.subTest(token=token):
                self.assertNotIn(token, identifiers)


class TestNoFuzzyOrRankingCodeExists(unittest.TestCase):

    FORBIDDEN_CALLS = ("SequenceMatcher", "get_close_matches", "levenshtein",
                       "edit_distance", "soundex", "metaphone", "fuzz",
                       "difflib", "rapidfuzz", "embedding", "cosine")

    FORBIDDEN_SELECTION = ("max", "min", "sort", "sorted_by_score", "rank",
                           "best", "score", "top", "argmax", "first")

    def test_no_fuzzy_matching_library_or_helper_is_referenced(self):
        tree = ast.parse(_source(RESOLVER), filename=RESOLVER)
        identifiers = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                identifiers.add(node.id)
            elif isinstance(node, ast.Attribute):
                identifiers.add(node.attr)
            elif isinstance(node, ast.Import):
                identifiers.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                identifiers.add(node.module)
        for token in self.FORBIDDEN_CALLS:
            with self.subTest(token=token):
                self.assertNotIn(token, identifiers)

    def test_the_resolver_never_ranks_or_takes_a_best_candidate(self):
        tree = ast.parse(_source(RESOLVER), filename=RESOLVER)
        called = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name):
                    called.add(func.id)
                elif isinstance(func, ast.Attribute):
                    called.add(func.attr)
        for token in ("max", "min", "rank", "argmax"):
            with self.subTest(token=token):
                self.assertNotIn(token, called)

    def test_no_candidate_sequence_is_indexed_at_zero(self):
        """``results[0]`` is the exact legacy defect, in source form.

        The single-candidate case unpacks - ``(only,) = candidates`` - which
        raises if the length guard above it is ever weakened. An index would
        keep working and quietly pick a winner.
        """
        tree = ast.parse(_source(RESOLVER), filename=RESOLVER)
        for node in ast.walk(tree):
            if isinstance(node, ast.Subscript) and \
                    isinstance(node.slice, ast.Constant) and \
                    node.slice.value == 0:
                target = getattr(node.value, "id", None)
                self.assertNotIn(target, ("candidates", "results", "matches",
                                          "found", "rows"))

    def test_the_single_candidate_case_unpacks_rather_than_indexes(self):
        tree = ast.parse(_source(RESOLVER), filename=RESOLVER)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_decide":
                unpacks = [child for child in ast.walk(node)
                           if isinstance(child, ast.Assign)
                           and any(isinstance(target, ast.Tuple)
                                   for target in child.targets)]
                self.assertTrue(
                    unpacks,
                    "_decide should unpack the single candidate, so that a "
                    "weakened length guard raises instead of choosing")
                return
        self.fail("_decide not found in %s" % RESOLVER)

    def test_the_decision_has_exactly_three_branches(self):
        """Zero advances, one resolves, more than one stops as ambiguous.

        Counted from the AST so a fourth branch - a tie-break, a preference,
        an 'if only one is CPIC' - cannot be added silently.
        """
        tree = ast.parse(_source(RESOLVER), filename=RESOLVER)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_decide":
                comparisons = [child for child in ast.walk(node)
                               if isinstance(child, ast.Compare)]
                self.assertLessEqual(
                    len(comparisons), 3,
                    "_decide grew a fourth comparison: %d found"
                    % len(comparisons))
                return
        self.fail("_decide not found in %s" % RESOLVER)


class TestPolicyVersion(unittest.TestCase):

    def test_the_policy_version_is_recorded_and_non_empty(self):
        self.assertTrue(RESOLVER_POLICY_VERSION.strip())
        self.assertEqual(EntityResolver.policy_version, RESOLVER_POLICY_VERSION)


class TestCatalogRefusesADuplicateKey(unittest.TestCase):

    def test_two_entities_with_one_canonical_key_is_a_construction_error(self):
        with self.assertRaises(ValueError):
            CanonicalCatalog((gene("CYP2C19"), gene("CYP2C19")))


if __name__ == "__main__":
    unittest.main()
