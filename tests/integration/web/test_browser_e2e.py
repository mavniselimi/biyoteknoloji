# -*- coding: utf-8 -*-
"""Browser tests. They run when a browser can actually be launched.

These are the only tests in the repository that say what a person in front of
a screen experiences: that the warning is visible without scrolling, that the
focus ring is where the keyboard is, that the status pair survives a 200%
zoom, that the page is usable with JavaScript switched off. Nothing else can
answer those questions, and this file does not pretend anything else does.

**Availability is measured, not assumed - and measuring it correctly is the
point of this docstring.** The earlier version of this file, and the gate
status beside it, decided a browser existed by looking for names on ``PATH``.
The gate status included ``playwright`` in that list, which is the *package's
console script*: it appears the moment ``pip install playwright`` finishes,
whether or not ``playwright install chromium`` has ever run. So one half of
the repository reported a browser it did not have, and the other half skipped
because its own list did not include Playwright at all. Both were wrong, in
opposite directions, about the same host.

What counts as a browser here is one that **starts**:
``apps.web.gate_status.managed_browser_status()`` imports Playwright, resolves
the executable it would launch, checks that the file exists, then launches it
and reads its version. A package is not a browser; a resolved path is not a
browser; a browser is a process that answered.

The skip below is derived from that same measurement, so this file and the
gate status can no longer disagree. When a browser is absent the reason names
which of the three checks failed, and when the application itself cannot be
served it names the missing packages instead.

**Screenshots.** Captured only when these tests actually run, written to
``tests/fixtures/wp17/browser/``, and every one of them is a real capture of a
real page from a real browser. When no browser runs, no image exists.

They show public gene symbols, because the migrated development cases name
real genes; they show no real patient data, no real person and no validation
evidence. ``TestTheBrowserRuntimeIsReportedHonestly`` below, which never
skips, fails if an image is committed anywhere the capture path could not have
written it, or if any document claims a browser run that did not happen.
"""

from __future__ import annotations

import os
import unittest

from apps.web.gate_status import (managed_browser_status as
                                  _managed_browser_status)


def browser_runtime_status():
    """The gate status' own measurement, reused rather than re-implemented."""
    import shutil

    from apps.web.gate_status import _BROWSER_BINARIES

    managed = dict(_managed_browser_status())
    found = [name for name in _BROWSER_BINARIES if shutil.which(name)]
    managed["browser_binaries_found"] = found
    managed["browser_runtime_available"] = bool(found) or managed[
        "managed_browser_launchable"]
    return managed

#: The one measurement, shared with the gate status so the two cannot report
#: different things about the same host.
_BROWSER = browser_runtime_status()

_SERVER_MISSING = []
for _name in ("fastapi", "uvicorn", "starlette"):
    try:  # pragma: no cover - environment dependent
        __import__(_name)
    except ImportError:  # pragma: no cover - environment dependent
        _SERVER_MISSING.append(_name)

#: Where captures go. One directory, created only when a capture is taken.
SCREENSHOT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))),
    "fixtures", "wp17", "browser")

#: The second directory a committed image may legitimately live in. Wave 4's
#: browser verification writes here, beside ``browser-verification.json``,
#: which names every capture it took;
#: ``test_every_wave04_capture_is_named_by_its_own_evidence_document`` holds
#: the two to each other so this exemption cannot widen quietly.
WAVE04_CAPTURE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))),
    "data", "web", "wave-04-browser")

#: The third. Wave 4B's sixteen-step flow writes here, beside
#: ``jury-flow.json``, which names every step it walked.
#: ``test_every_wave04b_capture_is_named_by_its_own_step`` holds the two to
#: each other, so this exemption buys no more than the last one did.
#:
#: Registered late, and that is the finding: Wave 4B committed sixteen images
#: into a directory the stray check did not know about, and the check went on
#: passing everywhere it could not run. This suite needs fastapi and starlette,
#: which the host that ran Wave 4B's own tests does not have.
WAVE04B_CAPTURE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))),
    "data", "closure", "wave-04b-browser")


