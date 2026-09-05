#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Legacy-vs-V2 comparison harness and baseline manifest verifier (WP-01).

Stdlib only and import-safe: importing this module runs nothing, reads nothing,
and touches no network.

Two modes::

    python3 scripts/compare_legacy_v2.py verify-manifest \\
        --repo-root . --manifest data/legacy-baseline/manifest.json

    python3 scripts/compare_legacy_v2.py compare \\
        --legacy <file-or-dir> --candidate <file-or-dir> \\
        --allowlist data/legacy-baseline/expected-differences.json \\
        --output <comparison-result.json>

Exit codes::

    0  MATCH, or only explicitly allowlisted differences
    1  at least one UNEXPECTED_DIFFERENCE
    2  input / schema / manifest / configuration failure

Comparison rules (deliberate, and not negotiable by a caller flag):

* JSON object key ORDER is not a semantic difference; JSON array order IS.
* CSV headers and cells are compared; row order is significant.
* Text is compared line by line.
* No numeric/string coercion: ``1`` and ``"1"`` differ.
* Timestamp and path fields are only ignored through an explicit, exact
  selector carried by an allowlist entry with a known LEGACY-BUG id.

There is no wildcard, subtree, or "accept all text changes" rule. A difference
without a matching allowlist entry is UNEXPECTED, always.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from legacy_baseline_lib import (  # noqa: E402
    ARTIFACT_ROLES, ARTIFACT_TYPES, HASH_ALGORITHM, SCHEMA_VERSION,
    KNOWN_LEGACY_BUG_IDS, DuplicateIdentityError, PathEscapeError,
    canonical_json_bytes, identity_key_for, identity_of, identity_sequence,
    is_safe_manifest_path, resolve_within_repo, sha256_file,
)

RESULT_SCHEMA_VERSION = "wp01-comparison-result/1"
SUPPORTED_MANIFEST_SCHEMAS = (SCHEMA_VERSION,)

EXIT_OK = 0
EXIT_UNEXPECTED_DIFFERENCE = 1
EXIT_CONFIGURATION_FAILURE = 2

STATUS_MATCH = "MATCH"
STATUS_EXPECTED = "EXPECTED_DIFFERENCE"
STATUS_UNEXPECTED = "UNEXPECTED_DIFFERENCE"
STATUS_MISSING_INPUT = "MISSING_INPUT"
STATUS_INVALID_MANIFEST = "INVALID_MANIFEST"
STATUS_UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
STATUS_AMBIGUOUS_IDENTITY = "AMBIGUOUS_IDENTITY"

ALL_STATUSES = (STATUS_MATCH, STATUS_EXPECTED, STATUS_UNEXPECTED,
                STATUS_MISSING_INPUT, STATUS_INVALID_MANIFEST,
                STATUS_UNSUPPORTED_FORMAT, STATUS_AMBIGUOUS_IDENTITY)

JSON_EXT = (".json",)
CSV_EXT = (".csv",)
TEXT_EXT = (".md", ".txt")


class ConfigurationError(Exception):
    """Raised for manifest/allowlist/input problems that must exit with 2."""


# ---------------------------------------------------------------------------
# Allowlist
# ---------------------------------------------------------------------------

#: Selector shapes that would suppress far more than one observable difference.
_BROAD_SELECTOR_TOKENS = ("*", "**", "?", "[]", "..")
_BROAD_SELECTOR_EXACT = ("", "$", "$.", "$..", "/", ".", "all", "any")


#: Used when a single-file comparison is run without an explicit --artifact-id.
#: It can never equal a declared allowlist artifact_id, so an active rule can
#: never be applied to an unidentified file.
UNIDENTIFIED_ARTIFACT = "<UNIDENTIFIED-ARTIFACT>"


class ArtifactIdentityError(Exception):
    """Raised when an artifact identity is unsafe or ambiguous."""


def normalize_artifact_id(value, context="artifact_id"):
    """Return a validated, normalised relative POSIX artifact identity.

    Rejects absolute paths, ``..`` traversal, backslashes, wildcards, and any
    non-normalised form. There is no basename fallback anywhere in this module:
    an allowlist rule matches one exact identity or nothing.
    """
    if not isinstance(value, str) or not value.strip():
        raise ArtifactIdentityError("%s must be a non-empty string" % context)
    candidate = value.strip().replace("\\", "/")
    for token in ("*", "?", "[", "]"):
        if token in candidate:
            raise ArtifactIdentityError(
                "%s %r contains the wildcard token %r; artifact identity must be exact"
                % (context, value, token))
    if not is_safe_manifest_path(candidate):
        raise ArtifactIdentityError(
            "%s %r must be a normalised relative POSIX path without '..' or a "
            "leading '/'" % (context, value))
    return candidate


