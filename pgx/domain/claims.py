# -*- coding: utf-8 -*-
"""Central claims boundary and prohibited-claim contract (WP-00).

This module is the single machine-readable source of truth for:

* which operation modes exist and which of them are enabled in P0;
* the one canonical prototype/clinical warning text;
* the categories of claims the product must never make;
* a deterministic, defense-in-depth claim-text scanner that API, UI, and
  reporting layers can call before releasing user-facing text.

Governing documents:

* ``docs/architecture/intended-purpose.md``
* ``docs/risk-management/safety-contract.md``
* ``architecture.md`` sections 2.1, 2.2, 2.3, 3, 10.2, 12.4

Design constraints (WP-00):

* Standard library only. No pydantic, no settings framework, no I/O.
* Deterministic: the same input always yields the same structured result.
* Immutable: boundary objects and results are frozen dataclasses.

SCOPE WARNING - READ BEFORE RELYING ON :func:`scan_claim_text`
--------------------------------------------------------------
The scanner is a **lexical, pattern-based defense layer**. It is not a
natural-language-understanding system, not a semantic classifier, and not
a scientific or regulatory validation of text. It exists to catch obvious
recommendation, dosing, and reassurance phrasing that escaped a safe
template. It can produce false negatives on paraphrase and false
positives on unusual phrasing. Safe templates and human review remain the
primary control; ``SAFETY-INV-010`` is enforced by this scanner only as a
last line of defense.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

__all__ = [
    "CANONICAL_CLINICAL_WARNING",
    "CANONICAL_CLINICAL_WARNING_EN",
    "CANONICAL_CLINICAL_WARNING_TR",
    "CLAIM_BOUNDARY_STATUS",
    "CLAIM_BOUNDARY_VERSION",
    "CLAIM_SCANNER_VERSION",
    "DEFAULT_CLAIM_BOUNDARY",
    "P0_CLAIM_BOUNDARY",
    "P0_ENABLED_MODES",
    "PILOT_DISABLED_REASON",
    "PROHIBITED_CLAIM_STATEMENTS_EN",
    "PROHIBITED_CLAIM_STATEMENTS_TR",
    "SUPPORTED_LANGUAGES",
    "ClaimBoundary",
    "ClaimBoundaryError",
    "ClaimPattern",
    "ClaimPhase",
    "ClaimScanResult",
    "ClaimViolation",
    "ModeNotEnabledError",
    "OperationMode",
    "PermittedInputKind",
    "ProhibitedClaimCategory",
    "ProhibitedClaimError",
    "SafeContextKind",
    "SuppressedMatch",
    "ViolationSeverity",
    "assert_claim_text_allowed",
    "canonical_clinical_warning",
    "claim_patterns",
    "is_mode_enabled",
    "prohibited_claim_statements",
    "require_mode_enabled",
    "scan_claim_text",
]


# ---------------------------------------------------------------------------
# Document identity
# ---------------------------------------------------------------------------

#: Version of the claim boundary contract expressed by this module.
CLAIM_BOUNDARY_VERSION = "0.1.0-draft"

#: Approval status. This module must not report an approved status until a
#: named human owner and a named scientific advisor have signed the review
#: table in ``docs/architecture/intended-purpose.md``. An AI coding agent
#: must never change this value.
CLAIM_BOUNDARY_STATUS = "DRAFT / AWAITING HUMAN AND SCIENTIFIC REVIEW"

#: Version of the lexical scanner rule set (bump when patterns change).
CLAIM_SCANNER_VERSION = "claim-scanner/0.1.0"

SUPPORTED_LANGUAGES: Tuple[str, ...] = ("tr", "en")


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ClaimPhase(str, Enum):
    """Programme phase that a claim boundary belongs to."""

    P0 = "P0"
    P1 = "P1"
    P2 = "P2"


class OperationMode(str, Enum):
    """Operating modes defined by ``architecture.md`` section 2.3."""

    #: Synthetic cases and public demo profiles; jury demonstration/training.
    DEMO = "DEMO"
    #: Versioned development, internal holdout, or expert holdout cases.
    VALIDATION = "VALIDATION"
    #: Future protocol-defined pilot. Disabled in P0; requires a P2 gate.
    PILOT = "PILOT"


class PermittedInputKind(str, Enum):
    """Input data kinds that P0 may accept."""

    SYNTHETIC_PHENOTYPE_PROFILE = "SYNTHETIC_PHENOTYPE_PROFILE"
    PROTOCOL_DEFINED_PHENOTYPE_PROFILE = "PROTOCOL_DEFINED_PHENOTYPE_PROFILE"
    PUBLIC_DEMO_PROFILE = "PUBLIC_DEMO_PROFILE"
    VERSIONED_VALIDATION_CASE = "VERSIONED_VALIDATION_CASE"
    MEDICATION_NAME_LIST = "MEDICATION_NAME_LIST"


class ProhibitedClaimCategory(str, Enum):
    """Categories of claims the system must never make.

    One-to-one with the prohibited list in ``architecture.md`` section 2.2
    and the ``DOES NOT`` list in ``docs/architecture/intended-purpose.md``.
    """

    DIAGNOSIS = "DIAGNOSIS"
    PRESCRIPTION = "PRESCRIPTION"
    DOSING = "DOSING"
    MEDICATION_CHANGE = "MEDICATION_CHANGE"
    TREATMENT_SELECTION = "TREATMENT_SELECTION"
    SAFETY_ASSURANCE = "SAFETY_ASSURANCE"
    CANDIDATE_PREFERENCE = "CANDIDATE_PREFERENCE"
    FALSE_REASSURANCE = "FALSE_REASSURANCE"
    REAL_PATIENT_DATA = "REAL_PATIENT_DATA"
    CLINICAL_DECISION_SUBSTITUTION = "CLINICAL_DECISION_SUBSTITUTION"
    VALIDATION_OVERCLAIM = "VALIDATION_OVERCLAIM"


class SafeContextKind(str, Enum):
    """Why a lexical match was not treated as a violation."""

    #: Sentence negates the claim ("... degildir", "does not ...").
    NEGATION = "NEGATION"
    #: Sentence forbids the claim (instruction lists, "avoid", "... verme").
    PROHIBITION = "PROHIBITION"
    #: Sentence defers the decision to a qualified clinician.
    CLINICIAN_DEFERRAL = "CLINICIAN_DEFERRAL"


class ViolationSeverity(str, Enum):
    """Severity of a detected claim violation."""

    #: Blocks report/response release (``SAFETY-INV-010``).
    BLOCKING = "BLOCKING"


# ---------------------------------------------------------------------------
# Canonical warning text (single source of truth)
# ---------------------------------------------------------------------------

CANONICAL_CLINICAL_WARNING_TR = (
    "Bu çıktı klinik karar, tanı, doz önerisi veya tedavi önerisi değildir. "
    "PGx Platform V2, araştırma/prototip amaçlı bir karar destek göstericisidir; "
    "sentetik veya protokolle tanımlanmış fenotip profillerini sürümlenmiş ve "
    "uzman yönetimli bir farmakogenetik kural kümesiyle karşılaştırarak "
    "izlenebilir dikkat bulguları ve bunlardan ayrı bir kapsam değerlendirmesi üretir. "
    "Eksik veri düşük risk anlamına gelmez. "
    "Doz, ilaç değişimi ve tedavi kararı yalnızca yetkili hekim tarafından; "
    "klinik tablo, endikasyon, laboratuvar sonuçları ve güncel kılavuzlar "
    "dikkate alınarak verilir."
)

CANONICAL_CLINICAL_WARNING_EN = (
    "This output is not a clinical decision, a diagnosis, a dose recommendation, "
    "or a treatment recommendation. "
    "PGx Platform V2 is a research/prototype decision-support demonstrator: it "
    "compares synthetic or protocol-defined phenotype profiles against a "
    "versioned, expert-governed pharmacogenetic ruleset and produces traceable "
    "attention findings plus a separate coverage assessment. "
    "Missing data does not mean low risk. "
    "Dose, medication change, and treatment decisions are made only by a "
    "qualified physician, considering the clinical picture, indication, "
    "laboratory results, and current guidelines."
)

#: Canonical warning by language code. Every user-facing surface must render
#: one of these strings; layers must not author their own variants.
CANONICAL_CLINICAL_WARNING: Mapping[str, str] = {
    "tr": CANONICAL_CLINICAL_WARNING_TR,
    "en": CANONICAL_CLINICAL_WARNING_EN,
}

PILOT_DISABLED_REASON = (
    "PILOT is disabled in P0. Enabling it requires a formally expanded intended "
    "purpose plus privacy, ethics, consent, security, and validation claims, "
    "recorded as an Architecture Decision Record and a P2 gate "
    "(architecture.md sections 2.3 and 19)."
)

PROHIBITED_CLAIM_STATEMENTS_EN: Mapping[ProhibitedClaimCategory, str] = {
    ProhibitedClaimCategory.DIAGNOSIS: "The system does not diagnose any condition.",
    ProhibitedClaimCategory.PRESCRIPTION: "The system does not prescribe any medication.",
    ProhibitedClaimCategory.DOSING: "The system does not calculate, suggest, or adjust a dose.",
    ProhibitedClaimCategory.MEDICATION_CHANGE: (
        "The system does not tell anyone to start, stop, replace, or change a medication."
    ),
    ProhibitedClaimCategory.TREATMENT_SELECTION: "The system does not select a treatment.",
    ProhibitedClaimCategory.SAFETY_ASSURANCE: (
        "The system does not declare any drug, phenotype, combination, or candidate safe."
    ),
    ProhibitedClaimCategory.CANDIDATE_PREFERENCE: (
        "The system does not describe a candidate as safer, preferred, suitable, or "
        "clinically equivalent."
    ),
    ProhibitedClaimCategory.FALSE_REASSURANCE: (
        "The system does not treat missing data or missing evidence as low or no risk."
    ),
    ProhibitedClaimCategory.REAL_PATIENT_DATA: (
        "The system does not process real VCF, EHR, genotype, diplotype, or laboratory "
        "data, and does not infer a real patient's phenotype, in P0."
    ),
    ProhibitedClaimCategory.CLINICAL_DECISION_SUBSTITUTION: (
        "The system does not replace or act as a clinical decision-maker."
    ),
    ProhibitedClaimCategory.VALIDATION_OVERCLAIM: (
        "The system does not present demo or development cases as independent clinical "
        "validation, approval, or certification."
    ),
}

PROHIBITED_CLAIM_STATEMENTS_TR: Mapping[ProhibitedClaimCategory, str] = {
    ProhibitedClaimCategory.DIAGNOSIS: "Sistem hiçbir hastalığı teşhis etmez.",
    ProhibitedClaimCategory.PRESCRIPTION: "Sistem ilaç reçete etmez.",
    ProhibitedClaimCategory.DOSING: "Sistem doz hesaplamaz, önermez ve ayarlamaz.",
    ProhibitedClaimCategory.MEDICATION_CHANGE: (
        "Sistem ilaç başlatma, bırakma, değiştirme veya kesme talimatı vermez."
    ),
    ProhibitedClaimCategory.TREATMENT_SELECTION: "Sistem tedavi seçmez.",
    ProhibitedClaimCategory.SAFETY_ASSURANCE: (
        "Sistem hiçbir ilacı, fenotipi, kombinasyonu veya adayı güvenli ilan etmez."
    ),
    ProhibitedClaimCategory.CANDIDATE_PREFERENCE: (
        "Sistem bir adayı daha güvenli, tercih edilir, uygun veya klinik olarak "
        "eşdeğer olarak nitelemez."
    ),
    ProhibitedClaimCategory.FALSE_REASSURANCE: (
        "Sistem eksik veriyi veya eksik kanıtı düşük/sıfır risk olarak yorumlamaz."
    ),
    ProhibitedClaimCategory.REAL_PATIENT_DATA: (
        "Sistem P0'da gerçek VCF, EHR, genotip, diplotip veya laboratuvar verisi "
        "işlemez ve gerçek hasta fenotipi çıkarımı yapmaz."
    ),
    ProhibitedClaimCategory.CLINICAL_DECISION_SUBSTITUTION: (
        "Sistem klinik karar vericinin yerine geçmez."
    ),
    ProhibitedClaimCategory.VALIDATION_OVERCLAIM: (
        "Sistem demo/geliştirme vakalarını bağımsız klinik validasyon, onay veya "
        "sertifikasyon olarak sunmaz."
    ),
}


def canonical_clinical_warning(language: str = "tr") -> str:
    """Return the one canonical warning text for ``language``.

    Layers must call this instead of embedding their own warning string.

    Raises:
        ValueError: if ``language`` is not a supported language code.
    """
    key = (language or "").strip().lower()
    if key not in CANONICAL_CLINICAL_WARNING:
        raise ValueError(
            "Unsupported warning language %r; supported: %s"
            % (language, ", ".join(sorted(CANONICAL_CLINICAL_WARNING)))
        )
    return CANONICAL_CLINICAL_WARNING[key]


def prohibited_claim_statements(language: str = "en") -> Mapping[ProhibitedClaimCategory, str]:
    """Return the canonical ``DOES NOT`` statement per prohibited category."""
    key = (language or "").strip().lower()
    if key == "tr":
        return PROHIBITED_CLAIM_STATEMENTS_TR
    if key == "en":
        return PROHIBITED_CLAIM_STATEMENTS_EN
    raise ValueError(
        "Unsupported statement language %r; supported: en, tr" % (language,)
    )


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ClaimBoundaryError(Exception):
    """Base error for claim boundary violations."""


class ModeNotEnabledError(ClaimBoundaryError):
    """Raised when a disabled operation mode is requested."""

    def __init__(self, mode: OperationMode, boundary: "ClaimBoundary") -> None:
        self.mode = mode
        self.boundary = boundary
        reason = PILOT_DISABLED_REASON if mode is OperationMode.PILOT else (
            "Mode is not enabled by the active claim boundary."
        )
        super().__init__(
            "Operation mode %s is not enabled in %s. %s"
            % (mode.value, boundary.phase.value, reason)
        )


class ProhibitedClaimError(ClaimBoundaryError):
    """Raised when text carrying prohibited claim language would be released."""

    def __init__(self, result: "ClaimScanResult") -> None:
        self.result = result
        categories = ", ".join(c.value for c in result.categories)
        super().__init__(
            "Prohibited claim language detected (%d violation(s): %s). "
            "Report release is blocked by SAFETY-INV-010."
            % (len(result.violations), categories)
        )


# ---------------------------------------------------------------------------
# Claim boundary model
# ---------------------------------------------------------------------------

#: Modes enabled in P0. PILOT is intentionally absent (architecture.md 2.3).
P0_ENABLED_MODES = frozenset({OperationMode.DEMO, OperationMode.VALIDATION})


@dataclass(frozen=True)
class ClaimBoundary:
    """Immutable declaration of what the product may and may not claim.

    A boundary object is the value that API, UI, reporting, validation, and
    LLM layers read. It is never mutated at runtime; a different phase means
    a different ``ClaimBoundary`` instance created under an Architecture
    Decision Record (``architecture.md`` section 23).
    """

    phase: ClaimPhase
    enabled_modes: frozenset = field(default_factory=frozenset)
    prohibited_categories: frozenset = field(default_factory=frozenset)
    permitted_input_kinds: frozenset = field(default_factory=frozenset)
    version: str = CLAIM_BOUNDARY_VERSION
    status: str = CLAIM_BOUNDARY_STATUS
    warning_by_language: Mapping[str, str] = field(
        default_factory=lambda: CANONICAL_CLINICAL_WARNING
    )

    # -- mode questions --------------------------------------------------

    def is_mode_enabled(self, mode: OperationMode) -> bool:
        """Return ``True`` only if ``mode`` may run under this boundary."""
        return mode in self.enabled_modes

    def require_mode_enabled(self, mode: OperationMode) -> None:
        """Raise :class:`ModeNotEnabledError` if ``mode`` is not enabled."""
        if not self.is_mode_enabled(mode):
            raise ModeNotEnabledError(mode, self)

    @property
    def disabled_modes(self) -> Tuple[OperationMode, ...]:
        """Modes that exist in the domain but are not enabled here."""
        return tuple(m for m in OperationMode if m not in self.enabled_modes)

    # -- claim questions -------------------------------------------------

    def is_category_prohibited(self, category: ProhibitedClaimCategory) -> bool:
        """Return ``True`` if ``category`` is forbidden under this boundary."""
        return category in self.prohibited_categories

    def warning(self, language: str = "tr") -> str:
        """Return the canonical warning text this boundary mandates."""
        key = (language or "").strip().lower()
        if key not in self.warning_by_language:
            raise ValueError("Unsupported warning language %r" % (language,))
        return self.warning_by_language[key]

    @property
    def is_approved(self) -> bool:
        """``True`` only when a human/scientific approval status is recorded.

        WP-00 ships an unapproved boundary on purpose. Downstream release
        gates may read this flag, but no code may set it to ``True`` without
        the recorded approval artifacts named in
        ``docs/architecture/intended-purpose.md``.
        """
        return "DRAFT" not in self.status.upper() and "AWAITING" not in self.status.upper()


#: The P0 claim boundary. All prohibited categories apply; PILOT is disabled;
#: only synthetic / protocol-defined / versioned validation inputs are legal.
P0_CLAIM_BOUNDARY = ClaimBoundary(
    phase=ClaimPhase.P0,
    enabled_modes=P0_ENABLED_MODES,
    prohibited_categories=frozenset(ProhibitedClaimCategory),
    permitted_input_kinds=frozenset(PermittedInputKind),
    version=CLAIM_BOUNDARY_VERSION,
    status=CLAIM_BOUNDARY_STATUS,
)

#: The boundary used when a caller does not pass one explicitly.
DEFAULT_CLAIM_BOUNDARY = P0_CLAIM_BOUNDARY


def is_mode_enabled(
    mode: OperationMode, boundary: ClaimBoundary = DEFAULT_CLAIM_BOUNDARY
) -> bool:
    """Explicit predicate: may ``mode`` run under ``boundary``?

    This is the function API, UI, and application layers must call before
    accepting a mode from a request. In P0 it returns ``False`` for
    :attr:`OperationMode.PILOT`.
    """
    if not isinstance(mode, OperationMode):
        raise TypeError("mode must be an OperationMode, got %r" % (type(mode).__name__,))
    return boundary.is_mode_enabled(mode)


def require_mode_enabled(
    mode: OperationMode, boundary: ClaimBoundary = DEFAULT_CLAIM_BOUNDARY
) -> None:
    """Raise :class:`ModeNotEnabledError` unless ``mode`` is enabled."""
    if not isinstance(mode, OperationMode):
        raise TypeError("mode must be an OperationMode, got %r" % (type(mode).__name__,))
    boundary.require_mode_enabled(mode)


# ---------------------------------------------------------------------------
# Lexical claim scanner (defense in depth - see module docstring)
# ---------------------------------------------------------------------------

# Turkish-aware case folding. Every mapping is one character to one
# character so that match offsets in the folded text remain valid offsets
# in the original text. ``str.lower()`` alone is unsafe here because
# ``"I".lower()`` yields a two-code-point string.
_FOLD_MAP = {
    ord("Ç"): "c", ord("ç"): "c",   # C cedilla
    ord("Ğ"): "g", ord("ğ"): "g",   # G breve
    ord("İ"): "i", ord("ı"): "i",   # dotted/dotless I
    ord("I"): "i",
    ord("Ö"): "o", ord("ö"): "o",   # O diaeresis
    ord("Ş"): "s", ord("ş"): "s",   # S cedilla
    ord("Ü"): "u", ord("ü"): "u",   # U diaeresis
    ord("Â"): "a", ord("â"): "a",
    ord("Î"): "i", ord("î"): "i",
    ord("Û"): "u", ord("û"): "u",
}


def _fold(text: str) -> str:
    """Fold Turkish diacritics and case, preserving character offsets.

    Folding lets one ASCII pattern match both ``"degildir"`` and
    ``"değildir"``. The legacy modules mix both spellings, so this is a
    correctness requirement, not a convenience.
    """
    folded = text.translate(_FOLD_MAP).lower()
    if len(folded) != len(text):  # pragma: no cover - defensive
        # Never risk reporting wrong offsets; fall back to the raw text.
        return text.lower() if len(text.lower()) == len(text) else text
    return folded


# --- safe context markers ---------------------------------------------------
#
# A "safe context" is a sentence that negates, forbids, or defers the claim
# instead of making it. Patterns below are matched against folded text.

_NEGATION_MARKERS = (
    # Turkish copular negation: degil / degildir / degilsin ...
    r"\bdegil\w*\b",
    # Turkish negative aorist: -maz / -mez (uretmez, gelmez, cikarilamaz).
    r"\b\w+m[ae]z\b",
    # Turkish negative present continuous: -mamaktadir / -memektedir.
    r"\b\w+m[ae]m[ae]kt[ae]dir\b",
    # Turkish negative potential: -amaz / -emez already covered above.
    r"\bhicbir\b",
    r"\bhic\s+bir\b",
    r"\basla\b",
    r"\byerine\s+gec\w*m[ae]z\b",
    # English negation.
    r"\b(?:not|never|cannot|can't|don't|doesn't|isn't|aren't|won't|without|no)\b",
)

_PROHIBITION_MARKERS = (
    # Turkish negative imperatives used in the legacy prompt/avoid lists.
    r"\b(?:ekleme|verme|kurma|yapma|onerme|uretme|belirtme|yazma|kullanma|degistirme)\b",
    r"\bkacin\w*\b",
    r"\byasak\w*\b",
    # English prohibition.
    r"\b(?:avoid|prohibited|forbidden|must\s+not|may\s+not|shall\s+not|do\s+not)\b",
)

_CLINICIAN_DEFERRAL_MARKERS = (
    r"\b(?:hekim|doktor|klinisyen|uzman\s+hekim)\w*\s+(?:tarafindan|karar\w*)\b",
    r"\byalnizca\s+(?:yetkili\s+)?(?:hekim|doktor|klinisyen)\w*\b",
    r"\b(?:hekiminize|doktorunuza|klinisyeninize)\s+danis\w*\b",
    r"\bby\s+(?:a\s+|the\s+)?(?:qualified\s+|licensed\s+|treating\s+)?"
    r"(?:physician|clinician|prescriber|doctor)\b",
    r"\bconsult\s+(?:your\s+|a\s+|the\s+)?(?:physician|doctor|clinician|pharmacist)\b",
)

_SAFE_CONTEXT_PATTERNS: Tuple[Tuple[SafeContextKind, "re.Pattern"], ...] = tuple(
    [(SafeContextKind.CLINICIAN_DEFERRAL, re.compile(p)) for p in _CLINICIAN_DEFERRAL_MARKERS]
    + [(SafeContextKind.NEGATION, re.compile(p)) for p in _NEGATION_MARKERS]
    + [(SafeContextKind.PROHIBITION, re.compile(p)) for p in _PROHIBITION_MARKERS]
)


@dataclass(frozen=True)
class ClaimPattern:
    """One lexical rule in the prohibited-claim registry.

    Attributes:
        rule_id: Stable identifier, quotable in a safety report.
        category: Prohibited claim category the rule defends.
        language: ``"tr"``, ``"en"``, or ``"xx"`` for language-independent.
        pattern: Regular expression, written against folded text.
        negatable: If ``True``, a negation or prohibition marker in the same
            sentence suppresses the match. Direct second-person imperatives
            are ``False``: "Bu ilaci kullanin" is a violation regardless of
            what the rest of the sentence claims. Clinician-deferral context
            suppresses both kinds.
        description: Human-readable intent of the rule.
    """

    rule_id: str
    category: ProhibitedClaimCategory
    language: str
    pattern: str
    negatable: bool
    description: str


_PATTERN_SPECS: Tuple[ClaimPattern, ...] = (
    # -- diagnosis ------------------------------------------------------
    ClaimPattern("CLAIM-DIAG-TR-001", ProhibitedClaimCategory.DIAGNOSIS, "tr",
                 r"\b(?:teshis|tani)\s+(?:koy|kon)\w*", True,
                 "Turkish 'teshis/tani koymak' (to make a diagnosis)."),
    ClaimPattern("CLAIM-DIAG-TR-002", ProhibitedClaimCategory.DIAGNOSIS, "tr",
                 r"\bhastali\w*\s+(?:var|mevcut)\w*", True,
                 "Asserting that the subject has a disease."),
    ClaimPattern("CLAIM-DIAG-EN-001", ProhibitedClaimCategory.DIAGNOSIS, "en",
                 r"\bdiagnos(?:e|es|ed|is|ing)\b", True,
                 "English diagnose/diagnosis verbs and nouns."),

    # -- prescription ---------------------------------------------------
    ClaimPattern("CLAIM-RX-TR-001", ProhibitedClaimCategory.PRESCRIPTION, "tr",
                 r"\brecete\s*(?:et|edil|yaz)\w*", True,
                 "Turkish 'recete etmek/yazmak' (to prescribe)."),
    ClaimPattern("CLAIM-RX-EN-001", ProhibitedClaimCategory.PRESCRIPTION, "en",
                 r"\bprescrib(?:e|es|ed|ing)\b|\bprescription\b", True,
                 "English prescribe/prescription."),

    # -- dosing ---------------------------------------------------------
    ClaimPattern("CLAIM-DOSE-TR-001", ProhibitedClaimCategory.DOSING, "tr",
                 r"\b(?:doz|tedavi|ilac)\w*\s+oneri\w*", True,
                 "Turkish 'doz/tedavi/ilac onerisi' (dose/treatment recommendation)."),
    ClaimPattern("CLAIM-DOSE-TR-002", ProhibitedClaimCategory.DOSING, "tr",
                 r"\bdoz\w*\s+(?:\S+\s+){0,2}?"
                 r"(?:azalt|artir|arttir|dusur|yukselt|ayarla|titre|yariya)\w*", True,
                 "Turkish dose-change verbs applied to a dose."),
    ClaimPattern("CLAIM-DOSE-TR-003", ProhibitedClaimCategory.DOSING, "tr",
                 r"\bdoz\w*\s+(?:\S+\s+){0,3}?(?:olmali|verilmeli|uygulanmali)\w*", True,
                 "Turkish deontic dose statement ('doz ... olmali')."),
    ClaimPattern("CLAIM-DOSE-EN-001", ProhibitedClaimCategory.DOSING, "en",
                 r"\b(?:reduce|increase|halve|double|adjust|titrate|lower|raise)\s+"
                 r"(?:the\s+|your\s+|his\s+|her\s+)?(?:dose|dosage|dosing)\b", True,
                 "English dose-change verbs."),
    ClaimPattern("CLAIM-DOSE-EN-002", ProhibitedClaimCategory.DOSING, "en",
                 r"\b(?:dose|dosage)\s+(?:should|must)\s+be\b", True,
                 "English deontic dose statement."),

    # -- medication change / direct instruction (imperatives) -----------
    ClaimPattern("CLAIM-MEDIC-TR-001", ProhibitedClaimCategory.MEDICATION_CHANGE, "tr",
                 r"\b(?:bu\s+)?(?:ilac|tedavi)\w*\s+(?:\S+\s+){0,2}?"
                 r"(?:kullanin|kullaniniz|kullanmalisiniz|alin|aliniz|birakin|birakiniz|"
                 r"kesin|kesiniz|durdurun|degistirin|baslayin|baslayiniz)\b", False,
                 "Turkish second-person imperative addressed to a drug/treatment."),
    ClaimPattern("CLAIM-MEDIC-TR-002", ProhibitedClaimCategory.DOSING, "tr",
                 r"\bdoz\w*\s+(?:\S+\s+){0,2}?"
                 r"(?:azaltin|azaltiniz|artirin|arttirin|dusurun|yukseltin|degistirin|"
                 r"ayarlayin|yariya\s+indirin)\b", False,
                 "Turkish second-person imperative addressed to a dose."),
    ClaimPattern("CLAIM-MEDIC-EN-001", ProhibitedClaimCategory.MEDICATION_CHANGE, "en",
                 r"\b(?:stop|start|switch|discontinue|withhold)\s+"
                 r"(?:taking\s+)?(?:the\s+|your\s+|this\s+)?"
                 r"(?:drug|medication|medicine|treatment|therapy)\b", True,
                 "English start/stop/switch instruction for a medication."),
    ClaimPattern("CLAIM-MEDIC-EN-002", ProhibitedClaimCategory.MEDICATION_CHANGE, "en",
                 r"\b(?:take|use)\s+(?:this|the)\s+(?:drug|medication|medicine)\b", True,
                 "English 'take/use this drug' instruction."),

    # -- treatment selection --------------------------------------------
    ClaimPattern("CLAIM-TXSEL-TR-001", ProhibitedClaimCategory.TREATMENT_SELECTION, "tr",
                 r"\byerine\b(?:\s+\S+){0,4}?\s+"
                 r"(?:kullanil|tercih\s+edil|baslan|gecil|verilme|secil)\w*"
                 r"(?:mali|meli)\w*", True,
                 "Turkish 'X yerine Y kullanilmalidir' substitution directive."),
    ClaimPattern("CLAIM-TXSEL-TR-002", ProhibitedClaimCategory.TREATMENT_SELECTION, "tr",
                 r"\b(?:tedavi|ilac|alternatif)\w*\s+(?:olarak\s+)?(?:\S+\s+){0,2}?"
                 r"(?:secilmeli|onerilmekte|oneriyoruz|oneririz|tavsiye\s+edil)\w*", True,
                 "Turkish treatment selection / recommendation verbs."),
    ClaimPattern("CLAIM-TXSEL-EN-001", ProhibitedClaimCategory.TREATMENT_SELECTION, "en",
                 r"\b(?:use|prescribe|switch\s+to|start)\b[^.;!?\n]{0,40}?\binstead\s+of\b",
                 True, "English 'use X instead of Y'."),
    ClaimPattern("CLAIM-TXSEL-EN-002", ProhibitedClaimCategory.TREATMENT_SELECTION, "en",
                 r"\brecommend(?:s|ed|ation|ations)?\b[^.;!?\n]{0,30}?"
                 r"\b(?:dose|dosage|drug|medication|treatment|therapy|alternative)\b",
                 True, "English recommendation of a drug, dose, or treatment."),

    # -- safety assurance -----------------------------------------------
    ClaimPattern("CLAIM-SAFE-TR-001", ProhibitedClaimCategory.SAFETY_ASSURANCE, "tr",
                 r"\b(?:guvenlidir|guvenliydi|risksizdir|zararsizdir|emniyetlidir)\b",
                 True, "Turkish assertive safety declaration."),
    ClaimPattern("CLAIM-SAFE-TR-002", ProhibitedClaimCategory.SAFETY_ASSURANCE, "tr",
                 r"\b(?:ilac|aday|kombinasyon|tedavi|kullanim|profil)\w*\s+"
                 r"(?:icin\s+)?(?:tamamen\s+|tumuyle\s+)?"
                 r"(?:guvenli|risksiz|zararsiz)\b", True,
                 "Turkish 'this drug/candidate ... safe' construction."),
    ClaimPattern("CLAIM-SAFE-EN-001", ProhibitedClaimCategory.SAFETY_ASSURANCE, "en",
                 r"\b(?:is|are|remains|remain|considered|proven|deemed)\s+"
                 r"(?:completely\s+|entirely\s+|clinically\s+|perfectly\s+)?safe\b",
                 True, "English 'is safe' declaration."),
    ClaimPattern("CLAIM-SAFE-EN-002", ProhibitedClaimCategory.SAFETY_ASSURANCE, "en",
                 r"\bsafe\s+to\s+(?:use|take|prescribe|combine|continue)\b|"
                 r"\brisk[-\s]free\b", True,
                 "English 'safe to use' / 'risk-free'."),

    # -- candidate preference -------------------------------------------
    ClaimPattern("CLAIM-CAND-TR-001", ProhibitedClaimCategory.CANDIDATE_PREFERENCE, "tr",
                 r"\bdaha\s+(?:guvenli|iyi|uygun|az\s+riskli|dusuk\s+riskli)\b", True,
                 "Turkish comparative preference ('daha guvenli/uygun')."),
    ClaimPattern("CLAIM-CAND-TR-002", ProhibitedClaimCategory.CANDIDATE_PREFERENCE, "tr",
                 r"\b(?:en\s+uygun|tercih\s+edilmeli\w*|tercih\s+edilir|"
                 r"onerilen\s+alternatif|uygun\s+(?:alternatif|aday|secenek)|"
                 r"klinik\s+olarak\s+esdeger\w*)\b", True,
                 "Turkish superlative/preference/equivalence labels."),
    ClaimPattern("CLAIM-CAND-EN-001", ProhibitedClaimCategory.CANDIDATE_PREFERENCE, "en",
                 r"\b(?:safer|better\s+tolerated|preferable|preferred|"
                 r"more\s+suitable|most\s+suitable|clinically\s+equivalent)\b", True,
                 "English candidate preference/equivalence labels."),

    # -- false reassurance ----------------------------------------------
    ClaimPattern("CLAIM-REASSURE-TR-001", ProhibitedClaimCategory.FALSE_REASSURANCE, "tr",
                 r"\b(?:dusuk|az)\s+(?:riskli\w*|risk\b|dikkatli\w*)", True,
                 "Turkish low-risk assertion (must always be negated or absent)."),
    ClaimPattern("CLAIM-REASSURE-EN-001", ProhibitedClaimCategory.FALSE_REASSURANCE, "en",
                 r"\b(?:low|no|minimal|negligible)\s+risk\b", True,
                 "English low/no-risk assertion."),

    # -- real patient data (P0) -----------------------------------------
    ClaimPattern("CLAIM-REALDATA-TR-001", ProhibitedClaimCategory.REAL_PATIENT_DATA, "tr",
                 r"\b(?:vcf|ehr|genotip|diplotip)\w*\s+(?:\S+\s+){0,3}?"
                 r"(?:yukle|isle|analiz|cozumle|degerlendir)\w*", True,
                 "Turkish claim of processing VCF/EHR/genotype input."),
    ClaimPattern("CLAIM-REALDATA-TR-002", ProhibitedClaimCategory.REAL_PATIENT_DATA, "tr",
                 r"\bgercek\s+hasta\s+(?:veri|genom|orne)\w*\s+(?:\S+\s+){0,3}?"
                 r"(?:kullanilarak|uzerinde|ile)\s+(?:\S+\s+){0,2}?"
                 r"(?:analiz|hesapla|degerlendir|calis)\w*", True,
                 "Turkish claim of computing on real patient data."),
    ClaimPattern("CLAIM-REALDATA-EN-001", ProhibitedClaimCategory.REAL_PATIENT_DATA, "en",
                 r"\b(?:your|the\s+patient's|patient)\s+"
                 r"(?:vcf|genome|genotype|ehr|laboratory\s+report|lab\s+report)\b",
                 True, "English claim of using a real patient's genomic/EHR data."),

    # -- clinical decision substitution ---------------------------------
    ClaimPattern("CLAIM-DECISION-TR-001",
                 ProhibitedClaimCategory.CLINICAL_DECISION_SUBSTITUTION, "tr",
                 r"\bklinik\s+karar\w*\s+(?:\S+\s+){0,2}?"
                 r"(?:ver|verir|veriyor|verici|uret|sagla|yerine\s+gec)\w*", True,
                 "Turkish claim of making or replacing a clinical decision."),
    ClaimPattern("CLAIM-DECISION-EN-001",
                 ProhibitedClaimCategory.CLINICAL_DECISION_SUBSTITUTION, "en",
                 r"\breplaces?\s+(?:the\s+|a\s+)?"
                 r"(?:clinical|medical|physician|doctor|clinician)\w*\b", True,
                 "English claim of replacing a clinician or clinical judgement."),

    # -- validation overclaim -------------------------------------------
    ClaimPattern("CLAIM-VALID-TR-001", ProhibitedClaimCategory.VALIDATION_OVERCLAIM, "tr",
                 r"\b(?:dogrulanmis|onaylanmis|valide\s+edilmis|sertifikali)\b"
                 r"[^.;!?\n]{0,30}?\b(?:klinik|tibbi|sistem|urun|cihaz)\w*\b", True,
                 "Turkish claim of clinical validation/approval/certification."),
    ClaimPattern("CLAIM-VALID-TR-002", ProhibitedClaimCategory.VALIDATION_OVERCLAIM, "tr",
                 r"\bce\s+(?:isaretli|belgeli)\b|\bruhsatli\b|"
                 r"\bklinik\s+kullanima\s+uygundur\b", True,
                 "Turkish regulatory/market-authorisation claim."),
    ClaimPattern("CLAIM-VALID-EN-001", ProhibitedClaimCategory.VALIDATION_OVERCLAIM, "en",
                 r"\b(?:fda|ce|ema)[-\s]?(?:approved|cleared|marked)\b|"
                 r"\bclinically\s+validated\b|\bapproved\s+for\s+clinical\s+use\b",
                 True, "English regulatory/clinical-validation claim."),
)

_COMPILED_PATTERNS: Tuple[Tuple[ClaimPattern, "re.Pattern"], ...] = tuple(
    (spec, re.compile(spec.pattern)) for spec in _PATTERN_SPECS
)


def claim_patterns() -> Tuple[ClaimPattern, ...]:
    """Return the immutable prohibited-claim pattern registry."""
    return _PATTERN_SPECS


# ---------------------------------------------------------------------------
# Scan results
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ClaimViolation:
    """One prohibited-claim hit, with enough context to act on it."""

    rule_id: str
    category: ProhibitedClaimCategory
    language: str
    matched_text: str
    start: int
    end: int
    sentence: str
    severity: ViolationSeverity = ViolationSeverity.BLOCKING

    def as_dict(self) -> Dict[str, object]:
        """Return a JSON-serialisable view for audit records and API errors."""
        return {
            "rule_id": self.rule_id,
            "category": self.category.value,
            "language": self.language,
            "matched_text": self.matched_text,
            "start": self.start,
            "end": self.end,
            "sentence": self.sentence,
            "severity": self.severity.value,
        }


@dataclass(frozen=True)
class SuppressedMatch:
    """A pattern hit that a safe context neutralised.

    Recorded for transparency: a reviewer must be able to see what the
    scanner decided to let through and why, instead of trusting a bare
    ``True``.
    """

    rule_id: str
    category: ProhibitedClaimCategory
    matched_text: str
    start: int
    end: int
    sentence: str
    safe_context: SafeContextKind
    safe_context_text: str

    def as_dict(self) -> Dict[str, object]:
        """Return a JSON-serialisable view."""
        return {
            "rule_id": self.rule_id,
            "category": self.category.value,
            "matched_text": self.matched_text,
            "start": self.start,
            "end": self.end,
            "sentence": self.sentence,
            "safe_context": self.safe_context.value,
            "safe_context_text": self.safe_context_text,
        }


@dataclass(frozen=True)
class ClaimScanResult:
    """Structured, deterministic outcome of a claim-text scan.

    Deliberately not a boolean: callers need the category, the rule ID, the
    matched span, and the sentence in order to fix the template, to write an
    audit record, and to explain the block to a reviewer.
    """

    text_length: int
    violations: Tuple[ClaimViolation, ...] = ()
    suppressed: Tuple[SuppressedMatch, ...] = ()
    scanner_version: str = CLAIM_SCANNER_VERSION
    boundary_version: str = CLAIM_BOUNDARY_VERSION

    @property
    def is_clean(self) -> bool:
        """``True`` when no prohibited claim survived safe-context analysis."""
        return not self.violations

    @property
    def has_violations(self) -> bool:
        """``True`` when at least one blocking violation was found."""
        return bool(self.violations)

    @property
    def categories(self) -> Tuple[ProhibitedClaimCategory, ...]:
        """Distinct violated categories, in first-occurrence order."""
        seen: List[ProhibitedClaimCategory] = []
        for violation in self.violations:
            if violation.category not in seen:
                seen.append(violation.category)
        return tuple(seen)

    @property
    def rule_ids(self) -> Tuple[str, ...]:
        """Distinct violated rule IDs, in first-occurrence order."""
        seen: List[str] = []
        for violation in self.violations:
            if violation.rule_id not in seen:
                seen.append(violation.rule_id)
        return tuple(seen)

    def violations_for(
        self, category: ProhibitedClaimCategory
    ) -> Tuple[ClaimViolation, ...]:
        """Return the violations belonging to ``category``."""
        return tuple(v for v in self.violations if v.category is category)

    def as_dict(self) -> Dict[str, object]:
        """Return a JSON-serialisable view for audit and API responses."""
        return {
            "scanner_version": self.scanner_version,
            "boundary_version": self.boundary_version,
            "text_length": self.text_length,
            "is_clean": self.is_clean,
            "violation_count": len(self.violations),
            "categories": [c.value for c in self.categories],
            "violations": [v.as_dict() for v in self.violations],
            "suppressed": [s.as_dict() for s in self.suppressed],
        }


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------

# Sentence terminators. ';' is included so that a directive cannot hide
# behind a disclaimer glued to it with a semicolon.
_SENTENCE_BOUNDARY = re.compile(r"[.!?;\n\r]+")


def _sentence_spans(text: str) -> Tuple[Tuple[int, int], ...]:
    """Split ``text`` into (start, end) sentence spans, preserving offsets."""
    spans: List[Tuple[int, int]] = []
    cursor = 0
    for match in _SENTENCE_BOUNDARY.finditer(text):
        end = match.start()
        if end > cursor:
            spans.append((cursor, end))
        cursor = match.end()
    if cursor < len(text):
        spans.append((cursor, len(text)))
    return tuple(spans)


def _safe_context_for(folded_sentence: str) -> Optional[Tuple[SafeContextKind, str]]:
    """Return the strongest safe context found in ``folded_sentence``.

    Clinician deferral is checked first because it neutralises even direct
    imperatives ("Doz ... yalnizca hekim tarafindan verilir").
    """
    for kind, pattern in _SAFE_CONTEXT_PATTERNS:
        found = pattern.search(folded_sentence)
        if found:
            return kind, found.group(0)
    return None


def scan_claim_text(
    text: Optional[str],
    *,
    languages: Optional[Sequence[str]] = None,
    boundary: ClaimBoundary = DEFAULT_CLAIM_BOUNDARY,
) -> ClaimScanResult:
    """Scan ``text`` for prohibited clinical claim language.

    This is the deterministic check that API, UI, and reporting layers call
    before releasing user-facing text (``SAFETY-INV-010``). It never mutates
    the text and never calls out to a model or a network service.

    Args:
        text: The candidate user-facing text. ``None`` or blank is clean.
        languages: Restrict the rule set to these language codes (plus
            language-independent rules). Defaults to every supported
            language, which is the correct choice for mixed TR/EN output.
        boundary: Claim boundary in force; only prohibited categories
            declared by the boundary are reported.

    Returns:
        A :class:`ClaimScanResult`. Inspect ``violations`` (structured) --
        do not reduce the answer to a boolean when reporting to a human.

    Note:
        Lexical defense in depth only. See the module docstring: this is
        not semantic analysis and never certifies that text is safe.
    """
    if text is None:
        return ClaimScanResult(text_length=0, boundary_version=boundary.version)

    if not isinstance(text, str):
        raise TypeError("text must be a str or None, got %r" % (type(text).__name__,))

    if not text.strip():
        return ClaimScanResult(text_length=len(text), boundary_version=boundary.version)

    if languages is None:
        allowed_languages = set(SUPPORTED_LANGUAGES)
    else:
        allowed_languages = {str(code).strip().lower() for code in languages}

    folded = _fold(text)
    violations: List[ClaimViolation] = []
    suppressed: List[SuppressedMatch] = []

    for start, end in _sentence_spans(text):
        raw_sentence = text[start:end].strip()
        folded_sentence = folded[start:end]
        safe_context = _safe_context_for(folded_sentence)

        for spec, compiled in _COMPILED_PATTERNS:
            if spec.language not in allowed_languages and spec.language != "xx":
                continue
            if not boundary.is_category_prohibited(spec.category):
                continue

            for match in compiled.finditer(folded_sentence):
                abs_start = start + match.start()
                abs_end = start + match.end()
                matched_text = text[abs_start:abs_end]

                if safe_context is not None:
                    kind, marker = safe_context
                    if kind is SafeContextKind.CLINICIAN_DEFERRAL or spec.negatable:
                        suppressed.append(
                            SuppressedMatch(
                                rule_id=spec.rule_id,
                                category=spec.category,
                                matched_text=matched_text,
                                start=abs_start,
                                end=abs_end,
                                sentence=raw_sentence,
                                safe_context=kind,
                                safe_context_text=marker,
                            )
                        )
                        continue

                violations.append(
                    ClaimViolation(
                        rule_id=spec.rule_id,
                        category=spec.category,
                        language=spec.language,
                        matched_text=matched_text,
                        start=abs_start,
                        end=abs_end,
                        sentence=raw_sentence,
                        severity=ViolationSeverity.BLOCKING,
                    )
                )

    # Deterministic ordering: position first, then rule ID.
    violations.sort(key=lambda v: (v.start, v.end, v.rule_id))
    suppressed.sort(key=lambda s: (s.start, s.end, s.rule_id))

    return ClaimScanResult(
        text_length=len(text),
        violations=tuple(violations),
        suppressed=tuple(suppressed),
        boundary_version=boundary.version,
    )


def assert_claim_text_allowed(
    text: Optional[str],
    *,
    languages: Optional[Sequence[str]] = None,
    boundary: ClaimBoundary = DEFAULT_CLAIM_BOUNDARY,
) -> ClaimScanResult:
    """Scan ``text`` and raise :class:`ProhibitedClaimError` on any violation.

    Convenience wrapper for call sites whose correct behaviour on a hit is
    to fail closed (``SAFETY-INV-010``: prohibited claim text blocks report
    release). The successful result is returned so that callers can record
    the scanner version in an audit entry.
    """
    result = scan_claim_text(text, languages=languages, boundary=boundary)
    if result.has_violations:
        raise ProhibitedClaimError(result)
    return result
