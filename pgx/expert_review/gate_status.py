# -*- coding: utf-8 -*-
"""The WP-22 gate (WP-22): the module exists; no expert has reviewed anything.

Two answers that must never be collapsed into one, and this document is built
so they can disagree:

- **Is the blind review machinery implemented?** Yes. The protocol document,
  the state machine, the blinding structure, the append-only records, the
  audit chain, the persistence layer, the API and the reviewer's pages all
  exist. That is a software fact, measured here by importing the modules and
  walking the tree.
- **Has any expert reviewed anything?** No. There is no approved protocol, no
  expert-holdout case, no active release, no configured restricted storage, no
  production authentication and no named reviewer. Nothing was reviewed and
  nothing was validated.

The second answer is not a placeholder waiting to be flipped. Six independent
preconditions are missing, five of them owned by people rather than by code,
and none of them can be satisfied by anything this repository could do to
itself. So ``expert_review_performed`` is ``false`` and stays ``false`` until
those people act.

Nothing here is asserted. The protocol state comes from
:func:`pgx.expert_review.protocol.load_protocol`, which reads a digest and no
signatures; the case counts come from the sealed WP-18 catalogue; the review
counts come from an injected store or are ``null`` when none was inspected;
the module markers are file checks.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Mapping, Optional, Tuple

from pgx.domain.claims import DEFAULT_CLAIM_BOUNDARY
from pgx.expert_review.protocol import (PROTOCOL_DOCUMENT_PATH,
                                        REQUIRED_SIGNATORY_ROLES,
                                        load_protocol)
from pgx.expert_review.vocabulary import (LIKERT_DIMENSIONS,
                                          REVIEW_ERROR_CODES,
                                          TRANSITIONS,
                                          VOCABULARY_VERSION)

__all__ = [
    "EXPERT_REVIEW_BLOCKER_CODES",
    "GATE_STATUS_VERSION",
    "MODULE_MARKERS",
    "RESTRICTED_STORAGE_ENV",
    "build_wp22_gate_status",
    "expert_review_gate_state",
    "expert_review_module_markers",
]

GATE_STATUS_VERSION = "pgx-wp22-gate-status/1"

#: The same variable WP-18 and WP-21 read. Named here rather than imported so
#: this module does not depend on either of their gate builders, both of which
#: read this one after the integrations below.
RESTRICTED_STORAGE_ENV = "PGX_VALIDATION_RESTRICTED_ROOT"

#: What actually constitutes WP-22 on disk. Every path is checked; a partial
#: set reports as not implemented rather than as implemented-with-gaps,
#: because a review module missing its protocol document or its persistence
#: is not a review module.
MODULE_MARKERS: Tuple[str, ...] = (
    "pgx/expert_review/protocol.py",
    "pgx/expert_review/service.py",
    "pgx/expert_review/models.py",
    "pgx/expert_review/audit.py",
    "pgx/expert_review/permits.py",
    "pgx/expert_review/ports.py",
    "pgx/infrastructure/db/expert_reviews.py",
    "apps/api/routers/expert_review.py",
    "apps/web/templates/expert_review.html",
    PROTOCOL_DOCUMENT_PATH,
)

EXPERT_REVIEW_BLOCKER_CODES: Mapping[str, Mapping[str, str]] = {
    "EXPERT_REVIEW_PROTOCOL_NOT_APPROVED": {
        "meaning": "the blind review protocol is a draft; the four required "
                   "signatory roles have not signed the current document "
                   "digest, so no governed operation may execute",
        "owner": "named human and scientific reviewers"},
    "EXPERT_REVIEW_NO_EXPERT_HOLDOUT_CASES": {
        "meaning": "zero expert-holdout cases exist, so there is nothing to "
                   "assign; a development case cannot be substituted, "
                   "because it shaped the software",
        "owner": "scientific curators; a holdout case cannot be generated"},
    "EXPERT_REVIEW_NO_NAMED_REVIEWERS": {
        "meaning": "no expert has been named, declared a conflict of "
                   "interest or accepted an assignment",
        "owner": "whoever recruits reviewers under the approved protocol"},
    "EXPERT_REVIEW_NO_ACTIVE_RELEASE": {
        "meaning": "no release is registered or active, so no review could "
                   "pin the software, dataset and ruleset it judged",
        "owner": "WP-03 operation"},
    "EXPERT_REVIEW_RESTRICTED_STORAGE_NOT_CONFIGURED": {
        "meaning": "expert-holdout payloads live in restricted storage and "
                   "none is configured, so no case could be shown to a "
                   "reviewer",
        "owner": "deployment"},
    "EXPERT_REVIEW_NO_PRODUCTION_AUTHENTICATION": {
        "meaning": "there is no production authentication, so no actor "
                   "string can be attributed to a person; a review recorded "
                   "against an unauthenticated actor names nobody",
        "owner": "WP-23"},
    "EXPERT_REVIEW_NONE_COMPLETED": {
        "meaning": "no review has reached COMPLETED under an approved "
                   "protocol; nobody looked",
        "owner": "named experts under the approved protocol"},
    "EXPERT_REVIEW_CLAIM_BOUNDARY_NOT_APPROVED": {
        "meaning": "the claim boundary awaits human and scientific review, "
                   "so no review outcome may be presented as a claim",
        "owner": "named human and scientific reviewers"},
}


def _restricted_storage_configured(environ: Optional[Mapping[str, str]]
                                   ) -> bool:
    values = os.environ if environ is None else environ
    root = values.get(RESTRICTED_STORAGE_ENV)
    return bool(root) and os.path.isdir(str(root))


def _active_release_available(resolver: Optional[Any]) -> bool:
    """Whether one release could be pinned right now.

    ``None`` means no resolver was injected, which is this repository's state.
    Returning ``False`` rather than raising: "no release" is a condition the
    gate reports, not an error it hits.
    """
    if resolver is None:
        return False
    try:
        return resolver.resolve() is not None
    except Exception:  # pragma: no cover - a resolver that cannot resolve
        return False


def expert_review_module_markers(root: str) -> Tuple[str, ...]:
    """The WP-22 files that exist, checked on disk rather than imported.

    Read from the tree for the same reason WP-20 reads WP-21's markers that
    way: an ImportError in an unrelated module must not turn a truthful
    "not implemented" into a crash inside a gate builder.
    """
    return tuple(path for path in MODULE_MARKERS
                 if os.path.exists(os.path.join(root, *path.split("/"))))


def expert_review_gate_state(*, protocol_approved: bool,
                             expert_holdout_cases: int,
                             named_reviewers: int,
                             active_release: bool,
                             restricted_storage: bool,
                             production_authentication: bool,
                             completed_reviews: Optional[int]) -> str:
    """``PASS`` only when real experts completed real reviews.

    ``completed_reviews`` of ``None`` means no store was inspected, which is
    not the same as an inspected store holding none - but both block, and for
    the same reason: there is no evidence a review happened.
    """
    if not (protocol_approved and active_release and restricted_storage
            and production_authentication):
        return "BLOCKED"
    if expert_holdout_cases <= 0 or named_reviewers <= 0:
        return "BLOCKED"
    if not completed_reviews:
        return "BLOCKED"
    return "PASS"


def build_wp22_gate_status(root: str = None,
                           environ: Optional[Mapping[str, str]] = None,
                           release_resolver: Optional[Any] = None,
                           review_store: Optional[Any] = None,
                           principal_resolver: Optional[Any] = None
                           ) -> Dict[str, Any]:
    """The committed WP-22 gate status, measured from this repository."""
    if root is None:
        root = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                            "..", ".."))
    protocol = load_protocol(root)
    markers = expert_review_module_markers(root)
    implemented = len(markers) == len(MODULE_MARKERS)
    restricted = _restricted_storage_configured(environ)
    active_release = _active_release_available(release_resolver)
    boundary = DEFAULT_CLAIM_BOUNDARY

    # WP-22 may consume the existing static principal; it implements no
    # authentication of its own and must not claim any. The resolver is asked
    # whether it authenticates, and a resolver that does not answer is taken
    # as not authenticating - the failure direction that under-claims.
    production_authentication = False
    if principal_resolver is not None:
        production_authentication = bool(
            getattr(principal_resolver, "authenticates", False))

    expert_holdout_cases = 0
    try:
        from pgx.validation.catalog import development_cases
        from pgx.validation.separation import audit_partition
        audit = audit_partition(development_cases(root))
        expert_holdout_cases = audit.expert_holdout_count
        development_cases_count = audit.development_count
    except Exception:  # pragma: no cover - a catalogue that cannot be read
        development_cases_count = 0

    # ``None`` rather than ``0`` throughout: nobody inspected a store, so
    # nothing was counted. An inspected store holding zero rows reports 0, and
    # a reader must be able to tell "we looked and found none" from "we did
    # not look".
    assigned_reviews: Optional[int] = None
    completed_reviews: Optional[int] = None
    named_reviewers = 0
    if review_store is not None:
        assignments = list(getattr(review_store, "all_assignments",
                                   lambda: [])())
        assigned_reviews = len(assignments)
        named_reviewers = len({item.reviewer_actor for item in assignments})
        completed_reviews = sum(
            1 for item in assignments
            if getattr(item.state, "value", str(item.state)) == "COMPLETED")

    blockers: List[Dict[str, Any]] = []

    def _block(code: str, detail: str) -> None:
        blockers.append({"code": code, "blocking": True, "detail": detail,
                         "owner": EXPERT_REVIEW_BLOCKER_CODES[code]["owner"]})

    if not protocol.is_approved:
        _block("EXPERT_REVIEW_PROTOCOL_NOT_APPROVED",
               "protocol status is %s; missing signatory roles: %s"
               % (protocol.status,
                  ", ".join(protocol.missing_signatory_roles) or "none"))
    if expert_holdout_cases == 0:
        _block("EXPERT_REVIEW_NO_EXPERT_HOLDOUT_CASES",
               "expert holdout: 0; %d development case(s) exist and none may "
               "be substituted" % development_cases_count)
    if named_reviewers == 0:
        _block("EXPERT_REVIEW_NO_NAMED_REVIEWERS",
               "no review store was inspected, so no reviewer was counted"
               if review_store is None
               else "the inspected store names no reviewer")
    if not active_release:
        _block("EXPERT_REVIEW_NO_ACTIVE_RELEASE",
               "no release resolver is wired and no release is active")
    if not restricted:
        _block("EXPERT_REVIEW_RESTRICTED_STORAGE_NOT_CONFIGURED",
               "%s is unset or does not name a directory"
               % RESTRICTED_STORAGE_ENV)
    if not production_authentication:
        _block("EXPERT_REVIEW_NO_PRODUCTION_AUTHENTICATION",
               "WP-22 consumes the existing static principal and implements "
               "no authentication; WP-23 owns that work")
    _block("EXPERT_REVIEW_NONE_COMPLETED",
           "no review store was inspected, so no completed review count was "
           "taken" if completed_reviews is None
           else "%d completed review(s) in the inspected store"
                % completed_reviews)
    if not boundary.is_approved:
        _block("EXPERT_REVIEW_CLAIM_BOUNDARY_NOT_APPROVED",
               "claim boundary status is %s" % boundary.status)
    blockers.sort(key=lambda item: (item["code"], item["detail"]))

    state = expert_review_gate_state(
        protocol_approved=protocol.is_approved,
        expert_holdout_cases=expert_holdout_cases,
        named_reviewers=named_reviewers,
        active_release=active_release,
        restricted_storage=restricted,
        production_authentication=production_authentication,
        completed_reviews=completed_reviews)

    return {
        "gate_status_schema_version": GATE_STATUS_VERSION,
        "work_package": "WP-22",
        "implementation_status": ("IMPLEMENTED" if implemented
                                  else "NOT_IMPLEMENTED"),
        "implementation_note": (
            "The protocol document, the review state machine, the blinding "
            "structure, the append-only records, the audit chain, the "
            "persistence layer, the API and the reviewer pages are "
            "implemented. That is a statement about software. Whether any "
            "expert reviewed anything is the separate question below, and "
            "the answer is no."),
        "expert_review_gate_status": state,
        "release_may_proceed": state == "PASS",
        "expert_review_module_implemented": implemented,
        "module_marker_paths": list(MODULE_MARKERS),
        "module_marker_present_count": len(markers),
        "review_vocabulary_version": VOCABULARY_VERSION,
        "review_state_count": len(TRANSITIONS),
        "review_error_code_count": len(REVIEW_ERROR_CODES),
        "likert_dimension_count": len(LIKERT_DIMENSIONS),
        "protocol": protocol.to_json(),
        "protocol_documented": protocol.is_documented,
        "protocol_approved": protocol.is_approved,
        "protocol_status": protocol.status,
        "required_signatory_roles": list(REQUIRED_SIGNATORY_ROLES),
        "protocol_signatory_count": len(protocol.signatories),
        "missing_signatory_roles": list(protocol.missing_signatory_roles),
        "named_reviewer_count": named_reviewers,
        "assigned_review_count": assigned_reviews,
        "completed_review_count": completed_reviews,
        "review_count_source": (
            "null rather than zero: no review store was inspected, so no "
            "count was taken" if completed_reviews is None
            else "counted from the supplied review store"),
        "expert_holdout_case_count": expert_holdout_cases,
        "development_case_count": development_cases_count,
        "development_is_not_review_material": (
            "The %d development cases shaped the software. Assigning one to "
            "an expert would produce a review of the material the system was "
            "built on, which is not evidence about anything else."
            % development_cases_count),
        "active_release_available": active_release,
        "restricted_storage_configured": restricted,
        "production_authentication_available": production_authentication,
        "authentication_boundary_note": (
            "WP-22 consumes the existing Principal, Role.EXPERT_REVIEWER and "
            "PrincipalResolver. It implements no passwords, sessions, "
            "tokens, login, signup or authentication tables, and it does not "
            "mark WP-18's access-ledger actor as authenticated. Until WP-23 "
            "supplies real authentication, an actor string identifies a "
            "configured principal and not a person."),
        "expert_review_performed": False,
        "expert_review_performed_note": (
            "False, and not a placeholder. Six preconditions are missing and "
            "five of them are owned by people: an approved protocol, an "
            "expert-holdout case, a named reviewer, an active release, "
            "restricted storage and production authentication. No change to "
            "this repository alone can make this true."),
        "clinical_validation_performed": False,
        "scientific_validation_performed": False,
        "claim_boundary_status": boundary.status,
        "claim_boundary_approved": boundary.is_approved,
        "blockers": blockers,
        "blocking_count": sum(1 for item in blockers if item["blocking"]),
        "not_clinical_validation": (
            "This document describes review machinery and its current empty "
            "state. It is not clinical validation, scientific validation or "
            "evidence of either. A correctly recorded review is a record "
            "that software worked, not a finding about a patient."),
    }
