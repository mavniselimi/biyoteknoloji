# -*- coding: utf-8 -*-
"""What a case says it was written against (WP-18).

A validation case is only meaningful against a stated version of the software,
the dataset and the ruleset. A case authored when a rule said MEDIUM and
evaluated after that rule was retired is not evidence about the current
release; it is evidence about a release nobody is shipping.

So compatibility is **declared and structured**, and it deliberately does four
things separately rather than collapsing them into one "version" string:

- ``software_version`` - the code that computes an assessment;
- ``dataset_version`` - the canonical scientific data;
- ``ruleset_version`` - the frozen rules;
- ``release_bundle`` - the manifest identity that pins all three together.

They are separate because they move separately. A dataset can be re-canonicalised
without a rule changing; a rule can be retired without the dataset moving. A
single string would make "compatible" unanswerable the first time one of them
changed on its own.

**Nothing here activates or creates a release.** A declaration names a version;
it does not assert that the version exists in this repository, and
:meth:`ReleaseCompatibility.resolved_against` is how a caller finds out that it
does not. That distinction is what lets a case be authored before a release is
registered without either lying about the release or blocking the author.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional

from pgx.validation.errors import CompatibilityError

__all__ = [
    "COMPATIBILITY_SCHEMA_VERSION",
    "ReleaseCompatibility",
    "UNPINNED",
]

COMPATIBILITY_SCHEMA_VERSION = "pgx-wp18-release-compatibility/1"

_SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.\-]+)?$")
_DATASET_ID = re.compile(r"^PGX-DATA-\d{8}-\d{3}$")
_RULESET_ID = re.compile(r"^PGX-RULESET-\d{8}-\d{3}$")
_RELEASE_ID = re.compile(r"^PGX-REL-\d{8}-\d{3}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class ReleaseCompatibility:
    """Which release a case was written against, as a declaration.

    Every field is optional *individually* and the object is never empty: a
    case that names nothing at all is refused, because "compatible with
    anything" is not a claim anybody can act on. What it is not required to do
    is name all four - a case authored against a ruleset before a release
    bundle exists names the ruleset, and says so.
    """

    software_version: Optional[str] = None
    dataset_public_id: Optional[str] = None
    ruleset_public_id: Optional[str] = None
    release_public_id: Optional[str] = None
    release_manifest_hash: Optional[str] = None
    note: Optional[str] = None

    def __post_init__(self) -> None:
        checks = (
            ("software_version", self.software_version, _SEMVER,
             "MAJOR.MINOR.PATCH"),
            ("dataset_public_id", self.dataset_public_id, _DATASET_ID,
             "PGX-DATA-YYYYMMDD-NNN"),
            ("ruleset_public_id", self.ruleset_public_id, _RULESET_ID,
             "PGX-RULESET-YYYYMMDD-NNN"),
            ("release_public_id", self.release_public_id, _RELEASE_ID,
             "PGX-REL-YYYYMMDD-NNN"),
            ("release_manifest_hash", self.release_manifest_hash, _DIGEST,
             "sha256:<64 hex>"),
        )
        for name, value, pattern, hint in checks:
            if value is None:
                continue
            if not isinstance(value, str) or not pattern.match(value):
                raise CompatibilityError("%s must match %s, got %r"
                                         % (name, hint, value))
        if not any(value is not None for _n, value, _p, _h in checks):
            raise CompatibilityError(
                "a case must declare at least one compatibility constraint; "
                "'compatible with anything' is not a statement a validation "
                "run can check")

    @property
    def is_pinned_to_release(self) -> bool:
        """Whether a specific release bundle is named.

        A case pinned only to a ruleset is still useful and still honest; it
        just cannot be attributed to a release until one exists.
        """
        return self.release_public_id is not None

    def conflicts_with(self, other: "ReleaseCompatibility") -> bool:
        """Whether two declarations name different values for one field.

        Absence never conflicts. One case naming a dataset and another staying
        silent is not a disagreement - it is one case saying less. Only two
        stated, different values are a conflict, because only then is there
        something for a validation run to be wrong about.
        """
        if not isinstance(other, ReleaseCompatibility):
            raise CompatibilityError("conflicts_with needs a "
                                     "ReleaseCompatibility")
        for name in ("software_version", "dataset_public_id",
                     "ruleset_public_id", "release_public_id",
                     "release_manifest_hash"):
            mine, theirs = getattr(self, name), getattr(other, name)
            if mine is not None and theirs is not None and mine != theirs:
                return True
        return False

    def resolved_against(self, available: Mapping[str, Any]) -> Dict[str, Any]:
        """Compare this declaration with what a deployment actually has.

        Returns a report rather than a boolean, and reports ``UNKNOWN`` for
        anything the deployment could not tell it. A missing active release
        makes every pinned field ``UNKNOWN`` - not ``False`` - because "there
        is no release to compare against" is a different fact from "the
        release is the wrong one", and only the second is a mismatch.
        """
        report: Dict[str, Any] = {}
        for name in ("software_version", "dataset_public_id",
                     "ruleset_public_id", "release_public_id",
                     "release_manifest_hash"):
            declared = getattr(self, name)
            if declared is None:
                report[name] = "NOT_DECLARED"
                continue
            actual = available.get(name)
            if actual is None:
                report[name] = "UNKNOWN"
            elif actual == declared:
                report[name] = "MATCH"
            else:
                report[name] = "MISMATCH"
        report["resolvable"] = "UNKNOWN" not in report.values()
        report["matches"] = (report["resolvable"]
                             and "MISMATCH" not in report.values())
        return report

    def to_json(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "schema_version": COMPATIBILITY_SCHEMA_VERSION,
            "is_pinned_to_release": self.is_pinned_to_release,
        }
        for name in ("software_version", "dataset_public_id",
                     "ruleset_public_id", "release_public_id",
                     "release_manifest_hash", "note"):
            value = getattr(self, name)
            if value is not None:
                payload[name] = value
        return payload


#: The declaration a development fixture carries when it was written against
#: the software alone. Not "no constraint": it names the software version and
#: says in its note that nothing else is pinned, which is a checkable claim.
def UNPINNED(software_version: str, note: str = "") -> ReleaseCompatibility:
    """A software-only declaration, spelled once so call sites agree."""
    return ReleaseCompatibility(
        software_version=software_version,
        note=note or ("declared against the software version only; no "
                      "dataset, ruleset or release bundle is pinned"))
