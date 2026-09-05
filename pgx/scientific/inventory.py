# -*- coding: utf-8 -*-
"""Deterministic inventory of the source values already in legacy files (WP-05).

Standard library plus ``pgx.domain`` and :mod:`pgx.scientific`.

**Read-only, always.** Nothing here opens a legacy file for writing. The MVP
CSVs are frozen WP-01 baseline artefacts; this module counts what is in them
and says so.

**An allowlist, not a heuristic.** :data:`LEGACY_SOURCE_COLUMNS` names every
(file, column) pair that actually carries a scientific source value. A column is
scanned because somebody checked it, never because its name contains the
substring ``source``. Two columns in this repository are named ``source`` and
``source_drug`` and carry drug names; they are listed in
:data:`EXCLUDED_COLUMNS` with the reason, so the exclusion is a recorded
decision rather than an oversight.

**Exact text, preserved.** Values are counted verbatim. ``report/pair:``
``variantAnnotation`` and ``report/pair:VariantAnnotation`` both occur in the
legacy outputs and are reported as two distinct values, because they are two
distinct strings and this module has no authority to decide they mean the same
thing. Case-variant groups are *reported* under
:attr:`LegacySourceInventory.observations` so a human can decide; they are never
merged.

**Byte-identical on re-run.** The output carries no wall-clock timestamp. What
it does carry is a SHA-256 of every input file, so a stale inventory is
detectable without making the inventory itself change every time it is
generated. Two runs over unchanged inputs produce the same bytes; that is what
makes a diff in this file mean the *data* changed.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from pgx.domain.hashing import sha256_digest
from pgx.scientific.errors import LegacyInventoryError
from pgx.scientific.validation import (
    IssueSeverity,
    PolicyIssue,
    PolicyIssueCode,
    sort_issues,
)

__all__ = [
    "EXCLUDED_COLUMNS",
    "LEGACY_SOURCE_COLUMNS",
    "LEGACY_INVENTORY_SCHEMA_VERSION",
    "LegacyColumn",
    "LegacyExclusion",
    "LegacySourceInventory",
    "LegacySourceValue",
    "SourceValueKind",
    "build_inventory",
    "unregistered_legacy_values",
]

LEGACY_INVENTORY_SCHEMA_VERSION = "pgx-legacy-source-inventory/1"

#: CSV field size ceiling. The legacy annotation files carry long free-text
#: excerpts; the stdlib default would raise on them.
_CSV_FIELD_LIMIT = 4 * 1024 * 1024


class SourceValueKind(str, Enum):
    """What kind of source value a column carries.

    Kept because the three are answerable by different evidence: a source
    *name* is a body, a source *container* is an endpoint or file within a
    provider's data, and an allele-function source is a specific scientific
    attribution.
    """

    #: The name of the body that published the record (``CPIC``, ``DPWG``).
    SOURCE_NAME = "SOURCE_NAME"
    #: The provider-internal container the record came from
    #: (``data/guidelineAnnotation``).
    SOURCE_CONTAINER = "SOURCE_CONTAINER"
    #: Attribution for an allele-function assignment.
    ALLELE_FUNCTION_SOURCE = "ALLELE_FUNCTION_SOURCE"

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class LegacyColumn:
    """One (file, column) pair that carries scientific source values."""

    relative_path: str
    column: str
    kind: SourceValueKind
    note: str

    @property
    def label(self) -> str:
        """``path::column``, the identity used throughout the report."""
        return "%s::%s" % (self.relative_path, self.column)

    def to_json(self) -> Dict[str, str]:
        return {
            "file": self.relative_path,
            "column": self.column,
            "kind": self.kind.value,
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class LegacyExclusion:
    """A column that *looks* like a source column and is not one."""

    relative_path: str
    column: str
    reason: str

    @property
    def label(self) -> str:
        return "%s::%s" % (self.relative_path, self.column)

    def to_json(self) -> Dict[str, str]:
        return {
            "file": self.relative_path,
            "column": self.column,
            "reason": self.reason,
        }


#: Every column scanned, and why. Adding a file means adding a line here.
LEGACY_SOURCE_COLUMNS: Tuple[LegacyColumn, ...] = (
    LegacyColumn(
        "clinpgx_mvp_seed/drug_gene_guidelines.csv", "source",
        SourceValueKind.SOURCE_NAME,
        "guideline-issuing body as recorded by the legacy cleaner"),
    LegacyColumn(
        "clinpgx_mvp_seed/drug_gene_guidelines.csv", "source_container",
        SourceValueKind.SOURCE_CONTAINER,
        "provider container the guideline annotation was read from"),
    LegacyColumn(
        "clinpgx_mvp_seed/phenotype_effect_rules.csv", "source_container",
        SourceValueKind.SOURCE_CONTAINER,
        "provider container the variant annotation was read from"),
    LegacyColumn(
        "clinpgx_mvp_seed/supported_genes.csv", "alleleFunctionSource",
        SourceValueKind.ALLELE_FUNCTION_SOURCE,
        "attribution for the allele-function assignment"),
    LegacyColumn(
        "clinpgx_outputs_v2/guideline_annotation_rows.csv", "source_hint",
        SourceValueKind.SOURCE_CONTAINER,
        "probe-recorded container for guideline annotation rows"),
    LegacyColumn(
        "clinpgx_outputs_v2/pair_annotation_rows.csv", "source_hint",
        SourceValueKind.SOURCE_CONTAINER,
        "probe-recorded container for pair annotation rows"),
    LegacyColumn(
        "clinpgx_outputs_v2/variant_annotation_filtered_rows.csv", "source_hint",
        SourceValueKind.SOURCE_CONTAINER,
        "probe-recorded container for filtered variant annotation rows"),
    LegacyColumn(
        "clinpgx_outputs_v2/mvp_candidate_drug_gene_edges.csv", "edge_source",
        SourceValueKind.SOURCE_CONTAINER,
        "provider container each candidate drug-gene edge was derived from"),
    LegacyColumn(
        "clinpgx_outputs_v2/resolved_genes.csv", "alleleFunctionSource",
        SourceValueKind.ALLELE_FUNCTION_SOURCE,
        "attribution for the allele-function assignment"),
)

#: Columns whose names suggest a source and whose contents are something else.
#: Recorded rather than silently skipped: a reader must be able to see that the
#: omission was a decision.
EXCLUDED_COLUMNS: Tuple[LegacyExclusion, ...] = (
    LegacyExclusion(
        "drug_graph_edges.csv", "source",
        "graph edge origin node - carries a drug name such as 'clopidogrel', "
        "not a scientific source. Counting it would invent sources named after "
        "medicines."),
    LegacyExclusion(
        "candidate_alternatives.csv", "source_drug",
        "the drug an alternative is proposed for, not a source of evidence."),
    LegacyExclusion(
        "clinpgx_mvp_seed/drug_gene_guidelines.csv", "literature_titles",
        "bibliographic titles of cited papers. These are citations belonging to "
        "a source, not sources the project acquires from."),
)


@dataclass(frozen=True, slots=True)
class LegacySourceValue:
    """One distinct source value, exactly as it appears in the legacy files."""

    value: str
    kind: SourceValueKind
    occurrences: int
    columns: Tuple[str, ...]

    @property
    def is_blank(self) -> bool:
        """True when the legacy cell was empty or whitespace only.

        Reported rather than dropped: a row whose source is blank is a row whose
        provenance is unknown, and that is a finding.
        """
        return not self.value.strip()

    def to_json(self) -> Dict[str, Any]:
        return {
            "value": self.value,
            "kind": self.kind.value,
            "occurrences": self.occurrences,
            "columns": list(self.columns),
            "blank": self.is_blank,
        }


@dataclass(frozen=True)
class LegacySourceInventory:
    """Everything found, plus what was scanned to find it.

    Carries no generation timestamp. Two runs over unchanged inputs must
    produce identical bytes, and a timestamp would make every run a diff.
    Staleness is detectable from ``input_digests`` instead.
    """

    schema_version: str
    values: Tuple[LegacySourceValue, ...]
    columns_scanned: Tuple[LegacyColumn, ...]
    exclusions: Tuple[LegacyExclusion, ...]
    input_digests: Mapping[str, str]
    missing_inputs: Tuple[str, ...]
    observations: Tuple[str, ...]

    def __post_init__(self) -> None:
        # A frozen dataclass holding a plain dict is not immutable, and a
        # mutated digest would make a stale inventory look current.
        object.__setattr__(
            self, "input_digests",
            MappingProxyType(dict(sorted(self.input_digests.items()))))

    @property
    def distinct_value_count(self) -> int:
        return len(self.values)

    @property
    def total_occurrences(self) -> int:
        return sum(value.occurrences for value in self.values)

    def values_of_kind(self, kind: SourceValueKind) -> Tuple[LegacySourceValue, ...]:
        return tuple(value for value in self.values if value.kind is kind)

    def to_json(self) -> Dict[str, Any]:
        """Canonical plain-JSON form. Every collection is already sorted."""
        return {
            "schema_version": self.schema_version,
            "columns_scanned": [column.to_json() for column in self.columns_scanned],
            "excluded_columns": [item.to_json() for item in self.exclusions],
            "input_digests": dict(sorted(self.input_digests.items())),
            "missing_inputs": list(self.missing_inputs),
            "totals": {
                "distinct_values": self.distinct_value_count,
                "total_occurrences": self.total_occurrences,
                "columns_scanned": len(self.columns_scanned),
            },
            "observations": list(self.observations),
            "values": [value.to_json() for value in self.values],
        }

    def content_hash(self) -> str:
        return sha256_digest(self.to_json())

    def render_json(self) -> str:
        """Exact file text: two-space indent, one trailing newline."""
        return json.dumps(self.to_json(), indent=2, ensure_ascii=False,
                          sort_keys=False) + "\n"


def _read_rows(path: str, relative: str) -> Tuple[List[Mapping[str, str]], List[str]]:
    """Return the rows and header of one legacy CSV.

    Raises rather than skipping an unreadable file: an inventory that silently
    omitted an input would look complete while being wrong.
    """
    try:
        with io.open(path, encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            fieldnames = list(reader.fieldnames or ())
            rows = [dict(row) for row in reader]
    except OSError as exc:
        raise LegacyInventoryError(
            "cannot read legacy input %s: %s" % (relative, exc)) from exc
    except (csv.Error, UnicodeDecodeError) as exc:
        raise LegacyInventoryError(
            "legacy input %s could not be parsed as UTF-8 CSV: %s"
            % (relative, exc)) from exc
    return rows, fieldnames


def _digest_file(path: str) -> str:
    """SHA-256 of the file's bytes, in the project's canonical spelling."""
    digest = hashlib.sha256()
    with io.open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def build_inventory(
    repo_root: str,
    columns: Sequence[LegacyColumn] = LEGACY_SOURCE_COLUMNS,
    exclusions: Sequence[LegacyExclusion] = EXCLUDED_COLUMNS,
) -> LegacySourceInventory:
    """Scan the legacy files and return what is there.

    Args:
        repo_root: repository root the relative paths are resolved against.
        columns: the (file, column) allowlist to scan.
        exclusions: columns deliberately not scanned, recorded in the output.

    Returns:
        A :class:`LegacySourceInventory`. Deterministic: values are sorted by
        kind, then by the exact value text, and every nested collection is
        sorted too.

    Raises:
        LegacyInventoryError: an input exists but cannot be read or parsed, or
            a listed column is absent from a file that does exist. A missing
            *file* is recorded in ``missing_inputs`` rather than raising, so the
            inventory still runs in a checkout without the optional probe
            outputs.
    """
    counters: Dict[Tuple[str, str], int] = {}
    kinds: Dict[Tuple[str, str], SourceValueKind] = {}
    column_sets: Dict[Tuple[str, str], set] = {}
    digests: Dict[str, str] = {}
    missing: List[str] = []
    observations: List[str] = []

    previous_limit = csv.field_size_limit()
    csv.field_size_limit(_CSV_FIELD_LIMIT)
    try:
        for column in sorted(columns, key=lambda item: item.label):
            path = os.path.join(repo_root, column.relative_path)
            if not os.path.isfile(path):
                if column.relative_path not in missing:
                    missing.append(column.relative_path)
                continue
            if column.relative_path not in digests:
                digests[column.relative_path] = _digest_file(path)
            rows, fieldnames = _read_rows(path, column.relative_path)
            if column.column not in fieldnames:
                raise LegacyInventoryError(
                    "%s exists but has no column %r. The inventory allowlist and "
                    "the legacy file have diverged; that is a fact somebody must "
                    "look at, not one to skip past."
                    % (column.relative_path, column.column))
            for row in rows:
                raw = row.get(column.column)
                value = raw if isinstance(raw, str) else ""
                key = (column.kind.value, value)
                counters[key] = counters.get(key, 0) + 1
                kinds[key] = column.kind
                column_sets.setdefault(key, set()).add(column.label)
    finally:
        csv.field_size_limit(previous_limit)

    values = tuple(
        LegacySourceValue(
            value=value,
            kind=kinds[(kind_value, value)],
            occurrences=counters[(kind_value, value)],
            columns=tuple(sorted(column_sets[(kind_value, value)])),
        )
        for kind_value, value in sorted(counters))

    observations.extend(_observe(values))

    return LegacySourceInventory(
        schema_version=LEGACY_INVENTORY_SCHEMA_VERSION,
        values=values,
        columns_scanned=tuple(sorted(columns, key=lambda item: item.label)),
        exclusions=tuple(sorted(exclusions, key=lambda item: item.label)),
        input_digests=dict(sorted(digests.items())),
        missing_inputs=tuple(sorted(missing)),
        observations=tuple(observations),
    )


def _observe(values: Sequence[LegacySourceValue]) -> Tuple[str, ...]:
    """Facts about the scanned values. Facts only - no normalisation.

    Case-variant spellings are *reported*, never merged: deciding that
    ``variantAnnotation`` and ``VariantAnnotation`` name the same container is a
    judgement about the provider's data model, and this module does not have
    the standing to make it.
    """
    notes: List[str] = []

    blank = tuple(value for value in values if value.is_blank)
    if blank:
        total = sum(value.occurrences for value in blank)
        columns = sorted({column for value in blank for column in value.columns})
        notes.append(
            "%d row(s) carry a blank source value, in %s. Their provenance is "
            "unrecorded and cannot be inferred."
            % (total, ", ".join(columns)))

    groups: Dict[Tuple[str, str], List[str]] = {}
    for value in values:
        if value.is_blank:
            continue
        groups.setdefault((value.kind.value, value.value.casefold()), []).append(
            value.value)
    for (kind_value, _folded), spellings in sorted(groups.items()):
        if len(set(spellings)) > 1:
            notes.append(
                "%s: %s differ only by case. They are counted separately; "
                "whether they name the same thing is a question for the source "
                "owner, not a normalisation this project may apply."
                % (kind_value, ", ".join(repr(s) for s in sorted(set(spellings)))))

    multi = tuple(value for value in values if len(value.columns) > 1)
    if multi:
        notes.append(
            "%d value(s) appear in more than one column; each is listed with "
            "every column it was found in." % len(multi))

    return tuple(notes)


def unregistered_legacy_values(
    inventory: LegacySourceInventory,
    registry: Any,
    kinds: Sequence[SourceValueKind] = (SourceValueKind.SOURCE_NAME,
                                        SourceValueKind.ALLELE_FUNCTION_SOURCE),
) -> Tuple[PolicyIssue, ...]:
    """Findings for legacy source values with no policy record.

    Matching is exact against ``source_key`` and against the record's
    ``display_name``. Nothing is fuzzy-matched: deciding that the legacy string
    ``CPIC`` refers to a particular registry entry is a mapping somebody records
    deliberately, and a near-match accepted here would be that decision made by
    a string-distance function.

    Only the kinds a project acquires *from* are checked by default. A provider
    container such as ``data/guidelineAnnotation`` is a location inside another
    source, not a source in its own right.
    """
    known = set()
    for record in tuple(registry.records):
        known.add(record.source_key)
        known.add(record.display_name)
        legacy_aliases = getattr(record, "legacy_aliases", ())
        known.update(legacy_aliases)

    issues: List[PolicyIssue] = []
    for value in inventory.values:
        if value.kind not in kinds or value.is_blank:
            continue
        if value.value in known:
            continue
        issues.append(PolicyIssue(
            PolicyIssueCode.LEGACY_SOURCE_UNREGISTERED, IssueSeverity.BLOCKER,
            value.value,
            "appears %d time(s) in %s but has no policy record. Legacy data "
            "citing an unregistered source cannot back published output."
            % (value.occurrences, ", ".join(value.columns))))
    return sort_issues(issues)


def render_markdown(inventory: LegacySourceInventory, title: str) -> str:
    """Render the inventory as the checked-in Markdown report.

    Deterministic for the same reason the JSON is: no timestamp, sorted
    collections, fixed section order.
    """
    lines: List[str] = [
        "# %s" % title,
        "",
        "Generated by `pgx-source-policy inventory-legacy` from the frozen "
        "legacy files. Read-only: no legacy file is modified, and no value is "
        "normalised, merged or renamed.",
        "",
        "This document counts what the legacy data *says*. It makes no claim "
        "that any of these sources may be used; that is recorded per source in "
        "`config/scientific-sources.json`, and at the time of writing every "
        "entry there is `PENDING_REVIEW`.",
        "",
        "## Totals",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        "| Distinct source values | %d |" % inventory.distinct_value_count,
        "| Total occurrences | %d |" % inventory.total_occurrences,
        "| Columns scanned | %d |" % len(inventory.columns_scanned),
        "| Inputs missing from this checkout | %d |" % len(inventory.missing_inputs),
        "",
        "## Columns scanned",
        "",
        "A column is scanned because it was checked and found to carry source "
        "values, never because of its name.",
        "",
        "| File | Column | Kind | Why |",
        "| --- | --- | --- | --- |",
    ]
    for column in inventory.columns_scanned:
        lines.append("| `%s` | `%s` | %s | %s |" % (
            column.relative_path, column.column, column.kind.value, column.note))

    lines.extend([
        "",
        "## Columns deliberately excluded",
        "",
        "Named here so the omission reads as a decision rather than an "
        "oversight.",
        "",
        "| File | Column | Why not a source |",
        "| --- | --- | --- |",
    ])
    for excluded in inventory.exclusions:
        lines.append("| `%s` | `%s` | %s |" % (
            excluded.relative_path, excluded.column, excluded.reason))

    for kind in SourceValueKind:
        values = inventory.values_of_kind(kind)
        if not values:
            continue
        lines.extend([
            "",
            "## %s" % kind.value.replace("_", " ").title(),
            "",
            "| Value (verbatim) | Occurrences | Columns |",
            "| --- | ---: | --- |",
        ])
        for value in values:
            shown = "*(blank)*" if value.is_blank else "`%s`" % value.value
            lines.append("| %s | %d | %s |" % (
                shown, value.occurrences,
                ", ".join("`%s`" % c for c in value.columns)))

    lines.extend(["", "## Observations", ""])
    if inventory.observations:
        for note in inventory.observations:
            lines.append("- %s" % note)
    else:
        lines.append("- None.")

    lines.extend(["", "## Input digests", "",
                  "| File | SHA-256 |", "| --- | --- |"])
    for path, digest in sorted(inventory.input_digests.items()):
        lines.append("| `%s` | `%s` |" % (path, digest))
    if inventory.missing_inputs:
        lines.extend(["", "Missing from this checkout:", ""])
        for path in inventory.missing_inputs:
            lines.append("- `%s`" % path)

    lines.append("")
    return "\n".join(lines)
