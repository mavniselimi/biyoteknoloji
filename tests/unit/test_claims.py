# -*- coding: utf-8 -*-
"""WP-00 unit tests for the central claims boundary and claim scanner.

Run with the standard library only:

    python3 -m unittest tests.unit.test_claims -v

These tests must not require pyproject.toml, pytest, FastAPI, Pydantic,
SQLAlchemy, PostgreSQL, or network access. WP-02 introduces the packaging
and dependency baseline; WP-00 must stay runnable before it exists.
"""

from __future__ import annotations

import ast
import io
import os
import sys
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from pgx.domain.claims import (  # noqa: E402
    CANONICAL_CLINICAL_WARNING,
    CANONICAL_CLINICAL_WARNING_EN,
    CANONICAL_CLINICAL_WARNING_TR,
    CLAIM_BOUNDARY_STATUS,
    DEFAULT_CLAIM_BOUNDARY,
    P0_CLAIM_BOUNDARY,
    ClaimBoundary,
    ClaimPhase,
    ClaimScanResult,
    ModeNotEnabledError,
    OperationMode,
    ProhibitedClaimCategory,
    ProhibitedClaimError,
    SafeContextKind,
    assert_claim_text_allowed,
    canonical_clinical_warning,
    claim_patterns,
    is_mode_enabled,
    prohibited_claim_statements,
    require_mode_enabled,
    scan_claim_text,
)


# ---------------------------------------------------------------------------
# Helper: read legacy warning constants without importing legacy modules.
# ---------------------------------------------------------------------------

def _legacy_string_constants(filename, names):
    """Return {name: value} for module-level string constants in a legacy file.

    Uses ``ast`` so the legacy scripts are never executed and never
    modified. WP-00 must not touch legacy behaviour.
    """
    path = os.path.join(_REPO_ROOT, filename)
    if not os.path.exists(path):
        return {}
    with io.open(path, encoding="utf-8") as handle:
        tree = ast.parse(handle.read(), filename=path)
    found = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in names:
                try:
                    value = ast.literal_eval(node.value)
                except (ValueError, SyntaxError):  # pragma: no cover
                    continue
                if isinstance(value, str):
                    found[target.id] = value
    return found


#: Legacy user-facing safety/warning constants, per module. These must all
#: pass the canonical scanner: the migration replaces them with one
#: canonical text, but it must not begin by declaring the existing
#: warnings unsafe.
LEGACY_WARNING_SOURCES = {
    "risk_engine.py": ("CLINICAL_WARNING_TR",),
    "gemini_report_generator.py": ("CLINICAL_WARNING_TR",),
    "candidate_onboarding.py": (
        "SAFETY_NOTICE",
        "CHEMICAL_RESOLVE_NOTICE",
        "NO_RULE_NOTICE",
    ),
    "alternative_ranker.py": (
        "SAFETY_NOTICE",
        "DATA_LIMIT_NOTICE",
        "INSUFFICIENT_PGX_RULE_NOTICE",
        "UNSUPPORTED_CANDIDATE_NOTICE",
    ),
}


# ---------------------------------------------------------------------------
# Operation modes
# ---------------------------------------------------------------------------


class TestOperationMode(unittest.TestCase):
    """Mode enum shape (architecture.md 2.3)."""

    def test_exactly_three_modes_exist(self):
        self.assertEqual(
            [m.value for m in OperationMode],
            ["DEMO", "VALIDATION", "PILOT"],
        )

    def test_modes_are_string_valued_for_transport(self):
        self.assertEqual(OperationMode.DEMO.value, "DEMO")
        self.assertEqual(OperationMode("VALIDATION"), OperationMode.VALIDATION)
        self.assertIsInstance(OperationMode.PILOT.value, str)

    def test_unknown_mode_is_rejected(self):
        with self.assertRaises(ValueError):
            OperationMode("PRODUCTION")


