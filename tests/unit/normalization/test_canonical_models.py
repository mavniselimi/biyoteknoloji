# -*- coding: utf-8 -*-
"""Canonical entities, locators, alias review state and outcomes (WP-07).

The invariants here are the ones that stop a canonical record from quietly
becoming an interpretation, and stop an ambiguity from quietly becoming a
choice.
"""

from __future__ import annotations

import ast
import datetime as _dt
import io
import os
import unittest

from pgx.normalization.errors import CanonicalizationError
from pgx.normalization.models import (AliasProposal, AliasStatus,
                                      CanonicalEntity, DuplicateClass,
                                      DuplicateGroup, DuplicateMember,
                                      EntityType, RawLocator, ReasonCode,
                                      ResolutionMethod, ResolutionOutcome,
                                      ResolutionQueueItem, ResolutionStatus,
                                      canonical_key_for, payload_digest)

from tests.unit.normalization._support import (ARTIFACT_HASH, DATASET_ID,
                                               MANIFEST_HASH, REPO_ROOT,
                                               REVIEWED_AT, approved_alias,
                                               clinpgx, drug, gene, locator,
                                               pending_alias)

MODELS = os.path.join("pgx", "normalization", "models.py")


def _source(relative: str) -> str:
    """Read a module's text, closing the handle.

    A bare ``open(...).read()`` leaks a file object, and the suite runs with
    ``-W error::ResourceWarning`` so the leak would fail the run rather than
    merely warn.
    """
    with io.open(os.path.join(REPO_ROOT, relative), encoding="utf-8") as handle:
        return handle.read()


class TestRawLocator(unittest.TestCase):

    def test_every_field_but_the_record_id_is_required(self):
        for missing in ("dataset_public_id", "snapshot_manifest_hash",
                        "artifact_path", "artifact_sha256", "pointer"):
            kwargs = dict(dataset_public_id=DATASET_ID,
                          snapshot_manifest_hash=MANIFEST_HASH,
                          artifact_path="responses/x.json",
                          artifact_sha256=ARTIFACT_HASH, pointer="/x")
            kwargs[missing] = "  "
            with self.subTest(field=missing):
                with self.assertRaises(CanonicalizationError):
                    RawLocator(**kwargs)

    def test_a_missing_source_record_id_is_allowed_and_visible(self):
        """Its absence is a data-quality finding, not something to invent."""
        item = locator(source_record_id=None)
        self.assertIsNone(item.source_record_id)
        self.assertIsNone(item.to_json()["source_record_id"])

    def test_an_absolute_or_traversing_artifact_path_is_refused(self):
        for path in ("/etc/passwd", "../secrets.json", "a/../../b"):
            with self.subTest(path=path):
                with self.assertRaises(CanonicalizationError):
                    locator(artifact_path=path)

    def test_it_carries_the_artifact_digest_so_it_stays_checkable(self):
        self.assertEqual(locator().to_json()["artifact_sha256"], ARTIFACT_HASH)


class TestAliasReviewState(unittest.TestCase):

    def test_a_proposal_defaults_to_pending_and_resolves_nothing(self):
        proposal = AliasProposal("CYP2C19P", "CYP2C19p")
        self.assertIs(proposal.status, AliasStatus.PENDING_REVIEW)
        self.assertFalse(proposal.resolves)

    def test_only_approved_resolves(self):
        for status in AliasStatus:
            proposal = (approved_alias("X") if status is AliasStatus.APPROVED
                        else AliasProposal("X", "X", status=status))
            with self.subTest(status=status):
                self.assertEqual(proposal.resolves,
                                 status is AliasStatus.APPROVED)

    def test_an_approval_that_names_nobody_is_refused(self):
        with self.assertRaises(CanonicalizationError):
            AliasProposal("X", "X", status=AliasStatus.APPROVED)
        with self.assertRaises(CanonicalizationError):
            AliasProposal("X", "X", status=AliasStatus.APPROVED,
                          reviewed_by="  ", reviewed_at=REVIEWED_AT)

    def test_an_approval_with_no_instant_is_refused(self):
        with self.assertRaises(CanonicalizationError):
            AliasProposal("X", "X", status=AliasStatus.APPROVED,
                          reviewed_by="a-reviewer")

    def test_there_is_no_method_that_approves_an_alias(self):
        """Approval is a decision, not a convenience method.

        Read from the class's own AST rather than from ``dir()``: a method
        added under a different name still shows up here.
        """
        tree = ast.parse(_source(MODELS), filename=MODELS)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "AliasProposal":
                names = {child.name for child in node.body
                         if isinstance(child, ast.FunctionDef)}
                for forbidden in ("approve", "set_status", "mark_approved",
                                  "with_status", "auto_approve"):
                    self.assertNotIn(forbidden, names)
                return
        self.fail("AliasProposal not found in %s" % MODELS)


