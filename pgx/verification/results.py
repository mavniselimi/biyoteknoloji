# -*- coding: utf-8 -*-
"""Turning a worker report into a result nothing can round up.

This is where the five outcomes are kept apart. Everything else in the package
either produces raw observations or renders them; this module is the one place
that decides what a set of observations *means*, and it is written so that
every way of getting a green light has to be earned.

Four rules, each of which exists because the opposite is the easy mistake:

**A skip is not a pass.** Every skip is classified against the inventory's
declared policy for that test. A test declared ``NEVER`` that skips is
``UNEXPLAINED``. A test that skips for a reason its policy does not name is
``UNEXPLAINED`` too - "PostgreSQL is missing" does not excuse a browser test.
Any unexplained skip fails the profile.

**Zero is not a pass.** A profile that executed nothing, or fewer tests than it
declared as a floor, is an ERROR. This is the cheapest false green there is: a
selector stops matching and the profile goes green in two seconds.

**BLOCKED is not FAIL, and neither is PASS.** A category whose tests all
skipped for a declared environment reason is ``BLOCKED``: nothing is wrong with
the software and nothing was verified either. Rendering that as FAIL would make
every machine without PostgreSQL look broken; rendering it as PASS would be a
lie.

**stdout is not a result.** Several negative tests print
``CONFIGURATION_FAILURE`` while passing. The outcome of a test is what the test
runner recorded, never a word found in the output. That sentence is repeated in
the artifacts so a later CI does not reinvent the mistake.
"""

from __future__ import annotations

from typing import Dict, List, Mapping, Optional, Tuple

from pgx.verification.inventory import Inventory
from pgx.verification.model import (
    Category,
    Outcome,
    ProfileResult,
    SkipClassification,
    SkipPolicy,
    SuiteSummary,
    TestEntry,
    TestOutcome,
    worst_outcome,
)
from pgx.verification.profiles import Profile
from pgx.verification.runner import WorkerReport

__all__ = [
    "KNOWN_STDOUT_MARKERS",
    "STDOUT_IS_NOT_A_RESULT",
    "classify_skip",
    "build_profile_result",
    "category_outcomes",
    "result_signature",
]

#: Strings the suite prints on purpose while passing. Listed so that a later CI
#: has a written reason not to grep for them, not so that anything here reacts
#: to them: nothing in this module reads worker stdout to decide an outcome.
KNOWN_STDOUT_MARKERS: Tuple[str, ...] = (
    "CONFIGURATION_FAILURE",
)

STDOUT_IS_NOT_A_RESULT = (
    "Test outcomes come from the test runner's recorded result, never from "
    "words found in stdout. Several negative tests print CONFIGURATION_FAILURE "
    "on purpose while passing; a CI job that grepped for it would fail a green "
    "suite.")

_OUTCOME_BY_NAME = {
    "PASS": Outcome.PASS,
    "FAIL": Outcome.FAIL,
    "ERROR": Outcome.ERROR,
    "SKIP": Outcome.SKIP,
}

#: Issue codes. Stable and controlled: a CI job keys on these, and a reworded
#: sentence must never change what a job decides.
ISSUE_NO_TESTS_EXECUTED = "VERIFY_NO_TESTS_EXECUTED"
ISSUE_BELOW_MINIMUM = "VERIFY_BELOW_DECLARED_MINIMUM"
ISSUE_UNEXPLAINED_SKIP = "VERIFY_UNEXPLAINED_SKIP"
ISSUE_FAILURES = "VERIFY_TEST_FAILURES"
ISSUE_ERRORS = "VERIFY_TEST_ERRORS"
ISSUE_UNPLANNED_RESULT = "VERIFY_UNPLANNED_RESULT"
ISSUE_MISSING_RESULT = "VERIFY_PLANNED_TEST_HAS_NO_RESULT"
ISSUE_COUNT_DISAGREEMENT = "VERIFY_RUNNER_COUNT_DISAGREES"
#: At least one category in this profile executed only skips. The profile
#: may still be PASS - nothing failed - and the category is still BLOCKED.
ISSUE_CATEGORY_BLOCKED = "VERIFY_CATEGORY_BLOCKED"


