"""The development case catalogue: what it is, and what it is not.

Six cases migrated from the legacy demonstration seed, plus one written here
to show an insufficient result. Every one of them is synthetic, every one is
labelled ``DEVELOPMENT``, and **none of them is validation evidence.**

That last sentence is the whole point of this module, so it is enforced rather
than written down: :class:`DevelopmentCase` refuses any role but
``DEVELOPMENT``, refuses ``is_validation_evidence=True``, refuses
``is_holdout=True``, and carries no field in which an expected result could be
recorded. A case that cannot hold an expectation cannot be scored against one,
and a set of cases that cannot be scored cannot become a pass rate.

**What was deliberately not migrated.** Each legacy profile carried a
``demo_use`` sentence - free Turkish prose naming medications and asserting
what a run would show ("to display a pharmacogenetic warning for
CYP2C19-related medicines such as clopidogrel"). None of it is here. It is
ungoverned text, it names medicines this catalogue must not associate with a
phenotype, and promoting it would put an unreviewed conclusion on a screen
under the authority of the interface. The migration records the source hash so
that what was dropped is auditable, and drops it.

**No medication list is inferred.** The legacy profiles contain phenotypes and
nothing else. A case here therefore proposes no medications; the interface
offers the pinned release's canonical catalogue, ordered by canonical key,
with nothing preselected. Reading a medicine out of a profile name would be
this layer performing the association the ruleset exists to govern.

At runtime the catalogue is read from the sealed artifact under ``data/demo/``,
never from ``clinpgx_mvp_seed/``. The seed is a migration input; a runtime that
read it would depend on a file nobody versions and would pick up any edit
without a migration.
"""

from __future__ import annotations

import io
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

__all__ = [
    "CASE_CATALOG_SCHEMA_VERSION",
    "CASE_ID_PATTERN",
    "DEVELOPMENT_CASES_PATH",
    "DemoCaseError",
    "DevelopmentCase",
    "PhenotypeObservationRecord",
    "load_development_cases",
    "parse_catalog",
]

CASE_CATALOG_SCHEMA_VERSION = "pgx-wp17-development-cases/1"

#: Case identifiers are minted by the migration and are never user text.
CASE_ID_PATTERN = re.compile(r"^WP17-CASE-[A-Z0-9][A-Z0-9-]{0,31}$")

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                          "..", ".."))
DEVELOPMENT_CASES_PATH = os.path.join(_REPO_ROOT, "data", "demo",
                                      "wp17-development-cases.json")

#: The one role a case in this catalogue may hold.
_PERMITTED_ROLE = "DEVELOPMENT"

#: Fields whose presence means somebody tried to record an expectation, a
#: conclusion or a person. Refused by name, at any depth, the way WP-16
#: refuses prohibited request fields - and for the same reason: a catalogue
#: that could hold one of these would eventually hold one.
FORBIDDEN_CASE_FIELDS: Tuple[str, ...] = (
    "expected_attention", "expected_coverage", "expected_result",
    "expected_findings", "expected_outcome", "gold_standard", "ground_truth",
    "reference_answer", "validation_result", "concordance", "accuracy",
    "pass_rate", "score", "rank", "recommended_medications", "demo_use",
    "narrative", "diagnosis", "indication", "dose", "dosage",
    "patient_name", "patient_id", "date_of_birth", "dob", "mrn", "ehr",
    "genotype", "diplotype", "star_allele", "alleles", "activity_score",
    "vcf", "vcf_path",
)


class DemoCaseError(ValueError):
    """A case document does not satisfy the catalogue's contract."""


@dataclass(frozen=True, slots=True)
class PhenotypeObservationRecord:
    """One canonical gene-to-phenotype observation, as migrated."""

    gene: str
    value: str

    def __post_init__(self) -> None:
        if not re.match(r"^GENE:[A-Z0-9][A-Z0-9\-.@_]{0,48}$", self.gene):
            raise DemoCaseError("a migrated observation names a canonical "
                                "gene key, got %r" % self.gene)
        if not re.match(r"^[A-Z][A-Z_]{0,31}$", self.value):
            raise DemoCaseError("a migrated observation carries a canonical "
                                "phenotype token, got %r" % self.value)

    def to_json(self) -> Dict[str, str]:
        return {"gene": self.gene, "value": self.value}


