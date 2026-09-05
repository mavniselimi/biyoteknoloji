# -*- coding: utf-8 -*-
"""Shared helpers for the WP-01 legacy baseline (stdlib only, import-safe).

Used by ``scripts/build_legacy_baseline.py``, ``scripts/compare_legacy_v2.py``
and the regression tests. Importing this module has no side effects: it never
runs a legacy script, never touches the network, and never writes a file.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import posixpath
import subprocess
import sys
import tempfile

SCHEMA_VERSION = "wp01-legacy-baseline/1"
HASH_ALGORITHM = "sha256"

#: The only legacy bug IDs an allowlist entry or artifact may reference.
KNOWN_LEGACY_BUG_IDS = tuple("LEGACY-BUG-%03d" % n for n in range(1, 13))

#: Artifact classification vocabulary (closed set; verify-manifest enforces it).
ARTIFACT_TYPES = (
    "python_module",
    "csv_dataset",
    "json_dataset",
    "json_output",
    "csv_output",
    "markdown_doc",
    "markdown_report",
    "text_output",
    "python_test",
)

ARTIFACT_ROLES = (
    "legacy_module",
    "legacy_raw_output",
    "legacy_seed_dataset",
    "legacy_seed_backup",
    "legacy_derived_output",
    "legacy_report_artifact",
    "legacy_candidate_seed",
    "legacy_historical_doc",
    "wp00_governance_doc",
    "wp00_domain_code",
    "wp00_test",
    "architecture_contract",
)


# ---------------------------------------------------------------------------
# Path safety
# ---------------------------------------------------------------------------


class PathEscapeError(ValueError):
    """Raised when a manifest path would resolve outside the repository."""


def to_repo_relative(path, repo_root):
    """Return a normalised POSIX repo-relative path, or raise PathEscapeError."""
    repo_root = os.path.realpath(repo_root)
    absolute = os.path.realpath(os.path.join(repo_root, path))
    if absolute != repo_root and not absolute.startswith(repo_root + os.sep):
        raise PathEscapeError("path escapes repository root: %r" % (path,))
    rel = os.path.relpath(absolute, repo_root).replace(os.sep, "/")
    if rel == "." or rel.startswith("../"):
        raise PathEscapeError("path escapes repository root: %r" % (path,))
    return rel


def is_safe_manifest_path(path):
    """True when ``path`` is a plain relative POSIX path with no traversal."""
    if not isinstance(path, str) or not path:
        return False
    if path.startswith("/") or path.startswith("\\"):
        return False
    if ":" in path.split("/")[0] and len(path.split("/")[0]) == 2:
        return False  # drive letter
    if path != posixpath.normpath(path):
        return False
    parts = path.split("/")
    return ".." not in parts and "" not in parts


def resolve_within_repo(repo_root, rel_path):
    """Resolve ``rel_path`` under ``repo_root``, refusing symlink escapes."""
    if not is_safe_manifest_path(rel_path):
        raise PathEscapeError("unsafe manifest path: %r" % (rel_path,))
    repo_root = os.path.realpath(repo_root)
    target = os.path.join(repo_root, rel_path)
    real = os.path.realpath(target)
    if real != repo_root and not real.startswith(repo_root + os.sep):
        raise PathEscapeError("path resolves outside repository: %r" % (rel_path,))
    return target


# ---------------------------------------------------------------------------
# Hashing and counting
# ---------------------------------------------------------------------------


def sha256_file(path):
    """Return the SHA-256 hex digest of a file, streamed."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text):
    """Return the SHA-256 hex digest of a UTF-8 string."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def csv_row_count(path):
    """Return the number of data rows (excluding the header) in a CSV file."""
    with io.open(path, encoding="utf-8", newline="") as handle:
        return sum(1 for _ in csv.DictReader(handle))


def read_json(path):
    """Load a JSON document from ``path``."""
    with io.open(path, encoding="utf-8") as handle:
        return json.load(handle)


def dump_json(obj, path):
    """Write ``obj`` as deterministic UTF-8 JSON (sorted keys, LF, trailing NL)."""
    text = json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return text


def canonical_json_bytes(obj):
    """Return deterministic JSON bytes for hashing."""
    return (json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


# ---------------------------------------------------------------------------
# Subprocess helper (offline only)
# ---------------------------------------------------------------------------


class LegacyRunError(RuntimeError):
    """Raised with precise detail when a legacy rerun cannot proceed."""


def run_legacy(argv, cwd, timeout=600, env_remove=("GEMINI_API_KEY",)):
    """Run a legacy script offline and return (exit_code, stdout, stderr).

    ``env_remove`` names environment variables that are stripped before the
    child starts, so no API key can leak into a baseline run.
    """
    env = dict(os.environ)
    for name in env_remove:
        env.pop(name, None)
    env["PYTHONHASHSEED"] = "0"
    try:
        proc = subprocess.run(
            [sys.executable] + list(argv),
            cwd=cwd, env=env, timeout=timeout,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise LegacyRunError("interpreter or script not found: %s" % (exc,))
    except subprocess.TimeoutExpired:
        raise LegacyRunError("legacy run exceeded %ss: %s" % (timeout, " ".join(argv)))
    return (
        proc.returncode,
        proc.stdout.decode("utf-8", "replace"),
        proc.stderr.decode("utf-8", "replace"),
    )


def temp_workspace(prefix):
    """Return a TemporaryDirectory; never point a legacy run at the live seed."""
    return tempfile.TemporaryDirectory(prefix=prefix)


def require_files(repo_root, relative_paths, context):
    """Raise LegacyRunError naming every missing input, instead of failing late."""
    missing = [p for p in relative_paths
               if not os.path.exists(os.path.join(repo_root, p))]
    if missing:
        raise LegacyRunError(
            "%s: missing required input file(s): %s" % (context, ", ".join(sorted(missing)))
        )


def assert_not_live_seed(out_dir, repo_root):
    """Refuse to write a reproduction into the active legacy seed directory."""
    live = os.path.realpath(os.path.join(repo_root, "clinpgx_mvp_seed"))
    target = os.path.realpath(out_dir)
    if target == live or target.startswith(live + os.sep):
        raise LegacyRunError(
            "refusing to run a reproduction into the active seed directory: %s" % out_dir
        )


# ---------------------------------------------------------------------------
# Explicit field normalisation (WP-01 corrective pass)
# ---------------------------------------------------------------------------

class DuplicateIdentityError(ValueError):
    """Raised when a list contains two items with the same identity value."""


#: Identity keys used to address list items by *what they are* rather than by
#: position. Keyed by the JSON field name that holds the list. Only these
#: registered lists get identity-based selectors; every other list stays
#: index-addressed, which is correct for scalar arrays.
IDENTITY_KEY_REGISTRY = {
    "drug_results": "drug",
    "candidate_results": "candidate_drug",
    "medications": "display_name",
    "findings": "gene",
    "artifacts": "path",
    "evidence_artifacts": "path",
    "entries": "rule_id",
    "legacy_bugs": "bug_id",
    "reproduction_cases": "case_id",
}


def identity_key_for(field_name):
    """Return the registered identity key for a list field, or ``None``."""
    return IDENTITY_KEY_REGISTRY.get(field_name)


def identity_of(item, key):
    """Return the scalar identity of ``item``, or ``None`` when unusable."""
    if not isinstance(item, dict):
        return None
    value = item.get(key)
    if isinstance(value, (str, int, float)) and not isinstance(value, bool):
        return value
    return None


def identity_sequence(items, key):
    """Return the ordered identities of ``items``, or ``None`` if not all have one.

    Raises:
        DuplicateIdentityError: when two items share an identity. Silently
            picking the first match would let an expected-difference rule be
            applied to the wrong entity.
    """
    identities = []
    for item in items:
        value = identity_of(item, key)
        if value is None:
            return None
        identities.append(value)
    duplicates = sorted({v for v in identities if identities.count(v) > 1})
    if duplicates:
        raise DuplicateIdentityError(
            "duplicate identity value(s) %s under key %r; a comparison selector "
            "would be ambiguous" % (", ".join(repr(d) for d in duplicates), key))
    return identities


def set_json_path(document, json_path, value):
    """Set an exact ``$.a.b`` path to ``value``. Returns True when it existed.

    Only plain dotted object paths are supported on purpose: this is used for
    documented, field-exact normalisation, never for wildcard suppression.
    """
    if not json_path.startswith("$."):
        raise ValueError("json_path must start with '$.': %r" % (json_path,))
    parts = json_path[2:].split(".")
    if not parts or any(not p for p in parts):
        raise ValueError("malformed json_path: %r" % (json_path,))
    node = document
    for part in parts[:-1]:
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    if not isinstance(node, dict) or parts[-1] not in node:
        return False
    node[parts[-1]] = value
    return True


def normalize_json_fields(document, rules):
    """Return (normalised_copy, applied_paths) for exact field rules.

    ``rules`` is a sequence of dicts carrying ``json_path`` and
    ``normalized_to``. Nothing else in the document is touched: there is no
    wildcard, no subtree ignore, and no whole-file exclusion.
    """
    normalised = json.loads(json.dumps(document))
    applied = []
    for rule in rules:
        if set_json_path(normalised, rule["json_path"], rule["normalized_to"]):
            applied.append(rule["json_path"])
    return normalised, sorted(applied)


def normalized_json_sha256(document, rules):
    """SHA-256 of the canonical JSON after exact-field normalisation."""
    normalised, applied = normalize_json_fields(document, rules)
    return hashlib.sha256(canonical_json_bytes(normalised)).hexdigest(), applied, normalised
