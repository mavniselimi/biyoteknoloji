# -*- coding: utf-8 -*-
"""The public validation report (WP-21): aggregates only, and why they are.

This is the artifact that leaves the building. It is committed, served to a
web page and quoted in evidence packs, so the design question is not "what
would be useful to include" but "what is safe to publish about cases whose
whole evidential value depends on nobody having seen them".

The answer: partition-level aggregates and nothing else.

Published: release identity and hashes, protocol and registry versions,
partition names, per-metric numerator, denominator, value, status and reason,
case counts, artifact hashes, blocker summaries.

Never published: any case identifier, any observation, any phenotype or
medication, any expected answer, any expert response, any filesystem path,
username, hostname or credential. :func:`assert_public_report_is_safe` walks
the finished document and refuses on any of them, so the guarantee is enforced
on the bytes rather than promised by the code that produced them.

Case-level execution evidence is a *separate restricted artifact*. This
repository has none, and that absence is reported rather than filled.
"""

from __future__ import annotations

import datetime as _dt
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from pgx.domain.hashing import sha256_digest
from pgx.validation.benchmark import DEVELOPMENT_SECTION
from pgx.validation.benchmark_models import BenchmarkPlan, BenchmarkRun
from pgx.validation.errors import ValidationDatasetError
from pgx.validation.metric_definitions import (FAILURE_PATH_CATALOGUE,
                                               FAILURE_PATH_CATALOGUE_VERSION,
                                               METRIC_DEFINITIONS,
                                               METRIC_REGISTRY_VERSION,
                                               MetricStatus,
                                               UNAVAILABLE_REASONS,
                                               registry_digest)
from pgx.validation.metrics import MetricValue
from pgx.validation.vocabulary import ValidationCaseRole

__all__ = [
    "PROHIBITED_REPORT_FIELDS",
    "REPORT_SCHEMA_VERSION",
    "ReportSafetyError",
    "assert_public_report_is_safe",
    "build_metric_definitions_document",
    "build_failure_path_document",
    "build_validation_report",
    "section_for_role",
]

REPORT_SCHEMA_VERSION = "pgx-wp21-validation-report/1"

#: Field names that must never appear at any depth of a public report. The
#: first group is WP-18's prohibited list, carried forward so a report cannot
#: reintroduce what a case refused to store; the rest are WP-21's own.
PROHIBITED_REPORT_FIELDS: Tuple[str, ...] = (
    "expected_result", "expected_attention", "expected_coverage",
    "gold_standard", "ground_truth", "answer_key", "concordance_answer",
    "expert_decision", "expert_response", "reviewer_answer",
    "payload", "payload_content", "phenotypes", "medications", "genotype",
    "vcf", "ehr", "patient", "patient_id", "mrn", "case_payload",
    "observations", "case_observations", "raw_result",
    "path", "filesystem_path", "absolute_path", "cwd", "home",
    "username", "user", "hostname", "host", "token", "credential",
    "password", "secret", "api_key",
)

#: Anything shaped like a filesystem path or a home directory. Checked on
#: string *values* as well as keys: a report that put an absolute path in a
#: detail message would leak the machine it ran on into an evidence artifact.
_PATH_SHAPED = re.compile(r"(^|[\s\"'(=])(/(?:home|Users|root|var|tmp|opt)/"
                          r"|[A-Za-z]:\\\\|~/)")


class ReportSafetyError(ValidationDatasetError):
    """A public report would have published something restricted."""


def _walk(value: Any, path: str, found: List[str]) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            name = str(key)
            if name.lower() in PROHIBITED_REPORT_FIELDS:
                found.append("%s.%s" % (path, name))
            _walk(item, "%s.%s" % (path, name), found)
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _walk(item, "%s[%d]" % (path, index), found)
    elif isinstance(value, str):
        if _PATH_SHAPED.search(value):
            found.append("%s (path-shaped value)" % path)


def assert_public_report_is_safe(document: Mapping[str, Any]) -> None:
    """Refuse a report carrying a restricted field or a machine-local path."""
    found: List[str] = []
    _walk(document, "$", found)
    if found:
        raise ReportSafetyError(
            "a public validation report may not carry: %s. These are either "
            "restricted case material or details of the machine that ran the "
            "benchmark; neither belongs in an artifact that is committed and "
            "served." % ", ".join(sorted(set(found))))


def section_for_role(role: ValidationCaseRole) -> str:
    """Which report section a role's results live under.

    Development results get their own named section rather than a flag on a
    shared table. A flag is something a reader can miss; a section headed
    ``DEVELOPMENT_REGRESSION`` is not.
    """
    if role is ValidationCaseRole.DEVELOPMENT:
        return DEVELOPMENT_SECTION
    return role.value


def build_metric_definitions_document() -> Dict[str, Any]:
    """The registry as a committed artifact, so definitions are auditable."""
    return {
        "schema_version": "pgx-wp21-metric-definitions/1",
        "metric_registry_version": METRIC_REGISTRY_VERSION,
        "metric_registry_digest": registry_digest(),
        "metric_count": len(METRIC_DEFINITIONS),
        "thresholds_declared": 0,
        "threshold_policy": (
            "No metric carries a threshold. A release threshold is a policy "
            "decision made by named people before results exist, with "
            "recorded provenance. No such policy exists for this system, so "
            "every threshold is null. A threshold added after seeing results "
            "would describe those results rather than judge them."),
        "metrics": [definition.to_json()
                    for definition in METRIC_DEFINITIONS],
        "unavailable_reasons": dict(sorted(UNAVAILABLE_REASONS.items())),
    }


