#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline activation and rollback drill (WP-03).

    python3 scripts/release_drill.py

Runs the release service end to end against the in-memory unit of work and
prints what happened at each step. It is evidence that the *rules and the
sequencing* are right - and nothing more than that.

**This is not a PostgreSQL drill.** No database is involved, so it proves
nothing about ``SELECT ... FOR UPDATE``, about transaction isolation, or about
the CHECK constraints and the append-only trigger. Those need a real server,
and WP-03 records them as BLOCKED. Presenting this output as transactional or
locking evidence would be a false claim; the header printed below says so too.

Standard library only.
"""

from __future__ import annotations

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from pgx.application.legacy_baseline import register_legacy_baseline  # noqa: E402
from pgx.application.release_service import (  # noqa: E402
    ReleaseNotActivatableError, ReleaseService, RollbackNotPermittedError,
)
from pgx.domain.enums import DatasetStatus  # noqa: E402
from tests.unit.application._scenario import (  # noqa: E402
    CountingEventIds, Scenario, StepClock,
)

ACTOR = "ops@example.org"


def _rule(title: str) -> None:
    print("\n" + title)
    print("-" * len(title))


def _pointer(store) -> str:
    pointer = store.pointer
    name = "none"
    if pointer.release_id is not None:
        name = str(store.releases[pointer.release_id].public_id)
    return "active=%s generation=%d updated_by=%s" % (
        name, pointer.generation, pointer.updated_by)


def main() -> int:
    """Run the drill and print a transcript."""
    print("=" * 78)
    print("WP-03 OFFLINE RELEASE DRILL")
    print("=" * 78)
    print("In-memory unit of work. No PostgreSQL, no transaction, no row lock.")
    print("Proves the compatibility rules, the audit trail and the rollback")
    print("contract. Does NOT prove locking, isolation, CHECK constraints or the")
    print("append-only trigger - those are BLOCKED without a real server.")

    scenario = Scenario()
    store = scenario.world.store
    service = ReleaseService(scenario.world.factory, clock=StepClock(),
                             new_event_id=CountingEventIds())
    first = scenario.release
    second = scenario.add_release("PGX-REL-20260829-002")

    _rule("1. Initial state")
    print("  %s" % _pointer(store))
    print("  releases: %s" % ", ".join(
        sorted(str(item.public_id) for item in store.releases.values())))

    _rule("2. Validate the first release")
    report = service.validate_release(first.id)
    print("  compatible: %s" % report.is_compatible)
    print("  problems  : %s" % (list(report.codes()) or "none"))

    _rule("3. Activate it")
    result = service.activate_release(first.id, ACTOR, "initial release")
    print("  changed=%s generation=%d audit_event=%s"
          % (result.changed, result.generation, result.audit_event_id))
    print("  %s" % _pointer(store))
    print("  first release status: %s" % store.releases[first.id].status.value)

    _rule("4. Re-activate the same release (idempotent no-op)")
    repeat = service.activate_release(first.id, ACTOR, "re-run the deploy step")
    print("  changed=%s generation=%d audit_event=%s"
          % (repeat.changed, repeat.generation, repeat.audit_event_id))
    print("  audit events so far: %d" % len(store.audit))

    _rule("5. Activate the second release")
    result = service.activate_release(second.id, ACTOR, "promote the next build")
    print("  changed=%s generation=%d" % (result.changed, result.generation))
    print("  %s" % _pointer(store))
    print("  first  -> %s" % store.releases[first.id].status.value)
    print("  second -> %s" % store.releases[second.id].status.value)

    _rule("6. Reject an incompatible release")
    import dataclasses
    from pgx.domain.identifiers import SoftwareVersionId

    broken = scenario.add_release("PGX-REL-20260829-003")
    store.releases[broken.id] = dataclasses.replace(
        broken, software_version_id=SoftwareVersionId.new())
    before = (store.pointer.generation, len(store.audit))
    try:
        service.activate_release(broken.id, ACTOR, "should not happen")
        print("  *** ACTIVATED - THIS IS A DEFECT ***")
    except ReleaseNotActivatableError as exc:
        print("  refused: %s" % ", ".join(exc.report.codes()))
    after = (store.pointer.generation, len(store.audit))
    print("  generation %d -> %d, audit events %d -> %d (both unchanged)"
          % (before[0], after[0], before[1], after[1]))
    print("  %s" % _pointer(store))

    _rule("7. Roll back to the first release")
    result = service.rollback_release(first.id, ACTOR, "regression found")
    print("  changed=%s generation=%d" % (result.changed, result.generation))
    print("  previous=%s new=%s" % (result.previous_release_id, result.release_id))
    print("  %s" % _pointer(store))
    print("  first  -> %s" % store.releases[first.id].status.value)
    print("  second -> %s" % store.releases[second.id].status.value)

    _rule("8. Refuse a rollback to a release that never ran")
    try:
        service.rollback_release(broken.id, ACTOR, "should not happen")
        print("  *** ROLLED BACK - THIS IS A DEFECT ***")
    except RollbackNotPermittedError as exc:
        print("  refused: %s" % exc)

    _rule("9. Immutable artifacts after the rollback")
    for label, release_id in (("first", first.id), ("second", second.id)):
        release = store.releases[release_id]
        print("  %-6s %s manifest_hash=%s"
              % (label, release.public_id, release.manifest_hash))
    print("  ruleset membership: %d rule(s), unchanged"
          % store.rulesets[scenario.ruleset.id].member_count)
    print("  dataset status    : %s"
          % store.datasets[scenario.dataset.id].status.value)

    _rule("10. Register the legacy baseline (comparison only)")
    legacy = register_legacy_baseline(
        uow_factory=scenario.world.factory,
        software_version_id=scenario.software.id, actor=ACTOR,
        clock=StepClock(), new_event_id=CountingEventIds())
    print("  created=%s public_id=%s" % (legacy.created, legacy.release_public_id))
    print("  wp01_manifest_hash=%s" % legacy.wp01_manifest_hash)
    legacy_release = next(item for item in store.releases.values()
                          if str(item.public_id) == legacy.release_public_id)
    print("  status=%s  ruleset members=%d"
          % (legacy_release.status.value,
             store.rulesets[legacy_release.ruleset_version_id].member_count))
    try:
        service.activate_release(legacy_release.id, ACTOR, "should not happen")
        print("  *** ACTIVATED - THIS IS A DEFECT ***")
    except ReleaseNotActivatableError as exc:
        print("  activation refused: %s" % ", ".join(exc.report.codes()))

    _rule("11. Audit trail")
    for event in reversed(store.audit):
        print("  %s  %-26s actor=%s" % (event.occurred_at.isoformat(),
                                        event.action.value, event.actor))
        print("      previous=%s new=%s"
              % (event.previous_release_id, event.new_release_id))

    _rule("12. Final state")
    print("  %s" % _pointer(store))
    print("  audit events: %d" % len(store.audit))
    print("\nDrill complete. Offline evidence only.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
