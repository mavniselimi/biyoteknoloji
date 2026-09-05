# -*- coding: utf-8 -*-
"""The benchmark contract (WP-21): what a run pins, and what it observed.

A benchmark result is only meaningful if you can say what produced it. Every
number this package can ever emit has to be attributable to one release, one
ruleset, one dataset, one software version and one case manifest - so the plan
pins all of them *before* execution, and every observation carries the same
identities back so a mismatch is detectable rather than assumed away.

Three deliberate refusals live in this module:

- **One release per run, resolved once.** :class:`BenchmarkPlan` holds the
  pinned identity; nothing re-reads an active-release pointer mid-run. An
  activation that commits while a benchmark is running changes the next run,
  not this one.

- **A mismatch blocks everything.** Not the offending row - everything. If one
  observation names a different release hash, the honest reading is "this run
  measured something other than what it says", and dropping the row and
  carrying on would produce a report whose title is false about its contents.

- **No expected answers anywhere.** An observation records what the system
  produced. What it *should* have produced, if anyone ever says so, arrives
  through a separate immutable reference-judgment input with its own
  provenance. WP-18 stores no answer key and this module does not add one.

Ports are protocols with no implementation here. Production code must not
import test fixtures, so the synthetic release used to prove the engine can
produce a table lives under ``tests/`` and is injected.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from pgx.domain.hashing import sha256_digest
from pgx.validation.errors import ValidationDatasetError
from pgx.validation.metric_definitions import (FAILURE_PATH_CATALOGUE_VERSION,
                                               METRIC_REGISTRY_VERSION,
                                               failure_paths_by_id)
from pgx.validation.vocabulary import ValidationCaseRole

__all__ = [
    "BENCHMARK_PROTOCOL_VERSION",
    "BenchmarkError",
    "BenchmarkObservation",
    "BenchmarkPlan",
    "BenchmarkRun",
    "PinMismatchError",
    "PinnedRelease",
    "ReferenceJudgment",
    "ReferenceJudgmentPort",
    "ReleaseResolutionPort",
    "RestrictedObservationPort",
    "UnpinnedError",
]

BENCHMARK_PROTOCOL_VERSION = "pgx-wp21-benchmark-protocol/1"

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_PUBLIC_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")


class BenchmarkError(ValidationDatasetError):
    """A benchmark could not be planned, executed or reported honestly."""


class UnpinnedError(BenchmarkError):
    """Something a run must name was absent.

    Its own type because the remedy differs from a mismatch: a mismatch means
    two real things disagree and somebody must find out which is right; an
    unpinned field means nobody said, and the run must not start.
    """


class PinMismatchError(BenchmarkError):
    """An observation disagrees with what the plan pinned.

    Carries the field and both values so the report can name the disagreement
    without the caller re-deriving it. Never carries payload content.
    """

    def __init__(self, field_name: str, expected: str, observed: str,
                 *, case_id: Optional[str] = None) -> None:
        self.field_name = field_name
        self.expected = expected
        self.observed = observed
        self.case_id = case_id
        where = "" if case_id is None else " (case %s)" % case_id
        super().__init__(
            "%s disagrees with the pinned run%s: pinned %s, observed %s. The "
            "whole run is refused rather than this row dropped; a report that "
            "silently excluded a disagreeing observation would describe a "
            "different run than the one it names."
            % (field_name, where, expected, observed))


def _require_digest(value: object, field_name: str) -> str:
    text = str(value or "")
    if not _DIGEST.match(text):
        raise UnpinnedError(
            "%s must be a canonical sha256:<hex> value; a benchmark that "
            "cannot name the bytes it ran against cannot be reproduced"
            % field_name)
    return text


def _require_public_id(value: object, field_name: str) -> str:
    text = str(value or "")
    if not _PUBLIC_ID.match(text):
        raise UnpinnedError("%s must be a public identifier" % field_name)
    return text


@dataclass(frozen=True, slots=True)
class PinnedRelease:
    """The single release a run measures, with every hash that names it.

    Resolved once, by a :class:`ReleaseResolutionPort`, before any case runs.
    Frozen, so nothing downstream can adjust what the run claims to have used.
    """

    release_public_id: str
    release_manifest_hash: str
    software_version: str
    software_hash: str
    dataset_public_id: str
    dataset_content_hash: str
    ruleset_public_id: str
    ruleset_content_hash: str
    resolved_at: _dt.datetime
    #: The WP-03 pointer generation seen at pin time, where one exists. Kept so
    #: a later activation is visibly a different run rather than a silent one.
    active_pointer_generation: Optional[int] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "release_public_id",
                           _require_public_id(self.release_public_id,
                                              "release_public_id"))
        object.__setattr__(self, "dataset_public_id",
                           _require_public_id(self.dataset_public_id,
                                              "dataset_public_id"))
        object.__setattr__(self, "ruleset_public_id",
                           _require_public_id(self.ruleset_public_id,
                                              "ruleset_public_id"))
        object.__setattr__(self, "software_version",
                           _require_public_id(self.software_version,
                                              "software_version"))
        for name in ("release_manifest_hash", "software_hash",
                     "dataset_content_hash", "ruleset_content_hash"):
            object.__setattr__(self, name,
                               _require_digest(getattr(self, name), name))
        if self.resolved_at.tzinfo is None:
            raise UnpinnedError("resolved_at must carry a timezone")

    def identity(self) -> Mapping[str, str]:
        """The fields every observation must echo back, unchanged."""
        return {
            "release_public_id": self.release_public_id,
            "release_manifest_hash": self.release_manifest_hash,
            "software_version": self.software_version,
            "software_hash": self.software_hash,
            "dataset_public_id": self.dataset_public_id,
            "dataset_content_hash": self.dataset_content_hash,
            "ruleset_public_id": self.ruleset_public_id,
            "ruleset_content_hash": self.ruleset_content_hash,
        }

    def to_json(self) -> Dict[str, Any]:
        payload = dict(self.identity())
        payload["resolved_at"] = self.resolved_at.astimezone(
            _dt.timezone.utc).isoformat().replace("+00:00", "Z")
        payload["active_pointer_generation"] = self.active_pointer_generation
        return payload


@dataclass(frozen=True, slots=True)
class BenchmarkPlan:
    """What will be measured, declared before anything is measured.

    ``case_manifest_hashes`` maps a role to the hash of the manifest listing
    that role's cases. One hash per partition rather than one for the union,
    because the partitions are reported separately and a combined hash would
    make a case moving between them invisible.
    """

    plan_id: str
    pinned_release: PinnedRelease
    roles: Tuple[ValidationCaseRole, ...]
    case_manifest_hashes: Mapping[str, str]
    declared_metric_ids: Tuple[str, ...]
    metric_registry_version: str = METRIC_REGISTRY_VERSION
    metric_registry_digest: str = ""
    failure_path_catalogue_version: str = FAILURE_PATH_CATALOGUE_VERSION
    protocol_version: str = BENCHMARK_PROTOCOL_VERSION
    #: Repeats per case. Two or more is what makes PGX-VAL-007 computable.
    repeat_count: int = 1
    note: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "plan_id",
                           _require_public_id(self.plan_id, "plan_id"))
        if not isinstance(self.pinned_release, PinnedRelease):
            raise UnpinnedError("a plan pins a PinnedRelease")
        if not self.roles:
            raise UnpinnedError("a plan names at least one role")
        for role in self.roles:
            if not isinstance(role, ValidationCaseRole):
                raise UnpinnedError("roles are ValidationCaseRole values")
        if len(set(self.roles)) != len(self.roles):
            raise UnpinnedError("a role appears twice in the plan")
        if not self.declared_metric_ids:
            raise UnpinnedError(
                "a plan declares which metrics it will report. Choosing them "
                "after seeing the run is how a flattering subset gets picked.")
        hashes = dict(self.case_manifest_hashes or {})
        for role in self.roles:
            if role.value not in hashes:
                raise UnpinnedError(
                    "no case-manifest hash pinned for role %s" % role.value)
        for name, value in sorted(hashes.items()):
            _require_digest(value, "case_manifest_hashes[%s]" % name)
        object.__setattr__(self, "case_manifest_hashes",
                           {name: str(value)
                            for name, value in sorted(hashes.items())})
        object.__setattr__(self, "roles", tuple(self.roles))
        object.__setattr__(self, "declared_metric_ids",
                           tuple(sorted(set(self.declared_metric_ids))))
        if int(self.repeat_count) < 1:
            raise UnpinnedError("repeat_count is at least 1")
        object.__setattr__(self, "repeat_count", int(self.repeat_count))
        if not self.metric_registry_digest:
            from pgx.validation.metric_definitions import registry_digest
            object.__setattr__(self, "metric_registry_digest",
                               registry_digest())
        _require_digest(self.metric_registry_digest, "metric_registry_digest")

    def to_json(self) -> Dict[str, Any]:
        return {
            "protocol_version": self.protocol_version,
            "plan_id": self.plan_id,
            "pinned_release": self.pinned_release.to_json(),
            "roles": [role.value for role in self.roles],
            "case_manifest_hashes": dict(self.case_manifest_hashes),
            "declared_metric_ids": list(self.declared_metric_ids),
            "metric_registry_version": self.metric_registry_version,
            "metric_registry_digest": self.metric_registry_digest,
            "failure_path_catalogue_version":
                self.failure_path_catalogue_version,
            "repeat_count": self.repeat_count,
            "note": self.note,
        }

    def plan_hash(self) -> str:
        return sha256_digest(self.to_json())


@dataclass(frozen=True, slots=True)
class BenchmarkObservation:
    """What one case did under the pinned release. No expected answer.

    ``output_hashes`` holds one hash per repeat, in execution order. Equality
    across all of them is what PGX-VAL-007 counts; storing the list rather
    than a boolean means a later reader can see *how many* repeats agreed
    rather than trusting a summary computed once.

    ``failure_paths`` names catalogue entries this observation exercised.
    Validated against the catalogue on construction, so a typo becomes an
    error instead of a path that silently never counts.
    """

    case_id: str
    role: ValidationCaseRole
    release_public_id: str
    release_manifest_hash: str
    software_version: str
    software_hash: str
    dataset_public_id: str
    dataset_content_hash: str
    ruleset_public_id: str
    ruleset_content_hash: str
    case_manifest_hash: str
    #: What the engine calculated, as controlled vocabulary values.
    attention_level: Optional[str] = None
    coverage_status: Optional[str] = None
    coverage_reason: Optional[str] = None
    firing_rule_id: Optional[str] = None
    finding_count: int = 0
    traceable_finding_count: int = 0
    unresolved_conflict: bool = False
    output_hashes: Tuple[str, ...] = field(default_factory=tuple)
    failure_paths: Tuple[str, ...] = field(default_factory=tuple)
    refused: bool = False
    refusal_code: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.role, ValidationCaseRole):
            raise BenchmarkError("observation role must be a "
                                 "ValidationCaseRole")
        object.__setattr__(self, "case_id", str(self.case_id))
        for name in ("release_manifest_hash", "software_hash",
                     "dataset_content_hash", "ruleset_content_hash",
                     "case_manifest_hash"):
            _require_digest(getattr(self, name), name)
        catalogue = failure_paths_by_id()
        unknown = sorted(set(self.failure_paths) - set(catalogue))
        if unknown:
            raise BenchmarkError(
                "observation names failure paths absent from the predeclared "
                "catalogue: %s. The catalogue is the denominator; a path "
                "outside it cannot be covered." % ", ".join(unknown))
        object.__setattr__(self, "failure_paths",
                           tuple(sorted(set(self.failure_paths))))
        object.__setattr__(self, "output_hashes",
                           tuple(str(item) for item in self.output_hashes))
        for item in self.output_hashes:
            _require_digest(item, "output_hashes[]")
        if self.traceable_finding_count > self.finding_count:
            raise BenchmarkError(
                "traceable findings (%d) exceed findings (%d)"
                % (self.traceable_finding_count, self.finding_count))
        if self.finding_count < 0 or self.traceable_finding_count < 0:
            raise BenchmarkError("finding counts may not be negative")

    @property
    def repeats_agree(self) -> Optional[bool]:
        """``None`` when fewer than two repeats ran. Not ``True``.

        One execution cannot show repeatability, and reporting ``True`` for it
        would put a case in the numerator of a metric it never tested.
        """
        if len(self.output_hashes) < 2:
            return None
        return len(set(self.output_hashes)) == 1

    def identity(self) -> Mapping[str, str]:
        return {
            "release_public_id": self.release_public_id,
            "release_manifest_hash": self.release_manifest_hash,
            "software_version": self.software_version,
            "software_hash": self.software_hash,
            "dataset_public_id": self.dataset_public_id,
            "dataset_content_hash": self.dataset_content_hash,
            "ruleset_public_id": self.ruleset_public_id,
            "ruleset_content_hash": self.ruleset_content_hash,
        }

    def to_json(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "case_id": self.case_id,
            "role": self.role.value,
            "case_manifest_hash": self.case_manifest_hash,
            "attention_level": self.attention_level,
            "coverage_status": self.coverage_status,
            "coverage_reason": self.coverage_reason,
            "firing_rule_id": self.firing_rule_id,
            "finding_count": self.finding_count,
            "traceable_finding_count": self.traceable_finding_count,
            "unresolved_conflict": self.unresolved_conflict,
            "repeat_count": len(self.output_hashes),
            "repeats_agree": self.repeats_agree,
            "failure_paths": list(self.failure_paths),
            "refused": self.refused,
            "refusal_code": self.refusal_code,
        }
        payload.update(self.identity())
        return payload


@dataclass(frozen=True, slots=True)
class ReferenceJudgment:
    """What a case's answer should be, supplied from outside with provenance.

    Deliberately not part of a validation case. WP-18 stores no expected
    answer so that authoring a case cannot double as writing its answer key;
    a judgment therefore arrives as its own immutable record naming who
    decided it and under which protocol.

    This repository has none. Every metric that needs one is
    ``NO_REFERENCE_JUDGMENT``, which is a different statement from "zero
    correct".
    """

    case_id: str
    expected_attention_level: str
    expected_coverage_status: str
    expected_coverage_reason: Optional[str] = None
    expected_rule_id: Optional[str] = None
    requires_evidence: bool = True
    #: Who decided, under what protocol, and when. Free text by design: the
    #: shape of a provenance record is WP-22's to fix, not WP-21's to guess.
    provenance: str = ""
    recorded_at: Optional[_dt.datetime] = None

    def __post_init__(self) -> None:
        if not str(self.provenance or "").strip():
            raise BenchmarkError(
                "a reference judgment without provenance is an assertion "
                "nobody signed; it may not enter a denominator")

    def to_json(self) -> Dict[str, Any]:
        return {
            "case_id": self.case_id,
            "expected_attention_level": self.expected_attention_level,
            "expected_coverage_status": self.expected_coverage_status,
            "expected_coverage_reason": self.expected_coverage_reason,
            "expected_rule_id": self.expected_rule_id,
            "requires_evidence": self.requires_evidence,
            "provenance": self.provenance,
        }


@dataclass(frozen=True, slots=True)
class BenchmarkRun:
    """A plan plus everything observed under it. Immutable once built."""

    plan: BenchmarkPlan
    observations: Tuple[BenchmarkObservation, ...]
    started_at: _dt.datetime
    finished_at: _dt.datetime
    separation_audit: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "observations", tuple(self.observations))
        seen = set()
        for observation in self.observations:
            key = (observation.case_id, observation.role.value)
            if key in seen:
                raise BenchmarkError(
                    "case %s appears twice for role %s. A repeated case "
                    "inflates a denominator without adding evidence."
                    % (observation.case_id, observation.role.value))
            seen.add(key)

    def for_role(self, role: ValidationCaseRole
                 ) -> Tuple[BenchmarkObservation, ...]:
        return tuple(item for item in self.observations if item.role is role)

    def to_json(self) -> Dict[str, Any]:
        """The run, ordered deterministically by case id within role.

        Sorting here is what makes input order irrelevant to the report hash:
        two runs that executed the same cases in different orders serialise
        identically, so a hash comparison tests the science rather than the
        scheduler.
        """
        ordered = sorted(self.observations,
                         key=lambda item: (item.role.value, item.case_id))
        return {
            "plan": self.plan.to_json(),
            "observation_count": len(ordered),
            "observations": [item.to_json() for item in ordered],
            "separation_audit": dict(self.separation_audit),
        }

    def scientific_digest(self) -> str:
        """A hash over what was measured, excluding when it was measured.

        Timestamps are deliberately outside this. Two identical reruns must
        produce the same digest, and they never produce the same clock
        readings, so including them would make "did we get the same result"
        untestable.
        """
        return sha256_digest(self.to_json())


class ReleaseResolutionPort:
    """Port: find and pin exactly one release, once, before execution."""

    def resolve(self) -> PinnedRelease:  # pragma: no cover - protocol
        raise NotImplementedError


class RestrictedObservationPort:
    """Port: execute the cases of one role and return their observations.

    Holdout payloads live in restricted storage. This port is the only way the
    benchmark sees them, and it returns observations - never payload content -
    so nothing downstream can leak a case into a public artifact.
    """

    def observe(self, *, role: ValidationCaseRole, plan: BenchmarkPlan
                ) -> Sequence[BenchmarkObservation]:  # pragma: no cover
        raise NotImplementedError


class ReferenceJudgmentPort:
    """Port: supply immutable reference judgments, if any exist.

    WP-22 will implement this. Until then an implementation returning an empty
    mapping is the truthful one, and the metrics that need judgments report
    ``NO_REFERENCE_JUDGMENT`` rather than zero.
    """

    def judgments(self, *, role: ValidationCaseRole
                  ) -> Mapping[str, ReferenceJudgment]:  # pragma: no cover
        raise NotImplementedError