def build_failure_path_document() -> Dict[str, Any]:
    """The predeclared denominator for failure-path coverage."""
    return {
        "schema_version": "pgx-wp21-failure-paths/1",
        "failure_path_catalogue_version": FAILURE_PATH_CATALOGUE_VERSION,
        "failure_path_count": len(FAILURE_PATH_CATALOGUE),
        "denominator_policy": (
            "This catalogue is the denominator for PGX-VAL-014 and "
            "PGX-VAL-015. It is declared before any benchmark runs. A run "
            "that exercises two paths reports two out of the catalogue size, "
            "never two out of two."),
        "failure_paths": [path.to_json() for path in FAILURE_PATH_CATALOGUE],
    }


def _partition_document(role: ValidationCaseRole,
                        values: Sequence[MetricValue],
                        case_count: Optional[int],
                        observation_count: Optional[int]) -> Dict[str, Any]:
    is_evidence = role is not ValidationCaseRole.DEVELOPMENT
    statuses: Dict[str, int] = {}
    for value in values:
        statuses[value.status.value] = statuses.get(value.status.value, 0) + 1
    return {
        "section": section_for_role(role),
        "role": role.value,
        "is_validation_evidence": is_evidence,
        "evidence_note": (
            "Results in this section are validation evidence only if a "
            "reference judgment and an independent case set exist."
            if is_evidence else
            "These cases shaped the software. They are a regression signal "
            "and are not validation evidence; no value here may enter a "
            "validation denominator."),
        "case_count": case_count,
        "observation_count": observation_count,
        "metric_count": len(values),
        "available_metric_count": sum(
            1 for value in values if value.status is MetricStatus.AVAILABLE),
        "status_counts": dict(sorted(statuses.items())),
        "metrics": [value.to_json() for value in values],
    }


def build_validation_report(*,
                            plan: Optional[BenchmarkPlan],
                            values_by_role: Mapping[str,
                                                    Sequence[MetricValue]],
                            case_counts: Mapping[str, Optional[int]],
                            observation_counts: Mapping[str, Optional[int]],
                            separation_audit: Mapping[str, Any],
                            blockers: Sequence[Mapping[str, Any]],
                            benchmark_executed: bool,
                            active_release_available: bool,
                            run: Optional[BenchmarkRun] = None,
                            generated_note: str = "") -> Dict[str, Any]:
    """Assemble the public report and refuse it if it leaks anything.

    ``plan`` is ``None`` when no benchmark could be planned - the real state
    of this repository. The report then carries a null pinned release rather
    than a placeholder, because a fabricated release identity is exactly the
    thing every hash in this file exists to prevent.
    """
    roles = [ValidationCaseRole.DEVELOPMENT,
             ValidationCaseRole.INTERNAL_HOLDOUT,
             ValidationCaseRole.EXPERT_HOLDOUT]
    partitions = []
    for role in roles:
        values = list(values_by_role.get(role.value, ()))
        partitions.append(_partition_document(
            role, values, case_counts.get(role.value),
            observation_counts.get(role.value)))

    evidence_values = [value for role in roles
                       if role is not ValidationCaseRole.DEVELOPMENT
                       for value in values_by_role.get(role.value, ())]
    numeric_evidence = sum(1 for value in evidence_values
                           if value.status is MetricStatus.AVAILABLE)

    document: Dict[str, Any] = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "work_package": "WP-21",
        "protocol_version": (None if plan is None
                             else plan.protocol_version),
        "metric_registry_version": METRIC_REGISTRY_VERSION,
        "metric_registry_digest": registry_digest(),
        "failure_path_catalogue_version": FAILURE_PATH_CATALOGUE_VERSION,
        "benchmark_executed": bool(benchmark_executed),
        "active_release_available": bool(active_release_available),
        "pinned_release": (None if plan is None
                           else plan.pinned_release.to_json()),
        "plan_id": None if plan is None else plan.plan_id,
        "plan_hash": None if plan is None else plan.plan_hash(),
        "case_manifest_hashes": ({} if plan is None
                                 else dict(plan.case_manifest_hashes)),
        "repeat_count": None if plan is None else plan.repeat_count,
        "declared_metric_ids": ([] if plan is None
                                else list(plan.declared_metric_ids)),
        "run_scientific_digest": (None if run is None
                                  else run.scientific_digest()),
        "separation_audit": dict(separation_audit),
        "partitions": partitions,
        "combined_overall_metric": None,
        "combined_overall_note": (
            "There is no combined figure, by design. Pooling development with "
            "holdout would let cases that shaped the software carry the "
            "partition meant to be independent of it; pooling the two holdout "
            "roles would let the larger carry the smaller. Read the "
            "partitions."),
        "numeric_validation_metric_count": numeric_evidence,
        "restricted_case_evidence_artifact": None,
        "restricted_case_evidence_note": (
            "Case-level execution evidence is a separate restricted artifact. "
            "None exists in this repository and none was generated."),
        "clinical_validation_performed": False,
        "expert_review_performed": False,
        "not_clinical_validation": (
            "This report describes software behaviour under a named release. "
            "It is not clinical validation, scientific validation or expert "
            "review, and no value in it establishes that the system is safe "
            "for any patient. Those are produced by people under WP-22 and "
            "cannot be produced by running a benchmark."),
        "blocker_count": len(blockers),
        "blockers": [dict(item) for item in sorted(
            blockers, key=lambda entry: str(entry.get("code", "")))],
        "note": generated_note,
    }
    assert_public_report_is_safe(document)
    return document


def report_digest(document: Mapping[str, Any]) -> str:
    return sha256_digest(document)
