# -*- coding: utf-8 -*-
"""Fixed, versioned report templates and their controlled labels (WP-15).

Everything a report says that did not come from the assessment is here, and
nothing here is generated. Labels are looked up in fixed tables; an unknown
code raises rather than falling back to itself, because a label that quietly
becomes ``"SOME_NEW_STATUS"`` is a report that shows a person a token nobody
wrote a meaning for.

**Turkish is the primary locale.** The product is Turkish-facing and the
canonical clinical warning was written in Turkish first; English exists so the
same report can be read by a reviewer who does not read Turkish.

**Governed values are never translated.** Reason codes, attention codes,
coverage codes, phenotypes, rule identifiers, evidence identifiers, release
identifiers and every hash are printed exactly as the engine produced them.
A label may be shown *beside* a code; it never replaces one. Two reasons: a
translated code cannot be matched against the ruleset that produced it, and a
translation is a place for a meaning to drift into a report without passing
through curation.

**Phenotypes are deliberately not localised at all.** ``RAPID`` and
``ULTRARAPID`` are different governed values whose confusion is its own safety
invariant (``SAFETY-INV-004``); a pair of Turkish adjectives for them would be
a translation of a scientific claim, made here, by nobody qualified.

The canonical clinical warning is **imported** from
:mod:`pgx.domain.claims`. It is never restated, paraphrased, shortened or
re-typed here, and a test greps this package for its text to prove it.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Tuple

from pgx.reporting.errors import ReportRenderError

__all__ = [
    "ATTENTION_LABELS",
    "FIELD_LABELS",
    "CONTROLLED_STATEMENTS",
    "COVERAGE_LABELS",
    "COVERAGE_REASON_LABELS",
    "DEFAULT_LOCALE",
    "INPUT_KIND_LABELS",
    "MEDICATION_QUESTIONS",
    "MODE_LABELS",
    "OBSERVATION_STATE_LABELS",
    "SECTION_TITLES",
    "SUPPORTED_LOCALES",
    "TEMPLATE_VERSIONS",
    "TEMPLATE_VERSION",
    "label",
    "require_locale",
    "require_template",
    "statement",
]

#: The template this build renders. A report records the version it was
#: rendered under, so a document produced last month can be told from one
#: produced by a changed template even when the facts are identical.
TEMPLATE_VERSION = "pgx-report-template/1"

#: Every template version this build can render. One today; the tuple exists
#: so adding a second is an edit here rather than a change of shape
#: everywhere.
TEMPLATE_VERSIONS: Tuple[str, ...] = (TEMPLATE_VERSION,)

#: Turkish first, deliberately.
DEFAULT_LOCALE = "tr"
SUPPORTED_LOCALES: Tuple[str, ...] = ("tr", "en")

ATTENTION_LABELS: Mapping[str, Mapping[str, str]] = {
    "HIGH": {"tr": "Yüksek dikkat düzeyi",
             "en": "High attention level"},
    "MEDIUM": {"tr": "Orta dikkat düzeyi",
               "en": "Medium attention level"},
    "LOW": {"tr": "Düşük dikkat düzeyi",
            "en": "Low attention level"},
    "NO_ACTIVE_ATTENTION": {
        "tr": "Bu sürümde etkin dikkat bulgusu üretilmedi",
        "en": "No active attention finding was produced in this release"},
    "NOT_ASSESSED": {
        "tr": "Değerlendirilmedi / değerlendirme kapsamı dışında",
        "en": "Not assessed / outside the assessed scope"},
}

COVERAGE_LABELS: Mapping[str, Mapping[str, str]] = {
    "FULL": {"tr": "Tam kapsam", "en": "Full coverage"},
    "PARTIAL": {"tr": "Kısmi kapsam", "en": "Partial coverage"},
    "INSUFFICIENT": {"tr": "Yetersiz kapsam", "en": "Insufficient coverage"},
    "UNSUPPORTED_DRUG": {
        "tr": "İlaç bu sürümün kapsamı dışında",
        "en": "The medication is outside this release's scope"},
    "UNSUPPORTED_PHENOTYPE": {
        "tr": "Fenotip bu sürümün kapsamı dışında",
        "en": "The phenotype is outside this release's scope"},
    "SOURCE_CONFLICT": {
        "tr": "Kaynaklar arasında çözülmemiş çelişki",
        "en": "Unresolved conflict between sources"},
}

COVERAGE_REASON_LABELS: Mapping[str, Mapping[str, str]] = {
    "DRUG_NOT_IN_CANONICAL_DATASET": {
        "tr": "İlaç, sabitlenmiş kanonik veri kümesinde bulunmuyor",
        "en": "The medication is not in the pinned canonical dataset"},
    "PHENOTYPE_NOT_PROVIDED": {
        "tr": "Bu gen için fenotip verilmedi",
        "en": "No phenotype was supplied for this gene"},
    "PHENOTYPE_NOT_SUPPORTED": {
        "tr": "Verilen değer, bu giriş sözleşmesinde kanonik bir fenotip "
              "değil",
        "en": "The supplied value is not a canonical phenotype under this "
              "input contract"},
    "NO_VALIDATED_RULE_FOR_AXIS": {
        "tr": "Yürürlükteki kural kümesi bu ekseni kapsayan bir kural "
              "içermiyor",
        "en": "The ruleset in force contains no rule covering this axis"},
    "SOME_AXES_NOT_COVERED": {
        "tr": "Beklenen eksenlerin bir bölümü değerlendirilemedi",
        "en": "Some of the expected axes could not be evaluated"},
    "VALIDATED_RULES_CONFLICT": {
        "tr": "Kural kümesindeki kurallar bu eksende birbiriyle çelişiyor",
        "en": "Rules in the ruleset disagree about this axis"},
    "DATASET_RULESET_MISMATCH": {
        "tr": "Veri kümesi ile kural kümesi aynı yapıya ait değil",
        "en": "The dataset and the ruleset do not belong to the same build"},
    "EVIDENCE_REFERENCE_MISSING": {
        "tr": "Kanıt referansı sabitlenmiş yapıda çözümlenemedi",
        "en": "An evidence reference did not resolve in the pinned build"},
}

OBSERVATION_STATE_LABELS: Mapping[str, Mapping[str, str]] = {
    "NORMALIZED": {"tr": "Kanonik fenotipe çevrildi",
                   "en": "Normalised to a canonical phenotype"},
    "MISSING": {"tr": "Değer verilmedi",
                "en": "No value was supplied"},
    "INDETERMINATE": {"tr": "Belirlenemedi olarak bildirildi",
                      "en": "Reported as indeterminate"},
    "UNSUPPORTED": {"tr": "Değer bu sözleşmede tanınmıyor",
                    "en": "The value is not recognised under this contract"},
    "NOT_EVALUATED": {"tr": "Bu eksende gözlem değerlendirilmedi",
                      "en": "No observation was evaluated on this axis"},
    # WP-13 uses ABSENT where the profile says nothing at all about the gene,
    # which is a different fact from MISSING - somebody supplied the gene and
    # left it blank. Both prevent coverage and they mean different things, so
    # both get their own sentence rather than one shared one.
    "ABSENT": {"tr": "Profil bu gen hakkında hiçbir şey belirtmiyor",
               "en": "The profile says nothing at all about this gene"},
}

MODE_LABELS: Mapping[str, Mapping[str, str]] = {
    "DEMO": {"tr": "Gösterim (sentetik profiller)",
             "en": "Demonstration (synthetic profiles)"},
    "VALIDATION": {"tr": "Doğrulama (sürümlenmiş iç vakalar)",
                   "en": "Validation (versioned internal cases)"},
    "PILOT": {"tr": "Pilot (P0'da kapalı)",
              "en": "Pilot (disabled in P0)"},
}

INPUT_KIND_LABELS: Mapping[str, Mapping[str, str]] = {
    "SYNTHETIC_PHENOTYPE_PROFILE": {
        "tr": "Sentetik fenotip profili",
        "en": "Synthetic phenotype profile"},
    "PROTOCOL_DEFINED_PHENOTYPE_PROFILE": {
        "tr": "Protokolle tanımlanmış fenotip profili",
        "en": "Protocol-defined phenotype profile"},
    "PUBLIC_DEMO_PROFILE": {
        "tr": "Açık gösterim profili",
        "en": "Public demonstration profile"},
    "VERSIONED_VALIDATION_CASE": {
        "tr": "Sürümlenmiş doğrulama vakası",
        "en": "Versioned validation case"},
    "MEDICATION_NAME_LIST": {
        "tr": "İlaç adı listesi",
        "en": "Medication name list"},
}

SECTION_TITLES: Mapping[str, Mapping[str, str]] = {
    "report": {"tr": "Farmakogenetik dikkat ve kapsam raporu",
               "en": "Pharmacogenetic attention and coverage report"},
    "warning": {"tr": "Uyarı", "en": "Warning"},
    "disclaimer": {"tr": "Bu belgenin niteliği",
                   "en": "What this document is"},
    "summary": {"tr": "Genel sonuç", "en": "Overall result"},
    "profile": {"tr": "Değerlendirilen fenotip gözlemleri",
                "en": "Phenotype observations evaluated"},
    "medications": {"tr": "İlaç bazlı bulgular",
                    "en": "Findings by medication"},
    "axes": {"tr": "Eksenler", "en": "Axes"},
    "findings": {"tr": "Bulgular", "en": "Findings"},
    "not_assessed": {"tr": "Değerlendirilmeyenler",
                     "en": "What was not assessed"},
    "conflicts": {"tr": "Çözülmemiş kaynak çelişkileri",
                  "en": "Unresolved source conflicts"},
    "uncertainty": {"tr": "Belirsizlik ve sınırlar",
                    "en": "Uncertainty and limits"},
    "provenance": {"tr": "Sürüm ve izlenebilirlik",
                   "en": "Versions and traceability"},
    "hashes": {"tr": "Özetler", "en": "Digests"},
}

#: Sentences the report may state, in full, from a fixed table. Every one of
#: them is a statement about *this system*, never about a medicine, a person
#: or a decision. Nothing composes a sentence at runtime.
CONTROLLED_STATEMENTS: Mapping[str, Mapping[str, str]] = {
    "not_assessed": {
        "tr": "Bu öğe değerlendirilmedi ve değerlendirme kapsamı dışındadır. "
              "Bu bir sonuç değildir; hiçbir düzey, hiçbir güvence ve hiçbir "
              "olumsuzlama anlamına gelmez.",
        "en": "This item was not assessed and is outside the assessed scope. "
              "It is not a result: it carries no level, no assurance and no "
              "negative finding."},
    "partial_coverage": {
        "tr": "Kapsam kısmidir. Aşağıdaki dikkat düzeyi yalnızca "
              "değerlendirilebilen eksenler için hesaplanmıştır; "
              "değerlendirilemeyen eksenler aşağıda gerekçeleriyle "
              "listelenmiştir.",
        "en": "Coverage is partial. The attention level below was calculated "
              "only over the axes that could be evaluated; the axes that "
              "could not are listed below with their reasons."},
    "high_attention_partial_coverage": {
        "tr": "Bu değer, yalnızca değerlendirilebilen eksenler arasındaki en "
              "yüksek düzeydir. Değerlendirilemeyen eksenler bu değere "
              "girmemiştir ve eksik veri bir düzey anlamına gelmez.",
        "en": "This value is the worst level among the evaluated subset "
              "only. The axes that could not be evaluated did not enter it, "
              "and missing data does not amount to a level."},
    "source_conflict": {
        "tr": "Bu eksende kaynaklar arasında çözülmemiş bir çelişki "
              "kayıtlıdır. Çelişki korunmuştur ve bu sistem tarafından "
              "çözülmemiştir; aşağıdaki referanslar çelişkinin kendisine "
              "işaret eder.",
        "en": "An unresolved conflict between sources is recorded on this "
              "axis. The conflict is preserved and was not resolved by this "
              "system; the references below point at the conflict itself."},
    "no_governed_codes": {
        "tr": "Bu yönetilen kural kümesi bir etki/açıklama kodu taşımıyor. "
              "Aşağıdaki gerekçe referansı ve kanıt referansları, bulgunun "
              "dayandığı kayıtlara işaret eder.",
        "en": "This governed ruleset does not carry an effect/explanation "
              "code. The rationale reference and evidence references below "
              "point at the records the finding rests on."},
    "full_coverage": {
        "tr": "Beklenen eksenlerin tamamı değerlendirilebildi; bu kalem için "
              "kaydedilmiş bir kapsam gerekçesi yoktur.",
        "en": "Every expected axis could be evaluated; no coverage reason is "
              "recorded for this item."},
    "attention_and_coverage": {
        "tr": "Dikkat düzeyi ve kapsam iki ayrı sonuçtur. Hiçbiri diğerinin "
              "özeti değildir ve hiçbiri diğeri olmadan okunmamalıdır.",
        "en": "Attention level and coverage are two separate results. "
              "Neither summarises the other, and neither should be read "
              "without the other."},
    "disclaimer": {
        "tr": "Bu belge bir araştırma/prototip gösterim çıktısıdır. "
              "Sentetik veya protokolle tanımlanmış fenotip profillerinin, "
              "sürümlenmiş ve uzman yönetimli bir kural kümesiyle "
              "karşılaştırılmasından üretilmiştir. Klinik kullanım için "
              "onaylanmamıştır ve klinik bir karar aracı değildir.",
        "en": "This document is a research/prototype demonstration output. "
              "It was produced by comparing synthetic or protocol-defined "
              "phenotype profiles against a versioned, expert-governed "
              "ruleset. It is not approved for clinical use and it is not a "
              "clinical decision tool."},
    "no_findings_for_medication": {
        "tr": "Bu ilaç için yönetilen kural kümesinden hesaplanmış bir bulgu "
              "yoktur. Bu, bir olumsuzlama değildir; yukarıdaki kapsam "
              "durumu bunun nedenini belirtir.",
        "en": "No finding was calculated for this medication from the "
              "governed ruleset. That is not a negative finding; the "
              "coverage status above states why."},
    "profile_note": {
        "tr": "Aşağıda, verilen profilin kanonik hâli yer alır. "
              "Yorumlanamayan gözlemler de gerekçeleriyle korunmuştur.",
        "en": "Below is the canonical form of the supplied profile. "
              "Observations that could not be interpreted are kept with "
              "their reasons."},
}

#: Column and row labels. Separate from :data:`SECTION_TITLES` because these
#: name *fields*, and a field whose label went missing would be a table
#: column with a blank heading rather than a missing section.
FIELD_LABELS: Mapping[str, Mapping[str, str]] = {
    "assessment_id": {"tr": "Değerlendirme kimliği", "en": "Assessment id"},
    "case_id": {"tr": "Vaka etiketi", "en": "Case label"},
    "mode": {"tr": "Çalışma kipi", "en": "Operation mode"},
    "input_kind": {"tr": "Girdi türü", "en": "Input kind"},
    "attention_code": {"tr": "Dikkat kodu", "en": "Attention code"},
    "attention": {"tr": "Dikkat düzeyi", "en": "Attention level"},
    # A finding's own level is labelled differently from a medication's or the
    # report's. Sharing one label invites a reader to take a single axis's
    # level for the whole medication's - and the difference between those two
    # is what coverage exists to express.
    "finding_attention_code": {"tr": "Bulgu dikkat kodu",
                               "en": "Finding attention code"},
    "finding_attention": {"tr": "Bulgu dikkat düzeyi",
                          "en": "Finding attention level"},
    "coverage_code": {"tr": "Kapsam kodu", "en": "Coverage code"},
    "coverage": {"tr": "Kapsam", "en": "Coverage"},
    "reason_code": {"tr": "Gerekçe kodu", "en": "Reason code"},
    "reason": {"tr": "Gerekçe", "en": "Reason"},
    "gene": {"tr": "Gen", "en": "Gene"},
    "drug": {"tr": "İlaç", "en": "Medication"},
    "requested_value": {"tr": "İstenen değer", "en": "Requested value"},
    "phenotype": {"tr": "Fenotip", "en": "Phenotype"},
    "observation_state": {"tr": "Gözlem durumu", "en": "Observation state"},
    "rule": {"tr": "Kural", "en": "Rule"},
    "rule_version": {"tr": "Kural sürümü", "en": "Rule version"},
    "rule_content_hash": {"tr": "Kural içerik özeti",
                          "en": "Rule content digest"},
    "rationale_reference": {"tr": "Gerekçe referansı",
                            "en": "Rationale reference"},
    "curation_revision": {"tr": "Küratörlük revizyonu",
                          "en": "Curation revision"},
    "effect_code": {"tr": "Etki kodu", "en": "Effect code"},
    "explanation_code": {"tr": "Açıklama kodu", "en": "Explanation code"},
    "evidence": {"tr": "Kanıt referansları", "en": "Evidence references"},
    "conflict": {"tr": "Çelişki referansları", "en": "Conflict references"},
    "declaration": {"tr": "Kapsam beyanı", "en": "Coverage declaration"},
    "release": {"tr": "Sürüm", "en": "Release"},
    "ruleset": {"tr": "Kural kümesi", "en": "Ruleset"},
    "dataset": {"tr": "Veri kümesi", "en": "Dataset"},
    "evidence_build": {"tr": "Kanıt yapısı", "en": "Evidence build"},
    "coverage_manifest": {"tr": "Kapsam bildirimi",
                          "en": "Coverage manifest"},
    "protocol": {"tr": "Protokol", "en": "Protocol"},
    "source_policy": {"tr": "Kaynak politikası", "en": "Source policy"},
    "software": {"tr": "Yazılım", "en": "Software"},
    "pointer_generation": {"tr": "Etkin sürüm işaretçisi kuşağı",
                           "en": "Active pointer generation"},
    "input_hash": {"tr": "Girdi özeti", "en": "Input digest"},
    "output_hash": {"tr": "Çıktı özeti", "en": "Output digest"},
    "coverage_result_hash": {"tr": "Kapsam sonucu özeti",
                             "en": "Coverage result digest"},
    "canonical_result_hash": {"tr": "Kanonik sonuç özeti",
                              "en": "Canonical result digest"},
    "report_hash": {"tr": "Rapor özeti", "en": "Report digest"},
    "report_schema_version": {"tr": "Rapor şeması sürümü",
                              "en": "Report schema version"},
    "template_version": {"tr": "Şablon sürümü", "en": "Template version"},
    "locale": {"tr": "Dil", "en": "Locale"},
    "engine_contract_version": {"tr": "Motor sözleşmesi sürümü",
                                "en": "Engine contract version"},
    "value": {"tr": "Değer", "en": "Value"},
    "field": {"tr": "Alan", "en": "Field"},
    "subject": {"tr": "Konu", "en": "Subject"},
    "kind": {"tr": "Tür", "en": "Kind"},
    "statement": {"tr": "Açıklama", "en": "Statement"},
    "codes": {"tr": "Kodlar", "en": "Codes"},
    "references": {"tr": "Referanslar", "en": "References"},
    "answer": {"tr": "Yanıt", "en": "Answer"},
    "none_recorded": {"tr": "kayıt yok", "en": "none recorded"},
}

#: The eight questions every medication section must answer. Published as
#: data, and asserted section by section, because "the section looks complete"
#: is not a property anybody can check twice the same way.
MEDICATION_QUESTIONS: Tuple[Tuple[str, Mapping[str, str]], ...] = (
    ("which_medication",
     {"tr": "Hangi ilaç değerlendirildi?",
      "en": "Which medication was assessed?"}),
    ("attention_level",
     {"tr": "Hesaplanan dikkat düzeyi nedir?",
      "en": "What is the calculated attention level?"}),
    ("coverage",
     {"tr": "Kapsam nedir; hangi eksenler değerlendirildi?",
      "en": "What is the coverage, and which axes were evaluated?"}),
    ("not_assessed",
     {"tr": "Neler değerlendirilmedi ve neden?",
      "en": "What was not assessed, and why?"}),
    ("rules",
     {"tr": "Her bulguyu hangi yönetilen kural üretti?",
      "en": "Which governed rule produced each finding?"}),
    ("evidence",
     {"tr": "Her bulgunun arkasında hangi kanıt kayıtları var?",
      "en": "Which evidence records stand behind each finding?"}),
    ("versions",
     {"tr": "Hangi sürüm, kural kümesi ve veri kümesi kullanıldı?",
      "en": "Which release, ruleset and dataset were used?"}),
    ("limits",
     {"tr": "Bu bölümden ne çıkarılamaz?",
      "en": "What may not be concluded from this section?"}),
)


def require_locale(locale: str) -> str:
    """Return a supported locale code, or refuse.

    Nothing is translated on the fly, so an unsupported locale has no report
    to fall back to. Falling back to Turkish for a caller who asked for
    something else would hand a reader a document in a language they did not
    request and cannot necessarily read.
    """
    key = (locale or "").strip().lower()
    if key not in SUPPORTED_LOCALES:
        raise ReportRenderError(
            "locale %r has no controlled label set; supported: %s"
            % (locale, ", ".join(SUPPORTED_LOCALES)),
            code="REPORT_LOCALE_NOT_SUPPORTED", location="$.locale")
    return key


def require_template(template_version: str) -> str:
    """Return a template version this build ships, or refuse."""
    if template_version not in TEMPLATE_VERSIONS:
        raise ReportRenderError(
            "template version %r is not one this build ships; available: %s"
            % (template_version, ", ".join(TEMPLATE_VERSIONS)),
            code="REPORT_TEMPLATE_UNKNOWN", location="$.template_version")
    return template_version


def label(table: Mapping[str, Mapping[str, str]], code: str,
          locale: str, *, table_name: str = "label") -> str:
    """The controlled label for one governed code, or a refusal.

    Never returns the code as its own label. A report that silently displayed
    ``NO_VALIDATED_RULE_FOR_AXIS`` where a sentence belongs would be showing a
    reader a token whose meaning nobody wrote down, and it would look like a
    rendering choice rather than a missing translation.
    """
    key = require_locale(locale)
    entry = table.get(code)
    if entry is None or key not in entry:
        raise ReportRenderError(
            "no controlled %s for %r in locale %r; a label is never invented "
            "for a governed code" % (table_name, code, key),
            code="REPORT_LABEL_UNKNOWN", location="$.%s" % table_name,
            detail={"code": code, "locale": key})
    return entry[key]


def statement(key: str, locale: str) -> str:
    """One controlled sentence from the fixed table, or a refusal."""
    return label(CONTROLLED_STATEMENTS, key, locale,
                 table_name="controlled_statement")


def question_labels(locale: str) -> Dict[str, str]:
    """The eight medication questions in one locale."""
    key = require_locale(locale)
    return {identifier: text[key] for identifier, text in MEDICATION_QUESTIONS}


def template_contract() -> Dict[str, Any]:
    """The template's published rules, as one document."""
    return {
        "template_version": TEMPLATE_VERSION,
        "template_versions": list(TEMPLATE_VERSIONS),
        "default_locale": DEFAULT_LOCALE,
        "supported_locales": list(SUPPORTED_LOCALES),
        "medication_questions": [identifier
                                 for identifier, _text
                                 in MEDICATION_QUESTIONS],
        "never_localised": [
            "attention codes", "coverage codes", "coverage reason codes",
            "phenotypes", "rule identifiers", "rule versions",
            "evidence identifiers", "conflict identifiers",
            "release identifiers", "every hash",
        ],
        "note": ("Labels are looked up, never generated. A governed code with "
                 "no controlled label raises rather than being displayed as "
                 "itself, and every code is printed beside its label rather "
                 "than replaced by it."),
    }
