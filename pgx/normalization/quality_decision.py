# -*- coding: utf-8 -*-
"""WP-C06: the named human decision about one dataset build.

WP-07 already carries the transition a decision causes: ``BUILDING ->
QUALITY_CHECKED``, guarded, audited, and refusing a replay. What it has never
carried is the *decision itself*. Its request has no verdict field, so the
only outcome it can express is approval; a data owner who read the report and
said no had nowhere to put that. It also binds the build and the quality
report but not the source policy that was in force when the data was
acquired, and it records a reviewer's name without their role.

This module adds the missing record and nothing else. It does not re-implement
the transition: an approved decision is handed to
:class:`pgx.application.canonical_service.CanonicalDatasetService`, which
still applies its own guard, its own verification and its own audit event.

**What a decision is bound to.** A dataset, a canonical build, the exact
quality report, and the exact source policy. All four are hashes or stable
keys, and all four are re-measured when a decision is used, because a report
that has been regenerated since somebody read it is a different report and an
approval of the old one says nothing about the new one.

**What this module refuses.**

- A decision with no reviewer, no role, no instant or no rationale. There is
  no default reviewer and no generated signature.
- A second decision about the same dataset and the same report. A retry must
  not produce two conflicting verdicts; the first one stands until the report
  changes.
- A decision whose bound digests no longer match what is on disk.
- Any suggestion that ``REJECTED`` moves a dataset forward. A rejection is
  recorded, audited, and changes no state.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import io
import json
import os
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from pgx.normalization.errors import QualityGateError

__all__ = [
    "DECISION_LEDGER_VERSION",
    "DatasetQualityDecision",
    "DecisionResult",
    "DecisionOutcome",
    "QualityDecision",
    "append_decision",
    "load_ledger",
    "measure_binding",
    "render_review_record",
    "verify_decision",
]

DECISION_LEDGER_VERSION = "pgx-wpc06-dataset-quality-decision/1"

#: Where the ledger lives, relative to the repository root.
LEDGER_PATH = os.path.join("data", "canonical", "dataset-quality-decisions.ndjson")


class QualityDecision(str, Enum):
    """The two things a data owner may say, and nothing in between.

    There is deliberately no ``PENDING`` or ``CONDITIONAL``. A decision that
    has not been made is an absent row, which is not the same thing as a
    recorded hesitation and should not be able to look like one.
    """

    APPROVED = "APPROVED"
    REJECTED = "REJECTED"

    @property
    def permits_transition(self) -> bool:
        """Only an approval may move a dataset, and only through WP-07."""
        return self is QualityDecision.APPROVED


class DecisionOutcome(str, Enum):
    """What happened when a decision was offered to the ledger."""

    RECORDED = "RECORDED"
    REFUSED_REPLAY = "REFUSED_REPLAY"
    REFUSED_STALE_BINDING = "REFUSED_STALE_BINDING"
    REFUSED_BUILD_MISSING = "REFUSED_BUILD_MISSING"

    @property
    def is_recorded(self) -> bool:
        return self is DecisionOutcome.RECORDED


def _require_text(value: object, field: str, limit: int = 2000) -> str:
    if not isinstance(value, str) or not value.strip():
        raise QualityGateError(
            "DatasetQualityDecision.%s must be a non-empty string. A quality "
            "decision names a person, their role, an instant and a reason; a "
            "record missing any of them is not a decision." % field)
    text = value.strip()
    if len(text) > limit:
        raise QualityGateError(
            "DatasetQualityDecision.%s is longer than %d characters"
            % (field, limit))
    return text


def _require_digest(value: object, field: str) -> str:
    text = _require_text(value, field, 100)
    body = text[7:] if text.startswith("sha256:") else text
    if len(body) != 64 or any(char not in "0123456789abcdef" for char in body):
        raise QualityGateError(
            "DatasetQualityDecision.%s must be a sha256 digest, got %r"
            % (field, value))
    return "sha256:" + body


@dataclass(frozen=True)
class DatasetQualityDecision:
    """One verdict, by one named person, about one exact build.

    Every field a forged decision would have to invent is required here, and
    the identifier is derived from the bound values rather than supplied, so
    two records that claim to be about the same thing collide instead of
    coexisting.
    """

    dataset_public_id: str
    canonical_build_key: str
    decision: QualityDecision
    reviewer_name: str
    reviewer_role: str
    decided_at: _dt.datetime
    rationale: str
    dq_artifact_hash: str
    source_policy_hash: str

    def __post_init__(self) -> None:
        if not isinstance(self.decision, QualityDecision):
            raise QualityGateError("decision must be a QualityDecision")
        for field in ("dataset_public_id", "canonical_build_key",
                      "reviewer_name", "reviewer_role", "rationale"):
            object.__setattr__(self, field,
                               _require_text(getattr(self, field), field))
        for field in ("dq_artifact_hash", "source_policy_hash"):
            object.__setattr__(self, field,
                               _require_digest(getattr(self, field), field))
        if not isinstance(self.decided_at, _dt.datetime):
            raise QualityGateError("decided_at must be a datetime")
        if self.decided_at.tzinfo is None:
            raise QualityGateError(
                "decided_at must carry a timezone; a bare instant is "
                "ambiguous and a decision's time is part of the record")
        object.__setattr__(self, "decided_at",
                           self.decided_at.astimezone(_dt.timezone.utc))

    @property
    def binding_key(self) -> str:
        """What makes two offers "the same decision" for replay purposes."""
        return "|".join((self.dataset_public_id, self.canonical_build_key,
                         self.dq_artifact_hash))

    @property
    def decision_id(self) -> str:
        """Derived, never supplied, so it cannot disagree with its contents."""
        material = "|".join((
            DECISION_LEDGER_VERSION, self.binding_key, self.source_policy_hash,
            self.decision.value, self.reviewer_name, self.reviewer_role,
            self.decided_at.isoformat(), self.rationale))
        return "DQD-" + hashlib.sha256(
            material.encode("utf-8")).hexdigest()[:24]

    def to_json(self) -> Dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "ledger_version": DECISION_LEDGER_VERSION,
            "dataset_public_id": self.dataset_public_id,
            "canonical_build_key": self.canonical_build_key,
            "decision": self.decision.value,
            "reviewer_name": self.reviewer_name,
            "reviewer_role": self.reviewer_role,
            "decided_at": self.decided_at.isoformat().replace("+00:00", "Z"),
            "rationale": self.rationale,
            "dq_artifact_hash": self.dq_artifact_hash,
            "source_policy_hash": self.source_policy_hash,
            "permits_transition": self.decision.permits_transition,
            "note": ("A recorded decision by one named person about one "
                     "build. An APPROVED decision is a precondition for the "
                     "WP-07 transition, not the transition itself, and never "
                     "a publication or a release."),
        }

    @classmethod
    def from_json(cls, payload: Mapping[str, Any]) -> "DatasetQualityDecision":
        return cls(
            dataset_public_id=payload.get("dataset_public_id"),
            canonical_build_key=payload.get("canonical_build_key"),
            decision=QualityDecision(payload.get("decision")),
            reviewer_name=payload.get("reviewer_name"),
            reviewer_role=payload.get("reviewer_role"),
            decided_at=_dt.datetime.fromisoformat(
                str(payload.get("decided_at", "")).replace("Z", "+00:00")),
            rationale=payload.get("rationale"),
            dq_artifact_hash=payload.get("dq_artifact_hash"),
            source_policy_hash=payload.get("source_policy_hash"))


# ---------------------------------------------------------------------------
# Binding: what a decision is about, measured rather than trusted
# ---------------------------------------------------------------------------

def _read_json(path: str) -> Optional[Dict[str, Any]]:
    if not os.path.isfile(path):
        return None
    try:
        with io.open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def _canonical_digest(value: object) -> Optional[str]:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    body = text[7:] if text.startswith("sha256:") else text
    if len(body) != 64:
        return None
    return "sha256:" + body


def measure_binding(build_path: str,
                    source_registry_path: str) -> Dict[str, Optional[str]]:
    """The four things a decision binds to, read from disk right now.

    The quality report's own ``content_hash`` is used rather than a digest of
    the file, because that is the value the report publishes about itself and
    the one every other artifact in this repository cites. The source policy
    is digested from its bytes, because the registry publishes no such field.
    """
    report = _read_json(os.path.join(build_path, "dq-report.json"))
    manifest = _read_json(os.path.join(build_path, "manifest.json"))
    policy_hash: Optional[str] = None
    if os.path.isfile(source_registry_path):
        digest = hashlib.sha256()
        with io.open(source_registry_path, "rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                digest.update(block)
        policy_hash = "sha256:" + digest.hexdigest()
    return {
        "dataset_public_id": (manifest or {}).get("dataset_public_id"),
        "canonical_build_key": (manifest or {}).get("canonical_build_key"),
        "dq_artifact_hash": _canonical_digest((report or {}).get("content_hash")),
        "source_policy_hash": policy_hash,
    }


def verify_decision(decision: DatasetQualityDecision, build_path: str,
                    source_registry_path: str) -> Tuple[bool, Tuple[str, ...]]:
    """Is this decision still about what is on disk?

    Returns ``(ok, problems)``. Each problem names the field, what the
    decision bound and what is there now, because "stale" on its own tells a
    reader nothing about which half moved.
    """
    measured = measure_binding(build_path, source_registry_path)
    problems: List[str] = []
    for field in ("dataset_public_id", "canonical_build_key",
                  "dq_artifact_hash", "source_policy_hash"):
        expected = getattr(decision, field)
        actual = measured.get(field)
        if actual is None:
            problems.append("%s could not be measured from the build or the "
                            "source registry" % field)
        elif actual != expected:
            problems.append("%s changed since the decision: bound %s, "
                            "measured %s" % (field, expected, actual))
    return (not problems), tuple(problems)


# ---------------------------------------------------------------------------
# The append-only ledger
# ---------------------------------------------------------------------------

def load_ledger(path: str) -> Tuple[DatasetQualityDecision, ...]:
    """Every decision recorded so far, oldest first."""
    if not os.path.isfile(path):
        return ()
    rows: List[DatasetQualityDecision] = []
    with io.open(path, encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(DatasetQualityDecision.from_json(json.loads(line)))
    return tuple(rows)


@dataclass(frozen=True)
class DecisionResult:
    """What the ledger did with an offered decision, and why."""

    outcome: DecisionOutcome
    decision: Optional[DatasetQualityDecision] = None
    existing: Optional[DatasetQualityDecision] = None
    problems: Tuple[str, ...] = ()
    detail: str = ""

    def to_json(self) -> Dict[str, Any]:
        return {
            "outcome": self.outcome.value,
            "recorded": self.outcome.is_recorded,
            "decision": self.decision.to_json() if self.decision else None,
            "conflicting_existing_decision":
                self.existing.to_json() if self.existing else None,
            "problems": list(self.problems),
            "detail": self.detail,
        }


def append_decision(decision: DatasetQualityDecision, build_path: str,
                    source_registry_path: str,
                    ledger_path: str) -> DecisionResult:
    """Record a decision, or refuse and say exactly which rule refused it.

    The order is the order of the questions: does the thing being decided
    about still exist, is the decision still about it, and has somebody
    already decided this. Only then is anything written, and the write
    appends - a decision is never edited, because the record of a mind
    changing is two rows, not one row that has been altered.
    """
    if not os.path.isdir(build_path):
        return DecisionResult(
            outcome=DecisionOutcome.REFUSED_BUILD_MISSING,
            decision=decision,
            detail="there is no build at %s to decide about" % build_path)

    ok, problems = verify_decision(decision, build_path, source_registry_path)
    if not ok:
        return DecisionResult(
            outcome=DecisionOutcome.REFUSED_STALE_BINDING,
            decision=decision, problems=problems,
            detail=("the decision no longer describes what is on disk. A "
                    "regenerated report is a different report, and an "
                    "approval of the old one says nothing about it."))

    for existing in load_ledger(ledger_path):
        if existing.binding_key == decision.binding_key:
            return DecisionResult(
                outcome=DecisionOutcome.REFUSED_REPLAY,
                decision=decision, existing=existing,
                detail=("%s already decided this build on %s. A retry must "
                        "not produce a second verdict; change the report or "
                        "record a superseding decision deliberately."
                        % (existing.reviewer_name,
                           existing.decided_at.isoformat())))

    os.makedirs(os.path.dirname(ledger_path) or ".", exist_ok=True)
    line = json.dumps(decision.to_json(), sort_keys=True,
                      ensure_ascii=False) + "\n"
    with io.open(ledger_path, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(line)
    return DecisionResult(
        outcome=DecisionOutcome.RECORDED, decision=decision,
        detail=("recorded as %s by %s (%s). %s"
                % (decision.decision.value, decision.reviewer_name,
                   decision.reviewer_role,
                   "It is a precondition for the WP-07 transition, which is a "
                   "separate act." if decision.decision.permits_transition
                   else "The dataset does not move and is not "
                        "release-eligible.")))


def render_review_record(decisions: Sequence[DatasetQualityDecision]) -> str:
    """The ledger, for a reader."""
    lines = [
        "# Dataset quality decisions",
        "",
        "Generated from `%s`. Each row is one named person's verdict on one "
        "exact build, bound to that build's quality report and to the source "
        "policy in force. Do not edit by hand." % LEDGER_PATH,
        "",
    ]
    if not decisions:
        lines += [
            "**No decision has been recorded.** That is not the same as a "
            "dataset having failed review: it means nobody has reviewed one. "
            "A quality report that passes its gate is a precondition for a "
            "decision, never a substitute for it.",
            "",
        ]
        return "\n".join(lines) + "\n"
    lines += ["| decision | dataset | build | reviewer | role | decided | "
              "DQ report | source policy |",
              "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for item in decisions:
        lines.append("| `%s` | `%s` | `%s` | %s | %s | %s | `%s` | `%s` |"
                     % (item.decision.value, item.dataset_public_id,
                        item.canonical_build_key, item.reviewer_name,
                        item.reviewer_role,
                        item.decided_at.isoformat().replace("+00:00", "Z"),
                        item.dq_artifact_hash[:23] + "...",
                        item.source_policy_hash[:23] + "..."))
    lines.append("")
    return "\n".join(lines) + "\n"
