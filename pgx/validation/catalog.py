# -*- coding: utf-8 -*-
"""The WP-17 development cases, seen as validation cases (WP-18).

Seven cases exist in this repository and every one of them is
``DEVELOPMENT``. They are read from ``data/demo/wp17-development-cases.json``
and **not copied**: the sealed catalogue stays the single source, its two
hashes stay verifiable, and this module is a view over it.

Why a view rather than a migration. Copying would create a second file that
could drift, and drift between "the demo catalogue" and "the validation
catalogue" is precisely the ambiguity a partition cannot afford. It would also
mean the WP-17 artifact tests and the WP-18 artifact tests could pass while
describing different sets of cases.

**They are development cases and they say so, three times.** ``role`` is
``DEVELOPMENT``, ``is_validation_evidence`` is false, ``is_holdout`` is false.
The reason is not that they are low quality - P1 through P6 are careful work -
but that they demonstrated the same rules they would be measured against.
Using them as validation evidence would report memory as generalisation, which
is what ``SAFETY-INV-009`` names.

No expected result is added here, and there is nowhere to add one: the case
model has no field for it. The catalogue's own ``FORBIDDEN_CASE_FIELDS``
refuses one on the WP-17 side as well, so a future edit would have to defeat
two independent guards.
"""

from __future__ import annotations

import datetime as _dt
import io
import json
import os
from typing import Any, Dict, List, Mapping, Optional, Tuple

from pgx.validation.cases import (Provenance, ValidationCaseId,
                                  ValidationCaseMetadata)
from pgx.validation.compatibility import UNPINNED
from pgx.validation.errors import ValidationCaseError
from pgx.validation.fingerprint import content_fingerprint
from pgx.validation.vocabulary import (DataClassification, ValidationCaseRole,
                                       VisibilityLevel)

__all__ = [
    "DEVELOPMENT_CATALOG_PATH",
    "DEVELOPMENT_SOFTWARE_VERSION",
    "development_cases",
    "load_development_catalog",
]

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

#: The sealed WP-17 artifact. Read, never written by this package.
DEVELOPMENT_CATALOG_PATH = os.path.join("data", "demo",
                                        "wp17-development-cases.json")

#: What the seven cases were authored against. Software only: no dataset,
#: ruleset or release was pinned when they were migrated, and pretending one
#: was would be inventing a release.
DEVELOPMENT_SOFTWARE_VERSION = "1.0.0"

#: Their creation time, taken from the migration rather than from a clock, so
#: this view is deterministic. The WP-17 catalogue records no per-case
#: timestamp; the date the migration was sealed is the honest stand-in and is
#: stated as such in the case notes.
_MIGRATION_DATE = _dt.datetime(2026, 8, 29, tzinfo=_dt.timezone.utc)

_NO_PII = ("This case is synthetic. It carries no data belonging to any real "
           "person: no identifier, no record and no clinical text. Public "
           "gene symbols appear as governed vocabulary.")


def load_development_catalog(root: str = _REPO_ROOT) -> Mapping[str, Any]:
    """The sealed WP-17 catalogue, as committed."""
    path = os.path.join(root, *DEVELOPMENT_CATALOG_PATH.split("/"))
    with io.open(path, encoding="utf-8") as handle:
        return json.load(handle)


def development_cases(root: str = _REPO_ROOT
                      ) -> Tuple[ValidationCaseMetadata, ...]:
    """The seven WP-17 cases as validation metadata. All DEVELOPMENT.

    Raises if the catalogue claims anything else. That check is not
    defensive-programming habit: the catalogue is a committed file, and a
    future edit marking one of its cases as holdout is exactly the mistake
    this package exists to catch - so it is caught here, at the point where
    the two worlds meet, rather than trusted.
    """
    catalog = load_development_catalog(root)
    source_file = catalog["source"]["source_file"]
    source_digest = catalog["source"]["source_file_sha256"]

    built: List[ValidationCaseMetadata] = []
    for entry in catalog["cases"]:
        if entry.get("case_role") != "DEVELOPMENT" or \
                entry.get("is_validation_evidence") or entry.get("is_holdout"):
            raise ValidationCaseError(
                "the WP-17 catalogue entry %r no longer declares itself a "
                "development case; WP-18 will not treat it as validation "
                "evidence and will not guess what it now is"
                % entry.get("case_id"))

        authored = entry.get("legacy_profile_key") is None
        provenance = Provenance(
            source_identity=(
                "%s#%s" % (source_file, entry["legacy_profile_key"])
                if not authored
                else "apps/web/demo_migration.py#%s" % entry["case_id"]),
            derivation_method=("WP-17 demo-profile migration"
                               if not authored
                               else "authored WP-17 development fixture"),
            # True by definition. These are the fixtures that shaped the
            # software, which is what makes them unusable as holdout.
            derived_from_development=True,
            source_digest=(source_digest if not authored else None),
            author="WP-17 migration")

        content = {"observations": list(entry["observations"])}
        built.append(ValidationCaseMetadata(
            case_id=ValidationCaseId(
                entry["case_id"].replace("WP17-CASE-", "PGX-VAL-DEV-")),
            role=ValidationCaseRole.DEVELOPMENT,
            classification=DataClassification.SYNTHETIC,
            provenance=provenance,
            content_fingerprint=content_fingerprint(content),
            no_pii_assertion=_NO_PII,
            created_at=_MIGRATION_DATE,
            compatibility=UNPINNED(DEVELOPMENT_SOFTWARE_VERSION),
            visibility=VisibilityLevel.AUTHOR_VISIBLE,
            title=entry.get("label"),
            notes=("Development and regression fixture only. Not validation "
                   "evidence and never part of a holdout denominator. The "
                   "creation time is the WP-17 migration date; the sealed "
                   "catalogue records no per-case timestamp."),
            extra={"wp17_case_id": entry["case_id"],
                   "legacy_profile_key": entry.get("legacy_profile_key"),
                   "observation_count": entry["observation_count"]}))
    return tuple(sorted(built, key=lambda case: case.case_id.value))
