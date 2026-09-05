"""Migrate the legacy demonstration profiles into the sealed catalogue.

Run once by the artifact generator; never at request time. The output is
``data/demo/wp17-development-cases.json`` and its manifest, and the interface
reads only those.

**What crosses.** The gene-to-phenotype mapping, normalised by WP-12's own
normaliser so the catalogue holds canonical keys and canonical phenotype
tokens rather than the seed's ``CYP2C19``/``poor`` spellings. The legacy key
and the source file's SHA-256, so an auditor can find what this came from.

**What does not.** ``demo_use`` - one sentence per profile, naming medicines
and asserting what a run will show. Three reasons, any one of them sufficient:
it associates a medicine with a phenotype, which is the association the
governed ruleset exists to make and this catalogue has no standing to; it
asserts an outcome, which would turn a demonstration input into an
expectation; and it is unreviewed prose that would appear on screen under the
interface's authority. ``profile_name`` crosses as a label because it names
the *profile* rather than a conclusion, and even then it is checked against
the prohibited-claim scanner before it is written.

**Nothing is inferred.** No medication list, no expected attention, no
severity. The profiles contain phenotypes; the catalogue contains phenotypes.

One case is not a migration at all: ``WP17-CASE-INSUFFICIENT`` is written here
to demonstrate an insufficient/not-assessed result, which the mandatory demo
flow requires and which no legacy profile produces. It is marked as authored
rather than migrated, and it is not a seventh legacy profile.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from apps.web.demo_cases import (CASE_CATALOG_SCHEMA_VERSION, DemoCaseError,
                                 DevelopmentCase, PhenotypeObservationRecord)

__all__ = [
    "LEGACY_SEED_PATH",
    "MIGRATION_VERSION",
    "build_catalog",
    "build_manifest",
    "legacy_source_digest",
    "migrate_profile",
]

MIGRATION_VERSION = "pgx-wp17-demo-migration/1"

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                          "..", ".."))
LEGACY_SEED_PATH = os.path.join(_REPO_ROOT, "clinpgx_mvp_seed",
                                "mvp_demo_profiles.json")
LEGACY_SEED_RELATIVE = "clinpgx_mvp_seed/mvp_demo_profiles.json"

#: The legacy key of each profile mapped to the identifier it becomes.
#:
#: An explicit table rather than a slug derived from the key. A derived
#: identifier changes when somebody renames a legacy key, and a case
#: identifier that changes is a link that breaks and an audit trail that
#: stops matching.
LEGACY_CASE_IDS: Mapping[str, str] = {
    "P1_normal": "WP17-CASE-P1",
    "P2_cyp2c19_poor": "WP17-CASE-P2",
    "P3_cyp2d6_poor": "WP17-CASE-P3",
    "P4_cyp2d6_ultrarapid": "WP17-CASE-P4",
    "P5_cyp2c9_decreased": "WP17-CASE-P5",
    "P6_mixed_high_attention": "WP17-CASE-P6",
}

#: What each migrated case is useful for, in controlled text written here.
#:
#: Not the legacy ``demo_use``. Each of these describes a *phenotype shape* -
#: which is what the profile actually contains - and names no medicine and no
#: outcome.
_DEMONSTRATES: Mapping[str, Mapping[str, str]] = {
    "WP17-CASE-P1": {
        "tr": "Beş gende de normal fonksiyon bildirilen profil.",
        "en": "A profile reporting normal function on all five genes."},
    "WP17-CASE-P2": {
        "tr": "Tek gende düşük fonksiyon bildirilen profil (CYP2C19).",
        "en": "A profile reporting reduced function on one gene (CYP2C19)."},
    "WP17-CASE-P3": {
        "tr": "Tek gende düşük fonksiyon bildirilen profil (CYP2D6).",
        "en": "A profile reporting reduced function on one gene (CYP2D6)."},
    "WP17-CASE-P4": {
        "tr": "Tek gende artmış fonksiyon bildirilen profil (CYP2D6). "
              "ULTRARAPID ve RAPID ayrı fenotiplerdir ve birbirinin yerine "
              "kullanılmaz.",
        "en": "A profile reporting increased function on one gene (CYP2D6). "
              "ULTRARAPID and RAPID are distinct phenotypes and are never "
              "used for one another."},
    "WP17-CASE-P5": {
        "tr": "Tek gende ara fonksiyon bildirilen profil (CYP2C9).",
        "en": "A profile reporting intermediate function on one gene "
              "(CYP2C9)."},
    "WP17-CASE-P6": {
        "tr": "Birden çok gende farklı fonksiyon düzeyleri bildirilen profil.",
        "en": "A profile reporting differing function levels across several "
              "genes."},
    "WP17-CASE-INSUFFICIENT": {
        "tr": "Yönetilen kuralların değerlendiremediği bir gen için fenotip "
              "bildiren profil. Kapsamın yetersiz kaldığı ve sonucun "
              "değerlendirilmedi olarak döndüğü durumu göstermek için "
              "yazılmıştır.",
        "en": "A profile reporting a phenotype for a gene the governed rules "
              "cannot evaluate. Written to show coverage falling short and a "
              "result returning as not assessed."},
}

_NO_PII: Mapping[str, str] = {
    "tr": "Bu vaka sentetiktir. Hiçbir gerçek kişiye ait veri, tanımlayıcı "
          "veya klinik metin içermez.",
    "en": "This case is synthetic. It contains no data, identifier or "
          "clinical text belonging to any real person.",
}

_MIGRATED_NOTE: Mapping[str, str] = {
    "tr": "Eski gösterim profilinden taşındı. Fenotipler WP-12 "
          "normalleştiricisiyle kanonik biçime getirildi. Kaynak dosyadaki "
          "serbest metin açıklaması taşınmadı: ilaç adı ve sonuç iddiası "
          "içerdiği için bu katalog onu tutmaz.",
    "en": "Migrated from the legacy demonstration profile. Phenotypes were "
          "canonicalised by the WP-12 normaliser. The source file's free-text "
          "note was not migrated: it names medicines and asserts an outcome, "
          "so this catalogue does not hold it.",
}

_AUTHORED_NOTE: Mapping[str, str] = {
    "tr": "Bu vaka taşınmadı; yetersiz kapsam gösterimi için burada yazıldı. "
          "Yedinci bir eski profil değildir ve doğrulama vakası sayılmaz.",
    "en": "This case was not migrated; it was written here to demonstrate "
          "insufficient coverage. It is not a seventh legacy profile and is "
          "not counted as a validation case.",
}

#: The authored insufficiency case. A gene no governed ruleset in this
#: repository declares an axis for, so coverage cannot be satisfied.
_INSUFFICIENT_OBSERVATIONS: Tuple[Tuple[str, str], ...] = (
    ("GENE:TESTGENE-UNCOVERED", "INDETERMINATE"),
)


def legacy_source_digest(path: Optional[str] = None) -> Dict[str, Any]:
    """The source file's identity, recorded so the migration is auditable."""
    target = path or LEGACY_SEED_PATH
    with io.open(target, "rb") as handle:
        raw = handle.read()
    return {
        "source_file": LEGACY_SEED_RELATIVE,
        "source_file_sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
        "source_file_bytes": len(raw),
    }


