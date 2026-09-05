# -*- coding: utf-8 -*-
"""A rule-based secret scanner that never prints what it found (WP-23).

**The finding is a location, never a value.** Every result carries a path, a
line number and a rule id, and nothing else. A scanner that printed the match
would put the secret into CI logs, terminal scrollback, a bug report and
eventually a ticket - which is the same disclosure the scanner exists to
prevent, arriving through the tool that found it.

**Allowlist entries are exact and explain themselves.** An entry names one
path, one rule and one reason. There is no directory-wide exclusion and no
"skip tests", because a broadly-excluded directory is one where a real secret
can later be committed unnoticed. The development Docker Compose credential is
one exact entry, not a pattern that would also cover a production DSN
committed beside it.

**Negative fixtures are classified, not ignored.** ``tests/fixtures/wp23/``
contains deliberately unsafe-looking strings so each rule can be proven to
fire. Those findings are reported with ``classification: NEGATIVE_FIXTURE``
rather than suppressed, so the scan output still shows them and a real secret
appearing in that directory would still be a finding a reader sees.
"""

from __future__ import annotations

import io
import os
import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

__all__ = [
    "ALLOWLIST",
    "NEGATIVE_FIXTURES",
    "NEGATIVE_FIXTURE_PATHS",
    "NegativeFixture",
    "RULES",
    "SECRET_SCAN_VERSION",
    "ScanFinding",
    "SecretRule",
    "scan_repository",
    "scan_text",
]

SECRET_SCAN_VERSION = "pgx-wp23-secret-scan/1"


@dataclass(frozen=True)
class SecretRule:
    """One detector. The pattern is here; a matched value never leaves."""

    rule_id: str
    title: str
    pattern: str
    severity: str
    rationale: str

    def compiled(self):
        return re.compile(self.pattern)

    def to_json(self) -> dict:
        """Published without the pattern.

        A published regex is a published description of what the scanner does
        *not* catch, which is more useful to someone hiding a secret than to
        anyone else.
        """
        return {"rule_id": self.rule_id, "title": self.title,
                "severity": self.severity, "rationale": self.rationale}


