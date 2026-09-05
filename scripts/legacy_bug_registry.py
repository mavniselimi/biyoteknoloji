# -*- coding: utf-8 -*-
"""LEGACY-BUG-001..012 registry (WP-01, stdlib only, import-safe).

Source of truth: ``architecture.md`` section 4.4.

Every entry carries ``protected_as_correct = False``. A known legacy defect is
snapshotted so that a later V2 difference can be recognised as a *correction*,
never as a regression. Nothing in this file authorises a V2 output.

``disposition`` values:

* ``registered_not_allowlisted`` - the defect is recorded, but no V2 artifact
  exists yet, so there is no honest comparison selector. WP-01 must not invent
  one.
* ``allowlisted_selector`` - a concrete, narrow selector is defined and the
  difference is expected when the owning WP lands.
"""

from __future__ import annotations

REGISTRY_SCHEMA_VERSION = "wp01-legacy-bugs/1"

LEGACY_BUGS = (
    {
        "bug_id": "LEGACY-BUG-001",
        "title": "RAPID and ULTRARAPID implicitly match each other",
        "observed_legacy_behavior": (
            "risk_engine.py phenotype matching treats RAPID and ULTRARAPID as "
            "interchangeable, so a rule written for one phenotype can fire for the other."
        ),
        "required_v2_behavior": (
            "Exact phenotype matching. A rule applying to several phenotypes must "
            "encode an explicit set (architecture.md 9.1, SAFETY-INV-004)."
        ),
        "observable_artifacts": ["clinpgx_mvp_seed/risk_outputs/risk_result_full.json"],
        "comparison_rules": (),
        "disposition": "registered_not_allowlisted",
        "protected_as_correct": False,
        "target_wp": "WP-12",
        "rationale": (
            "The captured P2 CYP2C19-poor case uses POOR/NORMAL phenotypes and does "
            "not exercise the RAPID/ULTRARAPID path, so no selector can be observed "
            "from the WP-01 baseline without fabricating a case."
        ),
    },
    {
        "bug_id": "LEGACY-BUG-002",
        "title": "Missing / no-rule / unsupported drugs receive top-level risk 'none'",
        "observed_legacy_behavior": (
            "Reproduced in the WP-01 baseline: codeine and warfarin return "
            "overall_risk_level='none' with finding status "
            "'gene_drug_known_no_profile_match'. RISK_LABEL_TR renders 'none' as "
            "'Dusuk / uyari yok', conflating 'not assessed' with 'low'."
        ),
        "required_v2_behavior": (
            "Attention becomes NOT_ASSESSED; coverage and a machine-readable reason "
            "code are mandatory and separate (architecture.md 9.2/9.3, SAFETY-INV-001)."
        ),
        "observable_artifacts": [
            "data/legacy-baseline/snapshots/risk-p2-cyp2c19-poor.json",
        ],
        "comparison_rules": (
            {"suffix": "CODEINE",
             "artifact_id": "risk-p2-cyp2c19-poor.json",
             "selector": "$.drug_results[drug=codeine].overall_risk_level",
             "note": "codeine: legacy 'none' must become NOT_ASSESSED"},
            {"suffix": "WARFARIN",
             "artifact_id": "risk-p2-cyp2c19-poor.json",
             "selector": "$.drug_results[drug=warfarin].overall_risk_level",
             "note": "warfarin: legacy 'none' must become NOT_ASSESSED"},
        ),
        "disposition": "allowlisted_selector",
        "protected_as_correct": False,
        "target_wp": "WP-13/WP-14",
        "rationale": (
            "Directly observed in the WP-01 rerun. The legacy value 'none' is the "
            "defect itself and must change; it is recorded so the change is visible. Each affected drug has its own "
            "identity-addressed rule, so a reordered list cannot move the codeine "
            "expectation onto another drug."
        ),
    },
    {
        "bug_id": "LEGACY-BUG-003",
        "title": "Gemini compact payload drops status and missing-data reason",
        "observed_legacy_behavior": (
            "risk_engine.build_gemini_payload emits compact findings that omit the "
            "per-finding 'status' field, so the LLM input cannot distinguish "
            "'no active flag' from 'not assessed'."
        ),
        "required_v2_behavior": (
            "The structured report must preserve coverage, reason code, evidence, and "
            "version metadata (architecture.md 10.1, LEGACY-BUG-003)."
        ),
        "observable_artifacts": ["data/legacy-baseline/snapshots/risk-p2-cyp2c19-poor.json"],
        "comparison_rules": (
            {"suffix": "COMPACT-KEYS",
             "artifact_id": "risk-p2-cyp2c19-poor.json",
             "selector": "$.gemini_input_compact_finding_keys",
             "note": "the compact LLM payload drops per-finding status"},
        ),
        "disposition": "allowlisted_selector",
        "protected_as_correct": False,
        "target_wp": "WP-15",
        "rationale": (
            "The WP-01 snapshot records the compact key set next to the full key set, "
            "so the dropped fields are provable rather than asserted."
        ),
    },
    {
        "bug_id": "LEGACY-BUG-004",
        "title": "Pair endpoint case variants produce large duplicate sets",
        "observed_legacy_behavior": (
            "clinpgx_probe_v2.py issues case-variant pair queries whose results are "
            "concatenated, so clinpgx_outputs_v2/pair_annotation_rows.csv carries "
            "duplicate logical rows."
        ),
        "required_v2_behavior": (
            "Canonical dedup before rule construction; duplicates reported as data "
            "quality metrics (architecture.md 8.3)."
        ),
        "observable_artifacts": ["clinpgx_outputs_v2/pair_annotation_rows.csv"],
        "comparison_rules": (),
        "disposition": "registered_not_allowlisted",
        "protected_as_correct": False,
        "target_wp": "WP-07",
        "rationale": (
            "The duplicate set is an input-side artifact. A dedup selector belongs to "
            "the WP-07 canonicalisation output, which does not exist yet."
        ),
    },
    {
        "bug_id": "LEGACY-BUG-005",
        "title": "Pair-level guideline presence upgrades annotation rows to high_guideline_supported",
        "observed_legacy_behavior": (
            "clean_mvp_seed_dataset.py assigns evidence strength from the existence of "
            "a guideline for the drug-gene pair, so unrelated annotation rows inherit "
            "'high_guideline_supported'."
        ),
        "required_v2_behavior": (
            "Evidence strength belongs to the exact evidence/interpretation record, not "
            "to the pair (architecture.md 8.4, SAFETY-INV-006)."
        ),
        "observable_artifacts": ["clinpgx_mvp_seed/phenotype_effect_rules.csv"],
        "comparison_rules": (),
        "disposition": "registered_not_allowlisted",
        "protected_as_correct": False,
        "target_wp": "WP-08/WP-11",
        "rationale": (
            "Requires the V2 evidence/interpretation split to express a comparable "
            "field. No honest selector exists against the legacy CSV alone."
        ),
    },
    {
        "bug_id": "LEGACY-BUG-006",
        "title": "MANUAL_EFFECT_HINTS applies pair-level effect/severity broadly",
        "observed_legacy_behavior": (
            "clean_mvp_seed_dataset.py contains a hand-written MANUAL_EFFECT_HINTS map "
            "that is applied at pair level and lands in the seed with no curation "
            "record, reviewer, or approval state."
        ),
        "required_v2_behavior": (
            "Import as unapproved draft curation proposals; never auto-validate "
            "(architecture.md 4.4, SAFETY-INV-003)."
        ),
        "observable_artifacts": ["clinpgx_mvp_seed/phenotype_effect_rules.csv"],
        "comparison_rules": (),
        "disposition": "registered_not_allowlisted",
        "protected_as_correct": False,
        "target_wp": "WP-09/WP-10",
        "rationale": (
            "The V2 counterpart is a curation record with an approval state; there is "
            "no legacy field to compare it against."
        ),
    },
    {
        "bug_id": "LEGACY-BUG-007",
        "title": "Summary counts become stale after seed merge",
        "observed_legacy_behavior": (
            "Proven in the WP-01 baseline: clinpgx_mvp_seed/mvp_seed_summary.json is "
            "byte-identical to a freshly rebuilt pre-merge summary and still reports "
            "supported_drugs=11 / guideline_rows=30, while the active CSV files hold "
            "15 drugs and 36 guideline rows."
        ),
        "required_v2_behavior": (
            "V2 artifacts are immutable and counts are generated from the artifact "
            "manifest (architecture.md 4.4, SAFETY-INV-007)."
        ),
        "observable_artifacts": [
            "clinpgx_mvp_seed/mvp_seed_summary.json",
            "data/legacy-baseline/snapshots/current-active-seed.json",
        ],
        "comparison_rules": (
            {"suffix": "SUPPORTED-DRUGS",
             "artifact_id": "mvp_seed_summary.json",
             "selector": "$.counts.supported_drugs",
             "note": "stale 11 vs active 15"},
            {"suffix": "GUIDELINE-ROWS",
             "artifact_id": "mvp_seed_summary.json",
             "selector": "$.counts.guideline_rows",
             "note": "stale 30 vs active 36"},
        ),
        "disposition": "allowlisted_selector",
        "protected_as_correct": False,
        "target_wp": "WP-03/WP-06",
        "rationale": (
            "Directly measured. The stale 11/30 values must not be carried into V2 and "
            "must not be treated as an expected V2 output."
        ),
    },
    {
        "bug_id": "LEGACY-BUG-008",
        "title": "Candidate graph is manual lookup plus display context, not traversal",
        "observed_legacy_behavior": (
            "alternative_ranker.py reads drug_graph_edges.csv as a flat lookup table; "
            "no traversal is performed, yet the output is presented as graph-based."
        ),
        "required_v2_behavior": (
            "P1 must either implement real traversal or name the feature a manual "
            "lookup (architecture.md 4.4)."
        ),
        "observable_artifacts": [
            "data/legacy-baseline/snapshots/alternative-beta-clopidogrel.json",
        ],
        "comparison_rules": (),
        "disposition": "registered_not_allowlisted",
        "protected_as_correct": False,
        "target_wp": "P1-01/P1-02",
        "rationale": (
            "This is a naming and capability claim rather than a value difference; no "
            "field-level selector would be honest."
        ),
    },
    {
        "bug_id": "LEGACY-BUG-009",
        "title": "0-100 candidate score creates an unsupported evaluability/safety impression",
        "observed_legacy_behavior": (
            "Reproduced in the WP-01 baseline: prasugrel and ticagrelor both receive "
            "score=59 under score_name 'MVP alternatif uygunluk on skoru' while their "
            "mvp_data_status is 'insufficient_pgx_rule_data' - a numeric score attached "
            "to a candidate with no usable rule."
        ),
        "required_v2_behavior": (
            "The score is removed from V2 P0/P1; candidates show data status only "
            "(architecture.md 4.4, SAFETY-INV-005)."
        ),
        "observable_artifacts": [
            "data/legacy-baseline/snapshots/alternative-beta-clopidogrel.json",
        ],
        "comparison_rules": (
            {"suffix": "PRASUGREL-SCORE-REMOVAL",
             "artifact_id": "alternative-beta-clopidogrel.json",
             "selector": "$.candidate_results[candidate_drug=prasugrel]"
                         ".legacy_score_unprotected",
             "note": "prasugrel score must disappear in V2"},
            {"suffix": "TICAGRELOR-SCORE-REMOVAL",
             "artifact_id": "alternative-beta-clopidogrel.json",
             "selector": "$.candidate_results[candidate_drug=ticagrelor]"
                         ".legacy_score_unprotected",
             "note": "ticagrelor score must disappear in V2"},
        ),
        "disposition": "allowlisted_selector",
        "protected_as_correct": False,
        "target_wp": "P1-02",
        "rationale": (
            "The score's disappearance in V2 is an expected, required difference. It is "
            "explicitly NOT a protected scientific result. Prasugrel and ticagrelor each have their "
            "own identity-addressed rule."
        ),
    },
    {
        "bug_id": "LEGACY-BUG-010",
        "title": ".bak files are overwritten on repeated merge",
        "observed_legacy_behavior": (
            "candidate_onboarding.py --merge copies the current CSV to <name>.bak before "
            "writing. A second merge overwrites the only backup, so the pre-merge state "
            "is unrecoverable. Three .bak files exist today and are the sole surviving "
            "pre-merge evidence."
        ),
        "required_v2_behavior": (
            "No in-place mutation; activate a new immutable dataset/ruleset version "
            "(architecture.md 4.4, SAFETY-INV-007)."
        ),
        "observable_artifacts": [
            "clinpgx_mvp_seed/supported_drugs.csv.bak",
            "clinpgx_mvp_seed/drug_gene_guidelines.csv.bak",
            "clinpgx_mvp_seed/phenotype_effect_rules.csv.bak",
        ],
        "comparison_rules": (),
        "disposition": "registered_not_allowlisted",
        "protected_as_correct": False,
        "target_wp": "WP-03",
        "rationale": (
            "A destructive-write behaviour, not a value difference. WP-01 freezes the "
            "surviving .bak hashes so the pre-merge state cannot be lost again."
        ),
    },
    {
        "bug_id": "LEGACY-BUG-011",
        "title": "API acquisition lacks pagination, retry, provenance, and failure completeness",
        "observed_legacy_behavior": (
            "clinpgx_probe.py and clinpgx_probe_v2.py call https://api.clinpgx.org "
            "directly with a third-party 'requests' dependency, no recorded acquisition "
            "run, no retry policy, and no completeness assertion."
        ),
        "required_v2_behavior": (
            "A production adapter must record and verify a complete acquisition run "
            "(architecture.md 8.1, WP-04)."
        ),
        "observable_artifacts": ["clinpgx_outputs_v2/pair_probe_raw.json"],
        "comparison_rules": (),
        "disposition": "registered_not_allowlisted",
        "protected_as_correct": False,
        "target_wp": "WP-04",
        "rationale": (
            "The probes are network-only and were deliberately NOT executed in WP-01 "
            "(reason code NETWORK_REQUIRED_NOT_EXECUTED), so no run-level selector can "
            "be observed offline."
        ),
    },
    {
        "bug_id": "LEGACY-BUG-012",
        "title": "Report can surface dosage/replacement language from source summaries",
        "observed_legacy_behavior": (
            "gemini_report_generator.py passes guideline summary text through to the "
            "report, and its only guard is a substring check for 'klinik karar' / "
            "'doz onerisi' in the model output."
        ),
        "required_v2_behavior": (
            "Evidence may preserve source text, but user-facing summaries must remain "
            "neutral and claim-scanned (architecture.md 4.4, SAFETY-INV-010)."
        ),
        "observable_artifacts": [
            "final_report/gemini_report.md",
            "data/legacy-baseline/snapshots/recorded-report-observation.json",
        ],
        "comparison_rules": (),
        "disposition": "registered_not_allowlisted",
        "protected_as_correct": False,
        "target_wp": "WP-15/P1-06",
        "rationale": (
            "The WP-00 claim scanner exists, but no V2 report artifact exists to compare "
            "against. A selector would be fabricated."
        ),
    },
)


def bug_ids():
    """Return the ordered tuple of registered bug IDs."""
    return tuple(bug["bug_id"] for bug in LEGACY_BUGS)


def by_id(bug_id):
    """Return one registry entry, or raise KeyError."""
    for bug in LEGACY_BUGS:
        if bug["bug_id"] == bug_id:
            return bug
    raise KeyError(bug_id)


def comparison_rules(bug):
    """Return the exact comparison rules declared by a registry entry."""
    return tuple(bug.get("comparison_rules") or ())


def expanded_rule_count():
    """Total number of concrete allowlist rules the registry produces."""
    return sum(len(comparison_rules(b)) for b in LEGACY_BUGS)
