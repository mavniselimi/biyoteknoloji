# -*- coding: utf-8 -*-
"""What a candidate dataset must satisfy to back a DEMO/VALIDATION release.

Declared as code, in one place, so that "the dataset met the candidate
criteria" is a claim somebody can check rather than a sentence in a report.

**These are not the publication gate, and they are weaker than it.** The
data-quality gate in :mod:`pgx.normalization.quality` answers a different
question - is this dataset fit to publish - and for the capture dataset it
answers no, for two reasons that are structural rather than accidental:

``SNAPSHOT_COMPLETENESS_UNKNOWN``
    a transcription capture cannot assert completeness relative to its
    upstream source. Four guideline annotations were read; nothing was crawled
    to discover whether others exist, and nothing should be. This blocker is
    permanent for this kind of snapshot and would be dishonest to clear.

``SOURCE_POLICY_NOT_APPROVED``
    no human decision authorises ``AGENT_TARGETED_RETRIEVAL`` for any source.
    H01's recorded outcome for ``cpic.database`` permits ``MANUAL_DOWNLOAD``
    and ``INTERNAL_DERIVATION`` only, under the condition "manual review and
    citation only", and its prohibited list includes "expanding the approved
    source set by implication". Clearing this blocker would mean extending a
    named pharmacist's decision past its recorded scope.

Both are therefore recorded as **named exceptions with stated reasons**, and
the acceptance says so on its face. A candidate release does not claim
completeness relative to CPIC's full corpus, and does not claim an approved
acquisition route; it claims to answer, in DEMO and VALIDATION only, exactly
the axes it transcribed. Any *other* blocking issue fails the criteria
outright - the exception list is closed, and a new blocker cannot join it by
appearing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Sequence, Tuple

__all__ = [
    "CANDIDATE_DQ_CRITERIA_VERSION",
    "FIRST_RELEASE_AXES",
    "PERMITTED_BLOCKING_CODES",
    "CriterionResult",
    "evaluate_candidate_criteria",
]

CANDIDATE_DQ_CRITERIA_VERSION = "pgx-wave03b-candidate-dq-criteria/1"

#: The only blocking codes a candidate dataset may carry, each with the reason
#: it is structural rather than fixable. A closed list: anything else blocks.
PERMITTED_BLOCKING_CODES: Mapping[str, str] = {
    "SNAPSHOT_COMPLETENESS_UNKNOWN": (
        "a transcription capture cannot assert completeness relative to its "
        "upstream source, and inferring it from the fact that every intended "
        "document was read would answer a different question"),
    "SOURCE_POLICY_NOT_APPROVED": (
        "no human decision authorises AGENT_TARGETED_RETRIEVAL; H01 permits "
        "MANUAL_DOWNLOAD and INTERNAL_DERIVATION for cpic.database and "
        "prohibits expanding the approved source set by implication"),
}

FIRST_RELEASE_AXES: Tuple[str, ...] = (
    "CYP2C19::amitriptyline",
    "CYP2C19::clopidogrel",
    "CYP2C19::omeprazole",
    "CYP2D6::amitriptyline",
    "CYP2D6::codeine",
)


@dataclass(frozen=True, slots=True)
class CriterionResult:
    criterion_id: str
    requirement: str
    met: bool
    observed: str

    def to_json(self) -> Dict[str, Any]:
        return {
            "criterion_id": self.criterion_id,
            "met": self.met,
            "observed": self.observed,
            "requirement": self.requirement,
        }


def evaluate_candidate_criteria(
        manifest: Mapping[str, Any],
        dq_report: Mapping[str, Any],
        observed_axes: Sequence[str] = ()) -> Tuple[CriterionResult, ...]:
    """Judge one canonical build against the candidate criteria.

    Reads the two artifacts on disk rather than the in-memory build, because a
    decision is about what was written, not about what a builder believed.
    """
    summary = dq_report.get("metrics") or manifest.get("summary") or {}
    decision = dq_report.get("decision") or {}
    blocking = tuple(decision.get("blocking_codes") or ())
    issues = {item.get("code"): item for item in (dq_report.get("issues") or ())}
    # Read from the caller, not from ``manifest["source_observed_axes"]``.
    # That field is a *counts* object - gene count, drug count, pair query
    # count - and iterating it yields its key names. The first version of this
    # criterion did exactly that, found none of the five axis strings among
    # them, and recorded a REJECTED verdict on a dataset that carries all five.
    # The axes now come from the sealed capture artifact, which is the only
    # place that actually lists them.
    axes = tuple(sorted(observed_axes))

    results: List[CriterionResult] = []

    def add(cid: str, requirement: str, met: bool, observed: str) -> None:
        results.append(CriterionResult(cid, requirement, met, observed))

    add("CD-01", "the raw snapshot is SEALED",
        manifest.get("snapshot_state") == "SEALED",
        "snapshot_state=%r" % manifest.get("snapshot_state"))

    add("CD-02",
        "the snapshot is a transcription capture and says so",
        manifest.get("snapshot_kind") == "TRANSCRIPTION_CAPTURE",
        "snapshot_kind=%r" % manifest.get("snapshot_kind"))

    unexpected = tuple(code for code in blocking
                       if code not in PERMITTED_BLOCKING_CODES)
    add("CD-03",
        "no blocking data-quality issue outside the closed exception list",
        not unexpected,
        "blocking=%s; outside the exception list=%s"
        % (list(blocking), list(unexpected)))

    add("CD-04",
        "no artifact in the snapshot is unclassified",
        "UNRECOGNISED_ARTIFACT" not in issues,
        "unrecognised artifacts=%d"
        % (issues.get("UNRECOGNISED_ARTIFACT", {}).get("count") or 0))

    add("CD-05",
        "no evidence-bearing artifact the capture family expects is missing",
        "REQUIRED_ARTIFACT_MISSING" not in issues,
        "required-missing=%d"
        % (issues.get("REQUIRED_ARTIFACT_MISSING", {}).get("count") or 0))

    add("CD-06",
        "every transcribed record carries a source record identity",
        "RECORD_WITHOUT_SOURCE_IDENTITY" not in issues,
        "records without identity=%d"
        % (issues.get("RECORD_WITHOUT_SOURCE_IDENTITY", {}).get("count") or 0))

    add("CD-07",
        "no blocking duplicate group",
        not summary.get("blocking_duplicate_group_count"),
        "blocking duplicate groups=%s"
        % summary.get("blocking_duplicate_group_count"))

    missing_axes = tuple(a for a in FIRST_RELEASE_AXES if a not in axes)
    add("CD-08",
        "all five first-release gene-drug axes are present",
        not missing_axes,
        "observed=%s; missing=%s" % (list(axes), list(missing_axes)))

    add("CD-09",
        "the dataset carries no legacy scientific rows",
        manifest.get("dataset_public_id") != "PGX-DATA-20260830-900"
        and manifest.get("snapshot_kind") != "LEGACY_IMPORT",
        "dataset=%r kind=%r" % (manifest.get("dataset_public_id"),
                                manifest.get("snapshot_kind")))

    add("CD-10",
        "the build declares itself reproducible from its own inputs",
        bool(manifest.get("content_hash")) and bool(
            manifest.get("canonical_build_key")),
        "content_hash=%s" % (manifest.get("content_hash") or "")[:24])

    return tuple(results)
