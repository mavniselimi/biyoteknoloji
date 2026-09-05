# -*- coding: utf-8 -*-
"""Running a profile in its own interpreter, and reading back what happened.

The runner never runs a test in this process. It writes a plan, starts
``pgx.verification._worker`` with ``sys.executable``, waits, and reads the
report file. Everything the verifier concludes comes from that file.

``sys.executable`` rather than ``python``: the interpreter that imported this
module is the one whose environment was verified, and picking up whatever
``python`` happens to mean on ``PATH`` is how a run ends up measuring a
different installation than the one being released.

The environment the worker gets is deliberate:

- ``PYTHONHASHSEED`` is fixed and recorded. Set after the interpreter starts it
  does nothing, so it goes in the environment.
- ``PYTHONDONTWRITEBYTECODE`` is on, so a repeated run cannot be faster because
  the first one left ``__pycache__`` behind - and cannot differ because of it.
- ``PYTHONWARNINGS`` turns ``ResourceWarning`` into an error, matching the
  documented command. A leaked file handle is a defect the suite already
  catches, and a profile that did not catch it would disagree with the command
  in the documentation.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from pgx.verification.errors import ResultParseError, RunnerError
from pgx.verification.inventory import Inventory
from pgx.verification.model import Category, Criticality
from pgx.verification.profiles import Profile

__all__ = [
    "DEFAULT_HASH_SEED",
    "WorkerReport",
    "select_test_ids",
    "run_profile_once",
    "run_profile",
    "worker_environment",
]

#: Fixed, recorded, and reported beside every result. Not zero, because zero
#: disables randomisation entirely and would hide a genuine ordering
#: dependency; a fixed non-zero seed keeps hashing randomised but identical
#: between runs, which is what makes a difference between runs meaningful.
DEFAULT_HASH_SEED = "20260904"

#: How long a single worker may take. The full suite runs in about four
#: minutes; twenty is generous enough that a slow machine is not a failure and
#: short enough that a hung run is not an overnight wait.
DEFAULT_TIMEOUT_SECONDS = 1800


@dataclass(frozen=True)
class WorkerReport:
    """One worker's report, as read back from its file."""

    outcomes: Mapping[str, Mapping[str, str]]
    planned: Tuple[str, ...]
    not_executed: Tuple[str, ...]
    runner_tests_run: int
    elapsed_seconds_approximate: int
    subtest_failure_counts: Mapping[str, int]
    stdout: str
    stderr: str
    exit_code: int

    @property
    def planned_count(self) -> int:
        return len(self.planned)


def select_test_ids(profile: Profile, inventory: Inventory) -> Tuple[str, ...]:
    """The test identifiers this profile selects, sorted.

    Filters are applied in a fixed order - categories, then exclusions, then
    modules, then criticality - so two callers cannot disagree about what a
    profile means.
    """
    entries = list(inventory.entries)
    if profile.categories:
        wanted = set(profile.categories)
        entries = [entry for entry in entries if entry.category in wanted]
    if profile.exclude_categories:
        unwanted = set(profile.exclude_categories)
        entries = [entry for entry in entries
                   if entry.category not in unwanted]
    if profile.modules:
        entries = [entry for entry in entries
                   if _module_selected(entry.module, profile.modules)]
    if profile.criticality is not None:
        entries = [entry for entry in entries
                   if entry.criticality is profile.criticality]
    return tuple(sorted(entry.test_id for entry in entries))


def _module_selected(module: str, selectors: Sequence[str]) -> bool:
    for selector in selectors:
        if module == selector or module.startswith(selector + "."):
            return True
    return False


def worker_environment(hash_seed: str = DEFAULT_HASH_SEED,
                       base: Optional[Mapping[str, str]] = None
                       ) -> Dict[str, str]:
    """The environment a worker runs in. Explicit, so a run is reproducible.

    ``TEST_DATABASE_URL`` is passed through untouched when it is set. WP-19
    never invents one, never points a suite at a database of its own choosing,
    and never starts or stops a server: the database tests decide for
    themselves whether what they were given is disposable, and refusing to
    forward the variable would only replace their careful check with a skip.
    """
    environment = dict(os.environ if base is None else base)
    environment["PYTHONHASHSEED"] = hash_seed
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONWARNINGS"] = "error::ResourceWarning"
    return environment


