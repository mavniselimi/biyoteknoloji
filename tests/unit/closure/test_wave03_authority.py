# -*- coding: utf-8 -*-
"""Wave 3 authority-state bridge (WP-C07 workstream A)."""

from __future__ import annotations

import os
import subprocess
import unittest

from pgx.closure.authority import (BRIDGE_ENTRIES, CANDIDATE_STATE_MEANINGS,
                                   PERMITTED_PRE_EXPERT_STATES,
                                   PROHIBITED_AUTHORITY_TERMS,
                                   CandidateAuthorityState,
                                   CandidateDecisionRecord,
                                   SatisfiabilityVerdict, bridge_table,
                                   contains_prohibited_term, describe_state)

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))


class ProhibitedTermsTest(unittest.TestCase):

    def test_the_five_terms_are_exactly_the_ones_the_policy_names(self):
        self.assertEqual(len(PROHIBITED_AUTHORITY_TERMS), 5)
        self.assertEqual(len(set(PROHIBITED_AUTHORITY_TERMS)), 5)
        for term in PROHIBITED_AUTHORITY_TERMS:
            self.assertRegex(term, r"^[A-Z]+_[A-Z]+$")

    def test_the_defining_module_does_not_contain_the_literals(self):
        # The whole point of assembling them at runtime. If this file ever
        # spells them out, the repository scan below starts matching its own
        # definition and stops being a test.
        path = os.path.join(_REPO, "pgx", "closure", "authority.py")
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        for term in PROHIBITED_AUTHORITY_TERMS:
            self.assertNotIn(term, text)

    def _wave03_artifacts(self):
        """Every file this wave wrote, found rather than listed.

        A hand-maintained list would silently stop covering the artifact
        somebody added last, which is the one most likely to overclaim.
        """
        found = []
        for directory, predicate in (
                (os.path.join("pgx", "closure"),
                 lambda n: n.startswith(("authority", "source_",
                                         "candidate_", "wave03"))),
                (os.path.join("tests", "unit", "closure"),
                 lambda n: n.startswith("test_wave03")),
                ("scripts", lambda n: n.startswith(
                    "build_closure_wave03")),
                (os.path.join("docs", "closure"),
                 lambda n: n.startswith("wave-03")),
                (os.path.join("data", "closure"),
                 lambda n: n.startswith("wave-03")),
        ):
            base = os.path.join(_REPO, directory)
            if not os.path.isdir(base):
                continue
            for name in sorted(os.listdir(base)):
                if not predicate(name):
                    continue
                full = os.path.join(base, name)
                if os.path.isdir(full):
                    for inner in sorted(os.listdir(full)):
                        found.append(os.path.join(full, inner))
                else:
                    found.append(full)
        return found

    def test_no_wave03_artifact_claims_a_prohibited_authority(self):
        artifacts = self._wave03_artifacts()
        # The test file defining the terms is excluded, and only that one.
        artifacts = [p for p in artifacts
                     if os.path.basename(p) != os.path.basename(__file__)]
        self.assertGreaterEqual(len(artifacts), 15,
                                "the artifact sweep found almost nothing, so "
                                "it is not checking what it claims to")
        for path in artifacts:
            if os.path.isdir(path) or path.endswith((".pyc", ".sha256")):
                continue
            with open(path, encoding="utf-8", errors="replace") as handle:
                text = handle.read()
            self.assertEqual(
                contains_prohibited_term(text), (),
                "%s claims a prohibited authority"
                % os.path.relpath(path, _REPO))

    def test_contains_prohibited_term_actually_matches(self):
        # A scanner that never matches anything would pass every test above.
        sample = "state: " + PROHIBITED_AUTHORITY_TERMS[0]
        self.assertEqual(contains_prohibited_term(sample),
                         (PROHIBITED_AUTHORITY_TERMS[0],))

    def test_contains_prohibited_term_rejects_non_strings(self):
        with self.assertRaises(TypeError):
            contains_prohibited_term(None)