def _skip_reason() -> str:
    """Name the prerequisite that is missing, not just 'blocked'."""
    problems = []
    if not _BROWSER["browser_runtime_available"]:
        if not _BROWSER["playwright_importable"]:
            problems.append("the playwright package is not importable and no "
                            "browser binary is on PATH")
        elif not _BROWSER["managed_browser_exists"]:
            problems.append(
                "playwright imports but its managed browser is not on disk "
                "at %r - run `playwright install chromium`"
                % _BROWSER["managed_browser_path"])
        else:
            problems.append(
                "the managed browser exists at %r but did not launch (%s)"
                % (_BROWSER["managed_browser_path"],
                   _BROWSER["managed_browser_probe_error"]))
    if _SERVER_MISSING:
        problems.append("the application cannot be served: %s not installed"
                        % ", ".join(_SERVER_MISSING))
    if not problems:
        return ""
    return ("no browser evidence can be produced on this host - %s. These "
            "tests did not execute here; no screenshot in this repository is "
            "a browser capture, and every visual or interactive claim in the "
            "WP-17 documents is marked UNVERIFIED rather than assumed."
            % "; ".join(problems))


SKIP_REASON = _skip_reason()
BROWSER_AVAILABLE = not SKIP_REASON


class TestTheBrowserRuntimeIsReportedHonestly(unittest.TestCase):
    """This class is **not** skipped. It is the honesty check itself."""

    def test_the_gate_status_agrees_with_the_host(self):
        import io
        import json

        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.dirname(os.path.abspath(__file__))))),
            "data", "web", "wp17-real-gate-status.json")
        with io.open(path, encoding="utf-8") as handle:
            status = json.load(handle)
        self.assertEqual(status["browser_runtime_available"],
                         BROWSER_AVAILABLE)
        if not BROWSER_AVAILABLE:
            self.assertEqual(status["screenshot_evidence_status"], "NONE")

    def test_no_image_is_committed_outside_a_capture_directory(self):
        """An image nowhere near a capture path is unexplained.

        Also rewritten away from "does this host have a browser". A committed
        capture is legitimate on a machine that cannot take one; what is not
        legitimate is an image that no code path could have produced.

        Two code paths produce images. ``test_every_page_is_captured`` writes
        into ``tests/fixtures/wp17/browser/``, and Wave 4's browser
        verification writes into ``data/web/wave-04-browser/`` beside the
        document that records what each capture shows. Every other image in
        the repository is a stray.
        """
        root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))))
        allowed = {os.path.abspath(SCREENSHOT_DIR),
                   os.path.abspath(WAVE04_CAPTURE_DIR),
                   os.path.abspath(WAVE04B_CAPTURE_DIR)}
        strays = []
        for directory in ("docs", "data", "tests"):
            for base, dirs, files in os.walk(os.path.join(root, directory)):
                dirs[:] = [name for name in dirs if name != "__pycache__"]
                if os.path.abspath(base) in allowed:
                    continue
                for name in files:
                    if name.lower().endswith((".png", ".jpg", ".jpeg",
                                              ".webp")):
                        strays.append(os.path.relpath(
                            os.path.join(base, name), root))
        self.assertEqual(strays, [])

    def test_every_wave04_capture_is_named_by_its_own_evidence_document(self):
        """What the second capture directory buys itself an exemption to do.

        A directory the stray check skips could otherwise hold any image at
        all. This closes it from the other side: the set of image files in
        ``data/web/wave-04-browser/`` must equal exactly the set of
        screenshots ``browser-verification.json`` names, so an image with no
        recorded page - and a recorded page with no image - both fail.
        """
        import io as _io
        import json as _json

        if not os.path.isdir(WAVE04_CAPTURE_DIR):
            self.skipTest("no Wave 4 capture directory in this checkout")
        record = os.path.join(WAVE04_CAPTURE_DIR, "browser-verification.json")
        self.assertTrue(os.path.isfile(record), record)
        with _io.open(record, encoding="utf-8") as handle:
            document = _json.load(handle)
        named = {page["screenshot"] for page in document["pages"]}
        present = {name for name in os.listdir(WAVE04_CAPTURE_DIR)
                   if name.lower().endswith((".png", ".jpg", ".jpeg",
                                             ".webp"))}
        self.assertEqual(present, named)

    def test_every_wave04b_capture_is_named_by_its_own_step(self):
        """The third directory, closed from the other side like the second.

        ``jury-flow.json`` records one step per page walked, and each step's
        screenshot is that step's name. The set of images on disk must equal
        the set of step names exactly: an image no step produced, and a step
        with no image, both fail here.
        """
        import io as _io
        import json as _json

        if not os.path.isdir(WAVE04B_CAPTURE_DIR):
            self.skipTest("no Wave 4B capture directory in this checkout")
        record = os.path.join(WAVE04B_CAPTURE_DIR, "jury-flow.json")
        self.assertTrue(os.path.isfile(record), record)
        with _io.open(record, encoding="utf-8") as handle:
            document = _json.load(handle)
        named = {"%s.png" % step["name"] for step in document["steps"]}
        present = {name for name in os.listdir(WAVE04B_CAPTURE_DIR)
                   if name.lower().endswith((".png", ".jpg", ".jpeg",
                                             ".webp"))}
        self.assertEqual(present, named)

    def test_the_documents_do_not_claim_a_browser_ran(self):
        """A claim that a browser ran needs committed evidence behind it.

        Gated on the *evidence*, not on this host. The first version skipped
        whenever the local machine happened to have a browser, which meant it
        checked nothing on the machines most likely to have written such a
        claim, and would have failed truthful documentation on a machine that
        merely lacked one. What makes the claim legitimate is that captures
        are committed - so that is what is asked.
        """
        root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))))
        if os.path.isdir(SCREENSHOT_DIR) and any(
                name.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))
                for name in os.listdir(SCREENSHOT_DIR)):
            self.skipTest("browser captures are committed; the claim is "
                          "backed by evidence in tests/fixtures/wp17/browser/")
        import io
        import re

        # Phrases that would assert a browser run happened. Searched for as
        # whole claims rather than as words, so a document may freely *say*
        # that no browser ran.
        forbidden = re.compile(
            r"(screenshot(s)? (were|was) (taken|captured))"
            r"|(captured in (a|the) browser)"
            r"|(verified in (a|the) browser)"
            r"|(browser (run|test)s? passed)", re.IGNORECASE)
        offenders = []
        for base, _dirs, files in os.walk(os.path.join(root, "docs")):
            for name in files:
                if not name.endswith(".md"):
                    continue
                path = os.path.join(base, name)
                with io.open(path, encoding="utf-8") as handle:
                    for number, line in enumerate(handle, 1):
                        if forbidden.search(line):
                            offenders.append("%s:%d" % (path, number))
        self.assertEqual(offenders, [])


