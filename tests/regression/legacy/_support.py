# -*- coding: utf-8 -*-
"""Shared test support for the WP-01 legacy regression suite.

Offline and stdlib only. Nothing here executes a network call, and nothing
writes into the repository: every legacy rerun goes to a TemporaryDirectory.
"""

from __future__ import annotations

import io
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
SCRIPTS_DIR = os.path.join(REPO_ROOT, "scripts")
BASELINE_DIR = os.path.join(REPO_ROOT, "data", "legacy-baseline")
SNAPSHOT_DIR = os.path.join(BASELINE_DIR, "snapshots")
MANIFEST_PATH = os.path.join(BASELINE_DIR, "manifest.json")
ALLOWLIST_PATH = os.path.join(BASELINE_DIR, "expected-differences.json")

for path in (REPO_ROOT, SCRIPTS_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)


def load_json(path):
    with io.open(path, encoding="utf-8") as handle:
        return json.load(handle)


def snapshot(name):
    return load_json(os.path.join(SNAPSHOT_DIR, name + ".json"))


def manifest():
    return load_json(MANIFEST_PATH)


REQUIRED_BASELINE_ARTIFACTS = (
    MANIFEST_PATH,
    ALLOWLIST_PATH,
    os.path.join(BASELINE_DIR, "reproduction-run-log.json"),
    os.path.join(SNAPSHOT_DIR, "current-active-seed.json"),
    os.path.join(SNAPSHOT_DIR, "original-cleaner-rebuild.json"),
    os.path.join(SNAPSHOT_DIR, "risk-p2-cyp2c19-poor.json"),
    os.path.join(SNAPSHOT_DIR, "alternative-beta-clopidogrel.json"),
    os.path.join(SNAPSHOT_DIR, "recorded-report-observation.json"),
    os.path.join(SNAPSHOT_DIR, "cli-contracts.json"),
)


def missing_baseline_artifacts():
    """Return required baseline artifacts that are absent."""
    return [os.path.relpath(p, REPO_ROOT).replace(os.sep, "/")
            for p in REQUIRED_BASELINE_ARTIFACTS if not os.path.exists(p)]


class BaselineRequiredMixin(object):
    """Fail loudly - never skip - when a required baseline artifact is absent.

    A missing manifest, allowlist or snapshot means the baseline was not built
    or was deleted. Skipping would let that pass as a green run.
    """

    @classmethod
    def require_baseline(cls):
        missing = missing_baseline_artifacts()
        if missing:
            raise AssertionError(
                "required WP-01 baseline artifact(s) missing: %s. "
                "Rebuild with: python3 scripts/build_legacy_baseline.py --repo-root ."
                % ", ".join(missing))

    def setUp(self):
        self.require_baseline()
        super(BaselineRequiredMixin, self).setUp()


#: Files WP-01 must leave byte-identical.
LEGACY_MODULES = (
    "clinpgx_probe.py", "clinpgx_probe_v2.py", "clean_mvp_seed_dataset.py",
    "risk_engine.py", "gemini_report_generator.py", "candidate_onboarding.py",
    "alternative_ranker.py",
)

WP00_FILES = (
    "docs/architecture/intended-purpose.md",
    "docs/risk-management/safety-contract.md",
    "pgx/__init__.py", "pgx/domain/__init__.py", "pgx/domain/claims.py",
    "tests/__init__.py", "tests/unit/__init__.py", "tests/unit/test_claims.py",
)

SEED_FILES = (
    "clinpgx_mvp_seed/supported_genes.csv",
    "clinpgx_mvp_seed/supported_drugs.csv",
    "clinpgx_mvp_seed/drug_gene_guidelines.csv",
    "clinpgx_mvp_seed/phenotype_effect_rules.csv",
    "clinpgx_mvp_seed/mvp_demo_profiles.json",
    "clinpgx_mvp_seed/mvp_seed_summary.json",
    "clinpgx_mvp_seed/supported_drugs.csv.bak",
    "clinpgx_mvp_seed/drug_gene_guidelines.csv.bak",
    "clinpgx_mvp_seed/phenotype_effect_rules.csv.bak",
)
