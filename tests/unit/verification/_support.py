# -*- coding: utf-8 -*-
"""Shared scaffolding for the WP-19 tests.

Two things live here: the repository root, resolved once, and small builders
for the records the verification system passes around. The builders exist so a
test that is about *one* property - an unexplained skip, a zero-test run - can
say so in three lines instead of assembling a full worker report by hand.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Mapping, Optional, Sequence

from pgx.verification.inventory import Inventory
from pgx.verification.model import (
    Category,
    Criticality,
    SkipPolicy,
    TestEntry,
)
from pgx.verification.profiles import Profile
from pgx.verification.runner import WorkerReport

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))


def entry(test_id: str,
          category: Category = Category.UNIT,
          criticality: Criticality = Criticality.SUPPORTING,
          skip_policy: SkipPolicy = SkipPolicy.NEVER,
          permitted: Sequence[str] = (),
          requirements: Sequence[str] = ()) -> TestEntry:
    """One inventory entry, with everything but the point defaulted."""
    return TestEntry(
        test_id=test_id,
        module=test_id.rsplit(".", 2)[0],
        category=category,
        work_package="WP-TEST",
        criticality=criticality,
        requirements=tuple(requirements),
        command="python -m unittest %s" % test_id,
        skip_policy=skip_policy,
        permitted_skip_reasons=tuple(permitted),
        assigned_by="test-fixture",
    )


def inventory(*entries: TestEntry) -> Inventory:
    return Inventory(tuple(entries), (), ())


def report(outcomes: Mapping[str, Mapping[str, str]],
           planned: Optional[Sequence[str]] = None,
           not_executed: Sequence[str] = (),
           runner_tests_run: Optional[int] = None) -> WorkerReport:
    """A worker report, as if a subprocess had produced one."""
    names = list(planned if planned is not None else sorted(outcomes))
    return WorkerReport(
        outcomes=dict(outcomes),
        planned=tuple(names),
        not_executed=tuple(not_executed),
        runner_tests_run=(len(outcomes) if runner_tests_run is None
                          else runner_tests_run),
        elapsed_seconds_approximate=0,
        subtest_failure_counts={},
        stdout="", stderr="", exit_code=0)


def profile(name: str = "test-profile", minimum: int = 1,
            **kwargs: Any) -> Profile:
    return Profile(name=name, description="a profile for one test",
                   minimum_tests=minimum, **kwargs)
