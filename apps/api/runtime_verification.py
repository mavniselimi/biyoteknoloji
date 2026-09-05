# -*- coding: utf-8 -*-
"""Proof that the ASGI runtime and the OpenAPI comparison actually ran.

The problem this exists to solve is narrow and worth stating plainly. WP-16's
gate status used to hard-code ``asgi_runtime_tests_executed: False`` and an
OpenAPI ``runtime_verification: BLOCKED``, with a note saying FastAPI could not
be installed. That was true where WP-16 was built and false the moment anybody
installed the framework and ran the suite - and the artifact went on saying it,
because a constant does not learn.

The obvious repair is the wrong one. Reporting ``asgi_runtime_tests_executed``
from *dependency availability* would replace a stale falsehood with a live one:
an importable FastAPI is not a test that ran. Between "the packages are here"
and "the checks passed" sits every reason a check fails, and a gate status that
cannot tell those apart is not measuring anything.

So execution is recorded, not inferred. Running

    python -m apps.api.runtime_verification

performs the real checks - composes the application, serves ``/openapi.json``
from it and compares that document with the committed artifact, answers a
health probe, and runs ``tests/integration/api/test_asgi_runtime.py`` - and
writes what happened to ``data/api/wp16-runtime-verification.json``. The gate
status reads that file. No file, no claim.

**Fail-closed, four ways.**

- *Absent.* No evidence file means ``BLOCKED``. That is the default state of a
  fresh checkout and it needs no configuration to be correct.
- *Failed.* A run where any check fails writes an evidence record with
  ``verified: false``, overwriting any earlier success. A failed verification
  cannot leave a VERIFIED artifact behind, and the record says which check
  failed rather than disappearing.
- *Incomplete.* The record is assembled in memory and written once, at the end,
  after every check has returned. A crashed or interrupted run writes nothing,
  so a partial run cannot be mistaken for a passing one.
- *Stale.* The record carries fingerprints of the inputs that determine runtime
  behaviour. If any of them changes, the evidence is rejected and the status
  returns to ``BLOCKED`` with the reason named. Evidence that outlived its
  subject is worse than no evidence, because it looks like the real thing.
- *Somebody else's.* The record also fingerprints the host it ran on - OS,
  architecture, interpreter version, package versions. A record produced on
  another machine is rejected on this one. Without that, a verification run on
  a build container would arrive in a checkout and go on attesting there: the
  fingerprints of the *inputs* would still match, because the source is the
  same, and the file would say VERIFIED about a run that never happened here.
  A committed attestation must not travel.

**What the record may contain.** Check names, pass/fail, counts, package
versions, an interpreter version, an OS and architecture, hashes, and a UTC
timestamp. What it may never contain: an absolute path, a hostname, a
credential, patient data, or any synthetic clinical payload - not a gene
identifier, not a drug identifier, not a case id. :func:`_reject_sensitive`
scans the rendered record before it is written and refuses rather than
truncating, because a redaction nobody notices is how the second one gets
through.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import io
import json
import os
import platform
import re
import sys
from typing import Any, Dict, List, Mapping, Optional, Tuple

from apps.api.openapi import canonical_json

# ``apps.api.gate_status`` imports this module at module scope, so this module
# must not import it back at module scope. The one constant it needs - where
# the committed OpenAPI artifact lives - is fetched inside the two functions
# that use it. One direction, no cycle, still one spelling of the path.

__all__ = [
    "EVIDENCE_PATH",
    "EVIDENCE_SCHEMA_VERSION",
    "NO_EVIDENCE",
    "STALE",
    "VERIFICATION_FAILED",
    "VERIFIED",
    "build_evidence",
    "evidence_freshness",
    "host_fingerprint",
    "input_fingerprints",
    "load_evidence",
    "main",
    "run_verification",
    "verified_runtime_status",
    "write_evidence",
]

EVIDENCE_SCHEMA_VERSION = "pgx-wp16-runtime-verification/1"

#: Committed beside the gate status it feeds, under ``data/api/``.
EVIDENCE_PATH = "data/api/wp16-runtime-verification.json"

#: The four states, as words. A boolean would collapse "nobody has looked",
#: "somebody looked and it failed" and "somebody looked at something else"
#: into one value, and those are the three different things a reader needs.
VERIFIED = "VERIFIED"
NO_EVIDENCE = "BLOCKED"
VERIFICATION_FAILED = "VERIFICATION_FAILED"
STALE = "STALE_EVIDENCE_REJECTED"

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..",
                                          ".."))

#: Every check a full verification must complete. Named here so a run that
#: skipped one cannot pass: :func:`build_evidence` compares this set with what
#: was actually reported and refuses to mark a partial run verified.
REQUIRED_CHECKS: Tuple[str, ...] = (
    "framework_imports",
    "application_composes",
    "openapi_served_matches_committed",
    "health_live_answers",
    "asgi_runtime_suite",
)

#: The packages whose versions are recorded. Their versions are part of what
#: the evidence attests: "these checks passed" is a claim about a stack.
_RECORDED_PACKAGES: Tuple[str, ...] = ("fastapi", "starlette", "pydantic",
                                       "uvicorn", "httpx")


# ---------------------------------------------------------------------------
# Fingerprints: what makes evidence stale
# ---------------------------------------------------------------------------

def _sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _api_source_files(root: str) -> List[str]:
    """Every module whose behaviour a runtime check could observe.

    ``apps/api`` only. The declarative contract is covered by the document
    fingerprint below; this one catches the changes that do *not* alter the
    document - a new middleware, a changed exception handler, a different
    dependency wiring - which are exactly the changes a runtime check exists
    to notice.
    """
    base = os.path.join(root, "apps", "api")
    found: List[str] = []
    for directory, dirs, files in os.walk(base):
        dirs[:] = sorted(name for name in dirs if name != "__pycache__")
        for name in sorted(files):
            if name.endswith(".py"):
                found.append(os.path.join(directory, name))
    return found


def input_fingerprints(root: str = _REPO_ROOT) -> Dict[str, Any]:
    """Hashes of the inputs that determine what a runtime check would see.

    Three, because they go stale for three different reasons:

    ``api_source_sha256``
        The API package's source. A middleware that changes what a request
        gets back invalidates evidence even though no route was declared.

    ``openapi_document_sha256``
        The generator's output, with the runtime-verification block removed.
        That block is *about* the document rather than part of the surface, so
        including it would mean recording a successful verification
        invalidated the evidence for that verification.

    ``committed_openapi_sha256``
        The artifact on disk, stripped the same way. A committed document
        edited by hand, or left stale, invalidates the comparison that was
        performed against it.
    """
    from apps.api.gate_status import OPENAPI_RELATIVE_PATH
    from apps.api.openapi import build_document

    digest = hashlib.sha256()
    for path in _api_source_files(root):
        relative = os.path.relpath(path, root).replace(os.sep, "/")
        with io.open(path, "rb") as handle:
            body = handle.read()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(body).hexdigest().encode("ascii"))
        digest.update(b"\n")

    committed_hash: Optional[str] = None
    artifact = os.path.join(root, *OPENAPI_RELATIVE_PATH.split("/"))
    if os.path.isfile(artifact):
        try:
            with io.open(artifact, encoding="utf-8") as handle:
                committed_hash = _sha256_text(
                    canonical_json(_surface_only(json.load(handle))))
        except (OSError, ValueError):  # pragma: no cover - defensive
            committed_hash = None

    return {
        "api_source_sha256": "sha256:" + digest.hexdigest(),
        "api_source_file_count": len(_api_source_files(root)),
        "openapi_document_sha256": _sha256_text(
            canonical_json(_surface_only(build_document()))),
        "committed_openapi_sha256": committed_hash,
    }


def _surface_only(document: Mapping[str, Any]) -> Dict[str, Any]:
    """The document without the block that says how it was verified."""
    copy = dict(document)
    copy.pop("x-pgx-runtime-verification", None)
    return copy


# ---------------------------------------------------------------------------
# The evidence record
# ---------------------------------------------------------------------------

def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(
        microsecond=0).isoformat().replace("+00:00", "Z")


def host_fingerprint() -> Dict[str, Any]:
    """What "this host" means for the purpose of accepting evidence.

    OS, architecture, interpreter and the versions of the packages the checks
    exercised. Deliberately *not* a hostname, a MAC address, a username or a
    path: the question is "is this the same kind of machine running the same
    stack", not "which machine is this", and an identifier that answered the
    second would be a fact about a person in a committed file.
    """
    return {
        "python": "%d.%d.%d" % sys.version_info[:3],
        "implementation": platform.python_implementation(),
        "system": platform.system(),
        "machine": platform.machine(),
        "packages": _package_versions(),
    }


def _package_versions() -> Dict[str, Optional[str]]:
    import importlib

    versions: Dict[str, Optional[str]] = {}
    for name in _RECORDED_PACKAGES:
        try:
            module = importlib.import_module(name)
        except Exception:  # noqa: BLE001 - absence is a recordable fact
            versions[name] = None
        else:
            versions[name] = getattr(module, "__version__", None)
    return versions


#: Patterns refused outright in a rendered evidence record. Deliberately blunt:
#: this file is small, structured and written by one function, so a false
#: positive is a five-second fix and a false negative is a leak.
_FORBIDDEN = (
    (re.compile(r"(?<![\w])/(?:Users|home|root|var|opt|tmp|private)/"),
     "an absolute filesystem path"),
    (re.compile(r"[A-Za-z]:\\"), "a Windows absolute path"),
    (re.compile(r"\bGENE:|\bDRUG:"), "a clinical entity identifier"),
    (re.compile(r"(?i)\b(password|passwd|secret|api[_-]?key|bearer|"
                r"authorization)\b"), "a credential-shaped field"),
    (re.compile(r"(?i)\bTEST-(?:TOKEN|CASE|SOURCE|SYNTHETIC)"),
     "a synthetic fixture identifier"),
    (re.compile(r"(?i)\b(genotype|diplotype|allele|phenotype|patient|mrn|"
                r"diagnosis|dose)\b"), "a clinical field name"),
)


def _reject_sensitive(rendered: str) -> None:
    """Refuse to write a record carrying anything it must not carry.

    Refuses rather than redacts. A record that quietly dropped a field would
    be a record nobody could reason about, and the next thing added to it
    would be dropped just as quietly.
    """
    for pattern, description in _FORBIDDEN:
        match = pattern.search(rendered)
        if match:
            raise ValueError(
                "refusing to write runtime-verification evidence: it contains "
                "%s (%r). Evidence records carry check names, counts, "
                "versions and hashes - nothing else."
                % (description, match.group(0)))


def build_evidence(checks: List[Dict[str, Any]], *,
                   root: str = _REPO_ROOT) -> Dict[str, Any]:
    """Assemble the record. Verified only if every required check passed."""
    reported = {check["name"] for check in checks}
    missing = [name for name in REQUIRED_CHECKS if name not in reported]
    passed = all(check["passed"] for check in checks) and not missing

    return {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "work_package": "WP-16",
        "verified": bool(passed),
        "verified_at": _now(),
        "required_checks": list(REQUIRED_CHECKS),
        "checks_not_run": missing,
        "checks": sorted(checks, key=lambda item: item["name"]),
        "environment": host_fingerprint(),
        "inputs": input_fingerprints(root),
        "note": (
            "Written by `python -m apps.api.runtime_verification`. It records "
            "what executed, not what is installed: an importable framework is "
            "not a test that ran. The gate status reads this file and reports "
            "BLOCKED when it is absent, when it says verified false, or when "
            "the input fingerprints no longer match the repository."),
    }


def write_evidence(evidence: Mapping[str, Any],
                   root: str = _REPO_ROOT) -> str:
    """Render, screen and write. One write, at the end, or none at all."""
    rendered = json.dumps(evidence, indent=2, sort_keys=True,
                          ensure_ascii=True) + "\n"
    _reject_sensitive(rendered)
    path = os.path.join(root, *EVIDENCE_PATH.split("/"))
    directory = os.path.dirname(path)
    if not os.path.isdir(directory):
        os.makedirs(directory)
    with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(rendered)
    return path


def load_evidence(root: str = _REPO_ROOT) -> Optional[Dict[str, Any]]:
    """The committed record, or ``None`` when there is none to read."""
    path = os.path.join(root, *EVIDENCE_PATH.split("/"))
    if not os.path.isfile(path):
        return None
    try:
        with io.open(path, encoding="utf-8") as handle:
            document = json.load(handle)
    except (OSError, ValueError):
        return None
    return document if isinstance(document, dict) else None


def evidence_freshness(evidence: Optional[Mapping[str, Any]],
                       root: str = _REPO_ROOT) -> Tuple[str, str]:
    """Classify a record: ``(status, reason)``. Never raises.

    The order of the checks is the order of the questions a reader would ask:
    is there a record, is it a record of this kind, did it pass, and is it
    still about this repository.
    """
    if evidence is None:
        return NO_EVIDENCE, ("no runtime-verification evidence has been "
                             "written; run `python -m "
                             "apps.api.runtime_verification`")
    if evidence.get("schema_version") != EVIDENCE_SCHEMA_VERSION:
        return STALE, ("evidence was written against schema %r, not %r"
                       % (evidence.get("schema_version"),
                          EVIDENCE_SCHEMA_VERSION))
    if not evidence.get("verified"):
        failed = [check.get("name") for check in evidence.get("checks", ())
                  if not check.get("passed")]
        missing = list(evidence.get("checks_not_run") or ())
        detail = ", ".join(sorted(set(failed + missing))) or "unspecified"
        return VERIFICATION_FAILED, ("the last verification run did not pass: "
                                     "%s" % detail)

    recorded_host = evidence.get("environment") or {}
    current_host = host_fingerprint()
    if recorded_host != current_host:
        return STALE, (
            "the evidence was produced on a different host or stack "
            "(%s/%s %s) than this one (%s/%s %s); an attestation does not "
            "travel between machines"
            % (recorded_host.get("system"), recorded_host.get("implementation"),
               recorded_host.get("python"), current_host["system"],
               current_host["implementation"], current_host["python"]))

    recorded = evidence.get("inputs") or {}
    current = input_fingerprints(root)
    for key in ("api_source_sha256", "openapi_document_sha256",
                "committed_openapi_sha256"):
        if recorded.get(key) != current.get(key):
            return STALE, ("%s changed since verification; the evidence "
                           "describes a different repository state" % key)
    return VERIFIED, "verified and current"


def verified_runtime_status(root: str = _REPO_ROOT) -> Dict[str, Any]:
    """What the gate status publishes about runtime execution.

    The single consumer-facing function. It never infers execution from
    installed packages, and it returns the fail-closed answer for every state
    that is not "a passing run whose inputs still match".
    """
    evidence = load_evidence(root)
    status, reason = evidence_freshness(evidence, root)
    verified = status == VERIFIED

    summary: Optional[Dict[str, Any]] = None
    if evidence is not None:
        summary = {
            "schema_version": evidence.get("schema_version"),
            "verified": bool(evidence.get("verified")),
            "verified_at": evidence.get("verified_at"),
            "environment": evidence.get("environment"),
            "checks": [{"name": check.get("name"),
                        "passed": bool(check.get("passed"))}
                       for check in evidence.get("checks", ())],
        }

    return {
        "asgi_runtime_tests_executed": verified,
        "asgi_runtime_test_status": status,
        "asgi_runtime_test_note": (
            "tests/integration/api/test_asgi_runtime.py was executed by "
            "`python -m apps.api.runtime_verification` and every check "
            "passed. This flag reports that recorded execution, not the "
            "presence of the packages."
            if verified else
            "no execution is recorded: %s. Installed dependencies are "
            "reported separately and are not evidence that a test ran."
            % reason),
        "openapi_runtime_verified": verified,
        "runtime_verification_evidence_path": EVIDENCE_PATH,
        "runtime_verification_evidence": summary,
        "runtime_verification_reason": reason,
    }


# ---------------------------------------------------------------------------
# The checks
# ---------------------------------------------------------------------------

def _check(name: str, passed: bool, detail: str, **extra: Any
           ) -> Dict[str, Any]:
    record: Dict[str, Any] = {"name": name, "passed": bool(passed),
                              "detail": detail}
    record.update(extra)
    return record


def _check_framework_imports() -> Dict[str, Any]:
    import importlib

    missing = []
    for name in ("fastapi", "starlette", "pydantic", "httpx"):
        try:
            importlib.import_module(name)
        except Exception:  # noqa: BLE001
            missing.append(name)
    return _check(
        "framework_imports", not missing,
        "every package the runtime checks need is importable" if not missing
        else "not importable: %s" % ", ".join(missing))


def _development_settings():
    """Settings that let the document be served, and nothing else.

    ``docs_enabled`` is refused in production, and ``/openapi.json`` is not
    routed without it - so the comparison needs a development environment to
    perform at all. Built here rather than read from the process environment
    so that verification does not depend on how a shell happened to be set up.
    """
    from apps.api.config import load_settings

    return load_settings({"PGX_API_ENV": "DEVELOPMENT",
                          "PGX_API_AUTH_MODE": "UNCONFIGURED",
                          "PGX_API_DOCS_ENABLED": "1"})


def _client():
    """A test client over the real application and a fail-closed provider.

    The provider is the production default: no assessment service, no release,
    no principal. Every check below is about transport - composition, the
    served document, a liveness probe - and none of them needs a capability.
    Using a fixture-backed provider here would put synthetic clinical data
    into a verification path whose output is a committed artifact.
    """
    from fastapi.testclient import TestClient

    from apps.api.factory import create_app
    from apps.api.provider import ServiceProvider

    settings = _development_settings()
    app = create_app(settings, ServiceProvider(settings=settings))
    return TestClient(app, raise_server_exceptions=False)


def _check_application_composes() -> Dict[str, Any]:
    try:
        client = _client()
    except Exception as error:  # noqa: BLE001
        return _check("application_composes", False,
                      "create_app raised %s" % type(error).__name__)
    return _check("application_composes", True,
                  "the application was built with a fail-closed provider",
                  route_count=len(client.app.routes))


def _check_openapi_served(root: str) -> Dict[str, Any]:
    """Serve the document over HTTP and compare it with the artifact.

    The comparison ignores ``x-pgx-runtime-verification`` and nothing else,
    which is what makes this check meaningful in both directions: it cannot
    pass because the two agree about being unverified, and it cannot fail
    merely because one of them has since been marked verified.
    """
    from apps.api.artifacts import load_openapi_document
    from apps.api.openapi import compare_documents

    try:
        response = _client().get("/openapi.json")
    except Exception as error:  # noqa: BLE001
        return _check("openapi_served_matches_committed", False,
                      "the request raised %s" % type(error).__name__)
    if response.status_code != 200:
        return _check("openapi_served_matches_committed", False,
                      "the served document answered %d" % response.status_code)
    try:
        committed = load_openapi_document(root)
    except OSError:
        return _check("openapi_served_matches_committed", False,
                      "the committed artifact could not be read")

    identical, differences = compare_documents(response.json(), committed)
    return _check(
        "openapi_served_matches_committed", identical,
        "the running application served a document identical to the committed "
        "artifact" if identical
        else "%d difference(s), first: %s" % (len(differences),
                                              differences[0]),
        difference_count=len(differences))


def _check_health_live() -> Dict[str, Any]:
    try:
        response = _client().get("/health/live")
    except Exception as error:  # noqa: BLE001
        return _check("health_live_answers", False,
                      "the request raised %s" % type(error).__name__)
    return _check("health_live_answers", response.status_code == 200,
                  "the liveness probe answered %d" % response.status_code)


def _check_asgi_runtime_suite() -> Dict[str, Any]:
    """Run the ASGI integration suite and require it to have actually run.

    Imported here rather than at module scope: this module ships in the wheel
    and the tests do not, so importing them at the top would make an installed
    package fail to import. A checkout without the suite fails this check,
    which is the right answer - the claim being recorded is that the suite
    ran.

    A suite that skipped everything does not count. ``testsRun`` minus the
    skips must be positive, or "executed" would be true of a run that
    executed nothing.
    """
    import unittest

    try:
        suite = unittest.defaultTestLoader.loadTestsFromName(
            "tests.integration.api.test_asgi_runtime")
    except Exception as error:  # noqa: BLE001
        return _check("asgi_runtime_suite", False,
                      "the suite could not be loaded (%s)"
                      % type(error).__name__)

    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=0).run(suite)
    executed = result.testsRun - len(result.skipped)
    passed = (result.wasSuccessful() and executed > 0
              and not result.unexpectedSuccesses)
    return _check(
        "asgi_runtime_suite", passed,
        "%d test(s) executed, %d skipped, %d failure(s), %d error(s)"
        % (executed, len(result.skipped), len(result.failures),
           len(result.errors)),
        tests_run=result.testsRun,
        tests_executed=executed,
        tests_skipped=len(result.skipped),
        failures=len(result.failures),
        errors=len(result.errors))


def run_verification(root: str = _REPO_ROOT) -> Dict[str, Any]:
    """Execute every check and return the record. Writes nothing.

    Ordered so a missing framework is reported once rather than as five
    identical import errors, and so the cheap structural checks run before the
    suite.
    """
    checks: List[Dict[str, Any]] = [_check_framework_imports()]
    if checks[0]["passed"]:
        checks.append(_check_application_composes())
        checks.append(_check_openapi_served(root))
        checks.append(_check_health_live())
        checks.append(_check_asgi_runtime_suite())
    return build_evidence(checks, root=root)


def main(argv: Optional[List[str]] = None) -> int:
    """``python -m apps.api.runtime_verification``.

    Exit 0 when verified, 1 when not. The record is written either way, so a
    failed run replaces a previous success rather than leaving it standing.
    """
    evidence = run_verification()
    path = write_evidence(evidence)

    print("WP-16 runtime verification: %s"
          % ("VERIFIED" if evidence["verified"] else "NOT VERIFIED"))
    for check in evidence["checks"]:
        print("  [%s] %-34s %s" % ("pass" if check["passed"] else "FAIL",
                                   check["name"], check["detail"]))
    for name in evidence["checks_not_run"]:
        print("  [ -- ] %-34s did not run" % name)
    print("evidence: %s" % EVIDENCE_PATH)
    if evidence["verified"]:
        print("regenerate the artifacts next: "
              "python -m apps.api.artifacts && python -m apps.web.artifacts")
    return 0 if evidence["verified"] else 1


if __name__ == "__main__":  # pragma: no cover - a developer entry point
    raise SystemExit(main())