class TestP0ModeAvailability(unittest.TestCase):
    """P0 enables DEMO and VALIDATION only; PILOT stays closed."""

    def test_demo_mode_is_enabled(self):
        self.assertTrue(is_mode_enabled(OperationMode.DEMO))

    def test_validation_mode_is_enabled(self):
        self.assertTrue(is_mode_enabled(OperationMode.VALIDATION))

    def test_pilot_mode_is_disabled_in_p0(self):
        self.assertFalse(is_mode_enabled(OperationMode.PILOT))
        self.assertNotIn(OperationMode.PILOT, P0_CLAIM_BOUNDARY.enabled_modes)
        self.assertIn(OperationMode.PILOT, P0_CLAIM_BOUNDARY.disabled_modes)

    def test_require_mode_enabled_raises_for_pilot(self):
        with self.assertRaises(ModeNotEnabledError) as ctx:
            require_mode_enabled(OperationMode.PILOT)
        message = str(ctx.exception)
        self.assertIn("PILOT", message)
        self.assertIn("P0", message)

    def test_require_mode_enabled_passes_for_demo_and_validation(self):
        require_mode_enabled(OperationMode.DEMO)
        require_mode_enabled(OperationMode.VALIDATION)

    def test_mode_check_rejects_non_enum_input(self):
        with self.assertRaises(TypeError):
            is_mode_enabled("PILOT")

    def test_default_boundary_is_the_p0_boundary(self):
        self.assertIs(DEFAULT_CLAIM_BOUNDARY, P0_CLAIM_BOUNDARY)
        self.assertIs(P0_CLAIM_BOUNDARY.phase, ClaimPhase.P0)


class TestClaimBoundaryModel(unittest.TestCase):
    """The boundary object is immutable and unapproved at WP-00."""

    def test_boundary_is_immutable(self):
        with self.assertRaises(Exception):
            P0_CLAIM_BOUNDARY.phase = ClaimPhase.P2  # type: ignore[misc]

    def test_all_prohibited_categories_apply_in_p0(self):
        for category in ProhibitedClaimCategory:
            self.assertTrue(
                P0_CLAIM_BOUNDARY.is_category_prohibited(category),
                "category %s must be prohibited in P0" % category.value,
            )

    def test_boundary_reports_draft_status_and_is_not_approved(self):
        self.assertEqual(
            CLAIM_BOUNDARY_STATUS,
            "DRAFT / AWAITING HUMAN AND SCIENTIFIC REVIEW",
        )
        self.assertFalse(P0_CLAIM_BOUNDARY.is_approved)

    def test_a_custom_boundary_can_narrow_categories(self):
        narrowed = ClaimBoundary(
            phase=ClaimPhase.P0,
            enabled_modes=frozenset({OperationMode.DEMO}),
            prohibited_categories=frozenset({ProhibitedClaimCategory.DOSING}),
        )
        self.assertTrue(narrowed.is_category_prohibited(ProhibitedClaimCategory.DOSING))
        self.assertFalse(
            narrowed.is_category_prohibited(ProhibitedClaimCategory.DIAGNOSIS)
        )
        self.assertFalse(narrowed.is_mode_enabled(OperationMode.VALIDATION))


# ---------------------------------------------------------------------------
# Canonical warning
# ---------------------------------------------------------------------------


class TestCanonicalWarning(unittest.TestCase):
    """There is exactly one canonical warning text, and it is scanner-clean."""

    def test_canonical_warning_available_in_tr_and_en(self):
        self.assertEqual(sorted(CANONICAL_CLINICAL_WARNING), ["en", "tr"])
        self.assertIs(canonical_clinical_warning("tr"), CANONICAL_CLINICAL_WARNING_TR)
        self.assertIs(canonical_clinical_warning("EN"), CANONICAL_CLINICAL_WARNING_EN)

    def test_unsupported_language_is_rejected(self):
        with self.assertRaises(ValueError):
            canonical_clinical_warning("de")

    def test_canonical_tr_warning_states_the_core_exclusions(self):
        text = CANONICAL_CLINICAL_WARNING_TR.lower()
        for fragment in ("klinik karar", "doz", "tedavi", "eksik veri", "hekim"):
            self.assertIn(fragment, text)

    def test_canonical_en_warning_states_the_core_exclusions(self):
        text = CANONICAL_CLINICAL_WARNING_EN.lower()
        for fragment in ("clinical decision", "dose", "treatment", "missing data",
                         "physician"):
            self.assertIn(fragment, text)

    def test_canonical_tr_warning_passes_the_scanner(self):
        result = scan_claim_text(CANONICAL_CLINICAL_WARNING_TR)
        self.assertTrue(result.is_clean, result.as_dict())

    def test_canonical_en_warning_passes_the_scanner(self):
        result = scan_claim_text(CANONICAL_CLINICAL_WARNING_EN)
        self.assertTrue(result.is_clean, result.as_dict())

    def test_canonical_warning_is_suppressed_not_merely_unmatched(self):
        """The warning is clean because it negates, not because it is bland."""
        result = scan_claim_text(CANONICAL_CLINICAL_WARNING_TR)
        self.assertTrue(result.suppressed)
        self.assertTrue(
            all(s.safe_context is SafeContextKind.NEGATION for s in result.suppressed),
            [s.as_dict() for s in result.suppressed],
        )

    def test_boundary_exposes_the_same_canonical_text(self):
        self.assertEqual(P0_CLAIM_BOUNDARY.warning("tr"), CANONICAL_CLINICAL_WARNING_TR)
        self.assertEqual(P0_CLAIM_BOUNDARY.warning("en"), CANONICAL_CLINICAL_WARNING_EN)