RULES: Tuple[SecretRule, ...] = (
    SecretRule(
        rule_id="SEC-001-PRIVATE-KEY",
        title="Private key material",
        pattern=r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY",
        severity="CRITICAL",
        rationale="A private key in source is compromised the moment it is "
                  "committed, and rotating it is the only remedy."),
    SecretRule(
        rule_id="SEC-002-CLOUD-TOKEN",
        title="High-confidence cloud or API token",
        pattern=(r"\b(?:AKIA[0-9A-Z]{16}"
                 r"|gh[pousr]_[A-Za-z0-9]{36,}"
                 r"|sk-(?:live|proj)-[A-Za-z0-9]{20,}"
                 r"|xox[baprs]-[0-9A-Za-z-]{10,})\b"),
        severity="CRITICAL",
        rationale="Provider-specific prefixes with fixed shapes. High "
                  "confidence by construction: these patterns do not match "
                  "ordinary identifiers."),
    SecretRule(
        rule_id="SEC-003-BEARER-LITERAL",
        title="Authorization or cookie header literal",
        # ``<...>`` is excluded, as it is in SEC-004 and SEC-005: angle
        # brackets are the universal documentation convention for "a value
        # goes here", and every architecture document that shows the shape of
        # a header uses them. A rule that fired on the documentation of a
        # cookie would fire hardest on the pages explaining why the cookie
        # matters.
        pattern=(r"(?i)\b(?:Authorization\s*[:=]\s*[\"']?Bearer\s+(?!<)\S"
                 r"|Set-Cookie\s*[:=]\s*[\"']?__Host-pgx_session=(?!<)\S"
                 r"|Cookie\s*[:=]\s*[\"']?__Host-pgx_session=(?!<)\S)"),
        severity="HIGH",
        rationale="A captured header replays. Committed ones appear in test "
                  "recordings and copied curl commands more often than in "
                  "configuration. Angle-bracket placeholders are excluded: "
                  "they are documentation, not a captured value."),
    SecretRule(
        rule_id="SEC-004-PASSWORD-ASSIGNMENT",
        title="Non-placeholder password or secret assignment",
        pattern=(r"(?i)\b(?:password|passwd|secret|api_key|apikey|"
                 r"private_key|client_secret)\s*[:=]\s*"
                 r"[\"'](?!\s*$)(?![A-Z_]{3,}\}|\$\{|<|\{\{|CHANGE|REPLACE|"
                 r"EXAMPLE|PLACEHOLDER|TEST-ONLY|x{4,}|\*{3,})"
                 r"[^\"'\n]{8,}[\"']"),
        severity="HIGH",
        rationale="An assigned literal that is not obviously a placeholder. "
                  "Placeholder shapes are excluded by the pattern rather "
                  "than by an allowlist, so a new placeholder convention "
                  "does not need a new exception."),
    SecretRule(
        rule_id="SEC-005-DSN-CREDENTIAL",
        title="Connection string carrying a credential",
        # Two exclusions are in the pattern rather than in the allowlist,
        # because both describe a *shape* that can never be a production
        # credential and an allowlist entry would have to be re-added for
        # every new file that used one.
        #
        # 1. A placeholder user or password - USER, PASSWORD, user, pw, <user>,
        #    ${VAR} - is documentation. Ninety-odd of these live in the DSN
        #    redaction module's own docstrings and in WP-02's evidence, all
        #    demonstrating what redaction removes.
        # 2. A host of localhost, 127.0.0.1, ::1 or a compose service name is
        #    the documented development configuration the work package
        #    explicitly scopes out. A credential for a database nobody outside
        #    the machine can reach is not a disclosure.
        #
        # Both exclusions narrow the rule and neither disables it: a DSN with
        # a real-looking password pointing at a real hostname still fires.
        pattern=(r"(?i)\b(?:postgresql|postgres|mysql|mongodb|redis|amqp)"
                 r"(?:\+\w+)?://"
                 r"(?!(?:user|username|pass|pw|password|test|example|"
                 r"placeholder|changeme|<)[:@])"
                 r"[^\s:/@\"']+:"
                 r"(?!(?:pw|pass|password|secret|one|two|three|changeme|"
                 r"example|placeholder|\*+)@)"
                 # A password that is already asterisks is redaction *output*.
                 # WP-02's evidence document is full of it, and reporting a
                 # redacted DSN as a leaked one would make the rule fire
                 # loudest on the code that does the redacting.
                 r"[^\s:/@\"']{2,}@"
                 r"(?!localhost|127\.0\.0\.1|\[::1\]|0\.0\.0\.0|"
                 r"postgres[:/@\s]|db[:/@\s]|host[:/@\s]|HOST[:/@\s])"),
        severity="CRITICAL",
        rationale="A DSN with an inline password is a credential and a "
                  "hostname together, which is everything an attacker needs. "
                  "Placeholder credentials and development hosts (localhost, "
                  "127.0.0.1, the compose service names) are excluded by the "
                  "pattern: they are the documented development "
                  "configuration, and a rule that reported all ninety of "
                  "them would be a rule nobody reads."),
    SecretRule(
        rule_id="SEC-006-COMMITTED-ENV-FILE",
        title="Committed environment file",
        pattern=r"\A",
        severity="HIGH",
        rationale="A .env file is where deployment secrets live by "
                  "convention, so its presence in the tree is the finding; "
                  "the contents are never read or reported."),
    SecretRule(
        rule_id="SEC-007-ARGON2-HASH",
        title="Committed password hash",
        pattern=r"\$argon2(?:id|i|d)\$v=\d+\$m=\d+,t=\d+,p=\d+\$[A-Za-z0-9+/]",
        severity="HIGH",
        rationale="A password hash is offline-attackable. A real one must "
                  "never be committed, and a test that needed one would be a "
                  "test that could be run against the real account."),
)

#: Files whose *presence* is the finding. Their contents are never opened.
_PRESENCE_RULES: Mapping[str, str] = {"SEC-006-COMMITTED-ENV-FILE": ".env"}

#: Suffixes that make an environment file a *template* rather than a secret.
#: ``.env.example`` is the documented convention for committing the shape of
#: a configuration without its values, and this repository's one says so on
#: its third line. Reporting it forever would train a reader to ignore the
#: rule, which is how the real ``.env`` gets ignored too.
_ENV_TEMPLATE_SUFFIXES = (".example", ".sample", ".template", ".dist")


@dataclass(frozen=True)
class AllowlistEntry:
    """One exact, scoped, explained exception.

    Path and rule are both exact. There is no glob and no directory prefix:
    an entry that covered a directory would keep covering it after somebody
    committed something else there.
    """

    path: str
    rule_id: str
    reason: str

    def to_json(self) -> dict:
        return {"path": self.path, "rule_id": self.rule_id,
                "reason": self.reason}


