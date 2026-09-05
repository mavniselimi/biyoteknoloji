# -*- coding: utf-8 -*-
"""Data-quality metrics and the fail-closed quality gate (WP-07).

Standard library plus :mod:`pgx.domain` and :mod:`pgx.normalization`.

**Every count here is derived.** Nothing in this module keeps a running tally
that a human typed. Metrics are computed from the same serialised rows the build
writes, and :func:`recount_from_build_path` recomputes all of them a second time
by reading the sealed files back off disk. A disagreement between the two is
itself a blocking finding, because a report that cannot be reproduced from the
artifacts it describes is not evidence of anything.

**Reconciliation, not summary.** For each stream the report states
``input = accepted + rejected + deferred`` and refuses to render if the identity
does not hold. A report where records simply vanish between two numbers is how a
pipeline loses data without anyone noticing.

**The gate fails closed.** Every unanswered question blocks. A missing source
approval blocks exactly as a refused one does; an unrecognised artifact blocks;
an ambiguity blocks; a conflicting identity collision blocks. The default answer
is "not quality checked", and that is the correct answer for a dataset nobody
has reviewed.

**The gate decides nothing about the dataset's lifecycle.** It returns a report.
There is no function here that marks a dataset ``QUALITY_CHECKED``, no automatic
approval, no reviewer default and no publication or release path - those are
human decisions, and a convenience wrapper for one would become the route
everybody used.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import (Any, Dict, Iterable, List, Mapping, Optional, Sequence,
                    Tuple)

from pgx.domain.hashing import sha256_digest
from pgx.normalization.artifacts import ArtifactRole, role_of
from pgx.normalization.build import CanonicalBuild, read_build_manifest
from pgx.normalization.errors import QualityGateError
from pgx.normalization.models import (DuplicateClass, EntityType,
                                      ResolutionStatus)

__all__ = [
    "DQ_REPORT_VERSION",
    "DataQualityIssue",
    "DataQualityIssueCode",
    "DataQualityReport",
    "GateDecision",
    "Reconciliation",
    "Severity",
    "evaluate_quality",
    "recount_from_build_path",
]

#: Bumped when the metric definitions or the gate rules change.
DQ_REPORT_VERSION = "pgx-data-quality/1"


class Severity(str, Enum):
    """How much a finding matters to the gate.

    Only ``BLOCKING`` stops a quality check. ``ADVISORY`` findings are real and
    are reported in full; they are things a reviewer should see rather than
    things that make the data unusable.
    """

    BLOCKING = "BLOCKING"
    ADVISORY = "ADVISORY"
    INFORMATIONAL = "INFORMATIONAL"

    def __str__(self) -> str:
        return self.value


class DataQualityIssueCode(str, Enum):
    """Stable codes, so a gate refusal can be matched on rather than parsed.

    Names are never reused for a different meaning. A code that stopped
    applying is retired rather than repurposed, because dashboards and tests
    match on these strings.
    """

    # -- provenance and governance --------------------------------------
    SNAPSHOT_NOT_SEALED = "SNAPSHOT_NOT_SEALED"
    SNAPSHOT_QUARANTINED = "SNAPSHOT_QUARANTINED"
    SNAPSHOT_NOT_ACQUIRED = "SNAPSHOT_NOT_ACQUIRED"
    SNAPSHOT_COMPLETENESS_UNKNOWN = "SNAPSHOT_COMPLETENESS_UNKNOWN"
    SOURCE_POLICY_MISSING = "SOURCE_POLICY_MISSING"
    SOURCE_POLICY_NOT_APPROVED = "SOURCE_POLICY_NOT_APPROVED"

    # -- artifacts ------------------------------------------------------
    UNRECOGNISED_ARTIFACT = "UNRECOGNISED_ARTIFACT"
    REQUIRED_ARTIFACT_MISSING = "REQUIRED_ARTIFACT_MISSING"
    EXPECTED_ARTIFACT_MISSING = "EXPECTED_ARTIFACT_MISSING"
    DERIVATION_CLAIM_BROKEN = "DERIVATION_CLAIM_BROKEN"

    # -- entities -------------------------------------------------------
    CANDIDATE_NOT_NORMALIZABLE = "CANDIDATE_NOT_NORMALIZABLE"
    CANDIDATE_DISPLAY_DISAGREEMENT = "CANDIDATE_DISPLAY_DISAGREEMENT"
    EXTERNAL_ID_CLAIMED_BY_SEVERAL_ENTITIES = \
        "EXTERNAL_ID_CLAIMED_BY_SEVERAL_ENTITIES"
    MALFORMED_EXTERNAL_IDENTIFIER = "MALFORMED_EXTERNAL_IDENTIFIER"
    ENTITY_WITHOUT_EXTERNAL_ID = "ENTITY_WITHOUT_EXTERNAL_ID"

    # -- resolution -----------------------------------------------------
    AMBIGUOUS_RESOLUTION = "AMBIGUOUS_RESOLUTION"
    UNRESOLVED_REFERENCE = "UNRESOLVED_REFERENCE"
    BROKEN_REFERENCE = "BROKEN_REFERENCE"
    INVALID_REFERENCE_INPUT = "INVALID_REFERENCE_INPUT"
    ALIAS_AWAITING_REVIEW = "ALIAS_AWAITING_REVIEW"

    # -- duplicates -----------------------------------------------------
    CONFLICTING_IDENTITY_COLLISION = "CONFLICTING_IDENTITY_COLLISION"
    SEMANTIC_DUPLICATE_CONTAINER = "SEMANTIC_DUPLICATE_CONTAINER"
    EXACT_DUPLICATE_OBSERVATION = "EXACT_DUPLICATE_OBSERVATION"
    RECORD_WITHOUT_SOURCE_IDENTITY = "RECORD_WITHOUT_SOURCE_IDENTITY"
    CONTAINER_SYNONYM_UNREVIEWED = "CONTAINER_SYNONYM_UNREVIEWED"

    # -- integrity of the report itself ---------------------------------
    RECONCILIATION_BROKEN = "RECONCILIATION_BROKEN"
    SUMMARY_DISAGREES_WITH_ARTIFACTS = "SUMMARY_DISAGREES_WITH_ARTIFACTS"

    # -- scope ----------------------------------------------------------
    OUT_OF_SCOPE_DATA_EXCLUDED = "OUT_OF_SCOPE_DATA_EXCLUDED"

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class DataQualityIssue:
    """One finding, with enough context to act on it.

    ``examples`` is bounded. A finding covering two thousand records is
    reported once with its count and a handful of examples: the alternative is
    a report so long that its own contents are hidden inside it.
    """

    code: DataQualityIssueCode
    severity: Severity
    subject: str
    detail: str
    count: int = 1
    examples: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.code, DataQualityIssueCode):
            raise QualityGateError("code must be a DataQualityIssueCode")
        if not isinstance(self.severity, Severity):
            raise QualityGateError("severity must be a Severity")
        object.__setattr__(self, "examples", tuple(self.examples[:5]))

    @property
    def blocking(self) -> bool:
        return self.severity is Severity.BLOCKING

    def to_json(self) -> Dict[str, Any]:
        return {
            "code": self.code.value,
            "severity": self.severity.value,
            "subject": self.subject,
            "detail": self.detail,
            "count": self.count,
            "examples": list(self.examples),
        }


@dataclass(frozen=True, slots=True)
class Reconciliation:
    """``input = accepted + rejected + deferred`` for one stream.

    Rendered only when the identity holds. A stream whose parts do not add up
    to its input has lost records somewhere between two counters, and
    publishing the parts anyway would present the loss as a result.
    """

    stream: str
    input_count: int
    accepted: int
    rejected: int
    deferred: int
    basis: str

    def __post_init__(self) -> None:
        for name in ("input_count", "accepted", "rejected", "deferred"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise QualityGateError(
                    "Reconciliation.%s must be a non-negative integer" % name)

    @property
    def balances(self) -> bool:
        return self.input_count == self.accepted + self.rejected + self.deferred

    @property
    def shortfall(self) -> int:
        return self.input_count - (self.accepted + self.rejected + self.deferred)

    def to_json(self) -> Dict[str, Any]:
        return {
            "stream": self.stream,
            "input_count": self.input_count,
            "accepted": self.accepted,
            "rejected": self.rejected,
            "deferred": self.deferred,
            "balances": self.balances,
            "shortfall": self.shortfall,
            "basis": self.basis,
        }


@dataclass(frozen=True, slots=True)
class GateDecision:
    """The gate's answer, and why.

    ``passed`` is true only when nothing blocks. There is no override argument,
    no severity threshold to lower and no allowlist of codes to ignore: a gate
    that can be argued down is not a gate.
    """

    passed: bool
    blocking_codes: Tuple[str, ...]
    advisory_codes: Tuple[str, ...]
    informational_codes: Tuple[str, ...]
    rationale: str

    def to_json(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "blocking_codes": list(self.blocking_codes),
            "advisory_codes": list(self.advisory_codes),
            "informational_codes": list(self.informational_codes),
            "rationale": self.rationale,
            "effect": ("A passing gate is a precondition for a human quality "
                       "decision, not the decision itself. Nothing here "
                       "transitions a dataset."),
        }


@dataclass(frozen=True)
class DataQualityReport:
    """The complete DQ record for one canonical build."""

    dq_report_version: str
    dataset_public_id: str
    canonical_build_key: str
    build_content_hash: str
    snapshot_manifest_hash: str
    metrics: Mapping[str, Any]
    reconciliations: Tuple[Reconciliation, ...]
    issues: Tuple[DataQualityIssue, ...]
    decision: GateDecision
    source_observed_axes: Mapping[str, Any]
    dataset_lifecycle_state: str = "BUILDING"

    @property
    def blocking_issues(self) -> Tuple[DataQualityIssue, ...]:
        return tuple(issue for issue in self.issues if issue.blocking)

    def content_identity(self) -> Dict[str, Any]:
        """Everything the report asserts about the build.

        There is no generation timestamp anywhere in this record, and that is
        deliberate. A DQ report is a pure function of the build it describes:
        the same build evaluated twice must produce identical bytes, so that
        "rebuild and compare" checks the metrics as well as the entities. When
        the report was computed is a fact about the run, and the build manifest
        beside it already records ``built_at``.
        """
        return {
            "dq_report_version": self.dq_report_version,
            "dataset_public_id": self.dataset_public_id,
            "canonical_build_key": self.canonical_build_key,
            "build_content_hash": self.build_content_hash,
            "snapshot_manifest_hash": self.snapshot_manifest_hash,
            "metrics": dict(self.metrics),
            "reconciliations": [item.to_json() for item in self.reconciliations],
            "issues": [item.to_json() for item in self.issues],
            "decision": self.decision.to_json(),
            "source_observed_axes": dict(self.source_observed_axes),
            "dataset_lifecycle_state": self.dataset_lifecycle_state,
        }

    def content_hash(self) -> str:
        return sha256_digest(self.content_identity())

    def to_json(self) -> Dict[str, Any]:
        payload = self.content_identity()
        payload["content_hash"] = self.content_hash()
        payload["lifecycle_note"] = (
            "This report describes a build. It does not approve one. The "
            "dataset remains BUILDING until a named human records a quality "
            "decision, and this package provides no way to record one.")
        return payload

    def render(self) -> str:
        """A short human-readable summary for a terminal."""
        lines = [
            "data quality report %s" % self.dq_report_version,
            "  dataset          %s" % self.dataset_public_id,
            "  build            %s" % self.canonical_build_key,
            "  lifecycle state  %s" % self.dataset_lifecycle_state,
            "  gate             %s" % ("PASS" if self.decision.passed
                                       else "BLOCKED"),
        ]
        for item in self.reconciliations:
            lines.append(
                "  %-22s input %d = accepted %d + rejected %d + deferred %d%s"
                % (item.stream, item.input_count, item.accepted, item.rejected,
                   item.deferred, "" if item.balances else "   IMBALANCED"))
        blocking = self.blocking_issues
        if blocking:
            lines.append("  blocking findings:")
            for issue in blocking:
                lines.append("    %-40s %s (%d)"
                             % (issue.code.value, issue.subject, issue.count))
        for severity, heading in ((Severity.ADVISORY, "advisory findings:"),
                                  (Severity.INFORMATIONAL,
                                   "informational findings:")):
            matching = [item for item in self.issues
                        if item.severity is severity]
            if not matching:
                continue
            lines.append("  " + heading)
            for issue in matching:
                lines.append("    %-40s %s (%d)"
                             % (issue.code.value, issue.subject, issue.count))
        return "\n".join(lines)


def evaluate_quality(build: CanonicalBuild, *,
                     source_policy_status: Optional[str] = None,
                     source_policy_content_hash: Optional[str] = None,
                     ) -> DataQualityReport:
    """Compute every metric and run the gate over one canonical build.

    Deterministic: the same build always produces the same report, byte for
    byte. There is no ``now`` parameter, because a wall-clock value in the
    report would make two evaluations of one build differ and would break the
    reproducibility check that compares them.

    ``source_policy_status`` is passed in rather than looked up, so that a
    caller cannot accidentally evaluate a build against a policy the build was
    not produced under. ``None`` means "no approval is on record", which blocks.
    """
    issues: List[DataQualityIssue] = []
    issues.extend(_provenance_issues(build, source_policy_status))
    issues.extend(_artifact_issues(build))
    issues.extend(_entity_issues(build))
    issues.extend(_resolution_issues(build))
    issues.extend(_duplicate_issues(build))
    issues.extend(_scope_issues(build))

    reconciliations = _reconciliations(build)
    for item in reconciliations:
        if not item.balances:
            issues.append(DataQualityIssue(
                code=DataQualityIssueCode.RECONCILIATION_BROKEN,
                severity=Severity.BLOCKING,
                subject=item.stream,
                detail=("input %d does not equal accepted %d + rejected %d + "
                        "deferred %d; %d record(s) are unaccounted for"
                        % (item.input_count, item.accepted, item.rejected,
                           item.deferred, item.shortfall)),
                count=abs(item.shortfall)))

    metrics = _metrics(build, source_policy_content_hash)
    ordered = tuple(sorted(issues, key=lambda item: (
        0 if item.blocking else 1, item.code.value, item.subject)))
    decision = _decide(ordered)

    return DataQualityReport(
        dq_report_version=DQ_REPORT_VERSION,
        dataset_public_id=build.dataset_public_id,
        canonical_build_key=build.build_key,
        build_content_hash=build.content_hash(),
        snapshot_manifest_hash=build.snapshot_manifest_hash,
        metrics=metrics,
        reconciliations=reconciliations,
        issues=ordered,
        decision=decision,
        source_observed_axes=dict(build.extraction.source_observed_axes),
        dataset_lifecycle_state="BUILDING")


def _decide(issues: Sequence[DataQualityIssue]) -> GateDecision:
    """Fail closed: any blocking finding refuses the check."""
    def codes(severity: Severity) -> Tuple[str, ...]:
        return tuple(sorted({item.code.value for item in issues
                             if item.severity is severity}))

    blocking = codes(Severity.BLOCKING)
    advisory = codes(Severity.ADVISORY)
    informational = codes(Severity.INFORMATIONAL)
    if blocking:
        rationale = (
            "%d blocking finding kind(s) refuse this quality check: %s. The "
            "gate fails closed: an unanswered question blocks exactly as a "
            "refused one does."
            % (len(blocking), ", ".join(blocking)))
        return GateDecision(False, blocking, advisory, informational, rationale)
    return GateDecision(
        True, (), advisory, informational,
        "No blocking finding. This is a precondition for a human quality "
        "decision, not a decision: a named reviewer must still record one, and "
        "this package provides no way to record it automatically.")


# -- issue producers ----------------------------------------------------


def _provenance_issues(build: CanonicalBuild,
                       source_policy_status: Optional[str]
                       ) -> List[DataQualityIssue]:
    issues: List[DataQualityIssue] = []
    if build.snapshot_state == "QUARANTINED":
        issues.append(DataQualityIssue(
            code=DataQualityIssueCode.SNAPSHOT_QUARANTINED,
            severity=Severity.BLOCKING,
            subject=build.dataset_public_id,
            detail=("the raw snapshot is QUARANTINED. Building from it is "
                    "allowed so the data can be examined; passing a quality "
                    "check on it is not.")))
    elif build.snapshot_state != "SEALED":
        issues.append(DataQualityIssue(
            code=DataQualityIssueCode.SNAPSHOT_NOT_SEALED,
            severity=Severity.BLOCKING,
            subject=build.dataset_public_id,
            detail=("the raw snapshot is %s rather than SEALED; its bytes are "
                    "not guaranteed to be final" % build.snapshot_state)))

    if build.snapshot_kind == "LEGACY_IMPORT":
        issues.append(DataQualityIssue(
            code=DataQualityIssueCode.SNAPSHOT_NOT_ACQUIRED,
            severity=Severity.BLOCKING,
            subject=build.dataset_public_id,
            detail=("the snapshot is a LEGACY_IMPORT: no acquisition run "
                    "records which endpoints were called, when, or whether the "
                    "responses were complete. Completeness relative to the "
                    "upstream source is unknown and is not inferred from the "
                    "fact that every file present was copied.")))

    if not build.snapshot_complete and build.snapshot_kind != "LEGACY_IMPORT":
        issues.append(DataQualityIssue(
            code=DataQualityIssueCode.SNAPSHOT_COMPLETENESS_UNKNOWN,
            severity=Severity.BLOCKING,
            subject=build.dataset_public_id,
            detail=("the raw snapshot does not assert completeness. A build "
                    "over a partial retrieval reports partial counts, and "
                    "partial counts read exactly like complete ones.")))

    if source_policy_status is None:
        issues.append(DataQualityIssue(
            code=DataQualityIssueCode.SOURCE_POLICY_MISSING,
            severity=Severity.BLOCKING,
            subject=build.dataset_public_id,
            detail=("no source-policy approval is on record for this dataset. "
                    "An unregistered source has no permissions rather than "
                    "unlimited ones.")))
    elif source_policy_status != "APPROVED":
        issues.append(DataQualityIssue(
            code=DataQualityIssueCode.SOURCE_POLICY_NOT_APPROVED,
            severity=Severity.BLOCKING,
            subject=build.dataset_public_id,
            detail="the source policy status is %r, not APPROVED"
                   % source_policy_status))
    return issues


def _artifact_issues(build: CanonicalBuild) -> List[DataQualityIssue]:
    extraction = build.extraction
    issues: List[DataQualityIssue] = []
    if extraction.unrecognised_artifacts:
        issues.append(DataQualityIssue(
            code=DataQualityIssueCode.UNRECOGNISED_ARTIFACT,
            severity=Severity.BLOCKING,
            subject="artifact role map",
            detail=("the snapshot contains artifacts the role map does not "
                    "classify. They were not read and no record was derived "
                    "from them; classify them before relying on this build."),
            count=len(extraction.unrecognised_artifacts),
            examples=extraction.unrecognised_artifacts))
    # A missing artifact is two different findings depending on what it was
    # for. A snapshot short of an *evidence* input produced an incomplete
    # canonical dataset and must block. A snapshot short of a comparison-only
    # file is a different build - a future acquisition-backed snapshot from the
    # same source will legitimately carry no legacy CSVs at all - and blocking
    # on that would make the role map's legacy-specific entries a permanent
    # obstacle to ever passing.
    required_missing = tuple(name for name in extraction.missing_artifacts
                             if role_of(name).counts_as_evidence)
    other_missing = tuple(name for name in extraction.missing_artifacts
                          if name not in required_missing)
    if required_missing:
        issues.append(DataQualityIssue(
            code=DataQualityIssueCode.REQUIRED_ARTIFACT_MISSING,
            severity=Severity.BLOCKING,
            subject="artifact role map",
            detail=("an artifact the role map treats as evidence is absent "
                    "from the snapshot, so this canonical dataset is missing "
                    "records the source was expected to supply"),
            count=len(required_missing),
            examples=required_missing))
    if other_missing:
        issues.append(DataQualityIssue(
            code=DataQualityIssueCode.EXPECTED_ARTIFACT_MISSING,
            severity=Severity.ADVISORY,
            subject="artifact role map",
            detail=("comparison-only or reference artifacts the role map knows "
                    "about are absent. They contribute no records, so the "
                    "canonical dataset is unaffected; the legacy comparisons "
                    "that would have used them cannot be made."),
            count=len(other_missing),
            examples=other_missing))
    broken = tuple(check for check in extraction.derivation_checks
                   if not check.consistent)
    if broken:
        issues.append(DataQualityIssue(
            code=DataQualityIssueCode.DERIVATION_CLAIM_BROKEN,
            severity=Severity.BLOCKING,
            subject="derived artifacts",
            detail=("a file classified as derived carries identifiers its "
                    "source does not. The 'derived, therefore not evidence' "
                    "reasoning has stopped holding for it."),
            count=len(broken),
            examples=tuple(check.derived_artifact for check in broken)))
    return issues


def _entity_issues(build: CanonicalBuild) -> List[DataQualityIssue]:
    issues: List[DataQualityIssue] = []
    by_code: Dict[str, List[Mapping[str, Any]]] = {}
    for finding in build.entity_findings:
        by_code.setdefault(str(finding.get("code")), []).append(finding)
    for code_name in sorted(by_code):
        findings = by_code[code_name]
        try:
            code = DataQualityIssueCode(code_name)
        except ValueError:
            continue
        blocking = any(bool(item.get("blocking")) for item in findings)
        issues.append(DataQualityIssue(
            code=code,
            severity=Severity.BLOCKING if blocking else Severity.ADVISORY,
            subject="canonical entities",
            detail=str(findings[0].get("detail")),
            count=len(findings),
            examples=tuple(str(item.get("canonical_key") or item.get("detail"))
                           for item in findings[:5])))

    malformed = []
    without_ids = []
    for entity in build.entities:
        for text in entity.findings:
            if "does not match" in text or "is blank" in text \
                    or "no validation rule" in text:
                malformed.append("%s: %s" % (entity.canonical_key, text))
        if not entity.external_ids:
            without_ids.append(entity.canonical_key)
    if malformed:
        issues.append(DataQualityIssue(
            code=DataQualityIssueCode.MALFORMED_EXTERNAL_IDENTIFIER,
            severity=Severity.ADVISORY,
            subject="external identifiers",
            detail=("identifiers that do not match their namespace's shape are "
                    "recorded rather than discarded: a broken external "
                    "reference must not look like an absent one"),
            count=len(malformed),
            examples=tuple(sorted(malformed))))
    if without_ids:
        issues.append(DataQualityIssue(
            code=DataQualityIssueCode.ENTITY_WITHOUT_EXTERNAL_ID,
            severity=Severity.ADVISORY,
            subject="canonical entities",
            detail=("these entities carry no external identifier, so they can "
                    "only ever be matched by name"),
            count=len(without_ids),
            examples=tuple(sorted(without_ids))))

    pending = []
    for entity in build.entities:
        for alias in entity.aliases:
            if not alias.resolves:
                pending.append("%s -> %s" % (entity.canonical_key,
                                             alias.normalized_alias))
    if pending:
        issues.append(DataQualityIssue(
            code=DataQualityIssueCode.ALIAS_AWAITING_REVIEW,
            severity=Severity.ADVISORY,
            subject="alias proposals",
            detail=("alternative names observed upstream are recorded as "
                    "proposals and do not resolve anything until a named "
                    "reviewer approves them"),
            count=len(pending),
            examples=tuple(sorted(pending))))
    return issues


def _resolution_issues(build: CanonicalBuild) -> List[DataQualityIssue]:
    buckets = {
        ResolutionStatus.AMBIGUOUS: (
            DataQualityIssueCode.AMBIGUOUS_RESOLUTION, Severity.BLOCKING,
            "a value matched more than one canonical entity. It is never "
            "settled by ranking, by insertion order or by picking the first "
            "candidate; it goes to a human."),
        ResolutionStatus.UNRESOLVED: (
            DataQualityIssueCode.UNRESOLVED_REFERENCE, Severity.BLOCKING,
            "a value matched no canonical entity at any stage"),
        ResolutionStatus.BROKEN_REFERENCE: (
            DataQualityIssueCode.BROKEN_REFERENCE, Severity.BLOCKING,
            "a relationship references an entity the canonical dataset does "
            "not contain"),
        ResolutionStatus.INVALID_INPUT: (
            DataQualityIssueCode.INVALID_REFERENCE_INPUT, Severity.BLOCKING,
            "a submitted value could not be normalised at all"),
    }
    issues: List[DataQualityIssue] = []
    for status, (code, severity, detail) in buckets.items():
        matching = tuple(item for item in build.resolutions
                         if item.status is status)
        if not matching:
            continue
        issues.append(DataQualityIssue(
            code=code, severity=severity, subject="entity resolution",
            detail=detail, count=len(matching),
            examples=tuple("%s %r" % (item.entity_type.value,
                                      item.submitted_value)
                           for item in matching[:5])))
    return issues


def _duplicate_issues(build: CanonicalBuild) -> List[DataQualityIssue]:
    dedup = build.dedup
    issues: List[DataQualityIssue] = []
    conflicting = dedup.of_class(DuplicateClass.CONFLICTING_IDENTITY)
    if conflicting:
        issues.append(DataQualityIssue(
            code=DataQualityIssueCode.CONFLICTING_IDENTITY_COLLISION,
            severity=Severity.BLOCKING,
            subject="duplicate detection",
            detail=("records claiming one source identity while carrying "
                    "different payloads. One of them is wrong, and discarding "
                    "either would hide which."),
            count=len(conflicting),
            examples=tuple(group.group_key for group in conflicting[:5])))
    semantic = dedup.of_class(DuplicateClass.SEMANTIC)
    if semantic:
        issues.append(DataQualityIssue(
            code=DataQualityIssueCode.SEMANTIC_DUPLICATE_CONTAINER,
            severity=Severity.ADVISORY,
            subject="duplicate detection",
            detail=("the same source record was returned under more than one "
                    "container spelling. The payloads are identical; only the "
                    "source's capitalisation differs. Counting both is "
                    "LEGACY-BUG-004."),
            count=len(semantic),
            examples=tuple(group.group_key for group in semantic[:5])))
    exact = dedup.of_class(DuplicateClass.EXACT)
    if exact:
        issues.append(DataQualityIssue(
            code=DataQualityIssueCode.EXACT_DUPLICATE_OBSERVATION,
            severity=Severity.INFORMATIONAL,
            subject="duplicate detection",
            detail=("one source record observed at several locators with an "
                    "identical payload. Every locator is retained."),
            count=len(exact),
            examples=tuple(group.group_key for group in exact[:5])))
    if dedup.unidentified:
        issues.append(DataQualityIssue(
            code=DataQualityIssueCode.RECORD_WITHOUT_SOURCE_IDENTITY,
            severity=Severity.BLOCKING,
            subject="duplicate detection",
            detail=("records with no source record identity cannot be "
                    "deduplicated. They are kept apart rather than merged on "
                    "content, because equal payloads are not evidence of one "
                    "record."),
            count=len(dedup.unidentified),
            examples=tuple(locator.pointer
                           for locator in dedup.unidentified[:5])))
    for entry in build.extraction.container_synonyms:
        issues.append(DataQualityIssue(
            code=DataQualityIssueCode.CONTAINER_SYNONYM_UNREVIEWED,
            severity=Severity.ADVISORY,
            subject="container naming",
            detail=("one source record reached through containers with "
                    "different names (%s). These are not case variants, so "
                    "they are not folded; whether they denote the same "
                    "container is a review question."
                    % ", ".join(entry.get("container_families", ()))),
            count=int(entry.get("record_count", 0)),
            examples=tuple(entry.get("examples", ()))))
    return issues


def _scope_issues(build: CanonicalBuild) -> List[DataQualityIssue]:
    excluded = build.extraction.excluded_record_counts
    if not excluded:
        return []
    total = sum(excluded.values())
    return [DataQualityIssue(
        code=DataQualityIssueCode.OUT_OF_SCOPE_DATA_EXCLUDED,
        severity=Severity.INFORMATIONAL,
        subject="P1 candidate data",
        detail=("candidate-onboarding records were counted and excluded from "
                "the P0 canonical dataset. Importing them would add drugs no "
                "reviewer selected."),
        count=total,
        examples=tuple("%s: %d" % (key, value)
                       for key, value in sorted(excluded.items())))]


# -- metrics and reconciliation -----------------------------------------


def _reconciliations(build: CanonicalBuild) -> Tuple[Reconciliation, ...]:
    """Every stream, balanced.

    Each is computed from the build's own contents. ``deferred`` means "kept,
    counted, and waiting for a decision" - never "dropped".
    """
    extraction = build.extraction
    candidates = extraction.candidates
    accepted_candidates = sum(1 for item in candidates
                              if item.normalized_value is not None)
    rejected_candidates = len(candidates) - accepted_candidates

    resolved = sum(1 for item in build.resolutions if item.is_resolved)
    invalid = sum(1 for item in build.resolutions
                  if item.status is ResolutionStatus.INVALID_INPUT)
    deferred_resolutions = len(build.resolutions) - resolved - invalid

    roles: Dict[str, int] = {}
    for report in extraction.reports:
        roles[report.role.value] = roles.get(report.role.value, 0) + 1
    evidence_roles = (ArtifactRole.ENTITY_CANDIDATE_INPUT.value,
                      ArtifactRole.RELATIONSHIP_REFERENCE_INPUT.value,
                      ArtifactRole.RAW_ANNOTATION_INPUT.value)
    artifacts_accepted = sum(roles.get(name, 0) for name in evidence_roles)
    artifacts_deferred = roles.get(ArtifactRole.UNRECOGNISED.value, 0)
    artifacts_total = sum(roles.values())

    return (
        Reconciliation(
            stream="raw_artifacts",
            input_count=artifacts_total,
            accepted=artifacts_accepted,
            rejected=artifacts_total - artifacts_accepted - artifacts_deferred,
            deferred=artifacts_deferred,
            basis=("accepted = artifacts read as evidence; rejected = derived, "
                   "out-of-scope or reference-only artifacts deliberately not "
                   "read; deferred = artifacts the role map does not classify")),
        Reconciliation(
            stream="entity_candidates",
            input_count=len(candidates),
            accepted=accepted_candidates,
            rejected=rejected_candidates,
            deferred=0,
            basis=("accepted = candidates that normalised and contributed to a "
                   "canonical entity; rejected = candidates whose value could "
                   "not be normalised at all")),
        Reconciliation(
            stream="entity_references",
            input_count=len(build.resolutions),
            accepted=resolved,
            rejected=invalid,
            deferred=deferred_resolutions,
            basis=("accepted = references that resolved to exactly one entity; "
                   "rejected = values that could not be normalised; deferred = "
                   "ambiguous, unresolved or broken references now in the "
                   "resolution queue")),
        Reconciliation(
            stream="source_record_observations",
            input_count=build.dedup.total_observations,
            accepted=build.dedup.distinct_records,
            rejected=0,
            deferred=build.dedup.duplicate_observations,
            basis=("accepted = distinct source records; deferred = additional "
                   "observations of a record already counted, every one of "
                   "which is retained inside its duplicate group; rejected is "
                   "zero because no observation is discarded")),
    )


def _metrics(build: CanonicalBuild,
             source_policy_content_hash: Optional[str]) -> Dict[str, Any]:
    """Every number in the report, derived from the build's serialised rows."""
    entities = build.entities
    by_type = {
        entity_type.value: sum(1 for item in entities
                               if item.entity_type is entity_type)
        for entity_type in EntityType
    }
    resolution_counts = {
        status.value: sum(1 for item in build.resolutions
                          if item.status is status)
        for status in ResolutionStatus
    }
    duplicate_counts = {
        classification.value: {
            "group_count": len(build.dedup.of_class(classification)),
            "member_count": build.dedup.member_count(classification),
        }
        for classification in DuplicateClass
    }
    return {
        "entity_counts": by_type,
        "entity_total": len(entities),
        "entities_with_external_id": sum(1 for item in entities
                                         if item.external_ids),
        "alias_proposal_total": sum(len(item.aliases) for item in entities),
        "approved_alias_total": sum(len(item.approved_aliases)
                                    for item in entities),
        "provenance_link_total": sum(len(item.locators) for item in entities),
        "resolution_counts": resolution_counts,
        "resolution_queue_size": len(build.queue),
        "decided_queue_item_count": sum(1 for item in build.queue
                                        if item.is_decided),
        "duplicate_counts": duplicate_counts,
        "observation_total": build.dedup.total_observations,
        "distinct_record_total": build.dedup.distinct_records,
        "duplicate_observation_total": build.dedup.duplicate_observations,
        "records_without_source_id": dict(
            build.extraction.records_without_source_id),
        "excluded_record_counts": dict(
            build.extraction.excluded_record_counts),
        # How many identities this *run* minted or reused is a fact about the
        # run, not about the build, and it belongs in the manifest beside
        # built_at. Recording it here would make two evaluations of the same
        # build differ - the first run mints, the second reuses - and would
        # break the reproducibility check that compares them.
        "identity_allocation_size": len(build.allocation),
        "source_policy_content_hash": source_policy_content_hash,
        "rule_versions": build.rule_versions,
    }