class TestProhibitedClaimStatements(unittest.TestCase):
    """Every prohibited category has a canonical DOES NOT statement."""

    def test_every_category_has_a_statement_in_both_languages(self):
        for language in ("tr", "en"):
            statements = prohibited_claim_statements(language)
            for category in ProhibitedClaimCategory:
                self.assertIn(category, statements)
                self.assertTrue(statements[category].strip())

    def test_statements_themselves_pass_the_scanner(self):
        for language in ("tr", "en"):
            for category, statement in prohibited_claim_statements(language).items():
                result = scan_claim_text(statement)
                self.assertTrue(
                    result.is_clean,
                    "%s/%s should be scanner-clean: %s"
                    % (language, category.value, result.as_dict()),
                )


# ---------------------------------------------------------------------------
# Prohibited claim detection
# ---------------------------------------------------------------------------


class TestProhibitedClaimsTurkish(unittest.TestCase):
    """Turkish recommendation / assurance phrasing must be caught."""

    def _assert_violates(self, text, category):
        result = scan_claim_text(text)
        self.assertTrue(result.has_violations, "expected a violation for %r" % text)
        self.assertIn(category, result.categories, result.as_dict())
        return result

    def test_direct_medication_instruction(self):
        self._assert_violates(
            "Bu ilacı kullanın.", ProhibitedClaimCategory.MEDICATION_CHANGE
        )

    def test_treatment_substitution(self):
        self._assert_violates(
            "Clopidogrel yerine ticagrelor kullanılmalıdır.",
            ProhibitedClaimCategory.TREATMENT_SELECTION,
        )

    def test_dose_reduction_instruction(self):
        self._assert_violates("Dozu %50 azaltın.", ProhibitedClaimCategory.DOSING)

    def test_safety_declaration(self):
        self._assert_violates(
            "Bu ilaç güvenlidir.", ProhibitedClaimCategory.SAFETY_ASSURANCE
        )

    def test_candidate_preference(self):
        self._assert_violates(
            "Ticagrelor bu hasta için daha güvenli bir seçenektir.",
            ProhibitedClaimCategory.CANDIDATE_PREFERENCE,
        )

    def test_dose_recommendation_noun(self):
        self._assert_violates(
            "Aşağıda hekim için doz önerisi sunulmuştur.",
            ProhibitedClaimCategory.DOSING,
        )

    def test_stop_medication_instruction(self):
        self._assert_violates(
            "Tedaviyi bırakın ve başka bir ilaca geçin.",
            ProhibitedClaimCategory.MEDICATION_CHANGE,
        )

    def test_false_reassurance(self):
        self._assert_violates(
            "Kural bulunamadı, bu nedenle bu ilaç düşük risklidir.",
            ProhibitedClaimCategory.FALSE_REASSURANCE,
        )

    def test_validation_overclaim(self):
        self._assert_violates(
            "Bu sistem klinik kullanıma uygundur.",
            ProhibitedClaimCategory.VALIDATION_OVERCLAIM,
        )

    def test_ascii_spelling_without_diacritics_is_also_caught(self):
        """Legacy code mixes 'degildir' and 'değildir'; folding must handle both."""
        self._assert_violates("Bu ilac guvenlidir.", ProhibitedClaimCategory.SAFETY_ASSURANCE)


