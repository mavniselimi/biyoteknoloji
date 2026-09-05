# -*- coding: utf-8 -*-
"""``pgx-validation`` - build, audit and publish the WP-18 artifacts.

Four subcommands, and none of them can create a validation result:

``artifacts``
    Regenerate every committed WP-18 document. Deterministic: the same tree
    produces the same bytes, so a diff is a diff of content.

``audit``
    Run the separation rules over the committed case set and print the
    result. Reads metadata only, never a payload, so anyone may run it -
    including a rule author, which is the point.

``gate-status``
    Print what this repository can honestly say about validation.

``import-restricted``
    The WP-22 entry point, wired to a storage root a deployment supplies.
    Refuses with controlled issue codes and writes nothing on failure. There
    is no restricted storage in this repository, so it refuses here.

There is deliberately no ``approve``, no ``promote`` and no ``mark-validated``.
A case does not become evidence because a command said so.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
from typing import Any, Dict, List, Mapping, Optional, Tuple

from pgx.application.validation_schema import (build_schemas,
                                               validate_case_manifest,
                                               validate_separation_audit,
                                               validate_validation_case,
                                               validate_wp18_gate_status)
from pgx.validation.catalog import development_cases
from pgx.validation.gate_status import build_wp18_gate_status
from pgx.validation.manifests import (build_case_manifest,
                                      build_holdout_manifest)
from pgx.validation.separation import audit_partition

__all__ = ["ARTIFACT_PATHS", "build_artifacts", "main", "write_artifacts"]

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

#: Every path this module owns, relative to the repository root.
ARTIFACT_PATHS: Tuple[str, ...] = (
    "schemas/validation-case.schema.json",
    "schemas/validation-case-manifest.schema.json",
    "schemas/validation-access-event.schema.json",
    "schemas/validation-separation-audit.schema.json",
    "schemas/wp18-gate-status.schema.json",
    "data/validation/wp18-development-case-manifest.json",
    "data/validation/wp18-holdout-case-manifest.json",
    "data/validation/wp18-separation-audit.json",
    "data/validation/wp18-real-gate-status.json",
)

_DEVELOPMENT_NOTE = (
    "The seven WP-17 catalogue cases, seen as validation cases. Every one is "
    "DEVELOPMENT: they demonstrated the same rules they would be measured "
    "against, so using them as validation evidence would report memory as "
    "generalisation (SAFETY-INV-009). None carries an expected result and "
    "none may enter a holdout denominator. This manifest is a view over "
    "data/demo/wp17-development-cases.json, which remains the source; the "
    "cases are not copied.")


def _json(document: Mapping[str, Any]) -> str:
    """Canonical bytes: sorted keys, two-space indent, ASCII, one newline."""
    return json.dumps(document, indent=2, sort_keys=True,
                      ensure_ascii=True) + "\n"


def build_artifacts(root: str = _REPO_ROOT) -> Dict[str, str]:
    """Every artifact, as rendered text, keyed by repository-relative path.

    Each document is validated against its own published schema before it is
    returned. A generator that emitted a document its own schema rejects would
    be publishing a constraint it does not keep.
    """
    schemas = build_schemas()
    rendered: Dict[str, str] = {path: _json(schema)
                                for path, schema in schemas.items()}

    cases = development_cases(root)
    audit = audit_partition(cases)

    development = build_case_manifest(cases, partition="DEVELOPMENT",
                                      note=_DEVELOPMENT_NOTE)
    holdout = build_holdout_manifest()
    gate = build_wp18_gate_status(root)

    checks = (
        (development, validate_case_manifest,
         "schemas/validation-case-manifest.schema.json"),
        (holdout, validate_case_manifest,
         "schemas/validation-case-manifest.schema.json"),
        (audit.to_json(), validate_separation_audit,
         "schemas/validation-separation-audit.schema.json"),
        (gate, validate_wp18_gate_status,
         "schemas/wp18-gate-status.schema.json"),
    )
    for document, validator, schema_path in checks:
        problems = validator(document, schemas[schema_path])
        if problems:
            raise ValueError("%s does not satisfy its own schema: %s"
                             % (schema_path, "; ".join(problems[:5])))
    for case in cases:
        problems = validate_validation_case(
            case.to_json(), schemas["schemas/validation-case.schema.json"])
        if problems:
            raise ValueError("case %s does not satisfy its schema: %s"
                             % (case.case_id.value, "; ".join(problems[:5])))

    rendered["data/validation/wp18-development-case-manifest.json"] = _json(
        development)
    rendered["data/validation/wp18-holdout-case-manifest.json"] = _json(
        holdout)
    rendered["data/validation/wp18-separation-audit.json"] = _json(
        audit.to_json())
    rendered["data/validation/wp18-real-gate-status.json"] = _json(gate)
    return rendered


def write_artifacts(root: str = _REPO_ROOT) -> Dict[str, str]:
    """Write every artifact under ``root``. Returns what was written."""
    rendered = build_artifacts(root)
    for relative, body in sorted(rendered.items()):
        path = os.path.join(root, *relative.split("/"))
        directory = os.path.dirname(path)
        if not os.path.isdir(directory):
            os.makedirs(directory)
        with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(body)
    return rendered


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pgx-validation", allow_abbrev=False,
        description="WP-18 validation dataset architecture. Builds and audits "
                    "the partition; computes no metric and approves nothing.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("artifacts", allow_abbrev=False,
                   help="regenerate every committed WP-18 artifact")
    sub.add_parser("audit", allow_abbrev=False,
                   help="run the separation rules over the committed cases")
    sub.add_parser("gate-status", allow_abbrev=False,
                   help="print what this repository can say about validation")

    args = parser.parse_args(argv)

    if args.command == "artifacts":
        for relative, body in sorted(write_artifacts().items()):
            print("%8d  %s" % (len(body.encode("utf-8")), relative))
        return 0

    if args.command == "audit":
        audit = audit_partition(development_cases())
        print(_json(audit.to_json()), end="")
        return 0 if audit.is_clean else 1

    status = build_wp18_gate_status()
    print(_json(status), end="")
    return 0


if __name__ == "__main__":  # pragma: no cover - a developer entry point
    raise SystemExit(main())
