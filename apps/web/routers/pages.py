"""The eleven page routes.

Each is registered from :mod:`apps.web.routes`: the path, the operation name,
the access policy and the parameter constraints all come from the table, so a
router cannot introduce a page the table does not describe or widen the roles
that reach one.
"""

from __future__ import annotations

from typing import Any, List, Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse

from apps.api.dependencies import require_access
from apps.web.dependencies import WebProvider
from apps.web.errors import WebError
from apps.web.pages import (PageEnvironment, PageResult, render_assessment_page,
                            render_case_detail_page, render_cases_page,
                            render_error_page, render_evidence_page,
                            render_expert_review_page, render_home_page,
                            render_login_page, render_system_page,
                            render_validation_page)
from apps.web.routes import web_route
from apps.web.security import CsrfError
from pgx.application.execution_context import (ExecutionChannel,
                                               ExecutionContext)

router = APIRouter(include_in_schema=False)

_HOME = web_route("web.home")
_LOGIN = web_route("web.login")
_LOGIN_SUBMIT = web_route("web.login_submit")
_LOGOUT = web_route("web.logout")
_CASES = web_route("web.cases")
_CASE = web_route("web.case_detail")
_ASSESS = web_route("web.case_assess")
_ASSESSMENT = web_route("web.assessment")
_EVIDENCE = web_route("web.evidence")
_VALIDATION = web_route("web.validation")
_EXPERT = web_route("web.expert_review")
_EXPERT_EXPECTED = web_route("web.expert_review_expected")
_EXPERT_REVEAL = web_route("web.expert_review_reveal")
_EXPERT_COMPLETE = web_route("web.expert_review_complete")
_SYSTEM = web_route("web.system")


def get_web_provider(request: Request) -> WebProvider:
    """The provider this application was composed with. The one test seam."""
    provider = getattr(request.app.state, "web_provider", None)
    if provider is None:  # pragma: no cover - create_web_app always sets it
        raise WebError("SERVICE_NOT_READY")
    return provider


def _environment(request: Request, provider: WebProvider) -> PageEnvironment:
    from apps.web.pages import PageEnvironment as _Env

    return _Env(
        locale=provider.settings.locale,
        environment=provider.settings.environment.value,
        request_id=getattr(request.state, "request_id", "") or "",
        asset_version=provider.settings.static_asset_version,
        dependency_notice=None)


def _respond(result: PageResult) -> HTMLResponse:
    return HTMLResponse(content=result.html, status_code=result.status,
                        headers=result.headers)


def _failure(request: Request, provider: WebProvider, error: WebError, *,
             route_name: str) -> HTMLResponse:
    return _respond(render_error_page(_environment(request, provider),
                                      code=error.code, route_name=route_name))


@router.get(_HOME.path, name=_HOME.name, response_class=HTMLResponse)
async def home(request: Request,
               principal: Any = Depends(require_access(_HOME.access,
                                                       _HOME.name)),
               provider: WebProvider = Depends(get_web_provider)
               ) -> HTMLResponse:
    return _respond(render_home_page(_environment(request, provider)))


def _session_token(request: Request) -> Optional[str]:
    """The presented session cookie, or ``None``.

    Read from the cookie and from nowhere else. There is deliberately no
    fallback to a header or a form field: a session that could arrive in a
    request body would be a session a cross-site form could set.
    """
    from pgx.security.vocabulary import SESSION_COOKIE_NAME

    return request.cookies.get(SESSION_COOKIE_NAME)


def _preauth_material(request: Request, provider: WebProvider):
    """``(binding, secret)`` for the login form's CSRF token, or ``None``.

    Bound to a short-lived host-scoped cookie the server set when it rendered
    the form. Login is not exempt from CSRF: an attacker who can post to
    ``/login`` with their own credentials logs the victim into the attacker's
    account, and everything the victim then does happens in a session the
    attacker controls and can read.
    """
    from pgx.security.vocabulary import PREAUTH_COOKIE_NAME

    value = request.cookies.get(PREAUTH_COOKIE_NAME)
    if not value:
        return None
    return (PREAUTH_COOKIE_NAME, value)


