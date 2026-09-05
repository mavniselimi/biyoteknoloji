# -*- coding: utf-8 -*-
"""SAFETY-INV-012: released results must be deterministic and auditable.

``LEGACY-BUG-007``. The safe control hashes through
``pgx.domain.hashing.sha256_digest`` - the function every release attributes a
result by - so a change to canonicalisation reaches this check.

Two sweeps: repetition catches a clock or an iteration order leaking into the
output, and re-ordering the medication list catches a result that depends on
the order its input arrived in.

The audit half of this invariant is **not** satisfied and is not claimed to be.
Actor, role, session and correlation identity on the append-only record belong
to WP-23, and operational repeat-run determinism belongs to WP-24. Both are
declared blockers, and ``TestTheDeferredHalfStaysDeclared`` holds them there.
"""

from __future__ import annotations

import unittest

from pgx.safety.controls import controls_for
from pgx.safety.evaluators import evaluate_deterministic_result
from pgx.safety.vocabulary import BlockerOwner, InvariantId
from tests.fixtures.wp20 import unsafe_determinism
from tests.unit.safety._support import production_canonical_engine


def _evaluate(engine):
    return evaluate_deterministic_result(
        engine, unsafe_determinism.base_input(),
        unsafe_determinism.orderings())


class TestTheCanonicalDigestIsDeterministic(unittest.TestCase):

    def setUp(self):
        self.verdict = _evaluate(production_canonical_engine())

    def test_it_is_compliant(self):
        self.assertTrue(self.verdict.compliant, self.verdict.violations)

    def test_repeats_and_orderings_were_both_swept(self):
        self.assertGreaterEqual(
            self.verdict.examined, 3 + len(unsafe_determinism.orderings()))

    def test_the_same_input_gives_the_same_hash(self):
        calculate = production_canonical_engine()
        request = unsafe_determinism.base_input()
        digests = {calculate(dict(request))["output_hash"] for _ in range(5)}
        self.assertEqual(len(digests), 1)

    def test_input_order_does_not_change_the_hash(self):
        calculate = production_canonical_engine()
        base = unsafe_determinism.base_input()
        baseline = calculate(dict(base))["output_hash"]
        for ordering in unsafe_determinism.orderings():
            with self.subTest(order=ordering):
                shuffled = dict(base)
                shuffled["medications"] = list(ordering)
                self.assertEqual(calculate(shuffled)["output_hash"], baseline)

    def test_a_different_release_does_change_the_hash(self):
        """Determinism is not insensitivity. A different pinned bundle must
        produce a different result, or the hash is not attributing anything."""
        calculate = production_canonical_engine()
        base = unsafe_determinism.base_input()
        other = dict(base, release_id="REL-TEST-999")
        self.assertNotEqual(calculate(dict(base))["output_hash"],
                            calculate(other)["output_hash"])


class TestEveryNegativeControlIsDetected(unittest.TestCase):

    def test_each_non_deterministic_engine_is_rejected(self):
        for control in controls_for(InvariantId.INV_012):
            with self.subTest(control=control.control_id):
                factory = unsafe_determinism.UNSAFE_SUBJECTS[
                    control.control_id]
                subject = factory() if isinstance(factory, type) else factory
                verdict = _evaluate(subject)
                self.assertFalse(verdict.compliant,
                                 "%s was NOT detected" % control.control_id)
                self.assertEqual(verdict.refusal_code,
                                 "SAFETY_NON_DETERMINISTIC_RESULT")

    def test_a_missing_sort_is_what_is_caught(self):
        """One line separates the safe engine from this one."""
        verdict = _evaluate(unsafe_determinism.order_dependent_engine)
        self.assertTrue(any("re-ordering" in v for v in verdict.violations),
                        verdict.violations)

    def test_a_mid_run_release_change_is_caught(self):
        verdict = _evaluate(unsafe_determinism.MidRunReleaseChangingEngine())
        self.assertTrue(any("different output hashes" in v
                            for v in verdict.violations), verdict.violations)

    def test_a_wall_clock_in_the_hash_is_caught(self):
        verdict = _evaluate(unsafe_determinism.wall_clock_engine)
        self.assertFalse(verdict.compliant)

    def test_the_catalogue_and_the_fixtures_agree(self):
        declared = {c.control_id for c in controls_for(InvariantId.INV_012)}
        self.assertEqual(declared, set(unsafe_determinism.UNSAFE_SUBJECTS))


class TestTheDeferredHalfStaysDeclared(unittest.TestCase):
    """Determinism is enforced now. Auditability is not, and says so."""

    def setUp(self):
        from pgx.safety.definitions import definitions_by_id
        self.definition = definitions_by_id()["SAFETY-INV-012"]

    def test_audit_completeness_is_implemented_and_unexercised(self):
        """WP-23 implemented it. Nothing has run it.

        This asserted that WP-23 *owed* audit completeness, which was true
        until WP-23 delivered it. The successor pins the pair that is now
        true: the implementation blocker is gone, and a blocker naming the
        operational gap has taken its place. An invariant with no blocker at
        all would be reporting itself satisfied on a system that has never
        written an audit row.
        """
        codes = {blocker.code for blocker in self.definition.blockers}
        owners = {blocker.owner for blocker in self.definition.blockers}
        self.assertIn("SAFETY_AUDIT_COMPLETENESS_NOT_OPERATIONAL", codes)
        self.assertNotIn(BlockerOwner.WP_23_AUTH_AUDIT, owners)

    def test_wp24_owns_operational_repeatability(self):
        owners = {blocker.owner for blocker in self.definition.blockers}
        self.assertIn(BlockerOwner.WP_24_CI_DEPLOY, owners)

    def test_the_persistence_surface_is_reported_as_a_gap(self):
        """The contract requires enforcement at the persistence boundary; that
        half is WP-23's, and the registry reports the difference rather than
        listing a surface nothing covers."""
        gap = [surface.value for surface in self.definition.surface_gap]
        self.assertIn("PERSISTENCE_BOUNDARY", gap)

    def test_no_authentication_was_invented_inside_the_safety_layer(self):
        """WP-23's security layer exists. None of it is in ``pgx/safety``.

        The original list named WP-23's own files as forbidden anywhere,
        which stopped being meaningful when they were legitimately built. The
        durable property is that the safety layer contains no authentication
        of its own: a gate that established a principal would be deciding who
        is allowed to be checked.
        """
        import os
        from tests.unit.safety._support import REPO_ROOT
        for path in ("pgx/safety/auth.py", "pgx/safety/security.py",
                     "pgx/safety/audit.py", "pgx/safety/principals.py"):
            with self.subTest(path=path):
                self.assertFalse(
                    os.path.exists(os.path.join(REPO_ROOT, *path.split("/"))))
