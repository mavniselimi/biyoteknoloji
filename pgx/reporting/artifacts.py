# -*- coding: utf-8 -*-
"""Immutable report artifacts and their manifests (WP-15).

A published report is a file somebody will read later, quote in a review, or
compare against another one. Three properties make that safe, and each is
enforced here rather than assumed of the caller.

**A name is a function of the content.** The artifact is named from the
assessment identity, the locale and the report hash, so two different reports
cannot claim one filename and the same report always claims the same one.
Nothing in the name comes from a clock.

**A published report is never silently overwritten.** Writing over an existing
artifact whose content differs raises. Writing the *identical* bytes is a
no-op that succeeds, so a re-run is idempotent and a changed report is a
refusal rather than a quiet replacement of something a reviewer may already
have read.

**The manifest is written last.** Everything is staged into temporary files in
the destination directory and moved into place with :func:`os.replace`, which
is atomic within a filesystem; the manifest lands only after the document it
describes. A crash therefore leaves at worst a report with no manifest - a
state :func:`read_artifact` refuses loudly - and never a manifest promising a
document that is not there. Temporary files are removed on any failure.

**Reading verifies.** :func:`read_artifact` recomputes the checksum of the
bytes on disk and compares it with the manifest before returning anything.
"""

from __future__ import annotations

import io
import json
import os
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from pgx.domain.hashing import sha256_digest
from pgx.reporting.errors import ReportArtifactError
from pgx.reporting.render import RENDERER_VERSION, rendered_checksum

__all__ = [
    "ARTIFACT_MANIFEST_SCHEMA_VERSION",
    "MANIFEST_FIELDS",
    "artifact_name",
    "build_manifest",
    "read_artifact",
    "write_artifact",
]

ARTIFACT_MANIFEST_SCHEMA_VERSION = "pgx-report-artifact-manifest/1"

#: Every field a manifest carries. Enumerated so an incomplete manifest is
#: refused by name rather than discovered when something reads it.
MANIFEST_FIELDS: Tuple[str, ...] = (
    "manifest_schema_version", "report_schema_version", "template_version",
    "renderer_version", "locale", "assessment_id", "input_hash",
    "output_hash", "coverage_result_hash", "canonical_result_hash",
    "report_hash", "rendered_checksum", "rendered_bytes", "document_filename",
    "manifest_filename", "release_provenance", "fact_ledger",
    "claim_scan", "engine_contract_version", "computation_schema_version",
    "note")

#: A dot is not a path separator, but ``..`` in a filename reads as one to
#: every person who sees it and to some tools that do not parse carefully.
#: The extension is appended after slugging, so nothing here needs one.
_SAFE_NAME = re.compile(r"[^A-Za-z0-9_-]")
_NOTE = (
    "An immutable rendered report and the facts it was checked against. The "
    "document is a presentation projection of a stored assessment: nothing "
    "here was recalculated, and nothing here is a clinical decision, a "
    "diagnosis, a dose or a treatment selection.")


def _slug(value: str) -> str:
    """A filename-safe fragment. Deterministic and lossy in one direction."""
    return _SAFE_NAME.sub("-", str(value))[:64]


def artifact_name(*, assessment_id: str, locale: str, report_hash: str
                  ) -> str:
    """The deterministic base name for one report artifact.

    ``<assessment id>-<locale>-<first 16 hex of the report hash>``. The hash
    fragment is what makes the name a function of the content: a report of the
    same assessment in the same locale under a changed template lands beside
    the old one rather than on top of it.
    """
    digest = report_hash.split(":")[-1][:16]
    if not digest:
        raise ReportArtifactError(
            "an artifact is named from its report hash, and this report has "
            "none", code="REPORT_ARTIFACT_INCOMPLETE",
            location="$.report_hash")
    return "report-%s-%s-%s" % (_slug(assessment_id), _slug(locale), digest)


def build_manifest(report, *, rendered: str, fact_ledger: Mapping[str, Any],
                   claim_scan: Mapping[str, Any],
                   document_filename: str,
                   manifest_filename: str) -> Dict[str, Any]:
    """The manifest for one rendered report.

    Carries both hashes and the byte checksum: ``output_hash`` says whether
    the facts are the same, ``report_hash`` whether the document is, and
    ``rendered_checksum`` whether the bytes are. A renderer change moves the
    third and not the first two, which is exactly the distinction an operator
    needs when a diff appears.
    """
    manifest = {
        "manifest_schema_version": ARTIFACT_MANIFEST_SCHEMA_VERSION,
        "report_schema_version": report.report_schema_version,
        "template_version": report.template_version,
        "renderer_version": RENDERER_VERSION,
        "locale": report.locale,
        "assessment_id": report.assessment_id,
        "input_hash": report.input_hash,
        "output_hash": report.output_hash,
        "coverage_result_hash": report.coverage_result_hash,
        "canonical_result_hash": report.canonical_result_hash,
        "report_hash": report.report_hash(),
        "rendered_checksum": rendered_checksum(rendered),
        "rendered_bytes": len(rendered.encode("utf-8")),
        "document_filename": document_filename,
        "manifest_filename": manifest_filename,
        "release_provenance": dict(report.release_provenance),
        "fact_ledger": dict(fact_ledger),
        "claim_scan": dict(claim_scan),
        "engine_contract_version": report.engine_contract_version,
        "computation_schema_version": report.computation_schema_version,
        "note": _NOTE,
    }
    missing = tuple(name for name in MANIFEST_FIELDS if name not in manifest)
    if missing:  # pragma: no cover - defensive
        raise ReportArtifactError(
            "the manifest is missing %s" % ", ".join(missing),
            code="REPORT_ARTIFACT_INCOMPLETE", location="$")
    return manifest