def _login_response(request: Request, provider: WebProvider, *,
                    failed: bool = False, rate_limited: bool = False,
                    session=None, set_cookie: Optional[str] = None,
                    preauth: Optional[str] = None) -> HTMLResponse:
    """Render the login page in whichever of its three states applies.

    ``Cache-Control: no-store`` is already on every page through
    :data:`~apps.web.security.SECURITY_HEADERS`, which is why it is not set
    again here - a second header would be a second thing to keep in step.
    """
    import secrets

    from apps.web.security import session_cookie_header
    from pgx.security.vocabulary import PREAUTH_COOKIE_NAME

    settings = provider.settings
    verifier = provider.csrf_for(session.session if session else None)
    token = verifier.issue() if verifier.configured else None
    actor = session.actor if session else None
    role = session.role if session else None

    issued_preauth = None
    if session is None and provider.csrf_factory is not None:
        # A fresh pre-auth secret per rendering of the form. Short-lived and
        # single-purpose: it authorises one login attempt and authenticates
        # nobody.
        issued_preauth = preauth or secrets.token_urlsafe(32)
        token = provider.csrf_factory(
            PREAUTH_COOKIE_NAME, issued_preauth).issue()

    result = render_login_page(
        _environment(request, provider),
        authentication_configured=settings.api.authentication_configured,
        form_enabled=bool(token) and session is None,
        csrf_token=token, failed=failed, rate_limited=rate_limited,
        actor=actor, role=role)
    response = _respond(result)
    if set_cookie is not None:
        response.headers.append("set-cookie", set_cookie)
    if issued_preauth is not None:
        response.headers.append(
            "set-cookie",
            session_cookie_header(PREAUTH_COOKIE_NAME, issued_preauth,
                                  max_age=600))
    return response


@router.get(_LOGIN.path, name=_LOGIN.name, response_class=HTMLResponse)
async def login(request: Request,
                principal: Any = Depends(require_access(_LOGIN.access,
                                                        _LOGIN.name)),
                provider: WebProvider = Depends(get_web_provider)
                ) -> HTMLResponse:
    """The form, or the signed-in identity. Never a signup link."""
    session = provider.authenticate(_session_token(request))
    return _login_response(request, provider, session=session)


@router.post(_LOGIN_SUBMIT.path, name=_LOGIN_SUBMIT.name,
             response_class=HTMLResponse)
async def login_submit(request: Request,
                       username: str = Form(default=""),
                       password: str = Form(default=""),
                       csrf_token: Optional[str] = Form(default=None),
                       principal: Any = Depends(
                           require_access(_LOGIN_SUBMIT.access,
                                          _LOGIN_SUBMIT.name)),
                       provider: WebProvider = Depends(get_web_provider)
                       ) -> HTMLResponse:
    """Authenticate, or refuse identically whatever went wrong.

    The order is the security content: CSRF first, then the service. A CSRF
    failure is refused before the username and password are read at all, so a
    forged cross-site post never reaches the rate limiter or the store.
    """
    from apps.web.security import session_cookie_header
    from pgx.security.errors import (AuthenticationFailed,
                                     PasswordPolicyError, RateLimited)
    from pgx.security.passwords import Password
    from pgx.security.vocabulary import (PREAUTH_COOKIE_NAME,
                                         SESSION_COOKIE_NAME)

    material = _preauth_material(request, provider)
    if material is None or provider.csrf_factory is None:
        return _login_response(request, provider, failed=False)
    binding, secret = material
    try:
        provider.csrf_factory(binding, secret).verify(csrf_token)
    except CsrfError:
        return _failure(request, provider, WebError("FORBIDDEN_ROLE"),
                        route_name=_LOGIN.name)

    if provider.authentication_service is None:
        return _login_response(request, provider)

    try:
        outcome = provider.authentication_service().login(
            username, Password(password),
            origin_key=(request.client.host if request.client else "unknown"),
            request_id=getattr(request.state, "request_id", None) or None)
    except RateLimited:
        return _login_response(request, provider, rate_limited=True)
    except (AuthenticationFailed, PasswordPolicyError):
        # One answer for every cause. A password that violated a bound and a
        # password that was simply wrong are the same refusal, because the
        # difference would tell a caller the policy without an account.
        return _login_response(request, provider, failed=True)
    except Exception:  # noqa: BLE001 - an unavailable store is not a hint
        return _login_response(request, provider, failed=True)

    # The raw token exists here and in the header below, and nowhere else. It
    # is not stored, not logged and not audited.
    cookie = session_cookie_header(SESSION_COOKIE_NAME, outcome.raw_token)
    session = provider.authenticate(outcome.raw_token)
    response = _login_response(request, provider, session=session,
                               set_cookie=cookie)
    # The pre-auth cookie has done its one job.
    response.headers.append(
        "set-cookie",
        session_cookie_header(PREAUTH_COOKIE_NAME, "", max_age=0))
    return response


