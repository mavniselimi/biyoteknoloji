#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the WP-01 legacy baseline: manifest, snapshots, expected differences.

Stdlib only. Every legacy rerun goes into a TemporaryDirectory; the active
``clinpgx_mvp_seed/`` is read but never written. No network call is made and
``GEMINI_API_KEY`` is stripped from every child process.

    python3 scripts/build_legacy_baseline.py --repo-root .

Network-only modules (``clinpgx_probe.py``, ``clinpgx_probe_v2.py``) are
deliberately not executed; they are recorded statically with reason code
``NETWORK_REQUIRED_NOT_EXECUTED``.
"""

from __future__ import annotations

import argparse
import ast
import datetime
import io
import json
import os
import platform
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from legacy_baseline_lib import (  # noqa: E402
    ARTIFACT_ROLES, ARTIFACT_TYPES, HASH_ALGORITHM, SCHEMA_VERSION,
    LegacyRunError, assert_not_live_seed, csv_row_count, dump_json,
    normalized_json_sha256, read_json, require_files, run_legacy, sha256_file,
    temp_workspace, to_repo_relative,
)
from legacy_bug_registry import (  # noqa: E402
    LEGACY_BUGS, REGISTRY_SCHEMA_VERSION, comparison_rules, expanded_rule_count,
)

BASELINE_DIR = "data/legacy-baseline"
SNAPSHOT_DIR = BASELINE_DIR + "/snapshots"

SEED = "clinpgx_mvp_seed"
SEED_CORE = ("supported_genes.csv", "supported_drugs.csv", "drug_gene_guidelines.csv",
             "phenotype_effect_rules.csv", "mvp_demo_profiles.json", "mvp_seed_summary.json")
SEED_BAKS = ("supported_drugs.csv.bak", "drug_gene_guidelines.csv.bak",
             "phenotype_effect_rules.csv.bak")

LEGACY_MODULES = ("clinpgx_probe.py", "clinpgx_probe_v2.py", "clean_mvp_seed_dataset.py",
                  "risk_engine.py", "gemini_report_generator.py",
                  "candidate_onboarding.py", "alternative_ranker.py")

NETWORK_ONLY_MODULES = ("clinpgx_probe.py", "clinpgx_probe_v2.py")

ARGPARSE_MODULES = ("clean_mvp_seed_dataset.py", "risk_engine.py",
                    "gemini_report_generator.py", "candidate_onboarding.py",
                    "alternative_ranker.py")

RISK_CASE_ARGS = ["--seed-dir", SEED, "--profile-id", "P2_cyp2c19_poor",
                  "--drugs", "clopidogrel,voriconazole,codeine,warfarin,amitriptyline"]
ALT_CASE_ARGS = ["--seed-dir", SEED, "--source-drug", "clopidogrel",
                 "--profile-id", "P2_cyp2c19_poor",
                 "--current-drugs", "clopidogrel,voriconazole,codeine,warfarin,amitriptyline",
                 "--candidate-file", "candidate_alternatives.csv",
                 "--graph-file", "drug_graph_edges.csv"]

#: Explicit, path-addressed normalisation. No blanket ignores: each entry names
#: the exact artifact and JSON key whose value is environment-dependent.
VOLATILE_FIELD_RULES = (
    {"artifact": "gemini_report_status.json", "json_path": "$.created_at",
     "reason": "wall-clock timestamp", "normalized_to": "<NORMALIZED:TIMESTAMP>"},
    {"artifact": "gemini_report_status.json", "json_path": "$.input_file",
     "reason": "absolute temporary path", "normalized_to": "<NORMALIZED:TEMP_PATH>"},
    {"artifact": "gemini_report_status.json", "json_path": "$.output_file",
     "reason": "absolute temporary path", "normalized_to": "<NORMALIZED:TEMP_PATH>"},
)


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def classify(rel_path):
    """Return (artifact_type, role) for a repo-relative path."""
    lower = rel_path.lower()
    if rel_path in LEGACY_MODULES:
        return "python_module", "legacy_module"
    if rel_path == "architecture.md":
        return "markdown_doc", "architecture_contract"
    if rel_path.startswith("docs/architecture/") or rel_path.startswith("docs/risk-management/"):
        return "markdown_doc", "wp00_governance_doc"
    if rel_path.startswith("pgx/"):
        return "python_module", "wp00_domain_code"
    if rel_path.startswith("tests/unit/") or rel_path == "tests/__init__.py":
        return "python_test", "wp00_test"
    if lower.endswith(".bak"):
        return "csv_dataset", "legacy_seed_backup"
    if rel_path.startswith("clinpgx_outputs/") or rel_path.startswith("clinpgx_outputs_v2/"):
        return ("json_output" if lower.endswith(".json") else "csv_output"), "legacy_raw_output"
    if rel_path.startswith(SEED + "/"):
        tail = rel_path[len(SEED) + 1:]
        if "/" in tail:
            if lower.endswith(".json"):
                return "json_output", "legacy_derived_output"
            if lower.endswith(".csv"):
                return "csv_output", "legacy_derived_output"
            return "markdown_report", "legacy_derived_output"
        return ("json_dataset" if lower.endswith(".json") else "csv_dataset"), "legacy_seed_dataset"
    if rel_path.startswith("final_report/"):
        if lower.endswith(".json"):
            return "json_output", "legacy_report_artifact"
        if lower.endswith(".txt"):
            return "text_output", "legacy_report_artifact"
        return "markdown_report", "legacy_report_artifact"
    if rel_path in ("candidate_alternatives.csv", "drug_graph_edges.csv"):
        return "csv_dataset", "legacy_candidate_seed"
    if rel_path == "MVP_1_TEKNIK_DURUM_RAPORU.md":
        return "markdown_doc", "legacy_historical_doc"
    return "text_output", "legacy_derived_output"


KNOWN_ISSUE_BY_PATH = {
    SEED + "/mvp_seed_summary.json": ["LEGACY-BUG-007"],
    SEED + "/supported_drugs.csv": ["LEGACY-BUG-007"],
    SEED + "/drug_gene_guidelines.csv": ["LEGACY-BUG-005", "LEGACY-BUG-007"],
    SEED + "/phenotype_effect_rules.csv": ["LEGACY-BUG-005", "LEGACY-BUG-006"],
    SEED + "/supported_drugs.csv.bak": ["LEGACY-BUG-010"],
    SEED + "/drug_gene_guidelines.csv.bak": ["LEGACY-BUG-010"],
    SEED + "/phenotype_effect_rules.csv.bak": ["LEGACY-BUG-010"],
    "clinpgx_outputs_v2/pair_annotation_rows.csv": ["LEGACY-BUG-004"],
    "clinpgx_outputs_v2/pair_probe_raw.json": ["LEGACY-BUG-004", "LEGACY-BUG-011"],
    "clinpgx_probe.py": ["LEGACY-BUG-011"],
    "clinpgx_probe_v2.py": ["LEGACY-BUG-004", "LEGACY-BUG-011"],
    "clean_mvp_seed_dataset.py": ["LEGACY-BUG-005", "LEGACY-BUG-006"],
    "risk_engine.py": ["LEGACY-BUG-001", "LEGACY-BUG-002", "LEGACY-BUG-003"],
    "gemini_report_generator.py": ["LEGACY-BUG-003", "LEGACY-BUG-012"],
    "candidate_onboarding.py": ["LEGACY-BUG-007", "LEGACY-BUG-010", "LEGACY-BUG-011"],
    "alternative_ranker.py": ["LEGACY-BUG-008", "LEGACY-BUG-009"],
    "final_report/gemini_report.md": ["LEGACY-BUG-012"],
    SEED + "/risk_outputs/risk_result_full.json": ["LEGACY-BUG-001", "LEGACY-BUG-002"],
    SEED + "/risk_outputs/gemini_input.json": ["LEGACY-BUG-003"],
    SEED + "/alternative_outputs_beta/alternative_result_full.json": [
        "LEGACY-BUG-008", "LEGACY-BUG-009"],
    SEED + "/alternative_outputs/alternative_result_full.json": [
        "LEGACY-BUG-008", "LEGACY-BUG-009"],
}

PROVENANCE_BY_PREFIX = (
    (SEED + "/", "Mutable legacy seed; mutated in place by candidate_onboarding.py --merge."),
    ("clinpgx_outputs_v2/", "Raw ClinPGx retrieval output from clinpgx_probe_v2.py (network run, not reproduced offline)."),
    ("clinpgx_outputs/", "First-generation ClinPGx exploration output; historical evidence only."),
    ("final_report/", "Recorded Gemini report artifacts; produced by an earlier run, not regenerated here."),
    ("docs/", "WP-00 governance document; DRAFT / AWAITING HUMAN AND SCIENTIFIC REVIEW."),
    ("pgx/", "WP-00 domain code; claims boundary contract."),
    ("tests/unit/", "WP-00 claim scanner tests."),
)


def provenance_for(rel_path):
    for prefix, note in PROVENANCE_BY_PREFIX:
        if rel_path.startswith(prefix):
            return note
    if rel_path in LEGACY_MODULES:
        return "Legacy executable module; frozen until its owning migration WP retires it."
    if rel_path == "architecture.md":
        return "Implementation source of truth; must not be modified by a work package."
    return "Legacy repository artifact captured by the WP-01 baseline."


MUTABLE_PATHS = {SEED + "/" + n for n in SEED_CORE} | {SEED + "/" + n for n in SEED_BAKS}


def collect_artifacts(repo_root):
    """Return the deterministic, repo-relative artifact list for the manifest."""
    include_dirs = ("clinpgx_outputs", "clinpgx_outputs_v2", SEED, "final_report",
                    "docs/architecture", "docs/risk-management", "pgx", "tests/unit")
    include_files = list(LEGACY_MODULES) + [
        "architecture.md", "candidate_alternatives.csv", "drug_graph_edges.csv",
        "MVP_1_TEKNIK_DURUM_RAPORU.md", "tests/__init__.py",
    ]
    found = []
    for name in include_files:
        if os.path.isfile(os.path.join(repo_root, name)):
            found.append(name)
    for directory in include_dirs:
        base = os.path.join(repo_root, directory)
        for root, dirs, files in os.walk(base):
            dirs[:] = sorted(d for d in dirs if d != "__pycache__")
            for fn in sorted(files):
                if fn.endswith((".pyc", ".pyo")) or fn == ".DS_Store":
                    continue
                found.append(to_repo_relative(os.path.join(root, fn), repo_root))

    artifacts = []
    for rel in sorted(set(found)):
        full = os.path.join(repo_root, rel)
        artifact_type, role = classify(rel)
        assert artifact_type in ARTIFACT_TYPES, rel
        assert role in ARTIFACT_ROLES, rel
        artifacts.append({
            "path": rel,
            "sha256": sha256_file(full),
            "size_bytes": os.path.getsize(full),
            "artifact_type": artifact_type,
            "role": role,
            "required": True,
            "mutable_legacy_state": rel in MUTABLE_PATHS,
            "provenance_note": provenance_for(rel),
            "known_issue_ids": KNOWN_ISSUE_BY_PATH.get(rel, []),
        })
    return artifacts


# ---------------------------------------------------------------------------
# Snapshot builders
# ---------------------------------------------------------------------------


def snapshot_active_seed(repo_root):
    """Read the live seed. Never writes; never regenerates."""
    require_files(repo_root, [SEED + "/" + n for n in SEED_CORE], "active seed snapshot")
    files = {}
    for name in SEED_CORE + SEED_BAKS:
        rel = SEED + "/" + name
        full = os.path.join(repo_root, rel)
        if not os.path.exists(full):
            files[name] = {"present": False}
            continue
        entry = {"present": True, "sha256": sha256_file(full),
                 "size_bytes": os.path.getsize(full)}
        if name.endswith(".csv") or name.endswith(".csv.bak"):
            entry["data_rows"] = csv_row_count(full)
        files[name] = entry

    summary = read_json(os.path.join(repo_root, SEED, "mvp_seed_summary.json"))
    counts = summary.get("counts", {})
    return {
        "snapshot_id": "current-active-seed",
        "snapshot_kind": "active_legacy_state",
        "not_a_validated_release": True,
        "description": (
            "Active mutable legacy seed as it exists on disk after candidate "
            "onboarding merged into it. This is legacy state evidence, not a "
            "validated dataset release."
        ),
        "active_counts": {
            "supported_genes": files["supported_genes.csv"]["data_rows"],
            "supported_drugs": files["supported_drugs.csv"]["data_rows"],
            "guideline_rows": files["drug_gene_guidelines.csv"]["data_rows"],
            "effect_rule_rows": files["phenotype_effect_rules.csv"]["data_rows"],
        },
        "stale_summary_counts": {
            "supported_genes": counts.get("supported_genes"),
            "supported_drugs": counts.get("supported_drugs"),
            "guideline_rows": counts.get("guideline_rows"),
            "effect_rule_rows": counts.get("effect_rule_rows"),
        },
        "stale_summary_issue": {
            "bug_id": "LEGACY-BUG-007",
            "protected_as_correct": False,
            "explanation": (
                "mvp_seed_summary.json still reports the pre-merge counts while the "
                "active CSV files hold the post-merge counts."
            ),
        },
        "backup_files_present": {n: files[n].get("present", False) for n in SEED_BAKS},
        "mutable_state_note": (
            "candidate_onboarding.py --merge rewrote supported_drugs.csv and "
            "drug_gene_guidelines.csv in place and copied the previous versions to "
            ".bak; a repeated merge would overwrite those backups (LEGACY-BUG-010)."
        ),
        "files": files,
    }


def snapshot_cleaner_rebuild(repo_root, log):
    """Re-run the original cleaner into a temporary directory only."""
    require_files(repo_root, ["clean_mvp_seed_dataset.py", "clinpgx_outputs_v2"],
                  "original cleaner reproduction")
    with temp_workspace("wp01-cleaner-") as tmp:
        assert_not_live_seed(tmp, repo_root)
        argv = ["clean_mvp_seed_dataset.py", "--input-dir", "clinpgx_outputs_v2",
                "--out-dir", tmp]
        started = utcnow()
        code, out, err = run_legacy(argv, cwd=repo_root)
        log.append({
            "step": "original-cleaner-rebuild", "started_at_utc": started,
            "command": "python3 clean_mvp_seed_dataset.py --input-dir clinpgx_outputs_v2 "
                       "--out-dir <TEMPORARY-DIRECTORY>",
            "working_directory_policy": "repository root",
            "exit_code": code, "network_used": False,
            "stdout_lines": len(out.splitlines()), "stderr_lines": len(err.splitlines()),
            "stderr_head": err.splitlines()[:3],
            "result": "PASS" if code == 0 else "FAIL",
        })
        if code != 0:
            raise LegacyRunError(
                "original cleaner failed with exit %d; stderr head: %s"
                % (code, " | ".join(err.splitlines()[:3]) or "(empty)")
            )
        produced = {}
        for name in SEED_CORE:
            path = os.path.join(tmp, name)
            if not os.path.exists(path):
                raise LegacyRunError(
                    "cleaner did not produce expected artifact: %s (produced: %s)"
                    % (name, ", ".join(sorted(os.listdir(tmp))))
                )
            entry = {"sha256": sha256_file(path), "size_bytes": os.path.getsize(path)}
            if name.endswith(".csv"):
                entry["data_rows"] = csv_row_count(path)
            active = os.path.join(repo_root, SEED, name)
            bak = active + ".bak"
            entry["matches_active_seed"] = (
                os.path.exists(active) and sha256_file(active) == entry["sha256"])
            entry["matches_seed_backup"] = (
                sha256_file(bak) == entry["sha256"] if os.path.exists(bak) else None)
            produced[name] = entry
        counts = read_json(os.path.join(tmp, "mvp_seed_summary.json")).get("counts", {})

    return {
        "snapshot_id": "original-cleaner-rebuild",
        "snapshot_kind": "legacy_reproducibility_evidence",
        "not_scientific_validation": True,
        "description": (
            "Deterministic rebuild of the ORIGINAL pre-merge seed from "
            "clinpgx_outputs_v2/ into a temporary directory. Counts prove legacy "
            "reproducibility only; they carry no claim of scientific correctness."
        ),
        "output_location_policy": "TemporaryDirectory; the active seed is never a target",
        "reproduced_counts": {
            "supported_genes": produced["supported_genes.csv"]["data_rows"],
            "supported_drugs": produced["supported_drugs.csv"]["data_rows"],
            "guideline_rows": produced["drug_gene_guidelines.csv"]["data_rows"],
            "effect_rule_rows": produced["phenotype_effect_rules.csv"]["data_rows"],
        },
        "expected_counts": {"supported_genes": 5, "supported_drugs": 11,
                            "guideline_rows": 30, "effect_rule_rows": 3084},
        "summary_counts_in_rebuild": counts,
        "differs_from_active_seed_in": sorted(
            n for n, v in produced.items() if v["matches_active_seed"] is False),
        "artifacts": produced,
        "interpretation": (
            "supported_drugs.csv and drug_gene_guidelines.csv differ from the active "
            "seed and match the .bak backups, which shows the merge changed exactly "
            "those two files. mvp_seed_summary.json matches the ACTIVE file, which is "
            "the direct proof of LEGACY-BUG-007: the summary was never regenerated "
            "after the merge."
        ),
    }


def snapshot_risk_case(repo_root, log):
    """Re-run the representative P2 CYP2C19-poor case into a temporary directory."""
    require_files(repo_root, ["risk_engine.py", SEED + "/supported_genes.csv",
                              SEED + "/mvp_demo_profiles.json"], "risk engine reproduction")
    with temp_workspace("wp01-risk-") as tmp:
        assert_not_live_seed(tmp, repo_root)
        argv = ["risk_engine.py"] + RISK_CASE_ARGS + ["--out-dir", tmp]
        started = utcnow()
        code, out, err = run_legacy(argv, cwd=repo_root)
        log.append({
            "step": "risk-p2-cyp2c19-poor", "started_at_utc": started,
            "command": "python3 risk_engine.py " + " ".join(RISK_CASE_ARGS)
                       + " --out-dir <TEMPORARY-DIRECTORY>",
            "working_directory_policy": "repository root",
            "exit_code": code, "network_used": False,
            "stdout_lines": len(out.splitlines()), "stderr_lines": len(err.splitlines()),
            "stderr_head": err.splitlines()[:3],
            "result": "PASS" if code == 0 else "FAIL",
        })
        if code != 0:
            raise LegacyRunError(
                "risk_engine failed with exit %d; stderr head: %s"
                % (code, " | ".join(err.splitlines()[:3]) or "(empty)"))
        expected = ("risk_result_full.json", "risk_findings.csv", "risk_report.md",
                    "gemini_input.json")
        missing = [n for n in expected if not os.path.exists(os.path.join(tmp, n))]
        if missing:
            raise LegacyRunError("risk_engine did not produce: %s" % ", ".join(missing))
        artifacts = {n: {"sha256": sha256_file(os.path.join(tmp, n)),
                         "size_bytes": os.path.getsize(os.path.join(tmp, n))}
                     for n in expected}
        result = read_json(os.path.join(tmp, "risk_result_full.json"))
        gemini_input = read_json(os.path.join(tmp, "gemini_input.json"))

    drug_results = []
    for entry in result.get("drug_results", []):
        findings = entry.get("findings", [])
        drug_results.append({
            "drug": entry.get("drug"),
            "status": entry.get("status"),
            "overall_risk_level": entry.get("overall_risk_level"),
            "overall_risk_label_tr": entry.get("overall_risk_label_tr"),
            "finding_count": len(findings),
            "active_flag_count": sum(
                1 for f in findings if f.get("status") == "risk_flag"),
            "finding_statuses": sorted({f.get("status") for f in findings if f.get("status")}),
            "genes": sorted({f.get("gene") for f in findings if f.get("gene")}),
        })

    full_keys = sorted(result["drug_results"][0]["findings"][0].keys())
    compact = gemini_input.get("drug_results", [])
    compact_keys = sorted(compact[0]["findings"][0].keys()) if compact and compact[0].get("findings") else []

    return {
        "snapshot_id": "risk-p2-cyp2c19-poor",
        "snapshot_kind": "historical_regression_seed",
        "not_clinical_validation": True,
        "contains_known_legacy_defects": True,
        "description": (
            "Offline rerun of the recorded P2 CYP2C19-poor demonstration. This is a "
            "historical regression seed that reproduces legacy behaviour INCLUDING "
            "known defects (LEGACY-BUG-001/002/003). It is not clinical validation and "
            "its values are not protected expected results."
        ),
        "case": {
            "profile_id": "P2_cyp2c19_poor",
            "profile_name": result.get("profile", {}).get("profile_name"),
            "phenotypes": result.get("profile", {}).get("phenotypes"),
            "selected_drugs": result.get("selected_drugs"),
        },
        "overall": {
            "overall_risk_level": result.get("overall_risk_level"),
            "overall_risk_label_tr": result.get("overall_risk_label_tr"),
            "overall_risk_score": result.get("overall_risk_score"),
            "risk_flag_count": result.get("risk_flag_count"),
            "same_gene_attention_count": len(result.get("same_gene_attention", [])),
        },
        "drug_results": drug_results,
        "legacy_clinical_warning_text": result.get("clinical_warning"),
        "legacy_warning_note": (
            "Recorded verbatim as legacy evidence. This is NOT the canonical warning; "
            "the canonical text lives in pgx/domain/claims.py."
        ),
        "full_finding_keys": full_keys,
        "gemini_input_compact_finding_keys": compact_keys,
        "dropped_keys_in_compact_payload": sorted(set(full_keys) - set(compact_keys)),
        "artifacts": artifacts,
        "determinism": "byte-identical across repeated runs on the same seed",
    }


def snapshot_alternative_beta(repo_root, log):
    """Re-run the clopidogrel candidate comparison into a temporary directory."""
    require_files(repo_root, ["alternative_ranker.py", "candidate_alternatives.csv",
                              "drug_graph_edges.csv"], "alternative ranker reproduction")
    with temp_workspace("wp01-alt-") as tmp:
        assert_not_live_seed(tmp, repo_root)
        argv = ["alternative_ranker.py"] + ALT_CASE_ARGS + ["--out-dir", tmp]
        started = utcnow()
        code, out, err = run_legacy(argv, cwd=repo_root)
        log.append({
            "step": "alternative-beta-clopidogrel", "started_at_utc": started,
            "command": "python3 alternative_ranker.py " + " ".join(ALT_CASE_ARGS)
                       + " --out-dir <TEMPORARY-DIRECTORY>",
            "working_directory_policy": "repository root",
            "exit_code": code, "network_used": False,
            "stdout_lines": len(out.splitlines()), "stderr_lines": len(err.splitlines()),
            "stderr_head": err.splitlines()[:3],
            "result": "PASS" if code == 0 else "FAIL",
        })
        if code != 0:
            raise LegacyRunError(
                "alternative_ranker failed with exit %d; stderr head: %s"
                % (code, " | ".join(err.splitlines()[:3]) or "(empty)"))
        expected = ("alternative_result_full.json", "alternative_candidates.csv",
                    "alternative_report.md")
        missing = [n for n in expected if not os.path.exists(os.path.join(tmp, n))]
        if missing:
            raise LegacyRunError("alternative_ranker did not produce: %s" % ", ".join(missing))
        artifacts = {n: {"sha256": sha256_file(os.path.join(tmp, n)),
                         "size_bytes": os.path.getsize(os.path.join(tmp, n))}
                     for n in expected}
        result = read_json(os.path.join(tmp, "alternative_result_full.json"))

    candidates = []
    for entry in result.get("candidate_results", []):
        candidates.append({
            "candidate_drug": entry.get("candidate_drug"),
            "mvp_data_status": entry.get("mvp_data_status"),
            "candidate_specific_risk_level": entry.get("candidate_specific_risk_level"),
            "legacy_score_unprotected": entry.get("score"),
        })
    return {
        "snapshot_id": "alternative-beta-clopidogrel",
        "snapshot_kind": "historical_regression_seed",
        "not_clinical_validation": True,
        "contains_known_legacy_defects": True,
        "description": (
            "Offline rerun of the MVP-2 beta candidate comparison for clopidogrel "
            "under the P2 CYP2C19-poor profile. Recorded as legacy behaviour only."
        ),
        "source_drug": result.get("source_drug"),
        "profile_id": result.get("profile_id"),
        "candidate_results": candidates,
        "legacy_score_name": result.get("score_name"),
        "score_disposition": {
            "bug_id": "LEGACY-BUG-009",
            "protected_as_correct": False,
            "explanation": (
                "Both candidates report mvp_data_status='insufficient_pgx_rule_data' "
                "yet still receive a numeric score. The score is a known defect that "
                "V2 removes; it is NOT a protected expected scientific result and no "
                "safety or preference conclusion may be drawn from it."
            ),
        },
        "graph_disposition": {
            "bug_id": "LEGACY-BUG-008",
            "protected_as_correct": False,
            "explanation": "The 'graph' is a flat CSV lookup, not a traversal.",
        },
        "no_candidate_preference_claim": (
            "This snapshot records data availability only. It asserts nothing about "
            "which candidate is safer, preferred, or suitable (SAFETY-INV-005)."
        ),
        "legacy_safety_notice_text": result.get("safety_notice"),
        "artifacts": artifacts,
    }


def snapshot_recorded_report(repo_root, log):
    """Hash the recorded final_report/ artifacts and observe an offline fallback."""
    recorded = {}
    for name in ("gemini_prompt.txt", "gemini_report.md", "gemini_report_payload.json",
                 "gemini_report_status.json"):
        rel = "final_report/" + name
        full = os.path.join(repo_root, rel)
        recorded[name] = ({"present": True, "sha256": sha256_file(full),
                           "size_bytes": os.path.getsize(full)}
                          if os.path.exists(full) else {"present": False})

    fallback = {"executed": False, "reason_code": "NOT_ATTEMPTED"}
    risk_input = os.path.join(repo_root, SEED, "risk_outputs", "gemini_input.json")
    if os.path.exists(os.path.join(repo_root, "gemini_report_generator.py")) and \
            os.path.exists(risk_input):
        with temp_workspace("wp01-gemini-") as tmp:
            assert_not_live_seed(tmp, repo_root)
            argv = ["gemini_report_generator.py", "--input",
                    os.path.join(SEED, "risk_outputs", "gemini_input.json"),
                    "--no-api", "--out-dir", tmp]
            started = utcnow()
            code, out, err = run_legacy(argv, cwd=repo_root)
            log.append({
                "step": "recorded-report-observation", "started_at_utc": started,
                "command": "python3 gemini_report_generator.py --input "
                           "clinpgx_mvp_seed/risk_outputs/gemini_input.json --no-api "
                           "--out-dir <TEMPORARY-DIRECTORY>",
                "working_directory_policy": "repository root; GEMINI_API_KEY stripped",
                "exit_code": code, "network_used": False,
                "stdout_lines": len(out.splitlines()), "stderr_lines": len(err.splitlines()),
                "stderr_head": err.splitlines()[:3],
                "result": "PASS" if code == 0 else "FAIL",
            })
            if code == 0:
                produced = sorted(os.listdir(tmp))
                artifacts = {}
                normalized = None
                for name in produced:
                    full = os.path.join(tmp, name)
                    if name == "gemini_report_status.json":
                        document = read_json(full)
                        digest, applied, norm_doc = normalized_json_sha256(
                            document, VOLATILE_FIELD_RULES)
                        normalized = norm_doc
                        artifacts[name] = {
                            "raw_sha256": sha256_file(full),
                            "normalized_sha256": digest,
                            "size_bytes": os.path.getsize(full),
                            "normalized_json_paths": applied,
                            "hashing": "normalized_canonical_json",
                        }
                    else:
                        artifacts[name] = {
                            "sha256": sha256_file(full),
                            "size_bytes": os.path.getsize(full),
                            "hashing": "raw_bytes",
                        }
                fallback = {
                    "executed": True,
                    "reason_code": "OFFLINE_FALLBACK_ONLY",
                    "api_key_supplied": False,
                    "network_used": False,
                    "produced": produced,
                    "artifacts": artifacts,
                    "status_non_volatile_fields": {
                        "used_api": (normalized or {}).get("used_api"),
                        "fallback_used": (normalized or {}).get("fallback_used"),
                        "validation_warnings": (normalized or {}).get("validation_warnings"),
                        "metadata": (normalized or {}).get("metadata"),
                    },
                    "normalization_note": (
                        "gemini_report_status.json is hashed AFTER normalising the "
                        "three documented volatile fields. It is not excluded from "
                        "hashing: a change to used_api, fallback_used, "
                        "validation_warnings or metadata changes the recorded hash."
                    ),
                }
            else:
                fallback = {"executed": False, "reason_code": "FALLBACK_RUN_FAILED",
                            "exit_code": code}

    return {
        "snapshot_id": "recorded-report-observation",
        "snapshot_kind": "legacy_report_evidence",
        "no_api_call_made": True,
        "description": (
            "Hashes of the previously recorded Gemini report artifacts, plus an "
            "offline --no-api fallback observation. No Gemini or other LLM API was "
            "called and GEMINI_API_KEY was stripped from the child environment."
        ),
        "recorded_artifacts": recorded,
        "offline_fallback_observation": fallback,
        "volatile_field_rules": list(VOLATILE_FIELD_RULES),
        "volatile_policy": (
            "Only the exact artifact+JSON key pairs listed in volatile_field_rules are "
            "normalised. No wildcard, subtree, or 'all text' ignore is used."
        ),
        "legacy_warning_variants_note": (
            "The recorded report carries legacy warning wording. It is preserved as "
            "legacy evidence and is explicitly NOT the canonical warning; the canonical "
            "text lives in pgx/domain/claims.py (WP-00)."
        ),
        "known_issue_ids": ["LEGACY-BUG-003", "LEGACY-BUG-012"],
    }


def snapshot_cli_contracts(repo_root, log):
    """Capture --help for offline-safe scripts; statically inspect network-only ones."""
    contracts = {}
    for name in ARGPARSE_MODULES:
        if not os.path.exists(os.path.join(repo_root, name)):
            contracts[name] = {"status": "MISSING_MODULE", "reason_code": "FILE_NOT_FOUND"}
            continue
        started = utcnow()
        code, out, err = run_legacy([name, "--help"], cwd=repo_root, timeout=60)
        text = out if out.strip() else err
        options = sorted({tok.split("=")[0].rstrip(",")
                          for tok in text.replace(",", " ").split()
                          if tok.startswith("--")})
        contracts[name] = {
            "status": "CAPTURED" if code == 0 else "HELP_FAILED",
            "reason_code": "OFFLINE_HELP_OK" if code == 0 else "HELP_EXIT_%d" % code,
            "exit_code": code,
            "help_line_count": len(text.splitlines()),
            "help_sha256": __import__("hashlib").sha256(text.encode("utf-8")).hexdigest(),
            "declared_options": options,
            "network_used": False,
        }
        log.append({
            "step": "cli-contract:" + name, "started_at_utc": started,
            "command": "python3 %s --help" % name,
            "working_directory_policy": "repository root",
            "exit_code": code, "network_used": False,
            "stdout_lines": len(out.splitlines()), "stderr_lines": len(err.splitlines()),
            "stderr_head": err.splitlines()[:3],
            "result": "PASS" if code == 0 else "FAIL",
        })

    for name in NETWORK_ONLY_MODULES:
        full = os.path.join(repo_root, name)
        if not os.path.exists(full):
            contracts[name] = {"status": "MISSING_MODULE", "reason_code": "FILE_NOT_FOUND"}
            continue
        with io.open(full, encoding="utf-8") as handle:
            source = handle.read()
        tree = ast.parse(source, filename=name)
        top_imports = sorted({a.name.split(".")[0]
                              for n in ast.walk(tree) if isinstance(n, ast.Import)
                              for a in n.names})
        funcs = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
        has_main_guard = any(
            isinstance(n, ast.If) and "__main__" in ast.dump(n.test) for n in tree.body)
        urls = sorted({n.value for n in ast.walk(tree)
                       if isinstance(n, ast.Constant) and isinstance(n.value, str)
                       and n.value.startswith("https://")})
        outputs = sorted({n.value for n in ast.walk(tree)
                          if isinstance(n, ast.Constant) and isinstance(n.value, str)
                          and (n.value.endswith(".json") or n.value.endswith(".csv"))
                          and not n.value.startswith("http")})
        contracts[name] = {
            "status": "NOT_EXECUTED",
            "reason_code": "NETWORK_REQUIRED_NOT_EXECUTED",
            "reason": (
                "Module performs live ClinPGx HTTP retrieval and requires the "
                "third-party 'requests' package; executing it would make a network "
                "call, which WP-01 forbids."
            ),
            "has_main_entrypoint": has_main_guard,
            "main_function_present": "main" in funcs,
            "cli_argument_mechanism": "argparse" if "argparse" in top_imports
                                      else "none (hardcoded constants)",
            "third_party_imports": [i for i in top_imports
                                    if i in ("requests", "httpx", "urllib3", "pandas")],
            "network_base_urls": urls,
            "expected_output_filenames": outputs,
            "network_used": False,
        }
        log.append({
            "step": "cli-contract:" + name, "started_at_utc": utcnow(),
            "command": "(not executed)",
            "working_directory_policy": "n/a",
            "exit_code": None, "network_used": False,
            "stdout_lines": 0, "stderr_lines": 0, "stderr_head": [],
            "result": "BLOCKED", "reason_code": "NETWORK_REQUIRED_NOT_EXECUTED",
        })

    return {
        "snapshot_id": "cli-contracts",
        "snapshot_kind": "legacy_interface_contract",
        "description": (
            "CLI surface of the legacy modules. --help is captured for offline-safe "
            "argparse modules; network-only probes are inspected statically."
        ),
        "not_executed_is_not_a_failure": (
            "A module recorded as NETWORK_REQUIRED_NOT_EXECUTED is a deliberate WP-01 "
            "boundary, not a baseline failure."
        ),
        "modules": contracts,
    }


# ---------------------------------------------------------------------------
# Manifest and expected differences
# ---------------------------------------------------------------------------


def _git(repo_root, *args, **kwargs):
    try:
        return subprocess.run(["git"] + list(args), cwd=repo_root,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return None


def git_checkpoint_state(repo_root):
    """Describe the local Git checkpoint using read-only observations only.

    This function never writes into ``.git`` and never attempts an unlink
    experiment. It reports only what it can observe:

    * ``GIT_NOT_AVAILABLE`` / ``NOT_A_GIT_REPOSITORY`` - from git itself;
    * ``GIT_IDENTITY_NOT_CONFIGURED`` - ``git config --get`` returns nothing;
    * ``NO_COMMIT_ON_BRANCH`` - ``git rev-parse HEAD`` fails;
    * ``GIT_METADATA_WRITE_NOT_AUTHORIZED`` - a stale ``.git/index.lock``
      exists while no git process holds it, which means a previous git write
      could not finalise. This is an observation about this environment's
      authorisation to modify ``.git`` metadata. It is **not** a claim about
      the filesystem or the mount: ordinary repository files in this working
      tree are created and rewritten normally.

    WP-01 never invents a Git identity and never touches global config.
    """
    state = {"git_available": False, "is_repository": False, "branch": None,
             "commit": None, "checkpoint_status": "BLOCKED", "blocked_reasons": [],
             "observations": {}}

    version = _git(repo_root, "--version")
    if version is None or version.returncode != 0:
        state["blocked_reasons"].append("GIT_NOT_AVAILABLE")
        return state
    state["git_available"] = True

    inside = _git(repo_root, "rev-parse", "--is-inside-work-tree")
    if inside is None or inside.returncode != 0:
        state["blocked_reasons"].append("NOT_A_GIT_REPOSITORY")
        return state
    state["is_repository"] = True

    head = _git(repo_root, "symbolic-ref", "--short", "HEAD")
    if head is not None and head.returncode == 0:
        state["branch"] = head.stdout.decode().strip()

    name = _git(repo_root, "config", "--get", "user.name")
    email = _git(repo_root, "config", "--get", "user.email")
    identity_configured = bool(
        name and name.returncode == 0 and name.stdout.strip()
        and email and email.returncode == 0 and email.stdout.strip())
    state["observations"]["identity_configured"] = identity_configured
    if not identity_configured:
        state["blocked_reasons"].append("GIT_IDENTITY_NOT_CONFIGURED")

    # Read-only observation: a stale lock means a prior git write did not
    # finalise. No probe file is written and no unlink is attempted.
    lock_path = os.path.join(repo_root, ".git", "index.lock")
    stale_lock = os.path.exists(lock_path)
    state["observations"]["stale_index_lock_present"] = stale_lock
    if stale_lock:
        state["observations"]["stale_index_lock_path"] = ".git/index.lock"
        state["blocked_reasons"].append("GIT_METADATA_WRITE_NOT_AUTHORIZED")

    rev = _git(repo_root, "rev-parse", "HEAD")
    if rev is not None and rev.returncode == 0:
        state["commit"] = rev.stdout.decode().strip()
    else:
        state["blocked_reasons"].append("NO_COMMIT_ON_BRANCH")

    state["blocked_reasons"] = sorted(set(state["blocked_reasons"]))
    state["checkpoint_status"] = "BLOCKED" if state["blocked_reasons"] else "PASS"
    state["scope_note"] = (
        "These reasons describe Git checkpoint authorisation in this session. "
        "They are not a claim about filesystem or mount capabilities: ordinary "
        "repository files are created and rewritten normally in this working tree."
    )
    return state


def build_expected_differences():
    """Expected-difference allowlist derived strictly from the bug registry.

    Each affected entity gets its own rule with an exact ``artifact_id`` and an
    identity-addressed selector, so a reordered list can never move one bug's
    expectation onto a different entity.
    """
    entries = []
    for bug in LEGACY_BUGS:
        rules = comparison_rules(bug)
        common = {
            "bug_id": bug["bug_id"],
            "title": bug["title"],
            "observed_legacy_behavior": bug["observed_legacy_behavior"],
            "required_v2_behavior": bug["required_v2_behavior"],
            "observable_artifacts": list(bug["observable_artifacts"]),
            "disposition": bug["disposition"],
            "protected_as_correct": bug["protected_as_correct"],
            "target_wp": bug["target_wp"],
            "rationale": bug["rationale"],
        }
        if not rules:
            entry = dict(common)
            entry.update({"rule_id": "XDIFF-" + bug["bug_id"], "artifact_id": None,
                          "comparison_selector": None, "scope_note": None,
                          "active": False})
            entries.append(entry)
            continue
        for rule in rules:
            entry = dict(common)
            entry.update({
                "rule_id": "XDIFF-%s-%s" % (bug["bug_id"], rule["suffix"]),
                "artifact_id": rule["artifact_id"],
                "comparison_selector": rule["selector"],
                "scope_note": rule["note"],
                "active": bug["disposition"] == "allowlisted_selector",
            })
            entries.append(entry)
    entries.sort(key=lambda e: e["rule_id"])
    return {
        "schema_version": REGISTRY_SCHEMA_VERSION,
        "policy": {
            "no_wildcard_paths": True,
            "no_whole_file_ignore": True,
            "no_whole_subtree_ignore": True,
            "no_blanket_text_acceptance": True,
            "every_entry_requires_a_known_bug_id": True,
            "unknown_bug_id_is_a_configuration_failure": True,
            "unused_entries_are_reported_not_silently_passed": True,
            "exact_artifact_identity_required": True,
            "no_basename_or_suffix_matching": True,
            "identity_addressed_list_selectors": True,
            "note": (
                "An entry with disposition 'registered_not_allowlisted' has no "
                "selector because no V2 artifact exists yet. WP-01 must not "
                "fabricate one; such an entry suppresses nothing. Active entries "
                "match one exact artifact_id and one exact selector; list items "
                "are addressed by identity (e.g. drug=codeine), never by index."
            ),
        },
        "known_bug_ids": [b["bug_id"] for b in LEGACY_BUGS],
        "active_rule_count": sum(1 for e in entries if e["active"]),
        "registry_rule_count": expanded_rule_count(),
        "entries": entries,
    }


#: WP-01's own evidence. Hashing these closes the chain: a silently edited
#: snapshot or allowlist must fail verification even without a Git commit.
EVIDENCE_SOURCES = (
    (SNAPSHOT_DIR, ".json", "baseline_snapshot"),
    (BASELINE_DIR, ".json", "baseline_registry"),
    ("scripts", ".py", "wp01_tooling"),
    ("tests/regression", ".py", "wp01_regression_test"),
    ("tests/regression/legacy", ".py", "wp01_regression_test"),
    ("tests/regression/legacy/fixtures", ".json", "wp01_regression_fixture"),
    ("docs/migration", ".md", "wp01_migration_doc"),
)


def collect_evidence_artifacts(repo_root, manifest_rel):
    """Hash WP-01's own outputs. The manifest never hashes itself."""
    seen = {}
    for directory, suffix, role in EVIDENCE_SOURCES:
        base = os.path.join(repo_root, directory)
        if not os.path.isdir(base):
            continue
        for name in sorted(os.listdir(base)):
            full = os.path.join(base, name)
            if not os.path.isfile(full) or not name.endswith(suffix):
                continue
            rel = to_repo_relative(full, repo_root)
            if rel == manifest_rel or rel in seen:
                continue
            seen[rel] = {
                "path": rel,
                "sha256": sha256_file(full),
                "size_bytes": os.path.getsize(full),
                "evidence_role": role,
                "required": True,
            }
    return [seen[k] for k in sorted(seen)]


