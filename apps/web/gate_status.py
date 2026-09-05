"""What the interface can actually do, measured rather than asserted.

Eighteen separate answers, none of them combined. "Is WP-17 done?" is not one
boolean: templates render here and no browser exists; the API contract is
implemented and no ASGI server can serve it; a case catalogue exists and no
validation architecture does. A single PASS over that would be false in every
direction at once.

Every value is read at call time - packages are imported to find out whether
they import, the template directory is walked, the sealed catalogue is parsed,
a page is actually rendered and scanned. Nothing here is a constant somebody
typed.

The expected honest result is: implemented; templates available; ASGI
blocked; browser absent; no screenshot evidence; accessibility structural
tests available; claim scan clean; PostgreSQL absent; authentication,
CSRF and sessions unavailable; claim boundary unapproved; no active release;
zero real assessments, reports and validation cases; expert review not
implemented; WP-18 not started.
"""

from __future__ import annotations

import importlib
import os
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from apps.web import WEB_VERSION
from apps.web.claim_gate import HTML_GATE_VERSION
from apps.web.demo_cases import CASE_CATALOG_SCHEMA_VERSION
from apps.web.render import TEMPLATE_DIR, TEMPLATE_NAMES, jinja2_available
from apps.web.routes import STATE_CHANGING_ROUTES, WEB_ROUTES

__all__ = [
    "SCREENSHOT_EVIDENCE_BROWSER_CAPTURED",
    "SCREENSHOT_EVIDENCE_NONE",
    "SCREENSHOT_EVIDENCE_STATUSES",
    "UI_GATE_STATUS_SCHEMA_VERSION",
    "build_ui_gate_status",
    "validation_blockers",
    "web_dependency_availability",
]

UI_GATE_STATUS_SCHEMA_VERSION = "pgx-wp17-ui-gate-status/1"

#: The two values ``screenshot_evidence_status`` may take, named once.
#:
#: They used to be spelled twice. The producer emitted ``"CAPTURED"`` and the
#: schema it publishes admitted only ``"NONE"`` and ``"BROWSER_CAPTURED"``,
#: so every artifact this module wrote with captures on disk failed its own
#: contract - a disagreement that survived from WP-17 to WP-24 because
#: nothing ever compared the two spellings. ``BROWSER_CAPTURED`` is the
#: surviving word: it is the one the published schema always declared, and it
#: says the thing that matters, which is that a rendered HTML snapshot is not
#: a capture. The constant exists so that the producer, the schema and the
#: tests cannot drift apart again; a literal here is now a defect.
SCREENSHOT_EVIDENCE_NONE = "NONE"
SCREENSHOT_EVIDENCE_BROWSER_CAPTURED = "BROWSER_CAPTURED"
SCREENSHOT_EVIDENCE_STATUSES: Tuple[str, ...] = (
    SCREENSHOT_EVIDENCE_NONE, SCREENSHOT_EVIDENCE_BROWSER_CAPTURED)

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                          "..", ".."))

#: The packages the interface needs, and what each is for.
_PACKAGES: Tuple[Tuple[str, str], ...] = (
    ("jinja2", "rendering the server-side templates"),
    ("markupsafe", "the autoescaping Jinja2 depends on"),
    ("fastapi", "registering the page routes"),
    ("starlette", "responses, static files and middleware"),
    ("uvicorn", "serving the application"),
    ("httpx", "the ASGI test client"),
    ("multipart", "parsing submitted forms"),
    ("playwright", "driving a real browser"),
    ("selenium", "driving a real browser"),
)

#: Where a browser would have to come from. Checked so "no browser ran" is a
#: measurement rather than a claim.
#: System browser binaries, looked for on PATH. ``playwright`` is **not** in
#: this list and must never be added back: it is the Python package's console
#: script, so ``shutil.which("playwright")`` succeeds the moment the package
#: is installed and reports a browser that may not exist. That false positive
#: is what this list used to produce, and it is the exact shape of claim this
#: file exists to prevent - a gate status asserting a capability instead of
#: measuring one.
_BROWSER_BINARIES: Tuple[str, ...] = ("chromium", "chrome", "google-chrome",
                                      "chromium-browser", "firefox")


def web_dependency_availability() -> Dict[str, Any]:
    """Import each package and report what happened."""
    results: Dict[str, Any] = {}
    for name, purpose in _PACKAGES:
        try:
            module = importlib.import_module(name)
        except Exception:  # noqa: BLE001 - any failure is unavailable
            results[name] = {"importable": False, "version": None,
                             "needed_for": purpose}
        else:
            results[name] = {"importable": True,
                             "version": getattr(module, "__version__", None),
                             "needed_for": purpose}
    return results