@router.post(_LOGOUT.path, name=_LOGOUT.name, response_class=HTMLResponse)
async def logout(request: Request,
                 csrf_token: Optional[str] = Form(default=None),
                 principal: Any = Depends(require_access(_LOGOUT.access,
                                                         _LOGOUT.name)),
                 provider: WebProvider = Depends(get_web_provider)
                 ) -> HTMLResponse:
    """Revoke server-side, then clear the cookie. In that order.

    Clearing first would leave a live session the user believes is closed,
    usable by anyone holding a copy of the token - and the user has no way to
    discover it, because their own browser no longer has the cookie.
    """
    from apps.web.security import session_cookie_header
    from pgx.security.vocabulary import SESSION_COOKIE_NAME

    raw_token = _session_token(request)
    session = provider.authenticate(raw_token)
    verifier = provider.csrf_for(session.session if session else None)
    try:
        verifier.verify(csrf_token)
    except CsrfError:
        return _failure(request, provider,
                        WebError("FORBIDDEN_ROLE"), route_name=_LOGIN.name)

    if provider.authentication_service is not None and raw_token:
        try:
            provider.authentication_service().logout(
                raw_token,
                request_id=getattr(request.state, "request_id", None) or None)
        except Exception:  # noqa: BLE001 - the cookie is cleared regardless
            pass
    response = _login_response(request, provider, session=None)
    response.headers.append(
        "set-cookie",
        session_cookie_header(SESSION_COOKIE_NAME, "", max_age=0))
    return response


@router.get(_CASES.path, name=_CASES.name, response_class=HTMLResponse)
async def cases(request: Request,
                principal: Any = Depends(require_access(_CASES.access,
                                                        _CASES.name)),
                provider: WebProvider = Depends(get_web_provider)
                ) -> HTMLResponse:
    entries, available = provider.cases()
    return _respond(render_cases_page(_environment(request, provider),
                                      cases=entries, available=available))


@router.get(_CASE.path, name=_CASE.name, response_class=HTMLResponse)
async def case_detail(request: Request, case_id: str,
                      principal: Any = Depends(require_access(_CASE.access,
                                                              _CASE.name)),
                      provider: WebProvider = Depends(get_web_provider)
                      ) -> HTMLResponse:
    case = provider.case(case_id)
    if case is None:
        return _failure(request, provider, WebError("RESOURCE_NOT_FOUND"),
                        route_name=_CASES.name)
    return _respond(render_case_detail_page(
        _environment(request, provider), case=case, client=provider.client,
        submit_available=provider.forms_available,
        csrf_token=provider.csrf.issue()))


@router.post(_ASSESS.path, name=_ASSESS.name, response_class=HTMLResponse)
async def submit_assessment(
        request: Request, case_id: str,
        csrf_token: Optional[str] = Form(default=None),
        medications: Optional[List[str]] = Form(default=None),
        principal: Any = Depends(require_access(_ASSESS.access,
                                                _ASSESS.name)),
        provider: WebProvider = Depends(get_web_provider)) -> HTMLResponse:
    try:
        provider.csrf.verify(csrf_token)
    except CsrfError:
        return _failure(request, provider, WebError("FORBIDDEN_ROLE"),
                        route_name=_CASES.name)

    case = provider.case(case_id)
    if case is None:
        return _failure(request, provider, WebError("RESOURCE_NOT_FOUND"),
                        route_name=_CASES.name)

    from apps.web.submission import build_assessment_request

    environment = _environment(request, provider)
    try:
        document = build_assessment_request(
            case, medications=tuple(medications or ()),
            max_medications=provider.settings.max_selected_medications)
        context = ExecutionContext(
            actor=principal.actor, role=principal.role.value,
            channel=ExecutionChannel.API,
            request_id=environment.request_id or None,
            authenticated_by=principal.authenticated_by)
        response = provider.client.create_assessment(document, context=context)
    except WebError as error:
        return _failure(request, provider, error, route_name=_CASES.name)

    return _respond(render_assessment_page(environment,
                                           document=response.document,
                                           status=200))


