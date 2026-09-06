# -*- coding: utf-8 -*-
"""The provisional claim boundary the candidate build runs under.

**Why this is a separate module and a separate type.**

``pgx/domain/claims.py`` is a frozen WP-01 legacy baseline artifact. Its
SHA-256 is pinned in ``data/legacy-baseline/manifest.json`` with
``mutable_legacy_state: false``, and ``scripts/amend_legacy_manifest.py``
refuses to amend a legacy entry at all - not its hash, not its metadata, not
its count. The baseline is historical evidence of what WP-00 shipped; a
correction that rewrites the evidence is not a correction.

The first version of this work added the candidate boundary *inside*
``claims.py``. It was caught by
``tests/unit/test_manifest_amendment.py::test_every_legacy_artifact_hash_
still_matches_disk``, which is exactly the guard that exists to catch it. The
boundary lives here instead, and the frozen module is byte-for-byte what it
was at the baseline freeze.

**The defect that made a distinct type necessary anyway.**

``ClaimBoundary.is_approved`` is a substring test over a free-text status: it
answers ``True`` for any status that avoids the words "draft" and "awaiting".
The candidate status - ``PROJECT_TEAM_PROVISIONAL / PENDING EXTERNAL EXPERT
REVIEW`` - contains neither word, so a candidate boundary constructed as a
plain ``ClaimBoundary`` would report itself **approved**. That is the single
redefinition this project must never make.

The frozen class cannot be corrected in place, so the correction is carried by
:class:`CandidateClaimBoundary`, which overrides ``is_approved`` to return
``False`` unconditionally. Not "usually false", not "false unless the status
says otherwise": there is no status text, and no future edit to a status
string, that can make a provisional boundary report an approval. The frozen
behaviour is preserved for every boundary that is not this one, and the hazard
is closed for the only boundary that could have hit it.

**What it does not do.** It does not enable a mode ``P0_CLAIM_BOUNDARY`` does
not enable, so it can never be the thing that unlocks ``PILOT``. It does not
represent, imply or substitute for the four recorded signatures named in
``docs/architecture/intended-purpose.md`` section 11. It records only that a
project team took provisional internal responsibility for running a candidate
prototype in ``DEMO`` and ``VALIDATION``.

See ``docs/architecture/decisions/0001-candidate-claim-boundary.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from pgx.domain.claims import (CANONICAL_CLINICAL_WARNING, ClaimBoundary,
                               ClaimPhase, OperationMode, P0_ENABLED_MODES,
                               PermittedInputKind, ProhibitedClaimCategory)

__all__ = [
    "CANDIDATE_CLAIM_BOUNDARY_STATUS",
    "CANDIDATE_CLAIM_BOUNDARY_VERSION",
    "CandidateClaimBoundary",
    "ClaimBoundaryAuthority",
    "P0_CANDIDATE_CLAIM_BOUNDARY",
    "execution_basis_of",
    "is_provisional",
    "permits_execution",
]


class ClaimBoundaryAuthority(str, Enum):
    """Who stands behind a claim boundary, and therefore what it may permit.

    ``HUMAN_APPROVAL_REQUIRED`` is what every boundary in ``claims.py`` means:
    nothing runs until the section 11 record is signed by the four named
    people. ``PROJECT_TEAM_PROVISIONAL`` is a strictly weaker statement made by
    this project's own team about its own prototype. The two are never
    interchangeable and the second never satisfies a gate that asks for the
    first.
    """

    HUMAN_APPROVAL_REQUIRED = "HUMAN_APPROVAL_REQUIRED"
    PROJECT_TEAM_PROVISIONAL = "PROJECT_TEAM_PROVISIONAL"

    def __str__(self) -> str:
        return self.value


#: The status a provisional candidate boundary carries. Spelled once so the
#: boundary, the report, the API and the UI cannot disagree about it, and
#: worded so that no reader can mistake it for an approval.
CANDIDATE_CLAIM_BOUNDARY_STATUS = (
    "PROJECT_TEAM_PROVISIONAL / PENDING EXTERNAL EXPERT REVIEW")

CANDIDATE_CLAIM_BOUNDARY_VERSION = "0.1.0-candidate-provisional"


@dataclass(frozen=True)
class CandidateClaimBoundary(ClaimBoundary):
    """A P0 boundary that a project team, not a signatory, stands behind.

    It is a real :class:`ClaimBoundary`, so everything that already accepts one
    - ``is_mode_enabled``, ``require_mode_enabled``, ``warning``,
    ``is_category_prohibited`` - accepts this unchanged and applies exactly the
    same restrictions. The subclass exists to say one thing the base class
    cannot say safely, and to refuse one thing the base class would allow.
    """

    #: Fixed by ``__post_init__``; present as a field so the value appears in
    #: ``repr`` and in any serialisation that walks the dataclass fields.
    authority: ClaimBoundaryAuthority = (
        ClaimBoundaryAuthority.PROJECT_TEAM_PROVISIONAL)

    def __post_init__(self) -> None:
        if self.authority is not ClaimBoundaryAuthority.PROJECT_TEAM_PROVISIONAL:
            raise ValueError(
                "CandidateClaimBoundary is the provisional boundary; it cannot "
                "carry authority %r. A boundary backed by human approval is a "
                "plain ClaimBoundary." % (self.authority,))

    @property
    def is_approved(self) -> bool:
        """Always ``False``. Not derived from any text, so no text can move it.

        The base class reads the status string. This does not, on purpose: the
        candidate status contains neither "draft" nor "awaiting", so the
        inherited test would answer ``True``.
        """
        return False

    @property
    def is_provisional(self) -> bool:
        """``True`` here and nowhere else. Never an approval."""
        return True

    def permits_execution(self, mode: OperationMode) -> bool:
        """Whether an assessment may run at all under this boundary.

        Narrower than approval on purpose: a provisional boundary can only
        permit a mode it already enables, and it enables exactly the P0 modes.
        It can never unlock ``PILOT``; that needs the signatures, which is the
        whole point.
        """
        if not isinstance(mode, OperationMode):
            raise TypeError("mode must be an OperationMode")
        return self.is_mode_enabled(mode) and mode in P0_ENABLED_MODES

    @property
    def execution_basis(self) -> str:
        """Why execution is permitted, in the words a report must use."""
        return ClaimBoundaryAuthority.PROJECT_TEAM_PROVISIONAL.value


#: The boundary the candidate build runs under.
#:
#: Identical to ``P0_CLAIM_BOUNDARY`` in every restriction - the same prohibited
#: categories, the same permitted input kinds, the same two modes, the same
#: canonical warning. It differs in exactly one respect: it records that a
#: project team took provisional responsibility for running the candidate
#: prototype.
#:
#: This is **not** the default. A caller has to name it, which means the
#: candidate path is visible at every call site rather than inherited by
#: accident.
P0_CANDIDATE_CLAIM_BOUNDARY = CandidateClaimBoundary(
    phase=ClaimPhase.P0,
    enabled_modes=P0_ENABLED_MODES,
    prohibited_categories=frozenset(ProhibitedClaimCategory),
    permitted_input_kinds=frozenset(PermittedInputKind),
    version=CANDIDATE_CLAIM_BOUNDARY_VERSION,
    status=CANDIDATE_CLAIM_BOUNDARY_STATUS,
    warning_by_language=CANONICAL_CLINICAL_WARNING,
)


def is_provisional(boundary: ClaimBoundary) -> bool:
    """``True`` only for a candidate boundary, for any boundary at all.

    Call sites that hold a plain ``ClaimBoundary`` use this rather than
    ``getattr(boundary, "is_provisional", False)``, so the question has one
    answer in one place.
    """
    return isinstance(boundary, CandidateClaimBoundary)


def permits_execution(boundary: ClaimBoundary, mode: OperationMode) -> bool:
    """Whether ``mode`` may run under ``boundary``, approved or provisional.

    An approved boundary permits any mode it enables. A provisional one
    permits only the P0 modes it enables. Anything else permits nothing -
    which is the state ``P0_CLAIM_BOUNDARY`` is in and must stay in.
    """
    if not isinstance(mode, OperationMode):
        raise TypeError("mode must be an OperationMode")
    if isinstance(boundary, CandidateClaimBoundary):
        return boundary.permits_execution(mode)
    return boundary.is_approved and boundary.is_mode_enabled(mode)


def execution_basis_of(boundary: ClaimBoundary) -> str:
    """Why execution is or is not permitted, for a reader of a report."""
    if isinstance(boundary, CandidateClaimBoundary):
        return boundary.execution_basis
    if boundary.is_approved:
        return "APPROVED"
    return "NOT_PERMITTED_PENDING_HUMAN_APPROVAL"
