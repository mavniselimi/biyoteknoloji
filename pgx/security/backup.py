# -*- coding: utf-8 -*-
"""The backup and restore plan, and a preflight that never claims success.

WP-23 owns the *checklist*; WP-24 owns *running* it. That split is the whole
design of this module, and it is why :func:`backup_status` reports
``backup_executed: false`` and ``restore_verified: false`` and has no code
path that could report otherwise from configuration alone.

**A preflight is not a backup.** :func:`preflight` reads what is configured
and what exists on disk. It never runs ``pg_dump``, never writes an archive,
never restores anything and never contacts a database. A command that
inspected configuration and then reported ``PASS`` would be reporting that a
backup *could* be taken, in a document whose readers will read it as a backup
*having been* taken - and the distance between those two is the entire value
of a backup.

**The scope is two things, not one.** PostgreSQL holds users, sessions,
audit events, assessments and governance state. The immutable artifact
manifests hold the released dataset, ruleset and evidence bundles. Restoring
the database against a different set of artifacts produces a system whose
audit rows reference releases it cannot resolve, so the pair has to be
captured and restored together or the restore is not a restore.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, Mapping, Optional, Tuple

__all__ = [
    "BACKUP_PLAN_VERSION",
    "BACKUP_SCOPE",
    "BackupScopeItem",
    "OperationalStatus",
    "backup_status",
    "preflight",
]

BACKUP_PLAN_VERSION = "pgx-wp23-backup-restore/1"


class OperationalStatus:
    """The vocabulary. Deliberately has no ``PASS``.

    ``NOT_EXECUTED`` is the only honest terminal value this repository can
    reach, and a vocabulary containing ``PASS`` would eventually have
    something assigned to it by a caller who meant "the configuration looks
    right".
    """

    NOT_EXECUTED = "NOT_EXECUTED"
    BLOCKED = "BLOCKED"
    EXECUTED_UNVERIFIED = "EXECUTED_UNVERIFIED"
    EXECUTED_VERIFIED = "EXECUTED_VERIFIED"

    ALL: Tuple[str, ...] = (NOT_EXECUTED, BLOCKED, EXECUTED_UNVERIFIED,
                            EXECUTED_VERIFIED)


@dataclass(frozen=True)
class BackupScopeItem:
    """One thing that must be captured, and what is lost without it."""

    item_id: str
    title: str
    kind: str
    encrypted_at_rest_required: bool
    retention_days: int
    rotation: str
    loss_consequence: str

    def to_json(self) -> dict:
        return {"item_id": self.item_id, "title": self.title,
                "kind": self.kind,
                "encrypted_at_rest_required":
                    self.encrypted_at_rest_required,
                "retention_days": self.retention_days,
                "rotation": self.rotation,
                "loss_consequence": self.loss_consequence}


BACKUP_SCOPE: Tuple[BackupScopeItem, ...] = (
    BackupScopeItem(
        item_id="POSTGRESQL_LOGICAL_DUMP",
        title="Logical dump of the application database",
        kind="POSTGRESQL", encrypted_at_rest_required=True,
        retention_days=90, rotation="daily, 90 daily + 12 monthly retained",
        loss_consequence="Every governed record is lost together: accounts, "
                         "sessions, the audit chain, assessments, curation "
                         "state and the release pointer. The audit chain in "
                         "particular cannot be reconstructed from anywhere "
                         "else, because reconstructing it is exactly what it "
                         "exists to make impossible."),
    BackupScopeItem(
        item_id="GOVERNED_AUDIT_STREAM",
        title="The canonical audit stream, exported and verified separately",
        kind="POSTGRESQL", encrypted_at_rest_required=True,
        retention_days=3650,
        rotation="daily, retained for ten years independently of the "
                 "database dump",
        loss_consequence="A restore that silently dropped audit rows would "
                         "produce a chain that verifies - because the "
                         "remaining links are internally consistent - while "
                         "being incomplete. Exporting the stream separately, "
                         "with its head sequence, makes a truncated restore "
                         "detectable."),
    BackupScopeItem(
        item_id="IMMUTABLE_ARTIFACT_MANIFESTS",
        title="Released dataset, ruleset and evidence manifests",
        kind="ARTIFACT", encrypted_at_rest_required=False,
        retention_days=3650, rotation="on release, retained indefinitely",
        loss_consequence="Audit rows and assessments pin release, dataset "
                         "and ruleset hashes. Without the manifests those "
                         "hashes reference nothing, so every historical "
                         "result becomes unverifiable even though the rows "
                         "survive."),
    BackupScopeItem(
        item_id="RESTRICTED_HOLDOUT_STORAGE",
        title="Restricted expert-holdout payload storage",
        kind="RESTRICTED", encrypted_at_rest_required=True,
        retention_days=3650,
        rotation="on change, retained for the life of the validation "
                 "programme",
        loss_consequence="The holdout set cannot be regenerated: a "
                         "regenerated case is a case the software has now "
                         "seen. Losing it ends the validation programme "
                         "rather than delaying it."),
)


@dataclass(frozen=True)
class PreflightCheck:
    """One thing the preflight can observe without running anything."""

    check_id: str
    title: str
    satisfied: bool
    detail: str

    def to_json(self) -> dict:
        return {"check_id": self.check_id, "title": self.title,
                "satisfied": self.satisfied, "detail": self.detail}


def preflight(root: str,
              environ: Optional[Mapping[str, str]] = None) -> Dict[str, object]:
    """What is configured, and what is missing. Runs nothing.

    Reports every check as an observation with a controlled detail string. It
    never contacts a database, never writes a file and never reports success
    of a backup - because it has not taken one, and the only thing worse than
    no backup is a document saying there is one.
    """
    values = os.environ if environ is None else environ
    checks = [
        PreflightCheck(
            "DATABASE_CONFIGURED", "A database connection is configured",
            bool(values.get("DATABASE_URL")),
            "DATABASE_URL is set" if values.get("DATABASE_URL")
            else "DATABASE_URL is unset, so there is nothing to dump"),
        PreflightCheck(
            "BACKUP_DESTINATION_CONFIGURED",
            "An encrypted backup destination is configured",
            bool(values.get("PGX_BACKUP_DESTINATION")),
            "PGX_BACKUP_DESTINATION is set"
            if values.get("PGX_BACKUP_DESTINATION")
            else "PGX_BACKUP_DESTINATION is unset; no destination means no "
                 "backup, and a local file beside the database is not one"),
        PreflightCheck(
            "ARTIFACT_MANIFESTS_PRESENT",
            "The immutable artifact manifests are readable",
            os.path.isdir(os.path.join(root, "data")),
            "the data directory is readable"
            if os.path.isdir(os.path.join(root, "data"))
            else "the data directory is not readable"),
        PreflightCheck(
            "RESTRICTED_STORAGE_CONFIGURED",
            "Restricted holdout storage is configured",
            bool(values.get("PGX_VALIDATION_RESTRICTED_ROOT")),
            "PGX_VALIDATION_RESTRICTED_ROOT is set"
            if values.get("PGX_VALIDATION_RESTRICTED_ROOT")
            else "PGX_VALIDATION_RESTRICTED_ROOT is unset; there is no "
                 "holdout storage to capture"),
        PreflightCheck(
            "RESTORE_TARGET_CONFIGURED",
            "A separate restore-verification target is configured",
            bool(values.get("PGX_RESTORE_TARGET_URL")),
            "PGX_RESTORE_TARGET_URL is set"
            if values.get("PGX_RESTORE_TARGET_URL")
            else "PGX_RESTORE_TARGET_URL is unset; a restore verified into "
                 "the production database is not a verification, it is an "
                 "outage"),
    ]
    unmet = [item.check_id for item in checks if not item.satisfied]
    return {
        "backup_plan_version": BACKUP_PLAN_VERSION,
        "checks": [item.to_json() for item in checks],
        "unmet_check_ids": unmet,
        "ready_to_execute": not unmet,
        # Even with every check satisfied, this is not a backup. The status
        # below stays NOT_EXECUTED until something actually runs, which is
        # WP-24's to do.
        "operational_status": (OperationalStatus.BLOCKED if unmet
                               else OperationalStatus.NOT_EXECUTED),
        "preflight_is_not_a_backup": (
            "This command reads configuration and the filesystem. It runs no "
            "pg_dump, writes no archive, restores nothing and contacts no "
            "database. A preflight that reported PASS would be reporting "
            "that a backup could be taken, to readers who will read it as a "
            "backup having been taken."),
    }


def backup_status(root: str,
                  environ: Optional[Mapping[str, str]] = None
                  ) -> Dict[str, object]:
    """The committed status document. Executed is false and stays false."""
    checks = preflight(root, environ)
    return {
        "backup_plan_version": BACKUP_PLAN_VERSION,
        "backup_procedure_documented": True,
        "runbook": "docs/operations/backup-restore-runbook.md",
        "scope_item_count": len(BACKUP_SCOPE),
        "scope": [item.to_json() for item in BACKUP_SCOPE],
        "encrypted_storage_required": True,
        "encryption_note": (
            "Every item whose kind is POSTGRESQL or RESTRICTED is encrypted "
            "at rest. The artifact manifests are not, because they are "
            "published documents containing no credential and no payload - "
            "encrypting them would imply they were sensitive and invite "
            "somebody to treat an unencrypted copy as a leak."),
        # The four facts the work package names, and none of them is derived
        # from configuration. Each would require something to have actually
        # run, and nothing has.
        "backup_executed": False,
        "restore_executed": False,
        "restore_verified": False,
        "operational_status": OperationalStatus.BLOCKED,
        "preflight": checks,
        "owner_split": (
            "WP-23 owns this plan, the scope, the retention policy, the "
            "restore-verification procedure and the preflight command. WP-24 "
            "owns executing them and reporting what happened. Nothing in "
            "this repository has executed a backup or a restore, and no "
            "document here may be read as saying otherwise."),
        "restore_verification_procedure": (
            "A restore is verified by restoring the dump into a separate "
            "target, running the migration head check, verifying the "
            "governed audit chain end to end against its exported head "
            "sequence, and confirming that every release manifest hash "
            "referenced by a restored audit row resolves. A restore that "
            "only checked the database started is a restore that would pass "
            "with an empty audit table."),
        "not_executed_note": (
            "backup_executed, restore_executed and restore_verified are all "
            "false. They are not placeholders awaiting a flag: there is no "
            "code path in this module that sets any of them true, because "
            "setting them would require observing an execution and this "
            "module observes configuration."),
    }