# -- independent re-count from the sealed files -------------------------


def recount_from_build_path(build_path: str) -> Dict[str, Any]:
    """Recompute the headline counts by reading the sealed build back.

    Deliberately independent of the in-memory build: it opens the NDJSON files
    and counts lines and fields. If this disagrees with what the manifest and
    the DQ report recorded, the report describes something other than the
    directory it sits in, and the caller raises
    ``SUMMARY_DISAGREES_WITH_ARTIFACTS``.
    """
    counts = {
        "gene_count": _count_lines(os.path.join(build_path, "genes.ndjson")),
        "drug_count": _count_lines(os.path.join(build_path, "drugs.ndjson")),
        "membership_count": _count_lines(
            os.path.join(build_path, "entity-membership.ndjson")),
        "queue_item_count": _count_lines(
            os.path.join(build_path, "resolution-queue.ndjson")),
        "duplicate_group_count": _count_lines(
            os.path.join(build_path, "duplicate-groups.ndjson")),
        "provenance_link_count": _count_lines(
            os.path.join(build_path, "provenance.ndjson")),
    }
    members = 0
    blocking_groups = 0
    for row in _read_ndjson(os.path.join(build_path, "duplicate-groups.ndjson")):
        members += int(row.get("member_count", 0))
        if row.get("blocking"):
            blocking_groups += 1
    counts["duplicate_group_member_count"] = members
    counts["blocking_duplicate_group_count"] = blocking_groups
    counts["duplicate_observation_count"] = members - counts[
        "duplicate_group_count"]

    allocation_path = os.path.join(build_path, "identity-allocation.json")
    if os.path.isfile(allocation_path):
        with open(allocation_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        counts["identity_allocation_size"] = len(payload.get("entries", ()))
    counts["entity_count"] = counts["gene_count"] + counts["drug_count"]
    return counts


def compare_with_artifacts(build_path: str) -> Tuple[bool, Tuple[str, ...]]:
    """Check a sealed build's recorded summary against a fresh re-count."""
    manifest = read_build_manifest(build_path)
    summary = manifest.get("summary") or {}
    actual = recount_from_build_path(build_path)
    problems: List[str] = []
    for name in ("gene_count", "drug_count", "entity_count",
                 "queue_item_count", "duplicate_group_count",
                 "duplicate_observation_count",
                 "blocking_duplicate_group_count"):
        if name in summary and summary[name] != actual.get(name):
            problems.append(
                "%s: manifest says %r, the artifacts contain %r"
                % (name, summary[name], actual.get(name)))
    if summary.get("locator_count") is not None and \
            summary["locator_count"] != actual.get("provenance_link_count"):
        problems.append(
            "locator_count: manifest says %r, provenance.ndjson contains %r"
            % (summary["locator_count"], actual.get("provenance_link_count")))
    return not problems, tuple(problems)


def _count_lines(path: str) -> int:
    if not os.path.isfile(path):
        return 0
    count = 0
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                count += 1
    return count


def _read_ndjson(path: str) -> Iterable[Mapping[str, Any]]:
    if not os.path.isfile(path):
        return
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if text:
                yield json.loads(text)
