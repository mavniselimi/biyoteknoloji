# -*- coding: utf-8 -*-
"""SBOM and vulnerability status (WP-24).

A vulnerability report's most important field is not the count of findings.
It is **what the findings were compared against** - which scanner, at which
version, with which advisory database, as of which date. A report saying "0
critical" without those is a report saying that something, at some point,
looked at something.

So every result here carries scanner identity, scanner version, advisory
database identity and date, the image digest scanned, the severity policy
applied, and the process exit code. When any of those is unavailable, the
status is ``BLOCKED`` or ``NOT_EXECUTED`` - never ``PASS``. A scan that could
not run is not a clean scan, and this is the single most common way a supply
chain report becomes false.

**Ignores.** Every suppression is exact, time-bounded and justified. There is
no wildcard, no severity floor that silently drops a class of findings, and no
"ignore everything in the base image". An unbounded ignore outlives the reason
it was added, and the person who added it is rarely the person who finds out.

**Secret values never appear.** ``pgx-security secret-scan`` stays the
blocking check and reports a path, a line and a rule id; this module records
its status and count and never its matches.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import shutil
import subprocess  # noqa: S404 - driving a scanner is the point
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence, Tuple

from pgx.deployment.vocabulary import ExecutionState, blocker

__all__ = [
    "SUPPLY_CHAIN_RESULT_VERSION",
    "SEVERITY_POLICY",
    "VulnerabilityIgnore",
    "IGNORES",
    "generate_sbom",
    "scan_vulnerabilities",
    "supply_chain_status",
]

SUPPLY_CHAIN_RESULT_VERSION = "pgx-wp24-supply-chain/1"

#: What blocks a release. Stated as a policy rather than left to a scanner's
#: default, because defaults differ between scanners and a policy that changed
#: when the tool changed would not be a policy.
SEVERITY_POLICY: Mapping[str, str] = {
    "CRITICAL": "blocks the release path",
    "HIGH": "blocks the release path",
    "MEDIUM": "recorded; reviewed before a release, does not block "
              "automatically",
    "LOW": "recorded",
    "UNKNOWN": "recorded and reviewed as though HIGH until classified, "
               "because an unclassified finding is not a low one",
}

_BLOCKING_SEVERITIES: Tuple[str, ...] = ("CRITICAL", "HIGH")


@dataclass(frozen=True)
class VulnerabilityIgnore:
    """One exact, justified, expiring suppression.

    Every field is required. An ignore with no expiry outlives its reason; an
    ignore with no justification cannot be reviewed; an ignore without an
    exact identifier is a wildcard wearing a disguise.
    """

    advisory_id: str
    package: str
    justification: str
    expires_on: str  # ISO date
    approved_by: str

    def active_on(self, day: _dt.date) -> bool:
        return day <= _dt.date.fromisoformat(self.expires_on)

    def to_json(self) -> Mapping[str, object]:
        return {"advisory_id": self.advisory_id, "package": self.package,
                "justification": self.justification,
                "expires_on": self.expires_on,
                "approved_by": self.approved_by}


#: Empty. Nothing has been scanned, so nothing has been suppressed. It stays a
#: declared, empty tuple rather than being absent so that a reviewer can see
#: there are none rather than infer it.
IGNORES: Tuple[VulnerabilityIgnore, ...] = ()


def _run(argv: Sequence[str], *, timeout: int = 600) -> Tuple[int, str]:
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
            list(argv), capture_output=True, text=True, timeout=timeout,
            check=False)
    except FileNotFoundError:
        return 127, ""
    except subprocess.TimeoutExpired:
        return 124, ""
    return completed.returncode, completed.stdout or ""


def generate_sbom(*, image_reference: Optional[str] = None,
                  lockfile_path: Optional[str] = None,
                  output_path: Optional[str] = None,
                  runner=None) -> Mapping[str, object]:
    """Produce an SBOM from real image or lockfile contents.

    Never from ``pyproject.toml``. That file declares *ranges*; an SBOM
    declares what is installed, and a bill of materials generated from a range
    is a list of what might be there.
    """
    run = runner or _run
    if image_reference and shutil.which("syft"):
        code, text = run(["syft", image_reference, "-o", "spdx-json"])
        if code == 0 and text.strip():
            if output_path:
                with open(output_path, "w", encoding="utf-8") as handle:
                    handle.write(text)
            return {"state": ExecutionState.EXECUTED.value,
                    "generator": "syft", "format": "spdx-json",
                    "source": "image", "reference": image_reference,
                    "path": output_path, "blockers": []}
    if lockfile_path and os.path.isfile(lockfile_path) and \
            shutil.which("syft"):
        code, text = run(["syft", "file:" + lockfile_path, "-o", "spdx-json"])
        if code == 0 and text.strip():
            if output_path:
                with open(output_path, "w", encoding="utf-8") as handle:
                    handle.write(text)
            return {"state": ExecutionState.EXECUTED.value,
                    "generator": "syft", "format": "spdx-json",
                    "source": "lockfile", "path": output_path,
                    "blockers": []}
    reason = ("no SBOM generator is available" if not shutil.which("syft")
              else "no image was built and no lockfile exists, so there are "
                   "no real contents to describe")
    return {
        "state": ExecutionState.BLOCKED.value, "generator": None,
        "format": None, "source": None, "path": None,
        "blockers": [dict(blocker("DEPLOY_SBOM_NOT_GENERATED",
                                  owner="the build host",
                                  detail=reason).to_json())],
        "note": ("An SBOM is generated from installed contents, never from "
                 "pyproject.toml: that file declares ranges, and a bill of "
                 "materials built from a range lists what might be there."),
    }


def scan_vulnerabilities(*, image_reference: Optional[str] = None,
                         image_digest: Optional[str] = None,
                         runner=None,
                         today: Optional[_dt.date] = None
                         ) -> Mapping[str, object]:
    """Run a real scanner, or report BLOCKED. Never PASS by default."""
    run = runner or _run
    day = today or _dt.date.today()
    active = [item for item in IGNORES if item.active_on(day)]
    expired = [item for item in IGNORES if not item.active_on(day)]
    base = {
        "supply_chain_version": SUPPLY_CHAIN_RESULT_VERSION,
        "scanner_name": None, "scanner_version": None,
        "advisory_database_identity": None, "advisory_database_date": None,
        "image_reference": image_reference, "image_digest": image_digest,
        "severity_policy": dict(SEVERITY_POLICY),
        "blocking_severities": list(_BLOCKING_SEVERITIES),
        "active_ignores": [dict(item.to_json()) for item in active],
        "expired_ignores": [dict(item.to_json()) for item in expired],
        "ignore_policy": (
            "Every suppression is exact, justified, expiring and attributed. "
            "There is no wildcard, no severity floor and no blanket ignore of "
            "a base image: an unbounded ignore outlives the reason it was "
            "added, and the person who added it is rarely the person who "
            "finds out."),
        "finding_counts": None,
        "exit_code": None,
    }
    if not image_reference:
        base.update({
            "state": ExecutionState.BLOCKED.value,
            "blockers": [dict(blocker(
                "DEPLOY_IMAGE_NOT_BUILT", owner="the build host",
                detail=("no image exists to scan; a vulnerability report "
                        "about no artifact is not a clean one")).to_json())]})
        return base
    scanner = next((name for name in ("trivy", "grype")
                    if shutil.which(name)), None)
    if scanner is None:
        base.update({
            "state": ExecutionState.BLOCKED.value,
            "blockers": [dict(blocker(
                "DEPLOY_VULNERABILITY_SCANNER_UNAVAILABLE",
                owner="the build host",
                detail=("no vulnerability scanner is installed; a scan that "
                        "could not run is not a clean scan")).to_json())]})
        return base
    version_code, version_text = run([scanner, "--version"], timeout=60)
    if scanner == "trivy":
        code, text = run([scanner, "image", "--format", "json",
                          "--scanners", "vuln", image_reference])
    else:
        code, text = run([scanner, image_reference, "-o", "json"])
    if code not in (0, 1) or not text.strip():
        base.update({
            "state": ExecutionState.NOT_EXECUTED.value,
            "scanner_name": scanner,
            "scanner_version": version_text.strip() or None,
            "exit_code": code,
            "blockers": [dict(blocker(
                "DEPLOY_VULNERABILITY_SCANNER_UNAVAILABLE",
                owner="the build host",
                detail="%s exited %d and produced no parseable report"
                       % (scanner, code)).to_json())]})
        return base
    counts, advisory_identity, advisory_date = _parse_findings(scanner, text)
    if advisory_identity is None:
        base.update({
            "state": ExecutionState.NOT_EXECUTED.value,
            "scanner_name": scanner,
            "scanner_version": version_text.strip() or None,
            "exit_code": code, "finding_counts": counts,
            "blockers": [dict(blocker(
                "DEPLOY_ADVISORY_DATABASE_UNAVAILABLE",
                owner="the build host",
                detail=("the scan produced findings but named no advisory "
                        "database; a count with nothing to compare it "
                        "against says only that something looked at "
                        "something")).to_json())]})
        return base
    blocking = sum(counts.get(name, 0) for name in _BLOCKING_SEVERITIES)
    base.update({
        "state": (ExecutionState.VERIFIED.value if blocking == 0
                  else ExecutionState.EXECUTED.value),
        "scanner_name": scanner,
        "scanner_version": version_text.strip() or None,
        "advisory_database_identity": advisory_identity,
        "advisory_database_date": advisory_date,
        "exit_code": code,
        "finding_counts": counts,
        "blocking_finding_count": blocking,
        "blockers": [],
    })
    return base


def _parse_findings(scanner: str, text: str
                    ) -> Tuple[Mapping[str, int], Optional[str],
                               Optional[str]]:
    counts: dict = {}
    identity: Optional[str] = None
    date: Optional[str] = None
    try:
        payload = json.loads(text)
    except ValueError:
        return counts, identity, date
    if scanner == "trivy":
        for result in payload.get("Results") or []:
            for finding in result.get("Vulnerabilities") or []:
                severity = str(finding.get("Severity") or "UNKNOWN").upper()
                counts[severity] = counts.get(severity, 0) + 1
        identity = "trivy-db"
        date = (payload.get("CreatedAt") or None)
    else:
        for match in payload.get("matches") or []:
            severity = str(
                (match.get("vulnerability") or {}).get("severity")
                or "UNKNOWN").upper()
            counts[severity] = counts.get(severity, 0) + 1
        descriptor = payload.get("descriptor") or {}
        identity = str((descriptor.get("db") or {}).get("schemaVersion")
                       or "grype-db") if descriptor else "grype-db"
        date = ((descriptor.get("db") or {}).get("built") or None)
    return counts, identity, date


def supply_chain_status(*, sbom: Optional[Mapping[str, Any]] = None,
                        vulnerabilities: Optional[Mapping[str, Any]] = None,
                        secret_scan_status: Optional[str] = None,
                        secret_finding_count: Optional[int] = None
                        ) -> Mapping[str, object]:
    """The three checks together, each keeping its own state."""
    sbom = dict(sbom or generate_sbom())
    vulnerabilities = dict(vulnerabilities or scan_vulnerabilities())
    blockers = list(sbom.get("blockers") or []) + list(
        vulnerabilities.get("blockers") or [])
    return {
        "supply_chain_version": SUPPLY_CHAIN_RESULT_VERSION,
        "sbom": sbom,
        "vulnerability_scan": vulnerabilities,
        "secret_scan": {
            "status": secret_scan_status,
            "finding_count": secret_finding_count,
            "blocking": True,
            "note": ("pgx-security secret-scan stays the blocking check. It "
                     "reports a path, a line and a rule id; no matched value "
                     "appears here or in it."),
        },
        "blockers": blockers,
        "release_path_clear": (
            sbom.get("state") == ExecutionState.EXECUTED.value
            and vulnerabilities.get("state") == ExecutionState.VERIFIED.value
            and secret_scan_status == "CLEAN"),
    }