def artifact_id_for(root, full_path):
    """Deterministic relative POSIX identity of a file under a comparison root.

    Resolves symlinks on both sides so that a link escaping the comparison root
    is rejected rather than silently identified as an inside path.
    """
    real_root = os.path.realpath(root)
    real_path = os.path.realpath(full_path)
    if real_path != real_root and not real_path.startswith(real_root + os.sep):
        raise ArtifactIdentityError(
            "artifact %r resolves outside the comparison root %r" % (full_path, root))
    relative = os.path.relpath(real_path, real_root).replace(os.sep, "/")
    return normalize_artifact_id(relative, "derived artifact identity")


def _reject_broad(entry_id, field, value):
    """Raise ConfigurationError when a selector/artifact is too broad."""
    if value is None:
        return
    if not isinstance(value, str):
        raise ConfigurationError(
            "allowlist entry %s: %s must be a string, got %r"
            % (entry_id, field, type(value).__name__))
    stripped = value.strip()
    if stripped.lower() in _BROAD_SELECTOR_EXACT:
        raise ConfigurationError(
            "allowlist entry %s: %s %r is too broad; an exact selector is required"
            % (entry_id, field, value))
    for token in _BROAD_SELECTOR_TOKENS:
        if token in stripped:
            raise ConfigurationError(
                "allowlist entry %s: %s %r contains the broad token %r; "
                "wildcard and traversal selectors are rejected"
                % (entry_id, field, value, token))


class Allowlist(object):
    """Validated expected-difference rules loaded from JSON."""

    def __init__(self, path=None):
        self.path = path
        self.sha256 = None
        self.schema_version = None
        self.entries = []
        self._used = set()
        if path is not None:
            self._load(path)

    def _load(self, path):
        if not os.path.exists(path):
            raise ConfigurationError("allowlist file not found: %s" % path)
        self.sha256 = sha256_file(path)
        try:
            with io.open(path, encoding="utf-8") as handle:
                document = json.load(handle)
        except ValueError as exc:
            raise ConfigurationError("allowlist is not valid JSON: %s: %s" % (path, exc))
        if not isinstance(document, dict):
            raise ConfigurationError("allowlist root must be a JSON object: %s" % path)
        self.schema_version = document.get("schema_version")
        raw_entries = document.get("entries")
        if not isinstance(raw_entries, list):
            raise ConfigurationError("allowlist 'entries' must be a list: %s" % path)

        seen_ids = set()
        for index, raw in enumerate(raw_entries):
            if not isinstance(raw, dict):
                raise ConfigurationError("allowlist entry %d is not an object" % index)
            rule_id = raw.get("rule_id") or ("entry[%d]" % index)
            bug_id = raw.get("bug_id")
            if bug_id not in KNOWN_LEGACY_BUG_IDS:
                raise ConfigurationError(
                    "allowlist entry %s references unknown bug id %r; known ids: %s"
                    % (rule_id, bug_id, ", ".join(KNOWN_LEGACY_BUG_IDS)))
            if rule_id in seen_ids:
                raise ConfigurationError("duplicate allowlist rule_id: %s" % rule_id)
            seen_ids.add(rule_id)
            if raw.get("protected_as_correct") is True:
                raise ConfigurationError(
                    "allowlist entry %s sets protected_as_correct=true; a known legacy "
                    "defect may never be protected as correct behaviour" % rule_id)

            active = bool(raw.get("active"))
            selector = raw.get("comparison_selector")
            artifact_id = raw.get("artifact_id")
            if active:
                if not selector:
                    raise ConfigurationError(
                        "allowlist entry %s is active but has no comparison_selector"
                        % rule_id)
                _reject_broad(rule_id, "comparison_selector", selector)
                if not artifact_id:
                    raise ConfigurationError(
                        "allowlist entry %s is active but declares no artifact_id; an "
                        "expected difference must name exactly one artifact" % rule_id)
                try:
                    artifact_id = normalize_artifact_id(
                        artifact_id, "allowlist entry %s artifact_id" % rule_id)
                except ArtifactIdentityError as exc:
                    raise ConfigurationError(str(exc))
            elif artifact_id is not None:
                try:
                    artifact_id = normalize_artifact_id(
                        artifact_id, "allowlist entry %s artifact_id" % rule_id)
                except ArtifactIdentityError as exc:
                    raise ConfigurationError(str(exc))

            self.entries.append({
                "rule_id": rule_id, "bug_id": bug_id, "active": active,
                "comparison_selector": selector,
                "artifact_id": artifact_id,
                "observable_artifacts": list(raw.get("observable_artifacts") or []),
                "title": raw.get("title"),
                "disposition": raw.get("disposition"),
            })

        active_keys = {}
        for entry in self.entries:
            if not entry["active"]:
                continue
            key = (entry["artifact_id"], entry["comparison_selector"])
            if key in active_keys:
                raise ConfigurationError(
                    "allowlist entries %s and %s declare the same artifact_id and "
                    "comparison_selector; an expected difference must be unambiguous"
                    % (active_keys[key], entry["rule_id"]))
            active_keys[key] = entry["rule_id"]

    def match(self, artifact_id, selector):
        """Return the rule_id covering this difference, by EXACT identity only.

        There is no basename fallback and no suffix matching: a rule written for
        ``snapshots/risk.json`` can never be applied to an unrelated file that
        merely shares a basename.
        """
        if artifact_id is None or artifact_id == UNIDENTIFIED_ARTIFACT:
            return None
        for entry in self.entries:
            if not entry["active"]:
                continue
            if entry["artifact_id"] != artifact_id:
                continue
            if entry["comparison_selector"] != selector:
                continue
            self._used.add(entry["rule_id"])
            return entry["rule_id"]
        return None

    @property
    def applied_rule_ids(self):
        return sorted(self._used)

    @property
    def unused_entries(self):
        """Active entries that matched nothing in this run (never silent)."""
        return sorted(e["rule_id"] for e in self.entries
                      if e["active"] and e["rule_id"] not in self._used)

    @property
    def inactive_entries(self):
        """Registered-but-not-allowlisted entries; these suppress nothing."""
        return sorted(e["rule_id"] for e in self.entries if not e["active"])


