# -*- coding: utf-8 -*-
"""Regenerating one artifact set in a fresh interpreter, and hashing it.

Run as ``python -m pgx.verification._artifact_worker <root> <generator>
<report.json>``. A separate process per regeneration, with a different
``PYTHONHASHSEED`` each time, is what makes the comparison worth doing: the
classic determinism bug is a document whose key order follows a set's iteration
order, and that reproduces perfectly inside one interpreter and differs between
two.

Only digests travel back. The documents themselves can be megabytes, and the
question being asked - "are these two the same" - is answered by a hash.
"""

from __future__ import annotations

import hashlib
import io
import json
import sys
from typing import Dict, List, Optional


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def regenerate(root: str, generator: str) -> Dict[str, Dict[str, object]]:
    """Import ``generator`` and call its ``build_artifacts``.

    ``generator`` is a module path. The convention across this repository is a
    module-level ``build_artifacts`` returning ``{relative path: rendered
    text}``, taking either no argument or a repository root; both shapes are
    accepted so a generator does not have to change to be verifiable.
    """
    import importlib
    module = importlib.import_module(generator)
    build = getattr(module, "build_artifacts")
    try:
        documents = build(root)
    except TypeError:
        documents = build()
    return {relative: {"sha256": _digest(text), "bytes": len(text.encode("utf-8"))}
            for relative, text in sorted(documents.items())}


def main(argv: Optional[List[str]] = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 3:
        sys.stderr.write("usage: python -m pgx.verification._artifact_worker "
                         "<root> <generator module> <report.json>\n")
        return 70
    root, generator, report_path = arguments
    report = {"artifacts": regenerate(root, generator),
              "generator": generator,
              "hash_seed": __import__("os").environ.get("PYTHONHASHSEED", ""),
              "worker_schema_version": "pgx-wp19-artifact-worker/1"}
    with io.open(report_path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(report, indent=2, sort_keys=True,
                                ensure_ascii=True) + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - a subprocess entry point
    sys.exit(main())
