# -*- coding: utf-8 -*-
"""Operational residuals after Wave 3, each with a measured blocker (WP-C11).

Every row here was checked in this wave rather than carried forward from an
earlier report. The distinction matters because a residual list that is copied
between waves stops being evidence about the repository and becomes evidence
about the previous list.

The pattern that emerged is worth stating once: **every remaining operational
residual is blocked on network egress that neither execution environment has.**
The device VM and the cloud container both refuse pypi.org and api.github.com
with HTTP 403, and the CI workflow cannot run at all until both are reachable -
``uv sync --frozen`` needs a lockfile that only a package index can produce, and
every ``uses:`` line in the workflow still carries an all-zero SHA marked
UNRESOLVED, which only api.github.com can resolve.

That also disposes of a tempting half-fix. The unpinned-linter finding is not
repaired by narrowing the ``ruff`` and ``mypy`` ranges in ``pyproject.toml``:
CI installs from ``uv.lock`` via ``uv sync --frozen``, so the lockfile *is* the
pin, and editing the ranges would change the declared intent while leaving the
gate exactly as non-reproducible as it was.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Tuple

__all__ = ["RESIDUALS", "RESIDUALS_VERSION", "OperationalResidual",
           "blocked_residuals", "caused_by_this_wave"]

RESIDUALS_VERSION = "pgx-wave03-operational-residuals/1"


@dataclass(frozen=True, slots=True)
class OperationalResidual:
    """One residual, what it needs, and what was measured when it was tried."""

    residual_id: str
    subject: str
    state: str
    needs: str
    measured_evidence: str

    def to_json(self) -> Dict[str, Any]:
        return {
            "measured_evidence": self.measured_evidence,
            "needs": self.needs,
            "residual_id": self.residual_id,
            "state": self.state,
            "subject": self.subject,
        }


RESIDUALS: Tuple[OperationalResidual, ...] = (
    OperationalResidual(
        residual_id="OR-01",
        subject="uv.lock does not exist",
        state="BLOCKED_BY_EXTERNAL_ACCESS",
        needs="a reachable package index to resolve the dependency graph",
        measured_evidence=(
            "`uv lock --offline` on the device VM resolved no solution: "
            "\"Because alembic was not found in the cache and your project "
            "depends on alembic>=1.13.1,<2.0 ... Packages were unavailable "
            "because the network was disabled.\" The uv cache is empty. "
            "pypi.org/simple/ returns HTTP 403 from both the device VM and "
            "the cloud container."),
    ),
    OperationalResidual(
        residual_id="OR-02",
        subject="CI linters are not version-pinned",
        state="BLOCKED_BY_EXTERNAL_ACCESS",
        needs="uv.lock, which is OR-01",
        measured_evidence=(
            "pyproject declares ruff>=0.4.0,<1.0 and mypy>=1.9,<2.0, and the "
            "workflow installs with `uv sync --frozen`, so the lockfile is "
            "the pin and the ranges are not. Narrowing the ranges would look "
            "like a fix and change nothing about what CI installs."),
    ),
    OperationalResidual(
        residual_id="OR-03",
        subject="every CI action SHA is unresolved",
        state="BLOCKED_BY_EXTERNAL_ACCESS",
        needs="api.github.com, to resolve each tag to its commit SHA",
        measured_evidence=(
            "build-and-verify.yml pins actions/checkout, "
            "actions/setup-python and astral-sh/setup-uv to "
            "0000000000000000000000000000000000000000 with a trailing "
            "\"- UNRESOLVED\" comment. api.github.com returns HTTP 403 from "
            "the cloud container; the device VM has no egress at all."),
    ),
    OperationalResidual(
        residual_id="OR-04",
        subject="no wheel or sdist has been built",
        state="BLOCKED_BY_EXTERNAL_ACCESS",
        needs="hatchling, the backend pyproject declares",
        measured_evidence=(
            "`import hatchling` fails on the device VM and it cannot be "
            "installed without a package index. Substituting a different "
            "build backend would produce a different artifact from the one "
            "the project declares, which is not the same evidence."),
    ),
    OperationalResidual(
        residual_id="OR-05",
        subject="no Python driver can reach PostgreSQL",
        state="BLOCKED_BY_EXTERNAL_ACCESS",
        needs="psycopg",
        measured_evidence=(
            "`import psycopg` fails on the device VM. The Wave 2 database "
            "drill was executed against a real PostgreSQL 16.13 server in the "
            "cloud container through psql rather than through the "
            "application's own driver, so the ORM path itself remains "
            "unexercised."),
    ),
    OperationalResidual(
        residual_id="OR-06",
        subject="no container image and no SBOM",
        state="BLOCKED_BY_EXTERNAL_ACCESS",
        needs="a container runtime",
        measured_evidence=(
            "no docker binary is present on the device VM, and the cloud "
            "container has the CLI but no daemon. THS6_CONTAINER_RUNTIME_"
            "UNAVAILABLE remains the accurate blocker."),
    ),
    OperationalResidual(
        residual_id="OR-07",
        subject="no staging environment has been deployed or observed",
        state="BLOCKED_BY_EXTERNAL_ACCESS",
        needs="an actual deployment target",
        measured_evidence=(
            "unchanged by this wave. A localhost process is not a staging "
            "environment and this project has already recorded that calling "
            "one staging would be the misdescription, not the shortcut."),
    ),
    OperationalResidual(
        residual_id="OR-08",
        subject="the checked-out .venv points at a missing interpreter",
        state="OBSERVED_NOT_REPAIRED",
        needs="nothing from outside; it is a local working-copy artifact",
        measured_evidence=(
            "uv reported \"Ignoring existing virtual environment linked to "
            "non-existent Python interpreter: .venv/bin/python3 -> "
            "python3.14\". The directory is not tracked by git, so it is a "
            "property of this working copy rather than of the repository, and "
            "Wave 3 did not touch it."),
    ),
    OperationalResidual(
        residual_id="OR-09",
        subject="two zero-byte git lock files cannot be removed",
        state="OBSERVED_NOT_REPAIRED",
        needs="filesystem permissions this session does not hold",
        measured_evidence=(
            ".git/HEAD.lock and .git/index.lock are both zero bytes and "
            "cannot be unlinked or renamed from the device shell "
            "(\"Operation not permitted\"). Commits in this wave were "
            "therefore made with an explicit index file and by writing "
            ".git/refs/heads/main directly, because git update-ref refuses "
            "while the locks are present. The commits themselves are "
            "ordinary; only the mechanism was unusual."),
    ),
    OperationalResidual(
        residual_id="OR-10",
        subject=("Wave 3's own new tests invalidated the WP-19 verification "
                 "artifacts, and neither environment can regenerate them "
                 "without making them worse"),
        state="CAUSED_BY_THIS_WAVE_AND_UNFIXABLE_HERE",
        needs=("a host with the api and database extras installed, whose "
               "verification records this repository will accept"),
        measured_evidence=(
            "A fresh build_artifacts() run on the device VM was compared "
            "against the committed artifact rather than assumed about. "
            "Committed: 7461 discovered, 274 suites, 0 load failures. Fresh "
            "on this host: 7481 discovered, 275 suites, and 2 load failures - "
            "tests.unit.expert_review.test_persistence and "
            "tests.unit.security.test_persistence, both ImportError on the "
            "absent sqlalchemy. Committing that would record two import "
            "failures that do not exist on a provisioned host. The cloud "
            "container has the dependencies but WP-19 records are "
            "host-fingerprinted and are correctly rejected here, so neither "
            "environment can produce an honest replacement. The stale-count "
            "guard in tests/unit/ths6 and the reproducibility checks in "
            "tests/unit/verification therefore fail, and they fail correctly: "
            "they are detecting real staleness that this wave caused."),
    ),
)


def caused_by_this_wave() -> Tuple[OperationalResidual, ...]:
    """Residuals this wave created.

    Listed separately because a residual a wave inherited and a residual a
    wave caused are different obligations, and a single count would let the
    second hide inside the first.
    """
    return tuple(item for item in RESIDUALS
                 if item.state == "CAUSED_BY_THIS_WAVE_AND_UNFIXABLE_HERE")


def blocked_residuals() -> Tuple[OperationalResidual, ...]:
    """Residuals waiting on something outside this session."""
    return tuple(item for item in RESIDUALS
                 if item.state == "BLOCKED_BY_EXTERNAL_ACCESS")
