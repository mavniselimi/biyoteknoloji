#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Assemble the Wave 4 execution manifest from the artifacts."""

from __future__ import annotations

import hashlib
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT = os.path.join(REPO, "data", "closure", "wave-04-execution-manifest.json")


def _read(*parts):
    with io.open(os.path.join(REPO, *parts), encoding="utf-8") as handle:
        return json.load(handle)


def _digest(path):
    with io.open(path, "rb") as handle:
        return "sha256:" + hashlib.sha256(handle.read()).hexdigest()


def main() -> int:
    catalogue = _read("data", "closure", "wave-04-catalogue",
                      "manifest.json")
    benchmark = _read("data", "closure", "wave-04-benchmark",
                      "run-manifest.json")
    performance = _read("data", "closure", "wave-04-performance.json")
    operational = _read("data", "closure",
                        "wave-04-operational-evidence.json")
    browser = _read("data", "web", "wave-04-browser",
                    "browser-verification.json")
    routes = _read("data", "web", "wave-04-route-audit.json")

    served = [p for p in browser["pages"] if p.get("status") == 200]
    blocked = [p for p in browser["pages"] if p.get("status") == 503]

    work_packages = [
        {"work_package": "WP-C10",
         "subject": "validation catalogue and holdout closure",
         "verdict": "COMPLETE",
         "evidence": ("%d cases sealed before any benchmark run: %d "
                      "development, %d internal holdout, %d expert reserved; "
                      "%d separation issues; reserved cases carry no expected "
                      "answer"
                      % (catalogue["case_total"],
                         catalogue["development_count"],
                         catalogue["internal_holdout_count"],
                         catalogue["expert_holdout_count"],
                         catalogue["separation_issue_count"]))},
        {"work_package": "WP-C11", "subject": "benchmark and metrics",
         "verdict": "COMPLETE",
         "evidence": ("%d cases scored, %d failures, %d unsafe false "
                      "reassurance, all declared thresholds met, %d reserved "
                      "payloads read"
                      % (benchmark["metrics"]["scored_case_count"],
                         benchmark["metrics"]["failed_case_count"],
                         benchmark["metrics"]["unsafe_false_reassurance_count"],
                         benchmark["metrics"]["expert_reserved_payloads_read"]))},
        {"work_package": "WP-C13", "subject": "operational evidence",
         "verdict": "PARTIAL",
         "evidence": ("PostgreSQL 16.13 migration round-trip to head "
                      "0012 verified, both new vocabulary values accepted and "
                      "invented ones rejected, 1,000-assessment run at p50 "
                      "%.3f ms / p95 %.3f ms with 0 errors; %d residuals "
                      "remain blocked on network egress or a missing driver"
                      % (performance["latency_p50_ms"],
                         performance["latency_p95_ms"],
                         len(operational["blocked"])))},
        {"work_package": "WP-C14A",
         "subject": "product surface and demo UX closure",
         "verdict": "PARTIAL",
         "evidence": ("%d web routes and %d API routes audited; %d pages "
                      "verified through Chromium at 1440x900, %d served and "
                      "%d returning an honest AUTHENTICATION_NOT_CONFIGURED "
                      "503; canonical warning present on every page; no "
                      "broken layout; the web surface is not wired to the "
                      "candidate release, which /system reports accurately"
                      % (routes["web_route_count"], routes["api_route_count"],
                         len(browser["pages"]), len(served), len(blocked)))},
        {"work_package": "WP-C14",
         "subject": "representative candidate demonstration",
         "verdict": "BLOCKED",
         "evidence": ("its prerequisites are a deployed web/API in a "
                      "production-like environment and a real PostgreSQL "
                      "behind the application. The database exists; the "
                      "deployment does not, and a localhost process in an "
                      "ephemeral container is not staging. Four of the six "
                      "jury-flow screens are behind authentication, which "
                      "cannot be composed without a driver that cannot be "
                      "installed.")},
    ]

    files = []
    for relative in (
            os.path.join("data", "closure", "wave-04-catalogue"),
            os.path.join("data", "closure", "wave-04-benchmark"),
            os.path.join("data", "web", "wave-04-browser")):
        base = os.path.join(REPO, relative)
        for name in sorted(os.listdir(base)):
            path = os.path.join(base, name)
            if os.path.isfile(path):
                files.append({"path": os.path.join(relative, name).replace(
                    os.sep, "/"), "sha256": _digest(path),
                    "byte_length": os.path.getsize(path)})
    for relative in (
            os.path.join("data", "closure", "wave-04-performance.json"),
            os.path.join("data", "closure",
                         "wave-04-operational-evidence.json"),
            os.path.join("data", "web", "wave-04-route-audit.json")):
        path = os.path.join(REPO, relative)
        files.append({"path": relative.replace(os.sep, "/"),
                      "sha256": _digest(path),
                      "byte_length": os.path.getsize(path)})

    payload = {
        "benchmark": benchmark,
        "browser_verification": {
            "blocked_pages": len(blocked),
            "canonical_warning_on_every_page": all(
                p.get("has_canonical_warning") for p in browser["pages"]),
            "no_broken_layout": not any(p.get("broken_layout")
                                        for p in browser["pages"]),
            "page_count": len(browser["pages"]),
            "served_pages": len(served),
            "viewport": browser["viewport"],
        },
        "catalogue": catalogue,
        "catalogue_is_not_the_wp18_holdout": {
            "wp18_holdout_case_count": _read(
                "data", "validation",
                "wp18-holdout-case-manifest.json")["case_count"],
            "why": (
                "WP-18 keeps validation case payloads out of this repository "
                "on purpose: a holdout case committed beside the rules it "
                "exists to test is no longer a holdout, and data/validation/ "
                "holds documents only. This catalogue is a different thing "
                "under the same word. Its cases are machine-authored from the "
                "candidate rules' own scope, its INTERNAL_HOLDOUT partition "
                "was sealed before the benchmark but shares one author with "
                "the ruleset, and its expert partition carries inputs with no "
                "expected answers because no expert has seen it. It is "
                "therefore internal-consistency evidence, it lives under "
                "data/closure/ with the rest of the wave artifacts rather "
                "than in data/validation/, and it does not raise WP-18's "
                "holdout count, which remains zero."),
        },
        "files": files,
        "label": "INTERNAL_VALIDATION",
        "manifest_version": "pgx-closure-wave04-manifest/1",
        "operational_evidence": operational,
        "performance": performance,
        "route_audit": {"api_route_count": routes["api_route_count"],
                        "web_route_count": routes["web_route_count"]},
        "work_packages": work_packages,
        "work_package_summary": {
            verdict: sum(1 for w in work_packages if w["verdict"] == verdict)
            for verdict in ("COMPLETE", "PARTIAL", "BLOCKED")},
    }
    with io.open(OUTPUT, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True,
                                ensure_ascii=False) + "\n")
    for item in work_packages:
        sys.stdout.write("  %-8s %-10s %s\n"
                         % (item["work_package"], item["verdict"],
                            item["subject"]))
    sys.stdout.write("\n%s\n" % json.dumps(payload["work_package_summary"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
