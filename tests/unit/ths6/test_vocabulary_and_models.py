# -*- coding: utf-8 -*-
"""The vocabulary refuses to be truthy, and the models refuse bad records.

Every test here defends one substitution. The most important is the first: if
an ``IMPLEMENTATION_TEST`` could ever answer "does this support a THS 6
claim" affirmatively, this repository's 6,920 passing tests would become
scientific evidence, and the whole work package would be decoration.

The second most important is the absence of a generic truthy API. There is no
``is_ok``, no ``__bool__``, no ``passed`` and no ``status`` string a caller
could truth-test, and these tests assert the absence by inspection rather
than by convention, because a convention is what somebody adds a helper to.
"""

from __future__ import annotations

import inspect
import unittest

from pgx.ths6 import (artifacts, claim_registry, contingency,
                      definition_of_done, demo, evidence_registry,
                      gate_matrix, integrity, models, pack, signoff, status,
                      traceability, vocabulary)
from pgx.ths6.models import (ClaimRecord, DefinitionOfDoneItem, EvidenceItem,
                             Finding, GateCondition, GateRecord,
                             TraceabilityRow, repository_relative)
from pgx.ths6.vocabulary import (BLOCKER_CODES, Blocker, ClaimSupport,
                                 EvidenceType, GateResult,
                                 PACK_INTEGRITY_IS_NOT_ACHIEVEMENT,
                                 exit_code_for_gate)

_MODULES = (artifacts, claim_registry, contingency, definition_of_done, demo,
            evidence_registry, gate_matrix, integrity, models, pack, signoff,
            status, traceability, vocabulary)


class TestEvidenceType(unittest.TestCase):

    def test_only_real_executed_and_observed_may_support_a_claim(self):
        affirmative = {item for item in EvidenceType
                       if item.may_support_a_ths6_claim}
        self.assertEqual(affirmative, {EvidenceType.REAL_EXECUTED,
                                       EvidenceType.REAL_OBSERVED})

    def test_a_passing_test_suite_is_not_evidence_for_a_claim(self):
        """The substitution this package exists to prevent."""
        self.assertFalse(
            EvidenceType.IMPLEMENTATION_TEST.may_support_a_ths6_claim)

    def test_a_rehearsal_is_not_evidence_for_a_claim(self):
        self.assertFalse(
            EvidenceType.TEST_ONLY_REHEARSAL.may_support_a_ths6_claim)

    def test_a_configured_thing_is_not_an_executed_one(self):
        self.assertFalse(
            EvidenceType.CONFIGURED_NOT_EXECUTED.may_support_a_ths6_claim)

    def test_a_document_is_not_a_result(self):
        self.assertFalse(EvidenceType.DOCUMENT_ONLY.may_support_a_ths6_claim)

    def test_the_three_pending_states_are_pending(self):
        self.assertEqual(
            {item for item in EvidenceType if item.is_pending},
            {EvidenceType.HUMAN_PENDING, EvidenceType.SCIENTIFIC_PENDING,
             EvidenceType.OPERATIONAL_PENDING})

    def test_pending_is_not_defective(self):
        """A missing approval is not a bug; a stale artifact is."""
        for item in EvidenceType:
            with self.subTest(item=item):
                self.assertFalse(item.is_pending and item.is_defective)

    def test_the_defective_states_are_stale_invalid_and_unavailable(self):
        self.assertEqual(
            {item for item in EvidenceType if item.is_defective},
            {EvidenceType.STALE, EvidenceType.INVALID,
             EvidenceType.UNAVAILABLE})

    def test_there_are_twelve_values(self):
        self.assertEqual(len(list(EvidenceType)), 12)

    def test_ordering_is_disabled(self):
        with self.assertRaises(TypeError):
            EvidenceType.REAL_EXECUTED < EvidenceType.DOCUMENT_ONLY
        with self.assertRaises(TypeError):
            EvidenceType.REAL_EXECUTED >= EvidenceType.DOCUMENT_ONLY