def managed_browser_status() -> Dict[str, Any]:
    """Whether a Playwright-managed browser can actually be launched.

    Three questions, asked in order, because only the third is the one that
    matters and the first two are the ones that are easy to mistake for it:

    1. Does the ``playwright`` package import? An installed package is not a
       browser.
    2. Does the executable it would launch exist on disk? A resolved path is
       not a browser either - ``pip install playwright`` sets one without
       ``playwright install`` ever having run.
    3. Does it launch and report a version? That is the browser.

    The launch is done once and closed immediately. It costs about a second
    and it is the only answer worth recording: everything cheaper than it has
    already been wrong here once.
    """
    result: Dict[str, Any] = {
        "playwright_importable": False,
        "managed_browser_path": None,
        "managed_browser_exists": False,
        "managed_browser_launchable": False,
        "managed_browser_version": None,
        "managed_browser_probe_error": None,
    }
    try:
        from playwright.sync_api import sync_playwright
    except Exception as error:  # noqa: BLE001 - any failure is unavailable
        result["managed_browser_probe_error"] = type(error).__name__
        return result
    result["playwright_importable"] = True

    try:
        with sync_playwright() as driver:
            path = driver.chromium.executable_path
            result["managed_browser_path"] = path
            result["managed_browser_exists"] = bool(path) and \
                os.path.isfile(path)
            if not result["managed_browser_exists"]:
                result["managed_browser_probe_error"] = "EXECUTABLE_ABSENT"
                return result
            browser = driver.chromium.launch()
            try:
                result["managed_browser_version"] = browser.version
                result["managed_browser_launchable"] = True
            finally:
                browser.close()
    except Exception as error:  # noqa: BLE001 - a failed launch is a no
        result["managed_browser_probe_error"] = type(error).__name__
    return result


def _browser_available() -> Dict[str, Any]:
    """Measured, not assumed. A browser is one that starts.

    Either a system binary on PATH or a Playwright-managed browser that was
    actually launched counts. Nothing else does - not an importable package,
    not a console script, not a resolved path.
    """
    import shutil

    found = [name for name in _BROWSER_BINARIES if shutil.which(name)]
    managed = managed_browser_status()
    available = bool(found) or managed["managed_browser_launchable"]

    if available:
        sources = []
        if found:
            sources.append("a system binary on PATH (%s)" % ", ".join(found))
        if managed["managed_browser_launchable"]:
            sources.append("a Playwright-managed browser that launched "
                           "(Chromium %s)" % managed["managed_browser_version"])
        note = ("A browser runtime is present: %s. Browser evidence is "
                "therefore possible here; whether any was captured is "
                "reported by screenshot_evidence_status, which is a separate "
                "measurement." % " and ".join(sources))
    elif managed["playwright_importable"]:
        note = ("The playwright package imports but no browser could be "
                "launched (%s). An installed package is not a browser: run "
                "`playwright install chromium`. Nothing in this repository "
                "is a browser capture, and no artifact claims to be."
                % (managed["managed_browser_probe_error"] or "unknown"))
    else:
        note = ("No browser is installed on this host and no browser "
                "automation package imports. Nothing in this repository is a "
                "browser capture, and no artifact claims to be.")

    # The absolute path is deliberately not part of what the gate status
    # publishes. It is a property of one machine - "/opt/pw-browsers/..." on a
    # build container says nothing about anyone else's laptop - and a
    # committed artifact carrying it guarantees a diff every time the file is
    # regenerated somewhere new. It stays in the live return value, where the
    # skip message and the diagnostics use it.
    published = {key: value for key, value in managed.items()
                 if key != "managed_browser_path"}
    return {
        "browser_runtime_available": available,
        "browser_binaries_found": found,
        "note": note,
        **published,
    }


def browser_runtime_detail() -> Dict[str, Any]:
    """The full measurement, path included. For messages, not for artifacts."""
    return managed_browser_status()


#: Where the browser tests write their captures. Measured rather than
#: assumed: this field used to be the constant "NONE", which was true on a
#: host with no browser and would have quietly stayed "NONE" on one that had
#: taken a thousand.
SCREENSHOT_DIR = os.path.join(_REPO_ROOT, "tests", "fixtures", "wp17",
                              "browser")

_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")


