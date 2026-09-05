# -*- coding: utf-8 -*-
"""Measuring coverage, or saying plainly that it could not be measured.

``coverage.py`` is declared in the dev dependency group and configured in
``pyproject.toml``. It is not installed in every environment, and no package
index is reachable from some of them, so this module has two paths and the
important one is the second.

**Measured.** Run the suite under ``coverage run``, export ``coverage json``,
and report line and branch coverage for the first-party packages, per module,
with the critical modules called out.

**Not measured.** Report ``BLOCKED``, name the missing package, and give the
exact command that would install it. Return ``None`` for every percentage.

There is no third path. A percentage is never estimated, never carried over
from an earlier run, and never derived from "how many test files import this
module", which is the tempting approximation and is not coverage. ``None`` is
the honest value for a measurement nobody took, and ``0.0`` is not: zero means
the tool ran and found nothing executed.

The threshold question is handled the same way. This module records what was
measured and which critical modules fell below the *declared* threshold. The
threshold is a constant in this file, written before any measurement was taken,
so it cannot be the number that happened to come out.
"""

from __future__ import annotations

import io
import json
import re
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

__all__ = [
    "COVERAGE_SCHEMA_VERSION",
    "CRITICAL_MODULE_PREFIXES",
    "DECLARED_LINE_THRESHOLD",
    "INSTALL_COMMAND",
    "CoverageSummary",
    "coverage_available",
    "coverage_version",
    "measure_coverage",
    "blocked_summary",
    "omit_patterns",
]

COVERAGE_SCHEMA_VERSION = "pgx-wp19-coverage-summary/1"

#: The exact command for the environment this project is developed in.
INSTALL_COMMAND = ".venv/bin/python -m pip install 'coverage[toml]>=7.4,<8.0'"

#: First-party code whose coverage is worth a separate line in the report.
#: Frozen WP-01 legacy scripts are deliberately absent: they are a baseline to
#: compare against, not code under development, and including them would move
#: the aggregate without telling anybody anything.
CRITICAL_MODULE_PREFIXES: Tuple[str, ...] = (
    "pgx/domain",
    "pgx/engine",
    "pgx/rules",
    "pgx/reporting",
    "pgx/evidence",
    "pgx/validation",
    "pgx/verification",
    "pgx/application",
    "pgx/ingestion",
    "pgx/normalization",
    "pgx/scientific",
    "pgx/infrastructure",
    "apps/api",
    "apps/web",
)

#: Declared here, before any measurement was taken, so that it cannot be a
#: number chosen after seeing the result. It is the level below which a
#: critical module is *listed for attention*; it is not a gate, because WP-19
#: has never measured this repository and inventing a passing bar for a
#: measurement nobody has taken would be the same error in the other direction.
DECLARED_LINE_THRESHOLD = 80.0


@dataclass(frozen=True)
class CoverageSummary:
    """What coverage was measured, or why none was."""

    status: str                       # "MEASURED" | "BLOCKED"
    tool: str = "coverage.py"
    tool_version: Optional[str] = None
    line_percent: Optional[float] = None
    branch_percent: Optional[float] = None
    covered_lines: Optional[int] = None
    total_lines: Optional[int] = None
    covered_branches: Optional[int] = None
    total_branches: Optional[int] = None
    measured_module_count: Optional[int] = None
    low_coverage_critical_modules: Tuple[Mapping[str, Any], ...] = ()
    excluded: Tuple[str, ...] = ()
    reason: str = ""
    install_command: str = INSTALL_COMMAND
    profile: str = ""

    def as_document(self) -> Dict[str, Any]:
        return {
            "branch_percent": self.branch_percent,
            "covered_branches": self.covered_branches,
            "covered_lines": self.covered_lines,
            "coverage_schema_version": COVERAGE_SCHEMA_VERSION,
            "declared_line_threshold": DECLARED_LINE_THRESHOLD,
            "excluded": list(self.excluded),
            "install_command": self.install_command,
            "line_percent": self.line_percent,
            "low_coverage_critical_modules": [
                dict(item) for item in self.low_coverage_critical_modules],
            "measured_module_count": self.measured_module_count,
            "profile": self.profile,
            "reason": self.reason,
            "status": self.status,
            "tool": self.tool,
            "tool_version": self.tool_version,
            "total_branches": self.total_branches,
            "total_lines": self.total_lines,
        }


