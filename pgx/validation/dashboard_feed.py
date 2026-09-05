# -*- coding: utf-8 -*-
"""The dashboard feed (WP-21): the only thing the web layer is allowed to read.

A deliberate narrowing. The web layer could import the benchmark engine and
render whatever it liked; instead it gets this - a flat, pre-checked, already
public document with no ports, no case set and no way to reach restricted
storage. The boundary is structural rather than a rule somebody remembers: a
request handler holding this document has nothing to leak.

Everything here comes from the public report and is re-checked by
:func:`~pgx.validation.benchmark_report.assert_public_report_is_safe` before
it is returned, so a field that slipped into the report is caught twice.

The feed carries display-ready shapes but not display text. Turkish and
English strings live in the web layer's label catalogue where every other
user-facing string lives; the feed carries codes and the page translates them.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

from pgx.domain.hashing import sha256_digest
from pgx.validation.benchmark import DEVELOPMENT_SECTION
from pgx.validation.benchmark_report import (assert_public_report_is_safe,
                                             REPORT_SCHEMA_VERSION)
from pgx.validation.metric_definitions import (METRIC_REGISTRY_VERSION,
                                               definitions_by_id)

__all__ = [
    "FEED_SCHEMA_VERSION",
    "build_dashboard_feed",
    "feed_digest",
]

FEED_SCHEMA_VERSION = "pgx-wp21-dashboard-feed/1"


def _row(metric: Mapping[str, Any],
         definitions: Mapping[str, Any]) -> Dict[str, Any]:
    """One table row. ``value`` stays a string or null - never coerced to 0.

    ``role`` is carried on the row as well as on the section. Redundant on
    purpose: a template that renders rows out of their section, or a reader
    inspecting the JSON, can still tell an EXPERT_HOLDOUT number from a
    DEVELOPMENT one without reconstructing the nesting.
    """
    metric_id = str(metric.get("metric_id"))
    definition = definitions.get(metric_id)
    status = str(metric.get("status"))
    row: Dict[str, Any] = {
        "metric_id": metric_id,
        "role": metric.get("role"),
        "label": "" if definition is None else definition.title,
        "kind": metric.get("kind"),
        "numerator": metric.get("numerator"),
        "denominator": metric.get("denominator"),
        "value": metric.get("value"),
        "status": status,
        "has_number": status == "AVAILABLE",
        "unavailable_reason": metric.get("unavailable_reason"),
        "is_validation_evidence": bool(metric.get("is_validation_evidence")),
    }
    # Present only where the metric is a distribution. An empty object on a
    # rate would invite a template to render "no categories" as a finding.
    if isinstance(metric.get("categories"), Mapping):
        row["categories"] = dict(metric["categories"])
    return row


def build_dashboard_feed(report: Mapping[str, Any]) -> Dict[str, Any]:
    """Turn a public validation report into the feed the page consumes.

    Refuses a report that is not the shape this function expects, rather than
    filling in defaults. A dashboard that rendered a partial feed as a
    complete one would present absence as measurement, which is the failure
    mode the whole work package is built around.
    """
    if str(report.get("report_schema_version")) != REPORT_SCHEMA_VERSION:
        raise ValueError(
            "dashboard feed expects a %s report; got %r"
            % (REPORT_SCHEMA_VERSION, report.get("report_schema_version")))
    assert_public_report_is_safe(report)
    definitions = definitions_by_id()

    sections: List[Dict[str, Any]] = []
    for partition in report.get("partitions", ()):
        metrics = [_row(metric, definitions)
                   for metric in partition.get("metrics", ())]
        sections.append({
            "section": partition.get("section"),
            "role": partition.get("role"),
            "is_validation_evidence": bool(
                partition.get("is_validation_evidence")),
            "is_development_regression":
                partition.get("section") == DEVELOPMENT_SECTION,
            "case_count": partition.get("case_count"),
            "observation_count": partition.get("observation_count"),
            "metric_count": len(metrics),
            "available_metric_count": sum(1 for row in metrics
                                          if row["has_number"]),
            "metrics": metrics,
        })

    pinned = report.get("pinned_release") or {}
    feed: Dict[str, Any] = {
        "feed_schema_version": FEED_SCHEMA_VERSION,
        "work_package": "WP-21",
        "metric_registry_version": METRIC_REGISTRY_VERSION,
        "metric_registry_digest": report.get("metric_registry_digest"),
        "benchmark_executed": bool(report.get("benchmark_executed")),
        "active_release_available": bool(
            report.get("active_release_available")),
        "release_public_id": pinned.get("release_public_id"),
        "release_manifest_hash": pinned.get("release_manifest_hash"),
        "dataset_public_id": pinned.get("dataset_public_id"),
        "ruleset_public_id": pinned.get("ruleset_public_id"),
        "software_version": pinned.get("software_version"),
        "plan_hash": report.get("plan_hash"),
        "run_scientific_digest": report.get("run_scientific_digest"),
        "report_digest": sha256_digest(report),
        "sections": sections,
        "combined_overall_metric": None,
        "numeric_validation_metric_count":
            report.get("numeric_validation_metric_count", 0),
        "clinical_validation_performed": False,
        "expert_review_performed": False,
        "blocker_count": report.get("blocker_count", 0),
        "blockers": [{"code": item.get("code"), "owner": item.get("owner")}
                     for item in report.get("blockers", ())],
    }
    assert_public_report_is_safe(feed)
    return feed


def feed_digest(feed: Mapping[str, Any]) -> str:
    return sha256_digest(feed)
