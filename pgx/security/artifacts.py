# -*- coding: utf-8 -*-
"""The committed WP-23 artifacts (WP-23).

Six documents plus nine schemas, all deterministic functions of this
repository except the two that measure the environment.

**Nothing here contains a credential, an account or a session.** Not one row
of ``security_users``, not one session, not one password hash, not one cookie
and not one audit event with real content. The published documents are
registries, policies and status - the things a reader outside the project
needs in order to know what the system does, none of which is a secret. A
test asserts it by scanning the rendered bytes with the secret scanner.

**Two artifacts measure the environment and are excluded from the
reproducibility comparison**, for the same reason WP-19, WP-21 and WP-22
exclude their gate statuses: the secret-scan report walks the filesystem and
the gate status reads environment variables, so two builds on different
machines legitimately differ.
"""

from __future__ import annotations

import io
import os
from typing import Any, Dict, Mapping, Optional

from pgx.infrastructure.audit.vocabulary import (AUDIT_ACTION_AREAS,
                                                 AUDIT_ACTIONS,
                                                 AUDIT_EVENT_VERSION,
                                                 GOVERNED_ACTION_REGISTRY,
                                                 OBJECT_TYPES)
from pgx.security.backup import backup_status
from pgx.security.gate_status import build_wp23_gate_status
from pgx.security.rate_limit import policy_document
from pgx.security.rbac import registry_document
from pgx.security.secret_scan import scan_repository

__all__ = [
    "AUDIT_ACTIONS_PATH",
    "BACKUP_STATUS_PATH",
    "DETERMINISTIC_ARTIFACT_PATHS",
    "GATE_STATUS_PATH",
    "RATE_LIMIT_PATH",
    "RBAC_REGISTRY_PATH",
    "SECRET_SCAN_PATH",
    "build_artifacts",
    "build_audit_action_registry",
    "write_document",
]

RBAC_REGISTRY_PATH = "data/security/wp23-rbac-registry.json"
AUDIT_ACTIONS_PATH = "data/security/wp23-audit-action-registry.json"
RATE_LIMIT_PATH = "data/security/wp23-rate-limit-policy.json"
SECRET_SCAN_PATH = "data/security/wp23-secret-scan-report.json"
BACKUP_STATUS_PATH = "data/security/wp23-backup-restore-status.json"
GATE_STATUS_PATH = "data/security/wp23-real-gate-status.json"

#: What a reproducibility check may rebuild and compare byte for byte. The
#: secret-scan report walks the tree and the gate status reads the
#: environment, so both are excluded - a machine with a different checkout
#: legitimately produces different bytes, and a check that flagged it would
#: be measuring the machine rather than the generator.
DETERMINISTIC_ARTIFACT_PATHS = (RBAC_REGISTRY_PATH, AUDIT_ACTIONS_PATH,
                                RATE_LIMIT_PATH, BACKUP_STATUS_PATH)


def _render(document: Mapping[str, Any], root: str) -> str:
    from pgx.verification.scrub import safe_render
    return safe_render(document, root)


def build_audit_action_registry() -> Dict[str, Any]:
    """Every governed action, its area, and whether it must be atomic.

    Published so that "is this action audited" can be answered without
    reading the code, and so a test can fail when a governed service performs
    an action with no entry here.
    """
    return {
        "audit_event_schema_version": AUDIT_EVENT_VERSION,
        "action_count": len(AUDIT_ACTIONS),
        "areas": {area: list(names)
                  for area, names in sorted(AUDIT_ACTION_AREAS.items())},
        "object_types": list(OBJECT_TYPES),
        "actions": {name: dict(entry)
                    for name, entry in sorted(
                        GOVERNED_ACTION_REGISTRY.items())},
        "atomic_action_count": sum(
            1 for entry in GOVERNED_ACTION_REGISTRY.values()
            if entry["requires_atomic_audit"]),
        "atomicity_note": (
            "An action marked requires_atomic_audit must have its audit "
            "append committed in the same transaction as the governed state "
            "change. If the append fails the change rolls back: a governed "
            "success nobody can account for is worse than a refusal, because "
            "the refusal tells the operator something happened."),
        "refusal_note": (
            "The five actions not marked atomic are refusals and one "
            "read-only verification. Their audit append is best-effort and "
            "may never alter the outcome: an audit outage that turned a "
            "controlled refusal into a 500 would be reporting a different "
            "answer from the one the system reached."),
        "no_content_note": (
            "This registry names actions. It contains no event, no actor, no "
            "object identifier and no payload - the trail itself is not "
            "published, and the reader for it emits safe projections only."),
    }


def build_artifacts(root: str) -> Dict[str, str]:
    """Every deterministic artifact, rendered. WP-19's generator signature."""
    from pgx.application.security_schema import build_schemas

    documents: Dict[str, str] = {
        RBAC_REGISTRY_PATH: _render(registry_document(), root),
        AUDIT_ACTIONS_PATH: _render(build_audit_action_registry(), root),
        RATE_LIMIT_PATH: _render(policy_document(), root),
        BACKUP_STATUS_PATH: _render(backup_status(root, {}), root),
    }
    for relative, schema in build_schemas().items():
        documents[relative] = _render(schema, root)
    return documents


def write_document(root: str, relative: str,
                   document: Mapping[str, Any]) -> str:
    rendered = _render(document, root)
    path = os.path.join(root, *relative.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w", encoding="utf-8") as handle:
        handle.write(rendered)
    return rendered
