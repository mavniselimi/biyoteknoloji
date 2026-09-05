# -*- coding: utf-8 -*-
"""Executing the WP-23 backup and restore runbook (WP-24).

WP-23 wrote the procedure and executed none of it. This module executes it,
and it does **not** replace WP-23's status artifact: that document records
``backup_executed: false`` and is a true statement about the moment it was
written. Rewriting history to make a later run look like an earlier one is the
failure this whole project is built against. WP-24 publishes a *successor*
observation instead, and the two are read together.

The four conditions. A restore is ``VERIFIED`` only when all four hold, and
they are four rather than one because each catches a different way a restore
can appear to work:

1. **A separate target database.** Restoring into the source proves the dump
   can be read and destroys what you were protecting. A restore into the same
   database is not a verification, it is an outage with a checklist.
2. **The exact Alembic head.** A restored database at the wrong revision runs
   against a schema the application was not written for; the data survived
   and the system still cannot use it.
3. **A verified audit chain whose event count matches the separately exported
   head sequence.** The chain verifying proves the rows that are there are
   consistent with each other. The count matching a *separately* exported head
   proves none went missing - a truncated restore produces a chain that
   verifies perfectly and is short.
4. **Every referenced release manifest hash resolves.** An assessment points
   at a release; a release points at a manifest. A restore whose audit rows
   reference manifests that are not in the restored artifact set has preserved
   the claims and lost what they were based on.

``pg_restore`` exiting zero satisfies none of these on its own, and the WP-23
handoff says so explicitly.

On what counts as a backup: a dump written to a temporary directory beside the
source database is not one. It shares the disk, the host and the failure. This
module records ``destination_kind`` and refuses ``VERIFIED`` operational
status for a temporary destination - a local drill is recorded as
``LOCAL_REHEARSAL_VERIFIED``, which is a real and useful result and is not an
operational backup.
"""

from __future__ import annotations

import datetime as _dt
import os
from typing import Any, Mapping, Optional, Sequence

from pgx.deployment.vocabulary import ExecutionState, blocker

__all__ = [
    "BACKUP_EXECUTION_VERSION",
    "LOCAL_REHEARSAL_VERIFIED",
    "RESTORE_CONDITIONS",
    "backup_execution_status",
    "evaluate_restore",
]

BACKUP_EXECUTION_VERSION = "pgx-wp24-backup-execution/1"

#: The label a local drill carries. Distinct from ``VERIFIED`` on purpose and
#: spelled once so a document, a CLI and a test cannot disagree about it.
LOCAL_REHEARSAL_VERIFIED = "LOCAL_REHEARSAL_VERIFIED"

#: The four conditions, in the order the runbook states them.
RESTORE_CONDITIONS: Sequence[Mapping[str, str]] = (
    {"condition_id": "RESTORE-01",
     "title": "restored into a separate target database",
     "why": "restoring into the source proves the dump is readable and "
            "destroys the thing being protected"},
    {"condition_id": "RESTORE-02",
     "title": "the restored database is at the exact expected Alembic head",
     "why": "data that survived into a schema the application was not "
            "written for is data the system cannot use"},
    {"condition_id": "RESTORE-03",
     "title": "the governed audit chain verifies and its event count matches "
              "the separately exported head sequence",
     "why": "a truncated restore produces a chain that verifies perfectly "
            "and is short; only the separately exported head catches it"},
    {"condition_id": "RESTORE-04",
     "title": "every referenced release manifest hash resolves against the "
              "restored immutable manifests",
     "why": "a restore that kept the claims and lost what they were based "
            "on has preserved nothing that can be defended"},
)

#: Destinations that are not backups. A dump beside the database it came from
#: shares the disk, the host and the failure.
_TEMPORARY_PREFIXES = ("/tmp", "/var/tmp", "/dev/shm")