def run_profile_once(profile: Profile,
                     inventory: Inventory,
                     root: str,
                     hash_seed: str = DEFAULT_HASH_SEED,
                     timeout: int = DEFAULT_TIMEOUT_SECONDS,
                     environ: Optional[Mapping[str, str]] = None
                     ) -> WorkerReport:
    """Run ``profile`` in one fresh interpreter and read back its report."""
    workspace = tempfile.mkdtemp(prefix="pgx-wp19-run-")
    plan_path = os.path.join(workspace, "plan.json")
    report_path = os.path.join(workspace, "report.json")
    try:
        plan: Dict[str, Any] = {"offline": profile.offline}
        if profile.discover:
            plan.update({"mode": "discover", "start": "tests",
                         "pattern": "test_*.py"})
        else:
            plan.update({"mode": "ids",
                         "ids": list(select_test_ids(profile, inventory))})
        with io.open(plan_path, "w", encoding="utf-8") as handle:
            json.dump(plan, handle)

        completed = subprocess.run(
            [sys.executable, "-m", "pgx.verification._worker",
             root, plan_path, report_path],
            cwd=root,
            env=worker_environment(hash_seed, environ),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=timeout, check=False)

        if not os.path.exists(report_path):
            raise RunnerError(
                "the verification worker for profile %r wrote no report "
                "(exit %d). Nothing can be concluded about those tests; this "
                "is not a failing result, it is an absent one. stderr: %s"
                % (profile.name, completed.returncode,
                   _tail(completed.stderr)))
        with io.open(report_path, "r", encoding="utf-8") as handle:
            try:
                document = json.load(handle)
            except ValueError as exc:
                raise ResultParseError(
                    "the worker report for profile %r is not readable JSON: %s"
                    % (profile.name, exc)) from exc
        return WorkerReport(
            outcomes=document.get("outcomes", {}),
            planned=tuple(document.get("planned", ())),
            not_executed=tuple(document.get("not_executed", ())),
            runner_tests_run=int(document.get("runner_tests_run", 0)),
            elapsed_seconds_approximate=int(
                document.get("elapsed_seconds_approximate", 0)),
            subtest_failure_counts=document.get("subtest_failure_counts", {}),
            stdout=_tail(completed.stdout),
            stderr=_tail(completed.stderr),
            exit_code=completed.returncode,
        )
    except subprocess.TimeoutExpired as exc:
        raise RunnerError(
            "the verification worker for profile %r did not finish within %d "
            "seconds" % (profile.name, timeout)) from exc
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def run_profile(profile: Profile,
                inventory: Inventory,
                root: str,
                hash_seed: str = DEFAULT_HASH_SEED,
                timeout: int = DEFAULT_TIMEOUT_SECONDS,
                environ: Optional[Mapping[str, str]] = None
                ) -> Tuple[WorkerReport, ...]:
    """Run ``profile`` as many times as it declares, each in a fresh process.

    Every repetition is recorded, including the ones that agreed. A report that
    kept only the differences could not distinguish "ran three times, identical"
    from "ran once".
    """
    reports: List[WorkerReport] = []
    for _ in range(max(1, profile.repeats)):
        reports.append(run_profile_once(profile, inventory, root, hash_seed,
                                        timeout, environ))
    return tuple(reports)


def _tail(raw: Optional[bytes], limit: int = 4000) -> str:
    """The last of a stream, decoded leniently.

    Bounded because a suite that printed a megabyte would otherwise put it in
    an artifact. Kept at all because a worker that died has its reason here.
    """
    if not raw:
        return ""
    text = raw.decode("utf-8", "replace")
    return text if len(text) <= limit else "...(truncated)...\n" + text[-limit:]
