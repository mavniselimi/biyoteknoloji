# -*- coding: utf-8 -*-
"""The process that actually runs tests, and reports exactly what happened.

Run as ``python -m pgx.verification._worker <plan.json> <report.json>``, always
in its own interpreter. Isolation is not tidiness: the suite imports two
hundred modules, several of which install module-level state, and a profile
that ran after another profile in the same process would be measuring the
second one's leftovers. It also means a test that segfaults or calls
``sys.exit`` takes the worker down and not the verifier.

Three things this module is careful about.

**Every planned test is accounted for.** ``unittest`` reports a failing
``setUpClass`` as one skip, and the tests in that class are simply never seen.
Sixteen such skips currently hide seventy-seven PostgreSQL tests. The worker
records the class-level skip *and* attributes it to every planned test inside
that class, so ``discovered`` and ``executed`` differ by a number somebody can
explain.

**The report is a file, not stdout.** Several negative tests deliberately print
``CONFIGURATION_FAILURE`` while passing. Anything that parsed stdout for words
would read those as failures. The report is written to a path given on the
command line and stdout is left free to contain whatever the suite prints.

**Durations are not recorded.** They are the one field guaranteed to differ
between two runs of the same thing, and every deterministic comparison here
would have to strip them. Not writing them down is simpler than remembering to.
"""

from __future__ import annotations

import io
import json
import os
import sys
import time
import unittest
from typing import Any, Dict, List, Optional, Tuple

# The worker is started as ``python -m``, so the repository root is already on
# sys.path. Imports below must not assume an installed package.
from pgx.verification.offline import (  # noqa: E402
    install_offline_guard,
    remove_offline_guard,
)

#: Exit codes describe the *worker*, never the tests. A worker that ran a suite
#: in which everything failed exits 0, because it did its job; the outcome is
#: in the report. Only a worker that could not produce a report exits non-zero.
EXIT_OK = 0
EXIT_NO_REPORT = 70


class _RecordingResult(unittest.TestResult):
    """A result that remembers every outcome by test identifier."""

    def __init__(self) -> None:
        super().__init__()
        self.outcomes: Dict[str, Tuple[str, str]] = {}
        #: ``setUpClass``/``setUpModule`` skips, as ``(prefix, reason)``.
        self.class_skips: List[Tuple[str, str]] = []
        self.subtest_failures: Dict[str, int] = {}

    # -- individual outcomes --------------------------------------------
    def addSuccess(self, test: unittest.TestCase) -> None:
        super().addSuccess(test)
        self._record(test, "PASS", "")

    def addFailure(self, test: unittest.TestCase, err: Any) -> None:
        super().addFailure(test, err)
        self._record(test, "FAIL", _first_line(err))

    def addError(self, test: unittest.TestCase, err: Any) -> None:
        super().addError(test, err)
        identifier = _identifier(test)
        prefix = _class_prefix(identifier)
        if prefix is not None:
            # An error raised in setUpClass or setUpModule. Attribute it to
            # every test underneath rather than losing them.
            self.class_skips.append((prefix, "ERROR: " + _first_line(err)))
            return
        self._record(test, "ERROR", _first_line(err))

    def addSkip(self, test: unittest.TestCase, reason: str) -> None:
        super().addSkip(test, reason)
        identifier = _identifier(test)
        prefix = _class_prefix(identifier)
        if prefix is not None:
            self.class_skips.append((prefix, reason))
            return
        self._record(test, "SKIP", reason)

    def addExpectedFailure(self, test: unittest.TestCase, err: Any) -> None:
        super().addExpectedFailure(test, err)
        # An expected failure is a test doing what it says. It passes.
        self._record(test, "PASS", "expected failure")

    def addUnexpectedSuccess(self, test: unittest.TestCase) -> None:
        super().addUnexpectedSuccess(test)
        self._record(test, "FAIL", "unexpectedly succeeded")

    def addSubTest(self, test: unittest.TestCase, subtest: Any,
                   err: Any) -> None:
        super().addSubTest(test, subtest, err)
        if err is None:
            return
        identifier = _identifier(test)
        self.subtest_failures[identifier] = (
            self.subtest_failures.get(identifier, 0) + 1)
        kind = ("ERROR" if err[0] is not None
                and not issubclass(err[0], test.failureException) else "FAIL")
        self.outcomes[identifier] = (kind, _first_line(err))

    # -- helpers ---------------------------------------------------------
    def _record(self, test: unittest.TestCase, outcome: str,
                reason: str) -> None:
        identifier = _identifier(test)
        existing = self.outcomes.get(identifier)
        # A subtest failure already recorded must not be overwritten by the
        # parent's success: unittest calls addSuccess for a test whose subtests
        # failed only in some versions, and a silent upgrade to PASS would be
        # the worst possible bug in this file.
        if existing is not None and existing[0] in ("FAIL", "ERROR"):
            return
        self.outcomes[identifier] = (outcome, reason)