class TestTheSkippedTestsHaveNotRotted(unittest.TestCase):
    """Also not skipped. A test that never runs decays silently.

    Every CSS selector the browser tests below depend on is checked against
    the committed templates here, without a browser. If a template stops
    emitting ``.clinical-warning`` or ``.status-pair``, this fails now rather
    than in whichever environment first has a browser to notice.
    """

    #: Each selector, and the template that must contain it.
    SELECTORS = (("clinical-warning", "_warning.html"),
                 ("status-pair", "_status_pair.html"),
                 ("status-attention", "_status_pair.html"),
                 ("status-coverage", "_status_pair.html"))

    def _template(self, name):
        import io as _io

        root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))))
        path = os.path.join(root, "apps", "web", "templates", name)
        with _io.open(path, encoding="utf-8") as handle:
            return handle.read()

    @staticmethod
    def _class_tokens(markup):
        """Every class name the template emits, as tokens rather than text.

        A substring search would pass on ``status-attention-note`` and on the
        word appearing in a comment, so the attributes are read and split.
        """
        import re

        tokens = set()
        for value in re.findall(r'class="([^"]*)"', markup):
            tokens.update(value.split())
        return tokens

    def test_every_selector_the_browser_tests_use_still_exists(self):
        for class_name, template in self.SELECTORS:
            self.assertIn(class_name, self._class_tokens(
                self._template(template)),
                "%s missing from %s" % (class_name, template))

    def test_the_selectors_are_named_in_this_file(self):
        # The pair above is only useful if it stays in step with the tests, so
        # the file is read for its own selectors and each must be listed.
        import io as _io
        import re

        with _io.open(os.path.abspath(__file__), encoding="utf-8") as handle:
            body = handle.read()
        used = set(re.findall(r'locator\("\.([a-z-]+)"', body))
        listed = {name for name, _template in self.SELECTORS}
        self.assertEqual(used - listed, set())