class TestClaimSupport(unittest.TestCase):

    def test_only_supported_is_sufficient(self):
        self.assertEqual(
            {item for item in ClaimSupport if item.is_sufficient},
            {ClaimSupport.SUPPORTED})

    def test_partially_supported_is_not_sufficient(self):
        self.assertFalse(ClaimSupport.PARTIALLY_SUPPORTED.is_sufficient)

    def test_not_evaluated_is_not_sufficient(self):
        self.assertFalse(ClaimSupport.NOT_EVALUATED.is_sufficient)

    def test_contradicted_is_not_sufficient(self):
        self.assertFalse(ClaimSupport.CONTRADICTED.is_sufficient)

    def test_publishable_matches_sufficient_today(self):
        for item in ClaimSupport:
            with self.subTest(item=item):
                self.assertEqual(item.is_publishable, item.is_sufficient)

    def test_ordering_is_disabled(self):
        with self.assertRaises(TypeError):
            ClaimSupport.SUPPORTED < ClaimSupport.UNSUPPORTED


class TestGateResult(unittest.TestCase):

    def test_only_pass_is_a_pass(self):
        self.assertEqual({item for item in GateResult if item.is_pass},
                         {GateResult.PASS})

    def test_blocked_is_not_a_pass(self):
        self.assertFalse(GateResult.BLOCKED.is_pass)

    def test_not_evaluated_is_not_a_pass(self):
        self.assertFalse(GateResult.NOT_EVALUATED.is_pass)

    def test_stale_is_not_a_pass(self):
        self.assertFalse(GateResult.STALE.is_pass)

    def test_fail_exits_louder_than_blocked(self):
        """A blocked gate is expected here; a failing one means a defect."""
        self.assertEqual(exit_code_for_gate(GateResult.FAIL), 1)
        self.assertEqual(exit_code_for_gate(GateResult.BLOCKED), 2)
        self.assertEqual(exit_code_for_gate(GateResult.PASS), 0)

    def test_not_evaluated_and_stale_exit_blocked(self):
        self.assertEqual(exit_code_for_gate(GateResult.NOT_EVALUATED), 2)
        self.assertEqual(exit_code_for_gate(GateResult.STALE), 2)

    def test_ordering_is_disabled(self):
        with self.assertRaises(TypeError):
            GateResult.PASS > GateResult.BLOCKED


class TestNoGenericTruthyApi(unittest.TestCase):
    """No package member offers a way to truth-test a status.

    Checked by inspection across every module rather than by reading the
    source once, because the failure mode is somebody adding a convenience
    helper months from now.
    """

    _FORBIDDEN = ("is_ok", "ok", "passed", "is_good", "succeeded",
                  "is_success", "is_valid_status", "truthy")

    def test_no_module_exports_a_generic_truthy_helper(self):
        for module in _MODULES:
            for name in self._FORBIDDEN:
                with self.subTest(module=module.__name__, name=name):
                    self.assertFalse(
                        hasattr(module, name),
                        "%s exports %r, which is a place IMPLEMENTED could "
                        "become PASS" % (module.__name__, name))

    def test_no_enum_defines_bool(self):
        for enum in (EvidenceType, ClaimSupport, GateResult):
            with self.subTest(enum=enum.__name__):
                self.assertNotIn("__bool__", vars(enum))

    def test_no_record_type_defines_bool(self):
        for record in (EvidenceItem, ClaimRecord, GateCondition, GateRecord,
                       DefinitionOfDoneItem, TraceabilityRow, Finding):
            with self.subTest(record=record.__name__):
                self.assertNotIn("__bool__", vars(record))

    def test_the_affirmative_predicates_are_each_true_for_one_value(self):
        self.assertEqual(
            sum(1 for item in EvidenceType if item.may_support_a_ths6_claim),
            2, "two evidence types, and no more, may support a claim")
        self.assertEqual(
            sum(1 for item in ClaimSupport if item.is_sufficient), 1)
        self.assertEqual(sum(1 for item in GateResult if item.is_pass), 1)


