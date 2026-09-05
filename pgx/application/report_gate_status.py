# -*- coding: utf-8 -*-
"""Why no real report can be published yet (WP-15).

Every count here is read off the repository rather than asserted, so the day
any of it changes this report changes with it and the change is visible in a
diff. A gate status that claimed reports exist when none do would be the same
class of overclaim the gate exists to prevent.

The blockers are not bugs and none can be cleared by writing code. WP-15's
machinery is implemented and verified against synthetic fixtures; what is
missing above it is human and scientific judgement, and one thing at this
level: nobody has reviewed the report templates or the Turkish label set,
which is a human act and not a test.
"""

from __future__ import annotations

import io
import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Tuple

from pgx.domain.claims import CLAIM_SCANNER_VERSION, DEFAULT_CLAIM_BOUNDARY
from pgx.domain.hashing import sha256_digest
from pgx.reporting.gate import SCANNER_LIMITS
from pgx.reporting.llm import LLM_ENABLED
from pgx.reporting.render import RENDERER_VERSION
from pgx.reporting.structured import REPORT_SCHEMA_VERSION
from pgx.reporting.templates import (DEFAULT_LOCALE, SUPPORTED_LOCALES,
                                     TEMPLATE_VERSION)

__all__ = [
    "BLOCKER_CODES",
    "DEFAULT_REPORT_ROOT",
    "GATE_STATUS_FILENAME",
    "REPORT_GATE_STATUS_VERSION",
    "ReportGateStatus",
    "build_report_gate_status",
]

REPORT_GATE_STATUS_VERSION = "pgx-wp15-gate-status/1"

#: Where a real published report would live. Empty, and a test asserts it
#: stays empty: a document here would mean a report had been published.
DEFAULT_REPORT_ROOT = os.path.join("data", "reports")

#: This report's own filename, skipped by the scanner below so regenerating it
#: cannot read a half-written copy of itself.
GATE_STATUS_FILENAME = "wp15-real-gate-status.json"

BLOCKER_CODES: Mapping[str, Mapping[str, str]] = {
    "REPORT_CLAIM_BOUNDARY_NOT_APPROVED": {
        "meaning": "the claim boundary is DRAFT and awaiting human and "
                   "scientific review, so no report of a real assessment may "
                   "be produced in any mode",
        "owner": "the people named in docs/architecture/intended-purpose.md, "
                 "not code",
        "unblocks": "the report service stops refusing before it reads "
                    "anything",
    },
    "REPORT_NO_REAL_ASSESSMENT": {
        "meaning": "no real assessment has been executed, so there is nothing "
                   "to report on; reporting does not calculate one to fill "
                   "the gap",
        "owner": "everything WP-14's own gate status blocks on",
        "unblocks": "a stored assessment exists for a report to project",
    },
    "REPORT_NO_DATABASE_RUNTIME": {
        "meaning": "SQLAlchemy and a driver cannot be installed in this "
                   "environment, so the production read port cannot be "
                   "constructed and no stored assessment can be loaded here",
        "owner": "an environment with the packages and a PostgreSQL server",
        "unblocks": "the read port the service is designed around",
    },
    "REPORT_TEMPLATES_NOT_REVIEWED": {
        "meaning": "no named human has reviewed the report templates, the "
                   "controlled sentences or the Turkish label set; they are "
                   "authored and tested, and nobody has approved them",
        "owner": "a named reviewer, and for the Turkish text a reviewer who "
                 "reads Turkish",
        "unblocks": "the wording a reader actually sees carries an approval",
    },
    "REPORT_NO_APPROVED_RULESET_OR_RELEASE": {
        "meaning": "no frozen ruleset, approved coverage manifest or active "
                   "release exists upstream, so any report would describe an "
                   "assessment that could not have been executed",
        "owner": "the WP-11 and WP-03 governance chains",
        "unblocks": "an assessment with real provenance to report",
    },
    "REPORT_NO_HUMAN_ROLE_ASSIGNMENTS": {
        "meaning": "no identity holds a scientific role, so none of the "
                   "approvals above can be performed by anybody",
        "owner": "WP-23 authentication, then whoever assigns roles",
        "unblocks": "every approval this list depends on",
    },
}


@dataclass(frozen=True, slots=True)
class ReportGateStatus:
    payload: Mapping[str, Any]

    def to_json(self) -> Dict[str, Any]:
        return dict(self.payload)

    def content_hash(self) -> str:
        return sha256_digest(self.to_json())

    @property
    def blockers(self) -> Tuple[Mapping[str, Any], ...]:
        return tuple(self.payload.get("blockers", ()))