def _canonical_observations(phenotypes: Mapping[str, str]
                            ) -> Tuple[PhenotypeObservationRecord, ...]:
    """Canonicalise through WP-12, then record what it produced.

    The normaliser is asked rather than a mapping table applied here. A second
    normaliser in the migration would be a second place for ``rapid`` to start
    meaning ``ultrarapid`` (SAFETY-INV-004), which is the failure WP-12 exists
    to make impossible.
    """
    from pgx.engine.phenotype_normalization import normalize_profile

    profile = normalize_profile(dict(phenotypes))
    records: List[PhenotypeObservationRecord] = []
    for observation in profile.observations:
        if observation.phenotype is None:
            raise DemoCaseError(
                "the legacy profile carries a value WP-12 could not "
                "canonicalise for %s; a migration never guesses one"
                % observation.gene_canonical_key)
        records.append(PhenotypeObservationRecord(
            gene=observation.gene_canonical_key,
            value=observation.phenotype.value))
    return tuple(sorted(records, key=lambda item: item.gene))


def _checked_label(text: str, *, case_id: str) -> str:
    """A label, scanned before it is written into a sealed artifact.

    The profile names come from the legacy file. They are short and
    descriptive, but they are still text this repository did not author, and
    the sealed artifact is read by the interface and rendered. Scanning here
    means a name that made a prohibited claim would fail the migration rather
    than appear on a screen.
    """
    from pgx.domain.claims import scan_claim_text

    report = scan_claim_text(text)
    if getattr(report, "violations", ()):
        raise DemoCaseError(
            "the legacy label for %s matches a prohibited claim pattern and "
            "is not migrated" % case_id)
    return text


def migrate_profile(legacy_key: str, profile: Mapping[str, Any], *,
                    source: Mapping[str, Any]) -> DevelopmentCase:
    """One legacy profile as one development case."""
    case_id = LEGACY_CASE_IDS.get(legacy_key)
    if case_id is None:
        raise DemoCaseError(
            "no case identifier is declared for legacy profile %r; a "
            "migration mints identifiers from a reviewed table, never from "
            "the key it happens to find" % legacy_key)
    return DevelopmentCase(
        case_id=case_id,
        label=_checked_label(str(profile.get("profile_name") or legacy_key),
                             case_id=case_id),
        case_role="DEVELOPMENT",
        is_synthetic=True,
        is_validation_evidence=False,
        is_holdout=False,
        observations=_canonical_observations(profile.get("phenotypes") or {}),
        legacy_profile_key=legacy_key,
        source_file=source["source_file"],
        source_file_sha256=source["source_file_sha256"],
        migration_note=_MIGRATED_NOTE["tr"],
        demonstrates=_DEMONSTRATES[case_id]["tr"],
        no_pii_assertion=_NO_PII["tr"])


