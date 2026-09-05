# -*- coding: utf-8 -*-
"""Keeping host paths, credentials and clinical payloads out of evidence.

Verification evidence is committed. That makes it a document with two jobs it
can fail at: it can leak the machine that produced it, and it can leak the data
the software was pointed at. Both have happened to other projects by accident,
and both are cheap to prevent at the moment of writing.

The module does two things, in this order:

**Replace what is known.** ``scrub_text`` rewrites the repository root, the
home directory and the temporary directory as ``<repo>``, ``<home>`` and
``<tmp>``. Those appear legitimately - a test id has no path in it, but a skip
reason often does - and rewriting them keeps the document useful.

**Refuse what is left.** ``reject_sensitive`` scans the rendered document for
anything that still looks like an absolute host path, a credential, or a
clinical payload, and raises. It refuses rather than silently deleting: a
document that had text removed from it is no longer the evidence it claims to
be, and the operator needs to know which generator produced the leak.

The order matters. Scrubbing first means the refusal fires only on things the
scrubber did not know about, which is exactly the set a human should look at.
"""

from __future__ import annotations

import os
import re
from typing import Iterable, Mapping, Optional, Sequence, Tuple

from pgx.verification.errors import ScrubRefusal

__all__ = [
    "FORBIDDEN_PATTERNS",
    "scrub_text",
    "scrub_document",
    "reject_sensitive",
    "safe_render",
]

#: Things a committed verification artifact must never contain. Each entry is
#: ``(name, compiled pattern)``; the name is what the refusal reports, so it is
#: written for somebody reading a build failure.
FORBIDDEN_PATTERNS: Tuple[Tuple[str, "re.Pattern[str]"], ...] = (
    ("an absolute POSIX home path",
     re.compile(r"/(?:home|Users|root)/[A-Za-z0-9._-]+")),
    ("an absolute Windows path",
     re.compile(r"[A-Za-z]:\\\\?(?:Users|Documents)", re.IGNORECASE)),
    ("a private temporary directory",
     re.compile(r"/(?:private/)?(?:tmp|var/folders)/[A-Za-z0-9._-]{6,}")),
    ("a database URL carrying a password",
     re.compile(r"[a-z+]+://[^\s:/@]+:[^\s@/]+@", re.IGNORECASE)),
    ("a credential assignment",
     re.compile(r"(?:password|passwd|secret|api[_-]?key|access[_-]?token"
                r"|private[_-]?key)\s*[=:]\s*\S", re.IGNORECASE)),
    ("a bearer token",
     re.compile(r"\b[Bb]earer\s+[A-Za-z0-9._~+/-]{12,}")),
    ("a private key block",
     re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    # The backslashes are optional because the same field can arrive two ways:
    # as a real key, which renders as "patient_name":, and inside a string that
    # itself contains JSON, which renders as \"patient_name\":. A pattern that
    # matched only the first would miss a payload embedded in a skip reason.
    ("a clinical payload field",
     re.compile(r"\\?\"(?:patient_name|patient_id|mrn|date_of_birth|dob"
                r"|national_id|diplotype|star_allele|genotype|vcf|fastq|bam)"
                r"\\?\"\s*:", re.IGNORECASE)),
)

#: Replacements applied before the refusal scan, longest path first so that a
#: temporary directory inside a home directory is rewritten as the temporary
#: directory rather than half-rewritten.
_PLACEHOLDERS = (
    ("<tmp>", ("TMPDIR",)),
    ("<home>", ("HOME", "USERPROFILE")),
)


def _replacements(root: str,
                  environ: Optional[Mapping[str, str]] = None
                  ) -> Tuple[Tuple[str, str], ...]:
    environment = os.environ if environ is None else environ
    found = [(os.path.abspath(root), "<repo>")]
    for placeholder, names in _PLACEHOLDERS:
        for name in names:
            value = environment.get(name)
            if value:
                found.append((os.path.abspath(value), placeholder))
    found.append(("/tmp", "<tmp>"))
    # Longest first: <repo> is usually inside <home>, and rewriting <home>
    # first would turn the repository root into "<home>/Projects/..." and hide
    # the fact that it was the repository.
    found.sort(key=lambda pair: len(pair[0]), reverse=True)
    return tuple(found)


def scrub_text(text: str, root: str,
               environ: Optional[Mapping[str, str]] = None) -> str:
    """Replace known machine-specific paths with stable placeholders."""
    scrubbed = text
    for value, placeholder in _replacements(root, environ):
        if value and value != "/":
            scrubbed = scrubbed.replace(value, placeholder)
    return scrubbed


def scrub_document(document: object, root: str,
                   environ: Optional[Mapping[str, str]] = None) -> object:
    """``scrub_text`` applied to every string in a JSON-shaped document.

    Keys are scrubbed too. A dictionary keyed by absolute path would otherwise
    leak the machine in the one place a value-only scrubber never looks.
    """
    if isinstance(document, str):
        return scrub_text(document, root, environ)
    if isinstance(document, dict):
        return {scrub_text(str(key), root, environ):
                scrub_document(value, root, environ)
                for key, value in document.items()}
    if isinstance(document, (list, tuple)):
        return [scrub_document(item, root, environ) for item in document]
    return document


def reject_sensitive(rendered: str,
                     patterns: Sequence[Tuple[str, "re.Pattern[str]"]]
                     = FORBIDDEN_PATTERNS) -> None:
    """Raise if ``rendered`` still contains something that must not ship.

    The sample in the refusal is deliberately short and is itself truncated:
    an error message that quoted the whole credential would put it in a build
    log, which is the same disclosure by a different route.
    """
    for name, pattern in patterns:
        match = pattern.search(rendered)
        if match is not None:
            raise ScrubRefusal(
                "refusing to write verification evidence containing %s" % name,
                _sample(match.group(0)))


def _sample(text: str, limit: int = 24) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[:limit] + "..."


def safe_render(document: object, root: str,
                environ: Optional[Mapping[str, str]] = None) -> str:
    """Scrub, render canonically, then refuse if anything survived.

    The single entry point every artifact writer uses, so that no generator can
    forget half of it. The rendering settings match the rest of the project:
    two-space indent, sorted keys, ASCII, one trailing newline.
    """
    import json
    scrubbed = scrub_document(document, root, environ)
    rendered = json.dumps(scrubbed, indent=2, sort_keys=True,
                          ensure_ascii=True) + "\n"
    reject_sensitive(rendered)
    return rendered
