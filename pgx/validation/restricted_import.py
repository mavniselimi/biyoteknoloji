# -*- coding: utf-8 -*-
"""The fail-closed boundary restricted payloads enter through (WP-18).

Nothing has ever passed through this. There is no restricted storage in this
repository, no expert payload exists, and none is committed - the boundary is
built so that WP-22 has somewhere safe to bring one, and so that the rules
governing that moment are written down while nobody is under time pressure.

Eight properties, each of which is a thing that goes wrong when an import
boundary is written casually:

1. **Schema before persistence.** The document is validated before anything is
   written, because a half-written invalid payload is harder to reason about
   than a refused one.
2. **Role and provenance enforced.** A payload arriving as a holdout must
   satisfy every holdout obligation - independent provenance, not derived from
   development - or it is not a holdout whatever the file says.
3. **Hashes computed here.** A declared hash is checked against a computed
   one, and the computed one wins. Trusting a supplied digest makes the digest
   decorative.
4. **No traversal, no symlink escape.** Both are checked after resolution, not
   before, because ``a/../../b`` and a symlink both look fine as strings.
5. **Atomic write.** Write to a temporary file in the destination directory,
   fsync, then rename. A rename within one filesystem is atomic, so a reader
   sees the old file or the new one and never a partial one.
6. **Previous state preserved on failure.** Every refusal happens before the
   rename, so a failed import leaves exactly what was there before.
7. **Controlled issue codes.** Callers get codes, never a raw exception - the
   exceptions raised down here quote paths, and a path is one of the things
   this boundary exists not to disclose.
8. **An audit written without answers.** The result records what was imported
   and whether separation held. It records no payload content, and a test
   asserts the audit against the prohibited-field list.

**No payload is ever logged.** Not on success, not on failure, not in an
exception message. That rule is why the issue codes are coarse.
"""

from __future__ import annotations

import io
import json
import os
import tempfile
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from pgx.domain.hashing import sha256_digest
from pgx.domain.immutable import thaw_json
from pgx.validation.cases import (PROHIBITED_PAYLOAD_FIELDS, RestrictedPayload,
                                  ValidationCaseMetadata,
                                  assert_no_prohibited_fields)
from pgx.validation.errors import (ImportRefusedError, SeparationError,
                                   ValidationCaseError)
from pgx.validation.separation import audit_partition
from pgx.validation.vocabulary import HOLDOUT_ROLES, ValidationCaseRole

__all__ = [
    "IMPORT_ISSUE_CODES",
    "MAX_PAYLOAD_BYTES",
    "RESTRICTED_IMPORT_VERSION",
    "ImportResult",
    "import_restricted_payload",
    "resolve_within",
]

RESTRICTED_IMPORT_VERSION = "pgx-wp18-restricted-import/1"

#: A payload describes one case's inputs. A megabyte is already far more than
#: a phenotype profile and a medication list need, and refusing above it means
#: a mistaken path - a sequencing file, an archive - is rejected on size
#: before anything tries to parse it.
MAX_PAYLOAD_BYTES = 1_048_576

IMPORT_ISSUE_CODES: Mapping[str, str] = {
    "STORAGE_NOT_CONFIGURED":
        "no restricted storage root was supplied, so there is nowhere to "
        "import into",
    "PATH_ESCAPES_ROOT":
        "the destination resolves outside the restricted storage root",
    "SYMLINK_IN_PATH":
        "the destination path passes through a symbolic link",
    "PAYLOAD_TOO_LARGE":
        "the payload exceeds the permitted size",
    "PAYLOAD_MALFORMED":
        "the payload is not a JSON object this boundary can read",
    "PROHIBITED_FIELD":
        "the payload carries a field this product does not accept",
    "ROLE_NOT_HOLDOUT":
        "restricted import accepts holdout cases only",
    "PROVENANCE_INSUFFICIENT":
        "the case does not satisfy the holdout provenance obligations",
    "DECLARED_HASH_MISMATCH":
        "the declared payload hash does not match the computed one",
    "FINGERPRINT_MISMATCH":
        "the declared content fingerprint does not match the payload",
    "SEPARATION_VIOLATION":
        "importing this case would break development/holdout separation",
    "DUPLICATE_CASE_ID":
        "a case with this identifier is already present",
    "WRITE_FAILED":
        "the atomic write did not complete; the previous state is unchanged",
}


def resolve_within(root: str, relative: str) -> str:
    """Resolve ``relative`` under ``root``, or refuse.

    Resolution first, checks after. ``os.path.realpath`` collapses ``..`` and
    follows every symlink, so the containment test is applied to where the
    path actually lands rather than to how it was spelled - which is the only
    version of this check that works.
    """
    if not isinstance(root, str) or not root:
        raise ImportRefusedError(["STORAGE_NOT_CONFIGURED"])
    if not isinstance(relative, str) or not relative or \
            os.path.isabs(relative):
        raise ImportRefusedError(["PATH_ESCAPES_ROOT"])

    real_root = os.path.realpath(root)
    candidate = os.path.realpath(os.path.join(real_root, relative))
    if candidate != real_root and not candidate.startswith(
            real_root + os.sep):
        raise ImportRefusedError(["PATH_ESCAPES_ROOT"])

    # A symlink anywhere on the way in is refused even when it happens to land
    # inside the root: it is a link somebody can repoint later, and this
    # boundary must not depend on nobody doing that.
    #
    # Walked over the *unresolved* components. Walking the resolved path finds
    # nothing, because resolution is precisely what replaced the link with its
    # target - which is how a containment check ends up reporting that a
    # symlink is not a symlink.
    walked = real_root
    for part in relative.replace("\\", "/").split("/"):
        if part in ("", "."):
            continue
        walked = os.path.join(walked, part)
        if os.path.islink(walked):
            raise ImportRefusedError(["SYMLINK_IN_PATH"])
    return candidate