class TestNoOverrideExistsAnywhere(unittest.TestCase):
    """No module names a force, assume, fixture or ignore-blocker option."""

    _SPELLINGS = ("--force", "--assume", "--fixture", "--ignore-blocker",
                  "--skip-preconditions", "--override")

    def test_no_module_source_offers_an_override_flag(self):
        for module in _MODULES:
            source = inspect.getsource(module)
            for spelling in self._SPELLINGS:
                with self.subTest(module=module.__name__,
                                  spelling=spelling):
                    self.assertNotIn(
                        '"%s"' % spelling, source,
                        "%s declares %s" % (module.__name__, spelling))

    def test_the_cli_offers_no_override_flag(self):
        from pgx.application import ths6_cli

        source = inspect.getsource(ths6_cli)
        for spelling in self._SPELLINGS:
            with self.subTest(spelling=spelling):
                self.assertNotIn('add_argument("%s"' % spelling, source)


class TestBlockerCodes(unittest.TestCase):

    def test_every_code_has_an_explanation(self):
        for code, detail in sorted(BLOCKER_CODES.items()):
            with self.subTest(code=code):
                self.assertTrue(detail.strip())

    def test_an_undeclared_code_is_refused(self):
        with self.assertRaises(ValueError):
            Blocker("THS6_MADE_UP", "detail", "owner")

    def test_a_blocker_needs_a_detail(self):
        with self.assertRaises(ValueError):
            Blocker("THS6_NO_APPROVED_SOURCE", "   ", "owner")

    def test_a_blocker_needs_an_owner(self):
        with self.assertRaises(ValueError):
            Blocker("THS6_NO_APPROVED_SOURCE", "detail", "")

    def test_a_blocker_serialises_as_blocking(self):
        blocker = Blocker("THS6_NO_APPROVED_SOURCE", "detail", "owner")
        self.assertIs(blocker.to_json()["blocking"], True)

    def test_the_integrity_disclaimer_is_spelled_once(self):
        self.assertIn("not the programme", PACK_INTEGRITY_IS_NOT_ACHIEVEMENT)


class TestRepositoryRelativePaths(unittest.TestCase):

    def test_an_absolute_posix_path_is_refused(self):
        with self.assertRaises(ValueError):
            repository_relative("/etc/passwd")

    def test_a_home_relative_path_is_refused(self):
        with self.assertRaises(ValueError):
            repository_relative("~/secrets.json")

    def test_a_windows_drive_letter_is_refused(self):
        with self.assertRaises(ValueError):
            repository_relative("C:\\Users\\somebody\\file.json")

    def test_a_unc_path_is_refused(self):
        with self.assertRaises(ValueError):
            repository_relative("\\\\server\\share\\file.json")

    def test_a_parent_traversal_is_refused(self):
        """Relative in spelling is not relative in effect."""
        with self.assertRaises(ValueError):
            repository_relative("docs/../../etc/passwd")

    def test_an_empty_path_is_refused(self):
        with self.assertRaises(ValueError):
            repository_relative("   ")

    def test_an_ordinary_path_is_accepted(self):
        self.assertEqual(repository_relative("data/ths6/x.json"),
                         "data/ths6/x.json")


