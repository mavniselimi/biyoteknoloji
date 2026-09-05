# -*- coding: utf-8 -*-
"""Shared builders and real-artifact access for the WP-08 tests.

Two kinds of input, deliberately separated.

Small explicit factories are used wherever a test asserts a rule, so the reader
can see in the test body why the rule fires. A fixture loaded from disk would
move the interesting half of the test somewhere else.

The real sealed build is used wherever a test asserts a *number*, because the
counts this work package reports - 1,794 records, 4,051 locators, 132 stated
origins - are claims about the actual quarantined snapshot. A synthetic build
would let every one of them pass while the real data said something else. The
real build is only ever read.
"""

from __future__ import annotations

import datetime as _dt
import io
import json
import os
import unittest
from typing import Any, Mapping, Optional, Sequence

from pgx.evidence.models import (EvidenceEntityLink, EvidenceEntityRole,
                                 EvidenceNaturalKey, EvidenceRecordDraft,
                                 EvidenceRecordType, ImportIssue,
                                 ImportIssueCode, IssueSeverity, OriginStatus,
                                 RawRecordLocator, RecordTypeMapping,
                                 RecordTypeMappingStatus, SourceAttribution,
                                 SourceRecordVersion, SourceTextFragment,
                                 TextLanguage, VersionStatus)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

DATASET_ID = "PGX-DATA-20260830-900"
MANIFEST_HASH = "sha256:" + "3b" * 32
ARTIFACT_HASH = "sha256:" + "7c" * 32
PAYLOAD_HASH = "sha256:" + "6f" * 32
PROVIDER = "clinpgx.api"
NOW = _dt.datetime(2026, 8, 30, 12, 0, tzinfo=_dt.timezone.utc)

SNAPSHOT_ROOT = os.path.join(REPO_ROOT, "data", "raw", "clinpgx-legacy-v2",
                             DATASET_ID)
CANONICAL_BUILD = os.path.join(REPO_ROOT, "data", "canonical", DATASET_ID)
EVIDENCE_BUILD = os.path.join(REPO_ROOT, "data", "evidence", DATASET_ID)


def source(relative: str) -> str:
    """Read a module's text, closing the handle.

    A bare ``open(...).read()`` leaks a file object, and the suite runs under
    ``-W error::ResourceWarning``, so the leak would fail the run.
    """
    with io.open(os.path.join(REPO_ROOT, relative), encoding="utf-8") as handle:
        return handle.read()


def locator(pointer: Optional[str] = "/CYP2C19::clopidogrel/pair/"
                                     "guidelineAnnotation/0",
            artifact_path: str = "responses/pair_probe_raw.json",
            csv_row_number: Optional[int] = None,
            requested_container: Optional[str] = "guidelineAnnotation"
            ) -> RawRecordLocator:
    """A well-formed locator into the legacy snapshot's shape."""
    return RawRecordLocator(
        dataset_public_id=DATASET_ID,
        snapshot_manifest_hash=MANIFEST_HASH,
        artifact_path=artifact_path,
        artifact_sha256=ARTIFACT_HASH,
        pointer=pointer,
        csv_row_number=csv_row_number,
        requested_container=requested_container)


def natural_key(source_record_id: str = "PA166104948",
                record_type: EvidenceRecordType =
                EvidenceRecordType.GUIDELINE_ANNOTATION,
                version_part: str = "0") -> EvidenceNaturalKey:
    return EvidenceNaturalKey(
        dataset_public_id=DATASET_ID,
        provider_source_key=PROVIDER,
        record_type=record_type,
        source_record_id=source_record_id,
        version_part=version_part)


def stated_origin(origin_source_key: str = "cpic.publications",
                  raw_origin_value: str = "CPIC") -> SourceAttribution:
    return SourceAttribution(provider_source_key=PROVIDER,
                             origin_status=OriginStatus.STATED_BY_SOURCE,
                             origin_source_key=origin_source_key,
                             raw_origin_value=raw_origin_value)


def unstated_origin() -> SourceAttribution:
    return SourceAttribution(provider_source_key=PROVIDER,
                             origin_status=OriginStatus.NOT_STATED_BY_SOURCE)


def known_version(value: str = "0") -> SourceRecordVersion:
    return SourceRecordVersion(status=VersionStatus.KNOWN, value=value)


def unknown_legacy_version() -> SourceRecordVersion:
    return SourceRecordVersion(status=VersionStatus.UNKNOWN_LEGACY)


def confirmed_mapping(object_class: str = "Guideline Annotation",
                      container: str = "guidelineAnnotation"
                      ) -> RecordTypeMapping:
    return RecordTypeMapping(
        record_type=EvidenceRecordType.GUIDELINE_ANNOTATION,
        status=RecordTypeMappingStatus.CONFIRMED,
        source_object_class=object_class,
        requested_container=container)


def fragment(text: str = "Consider an alternative for CYP2C19 poor "
                         "metabolizers.",
             field_name: str = "summaryMarkdown.html",
             ordinal: int = 0,
             at: Optional[RawRecordLocator] = None) -> SourceTextFragment:
    """A quotation carrying the locator it was quoted from.

    The locator is not optional in the model and is not made optional here: a
    fragment that cannot say which bytes it came from is not a citation, and a
    test helper that defaulted it away would let a test assert citation
    behaviour without any citation.
    """
    return SourceTextFragment(field_name=field_name, ordinal=ordinal,
                              text=text, text_format="text/html",
                              locator=at or locator(),
                              language=TextLanguage.UNKNOWN)