ALLOWLIST: Tuple[AllowlistEntry, ...] = (
    AllowlistEntry(
        path="docker-compose.yml",
        rule_id="SEC-004-PASSWORD-ASSIGNMENT",
        reason="The documented development-only database password for the "
               "disposable local PostgreSQL container. It is not a "
               "production credential, no deployment reads it, and the "
               "exception is this one file and this one rule - a pattern "
               "covering the directory would also cover a production DSN "
               "committed beside it."),
)

@dataclass(frozen=True)
class NegativeFixture:
    """One file that deliberately contains an unsafe-looking string.

    Classified, not ignored. A finding here is still reported - with
    ``classification: NEGATIVE_FIXTURE`` - so a real secret committed into one
    of these files still appears in the scan output and a reader still sees
    it. The difference from an allowlist entry is only that it does not count
    toward the blocking total.

    Each entry names one exact path and says what the file is proving. There
    is no "skip tests" and no directory sweep, because an excluded directory
    is one where a real secret can later be committed unnoticed - and the
    files below are precisely the ones that would look identical either way.
    """

    path: str
    reason: str

    def to_json(self) -> dict:
        return {"path": self.path, "reason": self.reason}


NEGATIVE_FIXTURES: Tuple[NegativeFixture, ...] = (
    NegativeFixture(
        path="tests/fixtures/wp23/negative_controls.py",
        reason="WP-23's own negative controls. Each string exists to prove "
               "one rule fires; a rule with no fixture proving it detects "
               "anything is a rule nobody has run."),
    NegativeFixture(
        path="tests/unit/verification/test_scrub.py",
        reason="WP-19's scrubber tests. The private-key header here is the "
               "input that proves the scrubber removes one."),
    NegativeFixture(
        path="tests/unit/api/test_runtime_verification.py",
        reason="Proves an Authorization header is stripped from runtime "
               "evidence before it is written."),
    NegativeFixture(
        path="tests/unit/infrastructure/test_configuration_policy.py",
        reason="WP-02's configuration-policy tests. The password literal is "
               "the input that proves configuration values are redacted."),
    NegativeFixture(
        path="tests/unit/api/test_contracts.py",
        reason="Proves a prohibited request field's value never reaches a "
               "response body."),
    NegativeFixture(
        path="tests/unit/api/test_errors.py",
        reason="Proves an error body never quotes a submitted value."),
    NegativeFixture(
        path="tests/unit/api/test_health.py",
        reason="Proves the readiness document never quotes a DSN."),
    NegativeFixture(
        path="tests/unit/api/test_safety.py",
        reason="Proves a prohibited value never reaches an assessment "
               "response."),
    NegativeFixture(
        path="tests/unit/web/test_security.py",
        reason="Proves a rendered page never carries a credential."),
    NegativeFixture(
        path="tests/unit/application/test_release_cli.py",
        reason="Proves the release CLI redacts a DSN in its output."),
    NegativeFixture(
        path="tests/unit/ingestion/test_ingestion_cli.py",
        reason="Proves the ingestion CLI redacts configuration values."),
    NegativeFixture(
        path="tests/unit/ingestion/test_request_key_and_cache.py",
        reason="Proves a request key never embeds a credential."),
    NegativeFixture(
        path="tests/unit/validation/test_cases.py",
        reason="Proves a validation case manifest carries no credential."),
    NegativeFixture(
        path="tests/unit/infrastructure/test_seed_and_cleanup_safety.py",
        reason="WP-02's seed-safety tests. The single-letter DSNs here are "
               "the inputs that prove endpoint canonicalisation treats two "
               "spellings of one database as the same database - which is "
               "what stops the seed pointing at a server it was not aimed "
               "at."),
)

NEGATIVE_FIXTURE_PATHS: Tuple[str, ...] = tuple(
    item.path for item in NEGATIVE_FIXTURES)

_SKIP_DIRECTORIES = frozenset({
    "__pycache__", ".git", ".venv", ".venv-linux", "node_modules",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "build", "dist",
    "_to_delete",
})

_SCANNED_SUFFIXES = (".py", ".md", ".json", ".yml", ".yaml", ".toml",
                     ".html", ".css", ".js", ".ini", ".cfg", ".txt", ".sh",
                     ".sql", ".env")