class TestEvidenceItemRefusals(unittest.TestCase):

    def _item(self, **overrides):
        fields = dict(evidence_id="EV-WP20-001", title="t",
                      work_package="WP-20",
                      evidence_type=EvidenceType.DOCUMENT_ONLY,
                      path="docs/x.md")
        fields.update(overrides)
        return EvidenceItem(**fields)

    def test_a_malformed_identifier_is_refused(self):
        with self.assertRaises(ValueError):
            self._item(evidence_id="EV-20-001")

    def test_an_out_of_range_work_package_is_refused(self):
        with self.assertRaises(ValueError):
            self._item(evidence_id="EV-WP26-001")

    def test_an_absolute_path_is_refused(self):
        with self.assertRaises(ValueError):
            self._item(path="/Users/somebody/x.md")

    def test_a_test_only_item_may_not_be_typed_real(self):
        with self.assertRaises(ValueError):
            self._item(evidence_type=EvidenceType.REAL_EXECUTED,
                       test_only=True)

    def test_a_rehearsal_type_must_be_marked_test_only(self):
        with self.assertRaises(ValueError):
            self._item(evidence_type=EvidenceType.TEST_ONLY_REHEARSAL,
                       test_only=False)

    def test_a_document_may_not_claim_a_real_observation(self):
        with self.assertRaises(ValueError):
            self._item(observed_or_executed=True)

    def test_a_limitation_needs_an_owner(self):
        with self.assertRaises(ValueError):
            self._item(limitations=("partial",))

    def test_a_limitation_with_an_owner_is_accepted(self):
        item = self._item(limitations=("partial",), gap_owner="data owner")
        self.assertEqual(item.gap_owner, "data owner")

    def test_a_malformed_claim_reference_is_refused(self):
        with self.assertRaises(ValueError):
            self._item(supported_claim_ids=("CLAIM-1",))

    def test_a_malformed_gate_reference_is_refused(self):
        with self.assertRaises(ValueError):
            self._item(gate_ids=("GATE-Z",))

    def test_a_title_is_required(self):
        with self.assertRaises(ValueError):
            self._item(title="  ")

    def test_the_media_type_is_derived_from_the_suffix(self):
        self.assertEqual(self._item(path="a/b.json").declared_media_type,
                         "application/json")
        self.assertEqual(self._item(path="a/b.md").declared_media_type,
                         "text/markdown")

    def test_the_serialised_form_reports_admissibility(self):
        document = self._item().to_json()
        self.assertIs(document["may_support_a_ths6_claim"], False)


class TestClaimRecordRefusals(unittest.TestCase):

    def _claim(self, **overrides):
        fields = dict(claim_id="THS6-CLAIM-001", statement="s",
                      origin="architecture.md",
                      required_evidence_ids=("EV-WP20-001",))
        fields.update(overrides)
        return ClaimRecord(**fields)

    def test_a_claim_requiring_no_evidence_is_refused(self):
        """A claim that needs nothing is one nothing can refute."""
        with self.assertRaises(ValueError):
            self._claim(required_evidence_ids=())

    def test_a_malformed_identifier_is_refused(self):
        with self.assertRaises(ValueError):
            self._claim(claim_id="CLAIM-001")

    def test_a_statement_is_required(self):
        with self.assertRaises(ValueError):
            self._claim(statement="")

    def test_an_origin_is_required(self):
        with self.assertRaises(ValueError):
            self._claim(origin=" ")

    def test_a_malformed_required_evidence_id_is_refused(self):
        with self.assertRaises(ValueError):
            self._claim(required_evidence_ids=("EV-1",))

    def test_a_malformed_dod_reference_is_refused(self):
        with self.assertRaises(ValueError):
            self._claim(dod_ids=("P0-DOD-016",))

    def test_the_default_support_is_not_evaluated(self):
        self.assertIs(self._claim().support, ClaimSupport.NOT_EVALUATED)


class TestGateRecordRefusals(unittest.TestCase):

    def _condition(self, met=True, blocker=None):
        return GateCondition(
            condition_id="X1", description="d", source_path="data/x.json",
            source_field="f", expected="is true", observed="True", met=met,
            blocker=blocker)

    def test_an_unmet_condition_must_name_a_blocker(self):
        with self.assertRaises(ValueError):
            self._condition(met=False)

    def test_a_met_condition_may_not_carry_a_blocker(self):
        with self.assertRaises(ValueError):
            self._condition(met=True, blocker=Blocker(
                "THS6_NO_APPROVED_SOURCE", "d", "o"))

    def test_an_unevaluated_condition_needs_no_blocker(self):
        self.assertIsNone(self._condition(met=None).blocker)

    def test_a_gate_with_no_condition_is_refused(self):
        """A gate with nothing to check would pass for free."""
        with self.assertRaises(ValueError):
            GateRecord(gate_id="GATE-A", title="t", conditions=(),
                       result=GateResult.PASS)

    def test_pass_beside_an_unmet_condition_is_refused(self):
        blocker = Blocker("THS6_NO_APPROVED_SOURCE", "d", "o")
        with self.assertRaises(ValueError):
            GateRecord(
                gate_id="GATE-A", title="t",
                conditions=(self._condition(met=False, blocker=blocker),),
                result=GateResult.PASS)

    def test_pass_beside_an_unevaluated_condition_is_refused(self):
        with self.assertRaises(ValueError):
            GateRecord(gate_id="GATE-A", title="t",
                       conditions=(self._condition(met=None),),
                       result=GateResult.PASS)

    def test_pass_while_carrying_a_blocker_is_refused(self):
        with self.assertRaises(ValueError):
            GateRecord(gate_id="GATE-A", title="t",
                       conditions=(self._condition(),),
                       result=GateResult.PASS,
                       blockers=(Blocker("THS6_NO_APPROVED_SOURCE", "d",
                                         "o"),))

    def test_a_clean_pass_is_accepted(self):
        record = GateRecord(gate_id="GATE-A", title="t",
                            conditions=(self._condition(),),
                            result=GateResult.PASS)
        self.assertEqual(record.unmet_condition_ids, ())
        self.assertIs(record.to_json()["is_pass"], True)

    def test_a_malformed_gate_identifier_is_refused(self):
        with self.assertRaises(ValueError):
            GateRecord(gate_id="GATE-G", title="t",
                       conditions=(self._condition(),),
                       result=GateResult.BLOCKED)


