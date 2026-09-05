# -*- coding: utf-8 -*-
"""Comparing repeated runs of the same thing.

A flaky test is one that does not agree with itself. Finding them needs
repetition, and repetition is expensive, so the design is bounded on purpose:
a documented critical subset (``profiles.FLAKY_SUBSET_MODULES``), three runs,
each in a fresh interpreter with the same recorded hash seed.

The comparison is over ``{test id: outcome}`` and nothing else. Durations
differ between runs by definition; skip reasons can name a package version;
timestamps are timestamps. Comparing any of those would report a stable suite
as unstable, which trains people to ignore the report.

One rule, stated because the tempting alternative is common and wrong:

    **A test that passes twice and fails once is FLAKY, not a majority pass.**

Majority voting on test results is how an intermittent failure becomes
invisible. Here, any test whose outcome is not identical across every
repetition is reported by name, with the outcome it produced each time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from pgx.verification.model import Outcome, ProfileResult
from pgx.verification.results import result_signature

__all__ = [
    "FLAKY_SCHEMA_VERSION",
    "FlakyTest",
    "FlakyReport",
    "compare_runs",
]

FLAKY_SCHEMA_VERSION = "pgx-wp19-flaky-report/1"


@dataclass(frozen=True)
class FlakyTest:
    """One test that did not agree with itself."""

    test_id: str
    outcomes: Tuple[str, ...]

    def as_document(self) -> Dict[str, Any]:
        return {
            "distinct_outcomes": sorted(set(self.outcomes)),
            "outcomes_by_repetition": list(self.outcomes),
            "test_id": self.test_id,
        }


@dataclass(frozen=True)
class FlakyReport:
    """What repeating a profile showed."""

    profile: str
    repetitions: int
    #: Tests whose outcome differed between repetitions.
    flaky: Tuple[FlakyTest, ...]
    #: Tests present in some repetitions and absent from others. A different
    #: fault from flakiness - the selection itself moved - and reported apart
    #: so the two are never confused.
    unstable_selection: Tuple[str, ...]
    #: Per-repetition counts, so "ran three times" is visible rather than
    #: implied by the absence of differences.
    counts_by_repetition: Tuple[Mapping[str, int], ...]
    hash_seed: str
    status: str            # "STABLE" | "FLAKY" | "BLOCKED"
    note: str = ""

    @property
    def is_stable(self) -> bool:
        return not self.flaky and not self.unstable_selection

    def as_document(self) -> Dict[str, Any]:
        return {
            "counts_by_repetition": [dict(item)
                                     for item in self.counts_by_repetition],
            "flaky_schema_version": FLAKY_SCHEMA_VERSION,
            "flaky_test_count": len(self.flaky),
            "flaky_tests": [item.as_document() for item in self.flaky],
            "hash_seed": self.hash_seed,
            "is_stable": self.is_stable,
            "note": self.note,
            "profile": self.profile,
            "repetitions": self.repetitions,
            "status": self.status,
            "unstable_selection": list(self.unstable_selection),
        }


#: Repeated into the artifact so a reader does not have to trust that majority
#: voting was avoided; they can see that it was.
NO_MAJORITY_VOTE = (
    "A test whose outcome differed between repetitions is reported as flaky, "
    "with the outcome it produced in each run. No majority vote is taken: two "
    "passes and one failure is a failure that happens sometimes, which is the "
    "thing worth knowing.")


def compare_runs(profile: str,
                 results: Sequence[ProfileResult],
                 hash_seed: str) -> FlakyReport:
    """Compare the signatures of repeated runs of one profile.

    Fewer than two results is ``BLOCKED``: one run cannot show instability, and
    reporting a single run as ``STABLE`` would be a claim nothing supports.
    """
    if len(results) < 2:
        return FlakyReport(
            profile=profile, repetitions=len(results), flaky=(),
            unstable_selection=(),
            counts_by_repetition=tuple(
                _counts(result) for result in results),
            hash_seed=hash_seed, status="BLOCKED",
            note="fewer than two repetitions were run, so nothing can be said "
                 "about stability; a single run is not evidence of it")

    signatures = [result_signature(result) for result in results]
    every_id: List[str] = sorted({identifier
                                  for signature in signatures
                                  for identifier in signature})

    flaky: List[FlakyTest] = []
    unstable: List[str] = []
    for identifier in every_id:
        seen = [signature.get(identifier) for signature in signatures]
        if any(value is None for value in seen):
            unstable.append(identifier)
            continue
        if len(set(seen)) > 1:
            flaky.append(FlakyTest(identifier,
                                   tuple(str(value) for value in seen)))

    status = "STABLE" if not flaky and not unstable else "FLAKY"
    return FlakyReport(
        profile=profile,
        repetitions=len(results),
        flaky=tuple(flaky),
        unstable_selection=tuple(unstable),
        counts_by_repetition=tuple(_counts(result) for result in results),
        hash_seed=hash_seed,
        status=status,
        note=NO_MAJORITY_VOTE,
    )


def _counts(result: ProfileResult) -> Dict[str, int]:
    document = result.summary.as_document()
    return {key: int(value) for key, value in sorted(document.items())}