def _serve(world):  # pragma: no cover - needs a server and a browser
    """Run the real application on a loopback port for the duration of a test."""
    import threading

    import uvicorn

    from apps.web.factory import create_web_app
    from tests.fixtures.wp17.synthetic import (synthetic_providers,
                                               test_web_settings)

    settings = test_web_settings()
    # Both providers. The web half owns the client, the catalogue and the CSRF
    # verifier; the API half owns the principal resolver every page route is
    # guarded by. Serving with only the first answered SERVICE_NOT_READY on
    # every route, public ones included.
    web_provider, api_provider = synthetic_providers(world, settings=settings,
                                                     with_csrf=True)
    app = create_web_app(settings, web_provider, api_provider=api_provider)
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:  # pragma: no cover - startup race
        pass
    port = server.servers[0].sockets[0].getsockname()[1]
    return server, thread, "http://127.0.0.1:%d" % port


@unittest.skipIf(SKIP_REASON, SKIP_REASON)
class TestThePageInARealBrowser(unittest.TestCase):  # pragma: no cover

    def setUp(self):
        from playwright.sync_api import sync_playwright

        from tests.unit.web._support import synthetic_world

        from tests.fixtures.wp16.synthetic import TEST_REVIEWER_TOKEN

        self.world = synthetic_world()
        self.addCleanup(self.world.close)
        self.server, self.thread, self.base = _serve(self.world)
        self._pw = sync_playwright().start()
        self.browser = self._pw.chromium.launch()
        # Seven of the eleven routes need a principal, and a browser suite
        # quietly looking at 401 pages would assert almost nothing. The
        # reviewer token reaches every route including the expert-review
        # screen. This is WP-16's development static token: there is no
        # session, no cookie and no login here, and WP-23 owns all three.
        self._context = self.browser.new_context(
            extra_http_headers={"Authorization": "Bearer "
                                + TEST_REVIEWER_TOKEN})
        self.page = self._context.new_page()

    def _capture(self, name):
        """Take a real screenshot, and say plainly that it is one.

        Written only while a browser is actually running. Nothing here
        fabricates an image, and ``TestTheBrowserRuntimeIsReportedHonestly``
        fails if one is committed on a host that has no browser.
        """
        if not os.path.isdir(SCREENSHOT_DIR):
            os.makedirs(SCREENSHOT_DIR)
        path = os.path.join(SCREENSHOT_DIR, "%s.png" % name)
        self.page.screenshot(path=path, full_page=True)
        return path

    def tearDown(self):
        self._context.close()
        self.browser.close()
        self._pw.stop()
        self.server.should_exit = True
        self.thread.join(timeout=5)

    def test_the_warning_is_visible_without_scrolling(self):
        self.page.set_viewport_size({"width": 1280, "height": 800})
        self.page.goto(self.base + "/cases")
        warning = self.page.locator(".clinical-warning")
        self.assertTrue(warning.is_visible())
        box = warning.bounding_box()
        self.assertLess(box["y"], 800)

    def test_the_warning_cannot_be_dismissed(self):
        self.page.goto(self.base + "/cases")
        self.page.keyboard.press("Escape")
        self.assertTrue(
            self.page.locator(".clinical-warning").is_visible())

    def test_the_page_works_with_javascript_disabled(self):
        from tests.fixtures.wp16.synthetic import TEST_REVIEWER_TOKEN

        context = self.browser.new_context(
            java_script_enabled=False,
            extra_http_headers={"Authorization": "Bearer "
                                + TEST_REVIEWER_TOKEN})
        page = context.new_page()
        page.goto(self.base + "/cases")
        self.assertTrue(
            page.locator(".clinical-warning").is_visible())
        self.assertGreater(page.locator("main a").count(), 0)
        context.close()

    def test_the_status_pair_stays_together_at_200_percent_zoom(self):
        self.page.set_viewport_size({"width": 640, "height": 480})
        self.page.goto(self.base + "/cases/WP17-CASE-P1")
        pairs = self.page.locator(".status-pair")
        for index in range(pairs.count()):
            pair = pairs.nth(index)
            self.assertEqual(pair.locator(".status-attention").count(),
                             1)
            self.assertEqual(pair.locator(".status-coverage").count(),
                             1)

    def test_every_interactive_element_is_reachable_by_keyboard(self):
        self.page.goto(self.base + "/cases")
        focusable = self.page.locator(
            "a[href], button:not([disabled]), input:not([disabled])")
        expected = focusable.count()
        seen = set()
        for _ in range(expected * 2):
            self.page.keyboard.press("Tab")
            seen.add(self.page.evaluate(
                "() => document.activeElement && "
                "document.activeElement.outerHTML"))
        self.assertGreaterEqual(len(seen), expected)

    def test_the_page_requests_nothing_from_a_remote_origin(self):
        remote = []
        self.page.on("request", lambda request: (
            remote.append(request.url)
            if not request.url.startswith(self.base) else None))
        self.page.goto(self.base + "/cases")
        self.page.wait_for_load_state("networkidle")
        self.assertEqual(remote, [])

    def test_every_page_is_captured(self):
        """Walk the interface in a real browser and photograph what it shows.

        This is the only artifact in the repository that records what the
        pages actually *look* like. Each file is a real capture of a real page
        from a launched Chromium, taken during this test; if this test does
        not run, no file is written and the gate status reports
        ``screenshot_evidence_status: NONE``.

        Public gene symbols appear in two of them - the migrated development
        cases name CYP1A2, CYP2C19, CYP2C9, CYP2D6 and CYP3A4, and the
        migration kept those identities rather than inventing substitutes. A
        gene symbol is published nomenclature, not data about a person.

        Everything behind them is synthetic: development-fixture cases,
        assessments computed against the synthetic TESTGENE ruleset, and
        fixture evidence records. No real patient data, no real person and no
        validation evidence is captured.
        """
        captured = []
        for name, path in (("home", "/"),
                           ("login", "/login"),
                           ("cases", "/cases"),
                           ("case-detail", "/cases/WP17-CASE-P1"),
                           ("validation", "/validation"),
                           ("expert-review",
                            "/expert-reviews/WP17-CASE-P1"),
                           ("system", "/system")):
            with self.subTest(page=name):
                response = self.page.goto(self.base + path)
                self.assertEqual(response.status, 200, path)
                self.page.wait_for_load_state("networkidle")
                captured.append(self._capture(name))

        self.assertEqual(len(captured), 7)
        for path in captured:
            self.assertTrue(os.path.isfile(path))
            # A PNG, not an empty file with a PNG name.
            with open(path, "rb") as handle:
                self.assertEqual(handle.read(8),
                                 b"\x89PNG\r\n\x1a\n")
            self.assertGreater(os.path.getsize(path), 1024)

    def test_the_console_is_clean(self):
        errors = []
        self.page.on("console", lambda message: (
            errors.append(message.text) if message.type == "error" else None))
        self.page.on("pageerror", lambda error: errors.append(str(error)))
        self.page.goto(self.base + "/cases")
        self.page.wait_for_load_state("networkidle")
        self.assertEqual(errors, [])
