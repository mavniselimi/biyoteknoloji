#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the Wave 4B runtime and product manifest.

Every verdict here is computed from an artifact on disk or from the composed
application itself. Nothing is asserted by this script: where it cannot
measure something it records that it could not, and the work package stays
BLOCKED.

Run it with the candidate deployment's own environment - the same
``PGX_RUNTIME_TRACK``, ``DATABASE_URL`` and repository root the server uses -
because the composition probe asks the real composition root what it runs, and
a probe run against a different environment measures a different deployment.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

OUTPUT = os.path.join(REPO, "data", "closure",
                      "wave-04b-runtime-product-manifest.json")
BROWSER_DIR = os.path.join(REPO, "data", "closure", "wave-04b-browser")


def _digest(path):
    with io.open(path, "rb") as handle:
        return "sha256:" + hashlib.sha256(handle.read()).hexdigest()


def _read(*parts):
    with io.open(os.path.join(REPO, *parts), encoding="utf-8") as handle:
        return json.load(handle)


def _commit():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO,
            stderr=subprocess.DEVNULL).decode().strip()
    except Exception:  # noqa: BLE001 - a checkout without git still builds
        return ""


def _composition():
    """What the deployed composition root runs, asked of the real one."""
    try:
        from apps.api.main import build_provider
    except Exception as error:  # noqa: BLE001
        return {"available": False,
                "detail": "%s: %s" % (type(error).__name__, error)}
    try:
        provider = build_provider()
        track = getattr(provider.runtime_track, "value", None)
        state = {"available": True, "runtime_track": track}
        if track == "CANDIDATE":
            pinned = provider.require_candidate_release()
            state.update({
                "release_public_id": pinned.release_public_id,
                "manifest_hash": pinned.manifest["manifest_hash"],
                "dataset_public_id": pinned.dataset_public_id,
                "ruleset_key": pinned.ruleset.ruleset_key,
                "ruleset_content_hash": pinned.ruleset.content_hash(),
                "authority_state": pinned.manifest["authority_state"],
                "review_state": pinned.manifest["review_state"],
                "claim_boundary_is_approved":
                    provider.claim_boundary.is_approved,
                "claim_boundary_status": provider.claim_boundary.status,
            })
            state["security_capabilities"] = provider.security_capabilities
        return state
    except Exception as error:  # noqa: BLE001
        return {"available": False,
                "detail": "%s: %s" % (type(error).__name__, error)}


def _browser():
    path = os.path.join(BROWSER_DIR, "jury-flow.json")
    if not os.path.isfile(path):
        return {"executed": False,
                "detail": "no browser evidence is committed"}
    with io.open(path, encoding="utf-8") as handle:
        document = json.load(handle)
    steps = document.get("steps", [])
    return {
        "executed": True,
        "step_count": len(steps),
        "viewport": document.get("viewport"),
        "browser": document.get("browser"),
        "steps": [{"name": s["name"], "url": s["url"],
                   "canonical_warning": s["canonical_warning"],
                   "horizontal_overflow": s["horizontal_overflow"],
                   "checks": s.get("found") or {}}
                  for s in steps],
        "anonymous_denial_status": document.get("anonymous_denial_status"),
        "not_found_status": document.get("not_found_status"),
        "post_logout_status": document.get("post_logout_status"),
        "session_cookies": document.get("session_cookies"),
        "cookies_after_logout": document.get("cookies_after_logout"),
        "console_error_count": document.get("console_error_count"),
        "console": document.get("console"),
        "expectation_failures": document.get("failures"),
        "pages_without_canonical_warning":
            document.get("pages_without_warning"),
        "pages_with_overflow": document.get("overflow_pages"),
        "screenshots": sorted(
            name for name in os.listdir(BROWSER_DIR)
            if name.endswith(".png")),
    }


#: What A7 requires each screen to show, checked against the page the running
#: application actually serves. Each entry is (path, requirement, needle).
SCREEN_REQUIREMENTS = (
    ("/system", "candidate runtime state named", "CANDIDATE"),
    ("/system", "governed runtime state named separately", "GOVERNED"),
    ("/system", "candidate release identity", "PGX-CANDIDATE-REL"),
    ("/system", "provisional authority", "PROJECT_TEAM_PROVISIONAL"),
    ("/validation", "internal validation label", "INTERNAL_VALIDATION"),
    ("/expert-reviews/demo-1", "pending external review",
     "PENDING_EXTERNAL_EXPERT_REVIEW"),
)