def _destination_kind(destination: Optional[str]) -> str:
    if not destination:
        return "none"
    normalised = os.path.abspath(destination)
    if any(normalised.startswith(prefix) for prefix in _TEMPORARY_PREFIXES):
        return "temporary"
    if "://" in str(destination):
        return "remote"
    return "local_path"


def evaluate_restore(*, separate_target: Optional[bool] = None,
                     restored_head: Optional[str] = None,
                     expected_head: Optional[str] = None,
                     chain_verified: Optional[bool] = None,
                     restored_event_count: Optional[int] = None,
                     exported_head_sequence: Optional[int] = None,
                     unresolved_manifest_hashes: Optional[Sequence[str]]
                     = None,
                     referenced_manifest_count: Optional[int] = None
                     ) -> Mapping[str, object]:
    """Check the four conditions. Each reports ``True``, ``False`` or ``None``.

    ``None`` means the condition was not evaluated - which is not a pass and
    not a failure. A restore report with an unevaluated condition is a report
    whose verification is incomplete, and collapsing that into ``False`` would
    make it indistinguishable from a condition that was checked and failed.
    """
    checks = []

    checks.append({
        **RESTORE_CONDITIONS[0], "satisfied": separate_target,
        "detail": ("the restore target was a separate database"
                   if separate_target else
                   "not evaluated" if separate_target is None else
                   "the restore was performed into the source database")})

    head_ok: Optional[bool]
    if restored_head is None or expected_head is None:
        head_ok = None
        head_detail = "not evaluated"
    else:
        head_ok = restored_head == expected_head
        head_detail = ("at %s" % restored_head if head_ok
                       else "restored at %s, expected %s"
                       % (restored_head, expected_head))
    checks.append({**RESTORE_CONDITIONS[1], "satisfied": head_ok,
                   "detail": head_detail})

    chain_ok: Optional[bool]
    if chain_verified is None or restored_event_count is None \
            or exported_head_sequence is None:
        chain_ok = None
        chain_detail = "not evaluated"
    else:
        counts_agree = restored_event_count == exported_head_sequence
        chain_ok = bool(chain_verified) and counts_agree
        chain_detail = (
            "chain verified and %d events match the exported head sequence"
            % restored_event_count if chain_ok else
            "chain verified but %d events do not match the exported head "
            "sequence %d" % (restored_event_count, exported_head_sequence)
            if chain_verified else "the chain did not verify")
    checks.append({**RESTORE_CONDITIONS[2], "satisfied": chain_ok,
                   "detail": chain_detail})

    manifests_ok: Optional[bool]
    if unresolved_manifest_hashes is None:
        manifests_ok = None
        manifest_detail = "not evaluated"
    else:
        manifests_ok = not list(unresolved_manifest_hashes)
        manifest_detail = (
            "all %s referenced manifests resolved"
            % (referenced_manifest_count if referenced_manifest_count
               is not None else "of the")
            if manifests_ok else
            "%d referenced manifest hashes did not resolve"
            % len(list(unresolved_manifest_hashes)))
    checks.append({**RESTORE_CONDITIONS[3], "satisfied": manifests_ok,
                   "detail": manifest_detail})

    satisfied = [item for item in checks if item["satisfied"] is True]
    unevaluated = [item for item in checks if item["satisfied"] is None]
    return {
        "conditions": checks,
        "condition_count": len(checks),
        "satisfied_count": len(satisfied),
        "unevaluated_count": len(unevaluated),
        "all_satisfied": len(satisfied) == len(checks),
        "note": (
            "All four, or the restore is not verified. pg_restore exiting "
            "zero satisfies none of them: it says the archive was readable."),
    }


