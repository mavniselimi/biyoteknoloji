"""Assemble each screen: fetch, model, render, gate.

One function per page, each following the same four steps and none skipping
one. Route handlers call these; the handlers themselves hold nothing but
wiring, which is what lets the whole interface be exercised in an environment
where no ASGI server can run.

The order is the safety property. A page is *rendered* only after its model is
built, and a model is *built* only after the client validated the response
against the WP-16 contract - and for the assessment page, only after the
fact-preservation check has compared the model with the response it came from.
The gate then refuses to return HTML that carries a prohibited claim or unsafe
markup. Four checks, each of which can only fail closed: every one of them
raises rather than returning something partial.

Failures land on the error page, and the error page is rendered through the
same gate. A failure path that skipped the scanner would be the path most
likely to interpolate something unexpected.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from apps.web import DEFAULT_LOCALE
from apps.web.client import PgxApiClient
from apps.web.errors import WebError
from apps.web.labels import field_label, ui_table
from apps.web.render import render_page
from apps.web.routes import web_route
from apps.web.view_models.assessment import build_assessment_page
from apps.web.view_models.base import PageContext, build_page_context
from apps.web.view_models.pages import (build_case_detail, build_case_list,
                                        build_error_page, build_evidence_page,
                                        build_expert_review_page,
                                        build_login_page, build_system_page,
                                        build_validation_board)
from pgx.reporting.templates import FIELD_LABELS, require_locale

__all__ = [
    "PageResult",
    "render_assessment_page",
    "render_case_detail_page",
    "render_cases_page",
    "render_error_page",
    "render_evidence_page",
    "render_expert_review_page",
    "render_home_page",
    "render_login_page",
    "render_system_page",
    "render_validation_page",
]


@dataclass(frozen=True, slots=True)
class PageResult:
    """One rendered page, with the status and headers it should be sent with."""

    html: str
    status: int
    route_name: str
    request_id: str

    @property
    def headers(self) -> Dict[str, str]:
        from apps.api.request_id import REQUEST_ID_HEADER
        from apps.web.security import security_headers

        headers = dict(security_headers())
        headers["Content-Type"] = "text/html; charset=utf-8"
        if self.request_id:
            headers[REQUEST_ID_HEADER] = self.request_id
        return headers


def _field_table(locale: str) -> Dict[str, str]:
    """WP-15's field labels in one locale, for the templates."""
    key = require_locale(locale)
    return {name: table[key] for name, table in FIELD_LABELS.items()
            if key in table}


def _context(route_name: str, *, locale: str, environment: str,
             request_id: str, asset_version: str,
             dependency_notice: Optional[str]) -> Dict[str, Any]:
    page = build_page_context(
        route_name=route_name, locale=locale, environment=environment,
        request_id=request_id, asset_version=asset_version,
        dependency_notice=dependency_notice)
    return {"page": page, "text": ui_table(locale),
            "field": _field_table(locale)}


@dataclass(frozen=True, slots=True)
class PageEnvironment:
    """What every page needs that is not about the page.

    Passed as one object rather than six arguments so a new frame-level value
    reaches every screen by being added here, instead of by being threaded
    through ten call sites and forgotten in one.
    """

    locale: str = DEFAULT_LOCALE
    environment: str = ""
    request_id: str = ""
    asset_version: str = "1"
    dependency_notice: Optional[str] = None

    def context(self, route_name: str) -> Dict[str, Any]:
        return _context(route_name, locale=self.locale,
                        environment=self.environment,
                        request_id=self.request_id,
                        asset_version=self.asset_version,
                        dependency_notice=self.dependency_notice)


def _render(route_name: str, context: Mapping[str, Any], *,
            status: int, request_id: str) -> PageResult:
    route = web_route(route_name)
    html = render_page(route.template, context)
    return PageResult(html=html, status=status, route_name=route_name,
                      request_id=request_id)


# ---------------------------------------------------------------------------
# Pages that need no client call
# ---------------------------------------------------------------------------

def render_home_page(env: PageEnvironment) -> PageResult:
    return _render("web.home", env.context("web.home"), status=200,
                   request_id=env.request_id)


def render_login_page(env: PageEnvironment, *,
                      authentication_configured: bool = False,
                      form_enabled: bool = False,
                      csrf_token: Optional[str] = None,
                      failed: bool = False, rate_limited: bool = False,
                      actor: Optional[str] = None,
                      role: Optional[str] = None) -> PageResult:
    """The login form, or the signed-in identity, or the unavailable state.

    ``failed`` is a boolean and carries no reason. The page must not tell an
    unknown username apart from a wrong password, so there is no parameter
    here that could express the difference - the reason is recorded on the
    server, in the audit row, and never travels.
    """
    context = env.context("web.login")
    context["model"] = build_login_page(
        authentication_configured=authentication_configured,
        form_enabled=form_enabled, csrf_token=csrf_token, failed=failed,
        rate_limited=rate_limited, actor=actor, role=role,
        locale=env.locale)
    return _render("web.login", context, status=200,
                   request_id=env.request_id)


