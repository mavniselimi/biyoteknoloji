# -*- coding: utf-8 -*-
"""The record types the evidence pack is made of (WP-25).

Every constraint in this module is a constructor-time refusal rather than a
validator somebody must remember to call. The reason is specific to this work
package: an evidence pack is read once, late, by somebody deciding whether to
believe a claim, and a malformed record that reached a document would be a
record nobody re-checked.

Four refusals are worth naming because each corresponds to a way a pack
becomes dishonest:

* **an absolute path** - a pack that leaks ``/Users/<somebody>/...`` is a pack
  produced on one machine and describing that machine, and it also discloses
  a person. Paths are repository-relative or the record does not exist.
* **an unowned gap** - a limitation nobody owns is a limitation nobody clears.
* **a numeric claim with no evidence** - the field ``contains_numeric_claim``
  exists so the claim scanner can find every number this pack asserts; a
  number with no cited artifact is the exact failure mode WP-15 was built to
  catch.
* **a test-only item claiming to be real** - ``test_only`` and
  ``evidence_type`` must agree, and the agreement is checked here rather than
  trusted, because the substitution of a passing test for a real result is the
  single most likely way this project would overstate itself.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Mapping, Optional, Sequence, Tuple

from pgx.ths6.vocabulary import (BLOCKER_CODES, Blocker, ClaimSupport,
                                 EvidenceType, GateResult)

__all__ = [
    "EVIDENCE_ID_PATTERN",
    "MEDIA_TYPES",
    "THS6_MODEL_VERSION",
    "ClaimRecord",
    "DefinitionOfDoneItem",
    "EvidenceItem",
    "Finding",
    "GateCondition",
    "GateRecord",
    "TraceabilityRow",
    "repository_relative",
]

THS6_MODEL_VERSION = "pgx-wp25-ths6-model/1"

#: ``EV-<WP>-<NNN>``: the work package that produced it and a stable ordinal.
#: Encoding the work package in the identifier means a reader can tell where
#: an item came from without a lookup, and means two work packages cannot
#: collide by both reaching ``007``.
EVIDENCE_ID_PATTERN = re.compile(r"^EV-WP(?:0[0-9]|1[0-9]|2[0-5])-[0-9]{3}$")

#: Claim identifiers, gate identifiers and DoD identifiers.
CLAIM_ID_PATTERN = re.compile(r"^THS6-CLAIM-[0-9]{3}$")
GATE_ID_PATTERN = re.compile(r"^GATE-[A-F]$")
DOD_ID_PATTERN = re.compile(r"^P0-DOD-0(?:0[1-9]|1[0-5])$")

#: What an artifact is, by suffix. Recorded per item so a reader knows whether
#: an item is machine-checkable without opening it.
MEDIA_TYPES: Mapping[str, str] = {
    ".json": "application/json",
    ".md": "text/markdown",
    ".py": "text/x-python",
    ".yml": "application/yaml",
    ".yaml": "application/yaml",
    ".png": "image/png",
    ".toml": "application/toml",
    ".txt": "text/plain",
    ".html": "text/html",
    ".sql": "application/sql",
    ".csv": "text/csv",
}

#: A path that starts with any of these is not repository-relative. Checked
#: as a rule rather than by looking for one user's home directory, because the
#: pack must be safe to produce on a machine nobody here has seen.
_ABSOLUTE_PREFIXES = ("/", "~", "\\\\")
_DRIVE_LETTER = re.compile(r"^[A-Za-z]:[\\/]")


def repository_relative(path: str) -> str:
    """Return ``path`` if it is repository-relative; raise if it is not.

    Rejects absolute POSIX paths, home-relative paths, Windows drive letters,
    UNC paths, and any path that climbs out of the tree with ``..``. The last
    matters because ``docs/../../etc/passwd`` is relative in spelling and
    absolute in effect.
    """
    if not path or not path.strip():
        raise ValueError("an evidence item names a path")
    if path.startswith(_ABSOLUTE_PREFIXES) or _DRIVE_LETTER.match(path):
        raise ValueError(
            "%r is an absolute path; an evidence pack that records one "
            "describes the machine it was built on and discloses whoever "
            "built it" % (path,))
    parts = path.replace("\\", "/").split("/")
    if ".." in parts:
        raise ValueError(
            "%r climbs out of the repository; relative in spelling is not "
            "relative in effect" % (path,))
    return path


@dataclass(frozen=True)
class Finding:
    """One thing WP-25 noticed that somebody has to resolve.

    Findings are not blockers. A blocker says a condition is unmet; a finding
    says a document, a count or an artifact is *wrong*, and wrongness has an
    owner and a resolution even when it blocks nothing.
    """

    code: str
    detail: str
    owner: str
    #: What WP-25 did in the meantime. Never "ignored".
    resolution: str
    #: Whether the finding, on its own, prevents a gate from passing.
    blocking: bool = False
    references: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.code not in BLOCKER_CODES:
            raise ValueError(
                "%r is not a declared WP-25 code" % (self.code,))
        for name in ("detail", "owner", "resolution"):
            if not getattr(self, name).strip():
                raise ValueError("a finding states its %s" % name)

    def to_json(self) -> Mapping[str, object]:
        return {"code": self.code, "detail": self.detail, "owner": self.owner,
                "resolution": self.resolution, "blocking": self.blocking,
                "references": list(self.references)}


@dataclass(frozen=True)
class EvidenceItem:
    """One artifact in the pack, and everything a reviewer needs about it.

    ``sha256`` and ``present`` are separate fields with a deliberate
    relationship: an absent item has no digest, and an item that claims a
    digest while absent is a contradiction the constructor refuses. This is
    the same ``null``-is-not-zero discipline WP-24 applied to latency.
    """

    evidence_id: str
    title: str
    work_package: str
    evidence_type: EvidenceType
    path: str
    #: Present-tense observation of the repository, filled by the registry.
    present: bool = False
    sha256: Optional[str] = None
    media_type: Optional[str] = None
    #: The schema this artifact declares itself against, when it has one.
    schema_path: Optional[str] = None
    #: What produced it: a command, a module, a person, a document.
    generator: str = ""
    #: Whether the artifact records a real event, in its own words.
    observed_or_executed: bool = False
    #: Whether it came from fixtures. Must agree with ``evidence_type``.
    test_only: bool = False
    #: Whether the artifact asserts a number that could be quoted outward.
    contains_numeric_claim: bool = False
    supported_claim_ids: Tuple[str, ...] = ()
    gate_ids: Tuple[str, ...] = ()
    #: The artifact whose change would make this one stale. Empty when the
    #: item is its own source.
    freshness_source: Optional[str] = None
    #: Filled by the registry: whether it validated against ``schema_path``.
    validation_result: Optional[str] = None
    limitations: Tuple[str, ...] = ()
    #: Who resolves what this item does not cover. Required whenever the item
    #: has a limitation, because an unowned gap is one nobody clears.
    gap_owner: Optional[str] = None

    def __post_init__(self) -> None:
        if not EVIDENCE_ID_PATTERN.match(self.evidence_id):
            raise ValueError(
                "%r is not a WP-25 evidence id (EV-WPnn-nnn)"
                % (self.evidence_id,))
        if not self.title.strip():
            raise ValueError("%s states a title" % self.evidence_id)
        repository_relative(self.path)
        if self.test_only and self.evidence_type.may_support_a_ths6_claim:
            raise ValueError(
                "%s is marked test-only and typed %s; a fixture result may "
                "never be typed as a real one"
                % (self.evidence_id, self.evidence_type))
        if (self.evidence_type is EvidenceType.TEST_ONLY_REHEARSAL
                and not self.test_only):
            raise ValueError(
                "%s is typed TEST_ONLY_REHEARSAL but not marked test-only"
                % (self.evidence_id,))
        if self.observed_or_executed and not (
                self.evidence_type.may_support_a_ths6_claim):
            raise ValueError(
                "%s claims a real observation but is typed %s"
                % (self.evidence_id, self.evidence_type))
        if self.limitations and not (self.gap_owner or "").strip():
            raise ValueError(
                "%s records a limitation with no owner; an unowned gap is "
                "one nobody clears" % (self.evidence_id,))
        for claim_id in self.supported_claim_ids:
            if not CLAIM_ID_PATTERN.match(claim_id):
                raise ValueError(
                    "%s cites %r, which is not a claim id"
                    % (self.evidence_id, claim_id))
        for gate_id in self.gate_ids:
            if not GATE_ID_PATTERN.match(gate_id):
                raise ValueError(
                    "%s cites %r, which is not a gate id"
                    % (self.evidence_id, gate_id))
        if self.freshness_source is not None:
            repository_relative(self.freshness_source)
        if self.schema_path is not None:
            repository_relative(self.schema_path)

    @property
    def declared_media_type(self) -> Optional[str]:
        suffix = os.path.splitext(self.path)[1].lower()
        return MEDIA_TYPES.get(suffix)

    def to_json(self) -> Mapping[str, object]:
        return {
            "evidence_id": self.evidence_id,
            "title": self.title,
            "work_package": self.work_package,
            "evidence_type": self.evidence_type.value,
            "path": self.path,
            "present": self.present,
            "sha256": self.sha256,
            "media_type": self.media_type or self.declared_media_type,
            "schema_path": self.schema_path,
            "generator": self.generator,
            "observed_or_executed": self.observed_or_executed,
            "test_only": self.test_only,
            "contains_numeric_claim": self.contains_numeric_claim,
            "may_support_a_ths6_claim":
                self.evidence_type.may_support_a_ths6_claim,
            "supported_claim_ids": list(self.supported_claim_ids),
            "gate_ids": list(self.gate_ids),
            "freshness_source": self.freshness_source,
            "validation_result": self.validation_result,
            "limitations": list(self.limitations),
            "gap_owner": self.gap_owner,
        }


@dataclass(frozen=True)
class ClaimRecord:
    """One statement the project might make, and what would justify it.

    ``required_evidence_ids`` is the conjunction. A claim is SUPPORTED only
    when every one of them resolves to a present, admissible item - there is
    no weighting, no "most of", and no partial credit that rounds up.
    """

    claim_id: str
    statement: str
    #: Where the claim comes from: an architecture section, a DoD item, a
    #: work package. A claim with no origin is one nobody asked for.
    origin: str
    required_evidence_ids: Tuple[str, ...]
    gate_id: Optional[str] = None
    dod_ids: Tuple[str, ...] = ()
    #: Whether the statement, if made publicly, would be a clinical or
    #: diagnostic claim. Those carry the strictest boundary in WP-15/WP-20.
    outward_facing: bool = False
    support: ClaimSupport = ClaimSupport.NOT_EVALUATED
    missing_evidence_ids: Tuple[str, ...] = ()
    notes: str = ""

    def __post_init__(self) -> None:
        if not CLAIM_ID_PATTERN.match(self.claim_id):
            raise ValueError(
                "%r is not a claim id (THS6-CLAIM-nnn)" % (self.claim_id,))
        if not self.statement.strip():
            raise ValueError("%s states a claim" % self.claim_id)
        if not self.origin.strip():
            raise ValueError(
                "%s names where the claim comes from" % self.claim_id)
        if not self.required_evidence_ids:
            raise ValueError(
                "%s requires no evidence; a claim that needs nothing is one "
                "nothing can refute" % self.claim_id)
        for evidence_id in self.required_evidence_ids:
            if not EVIDENCE_ID_PATTERN.match(evidence_id):
                raise ValueError(
                    "%s requires %r, which is not an evidence id"
                    % (self.claim_id, evidence_id))
        if self.gate_id is not None and not GATE_ID_PATTERN.match(
                self.gate_id):
            raise ValueError(
                "%s cites %r, which is not a gate id"
                % (self.claim_id, self.gate_id))
        for dod_id in self.dod_ids:
            if not DOD_ID_PATTERN.match(dod_id):
                raise ValueError(
                    "%s cites %r, which is not a DoD id"
                    % (self.claim_id, dod_id))

    def to_json(self) -> Mapping[str, object]:
        return {
            "claim_id": self.claim_id,
            "statement": self.statement,
            "origin": self.origin,
            "required_evidence_ids": list(self.required_evidence_ids),
            "gate_id": self.gate_id,
            "dod_ids": list(self.dod_ids),
            "outward_facing": self.outward_facing,
            "support": self.support.value,
            "sufficient": self.support.is_sufficient,
            "missing_evidence_ids": list(self.missing_evidence_ids),
            "notes": self.notes,
        }


@dataclass(frozen=True)
class GateCondition:
    """One mandatory condition of one gate.

    ``met`` is ``Optional[bool]`` rather than ``bool`` for the same reason
    WP-24's latency is nullable: "we did not evaluate this" is a third state,
    and collapsing it into ``False`` would make an unevaluated gate look
    merely blocked, which is a smaller problem than it is.
    """

    condition_id: str
    description: str
    #: The artifact this condition was read from, repository-relative.
    source_path: str
    #: The field inside that artifact. Named so a reviewer can check it.
    source_field: str
    expected: str
    observed: str
    met: Optional[bool]
    blocker: Optional[Blocker] = None

    def __post_init__(self) -> None:
        repository_relative(self.source_path)
        if not self.description.strip():
            raise ValueError("%s describes itself" % self.condition_id)
        if self.met is False and self.blocker is None:
            raise ValueError(
                "%s is unmet and names no blocker; an unmet condition with "
                "no owner is one nobody clears" % (self.condition_id,))
        if self.met is True and self.blocker is not None:
            raise ValueError(
                "%s is met and also carries a blocker" % (self.condition_id,))

    def to_json(self) -> Mapping[str, object]:
        return {
            "condition_id": self.condition_id,
            "description": self.description,
            "source_path": self.source_path,
            "source_field": self.source_field,
            "expected": self.expected,
            "observed": self.observed,
            "met": self.met,
            "blocker": self.blocker.to_json() if self.blocker else None,
        }


@dataclass(frozen=True)
class GateRecord:
    """One gate, its conditions and the conclusion they force.

    The conclusion is *derived* in ``gate_matrix``; it is stored here so the
    serialised document carries it, and the constructor re-checks the
    derivation. A gate whose stored result disagrees with its own conditions
    is refused rather than reported, because that disagreement is exactly the
    shape a manual override would take.
    """

    gate_id: str
    title: str
    conditions: Tuple[GateCondition, ...]
    result: GateResult
    blockers: Tuple[Blocker, ...] = ()
    #: Gates that must PASS before this one may. Gate F depends on A-E.
    depends_on: Tuple[str, ...] = ()
    findings: Tuple[Finding, ...] = ()
    notes: str = ""

    def __post_init__(self) -> None:
        if not GATE_ID_PATTERN.match(self.gate_id):
            raise ValueError("%r is not a gate id" % (self.gate_id,))
        if not self.conditions:
            raise ValueError(
                "%s has no conditions; a gate with nothing to check would "
                "pass for free" % self.gate_id)
        if self.result is GateResult.PASS:
            unmet = [item.condition_id for item in self.conditions
                     if item.met is not True]
            if unmet:
                raise ValueError(
                    "%s is recorded PASS with unmet or unevaluated "
                    "conditions %s" % (self.gate_id, sorted(unmet)))
            if self.blockers:
                raise ValueError(
                    "%s is recorded PASS while carrying %d blocker(s)"
                    % (self.gate_id, len(self.blockers)))

    @property
    def unmet_condition_ids(self) -> Tuple[str, ...]:
        return tuple(item.condition_id for item in self.conditions
                     if item.met is not True)

    def to_json(self) -> Mapping[str, object]:
        return {
            "gate_id": self.gate_id,
            "title": self.title,
            "result": self.result.value,
            "is_pass": self.result.is_pass,
            "condition_count": len(self.conditions),
            "met_condition_count": sum(1 for item in self.conditions
                                       if item.met is True),
            "unmet_condition_ids": list(self.unmet_condition_ids),
            "conditions": [item.to_json() for item in self.conditions],
            "blockers": [item.to_json() for item in self.blockers],
            "depends_on": list(self.depends_on),
            "findings": [item.to_json() for item in self.findings],
            "notes": self.notes,
        }


@dataclass(frozen=True)
class DefinitionOfDoneItem:
    """One P0 Definition of Done bullet, evaluated on its own.

    ``architecture_text`` holds the bullet verbatim. Storing the original
    wording rather than a paraphrase is what makes the count discrepancy
    between the prose and the enumeration checkable by a reader who has the
    architecture document open beside the artifact.
    """

    dod_id: str
    architecture_text: str
    #: What would have to be true, stated so it can be checked.
    observable_condition: str
    satisfied: Optional[bool]
    evidence_ids: Tuple[str, ...] = ()
    gate_ids: Tuple[str, ...] = ()
    blockers: Tuple[Blocker, ...] = ()
    #: Who supplies the missing thing. Required when not satisfied.
    owner: Optional[str] = None
    notes: str = ""

    def __post_init__(self) -> None:
        if not DOD_ID_PATTERN.match(self.dod_id):
            raise ValueError(
                "%r is not a DoD id (P0-DOD-001..015)" % (self.dod_id,))
        if not self.architecture_text.strip():
            raise ValueError(
                "%s carries the architecture bullet verbatim" % self.dod_id)
        if not self.observable_condition.strip():
            raise ValueError(
                "%s states an observable condition" % self.dod_id)
        if self.satisfied is not True and not (self.owner or "").strip():
            raise ValueError(
                "%s is not satisfied and names no owner" % self.dod_id)
        if self.satisfied is False and not self.blockers:
            raise ValueError(
                "%s is unsatisfied and names no blocker" % self.dod_id)

    def to_json(self) -> Mapping[str, object]:
        return {
            "dod_id": self.dod_id,
            "architecture_text": self.architecture_text,
            "observable_condition": self.observable_condition,
            "satisfied": self.satisfied,
            "evidence_ids": list(self.evidence_ids),
            "gate_ids": list(self.gate_ids),
            "blockers": [item.to_json() for item in self.blockers],
            "owner": self.owner,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class TraceabilityRow:
    """One row of requirement to result, with nowhere to hide a gap.

    Every field is a list of identifiers that must resolve. The matrix
    refuses dangling references, which is what turns this from a table
    somebody wrote into a table somebody can check.
    """

    row_id: str
    requirement: str
    #: Where the requirement is written down.
    requirement_source: str
    implementation_paths: Tuple[str, ...]
    test_paths: Tuple[str, ...]
    evidence_ids: Tuple[str, ...]
    claim_ids: Tuple[str, ...]
    gate_ids: Tuple[str, ...]
    dod_ids: Tuple[str, ...]
    result: ClaimSupport
    #: Required whenever ``result`` is anything but SUPPORTED.
    gap_owner: Optional[str] = None
    gap: str = ""

    def __post_init__(self) -> None:
        if not self.requirement.strip():
            raise ValueError("%s states a requirement" % self.row_id)
        for path in tuple(self.implementation_paths) + tuple(self.test_paths):
            repository_relative(path)
        if not self.result.is_sufficient and not (self.gap_owner or "").strip():
            raise ValueError(
                "%s is %s and names no gap owner"
                % (self.row_id, self.result))
        if not self.result.is_sufficient and not self.gap.strip():
            raise ValueError(
                "%s is %s and does not say what is missing"
                % (self.row_id, self.result))

    def to_json(self) -> Mapping[str, object]:
        return {
            "row_id": self.row_id,
            "requirement": self.requirement,
            "requirement_source": self.requirement_source,
            "implementation_paths": list(self.implementation_paths),
            "test_paths": list(self.test_paths),
            "evidence_ids": list(self.evidence_ids),
            "claim_ids": list(self.claim_ids),
            "gate_ids": list(self.gate_ids),
            "dod_ids": list(self.dod_ids),
            "result": self.result.value,
            "gap": self.gap,
            "gap_owner": self.gap_owner,
        }
