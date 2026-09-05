# -*- coding: utf-8 -*-
"""Do the deterministic things actually reproduce, byte for byte?

Two questions, kept apart because they have different answers and different
consequences.

**Does a generator agree with itself?** Run it twice, in two fresh
interpreters, with two *different* hash seeds, and compare the digests. Two
different seeds rather than the same one on purpose: a document whose key order
follows a set's iteration order reproduces perfectly within one interpreter and
differs between two, and that is the bug this check exists to find.

**Does the committed artifact match what the generator produces now?** For a
deterministic artifact - a schema, a contract, a catalogue - a mismatch means
the file in the repository is stale, and that is worth failing over.

The distinction that matters is which artifacts are eligible for the second
question. A gate status records the environment it was produced in: which
packages are importable, whether a browser launched, whether a database was
reachable. Regenerating one on a different machine *must* produce different
bytes, and comparing it with the committed copy would report an honest document
as stale. So gate statuses are checked for self-agreement only, and the
registry says so per generator rather than leaving it to a reader to work out.

No network is used, and none is needed: every generator here builds from files
in the repository.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from pgx.verification.errors import RunnerError

__all__ = [
    "REPRODUCIBILITY_SCHEMA_VERSION",
    "Generator",
    "GENERATORS",
    "GeneratorResult",
    "ReproducibilityReport",
    "check_generators",
    "file_digest",
]

REPRODUCIBILITY_SCHEMA_VERSION = "pgx-wp19-reproducibility-report/1"

#: Two different non-zero seeds. Zero would disable hash randomisation
#: entirely, which is the one setting under which an order-dependent document
#: reproduces perfectly and the check proves nothing.
SEED_A = "1"
SEED_B = "524287"


@dataclass(frozen=True)
class Generator:
    """One artifact generator, and what may be concluded from it."""

    name: str
    module: str
    #: Whether the committed files may be compared with a fresh build. False
    #: for anything that records the environment it ran in.
    committed_comparable: bool
    note: str = ""


GENERATORS: Tuple[Generator, ...] = (
    Generator(
        name="validation",
        module="pgx.application.validation_cli",
        committed_comparable=True,
        note="Schemas, case manifests and the separation audit are built from "
             "committed inputs alone, so a fresh build must match the "
             "committed bytes. The WP-18 gate status is built by the same CLI "
             "but is excluded from the committed comparison below, because it "
             "measures the filesystem."),
    Generator(
        name="api",
        module="apps.api.artifacts",
        committed_comparable=True,
        note="The OpenAPI document and the WP-16 contracts are generated from "
             "the declarative route table and depend on nothing outside it."),
    Generator(
        name="verification",
        module="pgx.verification.artifacts",
        committed_comparable=True,
        note="The test inventory, the requirement matrix, the profile "
             "registry and the seven published WP-19 schemas. All are "
             "functions of the repository, so a fresh build must match the "
             "committed bytes - and when it does not, the committed inventory "
             "is describing a suite that no longer exists."),
    Generator(
        name="web",
        module="apps.web.artifacts",
        committed_comparable=True,
        note="Route surface, catalogue schema and demo catalogue, all derived "
             "from committed sources."),
    Generator(
        name="security",
        module="pgx.security.artifacts",
        committed_comparable=True,
        note="The RBAC registry, the governed-action registry, the "
             "rate-limit policy and the backup status, plus the nine WP-23 "
             "schemas. The secret-scan report and the gate status are "
             "excluded from the committed comparison below: one walks the "
             "filesystem and the other reads the environment, so two builds "
             "on different machines legitimately differ."),
    Generator(
        name="expert-review",
        module="pgx.expert_review.artifacts",
        committed_comparable=True,
        note="The protocol manifest, the published workflow, the public "
             "aggregate and the eleven WP-22 schemas. Registered here rather "
             "than checked only by WP-22's own suite because the failure this "
             "catches is invisible inside one interpreter: the workflow "
             "document is built from a mapping of frozensets, and a set's "
             "iteration order is stable within a process and differs between "
             "two at different hash seeds. The WP-22 gate status is excluded "
             "from the committed comparison below, because it measures the "
             "filesystem and the environment."),
    Generator(
        name="deployment",
        module="pgx.deployment.artifacts",
        committed_comparable=True,
        note="The performance target registry, the reliability drill "
             "catalogue, the four restore conditions, the runtime asset "
             "manifest and the seventeen WP-24 schemas. The gate status, the "
             "release validation, the build provenance and the secret "
             "configuration are excluded from the committed comparison "
             "below: each measures the filesystem, the environment or a "
             "clock, and a document that measures the machine is supposed to "
             "differ between machines. The targets and the drills are "
             "registered here rather than checked only by WP-24's own suite "
             "because a refactor from a tuple to a set would be stable "
             "within one process and differ between two at different hash "
             "seeds."),
    Generator(
        name="ths6",
        module="pgx.ths6.artifacts",
        committed_comparable=True,
        note="The contingency matrix, the demonstration manifest, the "
             "sign-off matrix and the twenty WP-25 schemas. Only those: the "
             "evidence registry, the claim registry, the traceability "
             "matrix, the gate matrix, the Definition of Done evaluation, "
             "the preflight, the findings, the status and the pack manifest "
             "all measure the working tree - they hash files and read gate "
             "statuses that are themselves environment-dependent - so "
             "comparing one byte for byte between machines would fail for "
             "everybody. Registered here rather than checked only by WP-25's "
             "own suite because the demonstration manifest is built from "
             "tuples of dataclasses and the schema set from a dict, and a "
             "refactor to a set would be stable within one process and "
             "differ between two at different hash seeds."),
)

#: Artifacts a generator produces that record their environment. Excluded from
#: the committed-bytes comparison, and named here rather than guessed from the
#: filename, so that adding one is a decision.
ENVIRONMENT_DEPENDENT: Tuple[str, ...] = (
    "data/api/wp16-real-gate-status.json",
    "data/web/wp17-real-gate-status.json",
    "data/validation/wp18-real-gate-status.json",
    "data/verification/wp19-real-gate-status.json",
    "data/api/wp16-runtime-verification.json",
    "data/expert-review/wp22-real-gate-status.json",
    "data/security/wp23-real-gate-status.json",
    "data/security/wp23-secret-scan-report.json",
    # WP-24. Each of these measures the filesystem, the environment or a
    # clock. The targets, the drills, the restore conditions and the runtime
    # asset manifest are NOT here: they are derived from committed sources
    # and are compared byte for byte.
    "data/deployment/wp24-real-gate-status.json",
    "data/deployment/wp24-release-validation.json",
    "data/deployment/wp24-gate-e-status.json",
    "data/deployment/wp24-build-provenance.json",
    "data/deployment/wp24-secret-configuration.json",
    # WP-25. Each of these hashes the working tree or reads an artifact that
    # is itself environment-dependent. The contingency matrix, the
    # demonstration manifest and the sign-off matrix are NOT here: they are
    # pure declarations and are compared byte for byte.
    "data/ths6/wp25-evidence-registry.json",
    "data/ths6/wp25-claim-registry.json",
    "data/ths6/wp25-traceability-matrix.json",
    "data/ths6/wp25-gate-matrix.json",
    "data/ths6/wp25-definition-of-done.json",
    "data/ths6/wp25-demo-preflight.json",
    "data/ths6/wp25-findings.json",
    "data/ths6/wp25-ths6-status.json",
    "data/ths6/wp25-evidence-pack-manifest.json",
)


@dataclass(frozen=True)
class GeneratorResult:
    """What two regenerations of one generator showed."""

    generator: str
    module: str
    status: str                       # "REPRODUCIBLE" | "MISMATCH" | "BLOCKED"
    artifact_count: int
    #: Artifacts whose two builds disagreed. The determinism bug.
    unstable_artifacts: Tuple[str, ...]
    #: Deterministic artifacts whose committed bytes differ from a fresh build.
    stale_committed_artifacts: Tuple[str, ...]
    #: Artifacts named as environment-dependent and therefore not compared.
    excluded_from_committed_comparison: Tuple[str, ...]
    #: Deterministic artifacts with no committed file at all.
    missing_committed_artifacts: Tuple[str, ...]
    reason: str = ""

    def as_document(self) -> Dict[str, Any]:
        return {
            "artifact_count": self.artifact_count,
            "excluded_from_committed_comparison":
                list(self.excluded_from_committed_comparison),
            "generator": self.generator,
            "missing_committed_artifacts":
                list(self.missing_committed_artifacts),
            "module": self.module,
            "reason": self.reason,
            "stale_committed_artifacts":
                list(self.stale_committed_artifacts),
            "status": self.status,
            "unstable_artifacts": list(self.unstable_artifacts),
        }


@dataclass(frozen=True)
class ReproducibilityReport:
    """Every generator's result, and the one word for all of them."""

    generators: Tuple[GeneratorResult, ...]
    seeds: Tuple[str, str]
    status: str
    note: str = ""

    def as_document(self) -> Dict[str, Any]:
        return {
            "generators": [item.as_document() for item in self.generators],
            "hash_seeds": list(self.seeds),
            "note": self.note,
            "reproducibility_schema_version": REPRODUCIBILITY_SCHEMA_VERSION,
            "status": self.status,
        }