class TestCanonicalEntity(unittest.TestCase):

    def test_the_canonical_key_must_match_the_normalised_value(self):
        with self.assertRaises(CanonicalizationError):
            CanonicalEntity(entity_type=EntityType.GENE,
                            canonical_key="GENE:CYP2D6",
                            normalized_value="CYP2C19",
                            preferred_display="x", source_display="x",
                            locators=(locator(),))

    def test_a_gene_must_carry_an_already_normalised_symbol(self):
        with self.assertRaises(CanonicalizationError):
            CanonicalEntity(entity_type=EntityType.GENE,
                            canonical_key="GENE:cyp2c19",
                            normalized_value="cyp2c19",
                            preferred_display="x", source_display="x",
                            locators=(locator(),))

    def test_a_drug_must_carry_an_already_normalised_name(self):
        with self.assertRaises(CanonicalizationError):
            CanonicalEntity(entity_type=EntityType.DRUG,
                            canonical_key="DRUG:Clopidogrel",
                            normalized_value="Clopidogrel",
                            preferred_display="x", source_display="x",
                            locators=(locator(),))

    def test_an_entity_without_provenance_is_refused(self):
        """An entity with no locator cannot be traced to a source."""
        with self.assertRaises(CanonicalizationError):
            CanonicalEntity(entity_type=EntityType.GENE,
                            canonical_key="GENE:CYP2C19",
                            normalized_value="CYP2C19",
                            preferred_display="x", source_display="x",
                            locators=())

    def test_the_sources_own_spelling_is_kept(self):
        entity = CanonicalEntity(
            entity_type=EntityType.DRUG, canonical_key="DRUG:clopidogrel",
            normalized_value="clopidogrel", preferred_display="Clopidogrel",
            source_display="Clopidogrel", locators=(locator(),))
        self.assertEqual(entity.source_display, "Clopidogrel")

    def test_content_identity_excludes_the_allocated_uuid(self):
        """Two projects with different identities still agree on the data."""
        left = gene("CYP2C19", entity_uuid="11111111-1111-4111-8111-111111111111")
        right = gene("CYP2C19", entity_uuid="22222222-2222-4222-8222-222222222222")
        self.assertEqual(left.content_identity(), right.content_identity())
        self.assertNotEqual(left.to_json(), right.to_json())

    def test_lists_are_sorted_so_two_builds_agree(self):
        entity = gene("CYP2C19",
                      external_ids=(clinpgx("PA999"), clinpgx("PA124")),
                      aliases=(pending_alias("ZED"), pending_alias("ABLE")))
        self.assertEqual([item.value for item in entity.external_ids],
                         ["PA124", "PA999"])
        self.assertEqual([item.normalized_alias for item in entity.aliases],
                         ["ABLE", "ZED"])

    def test_approved_aliases_are_the_only_ones_offered_for_resolution(self):
        entity = gene("CYP2C19", aliases=(pending_alias("PENDING1"),
                                          approved_alias("APPROVED1")))
        self.assertEqual([item.normalized_alias
                          for item in entity.approved_aliases], ["APPROVED1"])


class TestNoInterpretationFieldExists(unittest.TestCase):
    """The columns the legacy CSVs mixed in with source facts.

    Read from the module's AST, so a field added under any of these names is
    caught wherever it is declared - and prose in a docstring cannot trip it.
    """

    FORBIDDEN = ("risk", "risk_level", "severity", "significance", "polarity",
                 "score", "candidate_score", "recommendation", "effect_hint",
                 "manual_effect_hint", "clinical_conclusion", "attention_level",
                 "phenotype", "plain_language_mvp", "demo_risk_level",
                 "evidence_tier", "usable_for_mvp", "alternative_drug")

    def _annotated_field_names(self, relative):
        tree = ast.parse(_source(relative), filename=relative)
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for child in node.body:
                    if isinstance(child, ast.AnnAssign) and \
                            isinstance(child.target, ast.Name):
                        names.add(child.target.id)
        return names

    def test_no_canonical_model_declares_an_interpretation_field(self):
        names = self._annotated_field_names(MODELS)
        for token in self.FORBIDDEN:
            with self.subTest(field=token):
                self.assertNotIn(token, names)

    def test_no_extraction_or_build_model_declares_one_either(self):
        for relative in (os.path.join("pgx", "normalization", "extract.py"),
                         os.path.join("pgx", "normalization", "build.py"),
                         os.path.join("pgx", "normalization", "dedup.py")):
            names = self._annotated_field_names(relative)
            for token in self.FORBIDDEN:
                with self.subTest(module=relative, field=token):
                    self.assertNotIn(token, names)

    def test_a_serialised_entity_carries_none_of_them(self):
        payload = gene("CYP2C19", external_ids=(clinpgx("PA124"),),
                       aliases=(approved_alias("CYP2C19A"),)).to_json()
        for token in self.FORBIDDEN:
            with self.subTest(field=token):
                self.assertNotIn(token, payload)