def classify_skip(entry: Optional[TestEntry],
                  reason: str) -> SkipClassification:
    """Whether ``reason`` is a skip this test was allowed to make.

    A test with no inventory entry is ``UNEXPLAINED``: an unknown test that
    skipped is exactly the case where the benefit of the doubt is wrong.
    """
    if entry is None:
        return SkipClassification.UNEXPLAINED
    if entry.skip_policy is SkipPolicy.NEVER:
        return SkipClassification.UNEXPLAINED
    permitted = [text.strip().lower()
                 for text in entry.permitted_skip_reasons if text.strip()]
    if not permitted:
        return SkipClassification.UNEXPLAINED
    observed = reason.lower()
    return (SkipClassification.ALLOWED
            if any(text in observed for text in permitted)
            else SkipClassification.UNEXPLAINED)


def build_profile_result(profile: Profile,
                         report: WorkerReport,
                         inventory: Inventory,
                         discovered: int) -> ProfileResult:
    """Read one worker report as a result, applying every rule above."""
    entries = inventory.by_id()
    outcomes: List[TestOutcome] = []
    issues: List[str] = []

    planned = set(report.planned)
    passed = failed = errored = skipped = unexplained = 0

    for identifier, record in sorted(report.outcomes.items()):
        raw = str(record.get("outcome", ""))
        reason = str(record.get("reason", ""))
        outcome = _OUTCOME_BY_NAME.get(raw)
        if outcome is None:
            # An outcome name the worker should never emit. Treated as an
            # error rather than ignored: an unreadable result is not a pass.
            outcome = Outcome.ERROR
            reason = "unrecognised worker outcome %r: %s" % (raw, reason)
        classification: Optional[SkipClassification] = None
        if outcome is Outcome.PASS:
            passed += 1
        elif outcome is Outcome.FAIL:
            failed += 1
        elif outcome is Outcome.ERROR:
            errored += 1
        else:
            skipped += 1
            classification = classify_skip(entries.get(identifier), reason)
            if classification is SkipClassification.UNEXPLAINED:
                unexplained += 1
        if identifier not in planned:
            issues.append(ISSUE_UNPLANNED_RESULT)
        outcomes.append(TestOutcome(identifier, outcome, reason,
                                    classification))

    executed = passed + failed + errored + skipped
    not_executed = len(report.not_executed)

    summary = SuiteSummary(
        discovered=discovered,
        executed=executed,
        passed=passed,
        failed=failed,
        errored=errored,
        skipped=skipped,
        unexplained_skips=unexplained,
        not_executed=not_executed,
    )

    if executed == 0:
        issues.append(ISSUE_NO_TESTS_EXECUTED)
    if executed < profile.minimum_tests:
        issues.append(ISSUE_BELOW_MINIMUM)
    if unexplained:
        issues.append(ISSUE_UNEXPLAINED_SKIP)
    if failed:
        issues.append(ISSUE_FAILURES)
    if errored:
        issues.append(ISSUE_ERRORS)
    if not_executed:
        issues.append(ISSUE_MISSING_RESULT)

    outcome = _profile_outcome(summary, issues)
    blocked_reason = ""
    if outcome is Outcome.BLOCKED:
        blocked_reason = _blocked_reason(outcomes)

    provisional = ProfileResult(
        profile=profile.name,
        outcome=outcome,
        summary=summary,
        outcomes=tuple(outcomes),
        blocked_reason=blocked_reason,
        issue_codes=tuple(sorted(set(issues))),
        stdout_note=STDOUT_IS_NOT_A_RESULT,
    )
    categories = {category.value: info
                  for category, info in category_outcomes(provisional,
                                                          inventory).items()
                  if info["executed"]}
    if any(info["outcome"] == Outcome.BLOCKED.value
           for info in categories.values()):
        issues.append(ISSUE_CATEGORY_BLOCKED)

    return ProfileResult(
        profile=profile.name,
        outcome=outcome,
        summary=summary,
        outcomes=tuple(outcomes),
        blocked_reason=blocked_reason,
        issue_codes=tuple(sorted(set(issues))),
        stdout_note=STDOUT_IS_NOT_A_RESULT,
        categories=categories,
    )


