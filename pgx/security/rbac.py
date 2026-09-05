# -*- coding: utf-8 -*-
"""The authoritative permission registry (WP-23).

One table, every cell written out. There is no hierarchy, no inheritance, no
wildcard and no "admin can do anything" shortcut, and the absence is the
design rather than an omission.

**Why no hierarchy.** A hierarchy is convenient exactly until a role is added
in the middle of it. Then every gate written to mean "only a reviewer" quietly
means "a reviewer or anyone above one", and the change that broke it touched
neither the gate nor the route - it added an enum member. Here a permission is
held by a role or it is not, and adding a role adds a column of explicit
decisions.

**Why ADMIN holds no expert-review permission.** An administrator can create
users, activate releases and read the audit trail. None of that makes them a
blind reviewer, and letting it would destroy the property WP-22 exists for: a
review is evidence only if the reviewer did not build the thing they reviewed.
An administrator who must review holds a second account whose exact role is
``EXPERT_REVIEWER`` - and even then WP-22's assignment check and payload
permit still apply. This registry grants the *ability to attempt* an
operation; it never grants an assignment.

**Why authentication roles do not touch curation roles.** WP-09 and WP-10
define author, reviewer and adjudicator as separation-of-duty roles on a
curation record. ``curation.administer`` here means "may operate the curation
tooling", not "may approve their own revision". Collapsing the two would make
the separation decorative, so this module deliberately has no permission that
names a curation *decision*.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, FrozenSet, Mapping, Tuple

from pgx.security.errors import AuthorizationDenied
from pgx.security.vocabulary import GOVERNED_ROLES

__all__ = [
    "PERMISSIONS",
    "PERMISSION_IDS",
    "RBAC_REGISTRY_VERSION",
    "Permission",
    "permissions_for_role",
    "registry_digest",
    "registry_document",
    "require_permission",
    "role_holds",
    "roles_holding",
]

RBAC_REGISTRY_VERSION = "pgx-wp23-rbac-registry/1"

_DEMO = "DEMO_USER"
_REVIEWER = "EXPERT_REVIEWER"
_ADMIN = "ADMIN"


@dataclass(frozen=True, slots=True)
class Permission:
    """One named ability, and the exact roles that hold it."""

    permission_id: str
    title: str
    #: What refusing this protects. Written for the person reading the
    #: registry document, who will not have this source open.
    rationale: str
    holders: FrozenSet[str]
    #: The governed surface this permission guards, so the artifact can be
    #: grouped and a reviewer can see the whole of one area at once.
    area: str

    def __post_init__(self) -> None:
        unknown = set(self.holders) - set(GOVERNED_ROLES)
        if unknown:
            raise ValueError(
                "permission %s names roles that do not exist: %s"
                % (self.permission_id, ", ".join(sorted(unknown))))

    def to_json(self) -> dict:
        return {"permission_id": self.permission_id, "title": self.title,
                "area": self.area, "rationale": self.rationale,
                "holders": sorted(self.holders)}


def _p(permission_id: str, title: str, area: str, rationale: str,
       *holders: str) -> Permission:
    return Permission(permission_id=permission_id, title=title, area=area,
                      rationale=rationale, holders=frozenset(holders))


#: The registry. Every governed ability in the system, with its exact holders.
#:
#: Read this as the security answer to "who may do what". The route tables in
#: ``apps.api.routes`` and ``apps.web.routes`` still declare roles directly -
#: that is what FastAPI enforces - and a test proves the two agree, so a route
#: cannot quietly widen beyond what this table permits.
PERMISSIONS: Tuple[Permission, ...] = (
    # -- session self-management ----------------------------------------
    _p("session.login", "Authenticate and start a session", "session",
       "Every role may hold an account. Refusing this to a role would make "
       "the account unusable rather than restricted.",
       _DEMO, _REVIEWER, _ADMIN),
    _p("session.logout", "End one's own session", "session",
       "A user must always be able to end their own session; a logout that "
       "could be forbidden is a session that cannot be revoked by the person "
       "most likely to notice it was stolen.",
       _DEMO, _REVIEWER, _ADMIN),
    _p("session.read_self", "Read one's own actor identifier and role",
       "session",
       "Bounded to the actor string and the role. There is no personal "
       "detail to read, because none is stored.",
       _DEMO, _REVIEWER, _ADMIN),

    # -- assessment and reading -----------------------------------------
    _p("assessment.create", "Run a demo assessment", "assessment",
       "The representative workflow. Permitted to every role because the "
       "input is a synthetic or development case, never a patient.",
       _DEMO, _REVIEWER, _ADMIN),
    _p("assessment.read", "Read an assessment result", "assessment",
       "Reading a result the same deployment produced. Holdout payloads are "
       "not reachable through this permission; WP-18's access policy governs "
       "those separately and refuses regardless of role.",
       _DEMO, _REVIEWER, _ADMIN),
    _p("catalogue.read", "Read the gene and drug catalogue", "catalogue",
       "Public scientific nomenclature. Refusing it would not protect "
       "anything and would make the interface unusable.",
       _DEMO, _REVIEWER, _ADMIN),
    _p("evidence.read", "Read an evidence record", "catalogue",
       "Traceability is the product. A finding whose citation cannot be "
       "opened is an assertion.",
       _DEMO, _REVIEWER, _ADMIN),
    _p("validation.read_public", "Read the public validation dashboard",
       "validation",
       "The dashboard publishes counts and empty states, never a holdout "
       "case or an expert response.",
       _DEMO, _REVIEWER, _ADMIN),

    # -- expert review: EXPERT_REVIEWER only, and assignment still applies
    _p("expert_review.list_assigned", "List one's own review assignments",
       "expert_review",
       "Only assignments belonging to the caller. ADMIN is excluded: an "
       "administrator who could enumerate assignments could enumerate the "
       "expert-holdout set.",
       _REVIEWER),
    _p("expert_review.read_assigned", "Open an assigned review", "expert_review",
       "Holding this permission does not produce an assignment. WP-22 "
       "refuses an unassigned case with the same answer it gives for a case "
       "that does not exist.",
       _REVIEWER),
    _p("expert_review.submit_expected", "Record a blinded expected response",
       "expert_review",
       "The blinded half of the protocol. An administrator recording an "
       "expectation would be the system predicting its own output.",
       _REVIEWER),
    _p("expert_review.reveal_assigned", "Reveal the system result",
       "expert_review",
       "The one-way door. No role may pass it without an assignment and a "
       "locked expectation, and no permission here can substitute for "
       "either.",
       _REVIEWER),
    _p("expert_review.complete_assigned", "Close an assigned review",
       "expert_review",
       "Records AGREE, PARTIAL or DISAGREE against a revealed result.",
       _REVIEWER),
    _p("expert_review.append_correction", "Append a review correction",
       "expert_review",
       "Append-only amendment by the reviewer who made the record.",
       _REVIEWER),

    # -- administration: ADMIN only --------------------------------------
    _p("release.register", "Register a release bundle", "release",
       "Release identity is what every audit row and every assessment pins.",
       _ADMIN),
    _p("release.activate", "Activate a release", "release",
       "Moves the pointer every subsequent assessment reads.", _ADMIN),
    _p("release.rollback", "Roll back to a previous release", "release",
       "The recovery path. Audited with both sides of the pointer move.",
       _ADMIN),
    _p("release.retire", "Retire a release", "release",
       "Ends a release's eligibility without deleting its evidence.", _ADMIN),
    _p("source_policy.administer", "Administer the scientific source policy",
       "curation",
       "Which sources may be published from. A scientific decision recorded "
       "by an operator, not made by one.", _ADMIN),
    _p("curation.administer", "Operate the curation workflow", "curation",
       "Operating the tooling. This is NOT authority to author, review or "
       "adjudicate a revision: WP-09's separation of duty governs those and "
       "is unchanged by any application role.", _ADMIN),
    _p("rule.administer", "Administer computable rules", "rules",
       "Validation and deprecation of rules under the approved protocol.",
       _ADMIN),
    _p("ruleset.administer", "Administer ruleset versions", "rules",
       "Freeze, reopen and retire. A frozen ruleset is what a release pins.",
       _ADMIN),
    _p("user.administer", "Create, disable, lock and re-role local users",
       "administration",
       "Account lifecycle. Never deletion: a deleted user takes the subject "
       "of their own audit history with them.", _ADMIN),
    _p("audit.read", "Read the governed audit trail", "administration",
       "Safe projections only. The reader exposes no payload, no expected "
       "response and no secret.", _ADMIN),
    _p("audit.verify", "Verify the audit hash chain", "administration",
       "Reports the first break and its position, never the content of any "
       "event.", _ADMIN),
)

PERMISSION_IDS: Tuple[str, ...] = tuple(
    item.permission_id for item in PERMISSIONS)

_BY_ID: Mapping[str, Permission] = {item.permission_id: item
                                    for item in PERMISSIONS}

if len(_BY_ID) != len(PERMISSIONS):  # pragma: no cover - import-time guard
    raise RuntimeError("the RBAC registry declares a duplicate permission id")


def role_holds(role: str, permission_id: str) -> bool:
    """Whether exactly this role holds exactly this permission.

    No hierarchy is consulted, because there is none. An unknown permission id
    raises rather than returning ``False``: a typo in a permission name must
    not read as a quiet denial that somebody later "fixes" by widening a role.
    """
    permission = _BY_ID.get(permission_id)
    if permission is None:
        raise KeyError(
            "%r is not a declared permission; a check against an undeclared "
            "permission would silently deny and then silently permit when "
            "somebody added it" % permission_id)
    return role in permission.holders


def require_permission(role: str, permission_id: str) -> None:
    """Raise :class:`AuthorizationDenied` unless the role holds it."""
    if not role_holds(role, permission_id):
        raise AuthorizationDenied(
            "the role does not hold this permission",
            code="PERMISSION_DENIED",
            details={"required_permission": permission_id})


def permissions_for_role(role: str) -> Tuple[str, ...]:
    """Every permission this role holds, sorted. Never inherited."""
    if role not in GOVERNED_ROLES:
        raise KeyError("%r is not a governed role" % role)
    return tuple(sorted(item.permission_id for item in PERMISSIONS
                        if role in item.holders))


def roles_holding(permission_id: str) -> Tuple[str, ...]:
    permission = _BY_ID.get(permission_id)
    if permission is None:
        raise KeyError("%r is not a declared permission" % permission_id)
    return tuple(sorted(permission.holders))


def registry_digest() -> str:
    """A hash over the whole matrix.

    Published in the gate status so a silent widening of any role shows up as
    a changed digest even if nobody reads the table.
    """
    from pgx.domain.hashing import sha256_digest
    return sha256_digest({
        "rbac_registry_version": RBAC_REGISTRY_VERSION,
        "permissions": [item.to_json() for item in PERMISSIONS]})


def registry_document() -> Dict[str, object]:
    """The published registry, as an artifact."""
    matrix: Dict[str, Dict[str, bool]] = {}
    for permission in PERMISSIONS:
        matrix[permission.permission_id] = {
            role: role in permission.holders
            for role in sorted(GOVERNED_ROLES)}
    return {
        "rbac_registry_version": RBAC_REGISTRY_VERSION,
        "registry_digest": registry_digest(),
        "roles": sorted(GOVERNED_ROLES),
        "role_hierarchy": None,
        "role_hierarchy_note": (
            "null, and not an empty list: there is no hierarchy to describe. "
            "Every permission names its holders explicitly, so adding a role "
            "adds a column of decisions rather than inheriting a set."),
        "permission_count": len(PERMISSIONS),
        "permissions": [item.to_json() for item in PERMISSIONS],
        "matrix": matrix,
        "permissions_by_role": {
            role: list(permissions_for_role(role))
            for role in sorted(GOVERNED_ROLES)},
        "admin_is_not_a_reviewer": (
            "ADMIN holds no expert_review.* permission. An administrator who "
            "must review holds a separate account whose exact role is "
            "EXPERT_REVIEWER, and WP-22's assignment check and payload permit "
            "still apply to it."),
        "authentication_does_not_grant_curation_authority": (
            "curation.administer permits operating the curation tooling. It "
            "is not authority to author, review or adjudicate a revision: "
            "WP-09's separation-of-duty rules govern those and no application "
            "role overrides them."),
    }
