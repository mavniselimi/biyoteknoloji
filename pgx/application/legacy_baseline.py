# -*- coding: utf-8 -*-
"""Registering the WP-01 legacy seed as a comparison-only baseline (WP-03).

The legacy MVP produced a dataset and a rule table. WP-01 froze them and hashed
them; WP-03 needs to be able to *refer* to that state - "this is what the old
system had" - without any of it becoming operational.

What this registration is, precisely:

* a **dataset version** in ``RETIRED`` status, carrying the WP-01 manifest hash;
* a **ruleset version** in ``RETIRED`` status with **empty membership**;
* a **release bundle** in ``RETIRED`` status pinning the two, plus the software
  build that performed the registration.

And what it is not, enforced rather than merely stated:

* **No legacy row becomes a rule.** The 3,084 legacy CSV rows are not read, not
  converted, and not imported. The ruleset pins *no* rules, so nothing in it can
  execute - and the release compatibility checks would refuse it anyway, twice
  over: a ``RETIRED`` release fails rule 13, and an empty ruleset fails rule 6.
* **It is never active.** ``RETIRED`` is terminal, so
  :meth:`~pgx.application.release_service.ReleaseService.activate_release` and
  ``rollback_release`` both refuse it. The active pointer cannot be aimed here.
* **It claims no scientific approval.** ``approved_by`` names this registration
  process, not a scientist, and the text says so.

Registration is idempotent, keyed by public identifier: running it twice
registers nothing the second time and reports what already existed. That makes
it safe in a deploy script, which is where it will actually be run.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import io
import json
import os
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional

from pgx.domain.enums import AuditAction, DatasetStatus, ReleaseStatus, RulesetStatus
from pgx.domain.hashing import sha256_digest
from pgx.domain.identifiers import (
    AuditEventId,
    DatasetPublicId,
    DatasetVersionId,
    ReleaseBundleId,
    ReleasePublicId,
    RulesetPublicId,
    RulesetVersionId,
)
from pgx.domain.models import AuditEvent, DatasetVersion, ReleaseBundle, RulesetVersion
from pgx.domain.ports import UnitOfWork
from pgx.domain.release_manifest import build_release_manifest, manifest_digest

__all__ = [
    "LEGACY_BASELINE_NOTE",
    "LEGACY_DATASET_PUBLIC_ID",
    "LEGACY_RELEASE_PUBLIC_ID",
    "LEGACY_RULESET_PUBLIC_ID",
    "LegacyBaselineResult",
    "register_legacy_baseline",
    "wp01_manifest_hash",
]

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

#: The WP-01 baseline manifest this registration refers to. Read, never written.
WP01_MANIFEST_PATH = os.path.join(_REPO_ROOT, "data", "legacy-baseline", "manifest.json")

#: Fixed public identifiers, so registration is idempotent by lookup.
LEGACY_DATASET_PUBLIC_ID = "PGX-DATA-20260829-999"
LEGACY_RULESET_PUBLIC_ID = "PGX-RULESET-20260829-999"
LEGACY_RELEASE_PUBLIC_ID = "PGX-REL-20260829-999"

#: The limitation, recorded on every row this creates. It is not decoration:
#: anyone reading these records needs to know what they may not be used for.
LEGACY_BASELINE_NOTE = (
    "HISTORICAL COMPARISON ONLY. This record refers to the WP-01 legacy MVP "
    "baseline. It contains no imported legacy rows, pins no executable rules, "
    "carries no scientific validation or approval, and is RETIRED so it can "
    "never be activated. It exists so later work can compare V2 output against "
    "what the legacy system produced."
)

#: Recorded in the approval fields. It names a process, not a person, and the
#: text is deliberately unmistakable: this is not a scientific approval.
LEGACY_APPROVAL_ACTOR = "system:wp03-legacy-baseline-registration (NOT a scientific approval)"

#: A fixed instant, so re-registering produces identical rows rather than rows
#: that differ only by when the command happened to run.
LEGACY_BASELINE_EPOCH = _dt.datetime(2026, 1, 1, 0, 0, 0, tzinfo=_dt.timezone.utc)


def wp01_manifest_hash(path: str = WP01_MANIFEST_PATH) -> str:
    """Return the canonical digest of the WP-01 baseline manifest.

    The file is read and hashed; it is never modified. The digest is what ties
    this registration to a specific frozen baseline: if the WP-01 manifest ever
    changed, this hash would change with it and the mismatch would be visible.
    """
    with io.open(path, "rb") as handle:
        raw = handle.read()
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _wp01_facts(path: str = WP01_MANIFEST_PATH) -> Mapping[str, Any]:
    """Return a small, non-scientific summary of the frozen baseline."""
    with io.open(path, encoding="utf-8") as handle:
        document = json.load(handle)
    return {
        "baseline_id": document.get("baseline_id"),
        "captured_at_utc": document.get("captured_at_utc"),
        "schema_version": document.get("schema_version"),
        "legacy_artifact_count": len(document.get("artifacts", [])),
        "evidence_artifact_count": len(document.get("evidence_artifacts", [])),
    }


@dataclass(frozen=True)
class LegacyBaselineResult:
    """What a registration attempt did."""

    created: bool
    dataset_public_id: str
    ruleset_public_id: str
    release_public_id: str
    release_id: Optional[str]
    wp01_manifest_hash: str
    note: str

    def to_json(self) -> Mapping[str, object]:
        """Machine-readable form for the CLI."""
        return {
            "action": "register-legacy-baseline",
            "created": self.created,
            "dataset_public_id": self.dataset_public_id,
            "ruleset_public_id": self.ruleset_public_id,
            "release_public_id": self.release_public_id,
            "release_id": self.release_id,
            "wp01_manifest_hash": self.wp01_manifest_hash,
            "status": ReleaseStatus.RETIRED.value,
            "executable": False,
            "note": self.note,
        }


def register_legacy_baseline(
    uow_factory: Callable[[], UnitOfWork],
    software_version_id,
    actor: str,
    clock: Callable[[], _dt.datetime] = lambda: _dt.datetime.now(_dt.timezone.utc),
    new_event_id: Callable[[], AuditEventId] = AuditEventId.new,
    manifest_path: str = WP01_MANIFEST_PATH,
) -> LegacyBaselineResult:
    """Register the legacy baseline, or report that it already exists.

    Idempotent by public identifier: a second run creates nothing, writes no
    second audit event, and returns ``created=False``.

    Args:
        uow_factory: Returns a fresh unit of work.
        software_version_id: The registered build performing the registration.
        actor: Who ran this. Recorded on the audit event.
        clock: Injected so the audit timestamp is assertable.
        new_event_id: Injected so the audit identity is assertable.
        manifest_path: The WP-01 baseline manifest to read and hash.
    """
    baseline_hash = wp01_manifest_hash(manifest_path)
    facts = _wp01_facts(manifest_path)

    with uow_factory() as uow:
        existing = uow.releases.get_by_public_id(ReleasePublicId(LEGACY_RELEASE_PUBLIC_ID))
        if existing is not None:
            return LegacyBaselineResult(
                created=False,
                dataset_public_id=LEGACY_DATASET_PUBLIC_ID,
                ruleset_public_id=LEGACY_RULESET_PUBLIC_ID,
                release_public_id=LEGACY_RELEASE_PUBLIC_ID,
                release_id=existing.id.to_json(),
                wp01_manifest_hash=baseline_hash,
                note=LEGACY_BASELINE_NOTE,
            )

        dataset = DatasetVersion(
            id=DatasetVersionId.new(),
            public_id=DatasetPublicId(LEGACY_DATASET_PUBLIC_ID),
            # RETIRED, never PUBLISHED: a PUBLISHED dataset is one a release may
            # be activated against, and this one may not.
            status=DatasetStatus.RETIRED,
            manifest_hash=baseline_hash,
            created_at=LEGACY_BASELINE_EPOCH,
            legacy_id=str(facts.get("baseline_id")),
        )

        ruleset = RulesetVersion(
            id=RulesetVersionId.new(),
            public_id=RulesetPublicId(LEGACY_RULESET_PUBLIC_ID),
            # RETIRED with empty membership. Not FROZEN: a FROZEN ruleset is
            # release-eligible, and the legacy rules were never validated.
            status=RulesetStatus.RETIRED,
            manifest_hash=baseline_hash,
            created_at=LEGACY_BASELINE_EPOCH,
            rule_ids=(),
            legacy_id=str(facts.get("baseline_id")),
        )

        uow.dataset_versions.add(dataset)
        uow.ruleset_versions.add(ruleset)

        software = uow.software_versions.get(software_version_id)
        if software is None:
            raise ValueError(
                "software version %s is not registered; register the build "
                "before registering the legacy baseline against it"
                % software_version_id)

        manifest = build_release_manifest(
            release_public_id=ReleasePublicId(LEGACY_RELEASE_PUBLIC_ID),
            software=software,
            dataset=dataset,
            ruleset=ruleset,
        )
        release = ReleaseBundle(
            id=ReleaseBundleId.new(),
            public_id=ReleasePublicId(LEGACY_RELEASE_PUBLIC_ID),
            software_version_id=software.id,
            dataset_version_id=dataset.id,
            ruleset_version_id=ruleset.id,
            manifest=manifest,
            manifest_hash=manifest_digest(manifest),
            # RETIRED is terminal: activate_release and rollback_release both
            # refuse it, so the active pointer can never be aimed here.
            status=ReleaseStatus.RETIRED,
            created_at=LEGACY_BASELINE_EPOCH,
            legacy_id=str(facts.get("baseline_id")),
            notes=LEGACY_BASELINE_NOTE,
        )
        uow.releases.add(release)

        uow.audit.append(AuditEvent(
            id=new_event_id(),
            action=AuditAction.LEGACY_BASELINE_REGISTERED,
            actor=actor,
            object_type="release_bundle",
            object_id=release.id.to_json(),
            occurred_at=clock(),
            reason=LEGACY_BASELINE_NOTE,
            previous_release_id=None,
            new_release_id=None,
            metadata={
                "release_public_id": LEGACY_RELEASE_PUBLIC_ID,
                "wp01_manifest_hash": baseline_hash,
                "wp01_baseline_id": facts.get("baseline_id"),
                "legacy_artifact_count": facts.get("legacy_artifact_count"),
                "evidence_artifact_count": facts.get("evidence_artifact_count"),
                "imported_legacy_rule_rows": 0,
                "executable": False,
                "comparison_only": True,
            },
        ))
        uow.commit()

        return LegacyBaselineResult(
            created=True,
            dataset_public_id=LEGACY_DATASET_PUBLIC_ID,
            ruleset_public_id=LEGACY_RULESET_PUBLIC_ID,
            release_public_id=LEGACY_RELEASE_PUBLIC_ID,
            release_id=release.id.to_json(),
            wp01_manifest_hash=baseline_hash,
            note=LEGACY_BASELINE_NOTE,
        )