class TestProhibitedClaimsEnglish(unittest.TestCase):
    """English recommendation / assurance phrasing must be caught."""

    def _assert_violates(self, text, category):
        result = scan_claim_text(text)
        self.assertTrue(result.has_violations, "expected a violation for %r" % text)
        self.assertIn(category, result.categories, result.as_dict())
        return result

    def test_candidate_is_safer(self):
        self._assert_violates(
            "This candidate is safer.", ProhibitedClaimCategory.CANDIDATE_PREFERENCE
        )

    def test_dose_reduction(self):
        self._assert_violates(
            "Reduce the dose by half.", ProhibitedClaimCategory.DOSING
        )

    def test_treatment_substitution(self):
        self._assert_violates(
            "Use ticagrelor instead of clopidogrel.",
            ProhibitedClaimCategory.TREATMENT_SELECTION,
        )

    def test_safety_declaration(self):
        self._assert_violates(
            "This combination is completely safe.",
            ProhibitedClaimCategory.SAFETY_ASSURANCE,
        )

    def test_stop_medication(self):
        self._assert_violates(
            "Stop the medication immediately.",
            ProhibitedClaimCategory.MEDICATION_CHANGE,
        )

    def test_regulatory_overclaim(self):
        self._assert_violates(
            "This product is FDA approved for clinical use.",
            ProhibitedClaimCategory.VALIDATION_OVERCLAIM,
        )

    def test_real_patient_data_claim(self):
        self._assert_violates(
            "We analysed your VCF and the patient's genome.",
            ProhibitedClaimCategory.REAL_PATIENT_DATA,
        )


class TestNegationAndDeferralAreSafe(unittest.TestCase):
    """Safe warnings that mention the forbidden concept must not be flagged."""

    SAFE_SENTENCES = (
        "Bu çıktı klinik karar veya doz önerisi değildir.",
        "This system does not recommend a dose.",
        "Bu rapor tedavi önerisi değildir.",
        "Bu sonuç bir teşhis değildir ve tanı koymaz.",
        "Sistem hiçbir ilacı güvenli ilan etmez.",
        "Eksik veri düşük risk anlamına gelmez.",
        "Bu aday için düşük riskli olduğu sonucuna varılamaz.",
        "Doz, ilaç değişimi ve tedavi kararı yalnızca yetkili hekim tarafından verilir.",
        "The dose must not be changed on the basis of this report.",
        "This output does not declare any drug safe.",
        "Dose changes are decided only by a qualified physician.",
        "Missing evidence does not mean low risk.",
    )

    def test_negated_and_deferred_sentences_are_clean(self):
        for sentence in self.SAFE_SENTENCES:
            with self.subTest(sentence=sentence):
                result = scan_claim_text(sentence)
                self.assertTrue(result.is_clean, result.as_dict())

    def test_suppression_reason_is_recorded(self):
        result = scan_claim_text("Bu çıktı klinik karar veya doz önerisi değildir.")
        self.assertTrue(result.suppressed)
        self.assertEqual(result.suppressed[0].safe_context, SafeContextKind.NEGATION)
        self.assertIn("degil", result.suppressed[0].safe_context_text)

    def test_clinician_deferral_is_recorded_as_such(self):
        result = scan_claim_text(
            "Doz önerisi yalnızca yetkili hekim tarafından verilir."
        )
        self.assertTrue(result.is_clean, result.as_dict())
        self.assertTrue(
            any(
                s.safe_context is SafeContextKind.CLINICIAN_DEFERRAL
                for s in result.suppressed
            ),
            [s.as_dict() for s in result.suppressed],
        )

    def test_a_disclaimer_cannot_launder_a_direct_imperative(self):
        """Imperatives are non-negatable: a trailing disclaimer must not help."""
        result = scan_claim_text("Bu ilacı kullanın; bu bir öneri değildir.")
        self.assertTrue(result.has_violations, result.as_dict())
        self.assertIn(
            ProhibitedClaimCategory.MEDICATION_CHANGE, result.categories
        )