def entity_link(canonical_key: str = "GENE:CYP2C19",
                entity_type: str = "GENE",
                role: EvidenceEntityRole = EvidenceEntityRole.RELATED_ENTITY,
                entity_uuid: str = "22222222-2222-4222-8222-222222222222"
                ) -> EvidenceEntityLink:
    return EvidenceEntityLink(entity_type=entity_type,
                              canonical_key=canonical_key,
                              entity_uuid=entity_uuid, role=role,
                              source_field="relatedGenes",
                              raw_value=canonical_key.split(":", 1)[1])


def issue(code: ImportIssueCode = ImportIssueCode.ORIGIN_SOURCE_NOT_STATED,
          severity: IssueSeverity = IssueSeverity.BLOCKING,
          subject: str = "PA166104948",
          detail: str = "the record states no origin") -> ImportIssue:
    return ImportIssue(code=code, severity=severity, subject=subject,
                       detail=detail)


def draft(record_uuid: Optional[str] = None,
          key: Optional[EvidenceNaturalKey] = None,
          attribution: Optional[SourceAttribution] = None,
          version: Optional[SourceRecordVersion] = None,
          mapping: Optional[RecordTypeMapping] = None,
          raw_payload: Optional[Mapping[str, Any]] = None,
          normalized_metadata: Optional[Mapping[str, Any]] = None,
          locators: Optional[Sequence[RawRecordLocator]] = None,
          entity_links: Optional[Sequence[EvidenceEntityLink]] = None,
          text_fragments: Optional[Sequence[SourceTextFragment]] = None,
          publications: Sequence[Any] = (),
          issues: Sequence[ImportIssue] = ()) -> EvidenceRecordDraft:
    """A complete, well-formed record. Every part is overridable."""
    return EvidenceRecordDraft(
        natural_key=key or natural_key(),
        record_type_mapping=mapping or confirmed_mapping(),
        attribution=attribution or stated_origin(),
        version=version or known_version(),
        source_record_id_raw="PA166104948",
        source_record_id_raw_type="str",
        raw_source_payload=raw_payload or {"id": "PA166104948",
                                           "objCls": "Guideline Annotation"},
        canonical_build_key="%s/61e892abb95facac" % DATASET_ID,
        canonical_build_content_hash="sha256:" + "61" * 32,
        locators=tuple(locators if locators is not None else (locator(),)),
        entity_links=tuple(entity_links if entity_links is not None
                           else (entity_link(),)),
        text_fragments=tuple(text_fragments if text_fragments is not None
                             else (fragment(),)),
        publications=tuple(publications),
        normalized_metadata=dict(normalized_metadata or {}),
        issues=tuple(issues),
        record_uuid=record_uuid)


class RealEvidenceBuildTestCase(unittest.TestCase):
    """Reads the real sealed evidence build. Never writes to it.

    Skipped rather than failed when the build is absent, so a checkout that has
    not run ``pgx-evidence build`` still runs the rest of the suite. A skip
    that silently replaced a real measurement with a synthetic one would be
    worse than no test.
    """

    build_path = EVIDENCE_BUILD
    snapshot_root = SNAPSHOT_ROOT

    @classmethod
    def setUpClass(cls) -> None:
        if not os.path.isdir(cls.build_path):
            raise unittest.SkipTest(
                "no sealed evidence build at %s; run pgx-evidence build"
                % cls.build_path)

    @classmethod
    def rows(cls, name: str) -> Sequence[Mapping[str, Any]]:
        path = os.path.join(cls.build_path, name)
        with io.open(path, encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]

    @classmethod
    def manifest(cls) -> Mapping[str, Any]:
        with io.open(os.path.join(cls.build_path, "manifest.json"),
                     encoding="utf-8") as handle:
            return json.load(handle)


_BUILD_CACHE = {}


def legacy_migration_build(output_root):
    """Assemble the real quarantined build once per process.

    ``build_evidence`` reads a 30MB snapshot and derives 1,794 records, which
    takes about four seconds. Twenty tests each doing that spend a minute
    re-deriving bytes that cannot have changed. The result is a frozen value,
    so sharing it between tests cannot let one test observe another's edit -
    and ``output_root`` is only where a later ``write_evidence_build`` will
    put it, not something the assembly depends on.
    """
    from pgx.evidence.build import (EvidenceBuildRequest, ImportMode,
                                    build_evidence)
    if "legacy" not in _BUILD_CACHE:
        _BUILD_CACHE["legacy"] = build_evidence(EvidenceBuildRequest(
            snapshot_root=SNAPSHOT_ROOT,
            canonical_build_path=CANONICAL_BUILD,
            output_root=output_root,
            mode=ImportMode.LEGACY_MIGRATION,
            allow_new_identities=True))
    return _BUILD_CACHE["legacy"]


def require_sealed_inputs(test_case):
    """Skip when the real snapshot or canonical build is not in this checkout."""
    for path in (SNAPSHOT_ROOT, CANONICAL_BUILD):
        if not os.path.isdir(path):
            test_case.skipTest("no sealed input at %s" % path)