# ---------------------------------------------------------------------------
# Difference detection
# ---------------------------------------------------------------------------

_MISSING = object()


def _kind(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _render(value):
    """Render a scalar for the report without coercing its type."""
    if value is _MISSING:
        return "<ABSENT>"
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, ensure_ascii=False)[:300]
    return json.dumps(value, ensure_ascii=False)


def _field_name(path):
    """Return the trailing object field name of a selector path."""
    tail = path.rsplit(".", 1)[-1]
    return tail.split("[", 1)[0]


def diff_json(legacy, candidate, selector="$"):
    """Yield (selector, legacy, candidate, reason) tuples.

    Rules:

    * Object key ORDER is not a semantic difference.
    * List items belonging to a registered identity list (see
      ``IDENTITY_KEY_REGISTRY``) are addressed by identity, e.g.
      ``$.drug_results[drug=codeine].overall_risk_level``. Reordering such a
      list therefore never moves a field difference onto a different entity.
    * List ORDER remains significant: when the identity sequence changes, an
      explicit ``[order]`` difference is emitted in addition to any field
      differences.
    * Lists without a usable identity stay index-addressed, which is correct
      for scalar arrays.
    * No numeric/string coercion is performed.

    Raises:
        DuplicateIdentityError: when an identity list contains repeated
            identities; the caller turns this into a comparison failure rather
            than silently selecting the first match.
    """
    differences = []

    def walk(left, right, path):
        if left is _MISSING or right is _MISSING:
            differences.append((path, left, right, "absent_on_one_side"))
            return
        if _kind(left) != _kind(right):
            differences.append((path, left, right, "type_mismatch"))
            return
        if isinstance(left, dict):
            for key in sorted(set(left) | set(right)):
                walk(left.get(key, _MISSING), right.get(key, _MISSING),
                     "%s.%s" % (path, key))
            return
        if isinstance(left, list):
            walk_list(left, right, path)
            return
        # bool is a subclass of int: keep True and 1 distinct.
        if isinstance(left, bool) != isinstance(right, bool) or left != right:
            differences.append((path, left, right, "value_mismatch"))

    def walk_list(left, right, path):
        key = identity_key_for(_field_name(path))
        left_ids = identity_sequence(left, key) if key else None
        right_ids = identity_sequence(right, key) if key else None

        if key is None or left_ids is None or right_ids is None:
            # Positional comparison (scalar arrays, or items lacking identity).
            if len(left) != len(right):
                differences.append((path + ".length", len(left), len(right),
                                    "array_length_mismatch"))
            for index in range(max(len(left), len(right))):
                walk(left[index] if index < len(left) else _MISSING,
                     right[index] if index < len(right) else _MISSING,
                     "%s[%d]" % (path, index))
            return

        # Identity-addressed comparison.
        if left_ids != right_ids:
            differences.append((
                "%s[order]" % path, left_ids, right_ids, "list_order_mismatch"))

        left_by_id = {identity_of(item, key): item for item in left}
        right_by_id = {identity_of(item, key): item for item in right}
        for identity in sorted(set(left_by_id) | set(right_by_id), key=lambda v: str(v)):
            item_path = "%s[%s=%s]" % (path, key, identity)
            if identity not in left_by_id:
                differences.append((item_path, _MISSING, right_by_id[identity],
                                    "list_item_added"))
                continue
            if identity not in right_by_id:
                differences.append((item_path, left_by_id[identity], _MISSING,
                                    "list_item_removed"))
                continue
            walk(left_by_id[identity], right_by_id[identity], item_path)

    walk(legacy, candidate, selector)
    return differences