def render_expert_review_page(env: PageEnvironment, *, case_id: str,
                              view: Any = None, protocol: Any = None,
                              csrf_token: Optional[str] = None,
                              forms_enabled: bool = False) -> PageResult:
    """The reviewer's own assignment, blinded until a reveal record exists.

    ``view`` is ``None`` for three conditions that must stay
    indistinguishable: no such case, not an expert-holdout case, and assigned
    to somebody else. All three render one controlled unavailable state, so
    the page is byte-identical whichever holds - a reviewer who could tell
    them apart would have an enumeration tool for the holdout set.

    The status is 200 in every case: the *page* rendered successfully and
    says what is available. A browser receiving 4xx shows an error rather
    than the explanation a reviewer needs, and the API - which is where a
    machine caller belongs - returns the real codes.
    """
    context = env.context("web.expert_review")
    context["model"] = build_expert_review_page(
        case_id, view=view, protocol=protocol, csrf_token=csrf_token,
        forms_enabled=forms_enabled, locale=env.locale)
    return _render("web.expert_review", context, status=200,
                   request_id=env.request_id)


def render_error_page(env: PageEnvironment, *, code: str,
                      route_name: str = "web.home") -> PageResult:
    """The controlled failure page, rendered through the same gate.

    ``route_name`` only decides which navigation entry is marked current. It
    does not change the content, and no caller can supply a message.
    """
    from apps.api.errors import status_for_code

    context = env.context(route_name)
    context["model"] = build_error_page(code, request_id=env.request_id,
                                        locale=env.locale)
    route = web_route(route_name)
    html = render_page("error.html", context)
    return PageResult(html=html, status=status_for_code(code),
                      route_name=route_name, request_id=env.request_id)


# ---------------------------------------------------------------------------
# Pages backed by the case catalogue
# ---------------------------------------------------------------------------

def render_cases_page(env: PageEnvironment, *,
                      cases: Sequence[Any],
                      available: bool = True) -> PageResult:
    context = env.context("web.cases")
    context["model"] = build_case_list(cases, locale=env.locale,
                                       available=available)
    return _render("web.cases", context, status=200,
                   request_id=env.request_id)


def render_case_detail_page(env: PageEnvironment, *, case: Any,
                            client: PgxApiClient,
                            submit_available: bool = False,
                            csrf_token: Optional[str] = None) -> PageResult:
    """One case, with the pinned release's medication catalogue.

    The catalogue call is allowed to fail without failing the page: a case's
    observations and provenance are worth showing even when no release is
    active, and the medication section then says so. That is the one place
    this module tolerates a partial page, and it is deliberate - the missing
    part is an *input control*, not a governed fact, and its absence is
    stated rather than implied.
    """
    drugs: List[Mapping[str, Any]] = []
    drugs_available = True
    try:
        response = client.list_drugs(request_id=env.request_id)
        drugs = list(response.document.get("items") or ())
    except WebError:
        drugs_available = False

    context = env.context("web.case_detail")
    context["model"] = build_case_detail(
        case, drugs=drugs, drugs_available=drugs_available,
        submit_available=bool(submit_available and drugs_available),
        csrf_token=csrf_token, locale=env.locale)
    return _render("web.case_detail", context, status=200,
                   request_id=env.request_id)


# ---------------------------------------------------------------------------
# Pages backed by the API client
# ---------------------------------------------------------------------------

def render_assessment_page(env: PageEnvironment, *,
                           document: Mapping[str, Any],
                           status: int = 200) -> PageResult:
    """The assessment screen, from one already-validated response.

    Takes the document rather than fetching it, because the same page is
    reached two ways - after a submission and by identity - and both must
    render identically. Fetching here would give the two paths two chances to
    differ.
    """
    context = env.context("web.assessment")
    context["model"] = build_assessment_page(document, locale=env.locale)
    return _render("web.assessment", context, status=status,
                   request_id=env.request_id)


def render_evidence_page(env: PageEnvironment, *,
                         document: Mapping[str, Any]) -> PageResult:
    context = env.context("web.evidence")
    context["model"] = build_evidence_page(document, locale=env.locale)
    return _render("web.evidence", context, status=200,
                   request_id=env.request_id)


def render_system_page(env: PageEnvironment, *,
                       client: PgxApiClient) -> PageResult:
    """Versions and readiness, fetched independently and reported separately.

    Two calls, two ``try`` blocks, two availability flags. Merging them would
    let one failure hide the other's answer - and the answer most worth seeing
    when a release cannot be read is the readiness report that says why.
    """
    version: Optional[Mapping[str, Any]] = None
    readiness: Optional[Mapping[str, Any]] = None
    try:
        version = client.get_system_version(
            request_id=env.request_id).document
    except WebError:
        version = None
    try:
        readiness = client.get_readiness(request_id=env.request_id).document
    except WebError:
        readiness = None

    context = env.context("web.system")
    context["model"] = build_system_page(version, readiness,
                                         locale=env.locale)
    return _render("web.system", context, status=200,
                   request_id=env.request_id)


def render_validation_page(env: PageEnvironment, *,
                           development_case_count: int,
                           blockers: Sequence[Tuple[str, str]] = (),
                           feed: Optional[Mapping[str, Any]] = None
                           ) -> PageResult:
    """Render the validation board from the committed WP-21 public feed.

    ``feed`` is passed in rather than loaded here so this function stays a
    pure rendering step: the caller decides where the feed comes from, and a
    test can hand it a synthetic one without touching the filesystem.
    """
    context = env.context("web.validation")
    context["model"] = build_validation_board(
        development_case_count=development_case_count,
        blockers=blockers, feed=feed, locale=env.locale)
    return _render("web.validation", context, status=200,
                   request_id=env.request_id)
