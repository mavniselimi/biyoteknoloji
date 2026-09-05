# -*- coding: utf-8 -*-
"""Pack integrity: two levels of hash, and no self-hash (WP-25).

**Level one** is a digest per member: what each file in the pack is.

**Level two** is a digest over the sorted ``(path, digest)`` pairs: what the
pack *as a whole* is. Two levels rather than one because they answer different
questions - "has this document changed" and "is this the same pack" - and a
single flat hash cannot tell a reviewer which.

**No self-hash.** The manifest is a member of the pack, and a manifest that
contained a digest of itself would be a file that could never satisfy its own
check: writing the digest changes the bytes, which changes the digest. So the
manifest records every member *except itself*, and its own identity is the
level-two digest, which a verifier recomputes. This is not pedantry - a
self-referential manifest is a check that quietly always fails or, worse, one
somebody "fixes" by excluding the field, at which point the manifest is no
longer covered by anything.

The result of this module is deliberately **not** a THS 6 verdict. A pack can
be perfectly intact and describe a programme that has achieved nothing; those
are separate results with separate exit codes, and
``PACK_INTEGRITY_IS_NOT_ACHIEVEMENT`` is emitted alongside every one of them.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from pgx.ths6.models import repository_relative
from pgx.ths6.vocabulary import PACK_INTEGRITY_IS_NOT_ACHIEVEMENT

__all__ = [
    "MANIFEST_MEMBER_PATH",
    "PACK_INTEGRITY_VERSION",
    "canonical_json",
    "member_digest",
    "pack_digest",
    "build_pack_manifest",
    "verify_pack_manifest",
]

PACK_INTEGRITY_VERSION = "pgx-wp25-pack-integrity/1"

#: The manifest's own place in the pack. Excluded from its own member list.
MANIFEST_MEMBER_PATH = "data/ths6/wp25-evidence-pack-manifest.json"


def canonical_json(document: Mapping[str, object]) -> str:
    """The project's canonical JSON form, spelled the same way everywhere."""
    return json.dumps(document, indent=2, sort_keys=True,
                      ensure_ascii=True) + "\n"


def member_digest(absolute: str) -> str:
    """Level one: the digest of one member's bytes."""
    digest = hashlib.sha256()
    with open(absolute, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def pack_digest(members: Sequence[Mapping[str, object]]) -> str:
    """Level two: the digest of the pack, over paths and digests only.

    Deliberately excludes sizes, timestamps and every other observation. Two
    checkouts of the same commit on two machines produce the same pack digest,
    and a difference in it means content differs rather than that somebody
    ran the build on a different day.
    """
    payload = json.dumps(
        {"version": PACK_INTEGRITY_VERSION,
         "members": sorted((str(item["path"]), str(item["sha256"]))
                           for item in members)},
        sort_keys=True, ensure_ascii=True)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _member_entry(root: str, relative: str) -> Mapping[str, object]:
    repository_relative(relative)
    absolute = os.path.join(root, *relative.split("/"))
    if os.path.islink(absolute):
        return {"path": relative, "present": True, "sha256": None,
                "bytes": None, "state": "SYMLINK_REFUSED"}
    if not os.path.isfile(absolute):
        return {"path": relative, "present": False, "sha256": None,
                "bytes": None, "state": "ABSENT"}
    return {"path": relative, "present": True,
            "sha256": member_digest(absolute),
            "bytes": os.path.getsize(absolute), "state": "PRESENT"}


def build_pack_manifest(root: str, members: Sequence[str],
                        *, pack_version: str) -> Mapping[str, object]:
    """Build the manifest over ``members``, excluding the manifest itself."""
    considered = sorted({item for item in members
                         if item != MANIFEST_MEMBER_PATH})
    entries = [_member_entry(root, item) for item in considered]
    complete = [item for item in entries if item["state"] == "PRESENT"]
    absent = [str(item["path"]) for item in entries
              if item["state"] == "ABSENT"]
    refused = [str(item["path"]) for item in entries
               if item["state"] == "SYMLINK_REFUSED"]
    return {
        "pack_integrity_version": PACK_INTEGRITY_VERSION,
        "pack_version": pack_version,
        "manifest_member_path": MANIFEST_MEMBER_PATH,
        "manifest_excludes_itself": True,
        "manifest_self_hash": None,
        "manifest_self_hash_note": (
            "null by construction. A manifest containing a digest of itself "
            "could never satisfy its own check: writing the digest changes "
            "the bytes it describes. The pack's identity is "
            "'pack_sha256', which a verifier recomputes."),
        "member_count": len(entries),
        "present_member_count": len(complete),
        "absent_member_paths": absent,
        "refused_member_paths": refused,
        "members": entries,
        "pack_sha256": pack_digest(complete),
        "integrity_note": PACK_INTEGRITY_IS_NOT_ACHIEVEMENT,
    }


def verify_pack_manifest(root: str,
                         manifest: Mapping[str, object]) -> Mapping[str,
                                                                    object]:
    """Recompute every digest and the pack digest, and report differences.

    Returns a document, never a bare boolean. ``intact`` is one field among
    several, and callers that want to know *why* a pack is not intact have
    the changed, absent and added lists rather than a failed assertion.
    """
    declared = {str(item["path"]): item
                for item in manifest.get("members", ())  # type: ignore
                }
    changed: List[Mapping[str, object]] = []
    absent: List[str] = []
    for relative, entry in sorted(declared.items()):
        observed = _member_entry(root, relative)
        if observed["state"] == "ABSENT":
            if entry.get("state") != "ABSENT":
                absent.append(relative)
            continue
        if observed["state"] == "SYMLINK_REFUSED":
            changed.append({"path": relative,
                            "expected": entry.get("sha256"),
                            "observed": "symlink"})
            continue
        if entry.get("sha256") != observed["sha256"]:
            changed.append({"path": relative,
                            "expected": entry.get("sha256"),
                            "observed": observed["sha256"]})
    present_now = [_member_entry(root, relative)
                   for relative in sorted(declared)]
    recomputed = pack_digest([item for item in present_now
                              if item["state"] == "PRESENT"])
    declared_digest = manifest.get("pack_sha256")
    intact = (not changed and not absent
              and recomputed == declared_digest)
    return {
        "pack_integrity_version": PACK_INTEGRITY_VERSION,
        "declared_pack_sha256": declared_digest,
        "recomputed_pack_sha256": recomputed,
        "pack_digest_matches": recomputed == declared_digest,
        "changed_member_count": len(changed),
        "changed_members": changed,
        "absent_member_paths": absent,
        "member_count": len(declared),
        "intact": intact,
        "integrity_note": PACK_INTEGRITY_IS_NOT_ACHIEVEMENT,
        "achievement_note": (
            "This result describes the pack's bytes. It says nothing about "
            "whether any gate passed, and an intact pack that records six "
            "blocked gates is exactly what an honest blocked programme "
            "looks like."),
    }