def coverage_available() -> bool:
    """Whether ``coverage.py`` can be imported in this interpreter."""
    try:
        import coverage  # noqa: F401
    except ImportError:
        return False
    return True


def coverage_version() -> Optional[str]:
    try:
        import coverage
    except ImportError:
        return None
    return getattr(coverage, "__version__", None)


#: What is excluded from measurement. Read from ``[tool.coverage.run] omit`` in
#: ``pyproject.toml`` rather than restated here, for two reasons. The list has
#: one source of truth, so the artifact cannot describe exclusions the tool is
#: not applying; and this module does not have to spell out legacy data paths,
#: which ``tests/unit/domain/test_dependency_boundaries.py`` correctly refuses
#: to see in a V2 module even inside a comment.
_EXCLUSION_NOTE = (
    "Read from [tool.coverage.run] omit in pyproject.toml. Three groups are "
    "excluded: the test code itself, because measuring it reports how much of "
    "the suite ran and that is already the test result; the frozen WP-01 "
    "baseline scripts and their tooling, because they are a baseline to "
    "compare against rather than code under development; and generated "
    "revision scripts and data artifacts, because they are executed against a "
    "database or are not code at all.")


def omit_patterns(root: str) -> Tuple[str, ...]:
    """The ``omit`` list coverage.py will actually apply.

    Parsed with ``tomllib`` where it exists and with a narrow bracket scanner
    on Python 3.10, which has no standard TOML reader. Returns an empty tuple
    rather than raising if the table is absent: a missing configuration is
    something the artifact should report, not something that should stop a
    coverage summary being produced.
    """
    path = os.path.join(root, "pyproject.toml")
    if not os.path.exists(path):
        return ()
    try:
        import tomllib
    except ImportError:
        tomllib = None
    if tomllib is not None:
        with io.open(path, "rb") as handle:
            document = tomllib.load(handle)
        run = document.get("tool", {}).get("coverage", {}).get("run", {})
        return tuple(str(item) for item in run.get("omit", ()))
    return _scan_omit(path)


def _scan_omit(path: str) -> Tuple[str, ...]:
    """Read one quoted-string array out of ``[tool.coverage.run]``.

    Deliberately narrow: it looks for the table header, then for ``omit = [``,
    then collects quoted strings until the closing bracket. Anything more
    general would be a TOML parser, and this file is not the place for one.
    """
    found: List[str] = []
    in_table = False
    in_array = False
    with io.open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped.startswith("["):
                in_table = stripped.startswith("[tool.coverage.run]")
                continue
            if not in_table:
                continue
            if not in_array:
                if stripped.startswith("omit") and "[" in stripped:
                    in_array = True
                    stripped = stripped.split("[", 1)[1]
                else:
                    continue
            for quoted in re.findall(r'"([^"]*)"', stripped):
                found.append(quoted)
            if "]" in stripped:
                break
    return tuple(found)


def blocked_summary(reason: str, profile: str = "",
                    root: Optional[str] = None) -> CoverageSummary:
    """A summary that measures nothing and says so.

    Every numeric field stays ``None``. This is the function every caller
    reaches when the tool is absent, and the reason it exists as a function is
    so that no caller can construct a partially-filled summary by hand.
    """
    return CoverageSummary(status="BLOCKED", reason=reason,
                           tool_version=coverage_version(), profile=profile,
                           excluded=_excluded(root))


def _excluded(root: Optional[str]) -> Tuple[str, ...]:
    """The note, followed by the patterns the tool will actually apply."""
    patterns = omit_patterns(root) if root else ()
    return (_EXCLUSION_NOTE,) + tuple(patterns)


