# -*- coding: utf-8 -*-
"""Wave 3B candidate capture vocabulary: one acquisition mode, one snapshot kind.

Revision ID: 0012_wave03b_candidate_capture
Revises: 0011_wp23_auth_audit
Create Date: 2026-09-06

Hand-written and reviewed, not autogenerate output. Purely additive: two check
constraints are widened by one value each, and nothing else in the schema
moves. No column changes type, no row is rewritten, no default changes.

**Why the vocabulary had to grow rather than be reused.**

``acquisition_mode`` had six values and none described what Wave 3 actually
did. ``MANUAL_DOWNLOAD`` and ``PUBLICATION_TRANSCRIPTION`` both assert a human
performed the act. ``OFFICIAL_API`` and ``LICENSED_BULK_EXPORT`` assert a
documented interface or an agreed export. ``INTERNAL_DERIVATION`` asserts no
external source was involved. ``NOT_DETERMINED`` asserts nobody decided.
Choosing any of them for an agent that opened one published page at a time
would have been a misdescription in a column whose whole job is to record how
this project is permitted to obtain records.

``snapshot_kind`` had the same problem for the same reason: ``ACQUISITION`` and
``CACHE_REPLAY`` claim a WP-04 run with retrieval metadata behind the bytes,
and ``LEGACY_IMPORT`` claims the files came from the frozen legacy probe
scripts.

**What the new values may not do.**

``AGENT_TARGETED_RETRIEVAL`` is excluded from ``AUTOMATED_ACQUISITION_MODES`` in
the domain, so it never becomes permission for unattended acquisition. It is 24
characters and fits ``source_policies.acquisition_mode``, ``String(32)``.

``TRANSCRIPTION_CAPTURE`` is 21 characters and fits ``raw_snapshots.
snapshot_kind``, ``String(24)`` - which is why it is not spelled
``SOURCE_TRANSCRIPTION_CAPTURE``, at 28.

**What is deliberately not relaxed.** Every constraint naming ``LEGACY_IMPORT``
keeps naming exactly ``LEGACY_IMPORT``. A transcription capture is therefore
subject to the ordinary rules for a non-legacy snapshot: it may be publication
eligible only when it is not quarantined, and it is not exempted from the
acquisition-run checks the way a legacy import is. That is correct - a capture
has no WP-04 run either, and the honest place to say so is its own
``limitations`` list, not an exemption borrowed from a different kind.
"""

from __future__ import annotations

from alembic import op

revision = "0012_wave03b_candidate_capture"
down_revision = "0011_wp23_auth_audit"
branch_labels = None
depends_on = None

_ACQUISITION_MODES_BEFORE = (
    "'NOT_DETERMINED', 'MANUAL_DOWNLOAD', 'OFFICIAL_API', "
    "'LICENSED_BULK_EXPORT', 'PUBLICATION_TRANSCRIPTION', "
    "'INTERNAL_DERIVATION'")
_ACQUISITION_MODES_AFTER = (
    _ACQUISITION_MODES_BEFORE + ", 'AGENT_TARGETED_RETRIEVAL'")

_SNAPSHOT_KINDS_BEFORE = "'ACQUISITION', 'CACHE_REPLAY', 'LEGACY_IMPORT'"
_SNAPSHOT_KINDS_AFTER = _SNAPSHOT_KINDS_BEFORE + ", 'TRANSCRIPTION_CAPTURE'"


def _replace_check(table: str, name: str, expression: str) -> None:
    op.drop_constraint(name, table, type_="check")
    op.create_check_constraint(name, table, expression)


def upgrade() -> None:
    _replace_check("source_policies",
                   "ck_source_policies_acquisition_mode_enum",
                   "acquisition_mode IN (%s)" % _ACQUISITION_MODES_AFTER)
    _replace_check("raw_snapshots", "ck_raw_snapshots_kind_enum",
                   "snapshot_kind IN (%s)" % _SNAPSHOT_KINDS_AFTER)


def downgrade() -> None:
    # Refuses rather than deleting. A row carrying one of the new values is a
    # real record of a real retrieval, and a downgrade that silently dropped it
    # would destroy provenance to satisfy a schema.
    connection = op.get_bind()
    for table, column, value in (
            ("source_policies", "acquisition_mode", "AGENT_TARGETED_RETRIEVAL"),
            ("raw_snapshots", "snapshot_kind", "TRANSCRIPTION_CAPTURE")):
        count = connection.exec_driver_sql(
            "SELECT count(*) FROM %s WHERE %s = '%s'" % (table, column, value)
        ).scalar()
        if count:
            raise RuntimeError(
                "refusing to downgrade: %d row(s) in %s still carry %s=%r. "
                "Reclassifying them would misdescribe how those records were "
                "obtained; remove or re-source them deliberately first."
                % (count, table, column, value))
    _replace_check("source_policies",
                   "ck_source_policies_acquisition_mode_enum",
                   "acquisition_mode IN (%s)" % _ACQUISITION_MODES_BEFORE)
    _replace_check("raw_snapshots", "ck_raw_snapshots_kind_enum",
                   "snapshot_kind IN (%s)" % _SNAPSHOT_KINDS_BEFORE)