class TestResolutionOutcome(unittest.TestCase):

    def test_a_resolved_outcome_must_name_what_it_resolved_to(self):
        with self.assertRaises(CanonicalizationError):
            ResolutionOutcome(entity_type=EntityType.GENE,
                              submitted_value="CYP2C19",
                              normalized_value="CYP2C19",
                              status=ResolutionStatus.RESOLVED,
                              method=ResolutionMethod.PREFERRED_NAME,
                              reason=ReasonCode.MATCHED_PREFERRED_NAME)

    def test_an_ambiguous_outcome_must_carry_every_candidate(self):
        with self.assertRaises(CanonicalizationError):
            ResolutionOutcome(entity_type=EntityType.GENE,
                              submitted_value="SHARED",
                              normalized_value="SHARED",
                              status=ResolutionStatus.AMBIGUOUS,
                              method=ResolutionMethod.APPROVED_ALIAS,
                              reason=ReasonCode.AMBIGUOUS_APPROVED_ALIAS,
                              candidate_keys=("GENE:CYP2C19",))

    def test_a_resolved_outcome_may_not_carry_unchosen_candidates(self):
        """That would be a silent selection wearing a resolution's clothes."""
        with self.assertRaises(CanonicalizationError):
            ResolutionOutcome(entity_type=EntityType.GENE,
                              submitted_value="SHARED",
                              normalized_value="SHARED",
                              status=ResolutionStatus.RESOLVED,
                              method=ResolutionMethod.APPROVED_ALIAS,
                              reason=ReasonCode.MATCHED_APPROVED_ALIAS,
                              canonical_key="GENE:CYP2C19",
                              candidate_keys=("GENE:CYP2C19", "GENE:CYP2D6"))

    def test_everything_but_resolved_needs_review(self):
        for status in ResolutionStatus:
            outcome = ResolutionOutcome(
                entity_type=EntityType.GENE, submitted_value="X",
                normalized_value="X", status=status,
                method=ResolutionMethod.NONE,
                reason=ReasonCode.NO_CANDIDATE_FOUND,
                canonical_key=("GENE:X" if status is ResolutionStatus.RESOLVED
                               else None),
                candidate_keys=(("GENE:A", "GENE:B")
                                if status is ResolutionStatus.AMBIGUOUS else ()))
            with self.subTest(status=status):
                self.assertEqual(outcome.needs_review,
                                 status is not ResolutionStatus.RESOLVED)


class TestResolutionQueueItem(unittest.TestCase):

    def _ambiguous(self):
        return ResolutionOutcome(
            entity_type=EntityType.GENE, submitted_value="SHARED",
            normalized_value="SHARED", status=ResolutionStatus.AMBIGUOUS,
            method=ResolutionMethod.APPROVED_ALIAS,
            reason=ReasonCode.AMBIGUOUS_APPROVED_ALIAS,
            candidate_keys=("GENE:CYP2C19", "GENE:CYP2D6"))

    def _item(self, **changes):
        kwargs = dict(queue_key="q1", dataset_public_id=DATASET_ID,
                      canonical_build_key="b1", outcome=self._ambiguous(),
                      created_at=REVIEWED_AT)
        kwargs.update(changes)
        return ResolutionQueueItem(**kwargs)

    def test_a_new_item_is_undecided(self):
        item = self._item()
        self.assertFalse(item.is_decided)
        self.assertIsNone(item.decided_by)

    def test_a_partial_decision_is_refused(self):
        with self.assertRaises(CanonicalizationError):
            self._item(decided_by="someone", decided_at=REVIEWED_AT)
        with self.assertRaises(CanonicalizationError):
            self._item(chosen_canonical_key="GENE:CYP2C19")

    def test_a_decision_may_only_choose_an_actual_candidate(self):
        with self.assertRaises(CanonicalizationError):
            self._item(decided_by="someone", decided_at=REVIEWED_AT,
                       decision_rationale="because",
                       chosen_canonical_key="GENE:CYP3A4")

    def test_a_complete_decision_choosing_a_candidate_is_accepted(self):
        item = self._item(decided_by="a-reviewer", decided_at=REVIEWED_AT,
                          decision_rationale="examined both source records",
                          chosen_canonical_key="GENE:CYP2C19")
        self.assertTrue(item.is_decided)

    def test_the_queue_item_keeps_every_candidate_in_its_json(self):
        self.assertEqual(self._item().to_json()["candidate_keys"],
                         ["GENE:CYP2C19", "GENE:CYP2D6"])