@dataclass(frozen=True, slots=True)
class ImportResult:
    """What one import did. Carries no payload content."""

    case_id: str
    role: str
    payload_hash: str
    content_fingerprint: str
    stored_relative_path: str
    byte_count: int
    separation_clean: bool
    separation_issue_codes: Tuple[str, ...]
    import_version: str = RESTRICTED_IMPORT_VERSION

    def to_json(self) -> Dict[str, Any]:
        return {
            "import_version": self.import_version,
            "case_id": self.case_id,
            "role": self.role,
            "payload_hash": self.payload_hash,
            "content_fingerprint": self.content_fingerprint,
            "stored_relative_path": self.stored_relative_path,
            "byte_count": self.byte_count,
            "separation_clean": self.separation_clean,
            "separation_issue_codes": list(self.separation_issue_codes),
        }


def _atomic_write(destination: str, body: str) -> None:
    """Write via a temporary file in the same directory, then rename.

    Same directory because rename is only atomic within one filesystem, and a
    temporary file in ``/tmp`` may be on another. ``fsync`` before the rename
    so a crash cannot leave a renamed file with unwritten contents.
    """
    directory = os.path.dirname(destination)
    if not os.path.isdir(directory):
        os.makedirs(directory, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="\n", dir=directory,
        prefix=".import-", suffix=".tmp", delete=False)
    try:
        with handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(handle.name, destination)
    except Exception:  # noqa: BLE001 - re-typed; the previous file is intact
        try:
            os.unlink(handle.name)
        except OSError:  # pragma: no cover - best effort cleanup
            pass
        raise ImportRefusedError(["WRITE_FAILED"])


def import_restricted_payload(
        *, storage_root: Optional[str], case: ValidationCaseMetadata,
        payload_document: Mapping[str, Any],
        existing_cases: Sequence[ValidationCaseMetadata] = (),
        relative_path: Optional[str] = None) -> ImportResult:
    """Bring one holdout payload into restricted storage, or refuse.

    Every refusal happens before the atomic rename, so a refused import leaves
    the destination exactly as it was. The return value is a result record fit
    for an audit artifact; it names hashes and counts and no content.
    """
    if not storage_root:
        raise ImportRefusedError(["STORAGE_NOT_CONFIGURED"])
    if not isinstance(case, ValidationCaseMetadata):
        raise ValidationCaseError("case must be a ValidationCaseMetadata")
    if case.role not in HOLDOUT_ROLES:
        raise ImportRefusedError(["ROLE_NOT_HOLDOUT"])
    if case.provenance.derived_from_development or (
            case.provenance.source_digest is None
            and case.provenance.citation is None):
        raise ImportRefusedError(["PROVENANCE_INSUFFICIENT"])

    if not isinstance(payload_document, Mapping) or not payload_document:
        raise ImportRefusedError(["PAYLOAD_MALFORMED"])
    try:
        assert_no_prohibited_fields(payload_document,
                                    PROHIBITED_PAYLOAD_FIELDS)
    except ValidationCaseError:
        # The underlying message names the field; it is deliberately not
        # forwarded, because this boundary's errors may be logged and the
        # field name is enough for the importer to act on.
        raise ImportRefusedError(["PROHIBITED_FIELD"])

    try:
        payload = RestrictedPayload(dict(payload_document))
    except ValidationCaseError:
        raise ImportRefusedError(["PAYLOAD_MALFORMED"])

    # Thawed before serialising: a frozen payload holds FrozenMapping values
    # all the way down, and json.dumps has no idea what those are.
    body = json.dumps({"schema_version": RESTRICTED_IMPORT_VERSION,
                       "case_id": case.case_id.value,
                       "content": thaw_json(payload.content)},
                      indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    encoded = body.encode("utf-8")
    if len(encoded) > MAX_PAYLOAD_BYTES:
        raise ImportRefusedError(["PAYLOAD_TOO_LARGE"])

    computed_hash = payload.payload_hash
    if case.payload_hash is not None and case.payload_hash != computed_hash:
        raise ImportRefusedError(["DECLARED_HASH_MISMATCH"])
    if case.content_fingerprint != payload.fingerprint:
        raise ImportRefusedError(["FINGERPRINT_MISMATCH"])

    known = {entry.case_id.value for entry in existing_cases}
    if case.case_id.value in known:
        raise ImportRefusedError(["DUPLICATE_CASE_ID"])

    audit = audit_partition(list(existing_cases) + [case])
    if not audit.is_clean:
        raise ImportRefusedError(["SEPARATION_VIOLATION"],
                                 ", ".join(audit.issue_codes))

    relative = relative_path or ("%s.json" % case.case_id.value)
    destination = resolve_within(storage_root, relative)
    _atomic_write(destination, body)

    return ImportResult(
        case_id=case.case_id.value,
        role=case.role.value,
        payload_hash=computed_hash,
        content_fingerprint=payload.fingerprint,
        stored_relative_path=relative,
        byte_count=len(encoded),
        separation_clean=audit.is_clean,
        separation_issue_codes=audit.issue_codes)