def backup_execution_status(*, destination: Optional[str] = None,
                            backup_taken: bool = False,
                            encrypted_at_rest: Optional[bool] = None,
                            includes_audit_export: bool = False,
                            includes_artifact_manifests: bool = False,
                            includes_restricted_holdout: Optional[bool]
                            = None,
                            restore: Optional[Mapping[str, Any]] = None,
                            local_rehearsal: bool = False,
                            now: Optional[_dt.datetime] = None
                            ) -> Mapping[str, object]:
    """The WP-24 successor observation. Never a rewrite of WP-23's artifact.

    ``includes_restricted_holdout`` is ``None`` when no restricted storage
    exists to capture. It is deliberately not ``False``: "there is nothing to
    back up" and "there was something and we did not back it up" are different
    facts, and creating an empty directory to call it captured would be the
    third and worst option.
    """
    kind = _destination_kind(destination)
    evaluation = dict(restore or evaluate_restore())
    blockers = []

    if not backup_taken:
        blockers.append(dict(blocker(
            "DEPLOY_BACKUP_NOT_EXECUTED",
            owner="WP-24 operation on a host with a database and a "
                  "destination",
            detail="no backup has been taken").to_json()))
    elif kind == "temporary":
        blockers.append(dict(blocker(
            "DEPLOY_BACKUP_NOT_EXECUTED",
            owner="whoever provisions backup storage",
            detail=("the destination is a temporary directory; it shares the "
                    "disk, the host and the failure with the database it "
                    "came from, so it is a drill artifact and not a backup")
        ).to_json()))
    if not evaluation.get("all_satisfied"):
        blockers.append(dict(blocker(
            "DEPLOY_RESTORE_NOT_VERIFIED",
            owner="WP-24 operation",
            detail=("%d of %d runbook conditions are satisfied and %d were "
                    "not evaluated"
                    % (evaluation.get("satisfied_count", 0),
                       evaluation.get("condition_count", 4),
                       evaluation.get("unevaluated_count", 4)))).to_json()))

    if evaluation.get("all_satisfied") and local_rehearsal:
        state = ExecutionState.TEST_ONLY_REHEARSAL
        operational = LOCAL_REHEARSAL_VERIFIED
    elif evaluation.get("all_satisfied") and kind in ("remote", "local_path"):
        state = ExecutionState.VERIFIED
        operational = "VERIFIED"
    elif backup_taken:
        state = ExecutionState.EXECUTED
        operational = "BLOCKED"
    else:
        state = ExecutionState.BLOCKED
        operational = "BLOCKED"

    return {
        "backup_execution_version": BACKUP_EXECUTION_VERSION,
        "state": state.value,
        "operational_status": operational,
        "supersedes": "data/security/wp23-backup-restore-status.json",
        "supersedes_note": (
            "A successor observation, not a replacement. WP-23's artifact "
            "records backup_executed: false and is a true statement about "
            "when it was written; rewriting it to match a later run is the "
            "failure this project is built against."),
        "backup_executed": backup_taken,
        # The destination KIND, never the destination. A path can name a host,
        # a bucket, an account or a customer.
        "destination_kind": kind,
        "encrypted_at_rest": encrypted_at_rest,
        "scope": {
            "postgresql_dump": backup_taken,
            "separate_audit_export_and_head": includes_audit_export,
            "immutable_artifact_manifests": includes_artifact_manifests,
            "restricted_holdout_storage": includes_restricted_holdout,
        },
        "restricted_holdout_note": (
            "null means no restricted holdout storage exists to capture. It "
            "is not false: 'there is nothing to back up' and 'there was "
            "something and we did not' are different facts, and creating an "
            "empty directory to call it captured would be worse than both."),
        "restore_verification": evaluation,
        "restore_verified": bool(evaluation.get("all_satisfied")),
        "local_rehearsal": local_rehearsal,
        "observed_at": (now.isoformat() if now else
                        (_dt.datetime.now(_dt.timezone.utc).isoformat()
                         if backup_taken else None)),
        "blockers": blockers,
        "no_secret_is_reported": (
            "No DSN, path, credential or encryption key appears in this "
            "document. The destination is reported as a kind, because a path "
            "can name a host, a bucket, an account or a customer."),
    }
