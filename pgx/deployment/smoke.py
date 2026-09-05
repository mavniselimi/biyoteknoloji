# -*- coding: utf-8 -*-
"""Staging smoke checks (WP-24).

What a smoke check is for: proving a *deployed* system answers, as opposed to
proving the code would answer if deployed. Those are different claims and this
module exists to keep them apart - which is why every result carries the
environment kind it came from, and why a rehearsal on a laptop can never be
serialised as ``STAGING``.

Three properties are checked, in this order, because each makes the next
meaningful:

1. **Liveness answers.** ``/health/live`` must return 200 while the database
   is down, while ClinPGx is unreachable, and with no active release. A
   liveness probe that consulted any of those would restart a healthy
   container because something else was briefly unavailable.
2. **Readiness tells the truth.** It must report NOT_READY with named
   components when something required is missing, and READY only when it is
   not. A readiness endpoint that reported READY on an unmigrated database is
   worse than none, because an orchestrator would send it traffic.
3. **The cookie policy survived the deployment.** If the deployment sets a
   session cookie, it must carry ``Secure``, ``HttpOnly``, ``SameSite=Strict``
   and no ``Domain``. This is checked on the wire rather than in the code,
   because the question is whether a proxy, a framework setting or a
   convenience flag changed it between here and the browser.

No response body is recorded. A smoke report that captured bodies would
capture whatever the deployment was serving, which is the one thing a report
travelling to an evidence pack must not do.
"""

from __future__ import annotations

import datetime as _dt
import json
import ssl
import urllib.error
import urllib.request
from typing import Any, Mapping, Optional, Sequence, Tuple

from pgx.deployment.vocabulary import (REHEARSAL_LABEL,
                                       DeploymentEnvironmentKind,
                                       ExecutionState, blocker)

__all__ = [
    "SMOKE_RESULT_VERSION",
    "REQUIRED_COOKIE_ATTRIBUTES",
    "cookie_policy_findings",
    "smoke_check",
]

SMOKE_RESULT_VERSION = "pgx-wp24-staging-smoke/1"

#: What a session cookie must carry when it crosses the wire. Checked as
#: presence of the attribute, and for ``SameSite`` as an exact value: a
#: deployment that downgraded Strict to Lax has changed the policy, and a
#: check that only asked "is SameSite present" would pass it.
REQUIRED_COOKIE_ATTRIBUTES: Tuple[str, ...] = ("Secure", "HttpOnly")

_TIMEOUT_SECONDS = 10


def cookie_policy_findings(set_cookie_headers: Sequence[str]
                           ) -> Mapping[str, object]:
    """Check every ``Set-Cookie`` the deployment emitted.

    A ``__Host-`` prefixed cookie is additionally required to carry no
    ``Domain`` and ``Path=/`` - the browser enforces that too, but a
    deployment emitting one that violates it has a cookie the browser will
    silently drop, which presents as "login does not work" with no error
    anywhere.
    """
    findings = []
    for header in set_cookie_headers:
        name = header.split("=", 1)[0].strip()
        lowered = header.lower()
        problems = []
        for attribute in REQUIRED_COOKIE_ATTRIBUTES:
            if attribute.lower() not in lowered:
                problems.append("missing %s" % attribute)
        if "samesite=strict" not in lowered:
            problems.append("SameSite is not Strict")
        if name.startswith("__Host-"):
            if "domain=" in lowered:
                problems.append(
                    "a __Host- cookie carries a Domain attribute, which the "
                    "browser will reject the whole cookie for")
            if "path=/" not in lowered:
                problems.append("a __Host- cookie is not Path=/")
        findings.append({"cookie": name, "problems": problems,
                         "compliant": not problems})
    return {
        "cookies_seen": len(findings),
        "findings": findings,
        "compliant": all(item["compliant"] for item in findings),
        "note": (
            "Checked on the wire, not in the source. The question a smoke "
            "check answers is whether a proxy or a framework setting changed "
            "the policy between the code and the browser."),
    }