@dataclass(frozen=True, slots=True)
class DevelopmentCase:
    """One synthetic development case. It holds no expected result.

    There is no field for one, and :data:`FORBIDDEN_CASE_FIELDS` is checked
    when a catalogue is parsed, so an expectation cannot be smuggled in as an
    extra key either.
    """

    case_id: str
    label: str
    case_role: str
    is_synthetic: bool
    is_validation_evidence: bool
    is_holdout: bool
    observations: Tuple[PhenotypeObservationRecord, ...]
    legacy_profile_key: Optional[str]
    source_file: Optional[str]
    source_file_sha256: Optional[str]
    migration_note: str
    demonstrates: str
    no_pii_assertion: str
    schema_version: str = CASE_CATALOG_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if CASE_ID_PATTERN.match(self.case_id) is None:
            raise DemoCaseError("a case identifier is minted by the migration "
                                "and matches %s; got %r"
                                % (CASE_ID_PATTERN.pattern, self.case_id))
        if self.case_role != _PERMITTED_ROLE:
            raise DemoCaseError(
                "this catalogue holds %s cases only. Holdout roles are "
                "defined by the validation-dataset work package and are not "
                "stored here, so that development and holdout cannot overlap "
                "(SAFETY-INV-009)." % _PERMITTED_ROLE)
        if not self.is_synthetic:
            raise DemoCaseError("every case in this catalogue is synthetic")
        if self.is_validation_evidence:
            raise DemoCaseError(
                "a development case is never validation evidence; recording "
                "one as such is how a demonstration becomes a claim")
        if self.is_holdout:
            raise DemoCaseError("a development case is never holdout data")
        if not self.observations:
            raise DemoCaseError("a case carries at least one observation")
        genes = [item.gene for item in self.observations]
        if len(set(genes)) != len(genes):
            raise DemoCaseError("a case names each gene at most once")
        if list(genes) != sorted(genes):
            raise DemoCaseError("observations are stored in canonical gene "
                                "order, so a catalogue is byte-stable")

    @property
    def observation_count(self) -> int:
        return len(self.observations)

    def phenotype_mapping(self) -> Dict[str, str]:
        """The gene-to-value mapping, for building an assessment request."""
        return {item.gene: item.value for item in self.observations}

    def to_json(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "case_id": self.case_id,
            "label": self.label,
            "case_role": self.case_role,
            "is_synthetic": self.is_synthetic,
            "is_validation_evidence": self.is_validation_evidence,
            "is_holdout": self.is_holdout,
            "legacy_profile_key": self.legacy_profile_key,
            "source_file": self.source_file,
            "source_file_sha256": self.source_file_sha256,
            "migration_note": self.migration_note,
            "demonstrates": self.demonstrates,
            "no_pii_assertion": self.no_pii_assertion,
            "observation_count": self.observation_count,
            "observations": [item.to_json() for item in self.observations],
        }


def _refuse_forbidden_fields(document: Any, path: str = "$") -> None:
    """Recursively refuse a field that could hold an expectation or a person."""
    if isinstance(document, Mapping):
        for key, value in document.items():
            if key in FORBIDDEN_CASE_FIELDS:
                raise DemoCaseError(
                    "the case catalogue carries %s%s, which this catalogue "
                    "does not hold" % (path, "." + str(key)))
            _refuse_forbidden_fields(value, "%s.%s" % (path, key))
    elif isinstance(document, (list, tuple)):
        for index, item in enumerate(document):
            _refuse_forbidden_fields(item, "%s[%d]" % (path, index))


def parse_catalog(document: Mapping[str, Any]) -> Tuple[DevelopmentCase, ...]:
    """Read a catalogue document into cases, or refuse it.

    Raises:
        DemoCaseError: the document is not a catalogue of this schema version,
            carries a forbidden field, or holds a case that is not a synthetic
            development case.
    """
    if not isinstance(document, Mapping):
        raise DemoCaseError("a case catalogue is an object")
    if document.get("schema_version") != CASE_CATALOG_SCHEMA_VERSION:
        raise DemoCaseError(
            "this build reads %s; the document declares %r"
            % (CASE_CATALOG_SCHEMA_VERSION, document.get("schema_version")))
    _refuse_forbidden_fields(document)

    cases: List[DevelopmentCase] = []
    for entry in document.get("cases") or ():
        if not isinstance(entry, Mapping):
            raise DemoCaseError("a case is an object")
        observations = tuple(
            PhenotypeObservationRecord(gene=item["gene"], value=item["value"])
            for item in entry.get("observations") or ())
        cases.append(DevelopmentCase(
            case_id=str(entry.get("case_id")),
            label=str(entry.get("label") or ""),
            case_role=str(entry.get("case_role")),
            is_synthetic=bool(entry.get("is_synthetic")),
            is_validation_evidence=bool(entry.get("is_validation_evidence")),
            is_holdout=bool(entry.get("is_holdout")),
            observations=observations,
            legacy_profile_key=entry.get("legacy_profile_key"),
            source_file=entry.get("source_file"),
            source_file_sha256=entry.get("source_file_sha256"),
            migration_note=str(entry.get("migration_note") or ""),
            demonstrates=str(entry.get("demonstrates") or ""),
            no_pii_assertion=str(entry.get("no_pii_assertion") or ""),
            schema_version=CASE_CATALOG_SCHEMA_VERSION))

    identifiers = [case.case_id for case in cases]
    if len(set(identifiers)) != len(identifiers):
        raise DemoCaseError("case identifiers are unique")
    if identifiers != sorted(identifiers):
        raise DemoCaseError("cases are stored in identifier order")
    return tuple(cases)


def load_development_cases(path: Optional[str] = None
                           ) -> Tuple[DevelopmentCase, ...]:
    """Read the sealed catalogue from disk.

    Args:
        path: the artifact to read. Defaults to the sealed WP-17 artifact.
            **Never** the legacy seed: that file is a migration input, is not
            versioned as a runtime artifact, and an edit to it would change
            what the interface shows without a migration having run.

    Raises:
        DemoCaseError: the artifact is missing or does not satisfy the
            contract. Missing is refused rather than treated as an empty
            catalogue - a page listing no cases because a file was absent
            looks identical to a page listing no cases because none exist.
    """
    target = path or DEVELOPMENT_CASES_PATH
    if not os.path.isfile(target):
        raise DemoCaseError(
            "the sealed development case catalogue is not present; run the "
            "WP-17 artifact generator")
    with io.open(target, encoding="utf-8") as handle:
        return parse_catalog(json.load(handle))
