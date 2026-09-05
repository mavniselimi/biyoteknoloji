# -*- coding: utf-8 -*-
"""``pgx-dataset`` - build, verify and register raw snapshots (WP-06).

Console entry point: ``pgx-dataset``. ``scripts/dataset.py`` is a thin wrapper
that delegates here, so the logic exists once and the installed package owns it.

Rules this CLI follows, each for a reason:

* **No network.** Nothing here fetches anything. A snapshot is built from an
  acquisition run that already happened and from the cache that already holds
  its bytes; a CLI that could fetch would blur the line between "we have this"
  and "we can get this".
* **No implicit overwrite, and no ``--force``.** There is deliberately no flag
  that rewrites a sealed snapshot. A dataset ID is claimed once; a new
  acquisition gets a new ID. An operator who believes a sealed snapshot is
  wrong should verify it and say so, not overwrite the evidence.
* **No command promotes a dataset.** There is no ``publish``, no
  ``quality-check``, no ``approve``, and no argument that names a reviewer.
  Registration creates a ``BUILDING`` dataset and stops.
* **Explicit dataset IDs.** ``--dataset-id`` is required everywhere. Nothing
  scans the raw root for "the next number": two builders doing that race, and
  a dataset's identity would depend on what else was on disk.

Exit codes:

===  =========================================================
0    success
1    the build was refused, or verification found a problem
2    configuration failure - bad path, unreadable input
3    the named snapshot or acquisition manifest does not exist
4    the snapshot is sealed but could not be registered
===  =========================================================
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Mapping, Optional

from pgx.application.dataset_service import DatasetService, RegistrationOutcome
from pgx.ingestion.common.cache import ResponseCache
from pgx.ingestion.common.manifest_io import (
    ManifestDeserializationError,
    load_acquisition_manifest,
)
from pgx.application.snapshot_schema import validate_snapshot_manifest
from pgx.ingestion.snapshots import SnapshotError, SnapshotKind, SnapshotManager

__all__ = [
    "DEFAULT_RAW_ROOT",
    "EXIT_CONFIGURATION_FAILURE",
    "EXIT_NOT_FOUND",
    "EXIT_OK",
    "EXIT_REFUSED",
    "EXIT_SEALED_UNREGISTERED",
    "build_parser",
    "main",
]

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_CONFIGURATION_FAILURE = 2
EXIT_NOT_FOUND = 3
EXIT_SEALED_UNREGISTERED = 4

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

#: Where snapshots live unless ``--raw-root`` says otherwise. Rooted in the
#: repository rather than in ``/tmp`` or the working directory: a default that
#: moved with the shell's ``cwd`` would scatter immutable evidence.
DEFAULT_RAW_ROOT = os.path.join(_REPO_ROOT, "data", "raw")


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser. Separated so tests can exercise it alone."""
    parser = argparse.ArgumentParser(
        prog="pgx-dataset",
        description=("Build, verify and register immutable raw snapshots. This "
                     "tool never publishes or approves a dataset."))

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--raw-root", default=None,
                        help="Snapshot root (default: data/raw).")
    common.add_argument("--text", action="store_true",
                        help="Human-readable output instead of JSON.")

    identified = argparse.ArgumentParser(add_help=False, parents=[common])
    identified.add_argument("--dataset-id", required=True,
                            help="Explicit PGX-DATA-YYYYMMDD-NNN identifier.")
    identified.add_argument("--source-key", required=True,
                            help="Registered source key; also the directory name.")

    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser(
        "build-from-run", parents=[identified],
        help="Seal a snapshot from a WP-04 acquisition manifest and its cache.")
    build.add_argument("--acquisition-manifest", required=True,
                       help="Path to the run manifest JSON written by WP-04.")
    build.add_argument("--cache-dir", required=True,
                       help="Cache root holding the retrieved response bodies.")
    build.add_argument("--cache-replay", action="store_true",
                       help="Record the snapshot as CACHE_REPLAY rather than "
                            "ACQUISITION. Content identity is unaffected.")

    legacy = subparsers.add_parser(
        "import-legacy", parents=[identified],
        help="Package a legacy output directory as a QUARANTINED snapshot.")
    legacy.add_argument("--source-dir", required=True,
                        help="Legacy directory to copy. Never modified.")
    legacy.add_argument("--origin-note", default=None,
                        help="One factual sentence about where it came from.")
    legacy.add_argument("--limitation", action="append", default=[],
                        metavar="TEXT",
                        help="A limitation to record. Repeatable.")

    subparsers.add_parser(
        "verify", parents=[identified],
        help="Re-hash a sealed snapshot and report every integrity problem.")
    subparsers.add_parser(
        "inspect", parents=[identified],
        help="Print a sealed snapshot's manifest without re-hashing it.")
    subparsers.add_parser(
        "status", parents=[identified],
        help="Report the filesystem and database halves without changing them.")

    register = subparsers.add_parser(
        "register", parents=[identified],
        help="Verify a sealed snapshot and register it as a BUILDING dataset.")
    register.add_argument("--actor", required=True,
                          help="Who is registering this build.")
    register.add_argument("--reason", default=None,
                          help="Why, for the audit event.")

    return parser