def file_digest(path: str) -> Optional[str]:
    """The sha256 of a file's bytes, or ``None`` when it is not there."""
    if not os.path.exists(path):
        return None
    digest = hashlib.sha256()
    with io.open(path, "rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def _regenerate(root: str, generator: Generator, seed: str,
                timeout: int = 600) -> Mapping[str, Mapping[str, Any]]:
    """One regeneration, in its own interpreter, at ``seed``."""
    workspace = tempfile.mkdtemp(prefix="pgx-wp19-artifact-")
    report_path = os.path.join(workspace, "report.json")
    environment = dict(os.environ)
    environment["PYTHONHASHSEED"] = seed
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "pgx.verification._artifact_worker",
             root, generator.module, report_path],
            cwd=root, env=environment, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=timeout, check=False)
        if not os.path.exists(report_path):
            raise RunnerError(
                "the artifact worker for %r produced no report (exit %d): %s"
                % (generator.name, completed.returncode,
                   completed.stderr.decode("utf-8", "replace")[-800:]))
        with io.open(report_path, "r", encoding="utf-8") as handle:
            return json.load(handle).get("artifacts", {})
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def check_generators(root: str,
                     generators: Sequence[Generator] = GENERATORS
                     ) -> ReproducibilityReport:
    """Regenerate each generator twice and compare, then check the tree."""
    results: List[GeneratorResult] = []
    for generator in generators:
        try:
            first = _regenerate(root, generator, SEED_A)
            second = _regenerate(root, generator, SEED_B)
        except RunnerError as exc:
            results.append(GeneratorResult(
                generator=generator.name, module=generator.module,
                status="BLOCKED", artifact_count=0, unstable_artifacts=(),
                stale_committed_artifacts=(),
                excluded_from_committed_comparison=(),
                missing_committed_artifacts=(), reason=str(exc)))
            continue

        unstable = tuple(sorted(
            relative for relative in sorted(set(first) | set(second))
            if first.get(relative, {}).get("sha256")
            != second.get(relative, {}).get("sha256")))

        stale: List[str] = []
        missing: List[str] = []
        excluded: List[str] = []
        if generator.committed_comparable:
            for relative, entry in sorted(first.items()):
                if relative in ENVIRONMENT_DEPENDENT:
                    excluded.append(relative)
                    continue
                committed = file_digest(
                    os.path.join(root, *relative.split("/")))
                if committed is None:
                    missing.append(relative)
                elif committed != entry.get("sha256"):
                    stale.append(relative)

        status = "REPRODUCIBLE"
        if unstable:
            status = "MISMATCH"
        elif stale or missing:
            status = "STALE"
        results.append(GeneratorResult(
            generator=generator.name, module=generator.module, status=status,
            artifact_count=len(first), unstable_artifacts=unstable,
            stale_committed_artifacts=tuple(stale),
            excluded_from_committed_comparison=tuple(excluded),
            missing_committed_artifacts=tuple(missing),
            reason=generator.note))

    overall = "REPRODUCIBLE"
    if any(item.status == "MISMATCH" for item in results):
        overall = "MISMATCH"
    elif any(item.status == "STALE" for item in results):
        overall = "STALE"
    elif any(item.status == "BLOCKED" for item in results):
        overall = "BLOCKED"
    elif not results:
        overall = "BLOCKED"

    return ReproducibilityReport(
        generators=tuple(results), seeds=(SEED_A, SEED_B), status=overall,
        note="Each generator was built twice, in two fresh interpreters, under "
             "two different PYTHONHASHSEED values. Artifacts that record the "
             "environment they were produced in are compared with each other "
             "and not with the committed copy, because a gate status is "
             "supposed to differ between machines.")