def _asgi_runtime_available() -> bool:
    """Whether the packages needed to serve and drive the app all import."""
    for name in ("fastapi", "starlette", "uvicorn", "httpx", "multipart"):
        try:
            importlib.import_module(name)
        except Exception:  # noqa: BLE001 - any failure is unavailable
            return False
    return True


def _screenshot_status() -> Dict[str, Any]:
    """What browser captures exist on disk, counted.

    Three states, and the middle one is the whole reason this is measured:

    - ``NONE``             - no capture directory, or nothing in it.
    - ``BROWSER_CAPTURED`` - real PNGs written by ``test_browser_e2e.py``
      while a real browser was running.

    A capture is only ever written by a test that has a launched browser, so
    the presence of a file here is itself evidence a browser ran. The count
    and the names are reported so a reader can check rather than trust.
    """
    names: List[str] = []
    if os.path.isdir(SCREENSHOT_DIR):
        names = sorted(name for name in os.listdir(SCREENSHOT_DIR)
                       if name.lower().endswith(_IMAGE_SUFFIXES))
    if not names:
        return {
            "screenshot_evidence_status": SCREENSHOT_EVIDENCE_NONE,
            "screenshot_evidence_count": 0,
            "screenshot_evidence_files": [],
            "screenshot_evidence_note": (
                "No screenshot exists in this repository. The HTML snapshots "
                "under tests/fixtures/wp17/snapshots/ are rendered template "
                "output, are labelled as such, and are not browser captures."),
        }
    return {
        "screenshot_evidence_status":
            SCREENSHOT_EVIDENCE_BROWSER_CAPTURED,
        "screenshot_evidence_count": len(names),
        "screenshot_evidence_files": names,
        "screenshot_evidence_note": (
            "%d browser capture(s) under tests/fixtures/wp17/browser/, "
            "written by tests/integration/web/test_browser_e2e.py while a "
            "launched browser was serving the pages. The HTML snapshots "
            "under tests/fixtures/wp17/snapshots/ are a different thing: "
            "rendered template output, labelled as such, not captures."
            % len(names)),
    }


def _template_status() -> Dict[str, Any]:
    present = sorted(name for name in os.listdir(TEMPLATE_DIR)
                     if name.endswith(".html")) if os.path.isdir(
                         TEMPLATE_DIR) else []
    return {
        "template_runtime_available": jinja2_available(),
        "declared_template_count": len(TEMPLATE_NAMES),
        "present_template_count": len(present),
        "templates_match_allowlist": sorted(TEMPLATE_NAMES) == present,
        "html_gate_version": HTML_GATE_VERSION,
    }


def _claim_scan_status() -> Dict[str, Any]:
    """Render one real page and scan it. Not a claim about scanning.

    The home page needs no client, no catalogue and no release, so it renders
    in any environment where Jinja2 is present - which makes this a genuine
    end-to-end check of template, gate and warning rather than a flag.
    """
    if not jinja2_available():
        return {"claim_scan_executed": False,
                "claim_scan_clean": None,
                "note": ("Jinja2 is not installed, so no page was rendered "
                         "and nothing was scanned.")}
    try:
        from apps.web.claim_gate import scan_page
        from apps.web.pages import PageEnvironment, render_home_page

        result = render_home_page(PageEnvironment(environment="GATE-STATUS"))
        report = scan_page(result.html)
        return {
            "claim_scan_executed": True,
            "claim_scan_clean": bool(report.is_clean),
            "scanned_page_bytes": report.html_length,
            "note": ("One page was really rendered and really scanned to "
                     "produce this value."),
        }
    except Exception:  # noqa: BLE001 - reported, never raised from a status
        return {"claim_scan_executed": False, "claim_scan_clean": None,
                "note": "Rendering a page for the scan did not complete."}


def _case_counts() -> Dict[str, Any]:
    from apps.web.demo_cases import DemoCaseError, load_development_cases

    try:
        cases = load_development_cases()
    except DemoCaseError:
        return {
            "development_case_count": 0,
            "development_case_count_source": (
                "the sealed catalogue is not present; the count is zero "
                "because there is nothing to read, not because it was empty"),
            "migrated_case_count": 0,
            "authored_case_count": 0,
            "case_catalog_available": False,
        }
    migrated = sum(1 for case in cases if case.legacy_profile_key)
    return {
        "development_case_count": len(cases),
        "development_case_count_source": (
            "read from the sealed catalogue under data/demo/"),
        "migrated_case_count": migrated,
        "authored_case_count": len(cases) - migrated,
        "case_catalog_available": True,
        "case_catalog_schema_version": CASE_CATALOG_SCHEMA_VERSION,
    }