class TestNoFalsePositives(unittest.TestCase):
    """Neutral, evidence-style text must scan clean."""

    NEUTRAL_TEXTS = (
        "",
        "   ",
        "\n\n",
        "CYP2C19 POOR fenotipi için klopidogrel ekseninde YÜKSEK dikkat bulgusu "
        "hesaplanmıştır. Bulgu, ruleset PGX-RULESET-0001 içindeki kural 42 ve "
        "kanıt kaydı EV-118 ile ilişkilendirilmiştir.",
        "Kapsam durumu PARTIAL olarak raporlanmıştır; nedeni "
        "SOME_AXES_NOT_COVERED reason koduyla kayıt altına alınmıştır.",
        "Genel dikkat düzeyi: düşük dikkat. Kapsam: FULL. Sürüm: PGX-REL-0007.",
        "The coverage status is INSUFFICIENT because no validated rule exists "
        "for this drug-gene axis in the active ruleset.",
        "Attention level HIGH was calculated for the CYP2C19 axis; the finding "
        "cites evidence records EV-118 and EV-231.",
        "Bu bölümde kullanılan veri seti, kural kümesi ve yazılım sürümleri "
        "rapor başlığında listelenmiştir.",
        "Kaynak özetinde doz ile ilgili bir ifade yer alır; bu ifade aktarılmamıştır.",
    )

    def test_neutral_text_produces_no_violations(self):
        for text in self.NEUTRAL_TEXTS:
            with self.subTest(text=text[:60]):
                result = scan_claim_text(text)
                self.assertTrue(result.is_clean, result.as_dict())

    def test_none_is_handled(self):
        result = scan_claim_text(None)
        self.assertTrue(result.is_clean)
        self.assertEqual(result.text_length, 0)

    def test_non_string_input_is_rejected(self):
        with self.assertRaises(TypeError):
            scan_claim_text(42)

    def test_low_attention_label_is_not_a_false_positive(self):
        """'düşük dikkat' is a legitimate attention level rendering."""
        result = scan_claim_text("Hesaplanan dikkat düzeyi: düşük dikkat.")
        self.assertTrue(result.is_clean, result.as_dict())


class TestStructuredResult(unittest.TestCase):
    """The scanner returns structured findings, not a bare boolean."""

    MULTI_VIOLATION_TEXT = (
        "Bu ilaç güvenlidir. "
        "Dozu %50 azaltın. "
        "Clopidogrel yerine ticagrelor kullanılmalıdır. "
        "This candidate is safer."
    )

    def test_result_type_and_metadata(self):
        result = scan_claim_text("Bu ilaç güvenlidir.")
        self.assertIsInstance(result, ClaimScanResult)
        self.assertEqual(result.text_length, len("Bu ilaç güvenlidir."))
        self.assertTrue(result.scanner_version)
        self.assertEqual(result.boundary_version, P0_CLAIM_BOUNDARY.version)

    def test_multiple_violations_are_returned_separately(self):
        result = scan_claim_text(self.MULTI_VIOLATION_TEXT)
        self.assertTrue(result.has_violations)
        self.assertFalse(result.is_clean)
        self.assertGreaterEqual(len(result.violations), 4)
        for category in (
            ProhibitedClaimCategory.SAFETY_ASSURANCE,
            ProhibitedClaimCategory.DOSING,
            ProhibitedClaimCategory.TREATMENT_SELECTION,
            ProhibitedClaimCategory.CANDIDATE_PREFERENCE,
        ):
            self.assertIn(category, result.categories, result.as_dict())

    def test_each_violation_carries_actionable_detail(self):
        result = scan_claim_text(self.MULTI_VIOLATION_TEXT)
        for violation in result.violations:
            self.assertTrue(violation.rule_id)
            self.assertIsInstance(violation.category, ProhibitedClaimCategory)
            self.assertTrue(violation.matched_text)
            self.assertTrue(violation.sentence)
            self.assertEqual(violation.severity.value, "BLOCKING")

    def test_offsets_point_at_the_original_text(self):
        result = scan_claim_text(self.MULTI_VIOLATION_TEXT)
        for violation in result.violations:
            self.assertEqual(
                self.MULTI_VIOLATION_TEXT[violation.start:violation.end],
                violation.matched_text,
            )

    def test_violations_are_ordered_deterministically(self):
        first = scan_claim_text(self.MULTI_VIOLATION_TEXT)
        second = scan_claim_text(self.MULTI_VIOLATION_TEXT)
        self.assertEqual(
            [v.as_dict() for v in first.violations],
            [v.as_dict() for v in second.violations],
        )
        starts = [v.start for v in first.violations]
        self.assertEqual(starts, sorted(starts))

    def test_result_is_json_serialisable(self):
        import json

        result = scan_claim_text(self.MULTI_VIOLATION_TEXT)
        payload = json.dumps(result.as_dict(), ensure_ascii=False)
        self.assertIn("SAFETY_ASSURANCE", payload)

    def test_violations_for_category_filter(self):
        result = scan_claim_text(self.MULTI_VIOLATION_TEXT)
        subset = result.violations_for(ProhibitedClaimCategory.SAFETY_ASSURANCE)
        self.assertTrue(subset)
        for violation in subset:
            self.assertIs(violation.category, ProhibitedClaimCategory.SAFETY_ASSURANCE)

    def test_rule_ids_are_unique_and_registered(self):
        registered = {pattern.rule_id for pattern in claim_patterns()}
        self.assertEqual(len(registered), len(claim_patterns()))
        result = scan_claim_text(self.MULTI_VIOLATION_TEXT)
        for rule_id in result.rule_ids:
            self.assertIn(rule_id, registered)

    def test_assert_helper_raises_and_carries_the_result(self):
        with self.assertRaises(ProhibitedClaimError) as ctx:
            assert_claim_text_allowed(self.MULTI_VIOLATION_TEXT)
        self.assertTrue(ctx.exception.result.has_violations)
        self.assertIn("SAFETY-INV-010", str(ctx.exception))

    def test_assert_helper_returns_result_when_clean(self):
        result = assert_claim_text_allowed(CANONICAL_CLINICAL_WARNING_TR)
        self.assertTrue(result.is_clean)

    def test_language_restriction_is_honoured(self):
        english_only = scan_claim_text("Bu ilaç güvenlidir.", languages=("en",))
        self.assertTrue(english_only.is_clean)
        turkish = scan_claim_text("Bu ilaç güvenlidir.", languages=("tr",))
        self.assertTrue(turkish.has_violations)

    def test_pattern_registry_covers_every_category(self):
        covered = {pattern.category for pattern in claim_patterns()}
        for category in ProhibitedClaimCategory:
            self.assertIn(category, covered, "no pattern defends %s" % category.value)


