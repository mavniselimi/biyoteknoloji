# -*- coding: utf-8 -*-
"""Rendered template output, written to disk so a human can read it.

**These are not screenshots.** They are the exact bytes the template layer
produces for a fixed set of synthetic inputs. No browser has laid them out, no
stylesheet has been applied to them and nobody has looked at them in a window.
What they are good for is review and diffing: a change to a template shows up
here as a change in HTML, in a pull request, where someone can see it.

Every snapshot is built from the synthetic fixtures - the TESTGENE world and
the migrated development catalogue. Two of them, ``cases.html`` and
``case_detail.html``, contain **public gene symbols** (CYP1A2, CYP2C19,
CYP2C9, CYP2D6, CYP3A4), because the migrated development cases name real
genes and the migration kept those identities rather than inventing
substitutes. A gene symbol is published nomenclature, not data about a person.

What is synthetic is everything else: the cases are development fixtures, the
assessments are computed against a synthetic ruleset, and the evidence records
are fixture constants. No real patient data, no real person and no validation
evidence appears in any of them.

**Three pages are deliberately not snapshotted.** The two assessment pages and
the system page each carry a value that is new on every run: an assessment
identifier allocated at submission, and the fingerprint of a frozen ruleset
built into a fresh temporary directory. (The evidence page is *not* among them
- every identifier it shows is a fixture constant, so it is committed like the
rest. That was established by the test rather than assumed.) Committing them would
mean either a file that fails on every run or a file with those values edited
out - and an artifact with its volatile parts quietly overwritten is exactly
the kind of doctored evidence this work package is not permitted to produce.
Their determinism is checked where it is real: ``tests/unit/web/test_pages.py``
renders the same response document twice and compares the bytes.
:data:`EXCLUDED_PAGES` names them and ``tests/unit/web/test_snapshots.py``
asserts that each one genuinely does vary, so the exclusion is revisited if
that ever stops being true.

Regenerate with::

    python -m tests.fixtures.wp17.snapshots

``tests/unit/web/test_snapshots.py`` re-renders each one and compares, so a
template change that is not regenerated fails the suite rather than leaving a
stale file behind.
"""

from __future__ import annotations

import io
import os
from typing import Dict

from apps.web.pages import (render_assessment_page, render_case_detail_page,
                            render_cases_page, render_error_page,
                            render_evidence_page, render_expert_review_page,
                            render_home_page, render_login_page,
                            render_system_page, render_validation_page)

__all__ = ["EXCLUDED_PAGES", "SNAPSHOT_DIR", "build_all_pages",
           "build_snapshots", "main", "write_snapshots"]

SNAPSHOT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "snapshots")

#: Prepended to every file. A reader who opens one of these out of context
#: must not be able to mistake it for a captured screen or for real output.
BANNER = (
    "<!-- Rendered template output from the WP-17 development fixtures.\n"
    "     Not a screenshot and not a browser capture.\n"
    "     Public gene symbols may appear; cases, profiles and assessments\n"
    "     are synthetic development fixtures. No real patient data, no real\n"
    "     person and no validation evidence is shown.\n"
    "     Regenerate: python -m tests.fixtures.wp17.snapshots -->\n")


#: Pages whose bytes carry a per-run identifier or fingerprint. Rendered by
#: :func:`build_all_pages`, never written to disk. See the module docstring.
EXCLUDED_PAGES = ("assessment_covered.html", "assessment_insufficient.html",
                  "system.html")


def build_snapshots() -> Dict[str, str]:
    """The pages that are byte-stable across runs. What gets committed."""
    return {name: html for name, html in build_all_pages().items()
            if name not in EXCLUDED_PAGES}