class TestDefinitionOfDoneItemRefusals(unittest.TestCase):

    def _item(self, **overrides):
        fields = dict(dod_id="P0-DOD-001", architecture_text="text",
                      observable_condition="condition", satisfied=True)
        fields.update(overrides)
        return DefinitionOfDoneItem(**fields)

    def test_an_out_of_range_identifier_is_refused(self):
        with self.assertRaises(ValueError):
            self._item(dod_id="P0-DOD-016")

    def test_a_zero_identifier_is_refused(self):
        with self.assertRaises(ValueError):
            self._item(dod_id="P0-DOD-000")

    def test_an_unsatisfied_item_needs_an_owner(self):
        with self.assertRaises(ValueError):
            self._item(satisfied=False, blockers=(Blocker(
                "THS6_NO_APPROVED_SOURCE", "d", "o"),))

    def test_an_unsatisfied_item_needs_a_blocker(self):
        with self.assertRaises(ValueError):
            self._item(satisfied=False, owner="data owner")

    def test_an_unevaluated_item_still_needs_an_owner(self):
        with self.assertRaises(ValueError):
            self._item(satisfied=None)

    def test_the_architecture_text_is_required(self):
        with self.assertRaises(ValueError):
            self._item(architecture_text="  ")


class TestTraceabilityRowRefusals(unittest.TestCase):

    def _row(self, **overrides):
        fields = dict(row_id="R1", requirement="r",
                      requirement_source="architecture.md",
                      implementation_paths=("pgx/ths6/",),
                      test_paths=("tests/unit/ths6/",), evidence_ids=(),
                      claim_ids=(), gate_ids=(), dod_ids=(),
                      result=ClaimSupport.SUPPORTED)
        fields.update(overrides)
        return TraceabilityRow(**fields)

    def test_an_unsupported_row_needs_a_gap_owner(self):
        with self.assertRaises(ValueError):
            self._row(result=ClaimSupport.UNSUPPORTED, gap="missing")

    def test_an_unsupported_row_must_say_what_is_missing(self):
        with self.assertRaises(ValueError):
            self._row(result=ClaimSupport.UNSUPPORTED, gap_owner="owner")

    def test_an_absolute_implementation_path_is_refused(self):
        with self.assertRaises(ValueError):
            self._row(implementation_paths=("/opt/pgx/",))

    def test_a_supported_row_needs_no_gap(self):
        self.assertEqual(self._row().gap, "")


class TestFinding(unittest.TestCase):

    def test_an_undeclared_code_is_refused(self):
        with self.assertRaises(ValueError):
            Finding("MADE_UP", "d", "o", "r")

    def test_a_resolution_is_required(self):
        with self.assertRaises(ValueError):
            Finding("THS6_EVIDENCE_STALE", "d", "o", "  ")

    def test_an_owner_is_required(self):
        with self.assertRaises(ValueError):
            Finding("THS6_EVIDENCE_STALE", "d", "", "r")

    def test_a_finding_defaults_to_non_blocking(self):
        self.assertIs(Finding("THS6_EVIDENCE_STALE", "d", "o", "r").blocking,
                      False)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