@router.get(_ASSESSMENT.path, name=_ASSESSMENT.name,
            response_class=HTMLResponse)
async def assessment(request: Request, assessment_id: str,
                     principal: Any = Depends(
                         require_access(_ASSESSMENT.access,
                                        _ASSESSMENT.name)),
                     provider: WebProvider = Depends(get_web_provider)
                     ) -> HTMLResponse:
    environment = _environment(request, provider)
    try:
        response = provider.client.get_assessment(
            assessment_id, request_id=environment.request_id)
    except WebError as error:
        return _failure(request, provider, error, route_name=_CASES.name)
    return _respond(render_assessment_page(environment,
                                           document=response.document))


@router.get(_EVIDENCE.path, name=_EVIDENCE.name, response_class=HTMLResponse)
async def evidence(request: Request, evidence_id: str,
                   principal: Any = Depends(require_access(_EVIDENCE.access,
                                                           _EVIDENCE.name)),
                   provider: WebProvider = Depends(get_web_provider)
                   ) -> HTMLResponse:
    environment = _environment(request, provider)
    try:
        response = provider.client.get_evidence(
            evidence_id, request_id=environment.request_id)
    except WebError as error:
        return _failure(request, provider, error, route_name=_CASES.name)
    return _respond(render_evidence_page(environment,
                                         document=response.document))


@router.get(_VALIDATION.path, name=_VALIDATION.name,
            response_class=HTMLResponse)
async def validation(request: Request,
                     principal: Any = Depends(
                         require_access(_VALIDATION.access,
                                        _VALIDATION.name)),
                     provider: WebProvider = Depends(get_web_provider)
                     ) -> HTMLResponse:
    from apps.web.gate_status import validation_blockers
    from apps.web.validation_feed import load_dashboard_feed

    entries, _available = provider.cases()
    # The committed public feed, read through the narrow adapter. The handler
    # never touches the benchmark engine, a release resolver or restricted
    # storage, so there is no path from here to a holdout payload.
    return _respond(render_validation_page(
        _environment(request, provider),
        development_case_count=len(entries),
        blockers=validation_blockers(provider.settings.locale),
        feed=load_dashboard_feed()))


def _expert_page(request: Request, provider: WebProvider, *, case_id: str,
                 principal: Any) -> HTMLResponse:
    """One rendering path for the GET and all three POSTs.

    Shared deliberately: four handlers each assembling their own model is
    four chances for one of them to pass a result into a blinded page.
    """
    view, protocol = provider.expert_review(
        case_id=case_id, actor=getattr(principal, "actor", ""),
        role=getattr(getattr(principal, "role", None), "value", ""))
    # Forms are inert unless a CSRF verifier is configured *and* a live
    # assignment exists. WP-23 owns the verifier; until then every deployment
    # renders the workflow as an explanation rather than as controls, because
    # a control that cannot submit is worse than none - a reviewer would fill
    # it in and believe it was recorded.
    token = None
    enabled = False
    try:
        token = provider.csrf.issue()
        enabled = view is not None
    except CsrfError:
        token, enabled = None, False
    return _respond(render_expert_review_page(
        _environment(request, provider), case_id=case_id, view=view,
        protocol=protocol, csrf_token=token, forms_enabled=enabled))


@router.get(_EXPERT.path, name=_EXPERT.name, response_class=HTMLResponse)
async def expert_review(request: Request, case_id: str,
                        principal: Any = Depends(
                            require_access(_EXPERT.access, _EXPERT.name)),
                        provider: WebProvider = Depends(get_web_provider)
                        ) -> HTMLResponse:
    return _expert_page(request, provider, case_id=case_id,
                        principal=principal)


async def _expert_post(request: Request, provider: WebProvider, *,
                       case_id: str, principal: Any, csrf_token: Optional[str],
                       operation: str, body: Any) -> HTMLResponse:
    """CSRF first, then the governed operation, then re-render.

    The verification runs before anything is read or written, exactly as it
    would in a deployment that had a real verifier - so these routes cannot
    become a CSRF-exempt habit when WP-23 gives them something to do.
    """
    try:
        provider.csrf.verify(csrf_token)
    except CsrfError:
        return _failure(request, provider, WebError("FORBIDDEN_ROLE"),
                        route_name=_EXPERT.name)
    service = provider.expert_review_service
    if service is not None:
        actor = getattr(principal, "actor", "")
        role = getattr(getattr(principal, "role", None), "value", "")
        try:
            getattr(service, operation)(case_id=case_id, actor=actor,
                                        role=role, body=body)
        except Exception:  # noqa: BLE001 - the re-render reports the state
            pass
    return _expert_page(request, provider, case_id=case_id,
                        principal=principal)