def _emit(document: Mapping[str, Any]) -> None:
    sys.stdout.write(json.dumps(document, indent=2, ensure_ascii=False) + "\n")


def _fail(code: str, message: str) -> None:
    sys.stderr.write(json.dumps({"error": code, "message": message}) + "\n")


def _manager(args: argparse.Namespace) -> SnapshotManager:
    return SnapshotManager(args.raw_root or DEFAULT_RAW_ROOT)


def _service(args: argparse.Namespace,
             source_policy=None) -> DatasetService:
    return DatasetService(_manager(args), source_policy=source_policy)


def main(argv: Optional[List[str]] = None) -> int:
    """Entry point. Returns the exit code rather than calling ``exit``."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return _dispatch(args)
    except ManifestDeserializationError as exc:
        _fail("acquisition_manifest_invalid", str(exc))
        return EXIT_REFUSED
    except SnapshotError as exc:
        _fail("snapshot_error", str(exc))
        return EXIT_REFUSED
    except FileNotFoundError as exc:
        _fail("not_found", str(exc))
        return EXIT_NOT_FOUND
    except ValueError as exc:
        _fail("bad_argument", str(exc))
        return EXIT_CONFIGURATION_FAILURE
    except OSError as exc:
        _fail("io_failure", str(exc))
        return EXIT_CONFIGURATION_FAILURE


def _dispatch(args: argparse.Namespace) -> int:
    if args.command == "build-from-run":
        return _cmd_build(args)
    if args.command == "import-legacy":
        return _cmd_import_legacy(args)
    if args.command == "verify":
        return _cmd_verify(args)
    if args.command == "inspect":
        return _cmd_inspect(args)
    if args.command == "register":
        return _cmd_register(args)
    if args.command == "status":
        return _cmd_status(args)
    raise ValueError("unhandled command %r" % args.command)  # pragma: no cover


def _cmd_build(args: argparse.Namespace) -> int:
    manifest_path = os.path.abspath(os.path.expanduser(args.acquisition_manifest))
    if not os.path.isfile(manifest_path):
        _fail("not_found", "no acquisition manifest at %s" % manifest_path)
        return EXIT_NOT_FOUND
    if not os.path.isdir(os.path.abspath(os.path.expanduser(args.cache_dir))):
        _fail("not_found", "no cache directory at %s" % args.cache_dir)
        return EXIT_NOT_FOUND

    manifest = load_acquisition_manifest(manifest_path)
    cache = ResponseCache(args.cache_dir)
    kind = SnapshotKind.CACHE_REPLAY if args.cache_replay else SnapshotKind.ACQUISITION
    result = _service(args).build_from_run(
        args.dataset_id, args.source_key, manifest, cache, snapshot_kind=kind)

    if args.text:
        sys.stdout.write(_render_build(result))
    else:
        _emit(result.to_json())
    return EXIT_OK if result.snapshot.sealed else EXIT_REFUSED


def _cmd_import_legacy(args: argparse.Namespace) -> int:
    source_dir = os.path.abspath(os.path.expanduser(args.source_dir))
    if not os.path.isdir(source_dir):
        _fail("not_found", "no legacy directory at %s" % source_dir)
        return EXIT_NOT_FOUND

    limitations = tuple(args.limitation) or _DEFAULT_LEGACY_LIMITATIONS
    origin: Dict[str, Any] = {
        "source_directory": os.path.basename(source_dir.rstrip(os.sep)),
        "imported_by": "pgx-dataset import-legacy",
    }
    if args.origin_note:
        origin["note"] = args.origin_note

    result = _service(args).import_legacy(
        args.dataset_id, args.source_key, source_dir, limitations, origin)
    if args.text:
        sys.stdout.write(_render_build(result))
    else:
        _emit(result.to_json())
    return EXIT_OK if result.snapshot.sealed else EXIT_REFUSED


def _cmd_verify(args: argparse.Namespace) -> int:
    manager = _manager(args)
    if not manager.exists(args.source_key, args.dataset_id):
        # Distinguished from a failed verification on purpose: "there is no
        # snapshot here" and "this snapshot is damaged" call for different
        # actions, and an operator scripting on exit codes needs to tell them
        # apart.
        _fail("not_found", "no snapshot at %s"
              % manager.snapshot_path(args.source_key, args.dataset_id))
        return EXIT_NOT_FOUND
    result = manager.verify(args.source_key, args.dataset_id,
                            schema_validator=validate_snapshot_manifest)
    if args.text:
        sys.stdout.write(result.render() + "\n")
    else:
        _emit(result.to_json())
    return EXIT_OK if result.ok else EXIT_REFUSED


def _cmd_inspect(args: argparse.Namespace) -> int:
    manager = _manager(args)
    if not manager.exists(args.source_key, args.dataset_id):
        _fail("not_found", "no snapshot at %s"
              % manager.snapshot_path(args.source_key, args.dataset_id))
        return EXIT_NOT_FOUND
    manifest = manager.inspect(args.source_key, args.dataset_id)
    if args.text:
        for key, value in manifest.summary().items():
            sys.stdout.write("%-24s %s\n" % (key, value))
        for limitation in manifest.limitations:
            sys.stdout.write("limitation               %s\n" % limitation)
    else:
        _emit(manifest.payload())
    return EXIT_OK


def _cmd_register(args: argparse.Namespace) -> int:
    manager = _manager(args)
    if not manager.exists(args.source_key, args.dataset_id):
        _fail("not_found", "no snapshot at %s"
              % manager.snapshot_path(args.source_key, args.dataset_id))
        return EXIT_NOT_FOUND
    result = _service(args).register(
        args.source_key, args.dataset_id, actor=args.actor, reason=args.reason)
    if args.text:
        sys.stdout.write(_render_build(result))
    else:
        _emit(result.to_json())
    if result.registration in (RegistrationOutcome.REGISTERED,
                               RegistrationOutcome.ALREADY_REGISTERED):
        return EXIT_OK
    return EXIT_SEALED_UNREGISTERED


def _cmd_status(args: argparse.Namespace) -> int:
    document = _service(args).status(args.source_key, args.dataset_id)
    if args.text:
        for key, value in document.items():
            if key == "manifest":
                continue
            sys.stdout.write("%-22s %s\n" % (key, value))
    else:
        _emit(document)
    return EXIT_OK if document["snapshot_sealed"] else EXIT_NOT_FOUND


def _render_build(result) -> str:
    lines = [
        "dataset:      %s" % result.dataset_public_id,
        "snapshot:     %s" % (result.snapshot.snapshot_path or "(not created)"),
        "sealed:       %s" % ("yes" if result.snapshot.sealed else "NO"),
        "registration: %s" % result.registration.value,
    ]
    if result.snapshot.manifest is not None:
        manifest = result.snapshot.manifest
        lines.extend([
            "kind:         %s" % manifest.snapshot_kind.value,
            "state:        %s" % manifest.snapshot_state.value,
            "artifacts:    %d" % manifest.artifact_count,
            "bytes:        %d" % manifest.total_byte_count,
            "content hash: %s" % manifest.snapshot_content_hash,
            "manifest hash:%s" % manifest.manifest_hash,
            "publishable:  %s" % ("yes" if manifest.publication_eligible else "no"),
        ])
    for issue in result.issues:
        lines.append("  " + issue.render())
    return "\n".join(lines) + "\n"


#: Recorded on a legacy import when the caller names no limitations. These are
#: facts about what is absent, not decoration: anybody reading such a snapshot
#: needs to know which questions it cannot answer.
_DEFAULT_LEGACY_LIMITATIONS = (
    "No WP-04 acquisition run backs these bytes; there is no trustworthy run "
    "identifier, request chronology, retry record or rate-limit metadata.",
    "Completeness relative to the upstream source is unknown and is not "
    "implied by every file present having been copied.",
    "The source policy for these bytes is unknown; no named human has reviewed "
    "whether they may be used.",
    "No canonicalization, no data-quality assessment, no evidence extraction "
    "and no interpretation has been performed.",
)