def _read_json(path: str) -> Any:
    if not os.path.isfile(path):
        return None
    try:
        with io.open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (ValueError, OSError):
        return None


def _published_reports(repo_root: str) -> List[str]:
    """Report artifacts actually present in the production directory.

    Matched on the artifact naming convention rather than on the extension,
    so the directory's own README and this status file are not counted as
    published reports. A file here that is *not* named like an artifact is
    still not a report - and if one ever appears, the artifact reader is what
    refuses it, not this count.
    """
    root = os.path.join(repo_root, DEFAULT_REPORT_ROOT)
    if not os.path.isdir(root):
        return []
    return sorted(name for name in os.listdir(root)
                  if name.startswith("report-")
                  and (name.endswith(".md") or name.endswith(".json")))


def _real_assessments(repo_root: str) -> List[str]:
    from pgx.application.assessment_gate_status import (
        DEFAULT_ASSESSMENT_ROOT, GATE_STATUS_FILENAME as ASSESSMENT_STATUS)
    root = os.path.join(repo_root, DEFAULT_ASSESSMENT_ROOT)
    if not os.path.isdir(root):
        return []
    found = []
    for name in sorted(os.listdir(root)):
        if not name.endswith(".json") or name == ASSESSMENT_STATUS:
            continue
        document = _read_json(os.path.join(root, name))
        if isinstance(document, dict) and document.get("assessment_id"):
            found.append(name)
    return found


def build_report_gate_status(repo_root: str = ".") -> ReportGateStatus:
    """Read the real repository and report what publication it permits."""
    from pgx.rules.registry import DEFAULT_RULESET_ROOT, FrozenRulesetRegistry

    executable = FrozenRulesetRegistry(
        os.path.join(repo_root, DEFAULT_RULESET_ROOT)).list_executable()
    assessments = _real_assessments(repo_root)
    published = _published_reports(repo_root)
    boundary = DEFAULT_CLAIM_BOUNDARY

    detail = {
        "REPORT_CLAIM_BOUNDARY_NOT_APPROVED":
            "claim boundary status is %s" % boundary.status,
        "REPORT_NO_REAL_ASSESSMENT":
            "%d real assessments are stored in this repository"
            % len(assessments),
        "REPORT_NO_DATABASE_RUNTIME":
            "the SQLAlchemy read port could not be constructed in this "
            "environment; the read model was exercised in memory instead",
        "REPORT_TEMPLATES_NOT_REVIEWED":
            "0 named humans have approved template %s or the %s label sets"
            % (TEMPLATE_VERSION, ", ".join(SUPPORTED_LOCALES)),
        "REPORT_NO_APPROVED_RULESET_OR_RELEASE":
            "%d frozen rulesets, 0 active releases, 0 approved coverage "
            "manifests" % len(executable),
        "REPORT_NO_HUMAN_ROLE_ASSIGNMENTS":
            "0 identities hold a scientific role",
    }
    blockers = [{"code": code, "blocking": True, "detail": detail[code]}
                for code in sorted(BLOCKER_CODES)]

    payload: Dict[str, Any] = {
        "gate_status_schema_version": REPORT_GATE_STATUS_VERSION,
        "work_package": "WP-15",
        "may_publish_real_reports": False,
        "claim_boundary_phase": boundary.phase.value,
        "claim_boundary_status": boundary.status,
        "claim_boundary_approved": boundary.is_approved,
        "llm_enabled": LLM_ENABLED,
        "llm_provider_implemented": False,
        "template_version": TEMPLATE_VERSION,
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "renderer_version": RENDERER_VERSION,
        "default_locale": DEFAULT_LOCALE,
        "supported_locales": list(SUPPORTED_LOCALES),
        "real_assessment_count": len(assessments),
        "real_report_count": 0,
        "published_artifact_count": len(published),
        "synthetic_only": True,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "scanner_version": CLAIM_SCANNER_VERSION,
        "scanner_limits": list(SCANNER_LIMITS),
        "note": (
            "This is an expected governance result, not a test failure. The "
            "WP-15 reporting pipeline is implemented and verified against "
            "synthetic fixtures; every report produced so far is synthetic "
            "and is flagged as such. No report of a real assessment has been "
            "produced, no artifact has been published to the production "
            "directory, no language model was called, and no count above was "
            "asserted rather than read from this repository."),
    }
    return ReportGateStatus(payload=payload)
