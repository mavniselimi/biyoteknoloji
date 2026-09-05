# -*- coding: utf-8 -*-
"""SAFETY-INV-007: persistence requires the complete pinned bundle.

``LEGACY-BUG-007``: legacy wrote results with no version metadata, so a stored
result could not be attributed to the data and rules that produced it.

Each required field is omitted **individually** rather than as a set. A check
that counts fields passes a record missing one and carrying a duplicate, and
that is exactly the shape of bug that survives review.
"""

from __future__ import annotations

import unittest

from pgx.safety.controls import controls_for
from pgx.safety.evaluators import (REQUIRED_PERSISTENCE_FIELDS,
                                   evaluate_persistence_requires_complete_bundle)
from pgx.safety.vocabulary import InvariantId
from tests.fixtures.wp20 import unsafe_persistence


def _evaluate(store):
    return evaluate_persistence_requires_complete_bundle(
        store, unsafe_persistence.complete_record())


class TestTheCompleteBundleIsRequired(unittest.TestCase):

    def setUp(self):
        self.verdict = _evaluate(unsafe_persistence.SafeStore())

    def test_it_is_compliant(self):
        self.assertTrue(self.verdict.compliant, self.verdict.violations)

    def test_every_required_field_was_omitted_in_turn(self):
        """One sweep per field, plus the complete record and the partial-commit
        probe."""
        self.assertGreaterEqual(self.verdict.examined,
                                len(REQUIRED_PERSISTENCE_FIELDS) + 2)

    def test_the_complete_record_is_accepted(self):
        """A boundary that rejects everything enforces nothing."""
        store = unsafe_persistence.SafeStore()
        store(unsafe_persistence.complete_record())
        self.assertEqual(len(store.rows), 1)

    def test_the_required_fields_are_the_contract_s(self):
        for field_name in ("release_id", "software_version", "dataset_version",
                           "ruleset_version", "input_hash", "output_hash"):
            with self.subTest(field=field_name):
                self.assertIn(field_name, REQUIRED_PERSISTENCE_FIELDS)


class TestEveryNegativeControlIsDetected(unittest.TestCase):

    def test_each_permissive_store_is_rejected(self):
        for control in controls_for(InvariantId.INV_007):
            with self.subTest(control=control.control_id):
                factory = unsafe_persistence.UNSAFE_SUBJECTS[
                    control.control_id]
                verdict = _evaluate(factory())
                self.assertFalse(verdict.compliant,
                                 "%s was NOT detected" % control.control_id)
                self.assertEqual(verdict.refusal_code,
                                 "SAFETY_RELEASE_BUNDLE_INCOMPLETE")

    def test_a_store_that_checks_only_hashes_is_caught(self):
        verdict = _evaluate(unsafe_persistence.StoreMissingReleaseField())
        self.assertTrue(any("release_id" in v for v in verdict.violations),
                        verdict.violations)

    def test_partial_persistence_is_caught(self):
        """The worst of the four, because it looks like success."""
        verdict = _evaluate(unsafe_persistence.PartiallyCommittingStore())
        self.assertTrue(any("abandoned" in v for v in verdict.violations),
                        verdict.violations)

    def test_the_remaining_dependency_is_declared_not_hidden(self):
        """The blocker changed owner when WP-23 shipped; it did not vanish.

        Actor identity on the audit record *was* WP-23's to implement, and
        now is implemented: the canonical event carries actor, role, session
        reference, assurance and correlation id, and refuses construction
        without them where they apply. What remains is that no deployment has
        composed the store, so nothing has been recorded - an operational
        fact owned by WP-24 rather than a missing mechanism.

        Both halves matter. Dropping the blocker entirely would report this
        invariant as fully satisfied while no audit row has ever been
        written; keeping one that says WP-23 owes an implementation would be
        equally untrue in the other direction.
        """
        from pgx.safety.definitions import definitions_by_id

        blockers = definitions_by_id()["SAFETY-INV-007"].blockers
        self.assertTrue(blockers, "the operational half must stay declared")
        codes = {item.code for item in blockers}
        self.assertIn("SAFETY_AUDIT_IDENTITY_NOT_OPERATIONAL", codes)
        self.assertFalse([item for item in blockers
                          if item.owner.value == "WP-23"])

    def test_the_catalogue_and_the_fixtures_agree(self):
        declared = {c.control_id for c in controls_for(InvariantId.INV_007)}
        self.assertEqual(declared, set(unsafe_persistence.UNSAFE_SUBJECTS))
