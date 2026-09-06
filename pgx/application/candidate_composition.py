# -*- coding: utf-8 -*-
"""Composing the candidate track (Wave 4B).

Wave 3B built a candidate release, a candidate ruleset and a candidate
assessment service, and composed none of them. Nothing reached them: the
deployment provider filled in the WP-23 security capabilities and left
``assessment_service`` and ``release_resolver`` at ``None``, so every
assessment answered 503 and ``/system`` reported no active release. A gate read
PASS anyway, because it constructed the service itself and asked that object
what it resolved - which measured a constructor.

This module is the missing piece, and it is deliberately small: two factories
and a status reader. It lives in the application layer rather than under
``apps/`` so that the API edge, the server-rendered interface and a test all
compose the *same* candidate service. There is one evaluator in this
repository and every surface reaches it through here.

**What it does not do.** It does not register anything in the WP-13 governed
release registry, does not write the governed active-release pointer, does not
touch the H01 source-policy decision, and does not change the candidate DQ
decision's ``permits_transition = false``. A candidate release composed here is
exactly as unapproved as it was on disk; composition is plumbing, not
promotion.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from pgx.application.candidate_assessment_service import (
    CandidateAssessmentService)
from pgx.application.candidate_release import (CandidateReleaseError,
                                               CandidateReleaseResolver)
from pgx.application.runtime_track import RuntimeTrack
from pgx.domain.authority import CandidateAuthorityState
from pgx.domain.candidate_claims import (P0_CANDIDATE_CLAIM_BOUNDARY,
                                         execution_basis_of)

__all__ = [
    "CandidateRuntime",
    "build_candidate_runtime",
    "describe_runtime_tracks",
]


class CandidateRuntime:
    """The candidate capabilities a provider is composed with.

    One resolver and one service, both built once and shared, because the
    candidate release artifacts are read-only files whose content is verified
    at resolution: reading them per request would re-verify the same bytes and
    change nothing about the answer.
    """

    def __init__(self, repo_root: str = ".") -> None:
        self._repo_root = repo_root
        self._resolver = CandidateReleaseResolver(repo_root)
        self._service = CandidateAssessmentService(
            release_resolver=self._resolver,
            claim_boundary=P0_CANDIDATE_CLAIM_BOUNDARY,
            repo_root=repo_root)

    @property
    def repo_root(self) -> str:
        return self._repo_root

    def release(self) -> Any:
        """The pinned candidate release, or ``None`` when it cannot be read.

        ``None`` rather than an exception, because the provider turns it into
        the typed 503 that names the missing capability, and a resolver that
        raised through the provider would produce a 500 for a configuration
        problem.
        """
        try:
            return self._resolver.resolve()
        except CandidateReleaseError:
            return None

    def service(self) -> CandidateAssessmentService:
        return self._service

    def release_error(self) -> str:
        try:
            self._resolver.resolve()
        except CandidateReleaseError as error:
            return str(error)
        return ""


def build_candidate_runtime(repo_root: str = ".") -> CandidateRuntime:
    """The candidate runtime for a repository root."""
    return CandidateRuntime(repo_root)


def _governed_state(release_resolver: Optional[Callable[[], Any]]
                    ) -> Dict[str, Any]:
    """What the governed track has, reported without pretending it has more."""
    state: Dict[str, Any] = {
        "track": RuntimeTrack.GOVERNED.value,
        "composed": release_resolver is not None,
        "release_public_id": None,
        "authority": "HUMAN_APPROVAL_REQUIRED",
        "detail": "",
    }
    if release_resolver is None:
        state["detail"] = (
            "No governed release is composed in this deployment. The WP-13 "
            "active-release pointer is a separate record and is untouched.")
        return state
    try:
        pinned = release_resolver()
    except Exception as error:  # noqa: BLE001 - reported, never raised on
        state["detail"] = "%s: %s" % (type(error).__name__, error)
        return state
    if pinned is None:
        state["detail"] = "No governed active release is registered."
        return state
    state["release_public_id"] = getattr(pinned, "release_public_id", None)
    state["detail"] = "A governed active release is registered."
    return state


def _candidate_state(runtime: Optional[CandidateRuntime]) -> Dict[str, Any]:
    """What the candidate track has, with every hash it is pinned by."""
    state: Dict[str, Any] = {
        "track": RuntimeTrack.CANDIDATE.value,
        "composed": runtime is not None,
        "release_public_id": None,
        "dataset_public_id": None,
        "ruleset_key": None,
        "ruleset_content_hash": None,
        "manifest_hash": None,
        "permitted_modes": (),
        "authority": None,
        "review_state": CandidateAuthorityState
        .PENDING_EXTERNAL_EXPERT_REVIEW.value,
        "claim_boundary_status": P0_CANDIDATE_CLAIM_BOUNDARY.status,
        "claim_boundary_is_approved": P0_CANDIDATE_CLAIM_BOUNDARY.is_approved,
        "claim_boundary_execution_basis": execution_basis_of(
            P0_CANDIDATE_CLAIM_BOUNDARY),
        "governed_registry_note": (
            "ACTIVE in the candidate-only lifecycle. Not registered, "
            "approved or published through the WP-13 governed release "
            "registry."),
        "detail": "",
    }
    if runtime is None:
        state["detail"] = (
            "This deployment does not serve the candidate track.")
        return state
    pinned = runtime.release()
    if pinned is None:
        state["detail"] = runtime.release_error()
        return state
    manifest = pinned.manifest
    state.update({
        "release_public_id": pinned.release_public_id,
        "dataset_public_id": pinned.dataset_public_id,
        "ruleset_key": pinned.ruleset.ruleset_key,
        "ruleset_content_hash": pinned.ruleset.content_hash(),
        "manifest_hash": manifest["manifest_hash"],
        "permitted_modes": tuple(manifest["permitted_modes"]),
        "authority": manifest["authority_state"],
        "review_state": manifest["review_state"],
        "pointer_generation": pinned.pointer_generation,
        "rule_count": len(pinned.ruleset.rules),
        "detail": "The candidate release is resolved and executable.",
    })
    return state


def describe_runtime_tracks(*, active_track: RuntimeTrack,
                            candidate_runtime: Optional[CandidateRuntime],
                            governed_release_resolver:
                            Optional[Callable[[], Any]] = None
                            ) -> Dict[str, Any]:
    """Both tracks, side by side, never merged into one "the release" row.

    ``/system`` renders this. Two separate blocks is the whole point: a reader
    must be able to see that the candidate release is resolved *and* that the
    governed one is not, at the same time, without either being able to stand
    in for the other.
    """
    return {
        "active_track": active_track.value,
        "candidate": _candidate_state(candidate_runtime),
        "governed": _governed_state(governed_release_resolver),
        "schema_version": "pgx-runtime-tracks/1",
    }