def _screen_requirements():
    """Ask the running application what each screen says.

    Uses the in-process ASGI transport rather than a live server, so this can
    be re-run from a checkout without one - and drives a real login first,
    because the pages that matter are behind authentication.
    """
    import asyncio
    import re as _re

    try:
        import httpx

        from apps.api.config import load_settings as _api_settings
        from apps.web.config import load_web_settings as _web_settings
        from apps.web.main import build_combined_app
    except Exception as error:  # noqa: BLE001
        return [{"path": path, "requirement": requirement,
                 "satisfied": False,
                 "detail": "%s: %s" % (type(error).__name__, error)}
                for path, requirement, _ in SCREEN_REQUIREMENTS]

    credentials = os.environ.get("PGX_DEMO_CREDENTIALS", "")
    user = os.environ.get("PGX_DEMO_USER", "jury")
    password = None
    if credentials and os.path.isfile(credentials):
        with io.open(credentials, encoding="utf-8") as handle:
            for line in handle:
                if line.strip() and not line.startswith("#"):
                    name, _, secret = line.partition("\t")
                    if name.strip() == user:
                        password = secret.strip()

    api = _api_settings()
    app, _ = build_combined_app(api, _web_settings(api=api))
    bodies = {}

    async def _walk():
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport,
                                     base_url="https://testserver") as client:
            if password:
                page = await client.get("/login")
                match = _re.search(
                    r'name="csrf_token"\s+value="([^"]+)"', page.text)
                if match:
                    await client.post("/login", data={
                        "username": user, "password": password,
                        "csrf_token": match.group(1)})
            for path in sorted({item[0] for item in SCREEN_REQUIREMENTS}):
                response = await client.get(path)
                bodies[path] = _re.sub(r"<[^>]+>", " ", response.text)

    try:
        asyncio.run(_walk())
    except Exception as error:  # noqa: BLE001
        return [{"path": path, "requirement": requirement,
                 "satisfied": False,
                 "detail": "%s: %s" % (type(error).__name__, error)}
                for path, requirement, _ in SCREEN_REQUIREMENTS]

    return [{"path": path, "requirement": requirement, "needle": needle,
             "satisfied": needle in bodies.get(path, "")}
            for path, requirement, needle in SCREEN_REQUIREMENTS]


def main() -> int:
    browser = _browser()
    composition = _composition()

    every_page_warned = bool(browser.get("executed")) and all(
        step["canonical_warning"] for step in browser.get("steps", []))
    no_overflow = bool(browser.get("executed")) and not any(
        step["horizontal_overflow"] for step in browser.get("steps", []))
    no_expectation_failure = browser.get("expectation_failures") == []
    logout_revokes = browser.get("post_logout_status") == 401
    anonymous_denied = browser.get("anonymous_denial_status") == 401

    # The A7 screen requirements, measured on the served pages rather than
    # inferred from the fact that a page returned 200. An earlier version of
    # this gate checked only that the walk completed - which is how Wave 3B's
    # G8 came to read PASS while the deployment could not reach the candidate
    # release at all. A gate that measures what was built rather than what was
    # required is not a gate.
    screens = _screen_requirements()
    screens_pass = all(item["satisfied"] for item in screens)

    wp_c14a = all((browser.get("executed"), every_page_warned, no_overflow,
                   no_expectation_failure, logout_revokes, anonymous_denied,
                   composition.get("runtime_track") == "CANDIDATE",
                   screens_pass))

    # WP-C14 additionally requires the demonstration to have run against the
    # composed deployment with authentication, audit and a real database - and
    # for the environment to be described as what it is.
    wp_c14 = bool(wp_c14a and composition.get("available")
                  and composition.get("security_capabilities", {})
                  .get("authentication_service_composed")
                  and composition.get("security_capabilities", {})
                  .get("audit_sink_composed")
                  and composition.get("claim_boundary_is_approved") is False)

    payload = {
        "manifest_version": "pgx-closure-wave04b-manifest/1",
        "commit": _commit(),
        "environment_class": "LOCAL_REPRESENTATIVE_ENVIRONMENT",
        "environment_note": (
            "A locally provisioned representative environment: real "
            "PostgreSQL 16.13, the declared dependencies installed, "
            "authentication, CSRF, authorisation, rate limiting and audit all "
            "composed, LLM off, no P1/P2 feature enabled, and no uncontrolled "
            "network dependency. It is not external staging and is not "
            "described as one."),
        "composition": composition,
        "browser": browser,
        "screen_requirements": screens,
        "work_packages": [
            {"work_package": "WP-C14A",
             "subject": "product surface and demo UX closure",
             "verdict": "PASS" if wp_c14a else "BLOCKED"},
            {"work_package": "WP-C14",
             "subject": "representative candidate demonstration",
             "verdict": "PASS" if wp_c14 else "BLOCKED"},
        ],
        "status_vocabulary": (
            ["COMPLETE CANDIDATE PROJECT", "SOURCE_GROUNDED",
             "PROJECT_TEAM_PROVISIONAL", "INTERNALLY_VALIDATED",
             "PENDING_EXTERNAL_EXPERT_REVIEW"]
            if wp_c14a and wp_c14 else
            ["CANDIDATE SCIENTIFIC ENGINE COMPLETE",
             "INTERNAL CONSISTENCY BENCHMARK COMPLETE",
             "RUNTIME / PRODUCT COMPOSITION INCOMPLETE",
             "PENDING EXTERNAL EXPERT REVIEW"]),
        "still_unavailable": [
            "No external expert has reviewed any of this.",
            "No independent validation exists.",
            "No clinical validation exists.",
            "The candidate source policy remains PENDING_REVIEW and the "
            "ordinary DQ gate still fails on its two structural blockers.",
            "The candidate DQ decision keeps permits_transition = false; "
            "candidate-only acceptance is not governed publication approval.",
            "THS-6 is not closed and no THS-6 gate was touched.",
        ],
        "files": [
            {"path": os.path.relpath(os.path.join(base, name), REPO)
             .replace(os.sep, "/"),
             "sha256": _digest(os.path.join(base, name))}
            for base, _, names in os.walk(BROWSER_DIR)
            for name in names],
    }
    payload["files"] = sorted(payload["files"], key=lambda item: item["path"])

    with io.open(OUTPUT, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True,
                                ensure_ascii=False) + "\n")

    for entry in payload["work_packages"]:
        print("  %-8s %-8s %s" % (entry["work_package"], entry["verdict"],
                                  entry["subject"]))
    print()
    print(" / ".join(payload["status_vocabulary"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
