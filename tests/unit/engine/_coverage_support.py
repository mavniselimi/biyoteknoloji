# -*- coding: utf-8 -*-
"""Shared setup for the WP-13 tests.

One synthetic world, built once per test class that needs it: a frozen WP-11
ruleset on a temporary path, a verified coverage manifest over it, and helpers
for assembling requests against them.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from typing import Any, Mapping, Optional, Sequence

from pgx.engine.coverage import CoverageRequest, evaluate_coverage
from tests.fixtures.wp13.synthetic import (SYNTHETIC_DRUG_CATALOGUE,
                                           synthetic_evidence_resolver,
                                           synthetic_frozen_ruleset,
                                           synthetic_manifest,
                                           synthetic_profile)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
COVERAGE_ROOT = os.path.join(REPO_ROOT, "data", "coverage")
REGRESSION_REPORT = os.path.join(REPO_ROOT, "data", "migration", "wp13",
                                 "coverage-regression-report.json")
REGRESSION_ALLOWLIST = os.path.join(REPO_ROOT, "data", "migration", "wp13",
                                    "coverage-regression-allowlist.json")
GATE_STATUS = os.path.join(COVERAGE_ROOT, "wp13-real-gate-status.json")


class SyntheticWorld:
    """A frozen ruleset and a verified manifest over it, on a temp path."""

    def __init__(self, expected_extra_gene: bool = True, count: int = 2):
        self.tmp = tempfile.mkdtemp()
        destination = os.path.join(self.tmp, "rulesets",
                                   "PGX-RULESET-29991231-001")
        self.frozen, self.definitions = synthetic_frozen_ruleset(destination,
                                                                 count=count)
        self.resolver = synthetic_evidence_resolver()
        self.manifest = synthetic_manifest(
            self.frozen, expected_extra_gene=expected_extra_gene)

    def close(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def request(self, *, phenotypes: Optional[Mapping[str, Any]] = None,
                medications: Sequence[str] = (),
                manifest=None, frozen=None, conflicts=(),
                resolver: Any = "default",
                drug_catalogue: Sequence[str] = SYNTHETIC_DRUG_CATALOGUE
                ) -> CoverageRequest:
        return CoverageRequest(
            profile=synthetic_profile(phenotypes),
            medications=tuple(medications),
            manifest=manifest if manifest is not None else self.manifest,
            frozen_ruleset=frozen if frozen is not None else self.frozen,
            drug_catalogue=tuple(drug_catalogue),
            evidence_resolver=(self.resolver if resolver == "default"
                               else resolver),
            conflicts=tuple(conflicts))

    def evaluate(self, **kwargs):
        return evaluate_coverage(self.request(**kwargs))