class TestDuplicateGroup(unittest.TestCase):

    def _member(self, pointer, digest="sha256:" + "aa" * 32, spelling=None):
        return DuplicateMember(locator(pointer=pointer), digest, spelling)

    def test_a_group_of_one_is_not_a_duplicate(self):
        with self.assertRaises(CanonicalizationError):
            DuplicateGroup(group_key="g", record_type="r",
                           dedup_key_version="v", classification=DuplicateClass.EXACT,
                           representative_digest="sha256:" + "aa" * 32,
                           members=(self._member("/a"),))

    def test_a_conflicting_identity_group_must_block(self):
        with self.assertRaises(CanonicalizationError):
            DuplicateGroup(group_key="g", record_type="r",
                           dedup_key_version="v",
                           classification=DuplicateClass.CONFLICTING_IDENTITY,
                           representative_digest="sha256:" + "aa" * 32,
                           members=(self._member("/a"), self._member("/b")),
                           differences=("payloads differ",), blocking=False)

    def test_a_conflicting_identity_group_must_say_what_differs(self):
        with self.assertRaises(CanonicalizationError):
            DuplicateGroup(group_key="g", record_type="r",
                           dedup_key_version="v",
                           classification=DuplicateClass.CONFLICTING_IDENTITY,
                           representative_digest="sha256:" + "aa" * 32,
                           members=(self._member("/a"), self._member("/b")),
                           differences=(), blocking=True)

    def test_choosing_a_representative_drops_no_member(self):
        group = DuplicateGroup(
            group_key="g", record_type="r", dedup_key_version="v",
            classification=DuplicateClass.SEMANTIC,
            representative_digest="sha256:" + "aa" * 32,
            members=(self._member("/b", spelling="VariantAnnotation"),
                     self._member("/a", spelling="variantAnnotation")))
        self.assertEqual(group.member_count, 2)
        pointers = [member.locator.pointer for member in group.members]
        self.assertEqual(pointers, ["/a", "/b"])
        self.assertEqual(len(group.to_json()["members"]), 2)

    def test_container_spellings_are_reported_verbatim(self):
        group = DuplicateGroup(
            group_key="g", record_type="r", dedup_key_version="v",
            classification=DuplicateClass.SEMANTIC,
            representative_digest="sha256:" + "aa" * 32,
            members=(self._member("/a", spelling="variantAnnotation"),
                     self._member("/b", spelling="VariantAnnotation")))
        self.assertEqual(group.container_spellings,
                         ("VariantAnnotation", "variantAnnotation"))


class TestPayloadDigest(unittest.TestCase):

    def test_key_order_and_whitespace_do_not_change_a_digest(self):
        self.assertEqual(payload_digest({"a": 1, "b": [2, 3]}),
                         payload_digest({"b": [2, 3], "a": 1}))

    def test_different_content_digests_differently(self):
        self.assertNotEqual(payload_digest({"a": 1}), payload_digest({"a": 2}))

    def test_array_order_is_meaningful(self):
        self.assertNotEqual(payload_digest([1, 2]), payload_digest([2, 1]))


class TestCanonicalKey(unittest.TestCase):

    def test_it_is_readable_and_is_not_a_uuid(self):
        self.assertEqual(canonical_key_for(EntityType.GENE, "CYP2C19"),
                         "GENE:CYP2C19")
        self.assertEqual(canonical_key_for(EntityType.DRUG, "clopidogrel"),
                         "DRUG:clopidogrel")


if __name__ == "__main__":
    unittest.main()


class TestDuplicateGroupRefusesABareString(unittest.TestCase):
    """A missed comma once turned one difference into the alphabet.

    ``tuple("text",)`` is ``tuple("text")``, which is a tuple of characters.
    The constructor refuses a bare string so that mistake fails loudly instead
    of serialising a difference list of single letters.
    """

    def test_a_string_differences_value_is_refused(self):
        member_a = DuplicateMember(locator(pointer="/a"), "sha256:" + "aa" * 32)
        member_b = DuplicateMember(locator(pointer="/b"), "sha256:" + "bb" * 32)
        with self.assertRaises(CanonicalizationError):
            DuplicateGroup(
                group_key="g", record_type="r", dedup_key_version="v",
                classification=DuplicateClass.CONFLICTING_IDENTITY,
                representative_digest="sha256:" + "aa" * 32,
                members=(member_a, member_b),
                differences="payloads differ", blocking=True)
