# -*- coding: utf-8 -*-
"""The committed WP-21 artifacts (WP-21).

Five documents plus six schemas, all deterministic functions of this
repository, so WP-19's reproducibility checker can build them twice and
compare bytes.

The one that matters is ``wp21-validation-report.json``. It is the real
current answer, and it contains no percentage: every metric in it is
``NOT_EXECUTED`` because no benchmark ran, in every partition. Producing that
document is a deliberate act - the code path that builds it
(:func:`build_real_report`) is separate from the one that computes metrics
from observations, so there is no way for an empty run to be mistaken for a
measured one.
"""

from __future__ import annotations

import io
import os
from typing import Any, Dict, Mapping, Optional

from pgx.validation.benchmark import BenchmarkEngine
from pgx.validation.benchmark_gate_status import build_wp21_gate_status
from pgx.validation.benchmark_report import (build_failure_path_document,
                                             build_metric_definitions_document,
                                             build_validation_report)
from pgx.validation.catalog import development_cases
from pgx.validation.dashboard_feed import build_dashboard_feed
from pgx.validation.metric_definitions import METRIC_IDS
from pgx.validation.separation import audit_partition
from pgx.validation.vocabulary import ValidationCaseRole

__all__ = [
    "DEFINITIONS_PATH",
    "DETERMINISTIC_ARTIFACT_PATHS",
    "FAILURE_PATHS_PATH",
    "FEED_PATH",
    "GATE_STATUS_PATH",
    "REPORT_PATH",
    "build_artifacts",
    "build_real_feed",
    "build_real_report",
    "write_document",
]

DEFINITIONS_PATH = "data/validation/wp21-metric-definitions.json"
FAILURE_PATHS_PATH = "data/validation/wp21-failure-path-catalogue.json"
REPORT_PATH = "data/validation/wp21-validation-report.json"
FEED_PATH = "data/validation/wp21-dashboard-feed.json"
GATE_STATUS_PATH = "data/validation/wp21-real-gate-status.json"

#: Everything a reproducibility check may rebuild and compare. The gate status
#: is excluded for the same reason WP-19 excludes its own: it reads the
#: environment, so two builds on different machines legitimately differ.
DETERMINISTIC_ARTIFACT_PATHS = (DEFINITIONS_PATH, FAILURE_PATHS_PATH,
                                REPORT_PATH, FEED_PATH)

_ROLES = (ValidationCaseRole.DEVELOPMENT,
          ValidationCaseRole.INTERNAL_HOLDOUT,
          ValidationCaseRole.EXPERT_HOLDOUT)


def _render(document: Mapping[str, Any], root: str) -> str:
    from pgx.verification.scrub import safe_render
    return safe_render(document, root)


def build_real_report(root: str) -> Dict[str, Any]:
    """The truthful current report: every metric NOT_EXECUTED, no percentage.

    Note what is *not* here: no call to :meth:`BenchmarkEngine.compute`. There
    are no observations to compute over, and running the metric engine on an
    empty list would produce a table of unavailable values that looks almost
    identical while meaning something different - "we ran and found nothing"
    rather than "nothing ran". The distinction is the point, so the two are
    built by different functions.
    """
    cases = development_cases(root)
    audit = audit_partition(cases)
    values = BenchmarkEngine.not_executed_values(
        _ROLES, METRIC_IDS,
        detail="no benchmark run exists: this repository has no active "
               "release, no holdout case and no reference judgment")
    gate = build_wp21_gate_status(root)
    counts = {
        ValidationCaseRole.DEVELOPMENT.value: audit.development_count,
        ValidationCaseRole.INTERNAL_HOLDOUT.value:
            audit.internal_holdout_count,
        ValidationCaseRole.EXPERT_HOLDOUT.value: audit.expert_holdout_count,
    }
    return build_validation_report(
        plan=None, values_by_role=values, case_counts=counts,
        observation_counts={role.value: None for role in _ROLES},
        separation_audit=audit.to_json(),
        blockers=[{"code": item["code"], "owner": item["owner"],
                   "detail": item["detail"]} for item in gate["blockers"]],
        benchmark_executed=False, active_release_available=False,
        generated_note=(
            "No benchmark has been executed. Every metric is NOT_EXECUTED "
            "rather than zero, and no partition carries a value. The seven "
            "development cases appear under DEVELOPMENT_REGRESSION and are "
            "not validation evidence. This document contains no percentage "
            "and no rate, because there is nothing to divide."))


def build_real_feed(root: str) -> Dict[str, Any]:
    return build_dashboard_feed(build_real_report(root))


def build_artifacts(root: str) -> Dict[str, str]:
    """Every deterministic artifact, rendered. WP-19's generator signature."""
    from pgx.application.benchmark_schema import build_schemas

    documents: Dict[str, str] = {
        DEFINITIONS_PATH: _render(build_metric_definitions_document(), root),
        FAILURE_PATHS_PATH: _render(build_failure_path_document(), root),
        REPORT_PATH: _render(build_real_report(root), root),
        FEED_PATH: _render(build_real_feed(root), root),
    }
    for relative, schema in build_schemas().items():
        documents[relative] = _render(schema, root)
    return documents


def write_document(root: str, relative: str,
                   document: Mapping[str, Any]) -> str:
    rendered = _render(document, root)
    path = os.path.join(root, *relative.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w", encoding="utf-8") as handle:
        handle.write(rendered)
    return rendered