def diff_csv(legacy_rows, candidate_rows, legacy_header, candidate_header):
    """Compare CSV header and cells; row order is significant."""
    differences = []
    if legacy_header != candidate_header:
        differences.append(("csv:header", legacy_header, candidate_header,
                            "header_mismatch"))
    if len(legacy_rows) != len(candidate_rows):
        differences.append(("csv:row_count", len(legacy_rows), len(candidate_rows),
                            "row_count_mismatch"))
    columns = legacy_header if legacy_header == candidate_header else None
    for index in range(min(len(legacy_rows), len(candidate_rows))):
        left, right = legacy_rows[index], candidate_rows[index]
        keys = columns if columns is not None else sorted(set(left) | set(right))
        for column in keys:
            left_cell = left.get(column, _MISSING)
            right_cell = right.get(column, _MISSING)
            if left_cell != right_cell:
                differences.append((
                    "csv:row[%d].column[%s]" % (index, column),
                    left_cell, right_cell, "cell_mismatch"))
    for index in range(min(len(legacy_rows), len(candidate_rows)),
                       max(len(legacy_rows), len(candidate_rows))):
        on_left = index < len(legacy_rows)
        differences.append((
            "csv:row[%d]" % index,
            legacy_rows[index] if on_left else _MISSING,
            candidate_rows[index] if not on_left else _MISSING,
            "row_absent_on_one_side"))
    return differences


def diff_text(legacy_lines, candidate_lines):
    """Compare text line by line; line numbers are 1-based in the report."""
    differences = []
    if len(legacy_lines) != len(candidate_lines):
        differences.append(("text:line_count", len(legacy_lines),
                            len(candidate_lines), "line_count_mismatch"))
    for index in range(max(len(legacy_lines), len(candidate_lines))):
        left = legacy_lines[index] if index < len(legacy_lines) else _MISSING
        right = candidate_lines[index] if index < len(candidate_lines) else _MISSING
        if left != right:
            differences.append(("text:line[%d]" % (index + 1), left, right,
                                "line_mismatch"))
    return differences


# ---------------------------------------------------------------------------
# File comparison
# ---------------------------------------------------------------------------