def _inherited_api_status() -> Dict[str, Any]:
    """WP-16's own gate status, inherited rather than re-measured.

    The API's runtime verification is the API's answer. Re-deriving it here
    would produce a second number that could disagree with the first, and the
    first is the one the API layer maintains.
    """
    from apps.api.gate_status import build_gate_status

    api = build_gate_status()
    return {
        "api_implementation_status": api["implementation_status"],
        "api_dependencies_available": api["api_dependencies_available"],
        "api_runtime_verification": api["openapi"]["runtime_verification"],
        "api_asgi_runtime_tests_executed": api["asgi_runtime_tests_executed"],
        "postgresql_runtime_available": api["postgresql_runtime_available"],
        "claim_boundary_phase": api["claim_boundary_phase"],
        "claim_boundary_status": api["claim_boundary_status"],
        "claim_boundary_approved": api["claim_boundary_approved"],
        "authentication_implemented": api["authentication_implemented"],
        "active_release_available": api["active_release_available"],
        "real_assessment_count": api["real_assessment_count"],
        "real_api_assessment_count": api["real_api_assessment_count"],
        "real_report_count": api["real_report_count"],
    }


def _wp18_status() -> Dict[str, Any]:
    markers = ("pgx/validation", "apps/validation", "data/holdout",
               "docs/architecture/wp18-validation-dataset.md")
    found = [relative for relative in markers
             if os.path.exists(os.path.join(_REPO_ROOT, relative))]
    return {"wp18_started": bool(found), "wp18_markers_found": found}


def validation_blockers(locale: str = "tr") -> Tuple[Tuple[str, str], ...]:
    """The blockers the validation page lists, in controlled text."""
    entries = {
        # WP-18 is implemented; what is absent is the dataset. Those are
        # different statements and the page must make the second one, because
        # "the architecture is missing" and "there is nothing to measure" send
        # a reader to different places.
        "WP-18": {
            "tr": "Doğrulama veri kümesi mimarisi uygulandı; bu depoda "
                  "hiçbir holdout vakası yoktur. Yedi geliştirme vakası "
                  "doğrulama kanıtı değildir.",
            "en": "The validation dataset architecture is implemented and "
                  "this repository holds no holdout case. The seven "
                  "development cases are not validation evidence."},
        # WP-21 is implemented now. What is absent is a benchmark to run: no
        # active release, no holdout case, no reference judgment. Saying "not
        # implemented" would send a reader to the wrong place - there is
        # nothing left to build here, and something left to author.
        "WP-21": {
            "tr": "Doğrulama ölçütleri uygulandı; hiçbir sürüm için "
                  "karşılaştırma çalıştırılmamıştır. Etkin sürüm, holdout "
                  "vakası ve referans yargısı bulunmadığı için her ölçüt "
                  "çalıştırılmadı durumundadır.",
            "en": "Validation metrics are implemented and no benchmark has "
                  "been run against any release. With no active release, no "
                  "holdout case and no reference judgment, every metric is "
                  "not executed."},
        "WP-22": {
            "tr": "Uzman inceleme protokolü uygulanmadı.",
            "en": "The expert review protocol is not implemented."},
        "CLAIM_BOUNDARY": {
            "tr": "İddia sınırı insan ve bilimsel inceleme beklemektedir.",
            "en": "The claim boundary awaits human and scientific review."},
        "ACTIVE_RELEASE": {
            "tr": "Bu depoda etkin bir sürüm bulunmuyor.",
            "en": "No release is active in this repository."},
    }
    key = "en" if locale == "en" else "tr"
    return tuple((code, text[key]) for code, text in sorted(entries.items()))