def _identifier(test: Any) -> str:
    try:
        return test.id()
    except Exception:  # pragma: no cover - defensive
        return str(test)


def _class_prefix(identifier: str) -> Optional[str]:
    """``tests.mod.Class.`` when ``identifier`` is a class-level pseudo-test.

    unittest names these ``setUpClass (tests.mod.Class)`` and
    ``setUpModule (tests.mod)``. Recognising the shape is how the tests hidden
    behind one of them get counted.
    """
    for marker in ("setUpClass (", "setUpModule (", "tearDownClass (",
                   "tearDownModule ("):
        if identifier.startswith(marker) and identifier.endswith(")"):
            return identifier[len(marker):-1] + "."
    return None


def _first_line(err: Any) -> str:
    """A one-line reason from an ``exc_info`` triple or a string."""
    if err is None:
        return ""
    if isinstance(err, str):
        return err.strip().splitlines()[0] if err.strip() else ""
    try:
        exc_type, exc_value = err[0], err[1]
    except (TypeError, IndexError):  # pragma: no cover - defensive
        return str(err)
    text = str(exc_value).strip()
    first = text.splitlines()[0] if text else ""
    name = getattr(exc_type, "__name__", str(exc_type))
    return ("%s: %s" % (name, first)) if first else name


def _load(plan: Dict[str, Any], root: str) -> Tuple[unittest.TestSuite,
                                                    List[str]]:
    """Build the suite this plan describes, and the ids it expected."""
    loader = unittest.TestLoader()
    if plan.get("mode") == "discover":
        start = os.path.join(root, *plan.get("start", "tests").split("/"))
        suite = loader.discover(start,
                                pattern=plan.get("pattern", "test_*.py"),
                                top_level_dir=root)
        from pgx.verification.discovery import flatten
        planned = sorted(case.id() for case in flatten(suite))
        return suite, planned
    identifiers = list(plan.get("ids", ()))
    suite = loader.loadTestsFromNames(identifiers)
    return suite, sorted(identifiers)


def run_plan(plan: Dict[str, Any], root: str) -> Dict[str, Any]:
    """Execute ``plan`` and return the report document."""
    offline = bool(plan.get("offline", True))
    if offline:
        install_offline_guard()
    stream = io.StringIO()
    try:
        suite, planned = _load(plan, root)
        result = _RecordingResult()
        started = time.time()
        runner = unittest.TextTestRunner(stream=stream, verbosity=0,
                                         resultclass=lambda *a, **k: result)
        runner.run(suite)
        elapsed = time.time() - started
    finally:
        if offline:
            remove_offline_guard()

    outcomes = dict(result.outcomes)
    # Attribute class-level skips and errors to the tests they suppressed.
    hidden: Dict[str, Tuple[str, str]] = {}
    for prefix, reason in result.class_skips:
        kind = "ERROR" if reason.startswith("ERROR: ") else "SKIP"
        for identifier in planned:
            if identifier.startswith(prefix) and identifier not in outcomes:
                hidden[identifier] = (kind, reason)
    outcomes.update(hidden)

    not_executed = [identifier for identifier in planned
                    if identifier not in outcomes]
    return {
        "class_level_skips": sorted(
            {"%s%s" % (prefix, "") for prefix, _ in result.class_skips}),
        # Rounded to whole seconds and kept out of every hash: reported so a
        # person can see a run got slower, never compared for determinism.
        "elapsed_seconds_approximate": int(elapsed),
        "not_executed": sorted(not_executed),
        "outcomes": {identifier: {"outcome": outcome, "reason": reason}
                     for identifier, (outcome, reason)
                     in sorted(outcomes.items())},
        "planned": planned,
        "planned_count": len(planned),
        "runner_tests_run": result.testsRun,
        "subtest_failure_counts": dict(sorted(result.subtest_failures.items())),
        "worker_schema_version": "pgx-wp19-worker-report/1",
    }


def main(argv: Optional[List[str]] = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 3:
        sys.stderr.write("usage: python -m pgx.verification._worker "
                         "<root> <plan.json> <report.json>\n")
        return EXIT_NO_REPORT
    root, plan_path, report_path = arguments
    with io.open(plan_path, "r", encoding="utf-8") as handle:
        plan = json.load(handle)
    report = run_plan(plan, root)
    rendered = json.dumps(report, indent=2, sort_keys=True,
                          ensure_ascii=True) + "\n"
    with io.open(report_path, "w", encoding="utf-8") as handle:
        handle.write(rendered)
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover - a subprocess entry point
    sys.exit(main())