def _read_text(path: str) -> str:
    with io.open(path, encoding="utf-8") as handle:
        return handle.read()


def _atomic_write(path: str, text: str, staged: List[str]) -> None:
    temporary = path + ".tmp"
    staged.append(temporary)
    with io.open(temporary, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    os.replace(temporary, path)
    staged.remove(temporary)


def write_artifact(report, *, rendered: str, fact_ledger: Mapping[str, Any],
                   claim_scan: Mapping[str, Any], directory: str
                   ) -> Dict[str, Any]:
    """Write one report and its manifest atomically, or write nothing.

    Raises:
        ReportArtifactError: an artifact of this name already exists carrying
            different content, or the write could not be completed.

    Returns:
        A record naming both paths and whether anything was written. Rewriting
        identical content returns ``written: False`` rather than raising:
        regenerating a report that has not changed is a normal thing to do,
        and making it an error would push callers into deleting files first.
    """
    if not isinstance(rendered, str) or not rendered:
        raise ReportArtifactError(
            "there is nothing to write", code="REPORT_ARTIFACT_INCOMPLETE",
            location="$.rendered")
    base = artifact_name(assessment_id=report.assessment_id,
                         locale=report.locale,
                         report_hash=report.report_hash())
    document_filename = base + ".md"
    manifest_filename = base + ".manifest.json"
    document_path = os.path.join(directory, document_filename)
    manifest_path = os.path.join(directory, manifest_filename)
    manifest = build_manifest(report, rendered=rendered,
                              fact_ledger=fact_ledger, claim_scan=claim_scan,
                              document_filename=document_filename,
                              manifest_filename=manifest_filename)
    manifest_text = json.dumps(manifest, ensure_ascii=False, sort_keys=True,
                               indent=2) + "\n"

    if os.path.exists(document_path):
        existing = _read_text(document_path)
        if existing != rendered:
            raise ReportArtifactError(
                "an artifact named %s already exists and carries different "
                "content. A published report is never silently overwritten: "
                "somebody may have read the one on disk."
                % document_filename,
                code="REPORT_ARTIFACT_CONFLICT",
                location="$.%s" % document_filename)
        if os.path.exists(manifest_path) and \
                _read_text(manifest_path) == manifest_text:
            return {"written": False, "document_path": document_path,
                    "manifest_path": manifest_path, "manifest": manifest,
                    "reason": "identical content already published"}

    os.makedirs(directory, exist_ok=True)
    staged: List[str] = []
    try:
        # The document first, the manifest last. A crash between them leaves a
        # report with no manifest, which reads as incomplete; the other order
        # would leave a manifest promising a document nobody wrote.
        _atomic_write(document_path, rendered, staged)
        _atomic_write(manifest_path, manifest_text, staged)
    except Exception:
        for temporary in list(staged):
            try:
                os.remove(temporary)
            except OSError:  # pragma: no cover - best effort cleanup
                pass
        raise
    return {"written": True, "document_path": document_path,
            "manifest_path": manifest_path, "manifest": manifest,
            "reason": "published"}


def read_artifact(manifest_path: str) -> Dict[str, Any]:
    """Read one artifact back, verifying it against its manifest.

    Raises:
        ReportArtifactError: the manifest is incomplete, the document it names
            is absent, or the bytes on disk do not hash to what it records.
    """
    if not os.path.isfile(manifest_path):
        raise ReportArtifactError(
            "no manifest at %s" % manifest_path,
            code="REPORT_ARTIFACT_INCOMPLETE", location="$.manifest_path")
    manifest = json.loads(_read_text(manifest_path))
    missing = tuple(name for name in MANIFEST_FIELDS if name not in manifest)
    if missing:
        raise ReportArtifactError(
            "the manifest at %s is missing %s"
            % (manifest_path, ", ".join(missing)),
            code="REPORT_ARTIFACT_INCOMPLETE", location="$.manifest")
    document_path = os.path.join(os.path.dirname(manifest_path),
                                 manifest["document_filename"])
    if not os.path.isfile(document_path):
        raise ReportArtifactError(
            "the manifest names %s, which is not there"
            % manifest["document_filename"],
            code="REPORT_ARTIFACT_INCOMPLETE", location="$.document_filename")
    rendered = _read_text(document_path)
    checksum = rendered_checksum(rendered)
    if checksum != manifest["rendered_checksum"]:
        raise ReportArtifactError(
            "%s hashes to %s; its manifest records %s. The document changed "
            "after it was published."
            % (manifest["document_filename"], checksum,
               manifest["rendered_checksum"]),
            code="REPORT_ARTIFACT_HASH_MISMATCH",
            location="$.rendered_checksum")
    if len(rendered.encode("utf-8")) != manifest["rendered_bytes"]:
        raise ReportArtifactError(
            "%s is %d bytes; its manifest records %d"
            % (manifest["document_filename"],
               len(rendered.encode("utf-8")), manifest["rendered_bytes"]),
            code="REPORT_ARTIFACT_HASH_MISMATCH",
            location="$.rendered_bytes")
    ledger = manifest.get("fact_ledger") or {}
    recorded = ledger.get("ledger_hash")
    if recorded is not None:
        recomputed = sha256_digest({key: value for key, value in ledger.items()
                                    if key != "ledger_hash"})
        if recomputed != recorded:
            raise ReportArtifactError(
                "the stored fact ledger recomputes to %s and records %s"
                % (recomputed, recorded),
                code="REPORT_ARTIFACT_HASH_MISMATCH",
                location="$.fact_ledger.ledger_hash")
    return {"manifest": manifest, "rendered": rendered,
            "document_path": document_path, "manifest_path": manifest_path,
            "verified": True}