class StateVocabularyTest(unittest.TestCase):

    def test_exactly_six_permitted_states(self):
        self.assertEqual(len(PERMITTED_PRE_EXPERT_STATES), 6)
        self.assertEqual(set(PERMITTED_PRE_EXPERT_STATES), {
            "SOURCE_GROUNDED_INTERNAL_DECISION",
            "PROJECT_TEAM_PROVISIONAL",
            "PENDING_EXTERNAL_EXPERT_REVIEW",
            "INTERNAL_VALIDATION",
            "LITERATURE_DERIVED_VALIDATION",
            "SOFTWARE_VERIFICATION",
        })

    def test_every_state_says_what_it_does_not_claim(self):
        for state in CandidateAuthorityState:
            claims, denies = describe_state(state)
            self.assertTrue(claims.strip())
            self.assertTrue(denies.strip())
            self.assertNotEqual(claims, denies)

    def test_meanings_cover_the_enum_exactly(self):
        self.assertEqual(set(CANDIDATE_STATE_MEANINGS),
                         set(PERMITTED_PRE_EXPERT_STATES))

    def test_states_are_not_ordered(self):
        with self.assertRaises(TypeError):
            _ = (CandidateAuthorityState.INTERNAL_VALIDATION <
                 CandidateAuthorityState.SOFTWARE_VERIFICATION)

    def test_describe_state_refuses_a_bare_string(self):
        with self.assertRaises(TypeError):
            describe_state("INTERNAL_VALIDATION")


class BridgeTableTest(unittest.TestCase):

    def test_requirement_ids_are_unique_and_ordered(self):
        ids = [entry.requirement_id for entry in BRIDGE_ENTRIES]
        self.assertEqual(len(set(ids)), len(ids))
        rows = bridge_table()
        self.assertEqual([row["requirement_id"] for row in rows],
                         sorted(ids))

    def test_every_entry_names_a_module_that_exists(self):
        for entry in BRIDGE_ENTRIES:
            path = os.path.join(_REPO, entry.module)
            self.assertTrue(os.path.exists(path),
                            "%s names a module that does not exist: %s"
                            % (entry.requirement_id, entry.module))

    def test_blocked_entries_exist_and_carry_a_reason(self):
        blocked = [e for e in BRIDGE_ENTRIES
                   if e.verdict in (
                       SatisfiabilityVerdict.BLOCKED_REQUIRES_EXTERNAL_HUMAN,
                       SatisfiabilityVerdict
                       .BLOCKED_REQUIRES_SECOND_INTERNAL_HUMAN)]
        self.assertGreaterEqual(len(blocked), 4)
        for entry in blocked:
            self.assertTrue(entry.note.strip(),
                            "%s is blocked with no stated reason"
                            % entry.requirement_id)

    def test_the_approval_envelope_blocker_is_real(self):
        # AB-01 claims a rule cannot become VALIDATED without an approval
        # envelope. Assert the actual code property rather than trusting the
        # table's own prose about itself.
        from pgx.rules.models import RuleProvenance
        annotations = RuleProvenance.__annotations__
        self.assertIn("approval_envelope_hash", annotations)
        import dataclasses
        fields = {f.name: f for f in dataclasses.fields(RuleProvenance)}
        field = fields["approval_envelope_hash"]
        self.assertIs(field.default, dataclasses.MISSING,
                      "approval_envelope_hash has become optional; AB-01 and "
                      "the candidate track's whole reason for existing need "
                      "rechecking")

    def test_no_entry_claims_a_prohibited_authority(self):
        for entry in BRIDGE_ENTRIES:
            joined = " ".join((entry.requirement, entry.candidate_path,
                               entry.note))
            self.assertEqual(contains_prohibited_term(joined), (),
                             entry.requirement_id)


class CandidateDecisionRecordTest(unittest.TestCase):

    def _record(self, **overrides):
        payload = dict(
            decision_id="D-01", subject="a source", decision="use it",
            authority_state=(
                CandidateAuthorityState.SOURCE_GROUNDED_INTERNAL_DECISION),
            rationale="because the licence permits it",
            decided_at="2026-09-06", decided_by="the project team")
        payload.update(overrides)
        return CandidateDecisionRecord(**payload)

    def test_a_record_carries_both_halves_of_its_state(self):
        payload = self._record().to_json()
        self.assertTrue(payload["authority_state_claims"])
        self.assertTrue(payload["authority_state_does_not_claim"])

    def test_review_state_cannot_be_anything_else(self):
        with self.assertRaises(ValueError):
            self._record(
                review_state=CandidateAuthorityState.INTERNAL_VALIDATION)

    def test_authority_state_must_be_a_member(self):
        with self.assertRaises(TypeError):
            self._record(authority_state="INTERNAL_VALIDATION")

    def test_a_record_may_not_claim_a_prohibited_authority(self):
        with self.assertRaises(ValueError):
            self._record(decision="the ruleset is "
                         + PROHIBITED_AUTHORITY_TERMS[0])

    def test_blank_fields_are_refused(self):
        for name in ("decision_id", "subject", "decision", "rationale",
                     "decided_at", "decided_by"):
            with self.assertRaises(ValueError, msg=name):
                self._record(**{name: "   "})

    def test_revision_counts_from_one(self):
        with self.assertRaises(ValueError):
            self._record(revision=0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