def _profile_outcome(summary: SuiteSummary, issues: List[str]) -> Outcome:
    """The single word for a profile, chosen without ranking anything.

    Order is explicit and each step is a separate sentence:

    * anything errored, or a planned test produced no result -> ERROR
    * anything failed, or a skip was unexplained -> FAIL
    * nothing ran, or fewer ran than declared -> ERROR
    * everything that ran skipped for a declared reason -> BLOCKED
    * otherwise -> PASS
    """
    if summary.errored or ISSUE_MISSING_RESULT in issues:
        return Outcome.ERROR
    if summary.failed or summary.unexplained_skips:
        return Outcome.FAIL
    if summary.executed == 0 or ISSUE_BELOW_MINIMUM in issues:
        return Outcome.ERROR
    if summary.passed == 0 and summary.skipped == summary.executed:
        return Outcome.BLOCKED
    return Outcome.PASS


def _blocked_reason(outcomes: List[TestOutcome]) -> str:
    reasons = sorted({item.reason for item in outcomes
                      if item.outcome is Outcome.SKIP and item.reason})
    if not reasons:
        return "every test skipped, and none said why"
    return reasons[0]


def category_outcomes(result: ProfileResult,
                      inventory: Inventory
                      ) -> Dict[Category, Dict[str, object]]:
    """Per-category outcomes for one run.

    A category with no test in this profile reports ``MISSING`` rather than
    being omitted: a table with a missing row reads as a table that forgot
    something, and a table with a MISSING cell reads as a finding.
    """
    entries = inventory.by_id()
    buckets: Dict[Category, List[TestOutcome]] = {}
    for item in result.outcomes:
        entry = entries.get(item.test_id)
        if entry is None:
            continue
        buckets.setdefault(entry.category, []).append(item)

    found: Dict[Category, Dict[str, object]] = {}
    for category in Category:
        items = buckets.get(category, [])
        if not items:
            found[category] = {
                "outcome": Outcome.MISSING.value,
                "executed": 0, "passed": 0, "failed": 0,
                "errored": 0, "skipped": 0,
                "reason": "no test in this profile belongs to this category",
            }
            continue
        passed = sum(1 for i in items if i.outcome is Outcome.PASS)
        failed = sum(1 for i in items if i.outcome is Outcome.FAIL)
        errored = sum(1 for i in items if i.outcome is Outcome.ERROR)
        skipped = sum(1 for i in items if i.outcome is Outcome.SKIP)
        unexplained = sum(
            1 for i in items
            if i.skip_classification is SkipClassification.UNEXPLAINED)
        if errored:
            outcome = Outcome.ERROR
        elif failed or unexplained:
            outcome = Outcome.FAIL
        elif passed == 0 and skipped:
            outcome = Outcome.BLOCKED
        elif passed == 0:
            outcome = Outcome.MISSING
        else:
            outcome = Outcome.PASS
        found[category] = {
            "outcome": outcome.value,
            "executed": len(items), "passed": passed, "failed": failed,
            "errored": errored, "skipped": skipped,
            "reason": ("" if outcome is not Outcome.BLOCKED
                       else _blocked_reason(items)),
        }
    return found


def result_signature(result: ProfileResult) -> Dict[str, str]:
    """The part of a result that must be identical between two runs.

    Test identifier to outcome, and nothing else. No durations, no timestamps,
    no counts derived from them, and no skip *reasons* - a reason can name a
    package version and would make an otherwise identical pair of runs look
    different. What must not change is which test did what.
    """
    return {item.test_id: item.outcome.value for item in result.outcomes}
