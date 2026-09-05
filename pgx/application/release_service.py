# -*- coding: utf-8 -*-
"""Release activation, rollback and history (WP-03, gated by WP-05).

Standard library, the domain, and the WP-05 source-policy package. No SQLAlchemy
import appears here, and a test asserts it never will: the compatibility rules
below are the part of this system that most needs to be exercisable without a
database, and a service that reached for a session could not be. The source
policy is a file rather than a table for the same reason.

**What this service is for.** A release binds a software build, a dataset
version and a ruleset version into one identity, so that any assessment can
name exactly what produced it. Activation is the moment that binding becomes
the system's current answer, and it is the moment worth guarding: everything
downstream inherits whatever was true here.

**Compatibility rules** (:class:`CompatibilityCode`) gate activation: fourteen
from WP-03, plus four added by WP-05 that check the scientific source policy.
They are checked together, and every failure is collected before anything is
reported, so an operator gets the whole list rather than one problem at a time.

**The WP-05 rules are the ones that stop an unreviewed source shipping.**
``source_registry.release_eligible`` is a database flag someone can set; it says
nothing about whether a human has read the source's terms. Rules 15 to 18 make
that flag insufficient on its own: a cited source needs a policy record, an
approval by a named reviewer resting on retrieved official evidence, a complete
reuse matrix, and no unresolved conflict. A policy file that will not load
blocks activation rather than being skipped.

**All or nothing.** A failed activation changes nothing: no status moves, the
pointer stays put, the generation does not advance, and no audit event is
written. That is enforced structurally - every mutation happens after the last
check, inside one unit of work, and the unit of work rolls back unless
``commit()`` is reached.

**Injected clock and identity.** ``clock`` and ``new_event_id`` are constructor
arguments so a test can pin both. A service that read the wall clock directly
would produce audit events nobody could assert on.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from pgx.domain.claims import DEFAULT_CLAIM_BOUNDARY, OperationMode
from pgx.domain.enums import (
    AuditAction,
    DatasetStatus,
    ReleaseStatus,
    RuleStatus,
    RulesetStatus,
    SourceRole,
)
from pgx.domain.errors import DomainError, DomainInvariantError, LifecycleError
from pgx.domain.identifiers import AuditEventId, ReleaseBundleId
from pgx.domain.models import ActiveRelease, AuditEvent, ReleaseBundle
from pgx.domain.ports import UnitOfWork
from pgx.domain.release_manifest import (
    ManifestValidationError,
    manifest_digest,
    validate_release_manifest,
)
from pgx.scientific.errors import ScientificGovernanceError
from pgx.scientific.policy import load_registry
from pgx.scientific.validation import blocking_issues, validate_source

__all__ = [
    "ActivationResult",
    "CompatibilityCode",
    "CompatibilityProblem",
    "CompatibilityReport",
    "ReleaseNotFoundError",
    "ReleaseService",
    "ReleaseServiceError",
    "ReleaseNotActivatableError",
    "RollbackNotPermittedError",
    "StaleActivationError",
]

#: Object type recorded on release audit events.
RELEASE_OBJECT_TYPE = "release_bundle"


class ReleaseServiceError(DomainError):
    """Base class for release orchestration failures."""


class ReleaseNotFoundError(ReleaseServiceError):
    """The named release does not exist."""


class ReleaseNotActivatableError(ReleaseServiceError):
    """A release failed one or more compatibility rules.

    Carries the full :class:`CompatibilityReport` so a caller can render every
    problem rather than only the first.
    """

    def __init__(self, report: "CompatibilityReport") -> None:
        super().__init__(report.summary())
        self.report = report


class RollbackNotPermittedError(ReleaseServiceError):
    """A rollback target is not a release the system may return to."""


class StaleActivationError(ReleaseServiceError):
    """The active pointer moved while this activation was being prepared."""


class CompatibilityCode(str, Enum):
    """Why a release may not be activated.

    Stable machine-readable codes, one per rule in ``architecture.md`` section
    7.2 and the WP-03 brief. Codes rather than prose because an operator tool,
    a CI job and a human all need to agree on what failed.
    """

    SOFTWARE_VERSION_NOT_REGISTERED = "SOFTWARE_VERSION_NOT_REGISTERED"
    DATASET_NOT_FOUND = "DATASET_NOT_FOUND"
    DATASET_NOT_PUBLISHED = "DATASET_NOT_PUBLISHED"
    DATASET_MANIFEST_HASH_MISMATCH = "DATASET_MANIFEST_HASH_MISMATCH"
    RULESET_NOT_FOUND = "RULESET_NOT_FOUND"
    RULESET_NOT_FROZEN = "RULESET_NOT_FROZEN"
    RULESET_MANIFEST_HASH_MISMATCH = "RULESET_MANIFEST_HASH_MISMATCH"
    RULESET_MEMBERSHIP_EMPTY = "RULESET_MEMBERSHIP_EMPTY"
    RULE_NOT_FOUND = "RULE_NOT_FOUND"
    RULE_NOT_VALIDATED = "RULE_NOT_VALIDATED"
    RULE_EVIDENCE_MISSING = "RULE_EVIDENCE_MISSING"
    EVIDENCE_NOT_FOUND = "EVIDENCE_NOT_FOUND"
    EVIDENCE_OUTSIDE_DATASET = "EVIDENCE_OUTSIDE_DATASET"
    EVIDENCE_SOURCE_NOT_FOUND = "EVIDENCE_SOURCE_NOT_FOUND"
    EVIDENCE_SOURCE_NOT_RELEASE_ELIGIBLE = "EVIDENCE_SOURCE_NOT_RELEASE_ELIGIBLE"
    EVIDENCE_SOURCE_IS_INTERNAL_SYSTEM = "EVIDENCE_SOURCE_IS_INTERNAL_SYSTEM"
    SOURCE_POLICY_UNAVAILABLE = "SOURCE_POLICY_UNAVAILABLE"
    EVIDENCE_SOURCE_POLICY_MISSING = "EVIDENCE_SOURCE_POLICY_MISSING"
    EVIDENCE_SOURCE_POLICY_NOT_APPROVED = "EVIDENCE_SOURCE_POLICY_NOT_APPROVED"
    EVIDENCE_SOURCE_POLICY_INCOMPLETE = "EVIDENCE_SOURCE_POLICY_INCOMPLETE"
    SOURCE_CONFLICT_UNRESOLVED = "SOURCE_CONFLICT_UNRESOLVED"
    RELEASE_MANIFEST_INVALID = "RELEASE_MANIFEST_INVALID"
    RELEASE_MANIFEST_HASH_MISMATCH = "RELEASE_MANIFEST_HASH_MISMATCH"
    RELEASE_RETIRED = "RELEASE_RETIRED"
    CLAIM_BOUNDARY_NOT_APPROVED = "CLAIM_BOUNDARY_NOT_APPROVED"
    OPERATION_MODE_NOT_PERMITTED = "OPERATION_MODE_NOT_PERMITTED"


@dataclass(frozen=True)
class CompatibilityProblem:
    """One reason a release may not be activated."""

    code: CompatibilityCode
    detail: str
    subject: Optional[str] = None

    def to_json(self) -> Mapping[str, object]:
        """Machine-readable form for the CLI and for audit metadata."""
        return {"code": self.code.value, "detail": self.detail,
                "subject": self.subject}


@dataclass(frozen=True)
class CompatibilityReport:
    """The full outcome of checking one release.

    ``problems`` empty means activatable. Everything is collected before
    anything is reported: an operator fixing a release wants the whole list.
    """

    release_id: str
    release_public_id: str
    problems: Tuple[CompatibilityProblem, ...] = ()

    @property
    def is_compatible(self) -> bool:
        """True when no rule failed."""
        return not self.problems

    def codes(self) -> Tuple[str, ...]:
        """Every failing code, in the order the rules ran."""
        return tuple(problem.code.value for problem in self.problems)

    def summary(self) -> str:
        """One-line human summary naming every failing rule."""
        if self.is_compatible:
            return "release %s satisfies every compatibility rule" % self.release_public_id
        return ("release %s failed %d compatibility rule(s): %s"
                % (self.release_public_id, len(self.problems),
                   "; ".join("%s (%s)" % (problem.code.value, problem.detail)
                             for problem in self.problems)))

    def to_json(self) -> Mapping[str, object]:
        """Machine-readable form for the CLI."""
        return {
            "release_id": self.release_id,
            "release_public_id": self.release_public_id,
            "is_compatible": self.is_compatible,
            "problems": [problem.to_json() for problem in self.problems],
        }


@dataclass(frozen=True)
class ActivationResult:
    """What an activation or rollback actually did.

    ``changed`` is ``False`` for the idempotent no-op case: re-activating the
    release that is already active is success, not an error, and it writes no
    second audit event.
    """

    release_id: str
    release_public_id: str
    previous_release_id: Optional[str]
    generation: int
    changed: bool
    audit_event_id: Optional[str]
    action: str

    def to_json(self) -> Mapping[str, object]:
        """Machine-readable form for the CLI."""
        return {
            "action": self.action,
            "release_id": self.release_id,
            "release_public_id": self.release_public_id,
            "previous_release_id": self.previous_release_id,
            "generation": self.generation,
            "changed": self.changed,
            "audit_event_id": self.audit_event_id,
        }


def _utc_now() -> _dt.datetime:
    """Default clock. Injected in tests so audit timestamps are assertable."""
    return _dt.datetime.now(_dt.timezone.utc)


class ReleaseService:
    """Validate, activate, roll back and report on release bundles.

    Args:
        uow_factory: Returns a fresh :class:`~pgx.domain.ports.UnitOfWork`
            context manager. A factory rather than an instance, because each
            operation owns its own transaction.
        clock: Returns the current UTC instant. Injected so tests do not depend
            on wall-clock time.
        new_event_id: Mints audit event identities. Injected so tests can pin
            them.
        boundary: The WP-00 claim boundary consulted before activation. A
            release may not be activated while the claim boundary forbids the
            mode it would serve.
        source_policy: Returns the WP-05 source registry. Injected so a test can
            supply one inline and so a deployment can point at a different
            reviewed file. If it raises, activation is blocked rather than
            allowed: a policy that will not load is not an absence of policy.
    """

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        clock: Callable[[], _dt.datetime] = _utc_now,
        new_event_id: Callable[[], AuditEventId] = AuditEventId.new,
        boundary=DEFAULT_CLAIM_BOUNDARY,
        source_policy: Callable[[], object] = load_registry,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._new_event_id = new_event_id
        self._boundary = boundary
        self._source_policy = source_policy

    # -- read-only operations -------------------------------------------

    def get_active_release(self) -> Optional[ReleaseBundle]:
        """Return the release currently in force, or ``None`` before the first."""
        with self._uow_factory() as uow:
            pointer = uow.active_release.get()
            if pointer.release_id is None:
                return None
            return uow.releases.get(pointer.release_id)

    def get_active_pointer(self) -> ActiveRelease:
        """Return the raw pointer, including its generation."""
        with self._uow_factory() as uow:
            return uow.active_release.get()

    def release_history(self, limit: int = 100) -> Sequence[AuditEvent]:
        """Return recent release audit events, newest first."""
        with self._uow_factory() as uow:
            return tuple(uow.audit.list_recent(limit))

    def validate_release(self, release_id: ReleaseBundleId) -> CompatibilityReport:
        """Check every compatibility rule without changing anything.

        Read-only: the unit of work is never committed, so calling this can
        have no effect on stored state.
        """
        with self._uow_factory() as uow:
            release = self._load_release(uow, release_id)
            return self._check_compatibility(uow, release)

    # -- activation ------------------------------------------------------

    def activate_release(
        self,
        release_id: ReleaseBundleId,
        actor: str,
        reason: str,
    ) -> ActivationResult:
        """Make ``release_id`` the active release, transactionally and audited.

        The order below is deliberate. Every check happens *before* the first
        mutation, so a rejection leaves the store exactly as it was - there is
        no partial activation to undo:

        1. lock the singleton pointer row (blocks a concurrent activation);
        2. load the candidate release;
        3. run all compatibility rules;
        4. recompute the manifest digest and compare it with the stored one;
        5. determine the previous active release;
        6. mark the candidate ``ACTIVE``;
        7. mark the previous release ``ROLLED_BACK``;
        8. move the pointer and increment the generation;
        9. append one audit event;
        10. commit.

        Re-activating the release that is already active is an idempotent
        no-op: it returns ``changed=False``, does not touch the generation, and
        writes no second audit event.

        Raises:
            ReleaseNotFoundError: no such release.
            ReleaseNotActivatableError: one or more compatibility rules failed.
            StaleActivationError: the pointer moved during this transaction.
        """
        actor = _require_actor(actor)
        reason = _require_reason(reason)

        with self._uow_factory() as uow:
            # 1. Lock first: everything after this reads a pointer nobody else
            #    can move until this transaction ends.
            pointer = uow.active_release.get_for_update()
            release = self._load_release(uow, release_id)

            # Idempotent no-op. Checked before validation so that re-running an
            # activation cannot fail because the world moved on around it.
            if pointer.release_id == release.id:
                return ActivationResult(
                    release_id=release.id.to_json(),
                    release_public_id=release.public_id.to_json(),
                    previous_release_id=release.id.to_json(),
                    generation=pointer.generation,
                    changed=False,
                    audit_event_id=None,
                    action="activate",
                )

            report = self._check_compatibility(uow, release)
            if not report.is_compatible:
                raise ReleaseNotActivatableError(report)

            return self._switch_pointer(
                uow=uow,
                pointer=pointer,
                target=release,
                actor=actor,
                reason=reason,
                action=AuditAction.RELEASE_ACTIVATED,
                label="activate",
            )

    # -- rollback --------------------------------------------------------

    def rollback_release(
        self,
        target_release_id: ReleaseBundleId,
        actor: str,
        reason: str,
    ) -> ActivationResult:
        """Return the system to a release that was previously in force.

        Rollback is deliberately narrower than activation. The target must be a
        release the audit history shows was **actually activated at some point**
        - "roll back" to something that never ran is not a rollback, it is an
        activation wearing the wrong name, and it would let an operator reach a
        never-validated release through a path with softer expectations.

        Compatibility is re-checked in full. A release that was valid a month
        ago may not be valid now - a source could have lost its release
        eligibility - and returning to it blindly would reinstate exactly the
        state the checks exist to prevent.

        Nothing is rewritten: datasets, rulesets, rules, manifests and past
        assessments are untouched. Only the pointer, two status fields and one
        new audit event change.

        Raises:
            ReleaseNotFoundError: no such release.
            RollbackNotPermittedError: the target was never active, is RETIRED,
                or is already the active release.
            ReleaseNotActivatableError: the target no longer passes the rules.
        """
        actor = _require_actor(actor)
        reason = _require_reason(reason)

        with self._uow_factory() as uow:
            pointer = uow.active_release.get_for_update()
            target = self._load_release(uow, target_release_id)

            if target.status is ReleaseStatus.RETIRED:
                raise RollbackNotPermittedError(
                    "release %s is RETIRED and may not be reinstated. Retirement "
                    "is a deliberate, terminal decision; reversing it requires "
                    "registering a new release rather than a rollback."
                    % target.public_id)

            if pointer.release_id == target.id:
                raise RollbackNotPermittedError(
                    "release %s is already the active release; there is nothing "
                    "to roll back to" % target.public_id)

            if not self._was_ever_activated(uow, target.id):
                raise RollbackNotPermittedError(
                    "release %s has never been activated, so the system cannot "
                    "return to it. Rollback restores a state that existed; use "
                    "activate for a release that has not run before."
                    % target.public_id)

            report = self._check_compatibility(uow, target)
            if not report.is_compatible:
                raise ReleaseNotActivatableError(report)

            return self._switch_pointer(
                uow=uow,
                pointer=pointer,
                target=target,
                actor=actor,
                reason=reason,
                action=AuditAction.RELEASE_ROLLED_BACK,
                label="rollback",
            )

    # -- shared pointer movement ----------------------------------------

    def _switch_pointer(
        self,
        uow: UnitOfWork,
        pointer: ActiveRelease,
        target: ReleaseBundle,
        actor: str,
        reason: str,
        action: AuditAction,
        label: str,
    ) -> ActivationResult:
        """Perform the mutating half of an activation or a rollback.

        Reached only after every check has passed, so each step below is
        expected to succeed; if any raises, the unit of work rolls back and the
        store is unchanged.
        """
        now = self._clock()
        previous_id = pointer.release_id

        # 6. The candidate becomes ACTIVE.
        uow.releases.set_status(
            target.id, ReleaseStatus.ACTIVE, activated_at=now, activated_by=actor)

        # 7. The outgoing release becomes ROLLED_BACK. Its content is untouched:
        #    only the lifecycle status moves.
        if previous_id is not None and previous_id != target.id:
            uow.releases.set_status(previous_id, ReleaseStatus.ROLLED_BACK)

        # 8. Pointer and generation move together, guarded by the generation we
        #    read under lock.
        moved = pointer.moved_to(target.id, updated_at=now, updated_by=actor)
        uow.active_release.update(moved, expected_generation=pointer.generation)

        # 9. Exactly one audit event per successful pointer change.
        event = AuditEvent(
            id=self._new_event_id(),
            action=action,
            actor=actor,
            object_type=RELEASE_OBJECT_TYPE,
            object_id=target.id.to_json(),
            occurred_at=now,
            reason=reason,
            previous_release_id=previous_id,
            new_release_id=target.id,
            metadata={
                "release_public_id": target.public_id.to_json(),
                "manifest_hash": target.manifest_hash,
                "generation": moved.generation,
            },
        )
        uow.audit.append(event)

        # 10. One commit, at the end.
        uow.commit()

        return ActivationResult(
            release_id=target.id.to_json(),
            release_public_id=target.public_id.to_json(),
            previous_release_id=None if previous_id is None else previous_id.to_json(),
            generation=moved.generation,
            changed=True,
            audit_event_id=event.id.to_json(),
            action=label,
        )

    # -- helpers ---------------------------------------------------------

    @staticmethod
    def _load_release(uow: UnitOfWork, release_id: ReleaseBundleId) -> ReleaseBundle:
        release = uow.releases.get(release_id)
        if release is None:
            raise ReleaseNotFoundError("no release bundle with id %s" % release_id)
        return release

    @staticmethod
    def _was_ever_activated(uow: UnitOfWork, release_id: ReleaseBundleId) -> bool:
        """True when the audit history records this release becoming active.

        History, not the release row, is the authority: the row's status says
        what is true now, while the question here is what was ever true.
        """
        events = uow.audit.list_for_object(RELEASE_OBJECT_TYPE, release_id.to_json())
        return any(
            event.new_release_id == release_id
            and event.action in (AuditAction.RELEASE_ACTIVATED,
                                 AuditAction.RELEASE_ROLLED_BACK)
            for event in events)

    # -- the fourteen compatibility rules --------------------------------

    def _check_compatibility(
        self, uow: UnitOfWork, release: ReleaseBundle
    ) -> CompatibilityReport:
        """Run every rule and collect every failure.

        Nothing short-circuits on the first problem: an operator repairing a
        release should see the whole list, and a report that stops early makes
        fixing one problem reveal the next.
        """
        problems: List[CompatibilityProblem] = []
        add = problems.append

        # 13. A retired release is terminal.
        if release.status is ReleaseStatus.RETIRED:
            add(CompatibilityProblem(
                CompatibilityCode.RELEASE_RETIRED,
                "release is RETIRED and may not be activated",
                release.public_id.to_json()))

        # 14. WP-00 governance is unchanged and the mode is still permitted.
        self._check_claim_boundary(add)

        # 1. Software version registered.
        software = uow.software_versions.get(release.software_version_id)
        if software is None:
            add(CompatibilityProblem(
                CompatibilityCode.SOFTWARE_VERSION_NOT_REGISTERED,
                "the release pins software version %s, which is not registered"
                % release.software_version_id,
                str(release.software_version_id)))

        # 2-3. Dataset published, and its hash is what the manifest pinned.
        dataset = uow.dataset_versions.get(release.dataset_version_id)
        if dataset is None:
            add(CompatibilityProblem(
                CompatibilityCode.DATASET_NOT_FOUND,
                "dataset version %s does not exist" % release.dataset_version_id,
                str(release.dataset_version_id)))
        else:
            if dataset.status is not DatasetStatus.PUBLISHED:
                add(CompatibilityProblem(
                    CompatibilityCode.DATASET_NOT_PUBLISHED,
                    "dataset %s is %s; only a PUBLISHED dataset may back an "
                    "active release" % (dataset.public_id, dataset.status.value),
                    dataset.public_id.to_json()))
            pinned = _manifest_section(release.manifest, "dataset")
            if pinned.get("manifest_hash") != dataset.manifest_hash:
                add(CompatibilityProblem(
                    CompatibilityCode.DATASET_MANIFEST_HASH_MISMATCH,
                    "the release manifest pins dataset hash %r but the stored "
                    "dataset hash is %r"
                    % (pinned.get("manifest_hash"), dataset.manifest_hash),
                    dataset.public_id.to_json()))

        # 4-7. Ruleset frozen, hash pinned, membership non-empty and validated.
        ruleset = uow.ruleset_versions.get(release.ruleset_version_id)
        if ruleset is None:
            add(CompatibilityProblem(
                CompatibilityCode.RULESET_NOT_FOUND,
                "ruleset version %s does not exist" % release.ruleset_version_id,
                str(release.ruleset_version_id)))
            return CompatibilityReport(
                release.id.to_json(), release.public_id.to_json(), tuple(problems))

        if ruleset.status is not RulesetStatus.FROZEN:
            add(CompatibilityProblem(
                CompatibilityCode.RULESET_NOT_FROZEN,
                "ruleset %s is %s; only a FROZEN ruleset may back an active "
                "release" % (ruleset.public_id, ruleset.status.value),
                ruleset.public_id.to_json()))

        pinned_ruleset = _manifest_section(release.manifest, "ruleset")
        if pinned_ruleset.get("manifest_hash") != ruleset.manifest_hash:
            add(CompatibilityProblem(
                CompatibilityCode.RULESET_MANIFEST_HASH_MISMATCH,
                "the release manifest pins ruleset hash %r but the stored "
                "ruleset hash is %r"
                % (pinned_ruleset.get("manifest_hash"), ruleset.manifest_hash),
                ruleset.public_id.to_json()))

        if not ruleset.rule_ids:
            add(CompatibilityProblem(
                CompatibilityCode.RULESET_MEMBERSHIP_EMPTY,
                "ruleset %s pins no rules; an empty ruleset would let a release "
                "claim coverage it does not have" % ruleset.public_id,
                ruleset.public_id.to_json()))

        # 8-11. Every member rule: validated, evidence-backed, evidence inside
        #       the pinned dataset, from a release-eligible, non-internal source.
        dataset_id = None if dataset is None else dataset.id
        cited_sources: Dict[str, object] = {}
        for rule_id in ruleset.rule_ids:
            self._check_member_rule(uow, rule_id, dataset_id, add, cited_sources)

        # 15-18. WP-05: every cited source carries an approved, complete policy,
        #        and no unresolved conflict touches it. Checked once per distinct
        #        source rather than once per evidence record: an operator wants
        #        "CPIC is unreviewed" said once, not four hundred times.
        self._check_source_policy(cited_sources, add)

        # 12. The manifest is structurally valid and still hashes to its digest.
        self._check_manifest(release, add)

        return CompatibilityReport(
            release.id.to_json(), release.public_id.to_json(), tuple(problems))

    def _check_claim_boundary(self, add: Callable[[CompatibilityProblem], None]) -> None:
        """Rule 14: WP-00 governance has not been quietly relaxed.

        Two separate things are checked. ``PILOT`` must still be disabled - a
        release activated while a forbidden mode is live would serve it. And the
        modes the boundary *does* enable must still be enabled, so this fails
        loudly if the vocabulary changes underneath.
        """
        if self._boundary.is_mode_enabled(OperationMode.PILOT):
            add(CompatibilityProblem(
                CompatibilityCode.OPERATION_MODE_NOT_PERMITTED,
                "PILOT mode is enabled in the claim boundary, which P0 does not "
                "permit; a release must not be activated into it",
                OperationMode.PILOT.value))
        if not (self._boundary.is_mode_enabled(OperationMode.DEMO)
                or self._boundary.is_mode_enabled(OperationMode.VALIDATION)):
            add(CompatibilityProblem(
                CompatibilityCode.CLAIM_BOUNDARY_NOT_APPROVED,
                "no operation mode is enabled in the claim boundary, so there is "
                "no mode an activated release could serve",
                None))

    def _check_member_rule(
        self,
        uow: UnitOfWork,
        rule_id,
        dataset_id,
        add: Callable[[CompatibilityProblem], None],
        cited_sources: Optional[Dict[str, object]] = None,
    ) -> None:
        """Rules 8 to 11, for one member of the pinned ruleset.

        ``cited_sources`` accumulates the distinct registry entries this rule's
        evidence names, so the WP-05 policy rules can be applied once per source
        after the sweep rather than once per evidence record.
        """
        if cited_sources is None:
            cited_sources = {}
        rule = uow.rules.get(rule_id)
        if rule is None:
            add(CompatibilityProblem(
                CompatibilityCode.RULE_NOT_FOUND,
                "ruleset member %s does not exist" % rule_id, str(rule_id)))
            return

        if rule.status is not RuleStatus.VALIDATED:
            add(CompatibilityProblem(
                CompatibilityCode.RULE_NOT_VALIDATED,
                "rule %s is %s; only VALIDATED rules may execute (SAFETY-INV-003)"
                % (rule_id, rule.status.value), str(rule_id)))

        if not rule.evidence_record_ids:
            add(CompatibilityProblem(
                CompatibilityCode.RULE_EVIDENCE_MISSING,
                "rule %s cites no evidence; every calculated finding must be "
                "traceable (SAFETY-INV-006)" % rule_id, str(rule_id)))
            return

        for evidence_id in rule.evidence_record_ids:
            evidence = uow.evidence.get(evidence_id)
            if evidence is None:
                add(CompatibilityProblem(
                    CompatibilityCode.EVIDENCE_NOT_FOUND,
                    "rule %s cites evidence %s, which does not exist"
                    % (rule_id, evidence_id), str(evidence_id)))
                continue

            if dataset_id is not None and evidence.dataset_version_id != dataset_id:
                add(CompatibilityProblem(
                    CompatibilityCode.EVIDENCE_OUTSIDE_DATASET,
                    "rule %s cites evidence %s from dataset %s, but the release "
                    "pins dataset %s. A rule may not reach outside the dataset "
                    "the release declares."
                    % (rule_id, evidence_id, evidence.dataset_version_id, dataset_id),
                    str(evidence_id)))

            source = uow.source_registry.get(evidence.source_registry_id)
            if source is None:
                add(CompatibilityProblem(
                    CompatibilityCode.EVIDENCE_SOURCE_NOT_FOUND,
                    "evidence %s names source %s, which is not registered"
                    % (evidence_id, evidence.source_registry_id),
                    str(evidence.source_registry_id)))
                continue

            cited_sources.setdefault(source.source_key, source)

            if source.role is SourceRole.INTERNAL_SYSTEM:
                add(CompatibilityProblem(
                    CompatibilityCode.EVIDENCE_SOURCE_IS_INTERNAL_SYSTEM,
                    "evidence %s comes from the INTERNAL_SYSTEM source %r, which "
                    "is technical bookkeeping and cannot support a scientific "
                    "release" % (evidence_id, source.source_key),
                    source.source_key))
            elif not source.release_eligible:
                add(CompatibilityProblem(
                    CompatibilityCode.EVIDENCE_SOURCE_NOT_RELEASE_ELIGIBLE,
                    "evidence %s comes from source %r, which is not marked "
                    "release_eligible" % (evidence_id, source.source_key),
                    source.source_key))

    def _check_source_policy(
        self,
        cited_sources: Mapping[str, object],
        add: Callable[[CompatibilityProblem], None],
    ) -> None:
        """Rules 15 to 18: the WP-05 source policy gate.

        ``source_registry.release_eligible`` is a WP-02 operational flag, and on
        its own it says only that somebody ticked a box in a database row. These
        rules are what make that box insufficient: a source may back a release
        only when the reviewed policy file carries an approval for it, made by a
        named human, on retrieved official evidence, with every reuse question
        answered.

        Fail-closed in three places, each of which would otherwise be a way to
        publish by accident:

        * the registry will not load - blocked, not skipped;
        * a cited source has no policy record - blocked, because an unregistered
          source has no permissions rather than unlimited ones;
        * a conflict touching a cited source is unresolved - blocked, including
          one whose materiality nobody has judged yet.
        """
        if not cited_sources:
            return

        try:
            registry = self._source_policy()
        except ScientificGovernanceError as exc:
            add(CompatibilityProblem(
                CompatibilityCode.SOURCE_POLICY_UNAVAILABLE,
                "the scientific source policy could not be loaded: %s. A policy "
                "that will not load is not an absence of restrictions, so "
                "activation is blocked." % exc, None))
            return
        if registry is None:
            add(CompatibilityProblem(
                CompatibilityCode.SOURCE_POLICY_UNAVAILABLE,
                "no scientific source policy is configured; every source a "
                "release cites must carry a reviewed policy record", None))
            return

        now = self._clock()
        for source_key in sorted(cited_sources):
            record = registry.get(source_key)
            if record is None:
                add(CompatibilityProblem(
                    CompatibilityCode.EVIDENCE_SOURCE_POLICY_MISSING,
                    "source %r is cited by this release but carries no entry in "
                    "the scientific source registry. Registering a source in the "
                    "database is not the same as approving it."
                    % source_key, source_key))
                continue

            if not record.is_approved:
                add(CompatibilityProblem(
                    CompatibilityCode.EVIDENCE_SOURCE_POLICY_NOT_APPROVED,
                    "source %r has policy status %s. No named human has approved "
                    "it, and release_eligible alone does not substitute for a "
                    "review." % (source_key, record.effective_status(now).value),
                    source_key))
                continue

            problems = blocking_issues(validate_source(record, now))
            if problems:
                add(CompatibilityProblem(
                    CompatibilityCode.EVIDENCE_SOURCE_POLICY_INCOMPLETE,
                    "source %r is approved but its policy record still has %d "
                    "blocking finding(s): %s"
                    % (source_key, len(problems),
                       ", ".join(sorted({p.code.value for p in problems}))),
                    source_key))

        for conflict in _blocking_conflicts(registry, tuple(sorted(cited_sources))):
            add(CompatibilityProblem(
                CompatibilityCode.SOURCE_CONFLICT_UNRESOLVED,
                "sources %s disagree about %s and the conflict is %s (%s). A "
                "release may not paper over a disagreement nobody has settled."
                % (" and ".join(conflict.source_keys), conflict.subject,
                   conflict.status.value, conflict.materiality.value),
                conflict.conflict_key))

    @staticmethod
    def _check_manifest(
        release: ReleaseBundle, add: Callable[[CompatibilityProblem], None]
    ) -> None:
        """Rule 12: the stored manifest is valid and matches its recorded digest.

        The digest is recomputed rather than trusted. A row whose hash column
        was edited out of band is exactly what this catches.
        """
        problems = validate_release_manifest(release.manifest)
        if problems:
            add(CompatibilityProblem(
                CompatibilityCode.RELEASE_MANIFEST_INVALID,
                "release manifest is structurally invalid: %s" % "; ".join(problems),
                release.public_id.to_json()))
            return
        try:
            recomputed = manifest_digest(release.manifest)
        except ManifestValidationError as exc:  # pragma: no cover - defensive
            add(CompatibilityProblem(
                CompatibilityCode.RELEASE_MANIFEST_INVALID, str(exc),
                release.public_id.to_json()))
            return
        if recomputed != release.manifest_hash:
            add(CompatibilityProblem(
                CompatibilityCode.RELEASE_MANIFEST_HASH_MISMATCH,
                "stored manifest hash %s does not match the digest recomputed "
                "from the payload (%s)" % (release.manifest_hash, recomputed),
                release.public_id.to_json()))


def _blocking_conflicts(registry: object, source_keys: Tuple[str, ...]) -> Tuple:
    """Conflicts that block, limited to the sources this release actually cites.

    A release citing only A and B is not held up by an unresolved disagreement
    between C and D. Returns an empty tuple for a registry that carries no
    conflicts at all, so a hand-built test registry needs no conflict support.
    """
    conflicts = getattr(registry, "conflicts", ())
    wanted = set(source_keys)
    return tuple(sorted(
        (c for c in conflicts
         if c.blocks_publication and wanted & set(c.source_keys)),
        key=lambda item: item.conflict_key))


def _manifest_section(manifest: Mapping[str, object], key: str) -> Mapping[str, object]:
    """Return one manifest section, or an empty mapping when it is missing.

    Missing sections are reported by the manifest rule; the hash comparisons
    must not raise before it gets the chance.
    """
    section = manifest.get(key)
    return section if isinstance(section, Mapping) else {}


def _require_actor(actor: str) -> str:
    """Every mutating operation names a responsible actor."""
    if not isinstance(actor, str) or not actor.strip():
        raise DomainInvariantError(
            "actor is required: an activation or rollback with no named actor "
            "cannot be audited")
    return actor.strip()


def _require_reason(reason: str) -> str:
    """Every mutating operation records why."""
    if not isinstance(reason, str) or not reason.strip():
        raise DomainInvariantError(
            "reason is required: an audit trail that records what changed but "
            "not why answers only half the question")
    return reason.strip()