def build_all_pages() -> Dict[str, str]:
    """Render every page against the synthetic world, excluded ones included."""
    from tests.fixtures.wp13.synthetic import DRUG_1
    from tests.fixtures.wp17.synthetic import (COVERED_FIXTURE_CASE,
                                               case_by_id, development_cases,
                                               execution_context,
                                               page_environment,
                                               synthetic_web_provider)
    from tests.unit.web._support import synthetic_world

    env = page_environment()
    cases = development_cases()
    pages: Dict[str, str] = {}

    world = synthetic_world()
    try:
        return _render_all(world, env, cases, pages)
    finally:
        # The world owns a temporary directory holding a frozen ruleset. This
        # function is called four times by tests/unit/web/test_snapshots.py
        # alone, so a missing close here is four leaked trees per run.
        world.close()


def _render_all(world, env, cases, pages):
    from tests.fixtures.wp13.synthetic import DRUG_1
    from tests.fixtures.wp17.synthetic import (COVERED_FIXTURE_CASE,
                                               case_by_id,
                                               execution_context,
                                               synthetic_web_provider)

    provider = synthetic_web_provider(world)
    client = provider.client
    context = execution_context()

    from apps.web.submission import build_assessment_request

    covered = client.create_assessment(
        build_assessment_request(COVERED_FIXTURE_CASE,
                                 medications=(DRUG_1,)),
        context=context)
    insufficient = client.create_assessment(
        build_assessment_request(case_by_id("WP17-CASE-P2"),
                                 medications=(DRUG_1,)),
        context=context)

    pages["home.html"] = render_home_page(env).html
    pages["login.html"] = render_login_page(
        env, authentication_configured=False).html
    pages["cases.html"] = render_cases_page(env, cases=cases,
                                            available=True).html
    pages["case_detail.html"] = render_case_detail_page(
        env, case=case_by_id("WP17-CASE-P1"), client=client,
        submit_available=False, csrf_token=None).html
    pages["assessment_covered.html"] = render_assessment_page(
        env, document=covered.document).html
    pages["assessment_insufficient.html"] = render_assessment_page(
        env, document=insufficient.document).html
    # WP-21: the committed public feed, so the snapshot shows the page a
    # reader actually gets - three partition tables, every metric NOT_EXECUTED.
    # Deliberately the real feed and not the synthetic one: a committed
    # snapshot carrying numbers could be mistaken for a validation result.
    from apps.web.validation_feed import load_dashboard_feed
    pages["validation.html"] = render_validation_page(
        env, development_case_count=len(cases),
        feed=load_dashboard_feed()).html
    pages["expert_review.html"] = render_expert_review_page(
        env, case_id="WP17-CASE-P1").html
    pages["system.html"] = render_system_page(env, client=client).html
    pages["error.html"] = render_error_page(
        env, code="RESOURCE_NOT_FOUND").html

    evidence_id = _first_evidence_id(covered.document)
    if evidence_id is not None:
        pages["evidence.html"] = render_evidence_page(
            env,
            document=client.get_evidence(
                evidence_id,
                request_id=env.request_id).document).html

    return {name: BANNER + html for name, html in sorted(pages.items())}


def _first_evidence_id(document):
    """The first evidence identifier the assessment document refers to.

    Evidence hangs off a gene-drug axis and off a finding, and a covered axis
    can cite evidence without producing a finding, so both are walked. The
    document is read exactly as the view model reads it; nothing here derives
    a reference the interface would not show.
    """
    for medication in document.get("medications") or ():
        for axis in medication.get("axes") or ():
            for reference in axis.get("evidence_references") or ():
                if reference:
                    return str(reference)
        for finding in medication.get("findings") or ():
            for reference in finding.get("evidence_references") or ():
                if reference:
                    return str(reference)
    return None


def write_snapshots(directory: str = SNAPSHOT_DIR) -> Dict[str, str]:
    rendered = build_snapshots()
    if not os.path.isdir(directory):
        os.makedirs(directory)
    for name, html in rendered.items():
        with io.open(os.path.join(directory, name), "w",
                     encoding="utf-8", newline="\n") as handle:
            handle.write(html)
    return rendered


def main(argv=None) -> int:
    for name, html in sorted(write_snapshots().items()):
        print("%8d  %s" % (len(html.encode("utf-8")), name))
    return 0


if __name__ == "__main__":  # pragma: no cover - a developer entry point
    raise SystemExit(main())