_GIT_STATE = {}


def build_manifest(repo_root, artifacts, evidence, active, rebuild):
    global _GIT_STATE
    _GIT_STATE = git_checkpoint_state(repo_root)
    return {
        "schema_version": SCHEMA_VERSION,
        "baseline_id": "WP01-LEGACY-BASELINE-001",
        "captured_at_utc": utcnow(),
        "repository_root_policy": (
            "All artifact paths are repo-relative POSIX paths. Absolute paths, '..' "
            "traversal, and symlink escapes outside the repository are rejected."
        ),
        "git_commit": _GIT_STATE.get("commit"),
        "git_checkpoint": _GIT_STATE,
        "python_version": platform.python_version(),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        },
        "manifest_hash_algorithm": HASH_ALGORITHM,
        "manifest_excludes_itself": True,
        "wp00_approval_status": {
            "claim_boundary_status": "DRAFT / AWAITING HUMAN AND SCIENTIFIC REVIEW",
            "is_approved": False,
            "note": "WP-01 did not change and does not claim WP-00 approval.",
        },
        "baseline_facts": {
            "supported_genes": active["active_counts"]["supported_genes"],
            "active_supported_drugs": active["active_counts"]["supported_drugs"],
            "active_guideline_rows": active["active_counts"]["guideline_rows"],
            "active_effect_rule_rows": active["active_counts"]["effect_rule_rows"],
            "stale_mvp_seed_summary_supported_drugs":
                active["stale_summary_counts"]["supported_drugs"],
            "stale_mvp_seed_summary_guideline_rows":
                active["stale_summary_counts"]["guideline_rows"],
            "stale_summary_known_issue_id": "LEGACY-BUG-007",
            "original_cleaner_supported_drugs":
                rebuild["reproduced_counts"]["supported_drugs"],
            "original_cleaner_guideline_rows":
                rebuild["reproduced_counts"]["guideline_rows"],
            "original_cleaner_effect_rule_rows":
                rebuild["reproduced_counts"]["effect_rule_rows"],
            "original_cleaner_supported_genes":
                rebuild["reproduced_counts"]["supported_genes"],
            "facts_are_legacy_observations_only": (
                "These counts document current legacy behaviour. They are not "
                "scientific validation and not a protected expected V2 result."
            ),
        },
        "artifacts": artifacts,
        "evidence_artifacts": evidence,
        "evidence_policy": (
            "WP-01's own outputs (snapshots, allowlist, run log, tooling, "
            "regression tests and migration docs) are hashed here so the "
            "baseline is tamper-evident even before a Git commit exists. The "
            "manifest is written last and never hashes itself."
        ),
        "artifact_counts": {
            "legacy_and_wp00": len(artifacts),
            "wp01_evidence": len(evidence),
        },
        "legacy_bugs": [
            {"bug_id": b["bug_id"], "title": b["title"],
             "disposition": b["disposition"],
             "protected_as_correct": b["protected_as_correct"],
             "target_wp": b["target_wp"]}
            for b in LEGACY_BUGS
        ],
        "reproduction_cases": [
            {"case_id": "original-cleaner-rebuild",
             "snapshot": SNAPSHOT_DIR + "/original-cleaner-rebuild.json",
             "executed": True, "network_used": False,
             "output_location": "TemporaryDirectory"},
            {"case_id": "current-active-seed",
             "snapshot": SNAPSHOT_DIR + "/current-active-seed.json",
             "executed": False, "network_used": False,
             "output_location": "read-only inspection of the live seed"},
            {"case_id": "risk-p2-cyp2c19-poor",
             "snapshot": SNAPSHOT_DIR + "/risk-p2-cyp2c19-poor.json",
             "executed": True, "network_used": False,
             "output_location": "TemporaryDirectory"},
            {"case_id": "alternative-beta-clopidogrel",
             "snapshot": SNAPSHOT_DIR + "/alternative-beta-clopidogrel.json",
             "executed": True, "network_used": False,
             "output_location": "TemporaryDirectory"},
            {"case_id": "recorded-report-observation",
             "snapshot": SNAPSHOT_DIR + "/recorded-report-observation.json",
             "executed": True, "network_used": False,
             "output_location": "TemporaryDirectory (--no-api fallback only)"},
            {"case_id": "cli-contracts",
             "snapshot": SNAPSHOT_DIR + "/cli-contracts.json",
             "executed": True, "network_used": False,
             "output_location": "no artifacts written"},
            {"case_id": "clinpgx-probe-network-acquisition",
             "snapshot": None, "executed": False, "network_used": False,
             "reason_code": "NETWORK_REQUIRED_NOT_EXECUTED",
             "output_location": "n/a"},
            {"case_id": "candidate-onboarding-acquisition-and-merge",
             "snapshot": None, "executed": False, "network_used": False,
             "reason_code": "NETWORK_AND_MUTATION_FORBIDDEN_NOT_EXECUTED",
             "output_location": "n/a"},
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the WP-01 legacy baseline.")
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args(argv)
    repo_root = os.path.realpath(args.repo_root)

    log = []
    os.makedirs(os.path.join(repo_root, SNAPSHOT_DIR), exist_ok=True)

    active = snapshot_active_seed(repo_root)
    rebuild = snapshot_cleaner_rebuild(repo_root, log)
    risk = snapshot_risk_case(repo_root, log)
    alternative = snapshot_alternative_beta(repo_root, log)
    report = snapshot_recorded_report(repo_root, log)
    cli = snapshot_cli_contracts(repo_root, log)

    for name, payload in (
        ("current-active-seed", active),
        ("original-cleaner-rebuild", rebuild),
        ("risk-p2-cyp2c19-poor", risk),
        ("alternative-beta-clopidogrel", alternative),
        ("recorded-report-observation", report),
        ("cli-contracts", cli),
    ):
        dump_json(payload, os.path.join(repo_root, SNAPSHOT_DIR, name + ".json"))

    # Order matters: everything the manifest hashes must exist and be final
    # before the manifest itself is written.
    dump_json(build_expected_differences(),
              os.path.join(repo_root, BASELINE_DIR, "expected-differences.json"))
    dump_json({"schema_version": "wp01-run-log/1", "entries": log},
              os.path.join(repo_root, BASELINE_DIR, "reproduction-run-log.json"))

    artifacts = collect_artifacts(repo_root)
    manifest_rel = BASELINE_DIR + "/manifest.json"
    evidence = collect_evidence_artifacts(repo_root, manifest_rel)
    manifest = build_manifest(repo_root, artifacts, evidence, active, rebuild)
    dump_json(manifest, os.path.join(repo_root, manifest_rel))

    print("baseline_id: %s" % manifest["baseline_id"])
    print("artifacts:   %d legacy/WP-00, %d WP-01 evidence" % (len(artifacts), len(evidence)))
    print("legacy bugs: %d (all protected_as_correct=false)" % len(LEGACY_BUGS))
    print("run log:     %d steps" % len(log))
    print("allowlist:   %d concrete rules (%d active)" % (
        expanded_rule_count(),
        sum(1 for e in build_expected_differences()["entries"] if e["active"])))
    for key, value in sorted(manifest["baseline_facts"].items()):
        if isinstance(value, int):
            print("  %-46s %s" % (key, value))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except LegacyRunError as exc:
        sys.stderr.write("LEGACY_BASELINE_ERROR: %s\n" % exc)
        sys.exit(2)
