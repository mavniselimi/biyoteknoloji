# -*- coding: utf-8 -*-
"""``pgx-ingest-clinpgx`` - plan, run, replay and inspect acquisitions (WP-04).

Console entry point: ``pgx-ingest-clinpgx``. ``scripts/ingest_clinpgx.py`` is a
thin wrapper that delegates here.

Rules this CLI follows, each for a concrete reason:

* **Which subcommands touch the network is stated, not implied.** ``plan``,
  ``replay-cache``, ``validate-cache`` and ``inspect-run`` never build a
  transport. ``acquire`` is the only one that can, and it says so in its help
  text and in its JSON output.
* **Every path is explicit.** ``--cache-dir`` is required; there is no default
  output directory. The legacy probes wrote to a module-level ``OUT_DIR``, so
  importing them decided where data went.
* **Endpoints are named by catalog ID only.** A path or a URL on the command
  line would reach an endpoint nobody declared.
* **No database.** Acquisition produces files and a manifest; persistence is a
  later work package.
* **No credential in any output.** The token is read from the environment by
  the transport and never printed; failure text is redacted before it is
  written.
* **Exit codes are an interface**, so a scheduler can branch on *why* a run
  failed rather than on stderr text.

Exit codes:

===  ==========================================================
0    success; an acquisition completed (warnings permitted)
1    the run finished but is not publishable (FAILED)
2    configuration or safety failure - the run did not start
3    a cache-only operation could not be satisfied
4    a manifest or cache failed validation
===  ==========================================================

Importing this module opens no connection, and neither does parsing arguments.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
from typing import Any, List, Mapping, Optional

from pgx.ingestion.clinpgx.catalog import catalog_ids, clinpgx_catalog
from pgx.ingestion.common.errors import (
    CacheError, CacheMissError, ConfigurationError, IngestionError,
)

__all__ = [
    "EXIT_CACHE_UNAVAILABLE",
    "EXIT_CONFIGURATION_FAILURE",
    "EXIT_OK",
    "EXIT_RUN_FAILED",
    "EXIT_VALIDATION_FAILED",
    "NETWORK_SUBCOMMANDS",
    "build_parser",
    "main",
]

EXIT_OK = 0
EXIT_RUN_FAILED = 1
EXIT_CONFIGURATION_FAILURE = 2
EXIT_CACHE_UNAVAILABLE = 3
EXIT_VALIDATION_FAILED = 4

#: The only subcommand that may open a connection. A test asserts that no other
#: code path builds a transport.
NETWORK_SUBCOMMANDS = ("acquire",)

#: Parameters the catalog's query builders read. Declared here so the CLI can
#: pass them through without knowing what any of them mean.
_PARAMETER_OPTIONS = (
    ("--symbol", "symbol", "Gene symbol, for gene and variant endpoints."),
    ("--name", "name", "Chemical name, for the chemical endpoint."),
    ("--gene-accession-id", "gene_accession_id",
     "ClinPGx gene accession ID, for guideline endpoints."),
    ("--chemical-accession-id", "chemical_accession_id",
     "ClinPGx chemical accession ID, for guideline endpoints."),
    ("--first-id", "first_id", "First object ID, for the pair report."),
    ("--second-id", "second_id", "Second object ID, for the pair report."),
    ("--result-type", "result_type", "Result type, for the pair report."),
    ("--object-id", "object_id", "Object ID, for connected objects."),
    ("--object-type", "object_type", "Object type, for connected objects."),
    ("--view", "view", "ClinPGx view parameter (default: base)."),
)


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser. Separated so tests can exercise it alone."""
    parser = argparse.ArgumentParser(
        prog="pgx-ingest-clinpgx",
        description=(
            "Acquire raw ClinPGx responses. Acquisition preserves source bytes "
            "and records what was retrieved; it performs no scientific "
            "interpretation, resolution or curation."))
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan = subparsers.add_parser(
        "plan", help="Show every request a run would make. Makes no request.")
    _add_common(plan)
    _add_parameters(plan)

    acquire = subparsers.add_parser(
        "acquire",
        help="Run an acquisition. THIS SUBCOMMAND MAKES NETWORK REQUESTS.")
    _add_common(acquire)
    _add_parameters(acquire)
    acquire.add_argument("--run-dir", default=None,
                         help="Directory to write the run manifest into.")
    acquire.add_argument("--timeout", type=float, default=30.0,
                         help="Per-request timeout in seconds (default 30).")
    acquire.add_argument("--max-attempts", type=int, default=4,
                         help="Maximum attempts per request (default 4).")
    acquire.add_argument("--max-pages", type=int, default=None,
                         help="Override the per-endpoint page limit.")
    acquire.add_argument("--refresh", action="store_true",
                         help="Ignore cached responses and re-fetch.")

    replay = subparsers.add_parser(
        "replay-cache",
        help="Re-run entirely from cache. Opens no connection.")
    _add_common(replay)
    _add_parameters(replay)
    replay.add_argument("--run-dir", default=None,
                        help="Directory to write the replay manifest into.")

    validate = subparsers.add_parser(
        "validate-cache", help="Re-hash every stored blob.")
    validate.add_argument("--cache-dir", required=True,
                          help="Cache root. Required; there is no default.")

    inspect = subparsers.add_parser(
        "inspect-run", help="Summarise a manifest written by an earlier run.")
    inspect.add_argument("--manifest", required=True,
                         help="Path to a run manifest JSON file.")
    inspect.add_argument("--full", action="store_true",
                         help="Print the whole manifest, not a summary.")
    return parser


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--cache-dir", required=True,
                        help="Cache root. Required; there is no default output "
                             "directory.")
    parser.add_argument(
        "--endpoint", action="append", dest="endpoints", default=None,
        metavar="ENDPOINT_ID",
        help="Catalog endpoint ID; repeatable. Valid IDs: %s. Paths and URLs "
             "are not accepted." % ", ".join(catalog_ids()))