@router.post(_EXPERT_EXPECTED.path, name=_EXPERT_EXPECTED.name,
             response_class=HTMLResponse)
async def expert_review_expected(
        request: Request, case_id: str,
        csrf_token: Optional[str] = Form(default=None),
        expected_attention_level: str = Form(default=""),
        expected_coverage_status: str = Form(default=""),
        expected_coverage_reason: Optional[str] = Form(default=None),
        expected_rule_id: Optional[str] = Form(default=None),
        requires_traceable_evidence: bool = Form(default=True),
        reviewer_note: str = Form(default=""),
        principal: Any = Depends(require_access(_EXPERT_EXPECTED.access,
                                                _EXPERT_EXPECTED.name)),
        provider: WebProvider = Depends(get_web_provider)) -> HTMLResponse:
    # Rationale codes arrive as repeated form values; read from the raw form
    # so a single-valued binding does not silently keep only the last.
    form = await request.form()
    body = {
        "expected_attention_level": expected_attention_level,
        "expected_coverage_status": expected_coverage_status,
        "expected_coverage_reason": expected_coverage_reason or None,
        "expected_rule_id": expected_rule_id or None,
        "requires_traceable_evidence": requires_traceable_evidence,
        "rationale_codes": tuple(form.getlist("rationale_codes")),
        "reviewer_note": reviewer_note,
    }
    return await _expert_post(request, provider, case_id=case_id,
                              principal=principal, csrf_token=csrf_token,
                              operation="record_expectation", body=body)


@router.post(_EXPERT_REVEAL.path, name=_EXPERT_REVEAL.name,
             response_class=HTMLResponse)
async def expert_review_reveal(
        request: Request, case_id: str,
        csrf_token: Optional[str] = Form(default=None),
        principal: Any = Depends(require_access(_EXPERT_REVEAL.access,
                                                _EXPERT_REVEAL.name)),
        provider: WebProvider = Depends(get_web_provider)) -> HTMLResponse:
    return await _expert_post(request, provider, case_id=case_id,
                              principal=principal, csrf_token=csrf_token,
                              operation="reveal", body={})


@router.post(_EXPERT_COMPLETE.path, name=_EXPERT_COMPLETE.name,
             response_class=HTMLResponse)
async def expert_review_complete(
        request: Request, case_id: str,
        csrf_token: Optional[str] = Form(default=None),
        decision: str = Form(default=""),
        reviewer_note: str = Form(default=""),
        principal: Any = Depends(require_access(_EXPERT_COMPLETE.access,
                                                _EXPERT_COMPLETE.name)),
        provider: WebProvider = Depends(get_web_provider)) -> HTMLResponse:
    form = await request.form()
    from pgx.expert_review.vocabulary import LIKERT_DIMENSIONS
    ratings = {}
    for dimension in LIKERT_DIMENSIONS:
        raw = form.get("rating_%s" % dimension)
        if raw not in (None, ""):
            try:
                ratings[dimension] = int(raw)
            except (TypeError, ValueError):
                # An unparseable rating is dropped rather than guessed. The
                # domain would refuse the whole completion for it, and losing
                # a decision to a typo in an optional field is the wrong
                # trade.
                continue
    return await _expert_post(
        request, provider, case_id=case_id, principal=principal,
        csrf_token=csrf_token, operation="complete",
        body={"decision": decision, "ratings": ratings,
              "reviewer_note": reviewer_note})


@router.get(_SYSTEM.path, name=_SYSTEM.name, response_class=HTMLResponse)
async def system(request: Request,
                 principal: Any = Depends(require_access(_SYSTEM.access,
                                                         _SYSTEM.name)),
                 provider: WebProvider = Depends(get_web_provider)
                 ) -> HTMLResponse:
    return _respond(render_system_page(_environment(request, provider),
                                       client=provider.client))