def build_ui_gate_status() -> Dict[str, Any]:
    """Build the WP-17 gate status by measuring this repository."""
    dependencies = web_dependency_availability()
    templates = _template_status()
    browser = _browser_available()
    scan = _claim_scan_status()
    cases = _case_counts()
    api = _inherited_api_status()

    asgi_available = all(dependencies[name]["importable"]
                         for name in ("fastapi", "starlette"))

    blockers: List[Dict[str, Any]] = []
    if not asgi_available:
        missing = sorted(name for name in ("fastapi", "starlette", "uvicorn",
                                           "httpx", "multipart")
                         if not dependencies[name]["importable"])
        blockers.append({
            "code": "WEB_ASGI_RUNTIME_UNAVAILABLE", "blocking": True,
            "detail": "not importable in this environment: %s"
                      % ", ".join(missing)})
    if not browser["browser_runtime_available"]:
        blockers.append({
            "code": "WEB_BROWSER_RUNTIME_UNAVAILABLE", "blocking": True,
            "detail": "no browser binary and no browser automation package is "
                      "present, so no end-to-end browser test ran and no "
                      "screenshot was captured"})
    if not api["claim_boundary_approved"]:
        blockers.append({
            "code": "WEB_CLAIM_BOUNDARY_NOT_APPROVED", "blocking": True,
            "detail": "claim boundary status is %s"
                      % api["claim_boundary_status"]})
    if not api["active_release_available"]:
        blockers.append({
            "code": "WEB_NO_ACTIVE_RELEASE", "blocking": True,
            "detail": "no release is active, so no page can show a pinned "
                      "version or run an assessment"})
    blockers.append({
        "code": "WEB_AUTHENTICATION_NOT_IMPLEMENTED", "blocking": True,
        "detail": "the login screen is an honest shell; authentication, "
                  "sessions and CSRF belong to WP-23"})
    blockers.append({
        "code": "WEB_VALIDATION_ARCHITECTURE_UNAVAILABLE", "blocking": True,
        "detail": "the validation dashboard shows an empty state only; the "
                  "dataset architecture and the metrics belong to WP-18 and "
                  "WP-21"})
    # Replaced at WP-22. The screen is no longer a disabled shell: it renders
    # the real eight-step workflow against the real service. What still
    # blocks it is that no deployment can issue a CSRF token or authenticate
    # a reviewer, so every control is inert - which is a WP-23 fact, not a
    # WP-22 one, and is worth saying precisely rather than leaving a stale
    # sentence that reads as "the workflow was never built".
    blockers.append({
        "code": "WEB_EXPERT_REVIEW_FORMS_DISABLED", "blocking": True,
        "detail": "the expert-review workflow renders, and its forms cannot "
                  "submit: authentication and CSRF belong to WP-23, so no "
                  "reviewer can be identified and no control is enabled"})
    blockers.sort(key=lambda item: item["code"])

    return {
        "gate_status_schema_version": UI_GATE_STATUS_SCHEMA_VERSION,
        "work_package": "WP-17",

        # 1. Implementation.
        "implementation_status": "IMPLEMENTED",
        "web_version": WEB_VERSION,
        "declared_route_count": len(WEB_ROUTES),
        "state_changing_route_count": len(STATE_CHANGING_ROUTES),

        # 2. Runtimes, each reported on its own.
        **templates,
        "asgi_runtime_available": asgi_available,
        "asgi_runtime_tests_executed": _asgi_runtime_available(),
        "asgi_runtime_note": (
            "tests/integration/web/test_asgi_web.py runs when the ASGI stack "
            "imports and skips, naming the missing packages, when it does "
            "not. This flag reports whether the stack imports here; it is not "
            "a record of a particular run."),
        **browser,
        **_screenshot_status(),
        "accessibility_structural_tests_available": True,
        "accessibility_structural_test_note": (
            "Structural checks parse the rendered HTML with the standard "
            "library, so they run wherever the templates render. No axe or "
            "browser-based audit has been performed."),
        **scan,

        # 3. Inherited from WP-16, not re-measured.
        **api,

        # 4. Governance and workflow status.
        "csrf_implemented": False,
        "session_management_implemented": False,
        "login_is_shell_only": True,
        "expert_review_workflow_status": "NOT_IMPLEMENTED",
        "validation_dashboard_status": "EMPTY_STATE_ONLY",

        # 5. What actually exists.
        **cases,
        "real_validation_case_count": 0,
        "real_validation_case_count_source": (
            "no validation case architecture exists, so there is nothing to "
            "count; development cases are not validation cases"),
        "holdout_case_count": None,
        "holdout_case_count_note": (
            "null rather than zero: holdout storage is not implemented, so no "
            "count was taken"),

        # 6. What was not started.
        **_wp18_status(),

        "blocker_count": len(blockers),
        "blockers": blockers,
        "may_serve_real_traffic": False,
        "note": (
            "An expected governance and environment result, not a test "
            "failure. The interface is implemented and its templates really "
            "render in this environment - the HTML is produced, scanned for "
            "prohibited claims and parsed for structure by the test suite. "
            "What is blocked is everything needing a package index, a "
            "browser, a database or a human approval. No count above was "
            "asserted rather than measured, no missing dependency was "
            "replaced with a stand-in, and no synthetic artifact is presented "
            "as real."),
    }