@dataclass(frozen=True)
class ScanFinding:
    """One location. Never a value.

    ``matched_length`` is the only thing recorded about the match itself, and
    it exists so a reviewer can tell a two-character false positive from a
    forty-character token without seeing either.
    """

    path: str
    line: int
    rule_id: str
    severity: str
    classification: str
    matched_length: int

    def to_json(self) -> dict:
        return {"path": self.path, "line": self.line,
                "rule_id": self.rule_id, "severity": self.severity,
                "classification": self.classification,
                "matched_length": self.matched_length}

    def __repr__(self) -> str:  # pragma: no cover - fixed on purpose
        return "<ScanFinding %s:%d %s>" % (self.path, self.line, self.rule_id)


def _classification(relative: str, rule_id: str) -> str:
    for entry in ALLOWLIST:
        if entry.path == relative and entry.rule_id == rule_id:
            return "ALLOWLISTED"
    for fixture in NEGATIVE_FIXTURES:
        if relative == fixture.path:
            return "NEGATIVE_FIXTURE"
    return "FINDING"


def scan_text(text: str, *, relative: str = "<memory>",
              rules: Sequence[SecretRule] = RULES) -> List[ScanFinding]:
    """Scan one document. Returns locations; the values stay here."""
    findings: List[ScanFinding] = []
    for rule in rules:
        if rule.rule_id in _PRESENCE_RULES:
            continue
        compiled = rule.compiled()
        for number, line in enumerate(text.splitlines(), start=1):
            match = compiled.search(line)
            if match is None:
                continue
            findings.append(ScanFinding(
                path=relative, line=number, rule_id=rule.rule_id,
                severity=rule.severity,
                classification=_classification(relative, rule.rule_id),
                # The length, never the text. A reviewer can tell a short
                # false positive from a long token without seeing either.
                matched_length=len(match.group(0))))
    return findings


def scan_repository(root: str, *, rules: Sequence[SecretRule] = RULES
                    ) -> Dict[str, object]:
    """Scan the tree, including every committed artifact.

    Artifacts are scanned rather than skipped: a published document is the
    thing most likely to be read by somebody outside the project, so a
    credential that reached one is the worst case rather than a lesser one.
    """
    findings: List[ScanFinding] = []
    scanned = 0
    for directory, subdirectories, files in os.walk(root):
        subdirectories[:] = [name for name in sorted(subdirectories)
                             if name not in _SKIP_DIRECTORIES
                             and not name.startswith(".")]
        for name in sorted(files):
            path = os.path.join(directory, name)
            relative = os.path.relpath(path, root).replace(os.sep, "/")
            if name == ".env" or (name.startswith(".env.")
                                  and not name.endswith(
                                      _ENV_TEMPLATE_SUFFIXES)):
                findings.append(ScanFinding(
                    path=relative, line=0,
                    rule_id="SEC-006-COMMITTED-ENV-FILE", severity="HIGH",
                    classification=_classification(
                        relative, "SEC-006-COMMITTED-ENV-FILE"),
                    matched_length=0))
                continue
            if not name.endswith(_SCANNED_SUFFIXES):
                continue
            try:
                with io.open(path, encoding="utf-8", errors="strict") as fh:
                    text = fh.read()
            except (UnicodeDecodeError, OSError):
                continue
            scanned += 1
            findings.extend(scan_text(text, relative=relative, rules=rules))

    blocking = [item for item in findings
                if item.classification == "FINDING"]
    return {
        "secret_scan_version": SECRET_SCAN_VERSION,
        "rule_count": len(rules),
        "rules": [rule.to_json() for rule in rules],
        "allowlist": [entry.to_json() for entry in ALLOWLIST],
        "allowlist_count": len(ALLOWLIST),
        "negative_fixtures": [item.to_json() for item in NEGATIVE_FIXTURES],
        "negative_fixture_count": len(NEGATIVE_FIXTURES),
        "scanned_file_count": scanned,
        "finding_count": len(blocking),
        "findings": [item.to_json() for item in blocking],
        "classified_finding_count": len(findings) - len(blocking),
        "classified_findings": [item.to_json() for item in findings
                                if item.classification != "FINDING"],
        "status": "CLEAN" if not blocking else "FINDINGS",
        "no_value_is_reported": (
            "Every result is a path, a line and a rule id. No matched value "
            "appears in this document, in the command output or in any log: "
            "a scanner that printed what it found would be the same "
            "disclosure it exists to prevent, arriving through the tool."),
        "allowlist_policy": (
            "Each entry names one exact path and one exact rule with a "
            "reason. There is no directory-wide exclusion and no blanket "
            "skip of tests or fixtures, because an excluded directory is one "
            "where a real secret can later be committed unnoticed."),
    }