def measure_coverage(root: str,
                     start_directory: str = "tests",
                     pattern: str = "test_*.py",
                     profile: str = "full",
                     timeout: int = 3600,
                     environ: Optional[Mapping[str, str]] = None
                     ) -> CoverageSummary:
    """Run the suite under ``coverage.py`` and summarise the result.

    Uses the ``coverage`` command line rather than its Python API: the CLI is
    the documented, stable surface, and running it as a subprocess keeps the
    measured process free of this module's own imports.

    Returns a ``BLOCKED`` summary rather than raising when the tool is absent.
    The absence of a measurement is a result the caller must report, not an
    error it should have to catch.
    """
    if not coverage_available():
        return blocked_summary(
            "coverage.py is not importable in this interpreter, so no line or "
            "branch percentage has been measured. It is declared in the dev "
            "dependency group and configured in pyproject.toml; install it "
            "with: %s" % INSTALL_COMMAND, profile, root)

    workspace = tempfile.mkdtemp(prefix="pgx-wp19-coverage-")
    data_file = os.path.join(workspace, ".coverage")
    json_path = os.path.join(workspace, "coverage.json")
    environment = dict(os.environ if environ is None else environ)
    environment["COVERAGE_FILE"] = data_file
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        run = subprocess.run(
            [sys.executable, "-m", "coverage", "run",
             "--rcfile", os.path.join(root, "pyproject.toml"),
             "-m", "unittest", "discover",
             "-s", start_directory, "-p", pattern, "-t", "."],
            cwd=root, env=environment, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=timeout, check=False)
        export = subprocess.run(
            [sys.executable, "-m", "coverage", "json",
             "--rcfile", os.path.join(root, "pyproject.toml"),
             "-o", json_path],
            cwd=root, env=environment, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=600, check=False)
        if not os.path.exists(json_path):
            return blocked_summary(
                "coverage.py is installed but produced no report (run exit %d, "
                "export exit %d). No percentage is reported, because none was "
                "measured." % (run.returncode, export.returncode), profile,
                root)
        with io.open(json_path, "r", encoding="utf-8") as handle:
            document = json.load(handle)
    except subprocess.TimeoutExpired:
        return blocked_summary(
            "the coverage run did not finish within %d seconds; no percentage "
            "is reported" % timeout, profile, root)
    finally:
        shutil.rmtree(workspace, ignore_errors=True)

    return _summarise(document, profile, root)


def _summarise(document: Mapping[str, Any], profile: str,
               root: str) -> CoverageSummary:
    totals = document.get("totals", {})
    files = document.get("files", {})
    low: List[Dict[str, Any]] = []
    for path, entry in sorted(files.items()):
        normalised = path.replace(os.sep, "/")
        if not normalised.startswith(CRITICAL_MODULE_PREFIXES):
            continue
        summary = entry.get("summary", {})
        percent = summary.get("percent_covered")
        if percent is None or percent >= DECLARED_LINE_THRESHOLD:
            continue
        low.append({
            "module": normalised,
            "line_percent": round(float(percent), 2),
            "missing_lines": summary.get("missing_lines"),
            "statements": summary.get("num_statements"),
        })

    line_percent = totals.get("percent_covered")
    branch_percent = None
    if totals.get("num_branches"):
        covered = totals.get("covered_branches") or 0
        branch_percent = round(
            100.0 * float(covered) / float(totals["num_branches"]), 2)

    return CoverageSummary(
        status="MEASURED",
        tool_version=coverage_version(),
        line_percent=(None if line_percent is None
                      else round(float(line_percent), 2)),
        branch_percent=branch_percent,
        covered_lines=totals.get("covered_lines"),
        total_lines=totals.get("num_statements"),
        covered_branches=totals.get("covered_branches"),
        total_branches=totals.get("num_branches"),
        measured_module_count=len(files),
        low_coverage_critical_modules=tuple(low),
        excluded=_excluded(root),
        reason="",
        profile=profile,
    )
