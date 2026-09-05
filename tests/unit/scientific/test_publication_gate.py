# -*- coding: utf-8 -*-
"""The gate that decides whether a dataset may be published.

Three properties are checked, in this order of importance:

1. **It blocks by default.** Against the checked-in registry - the real one,
   with nothing approved - every reasonable intent is refused.
2. **The intent decides which questions are asked.** A dataset that only stores
   and analyses records is not judged against redistribution terms.
3. **It is deterministic.** The same inputs give the same issues, in the same
   order, with the same digest. A gate whose verdict wobbled could not be cited
   by a release.
"""

from __future__ import annotations

import datetime as _dt
import os
import unittest

from pgx.scientific.models import ClaimCategory, ReuseDimension, ReuseMatrix, ReusePermission
from pgx.scientific.policy import load_registry
from pgx.scientific.publication_gate import (
    PublicationDecision,
    PublicationIntent,
    evaluate_publication,
)
from pgx.scientific.validation import CORE_PUBLICATION_DIMENSIONS, PolicyIssueCode

from tests.unit.scientific import _fixtures as fx

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
CONFIG_PATH = os.path.join(REPO_ROOT, "config", "scientific-sources.json")


class TestTheDefaultRegistryPublishesNothing(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.registry = load_registry(CONFIG_PATH)

    def _evaluate(self, **kwargs):
        intent = PublicationIntent(dataset_key="PGX-DS-TEST", **kwargs)
        return evaluate_publication(self.registry, intent, fx.NOW)

    def test_a_dataset_citing_a_real_candidate_source_is_blocked(self):
        result = self._evaluate(source_keys=("cpic.database",))
        self.assertIs(result.decision, PublicationDecision.BLOCKED)

    def test_the_verdict_says_the_source_is_unreviewed(self):
        result = self._evaluate(source_keys=("cpic.database",))
        self.assertIn(PolicyIssueCode.SOURCE_PENDING_REVIEW.value,
                      result.blocking_codes)

    def test_every_candidate_source_is_blocked_individually(self):
        for key in self.registry.source_keys:
            with self.subTest(source=key):
                self.assertIs(self._evaluate(source_keys=(key,)).decision,
                              PublicationDecision.BLOCKED)

    def test_a_dataset_citing_nothing_is_blocked(self):
        result = self._evaluate()
        self.assertIs(result.decision, PublicationDecision.BLOCKED)
        self.assertIn(PolicyIssueCode.REGISTRY_EMPTY.value, result.blocking_codes)


class TestAnUnregisteredSourceBlocks(unittest.TestCase):

    def test_citing_a_source_with_no_policy_is_refused(self):
        registry = fx.registry(fx.approved_source())
        intent = PublicationIntent(dataset_key="d",
                                   source_keys=("fixture.nosuchsource",))
        result = evaluate_publication(registry, intent, fx.NOW)
        self.assertIs(result.decision, PublicationDecision.BLOCKED)
        self.assertIn(PolicyIssueCode.SOURCE_UNREGISTERED.value,
                      result.blocking_codes)


class TestACompletePolicyLetsAPublicationThrough(unittest.TestCase):
    """The mechanism works; it is the real registry that is unapproved."""

    def setUp(self):
        self.registry = fx.registry(fx.approved_source())

    def _evaluate(self, **kwargs):
        intent = PublicationIntent(dataset_key="d",
                                   source_keys=("fixture.approved",), **kwargs)
        return evaluate_publication(self.registry, intent, fx.NOW)

    def test_it_is_eligible(self):
        self.assertIs(self._evaluate().decision, PublicationDecision.ELIGIBLE)

    def test_an_eligible_verdict_carries_no_blocking_issue(self):
        self.assertEqual(self._evaluate().blockers, ())

    def test_a_claim_category_the_source_supports_is_permitted(self):
        result = self._evaluate(
            claim_categories=(ClaimCategory.PRIMARY_GUIDELINE_RECOMMENDATION,))
        self.assertIs(result.decision, PublicationDecision.ELIGIBLE)

    def test_a_claim_category_nothing_supports_is_refused(self):
        result = self._evaluate(
            claim_categories=(ClaimCategory.DRUG_LABEL_STATEMENT,))
        self.assertIs(result.decision, PublicationDecision.BLOCKED)
        self.assertIn(PolicyIssueCode.NO_CLAIM_CATEGORY_APPROVED.value,
                      result.blocking_codes)

    def test_one_cleared_source_is_enough_for_a_category(self):
        """A dataset may cite a source that backs a different category."""
        registry = fx.registry(
            fx.approved_source(source_key="fixture.guideline"),
            fx.approved_source(source_key="fixture.mapping",
                               categories=(ClaimCategory.PHENOTYPE_MAPPING,)))
        intent = PublicationIntent(
            dataset_key="d",
            source_keys=("fixture.guideline", "fixture.mapping"),
            claim_categories=(ClaimCategory.PHENOTYPE_MAPPING,))
        self.assertIs(evaluate_publication(registry, intent, fx.NOW).decision,
                      PublicationDecision.ELIGIBLE)


class TestTheIntentDecidesWhichQuestionsAreAsked(unittest.TestCase):

    def setUp(self):
        # Everything the project does internally is allowed; publishing the
        # source's records verbatim is not. A perfectly ordinary licence shape.
        permissions = {d: ReusePermission.ALLOWED for d in ReuseDimension}
        permissions[ReuseDimension.VERBATIM_REDISTRIBUTION] = \
            ReusePermission.PROHIBITED
        self.registry = fx.registry(
            fx.approved_source(reuse=ReuseMatrix(permissions)))

    def _evaluate(self, **kwargs):
        intent = PublicationIntent(dataset_key="d",
                                   source_keys=("fixture.approved",), **kwargs)
        return evaluate_publication(self.registry, intent, fx.NOW)

    def test_internal_use_only_is_eligible(self):
        self.assertIs(self._evaluate().decision, PublicationDecision.ELIGIBLE)

    def test_verbatim_redistribution_is_refused(self):
        result = self._evaluate(redistributes_verbatim=True)
        self.assertIs(result.decision, PublicationDecision.BLOCKED)
        self.assertIn(PolicyIssueCode.REUSE_PERMISSION_PROHIBITED.value,
                      result.blocking_codes)

    def test_the_core_dimensions_are_always_in_scope(self):
        intent = PublicationIntent(dataset_key="d")
        for dimension in CORE_PUBLICATION_DIMENSIONS:
            self.assertIn(dimension, intent.required_dimensions)

    def test_each_flag_adds_exactly_its_own_dimension(self):
        cases = (
            ("displays_source_text", ReuseDimension.PUBLIC_DISPLAY),
            ("redistributes_aggregated", ReuseDimension.AGGREGATED_REDISTRIBUTION),
            ("redistributes_verbatim", ReuseDimension.VERBATIM_REDISTRIBUTION),
            ("shares_with_third_party", ReuseDimension.THIRD_PARTY_SHARING),
            ("commercial_use", ReuseDimension.COMMERCIAL_USE),
            ("automated_acquisition", ReuseDimension.AUTOMATED_ACQUISITION),
            ("bulk_download", ReuseDimension.BULK_DOWNLOAD),
        )
        base = set(PublicationIntent(dataset_key="d").required_dimensions)
        for flag, dimension in cases:
            with self.subTest(flag=flag):
                widened = set(PublicationIntent(
                    dataset_key="d", **{flag: True}).required_dimensions)
                self.assertEqual(widened - base, {dimension})

    def test_the_narrowest_intent_is_the_default(self):
        """A caller who forgets a flag asks for less, never more."""
        intent = PublicationIntent(dataset_key="d")
        self.assertEqual(set(intent.required_dimensions),
                         set(CORE_PUBLICATION_DIMENSIONS))

    def test_required_dimensions_are_in_canonical_order(self):
        intent = PublicationIntent(dataset_key="d", commercial_use=True,
                                   displays_source_text=True)
        canonical = [d for d in ReuseDimension if d in intent.required_dimensions]
        self.assertEqual(list(intent.required_dimensions), canonical)


class TestTheVerdictIsDeterministic(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.registry = load_registry(CONFIG_PATH)
        cls.intent = PublicationIntent(
            dataset_key="PGX-DS-TEST",
            source_keys=("cpic.database", "clinpgx.api"),
            claim_categories=(ClaimCategory.PRIMARY_GUIDELINE_RECOMMENDATION,))

    def _run(self):
        return evaluate_publication(self.registry, self.intent, fx.NOW)

    def test_two_runs_produce_the_same_digest(self):
        self.assertEqual(self._run().digest(), self._run().digest())

    def test_two_runs_produce_the_same_issue_order(self):
        first = [issue.to_json() for issue in self._run().issues]
        second = [issue.to_json() for issue in self._run().issues]
        self.assertEqual(first, second)

    def test_source_key_order_does_not_change_the_verdict(self):
        reversed_intent = PublicationIntent(
            dataset_key="PGX-DS-TEST",
            source_keys=("clinpgx.api", "cpic.database"),
            claim_categories=(ClaimCategory.PRIMARY_GUIDELINE_RECOMMENDATION,))
        self.assertEqual(
            evaluate_publication(self.registry, reversed_intent, fx.NOW).digest(),
            self._run().digest())

    def test_a_different_instant_gives_a_different_digest(self):
        """The instant is part of the verdict: an approval can expire."""
        later = fx.NOW + _dt.timedelta(days=1)
        self.assertNotEqual(
            evaluate_publication(self.registry, self.intent, later).digest(),
            self._run().digest())

    def test_blockers_are_reported_before_warnings(self):
        severities = [issue.severity.value for issue in self._run().issues]
        self.assertEqual(severities, sorted(
            severities, key=lambda s: {"BLOCKER": 0, "WARNING": 1,
                                       "INFO": 2}[s]))

    def test_the_verdict_records_the_registry_it_judged(self):
        self.assertEqual(self._run().registry_content_hash,
                         self.registry.content_hash())

    def test_nothing_short_circuits(self):
        """An operator repairing a dataset gets the whole list at once."""
        result = self._run()
        subjects = {issue.subject for issue in result.blockers}
        self.assertIn("cpic.database", subjects)
        self.assertIn("clinpgx.api", subjects)


class TestTheVerdictRendersAndSerialises(unittest.TestCase):

    def setUp(self):
        self.result = evaluate_publication(
            fx.registry(fx.pending_source()),
            PublicationIntent(dataset_key="d", source_keys=("fixture.pending",)),
            fx.NOW)

    def test_the_json_form_names_the_decision_and_every_issue(self):
        document = self.result.to_json()
        self.assertEqual(document["decision"], "BLOCKED")
        self.assertEqual(len(document["issues"]), len(self.result.issues))
        self.assertEqual(document["summary"]["BLOCKER"],
                         len(self.result.blockers))

    def test_the_evaluated_instant_is_recorded_in_utc(self):
        self.assertTrue(self.result.to_json()["evaluated_at"].endswith("Z"))

    def test_the_rendered_report_names_the_decision(self):
        self.assertIn("BLOCKED", self.result.render())

    def test_blocking_codes_are_sorted_and_unique(self):
        codes = list(self.result.blocking_codes)
        self.assertEqual(codes, sorted(set(codes)))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