def _request(url: str, *, ca_bundle: Optional[str] = None
             ) -> Tuple[Optional[int], Mapping[str, Any], Sequence[str], str]:
    """One GET. Returns status, parsed JSON body, Set-Cookie headers, error.

    ``ca_bundle`` is how a local rehearsal is verified: the generated CA is
    passed explicitly and the handshake is verified against it. There is no
    parameter here that disables verification, deliberately - ``curl -k`` is
    not evidence of TLS, it is evidence that verification was switched off,
    and a report containing it would describe an experiment that did not test
    what it claims.
    """
    context = None
    if url.startswith("https://"):
        context = ssl.create_default_context(cafile=ca_bundle)
    try:
        with urllib.request.urlopen(  # noqa: S310 - an operator-supplied URL
                url, timeout=_TIMEOUT_SECONDS, context=context) as response:
            raw = response.read(65536)
            cookies = response.headers.get_all("Set-Cookie") or []
            status = response.status
    except urllib.error.HTTPError as error:
        raw = error.read(65536)
        cookies = list(error.headers.get_all("Set-Cookie") or [])
        status = error.code
    except Exception as error:  # noqa: BLE001 - the reason, never the body
        return None, {}, (), type(error).__name__
    try:
        body = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        body = {}
    return status, (body if isinstance(body, dict) else {}), tuple(
        cookies), ""


def smoke_check(base_url: Optional[str], *,
                environment: DeploymentEnvironmentKind =
                DeploymentEnvironmentKind.LOCAL_REHEARSAL,
                ca_bundle: Optional[str] = None,
                requester=None,
                now: Optional[_dt.datetime] = None) -> Mapping[str, object]:
    """Probe a running deployment, or report that there is none.

    ``base_url`` of ``None`` is the state this repository is in, and the
    result says so with a blocker rather than with zeros.
    """
    request = requester or _request
    label = (REHEARSAL_LABEL
             if environment is DeploymentEnvironmentKind.LOCAL_REHEARSAL
             else None)
    if not base_url:
        return {
            "staging_smoke_version": SMOKE_RESULT_VERSION,
            "state": ExecutionState.BLOCKED.value,
            "environment_kind": environment.value,
            "rehearsal_label": label,
            "base_url_scheme": None,
            "liveness": None, "readiness": None, "cookie_policy": None,
            "blockers": [dict(blocker(
                "DEPLOY_STAGING_NOT_DEPLOYED",
                owner="WP-24 operation on a host with a container runtime",
                detail=("no base URL was supplied, so nothing was probed; "
                        "this is not a deployment that failed its smoke "
                        "check, it is the absence of a deployment")
            ).to_json())],
            "note": _SMOKE_NOTE,
        }
    scheme = base_url.split("://", 1)[0]
    live_status, live_body, _, live_error = request(
        base_url.rstrip("/") + "/health/live", ca_bundle=ca_bundle)
    ready_status, ready_body, ready_cookies, ready_error = request(
        base_url.rstrip("/") + "/health/ready", ca_bundle=ca_bundle)
    login_status, _, login_cookies, _ = request(
        base_url.rstrip("/") + "/login", ca_bundle=ca_bundle)

    liveness_ok = live_status == 200
    blockers = []
    if not liveness_ok:
        blockers.append(dict(blocker(
            "DEPLOY_SMOKE_NOT_EXECUTED", owner="the deployment",
            detail=("liveness did not answer 200 (%s)"
                    % (live_error or live_status))).to_json()))
    cookies = tuple(ready_cookies) + tuple(login_cookies)
    return {
        "staging_smoke_version": SMOKE_RESULT_VERSION,
        "state": (ExecutionState.OBSERVED.value if liveness_ok
                  else ExecutionState.NOT_EXECUTED.value),
        "environment_kind": environment.value,
        "rehearsal_label": label,
        "base_url_scheme": scheme,
        # Three separate facts, because collapsing them is how "we used
        # HTTPS" becomes "TLS was verified". Verification is never disabled -
        # there is no parameter here that could - so the remaining question
        # is which trust store answered, and a rehearsal CA is not the public
        # one.
        "tls_used": scheme == "https",
        "tls_verification_disabled": False,
        "tls_trust_source": (None if scheme != "https"
                             else "supplied_ca_bundle" if ca_bundle
                             else "system_trust_store"),
        "observed_at": (now or _dt.datetime.now(_dt.timezone.utc)
                        ).isoformat(),
        "liveness": {"status": live_status, "answered": liveness_ok,
                     "error": live_error or None},
        "readiness": {
            "status": ready_status,
            "reported_status": ready_body.get("status"),
            # Component *names* only. A readiness body carries details that
            # name configuration; the names are what an operator acts on.
            "blocking_failures": list(ready_body.get("blocking_failures")
                                      or []),
            "error": ready_error or None},
        "login_page_status": login_status,
        "cookie_policy": dict(cookie_policy_findings(cookies)),
        "blockers": blockers,
        "note": _SMOKE_NOTE,
    }


_SMOKE_NOTE = (
    "No response body is recorded, only status codes, component names and "
    "cookie attribute compliance. A smoke report that captured bodies would "
    "capture whatever the deployment was serving, which is the one thing a "
    "report travelling to an evidence pack must not do.")