def _add_parameters(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("endpoint parameters")
    for flag, _dest, help_text in _PARAMETER_OPTIONS:
        group.add_argument(flag, default=None, help=help_text)


def _parameters_from(args) -> Mapping[str, Any]:
    """Collect the endpoint parameters the user supplied."""
    values = {}
    for flag, dest, _help in _PARAMETER_OPTIONS:
        attribute = flag.lstrip("-").replace("-", "_")
        value = getattr(args, attribute, None)
        if value is not None:
            values[dest] = value
    values.setdefault("view", "base")
    return values


def _emit(document: Mapping[str, Any]) -> None:
    """Print one JSON document to stdout."""
    sys.stdout.write(json.dumps(document, indent=2, sort_keys=True,
                                default=str) + "\n")


def _fail(code: str, message: str) -> None:
    """Print a machine-readable failure to stderr, already redacted."""
    sys.stderr.write(json.dumps({"error": code, "detail": message},
                                sort_keys=True) + "\n")


def _redact(text: str) -> str:
    """Strip anything credential-shaped before it reaches an operator's log."""
    from pgx.infrastructure.db.config import sanitize_message

    return sanitize_message(str(text))


def _build_service(args, network: bool):
    """Construct the service. Builds a transport only when ``network``."""
    from pgx.application.ingestion_service import IngestionService
    from pgx.ingestion.common.cache import ResponseCache
    from pgx.ingestion.common.retry import RetryPolicy

    cache = ResponseCache(args.cache_dir)
    factory = None
    if network:
        from pgx.ingestion.clinpgx.client import build_clinpgx_transport

        def factory():  # noqa: F811 - deliberate late binding
            return build_clinpgx_transport()

    policy = RetryPolicy(max_attempts=getattr(args, "max_attempts", 4) or 4)
    return IngestionService(
        cache=cache, transport_factory=factory, retry_policy=policy,
        timeout_seconds=getattr(args, "timeout", 30.0) or 30.0)


def _write_manifest(run_dir: Optional[str], manifest) -> Optional[str]:
    """Write the run manifest, if a directory was given. Returns its path."""
    if not run_dir:
        return None
    os.makedirs(run_dir, exist_ok=True)
    path = os.path.join(run_dir, "acquisition-manifest-%s.json"
                        % manifest.run_id.to_json())
    with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(manifest.to_json(), indent=2, sort_keys=True,
                                default=str) + "\n")
    return path


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point for ``pgx-ingest-clinpgx``."""
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "plan":
            service = _build_service(args, network=False)
            plan = service.plan_acquisition(_parameters_from(args), args.endpoints)
            _emit(dict(plan.to_json(), command="plan",
                       network_used=False))
            return EXIT_OK

        if args.command == "acquire":
            service = _build_service(args, network=True)
            manifest = service.acquire(_parameters_from(args), args.endpoints,
                                       refresh=args.refresh)
            path = _write_manifest(args.run_dir, manifest)
            _emit(dict(manifest.summary(), command="acquire",
                       network_used=True, manifest_path=path,
                       warnings=list(manifest.warnings),
                       failures=list(manifest.failures)))
            return EXIT_OK if manifest.is_publishable else EXIT_RUN_FAILED

        if args.command == "replay-cache":
            service = _build_service(args, network=False)
            manifest = service.replay_from_cache(_parameters_from(args),
                                                 args.endpoints)
            path = _write_manifest(args.run_dir, manifest)
            _emit(dict(manifest.summary(), command="replay-cache",
                       network_used=False, manifest_path=path,
                       warnings=list(manifest.warnings),
                       failures=list(manifest.failures)))
            if manifest.is_publishable:
                return EXIT_OK
            missing = any("CACHE_MISS" in (record.error_code or "")
                          for endpoint in manifest.endpoints
                          for record in endpoint.records)
            return EXIT_CACHE_UNAVAILABLE if missing else EXIT_RUN_FAILED

        if args.command == "validate-cache":
            service = _build_service(args, network=False)
            report = service.validate_cache()
            _emit(dict(report, command="validate-cache", network_used=False))
            return EXIT_OK if report["healthy"] else EXIT_VALIDATION_FAILED

        if args.command == "inspect-run":
            with io.open(args.manifest, encoding="utf-8") as handle:
                document = json.load(handle)
            _emit(dict(_summarise(document), command="inspect-run",
                       network_used=False,
                       full=document if args.full else None))
            return EXIT_OK if document.get("is_publishable") else EXIT_RUN_FAILED

        _fail("UNKNOWN_COMMAND", "no handler for %r" % args.command)
        return EXIT_CONFIGURATION_FAILURE

    except ConfigurationError as exc:
        _fail("CONFIGURATION_FAILURE",
              "%s: %s" % (type(exc).__name__, _redact(exc)))
        return EXIT_CONFIGURATION_FAILURE
    except CacheMissError as exc:
        _fail("CACHE_MISS", _redact(exc))
        return EXIT_CACHE_UNAVAILABLE
    except CacheError as exc:
        _fail("CACHE_FAILURE", "%s: %s" % (type(exc).__name__, _redact(exc)))
        return EXIT_VALIDATION_FAILED
    except IngestionError as exc:
        _fail("INGESTION_FAILURE", "%s: %s" % (type(exc).__name__, _redact(exc)))
        return EXIT_RUN_FAILED
    except (OSError, ValueError) as exc:
        _fail("OPERATION_FAILURE", "%s: %s" % (type(exc).__name__, _redact(exc)))
        return EXIT_CONFIGURATION_FAILURE


def _summarise(document: Mapping[str, Any]) -> Mapping[str, Any]:
    """A short view of a stored manifest."""
    return {
        "run_id": document.get("run_id"),
        "source_id": document.get("source_id"),
        "status": document.get("status"),
        "is_publishable": document.get("is_publishable"),
        "content_hash": document.get("content_hash"),
        "endpoint_count": document.get("endpoint_count"),
        "total_pages": document.get("total_pages"),
        "total_records": document.get("total_records"),
        "warnings": document.get("warnings", []),
        "failures": document.get("failures", []),
    }


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
