"""The web surface, declared once.

Eleven pages, closed. Three things read this table and nothing else defines
them: the FastAPI routers register from it, the published route-surface
artifact is generated from it, and the boundary tests assert against it. The
same arrangement WP-16 uses for the API, for the same reason - "is this page
documented, authorised and tested?" should have a mechanical answer.

Two constraints are enforced at import rather than reviewed:

**No web path may shadow an API path.** ``/api/``, ``/health/``, ``/openapi``
and the documentation paths are reserved. A page that claimed one would take
traffic from the API in the combined application, and the symptom would be an
API client receiving HTML.

**Every state-changing route requires CSRF verification.** The flag is not
optional and not per-router: a ``POST`` declared here without
``requires_csrf`` fails the import. WP-23 supplies the real verifier; until
then the production verifier refuses, which is why these routes are
unavailable rather than unprotected.

Roles come from :mod:`apps.api.security` - the same three governed roles, the
same explicit sets, the same absence of a hierarchy. A second role vocabulary
for the interface would be a second thing to keep in step with the audit
trail.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional, Tuple

from apps.api.security import PUBLIC, AccessPolicy, Role, roles
from apps.web import RESERVED_PATH_PREFIXES

__all__ = [
    "PUBLIC_ROUTES",
    "STATE_CHANGING_ROUTES",
    "WEB_ROUTES",
    "WEB_ROUTES_BY_NAME",
    "WebParameter",
    "WebRoute",
    "web_route",
]

_ANY_USER = roles(Role.DEMO_USER, Role.EXPERT_REVIEWER, Role.ADMIN)
_REVIEWER = roles(Role.EXPERT_REVIEWER)

_UUID_PATTERN = (r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
                 r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

#: A development case identifier. Deliberately narrow: these identifiers are
#: minted by the migration and are never user text.
_CASE_ID_PATTERN = r"^WP17-CASE-[A-Z0-9][A-Z0-9-]{0,31}$"


@dataclass(frozen=True, slots=True)
class WebParameter:
    """One bounded path or query parameter.

    Every parameter carries a pattern or a numeric range, for the reason
    WP-16's do: an unconstrained identifier reaching a lookup is an injection
    surface, and an unconstrained integer is a denial of service.
    """

    name: str
    location: str
    kind: str
    required: bool
    description: str
    pattern: Optional[str] = None
    max_length: Optional[int] = None
    minimum: Optional[int] = None
    maximum: Optional[int] = None
    default: Optional[object] = None

    def __post_init__(self) -> None:
        if self.location not in ("path", "query"):
            raise ValueError("a web parameter is a path or query parameter")
        if self.kind not in ("string", "integer"):
            raise ValueError("a web parameter is a string or an integer")
        if self.kind == "string" and self.pattern is None:
            raise ValueError(
                "a string parameter declares the exact shape it accepts")
        if self.kind == "integer" and (self.minimum is None
                                       or self.maximum is None):
            raise ValueError("an integer parameter declares its range")
        if self.location == "path" and not self.required:
            raise ValueError("a path parameter is always required")


@dataclass(frozen=True, slots=True)
class WebRoute:
    """One page: its address, its template, and who may reach it."""

    name: str
    method: str
    path: str
    title_key: str
    template: str
    access: AccessPolicy
    description: str
    parameters: Tuple[WebParameter, ...] = ()
    requires_csrf: bool = False
    nav_key: Optional[str] = None
    success_status: int = 200

    def __post_init__(self) -> None:
        if self.method not in ("GET", "POST"):
            raise ValueError("the web surface is GET and POST only")
        if not self.path.startswith("/"):
            raise ValueError("a route path is absolute")
        for reserved in RESERVED_PATH_PREFIXES:
            if self.path == reserved.rstrip("/") or \
                    self.path.startswith(reserved):
                raise ValueError(
                    "web route %s would shadow the reserved path %s; an API "
                    "client would receive HTML" % (self.name, reserved))
        if self.method == "POST" and not self.requires_csrf:
            raise ValueError(
                "state-changing route %s must declare CSRF verification"
                % self.name)
        if self.method == "GET" and self.requires_csrf:
            raise ValueError(
                "a GET route changes nothing and needs no CSRF token")
        declared = {item.name for item in self.parameters
                    if item.location == "path"}
        in_path = {segment[1:-1] for segment in self.path.split("/")
                   if segment.startswith("{") and segment.endswith("}")}
        if declared != in_path:
            raise ValueError(
                "route %s declares path parameters %s and its path names %s"
                % (self.name, sorted(declared), sorted(in_path)))

    @property
    def path_parameters(self) -> Tuple[WebParameter, ...]:
        return tuple(item for item in self.parameters
                     if item.location == "path")

    @property
    def query_parameters(self) -> Tuple[WebParameter, ...]:
        return tuple(item for item in self.parameters
                     if item.location == "query")

    def url(self, **values: object) -> str:
        """Build this route's URL. The only way a template gets a link.

        Templates never concatenate a path. Every anchor comes from here, so
        a page cannot link somewhere the route table does not describe, and a
        path that changes changes in one place.
        """
        path = self.path
        for parameter in self.path_parameters:
            if parameter.name not in values:
                raise KeyError("route %s needs %s" % (self.name,
                                                      parameter.name))
            path = path.replace("{%s}" % parameter.name,
                                str(values[parameter.name]))
        return path


_CASE_ID = WebParameter(
    name="case_id", location="path", kind="string", required=True,
    description="A development case identifier minted by the WP-17 migration.",
    pattern=_CASE_ID_PATTERN, max_length=48)

_ASSESSMENT_ID = WebParameter(
    name="assessment_id", location="path", kind="string", required=True,
    description="The immutable identity of a stored assessment.",
    pattern=_UUID_PATTERN, max_length=36)

_EVIDENCE_ID = WebParameter(
    name="evidence_id", location="path", kind="string", required=True,
    description="The immutable record identity of one evidence record.",
    pattern=_UUID_PATTERN, max_length=36)

_REVIEW_CASE_ID = WebParameter(
    name="case_id", location="path", kind="string", required=True,
    description="An expert-review case identifier. Never resolved: this page "
                "reports nothing about whether the case exists.",
    pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$", max_length=64)


WEB_ROUTES: Tuple[WebRoute, ...] = (
    WebRoute(
        name="web.home",
        method="GET",
        path="/",
        title_key="home.heading",
        template="home.html",
        access=PUBLIC,
        nav_key="nav.home",
        description=(
            "The entry page. Public, because a page that required a principal "
            "in a deployment where none can be established would leave a "
            "visitor at an error with nothing to do. It shows the warning, "
            "the navigation and the environment, and no case data."),
    ),
    WebRoute(
        name="web.login",
        method="GET",
        path="/login",
        title_key="login.heading",
        template="login.html",
        access=PUBLIC,
        nav_key="nav.login",
        description=(
            "The login form. Public because an unauthenticated visitor is "
            "exactly who needs it. It sets a short-lived host-scoped pre-auth "
            "cookie and renders a CSRF token bound to it; it displays no "
            "credential and states nothing about whether any username "
            "exists."),
    ),
    WebRoute(
        name="web.login_submit",
        method="POST",
        path="/login",
        title_key="login.heading",
        template="login.html",
        access=PUBLIC,
        requires_csrf=True,
        description=(
            "Authenticate and start a session. Public in the access-policy "
            "sense - there is no principal yet - and emphatically not "
            "unprotected: the pre-auth CSRF token is verified first. A login "
            "form without CSRF lets an attacker log a victim into the "
            "attacker's account, and everything the victim then does happens "
            "in a session the attacker controls."),
    ),
    WebRoute(
        name="web.logout",
        method="POST",
        path="/logout",
        title_key="login.heading",
        template="login.html",
        access=PUBLIC,
        requires_csrf=True,
        description=(
            "Revoke the server-side session, then clear the cookie. In that "
            "order: clearing first would leave a live session the user "
            "believes is closed, usable by anyone holding a copy of the "
            "token."),
    ),
    WebRoute(
        name="web.cases",
        method="GET",
        path="/cases",
        title_key="cases.heading",
        template="cases.html",
        access=_ANY_USER,
        nav_key="nav.cases",
        description=(
            "The synthetic development case catalogue, read from the sealed "
            "WP-17 artifact. Never from the legacy seed file."),
    ),
    WebRoute(
        name="web.case_detail",
        method="GET",
        path="/cases/{case_id}",
        title_key="case.heading",
        template="case_detail.html",
        access=_ANY_USER,
        parameters=(_CASE_ID,),
        description=(
            "One development case: its canonical observations, the pinned "
            "release's medication catalogue, and exactly which fields a "
            "submission would carry."),
    ),
    WebRoute(
        name="web.case_assess",
        method="POST",
        path="/cases/{case_id}/assess",
        title_key="assessment.heading",
        template="assessment.html",
        access=_ANY_USER,
        parameters=(_CASE_ID,),
        requires_csrf=True,
        success_status=200,
        description=(
            "Submit one synthetic assessment through the WP-16 client. The "
            "only state-changing page route. Unavailable in production until "
            "a CSRF verifier and an authentication provider exist."),
    ),
    WebRoute(
        name="web.assessment",
        method="GET",
        path="/assessments/{assessment_id}",
        title_key="assessment.heading",
        template="assessment.html",
        access=_ANY_USER,
        parameters=(_ASSESSMENT_ID,),
        description=(
            "One stored assessment, rendered from the exact WP-16 response. "
            "Reports the release it was pinned to, whatever is active now."),
    ),
    WebRoute(
        name="web.evidence",
        method="GET",
        path="/evidence/{evidence_id}",
        title_key="evidence.heading",
        template="evidence.html",
        access=_ANY_USER,
        parameters=(_EVIDENCE_ID,),
        description=(
            "One evidence record's immutable provenance projection. Identity "
            "and hashes; no source prose, no path, no authored advice."),
    ),
    WebRoute(
        name="web.validation",
        method="GET",
        path="/validation",
        title_key="validation.heading",
        template="validation.html",
        access=_ANY_USER,
        nav_key="nav.validation",
        description=(
            "The shell and the honest empty state. No metric is computed and "
            "no zero denominator becomes a percentage."),
    ),
    WebRoute(
        name="web.expert_review",
        method="GET",
        path="/expert-reviews/{case_id}",
        title_key="expert.heading",
        template="expert_review.html",
        access=_REVIEWER,
        parameters=(_REVIEW_CASE_ID,),
        nav_key="nav.expert_review",
        description=(
            "The reviewer's own assignment, state-aware. Blinded until a "
            "reveal record exists: the view model has no field a result "
            "could occupy, so no template mistake can leak one into a hidden "
            "element. A missing or foreign assignment renders one controlled "
            "unavailable state that discloses nothing about whether the case "
            "exists."),
    ),
    WebRoute(
        name="web.expert_review_expected",
        method="POST",
        path="/expert-reviews/{case_id}/expected",
        title_key="expert.heading",
        template="expert_review.html",
        access=_REVIEWER,
        parameters=(_REVIEW_CASE_ID,),
        requires_csrf=True,
        success_status=200,
        description=(
            "Lock the expected response. Unavailable in production until a "
            "CSRF verifier and an authentication provider exist, which is "
            "WP-23's work - the form renders inert without both."),
    ),
    WebRoute(
        name="web.expert_review_reveal",
        method="POST",
        path="/expert-reviews/{case_id}/reveal",
        title_key="expert.heading",
        template="expert_review.html",
        access=_REVIEWER,
        parameters=(_REVIEW_CASE_ID,),
        requires_csrf=True,
        success_status=200,
        description=(
            "The one-way door. Permitted only once an expectation is locked, "
            "and only once."),
    ),
    WebRoute(
        name="web.expert_review_complete",
        method="POST",
        path="/expert-reviews/{case_id}/complete",
        title_key="expert.heading",
        template="expert_review.html",
        access=_REVIEWER,
        parameters=(_REVIEW_CASE_ID,),
        requires_csrf=True,
        success_status=200,
        description=(
            "Record AGREE, PARTIAL or DISAGREE and any optional ratings. The "
            "record is immutable afterwards."),
    ),
    WebRoute(
        name="web.system",
        method="GET",
        path="/system",
        title_key="system.heading",
        template="system.html",
        access=PUBLIC,
        nav_key="nav.system",
        description=(
            "The active release and the readiness report, exactly as WP-16 "
            "returns them. Public on the same terms as the API's own version "
            "and health routes."),
    ),
)

WEB_ROUTES_BY_NAME: Mapping[str, WebRoute] = {
    route.name: route for route in WEB_ROUTES}

PUBLIC_ROUTES: Tuple[str, ...] = tuple(
    route.name for route in WEB_ROUTES if route.access.public)

STATE_CHANGING_ROUTES: Tuple[str, ...] = tuple(
    route.name for route in WEB_ROUTES if route.method == "POST")

#: The navigation, in display order. A subset of the routes: a page reachable
#: only from another page is deliberate, not an omission.
NAVIGATION: Tuple[str, ...] = (
    "web.home", "web.cases", "web.validation", "web.system", "web.login")


def web_route(name: str) -> WebRoute:
    """Look up one route, or fail loudly."""
    try:
        return WEB_ROUTES_BY_NAME[name]
    except KeyError:  # pragma: no cover - defensive
        raise KeyError("no web route named %r" % name) from None


def _check_table() -> None:
    """Invariants checked at import, so a mistake stops a start-up."""
    from apps.web.labels import UI_TEXT

    seen_names, seen_addresses = set(), set()
    for route in WEB_ROUTES:
        if route.name in seen_names:
            raise ValueError("duplicate web route name %r" % route.name)
        seen_names.add(route.name)
        address = (route.method, route.path)
        if address in seen_addresses:
            raise ValueError("duplicate web route %s %s" % address)
        seen_addresses.add(address)
        if route.title_key not in UI_TEXT:
            raise ValueError("route %s names unknown title key %r"
                             % (route.name, route.title_key))
        if route.nav_key is not None and route.nav_key not in UI_TEXT:
            raise ValueError("route %s names unknown navigation key %r"
                             % (route.name, route.nav_key))
    for name in NAVIGATION:
        if name not in seen_names:
            raise ValueError("navigation names unknown route %r" % name)


_check_table()