def detect_format(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in JSON_EXT:
        return "json"
    if ext in CSV_EXT:
        return "csv"
    if ext in TEXT_EXT:
        return "text"
    return None


def _read_csv(path):
    with io.open(path, encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = [dict(row) for row in reader]
        return rows, list(reader.fieldnames or [])


def compare_files(legacy_path, candidate_path, artifact_id, allowlist):
    """Compare one pair of files and return an artifact result dict."""
    result = {
        "artifact": artifact_id,
        "artifact_identity_declared": artifact_id != UNIDENTIFIED_ARTIFACT,
        "legacy_path": legacy_path,
        "candidate_path": candidate_path,
        "format": None,
        "status": None,
        "legacy_sha256": None,
        "candidate_sha256": None,
        "differences": [],
    }

    legacy_exists = os.path.isfile(legacy_path)
    candidate_exists = os.path.isfile(candidate_path)
    if not legacy_exists or not candidate_exists:
        result["status"] = STATUS_MISSING_INPUT
        result["detail"] = "missing on %s side" % (
            "legacy" if not legacy_exists else "candidate")
        return result

    result["legacy_sha256"] = sha256_file(legacy_path)
    result["candidate_sha256"] = sha256_file(candidate_path)

    fmt = detect_format(legacy_path)
    candidate_fmt = detect_format(candidate_path)
    if fmt is None or candidate_fmt is None or fmt != candidate_fmt:
        result["status"] = STATUS_UNSUPPORTED_FORMAT
        result["format"] = fmt or os.path.splitext(legacy_path)[1] or "unknown"
        result["detail"] = (
            "supported formats are JSON (.json), CSV (.csv) and UTF-8 text "
            "(.md, .txt); got legacy=%r candidate=%r"
            % (os.path.splitext(legacy_path)[1], os.path.splitext(candidate_path)[1]))
        return result
    result["format"] = fmt

    if result["legacy_sha256"] == result["candidate_sha256"]:
        result["status"] = STATUS_MATCH
        return result

    try:
        if fmt == "json":
            with io.open(legacy_path, encoding="utf-8") as handle:
                left = json.load(handle)
            with io.open(candidate_path, encoding="utf-8") as handle:
                right = json.load(handle)
            try:
                raw = diff_json(left, right)
            except DuplicateIdentityError as exc:
                result["status"] = STATUS_AMBIGUOUS_IDENTITY
                result["detail"] = (
                    "%s; refusing to guess which entity an expected-difference "
                    "rule applies to" % exc)
                return result
        elif fmt == "csv":
            left_rows, left_header = _read_csv(legacy_path)
            right_rows, right_header = _read_csv(candidate_path)
            raw = diff_csv(left_rows, right_rows, left_header, right_header)
        else:
            with io.open(legacy_path, encoding="utf-8") as handle:
                left_lines = handle.read().splitlines()
            with io.open(candidate_path, encoding="utf-8") as handle:
                right_lines = handle.read().splitlines()
            raw = diff_text(left_lines, right_lines)
    except ValueError as exc:
        result["status"] = STATUS_UNSUPPORTED_FORMAT
        result["detail"] = "could not parse as %s: %s" % (fmt, exc)
        return result

    expected = 0
    for selector, left, right, reason in raw:
        rule_id = allowlist.match(artifact_id, selector)
        entry = {
            "selector": selector,
            "reason": reason,
            "legacy_value": _render(left),
            "candidate_value": _render(right),
            "status": STATUS_EXPECTED if rule_id else STATUS_UNEXPECTED,
            "matched_rule_id": rule_id,
        }
        if rule_id:
            expected += 1
        result["differences"].append(entry)

    result["differences"].sort(key=lambda d: (d["selector"], d["reason"]))
    if not result["differences"]:
        # Byte difference with no semantic difference (e.g. JSON key order).
        result["status"] = STATUS_MATCH
        result["note"] = "byte difference only; no semantic difference detected"
    elif expected == len(result["differences"]):
        result["status"] = STATUS_EXPECTED
    else:
        result["status"] = STATUS_UNEXPECTED
    return result


# ---------------------------------------------------------------------------
# Manifest verification
# ---------------------------------------------------------------------------


def verify_manifest(repo_root, manifest_path):
    """Verify the baseline manifest. Returns (report, exit_code)."""
    problems = []
    checked = 0

    if not os.path.exists(manifest_path):
        raise ConfigurationError("manifest not found: %s" % manifest_path)
    try:
        with io.open(manifest_path, encoding="utf-8") as handle:
            manifest = json.load(handle)
    except ValueError as exc:
        raise ConfigurationError("manifest is not valid JSON: %s" % exc)

    schema = manifest.get("schema_version")
    if schema not in SUPPORTED_MANIFEST_SCHEMAS:
        problems.append({
            "code": "UNSUPPORTED_SCHEMA_VERSION", "path": None,
            "detail": "manifest schema_version %r is not in %r"
                      % (schema, list(SUPPORTED_MANIFEST_SCHEMAS))})

    if manifest.get("manifest_hash_algorithm") != HASH_ALGORITHM:
        problems.append({
            "code": "UNSUPPORTED_HASH_ALGORITHM", "path": None,
            "detail": "only %s is permitted, got %r"
                      % (HASH_ALGORITHM, manifest.get("manifest_hash_algorithm"))})

    known_bugs = set(KNOWN_LEGACY_BUG_IDS)
    for bug in manifest.get("legacy_bugs", []):
        if bug.get("bug_id") not in known_bugs:
            problems.append({"code": "UNKNOWN_LEGACY_BUG_ID", "path": None,
                             "detail": "manifest references %r" % bug.get("bug_id")})
        if bug.get("protected_as_correct") is not False:
            problems.append({
                "code": "BUG_PROTECTED_AS_CORRECT", "path": None,
                "detail": "%s must have protected_as_correct=false" % bug.get("bug_id")})

    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        problems.append({"code": "NO_ARTIFACTS", "path": None,
                         "detail": "manifest declares no artifacts"})
        artifacts = []

    manifest_rel = os.path.relpath(os.path.realpath(manifest_path),
                                   os.path.realpath(repo_root)).replace(os.sep, "/")
    seen_paths = []
    for artifact in artifacts:
        path = artifact.get("path")
        seen_paths.append(path)

        if path == manifest_rel:
            problems.append({"code": "MANIFEST_LISTS_ITSELF", "path": path,
                             "detail": "the manifest must not hash itself"})
            continue
        if not is_safe_manifest_path(path):
            problems.append({"code": "UNSAFE_PATH", "path": path,
                             "detail": "absolute, non-normalised, or traversing path"})
            continue
        try:
            full = resolve_within_repo(repo_root, path)
        except PathEscapeError as exc:
            problems.append({"code": "PATH_ESCAPES_REPOSITORY", "path": path,
                             "detail": str(exc)})
            continue

        if artifact.get("artifact_type") not in ARTIFACT_TYPES:
            problems.append({"code": "INVALID_ARTIFACT_TYPE", "path": path,
                             "detail": "%r not in the permitted set"
                                       % artifact.get("artifact_type")})
        if artifact.get("role") not in ARTIFACT_ROLES:
            problems.append({"code": "INVALID_ARTIFACT_ROLE", "path": path,
                             "detail": "%r not in the permitted set" % artifact.get("role")})
        for bug_id in artifact.get("known_issue_ids", []):
            if bug_id not in known_bugs:
                problems.append({"code": "UNKNOWN_LEGACY_BUG_ID", "path": path,
                                 "detail": "artifact references %r" % bug_id})

        digest = artifact.get("sha256")
        if not isinstance(digest, str) or len(digest) != 64 or \
                any(c not in "0123456789abcdef" for c in digest):
            problems.append({"code": "INVALID_SHA256_FORMAT", "path": path,
                             "detail": "expected 64 lowercase hex characters"})
            continue

        if not os.path.isfile(full):
            if artifact.get("required"):
                problems.append({"code": "REQUIRED_FILE_MISSING", "path": path,
                                 "detail": "declared required but not present"})
            continue

        actual_size = os.path.getsize(full)
        if actual_size != artifact.get("size_bytes"):
            problems.append({"code": "SIZE_MISMATCH", "path": path,
                             "detail": "manifest %r, actual %d"
                                       % (artifact.get("size_bytes"), actual_size)})
        actual_hash = sha256_file(full)
        if actual_hash != digest:
            problems.append({"code": "SHA256_MISMATCH", "path": path,
                             "detail": "manifest %s..., actual %s..."
                                       % (digest[:12], actual_hash[:12])})
        checked += 1

    # --- WP-01 evidence chain -------------------------------------------
    evidence = manifest.get("evidence_artifacts")
    evidence_checked = 0
    if evidence is None:
        problems.append({
            "code": "NO_EVIDENCE_ARTIFACTS", "path": None,
            "detail": ("manifest declares no evidence_artifacts; WP-01 snapshots, "
                       "allowlist and run log must be hash-bound")})
        evidence = []
    elif not isinstance(evidence, list) or not evidence:
        problems.append({"code": "NO_EVIDENCE_ARTIFACTS", "path": None,
                         "detail": "evidence_artifacts must be a non-empty list"})
        evidence = []

    evidence_paths = []
    for artifact in evidence:
        path = artifact.get("path")
        evidence_paths.append(path)
        if path == manifest_rel:
            problems.append({"code": "MANIFEST_LISTS_ITSELF", "path": path,
                             "detail": "the manifest must not hash itself"})
            continue
        if not is_safe_manifest_path(path):
            problems.append({"code": "UNSAFE_EVIDENCE_PATH", "path": path,
                             "detail": "absolute, non-normalised, or traversing path"})
            continue
        try:
            full = resolve_within_repo(repo_root, path)
        except PathEscapeError as exc:
            problems.append({"code": "EVIDENCE_PATH_ESCAPES_REPOSITORY", "path": path,
                             "detail": str(exc)})
            continue
        digest = artifact.get("sha256")
        if not isinstance(digest, str) or len(digest) != 64 or \
                any(c not in "0123456789abcdef" for c in digest):
            problems.append({"code": "INVALID_SHA256_FORMAT", "path": path,
                             "detail": "expected 64 lowercase hex characters"})
            continue
        if not os.path.isfile(full):
            problems.append({"code": "EVIDENCE_FILE_MISSING", "path": path,
                             "detail": "declared evidence artifact is not present"})
            continue
        if os.path.getsize(full) != artifact.get("size_bytes"):
            problems.append({"code": "EVIDENCE_SIZE_MISMATCH", "path": path,
                             "detail": "manifest %r, actual %d"
                                       % (artifact.get("size_bytes"), os.path.getsize(full))})
        actual = sha256_file(full)
        if actual != digest:
            problems.append({"code": "EVIDENCE_SHA256_MISMATCH", "path": path,
                             "detail": "manifest %s..., actual %s..."
                                       % (digest[:12], actual[:12])})
        evidence_checked += 1

    if evidence_paths and evidence_paths != sorted(p for p in evidence_paths if p):
        problems.append({"code": "NON_DETERMINISTIC_ORDER", "path": None,
                         "detail": "evidence_artifacts must be sorted by path"})

    required_evidence = ("data/legacy-baseline/expected-differences.json",
                         "data/legacy-baseline/reproduction-run-log.json")
    for required in required_evidence:
        if required not in set(evidence_paths):
            problems.append({"code": "REQUIRED_EVIDENCE_NOT_DECLARED", "path": required,
                             "detail": "must be part of the evidence hash chain"})
    if not any(p and p.startswith("data/legacy-baseline/snapshots/")
               for p in evidence_paths):
        problems.append({"code": "REQUIRED_EVIDENCE_NOT_DECLARED",
                         "path": "data/legacy-baseline/snapshots/",
                         "detail": "no baseline snapshot is hash-bound"})

    if seen_paths != sorted(p for p in seen_paths if p is not None) and \
            all(p is not None for p in seen_paths):
        problems.append({"code": "NON_DETERMINISTIC_ORDER", "path": None,
                         "detail": "artifacts must be sorted by path"})
    if len(seen_paths) != len(set(seen_paths)):
        problems.append({"code": "DUPLICATE_PATH", "path": None,
                         "detail": "the same path is listed more than once"})

    problems.sort(key=lambda p: (p["code"], p["path"] or ""))
    report = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "mode": "verify-manifest",
        "manifest_path": manifest_rel,
        "manifest_sha256": sha256_file(manifest_path),
        "manifest_schema_version": schema,
        "baseline_id": manifest.get("baseline_id"),
        "artifacts_declared": len(artifacts),
        "artifacts_hash_verified": checked,
        "evidence_declared": len(evidence),
        "evidence_hash_verified": evidence_checked,
        "problem_count": len(problems),
        "problems": problems,
        "outcome": STATUS_MATCH if not problems else STATUS_INVALID_MANIFEST,
    }
    return report, (EXIT_OK if not problems else EXIT_CONFIGURATION_FAILURE)


# ---------------------------------------------------------------------------
# Compare mode
# ---------------------------------------------------------------------------


def _pair_inputs(legacy, candidate, artifact_id=None):
    """Return an ordered list of (artifact_id, legacy_path, candidate_path).

    File mode requires an explicit ``--artifact-id`` before any active
    allowlist rule can apply; without one the artifact is identified as
    ``UNIDENTIFIED_ARTIFACT``, which no rule can match. Directory mode derives
    a deterministic relative POSIX identity from the comparison root and
    rejects anything that resolves outside it.
    """
    if os.path.isfile(legacy) and os.path.isfile(candidate):
        if artifact_id is None:
            identity = UNIDENTIFIED_ARTIFACT
        else:
            try:
                identity = normalize_artifact_id(artifact_id, "--artifact-id")
            except ArtifactIdentityError as exc:
                raise ConfigurationError(str(exc))
        return [(identity, legacy, candidate)]

    if os.path.isdir(legacy) and os.path.isdir(candidate):
        if artifact_id is not None:
            raise ConfigurationError(
                "--artifact-id applies to single-file comparison only; directory "
                "comparison derives each identity from the comparison root")
        names = set()
        for base in (legacy, candidate):
            for root, dirs, files in os.walk(base):
                dirs[:] = sorted(d for d in dirs if d != "__pycache__")
                for fn in files:
                    if fn.endswith((".pyc", ".pyo")) or fn == ".DS_Store":
                        continue
                    try:
                        names.add(artifact_id_for(base, os.path.join(root, fn)))
                    except ArtifactIdentityError as exc:
                        raise ConfigurationError(str(exc))
        return [(name, os.path.join(legacy, name), os.path.join(candidate, name))
                for name in sorted(names)]

    raise ConfigurationError(
        "legacy and candidate must both be files or both be directories "
        "(legacy=%s exists=%s, candidate=%s exists=%s)"
        % (legacy, os.path.exists(legacy), candidate, os.path.exists(candidate)))


def run_compare(legacy, candidate, allowlist_path, output_path=None,
                artifact_id=None):
    """Compare two artifacts or trees. Returns (report, exit_code)."""
    for label, path in (("legacy", legacy), ("candidate", candidate)):
        if not os.path.exists(path):
            raise ConfigurationError("%s input does not exist: %s" % (label, path))

    allowlist = Allowlist(allowlist_path)
    pairs = _pair_inputs(legacy, candidate, artifact_id)

    results = [compare_files(lp, cp, identity, allowlist)
               for identity, lp, cp in pairs]
    results.sort(key=lambda r: r["artifact"])

    counts = {status: 0 for status in ALL_STATUSES}
    for result in results:
        counts[result["status"]] += 1

    if counts[STATUS_AMBIGUOUS_IDENTITY]:
        outcome, exit_code = STATUS_AMBIGUOUS_IDENTITY, EXIT_CONFIGURATION_FAILURE
    elif counts[STATUS_UNSUPPORTED_FORMAT] or counts[STATUS_MISSING_INPUT]:
        outcome, exit_code = (
            STATUS_UNSUPPORTED_FORMAT if counts[STATUS_UNSUPPORTED_FORMAT]
            else STATUS_MISSING_INPUT), EXIT_CONFIGURATION_FAILURE
    elif counts[STATUS_UNEXPECTED]:
        outcome, exit_code = STATUS_UNEXPECTED, EXIT_UNEXPECTED_DIFFERENCE
    elif counts[STATUS_EXPECTED]:
        outcome, exit_code = STATUS_EXPECTED, EXIT_OK
    else:
        outcome, exit_code = STATUS_MATCH, EXIT_OK

    report = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "mode": "compare",
        "legacy_input": {
            "path": legacy,
            "kind": "directory" if os.path.isdir(legacy) else "file",
            "sha256": sha256_file(legacy) if os.path.isfile(legacy) else None,
        },
        "candidate_input": {
            "path": candidate,
            "kind": "directory" if os.path.isdir(candidate) else "file",
            "sha256": sha256_file(candidate) if os.path.isfile(candidate) else None,
        },
        "allowlist": {
            "path": allowlist.path,
            "sha256": allowlist.sha256,
            "schema_version": allowlist.schema_version,
            "entry_count": len(allowlist.entries),
        },
        "counts_by_status": {k: counts[k] for k in ALL_STATUSES},
        "difference_count": sum(len(r["differences"]) for r in results),
        "artifacts": results,
        "artifact_identity": {
            "mode": "file" if os.path.isfile(legacy) else "directory",
            "declared_artifact_id": artifact_id,
            "unidentified_artifacts": sorted(
                r["artifact"] for r in results
                if r["artifact"] == UNIDENTIFIED_ARTIFACT),
            "note": (
                "Allowlist rules match one exact artifact identity. A single-file "
                "comparison without --artifact-id is reported as "
                "%s and can never match an active rule." % UNIDENTIFIED_ARTIFACT),
        },
        "applied_rule_ids": allowlist.applied_rule_ids,
        "unused_allowlist_entries": allowlist.unused_entries,
        "inactive_allowlist_entries": allowlist.inactive_entries,
        "outcome": outcome,
    }
    if output_path:
        with io.open(output_path, "wb") as handle:
            handle.write(canonical_json_bytes(report))
    return report, exit_code


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser():
    parser = argparse.ArgumentParser(
        prog="compare_legacy_v2.py",
        description="WP-01 legacy baseline verifier and legacy-vs-V2 comparison harness.")
    sub = parser.add_subparsers(dest="command")

    verify = sub.add_parser("verify-manifest", help="verify the baseline manifest")
    verify.add_argument("--repo-root", default=".")
    verify.add_argument("--manifest", default="data/legacy-baseline/manifest.json")
    verify.add_argument("--output", default=None)

    compare = sub.add_parser("compare", help="compare a legacy artifact against a candidate")
    compare.add_argument("--legacy", required=True)
    compare.add_argument("--candidate", required=True)
    compare.add_argument("--allowlist", default="data/legacy-baseline/expected-differences.json")
    compare.add_argument(
        "--artifact-id", default=None,
        help=("Exact artifact identity for a single-file comparison. Required "
              "before any active expected-difference rule can apply. Not valid "
              "for directory comparison, where identity is derived from the "
              "comparison root."))
    compare.add_argument("--output", default=None)
    compare.add_argument("--quiet", action="store_true")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return EXIT_CONFIGURATION_FAILURE
    try:
        if args.command == "verify-manifest":
            report, code = verify_manifest(args.repo_root, args.manifest)
            if args.output:
                with io.open(args.output, "wb") as handle:
                    handle.write(canonical_json_bytes(report))
            sys.stdout.write(
                "verify-manifest: %s (%d legacy artifacts declared / %d verified; "
                "%d evidence artifacts declared / %d verified; %d problem(s))\n"
                % (report["outcome"], report["artifacts_declared"],
                   report["artifacts_hash_verified"], report["evidence_declared"],
                   report["evidence_hash_verified"], report["problem_count"]))
            for problem in report["problems"][:20]:
                sys.stdout.write("  %-26s %s  %s\n" % (
                    problem["code"], problem["path"] or "-", problem["detail"]))
            return code

        report, code = run_compare(args.legacy, args.candidate, args.allowlist,
                                   args.output, args.artifact_id)
        if not args.quiet:
            sys.stdout.write("compare: %s\n" % report["outcome"])
            for status in ALL_STATUSES:
                sys.stdout.write("  %-24s %d\n" % (status, report["counts_by_status"][status]))
            if report["artifact_identity"]["unidentified_artifacts"]:
                sys.stdout.write(
                    "  note: single-file comparison without --artifact-id; no "
                    "active allowlist rule can apply\n")
            if report["unused_allowlist_entries"]:
                sys.stdout.write("  unused allowlist entries: %s\n"
                                 % ", ".join(report["unused_allowlist_entries"]))
        return code
    except ConfigurationError as exc:
        sys.stderr.write("CONFIGURATION_FAILURE: %s\n" % exc)
        return EXIT_CONFIGURATION_FAILURE
    except PathEscapeError as exc:
        sys.stderr.write("CONFIGURATION_FAILURE: %s\n" % exc)
        return EXIT_CONFIGURATION_FAILURE


if __name__ == "__main__":
    sys.exit(main())