def _insufficiency_case() -> DevelopmentCase:
    """The authored case that demonstrates an unevaluable axis."""
    return DevelopmentCase(
        case_id="WP17-CASE-INSUFFICIENT",
        label="Yetersiz kapsam gösterim profili",
        case_role="DEVELOPMENT",
        is_synthetic=True,
        is_validation_evidence=False,
        is_holdout=False,
        observations=tuple(
            PhenotypeObservationRecord(gene=gene, value=value)
            for gene, value in sorted(_INSUFFICIENT_OBSERVATIONS)),
        legacy_profile_key=None,
        source_file=None,
        source_file_sha256=None,
        migration_note=_AUTHORED_NOTE["tr"],
        demonstrates=_DEMONSTRATES["WP17-CASE-INSUFFICIENT"]["tr"],
        no_pii_assertion=_NO_PII["tr"])


def build_catalog(path: Optional[str] = None) -> Dict[str, Any]:
    """Build the whole sealed catalogue document from the legacy seed."""
    source = legacy_source_digest(path)
    with io.open(path or LEGACY_SEED_PATH, encoding="utf-8") as handle:
        profiles = json.load(handle)

    if set(profiles) != set(LEGACY_CASE_IDS):
        raise DemoCaseError(
            "the legacy seed holds %s and the migration declares %s; a "
            "migration that silently skipped or invented a profile would be "
            "a migration nobody could check"
            % (sorted(profiles), sorted(LEGACY_CASE_IDS)))

    cases = [migrate_profile(key, value, source=source)
             for key, value in sorted(profiles.items())]
    cases.append(_insufficiency_case())
    cases.sort(key=lambda case: case.case_id)

    return {
        "schema_version": CASE_CATALOG_SCHEMA_VERSION,
        "migration_version": MIGRATION_VERSION,
        "case_role": "DEVELOPMENT",
        "is_validation_evidence": False,
        "contains_holdout": False,
        "migrated_case_count": len(LEGACY_CASE_IDS),
        "authored_case_count": 1,
        "case_count": len(cases),
        "source": dict(source),
        "note": (
            "Synthetic development cases for demonstration only. None of "
            "these is validation evidence, holdout data, a clinical example "
            "or a record of any person. No case carries an expected result, "
            "and this catalogue has no field in which one could be recorded. "
            "The legacy source file's free-text notes were deliberately not "
            "migrated: they name medicines and assert outcomes."),
        "cases": [case.to_json() for case in cases],
    }


def build_manifest(catalog: Mapping[str, Any], *,
                   rendered: Optional[str] = None) -> Dict[str, Any]:
    """The catalogue's own identity, so a reader can check what they have.

    Two hashes, because they answer two different questions and a manifest
    carrying only one of them misleads whoever asks the other.

    ``catalog_sha256`` is over a canonical compact serialisation. It is the
    identity of the *content*, and it survives the file being reformatted,
    reindented or re-serialised by a different tool.

    ``catalog_file_sha256`` is over the exact bytes written to
    ``data/demo/wp17-development-cases.json``. It is what ``sha256sum`` on
    that file produces. Without it, a reader who checksums the committed file
    gets a mismatch against the only hash in the manifest and has no way to
    tell a reformat from a tampering.
    """
    body = json.dumps(catalog, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True).encode("utf-8")
    file_hash: Dict[str, Any] = {}
    if rendered is not None:
        raw = rendered.encode("utf-8")
        file_hash = {
            "catalog_file_sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
            "catalog_file_bytes": len(raw),
            "catalog_file_path": "data/demo/wp17-development-cases.json",
            "catalog_hash_note": (
                "catalog_sha256 is over a canonical compact serialisation of "
                "the catalogue content; catalog_file_sha256 is over the bytes "
                "of the committed file and is what sha256sum reports for it."),
        }
    return {
        "manifest_version": "pgx-wp17-demo-manifest/1",
        "migration_version": MIGRATION_VERSION,
        "schema_version": CASE_CATALOG_SCHEMA_VERSION,
        "catalog_sha256": "sha256:" + hashlib.sha256(body).hexdigest(),
        "catalog_bytes": len(body),
        "case_count": catalog["case_count"],
        "migrated_case_count": catalog["migrated_case_count"],
        "authored_case_count": catalog["authored_case_count"],
        "case_ids": [case["case_id"] for case in catalog["cases"]],
        "source": dict(catalog["source"]),
        "artifact_kind": "SOURCE_DERIVED_AND_AUTHORED",
        "artifact_note": (
            "Six cases are derived from the legacy source file named above; "
            "one is authored in apps/web/demo_migration.py to demonstrate "
            "insufficient coverage. Nothing here is browser-generated, "
            "runtime verified, or manually reviewed by a scientific "
            "reviewer."),
        "validation_status": "NOT_VALIDATION_EVIDENCE",
        **file_hash,
    }
