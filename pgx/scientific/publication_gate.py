# -*- coding: utf-8 -*-
"""Deterministic dataset publication eligibility (WP-05).

Standard library plus :mod:`pgx.scientific` and ``pgx.domain``.

**One question, one answer.** Given a registry, a statement of what a dataset
intends to do with its sources, and an instant, this module answers whether the
dataset may be published - and if not, exactly why, in stable codes.

**The intent matters.** "May we use CPIC?" is not a question with an answer. A
dataset that stores records and analyses them internally touches three reuse
dimensions; one that also shows source text to an end user touches a fourth;
one that redistributes records verbatim touches a fifth, and it is entirely
ordinary for a source to permit the first three and forbid the fifth.
:class:`PublicationIntent` is how a caller says which questions actually arise,
so the gate checks those and not a guessed superset.

**Fail closed at every join.**

* A source the registry does not carry blocks. Absence of policy is not
  absence of restriction.
* An unanswered reuse dimension blocks exactly as a prohibited one does.
* A claim category no approved source supports blocks; the dataset would
  otherwise assert something nothing backs.
* An unresolved conflict touching a cited source blocks, including one whose
  materiality nobody has judged.
* An empty source list blocks. A dataset citing nothing has nothing behind it.

**Deterministic.** The same inputs produce the same issues in the same order
and therefore the same :meth:`PublicationEligibility.digest`. The evaluation
instant is an argument, never the wall clock, so a report can be reproduced.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple

from pgx.domain.hashing import sha256_digest
from pgx.scientific.conflict import ConflictRegister
from pgx.scientific.models import ClaimCategory, ReuseDimension, SourceConflict
from pgx.scientific.validation import (
    CORE_PUBLICATION_DIMENSIONS,
    IssueSeverity,
    PolicyIssue,
    PolicyIssueCode,
    blocking_issues,
    issue_summary,
    sort_issues,
    validate_source,
)

__all__ = [
    "PublicationDecision",
    "PublicationEligibility",
    "PublicationIntent",
    "evaluate_publication",
]

#: Which extra reuse dimension each optional intent flag brings into scope.
_INTENT_DIMENSIONS: Tuple[Tuple[str, ReuseDimension], ...] = (
    ("displays_source_text", ReuseDimension.PUBLIC_DISPLAY),
    ("redistributes_aggregated", ReuseDimension.AGGREGATED_REDISTRIBUTION),
    ("redistributes_verbatim", ReuseDimension.VERBATIM_REDISTRIBUTION),
    ("shares_with_third_party", ReuseDimension.THIRD_PARTY_SHARING),
    ("commercial_use", ReuseDimension.COMMERCIAL_USE),
    ("automated_acquisition", ReuseDimension.AUTOMATED_ACQUISITION),
    ("bulk_download", ReuseDimension.BULK_DOWNLOAD),
)


class PublicationDecision(str, Enum):
    """The gate's verdict.

    Two values, not three. There is no "eligible with warnings": a warning that
    could let publication through would be a blocker written softly.
    """

    ELIGIBLE = "ELIGIBLE"
    BLOCKED = "BLOCKED"

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class PublicationIntent:
    """What a dataset proposes to do with its sources.

    Every flag defaults to ``False`` - the narrowest intent - so a caller that
    forgets one asks for *less* permission rather than more.

    ``claim_categories`` names what the dataset intends to assert. Each one must
    be backed by at least one source approved for that category; a dataset that
    carries prescribing recommendations while no source is cleared to supply
    them is exactly the failure this field catches.
    """

    dataset_key: str
    source_keys: Tuple[str, ...] = ()
    claim_categories: Tuple[ClaimCategory, ...] = ()
    displays_source_text: bool = False
    redistributes_aggregated: bool = False
    redistributes_verbatim: bool = False
    shares_with_third_party: bool = False
    commercial_use: bool = False
    automated_acquisition: bool = False
    bulk_download: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.dataset_key, str) or not self.dataset_key.strip():
            raise ValueError("dataset_key must be a non-blank string")
        keys = tuple(self.source_keys or ())
        for key in keys:
            if not isinstance(key, str) or not key.strip():
                raise ValueError("source_keys must contain non-blank strings")
        object.__setattr__(self, "source_keys", tuple(sorted(set(keys))))
        categories = tuple(self.claim_categories or ())
        for category in categories:
            if not isinstance(category, ClaimCategory):
                raise ValueError("claim_categories must contain ClaimCategory members")
        object.__setattr__(
            self, "claim_categories",
            tuple(sorted(set(categories), key=lambda item: item.value)))
        for name, _dimension in _INTENT_DIMENSIONS:
            if not isinstance(getattr(self, name), bool):
                raise ValueError("%s must be a bool" % name)

    @property
    def required_dimensions(self) -> Tuple[ReuseDimension, ...]:
        """Every reuse dimension this intent puts in scope, in canonical order.

        The three core dimensions are always in scope: any use at all stores
        records, reads them and derives from them.
        """
        required = list(CORE_PUBLICATION_DIMENSIONS)
        for name, dimension in _INTENT_DIMENSIONS:
            if getattr(self, name) and dimension not in required:
                required.append(dimension)
        canonical = tuple(ReuseDimension)
        return tuple(d for d in canonical if d in required)

    def to_json(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "dataset_key": self.dataset_key,
            "source_keys": list(self.source_keys),
            "claim_categories": [c.value for c in self.claim_categories],
        }
        for name, _dimension in _INTENT_DIMENSIONS:
            payload[name] = getattr(self, name)
        payload["required_dimensions"] = [d.value for d in self.required_dimensions]
        return payload


@dataclass(frozen=True, slots=True)
class PublicationEligibility:
    """The gate's full answer: a verdict plus every reason behind it.

    Nothing short-circuits. A caller repairing a dataset wants the whole list,
    and a report that stopped at the first blocker would make each fix reveal
    one more.
    """

    decision: PublicationDecision
    dataset_key: str
    evaluated_at: _dt.datetime
    issues: Tuple[PolicyIssue, ...] = ()
    evaluated_source_keys: Tuple[str, ...] = ()
    registry_content_hash: Optional[str] = None

    @property
    def is_eligible(self) -> bool:
        return self.decision is PublicationDecision.ELIGIBLE

    @property
    def blockers(self) -> Tuple[PolicyIssue, ...]:
        return blocking_issues(self.issues)

    @property
    def blocking_codes(self) -> Tuple[str, ...]:
        """Sorted, duplicate-free codes, for a caller matching on the class."""
        return tuple(sorted({issue.code.value for issue in self.blockers}))

    def to_json(self) -> Dict[str, Any]:
        return {
            "decision": self.decision.value,
            "dataset_key": self.dataset_key,
            "evaluated_at": self.evaluated_at.astimezone(
                _dt.timezone.utc).isoformat().replace("+00:00", "Z"),
            "evaluated_source_keys": list(self.evaluated_source_keys),
            "registry_content_hash": self.registry_content_hash,
            "summary": issue_summary(self.issues),
            "issues": [issue.to_json() for issue in self.issues],
        }

    def digest(self) -> str:
        """Canonical digest of the verdict, for an evidence record.

        Includes the evaluation instant: the same registry can legitimately give
        a different answer after a review expires, and a digest that hid that
        would make two different verdicts look like one.
        """
        return sha256_digest(self.to_json())

    def render(self) -> str:
        """Human-readable report. Stable line order."""
        lines = [
            "dataset:  %s" % self.dataset_key,
            "decision: %s" % self.decision.value,
            "at:       %s" % self.evaluated_at.isoformat(),
            "sources:  %s" % (", ".join(self.evaluated_source_keys) or "(none)"),
        ]
        counts = issue_summary(self.issues)
        lines.append("issues:   %d blocking, %d warning, %d info"
                     % (counts["BLOCKER"], counts["WARNING"], counts["INFO"]))
        for issue in self.issues:
            lines.append("  " + issue.render())
        return "\n".join(lines)


def evaluate_publication(
    registry: Any,
    intent: PublicationIntent,
    now: _dt.datetime,
    conflicts: Optional[Sequence[SourceConflict]] = None,
) -> PublicationEligibility:
    """Decide whether a dataset may be published, and say why not.

    Args:
        registry: anything exposing ``records`` and (optionally) ``conflicts``
            and ``content_hash()`` - normally a
            :class:`~pgx.scientific.policy.SourcePolicyRegistry`.
        intent: what the dataset proposes to do with its sources.
        now: the instant to evaluate against. An argument, never the wall
            clock, so the verdict is reproducible.
        conflicts: conflicts to consider. Defaults to the registry's own.

    Returns:
        A :class:`PublicationEligibility` whose ``decision`` is ``ELIGIBLE``
        only when no blocking issue was found.
    """
    issues: List[PolicyIssue] = []
    required = intent.required_dimensions

    if not intent.source_keys:
        issues.append(PolicyIssue(
            PolicyIssueCode.REGISTRY_EMPTY, IssueSeverity.BLOCKER,
            intent.dataset_key,
            "the dataset names no sources. A dataset that cites nothing has "
            "nothing standing behind it and may not be published."))

    known: List[Any] = []
    for source_key in intent.source_keys:
        record = registry.get(source_key)
        if record is None:
            issues.append(PolicyIssue(
                PolicyIssueCode.SOURCE_UNREGISTERED, IssueSeverity.BLOCKER,
                source_key,
                "the dataset cites a source with no policy record. An "
                "unregistered source has no permissions, not unlimited ones."))
            continue
        known.append(record)
        issues.extend(validate_source(record, now, required))

    # Each intended claim category needs at least one source cleared for it.
    for category in intent.claim_categories:
        supporting = tuple(r for r in known if r.may_support_claim(category, now))
        if not supporting:
            # One cleared source is enough. A dataset may legitimately cite a
            # source that backs a different category, so the sources that do
            # not support this one are not themselves a finding.
            issues.append(PolicyIssue(
                PolicyIssueCode.NO_CLAIM_CATEGORY_APPROVED, IssueSeverity.BLOCKER,
                intent.dataset_key,
                "the dataset intends to assert %s, but none of its %d source(s) "
                "is approved to support that category."
                % (category.value, len(intent.source_keys))))

    register = ConflictRegister.from_records(
        conflicts if conflicts is not None else tuple(getattr(registry, "conflicts", ())))
    issues.extend(register.issues_for(intent.source_keys))

    ordered = sort_issues(issues)
    decision = (PublicationDecision.BLOCKED if blocking_issues(ordered)
                else PublicationDecision.ELIGIBLE)

    content_hash = None
    hasher = getattr(registry, "content_hash", None)
    if callable(hasher):
        content_hash = hasher()

    return PublicationEligibility(
        decision=decision,
        dataset_key=intent.dataset_key,
        evaluated_at=now,
        issues=ordered,
        evaluated_source_keys=intent.source_keys,
        registry_content_hash=content_hash,
    )