# ---------------------------------------------------------------------------
# Legacy migration guard
# ---------------------------------------------------------------------------


class TestLegacyWarningsPassTheScanner(unittest.TestCase):
    """Existing legacy safety notices must survive the canonical scanner.

    WP-00 replaces the divergent legacy strings with one canonical text in a
    later work package. It must not start by declaring the current warnings
    unsafe, and the scanner must not regress into flagging correct
    negated disclaimers.
    """

    def test_every_known_legacy_warning_is_clean(self):
        checked = 0
        for filename, names in LEGACY_WARNING_SOURCES.items():
            constants = _legacy_string_constants(filename, names)
            if not constants:
                self.skipTest("legacy file %s not available" % filename)
            for name, value in sorted(constants.items()):
                with self.subTest(source="%s::%s" % (filename, name)):
                    result = scan_claim_text(value)
                    self.assertTrue(result.is_clean, result.as_dict())
                    checked += 1
        self.assertGreaterEqual(checked, 8, "expected at least 8 legacy warnings")

    def test_legacy_files_declare_the_expected_warning_constants(self):
        """Guards the WP-00 legacy inventory against silent drift."""
        for filename, names in LEGACY_WARNING_SOURCES.items():
            path = os.path.join(_REPO_ROOT, filename)
            if not os.path.exists(path):
                self.skipTest("legacy file %s not available" % filename)
            constants = _legacy_string_constants(filename, names)
            for name in names:
                self.assertIn(
                    name, constants, "%s no longer defines %s" % (filename, name)
                )

    def test_legacy_warnings_are_not_identical_across_modules(self):
        """Records the divergence that motivates one canonical text."""
        risk = _legacy_string_constants("risk_engine.py", ("CLINICAL_WARNING_TR",))
        candidate = _legacy_string_constants(
            "candidate_onboarding.py", ("SAFETY_NOTICE",)
        )
        ranker = _legacy_string_constants("alternative_ranker.py", ("SAFETY_NOTICE",))
        if not (risk and candidate and ranker):
            self.skipTest("legacy files not available")
        variants = {
            risk["CLINICAL_WARNING_TR"],
            candidate["SAFETY_NOTICE"],
            ranker["SAFETY_NOTICE"],
        }
        self.assertGreater(
            len(variants), 1,
            "legacy warnings are expected to diverge; the canonical text replaces them",
        )

    def test_canonical_text_is_not_yet_used_by_legacy_modules(self):
        """WP-00 documents the target; it does not edit legacy files."""
        risk = _legacy_string_constants("risk_engine.py", ("CLINICAL_WARNING_TR",))
        if not risk:
            self.skipTest("legacy file not available")
        self.assertNotEqual(risk["CLINICAL_WARNING_TR"], CANONICAL_CLINICAL_WARNING_TR)


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
