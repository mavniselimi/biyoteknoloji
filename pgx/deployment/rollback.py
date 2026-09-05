# -*- coding: utf-8 -*-
"""Rollback, in both of its meanings (WP-24).

"Rollback" names two different operations in this system and conflating them
is how a deployment ends up serving an old image against a new schema, or
worse, deciding that rolling back a release means editing one.

**Deployment rollback** replaces the running image with the previous one. It
must not downgrade the database. A schema migration is forward-only in
practice - ``0011``'s ``downgrade()`` refuses while any user, session or
governed audit event exists, and that refusal is correct: dropping those
tables destroys the account history and the integrity chain together. So an
image rollback is only safe between images that both work against the current
schema, and this module records *which two images* rather than "the previous
one", because a tag is not an identity.

**Governed release rollback** moves the active-release pointer to a previously
active release. WP-03 owns it and this module does not reimplement it. What
matters here is what must not happen: the manifest of an existing release is
never edited, the history is never rewritten, and the pointer transition is
audited like any other governed change. A release is immutable; rolling back
means pointing somewhere else, not changing where you were pointing.

Neither operation is performed against fixtures and reported as operational.
When two real image identities or two eligible releases do not exist, the
machinery is exercised against clearly labelled test doubles and the
operational drill stays BLOCKED - the label travels with the result.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Mapping, Optional, Sequence

from pgx.deployment.vocabulary import (REHEARSAL_LABEL,
                                       DeploymentEnvironmentKind,
                                       ExecutionState, blocker)

__all__ = [
    "ROLLBACK_RESULT_VERSION",
    "governed_release_rollback_status",
    "image_rollback_drill",
]

ROLLBACK_RESULT_VERSION = "pgx-wp24-rollback-drill/1"


def image_rollback_drill(*, previous_image: Optional[Mapping[str, Any]] = None,
                         candidate_image: Optional[Mapping[str, Any]] = None,
                         health_before: Optional[Mapping[str, Any]] = None,
                         health_after: Optional[Mapping[str, Any]] = None,
                         database_downgraded: bool = False,
                         environment: DeploymentEnvironmentKind =
                         DeploymentEnvironmentKind.LOCAL_REHEARSAL,
                         test_only: bool = False,
                         now: Optional[_dt.datetime] = None
                         ) -> Mapping[str, object]:
    """Record a deployment rollback between two *identified* images.

    Both identities are required and are recorded by id, not by tag. A tag is
    a name somebody can move; two rollback records that both say
    ``pgx-platform:latest`` describe an operation nobody can reconstruct.

    ``database_downgraded`` is recorded and, when true, makes the drill a
    failure rather than a success. A rollback that downgraded the schema is
    not the operation this drill is for, and letting it pass would put the
    procedure in a runbook.
    """
    label = (REHEARSAL_LABEL
             if environment is DeploymentEnvironmentKind.LOCAL_REHEARSAL
             else None)
    blockers = []
    if not previous_image or not candidate_image:
        blockers.append(dict(blocker(
            "DEPLOY_ROLLBACK_NOT_EXERCISED",
            owner="WP-24 operation on a host with a container runtime",
            detail=("two identified images are required; a rollback recorded "
                    "between one image and 'the previous one' names an "
                    "operation nobody can reconstruct")).to_json()))
        return {
            "rollback_result_version": ROLLBACK_RESULT_VERSION,
            "kind": "deployment_image",
            "state": ExecutionState.BLOCKED.value,
            "environment_kind": environment.value,
            "rehearsal_label": label,
            "test_only": test_only,
            "previous_image": previous_image, "candidate_image":
                candidate_image,
            "database_downgraded": database_downgraded,
            "health_before": None, "health_after": None,
            "blockers": blockers, "note": _ROLLBACK_NOTE,
        }
    ambiguous = [name for name, image in
                 (("previous", previous_image), ("candidate",
                                                 candidate_image))
                 if not (image.get("image_id") or image.get("image_digest"))]
    if ambiguous:
        blockers.append(dict(blocker(
            "DEPLOY_ROLLBACK_NOT_EXERCISED", owner="the operator",
            detail=("the %s image is identified by tag only; a tag is a name "
                    "somebody can move" % ", ".join(ambiguous))).to_json()))
    same = ((previous_image.get("image_id") or previous_image.get(
        "image_digest")) == (candidate_image.get("image_id")
                             or candidate_image.get("image_digest")))
    if same:
        blockers.append(dict(blocker(
            "DEPLOY_ROLLBACK_NOT_EXERCISED", owner="the operator",
            detail=("the two images have the same identity, so no rollback "
                    "took place")).to_json()))
    recovered = bool(health_after and health_after.get("liveness_status")
                     == 200)
    succeeded = (not blockers and recovered and not database_downgraded)
    if test_only:
        state = ExecutionState.TEST_ONLY_REHEARSAL
    elif blockers:
        state = ExecutionState.BLOCKED
    else:
        state = (ExecutionState.VERIFIED if succeeded
                 else ExecutionState.EXECUTED)
    return {
        "rollback_result_version": ROLLBACK_RESULT_VERSION,
        "kind": "deployment_image",
        "state": state.value,
        "environment_kind": environment.value,
        "rehearsal_label": label,
        "test_only": test_only,
        "previous_image": dict(previous_image),
        "candidate_image": dict(candidate_image),
        "rollback_target_explicit": True,
        "database_downgraded": database_downgraded,
        "database_downgrade_note": (
            "A rollback must not downgrade the schema. Migration 0011's "
            "downgrade refuses while any user, session or governed audit "
            "event exists, and that refusal is correct - dropping those "
            "tables destroys the account history and the integrity chain "
            "together."),
        "health_before": dict(health_before) if health_before else None,
        "health_after": dict(health_after) if health_after else None,
        "observed_at": (now or _dt.datetime.now(_dt.timezone.utc)
                        ).isoformat(),
        "blockers": blockers,
        "note": _ROLLBACK_NOTE,
    }


def governed_release_rollback_status(
        *, releases: Optional[Sequence[Mapping[str, Any]]] = None,
        active_release_id: Optional[str] = None,
        rolled_back_to: Optional[str] = None,
        audited_event_id: Optional[str] = None,
        test_only: bool = False) -> Mapping[str, object]:
    """Report a governed release rollback, or why one has not happened.

    This does not perform the rollback: WP-03's release service does, and a
    second implementation of the eligibility rules here would be a second
    place for them to be wrong. What this records is that the transition was
    audited, that the manifest was not edited, and that two eligible releases
    existed in the first place.
    """
    known = list(releases or [])
    blockers = []
    if len(known) < 2:
        blockers.append(dict(blocker(
            "DEPLOY_NO_ELIGIBLE_RELEASE",
            owner="WP-03 operation, once a release is approved and activated",
            detail=("a governed rollback needs two eligible releases; %d "
                    "exist. Manufacturing a second one as evidence would "
                    "make the drill describe a release nobody approved"
                    % len(known))).to_json()))
    if rolled_back_to is None:
        blockers.append(dict(blocker(
            "DEPLOY_ROLLBACK_NOT_EXERCISED",
            owner="WP-03 operation",
            detail="no pointer transition has been performed").to_json()))
    elif audited_event_id is None:
        blockers.append(dict(blocker(
            "DEPLOY_ROLLBACK_NOT_EXERCISED", owner="the deployment",
            detail=("the pointer moved with no governed audit event; an "
                    "unaudited release transition is a change to what the "
                    "system asserts, made by nobody")).to_json()))
    state = (ExecutionState.TEST_ONLY_REHEARSAL if test_only
             else ExecutionState.BLOCKED if blockers
             else ExecutionState.VERIFIED)
    return {
        "rollback_result_version": ROLLBACK_RESULT_VERSION,
        "kind": "governed_release",
        "state": state.value,
        "test_only": test_only,
        "eligible_release_count": len(known),
        "active_release_id": active_release_id,
        "rolled_back_to": rolled_back_to,
        "audited_event_id": audited_event_id,
        "manifest_edited": False,
        "immutability_note": (
            "No release manifest is ever edited. A release is immutable and "
            "rolling back means pointing somewhere else, not changing where "
            "you were pointing - so the history stays readable and a rolled- "
            "back release is still exactly what it was when it was active."),
        "blockers": blockers,
        "note": _ROLLBACK_NOTE,
    }


_ROLLBACK_NOTE = (
    "Two different operations share the word rollback: replacing a running "
    "image, and moving the governed active-release pointer. Neither is "
    "performed against fixtures and reported as operational; when the real "
    "identities do not exist the machinery is exercised against labelled "
    "test doubles and the operational drill stays BLOCKED.")
