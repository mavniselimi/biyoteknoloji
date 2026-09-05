"""The gate a page passes before it is delivered.

WP-15's scanner reads text. HTML is not text, and the difference is exactly
where a prohibited claim can hide, so this module scans a rendered page three
ways and refuses if any of them finds something.

**1. The extracted text.** ``<b>güven</b>li ilaç`` contains no prohibited
substring in its raw form and reads as one to every human who sees it. Text
nodes are concatenated in document order before scanning, so a tag placed
inside a phrase does not break the phrase.

**2. The attribute values.** ``title``, ``alt``, ``aria-label`` and every
``data-`` attribute are read by screen readers, shown on hover and copied into
bug reports. A claim that lives only in an attribute is a claim.

**3. The raw markup.** Cheap, and it catches a claim in a comment or in a
place the parser did not treat as text.

The gate also refuses markup that is unsafe regardless of what it says: a
``<script>`` element, an event-handler attribute, a ``javascript:`` or
``data:`` URL, an external resource reference, a control character. Those are
not claim problems, but this is the last place a page passes through, and a
check here cannot be forgotten by a template.

**What the gate cannot do.** The scanner is lexical: it matches published
patterns over folded text and performs no semantic analysis. A page that says
something prohibited in words nobody wrote a pattern for passes. A clean scan
is evidence that no published pattern matched; it is never evidence that a
page is safe. That limit is published in the gate's own contract rather than
left for a reader to infer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from pgx.domain.claims import (CLAIM_SCANNER_VERSION, ClaimBoundary,
                               ClaimScanResult, DEFAULT_CLAIM_BOUNDARY,
                               scan_claim_text)

__all__ = [
    "HTML_GATE_VERSION",
    "MAX_DISPLAY_LENGTH",
    "PageSafetyError",
    "PageScanReport",
    "extract_attribute_text",
    "extract_visible_text",
    "gate_contract",
    "require_safe_page",
    "scan_page",
]

HTML_GATE_VERSION = "pgx-web-html-gate/1"

#: The longest a single displayed value may be. A page is a fixed layout over
#: bounded governed facts; a value longer than this is a value that came from
#: somewhere it should not have.
MAX_DISPLAY_LENGTH = 4096

#: Elements whose content is not shown to a reader and must therefore not be
#: concatenated into the visible text - and, for the first two, must not be
#: present at all.
_NON_TEXT_ELEMENTS = frozenset({"script", "style", "template"})

#: Attributes that carry text a person or a screen reader will encounter.
_TEXTUAL_ATTRIBUTES = frozenset({
    "title", "alt", "aria-label", "aria-description", "aria-placeholder",
    "aria-valuetext", "aria-roledescription", "placeholder", "label",
    "content", "value", "summary"})

#: Attributes that may carry executable content, in any element.
_EVENT_ATTRIBUTE = re.compile(r"^on[a-z]+$", re.I)

#: URL-valued attributes the gate inspects.
_URL_ATTRIBUTES = frozenset({"href", "src", "action", "formaction", "data",
                             "poster", "srcset", "background"})

#: The only URL shapes a page may contain: an absolute internal path, a
#: fragment, or a bare query. No scheme is permitted at all - not ``https:``,
#: because this interface links to nothing outside itself, and permitting one
#: scheme means writing a parser that decides which.
_SAFE_URL = re.compile(r"^(?:/(?!/)[^\s\"'<>\\]*|#[A-Za-z0-9._:-]*|\?[^\s\"'<>\\]*)$")

_CONTROL_CHARACTERS = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f  ]")


class PageSafetyError(Exception):
    """A rendered page was refused. It is not delivered.

    Carries codes and offsets, never the offending sentence: a refusal record
    holding a prohibited claim puts that claim into the log, where it outlives
    the request and is read by people the page was never shown to.
    """

    def __init__(self, code: str, message: str, *,
                 detail: Optional[Mapping[str, Any]] = None) -> None:
        self.code = code
        self.detail = dict(detail or {})
        super().__init__(message)


class _PageParser(HTMLParser):
    """Collects visible text, attribute text, URLs and structural problems."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text_parts: List[str] = []
        self.attribute_parts: List[str] = []
        self.urls: List[Tuple[str, str]] = []
        self.problems: List[Tuple[str, str]] = []
        self._suppressing: List[str] = []
        self._in_script = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        lowered = tag.lower()
        if lowered in ("script", "style", "template"):
            self._suppressing.append(lowered)
        if lowered == "script":
            self._in_script += 1
            # A script *element* is not the problem; executable content in the
            # document is. A reference to this origin's own file is what the
            # content-security policy permits and what progressive enhancement
            # needs, so it is checked as a URL like any other. A script with
            # no src carries its program inline, and that is refused.
            sources = [value for name, value in attrs
                       if (name or "").lower() == "src"]
            if not sources or not (sources[0] or "").strip():
                self.problems.append(("INLINE_SCRIPT", lowered))
        if lowered in ("iframe", "object", "embed", "applet", "frame"):
            self.problems.append(("EMBEDDED_CONTENT", lowered))
        for name, value in attrs:
            name = (name or "").lower()
            value = value or ""
            if _EVENT_ATTRIBUTE.match(name):
                self.problems.append(("EVENT_HANDLER", name))
            if name == "style":
                # An inline style attribute is blocked by the content-security
                # policy anyway; refusing it here means the page and the
                # policy agree rather than the page relying on the policy.
                self.problems.append(("INLINE_STYLE", name))
            if name in _URL_ATTRIBUTES:
                self.urls.append((name, value))
            if name in _TEXTUAL_ATTRIBUTES or name.startswith("data-"):
                self.attribute_parts.append(value)

    def handle_startendtag(self, tag: str, attrs) -> None:
        self.handle_starttag(tag, attrs)
        if self._suppressing and self._suppressing[-1] == tag.lower():
            self._suppressing.pop()

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script" and self._in_script:
            self._in_script -= 1
        if self._suppressing and self._suppressing[-1] == tag.lower():
            self._suppressing.pop()

    def handle_data(self, data: str) -> None:
        if self._in_script and data.strip():
            # Content inside a script element, even one with a src. A browser
            # ignores it; a reviewer reading the page source does not, and a
            # payload placed there would be invisible to a text scan.
            self.problems.append(("INLINE_SCRIPT", "script"))
        if self._suppressing:
            return
        self.text_parts.append(data)

    def handle_comment(self, data: str) -> None:
        # Collected as text: a comment is not shown, but it ships with the
        # page and is read by anyone who opens the source.
        self.attribute_parts.append(data)


@dataclass(frozen=True, slots=True)
class PageScanReport:
    """What the gate found. Safe to store beside a rendered page."""

    is_clean: bool
    html_length: int
    visible_text_length: int
    violation_count: int
    categories: Tuple[str, ...]
    rule_ids: Tuple[str, ...]
    structural_problems: Tuple[Tuple[str, str], ...]
    unsafe_urls: Tuple[str, ...]
    scanner_version: str = CLAIM_SCANNER_VERSION
    gate_version: str = HTML_GATE_VERSION

    def to_json(self) -> Dict[str, Any]:
        return {
            "gate_version": self.gate_version,
            "scanner_version": self.scanner_version,
            "is_clean": self.is_clean,
            "html_length": self.html_length,
            "visible_text_length": self.visible_text_length,
            "violation_count": self.violation_count,
            "categories": list(self.categories),
            "rule_ids": list(self.rule_ids),
            "structural_problems": [list(item)
                                    for item in self.structural_problems],
            "unsafe_urls": list(self.unsafe_urls),
        }


def _parse(html: str) -> _PageParser:
    parser = _PageParser()
    parser.feed(html)
    parser.close()
    return parser


def extract_visible_text(html: str) -> str:
    """Text nodes in document order, with tags removed but words joined.

    Joined with a single space rather than concatenated directly: two nodes
    separated by a block element are two words, and gluing them would invent a
    compound the page does not show. Within a phrase an inline tag still
    disappears, which is the case this exists for.
    """
    parser = _parse(html)
    return " ".join(part.strip() for part in parser.text_parts if part.strip())


def extract_attribute_text(html: str) -> str:
    """Every attribute value a reader or a screen reader can encounter."""
    parser = _parse(html)
    return " ".join(part.strip() for part in parser.attribute_parts
                    if part.strip())


def _concatenated_text(html: str) -> str:
    """Text with inline boundaries removed entirely.

    The join in :func:`extract_visible_text` inserts a space between nodes,
    which is right for reading and wrong for detection: ``güven<b></b>li``
    becomes ``güven li`` and no longer matches. This variant removes the
    boundaries so a phrase split by markup is still one phrase.
    """
    parser = _parse(html)
    return "".join(parser.text_parts)


def scan_page(html: str, *,
              boundary: ClaimBoundary = DEFAULT_CLAIM_BOUNDARY,
              languages: Optional[Sequence[str]] = None) -> PageScanReport:
    """Scan one rendered page every way it can be read.

    Returns a report; it does not raise. :func:`require_safe_page` is the one
    that refuses, so a caller that wants to *inspect* a page - a test, a
    snapshot generator - does not have to catch an exception to do it.
    """
    if not isinstance(html, str):
        raise TypeError("a rendered page is a string")

    parser = _parse(html)
    visible = extract_visible_text(html)
    concatenated = _concatenated_text(html)
    attributes = extract_attribute_text(html)

    results = [
        scan_claim_text(visible, languages=languages, boundary=boundary),
        scan_claim_text(concatenated, languages=languages, boundary=boundary),
        scan_claim_text(attributes, languages=languages, boundary=boundary),
        scan_claim_text(html, languages=languages, boundary=boundary),
    ]
    violations = [item for result in results for item in result.violations]
    categories = sorted({item.category.value for item in violations})
    rule_ids = sorted({item.rule_id for item in violations})

    unsafe_urls = []
    for name, value in parser.urls:
        candidate = (value or "").strip()
        if not candidate:
            continue
        if _SAFE_URL.match(candidate) is None:
            unsafe_urls.append("%s=%s" % (name, candidate[:120]))

    problems = list(parser.problems)
    if _CONTROL_CHARACTERS.search(html):
        problems.append(("CONTROL_CHARACTER", "document"))

    return PageScanReport(
        is_clean=not violations and not problems and not unsafe_urls,
        html_length=len(html),
        visible_text_length=len(visible),
        violation_count=len(violations),
        categories=tuple(categories),
        rule_ids=tuple(rule_ids),
        structural_problems=tuple(sorted(set(problems))),
        unsafe_urls=tuple(sorted(set(unsafe_urls))),
    )


def require_safe_page(html: str, *,
                      boundary: ClaimBoundary = DEFAULT_CLAIM_BOUNDARY,
                      languages: Optional[Sequence[str]] = None) -> PageScanReport:
    """Scan, and refuse to deliver a page that is not clean.

    Raises:
        PageSafetyError: the page carries a prohibited claim in its text, its
            attributes or its markup; or it carries a script, an event
            handler, an inline style, embedded content, an external or
            scriptable URL, or a control character. A dirty page is blocked
            rather than delivered with the offending part removed: removing it
            would leave a page whose remaining text was written to sit beside
            something no longer there.
    """
    report = scan_page(html, boundary=boundary, languages=languages)
    if report.is_clean:
        return report
    if report.violation_count:
        raise PageSafetyError(
            "WEB_PROHIBITED_CLAIM",
            "the rendered page contains %d prohibited claim match(es) in "
            "categor(ies) %s; it is not delivered"
            % (report.violation_count, ", ".join(report.categories)),
            detail=report.to_json())
    raise PageSafetyError(
        "WEB_UNSAFE_MARKUP",
        "the rendered page contains unsafe markup (%s) or unsafe URLs (%d); "
        "it is not delivered"
        % (", ".join(code for code, _ in report.structural_problems) or "none",
           len(report.unsafe_urls)),
        detail=report.to_json())


def check_display_value(value: str, *, location: str) -> str:
    """One value about to be displayed, or a refusal.

    Applied to data-originated values before they reach a template. Escaping
    handles what a value *means* to a browser; this handles what it is: a
    control character, or a value long enough to be a payload rather than a
    fact.
    """
    if not isinstance(value, str):
        raise PageSafetyError(
            "WEB_DISPLAY_VALUE_INVALID",
            "a displayed value is a string", detail={"location": location})
    if len(value) > MAX_DISPLAY_LENGTH:
        raise PageSafetyError(
            "WEB_DISPLAY_VALUE_TOO_LONG",
            "a displayed value exceeds %d characters" % MAX_DISPLAY_LENGTH,
            detail={"location": location, "limit": MAX_DISPLAY_LENGTH})
    if _CONTROL_CHARACTERS.search(value):
        raise PageSafetyError(
            "WEB_DISPLAY_VALUE_CONTROL_CHARACTER",
            "a displayed value contains a control character",
            detail={"location": location})
    return value


def gate_contract() -> Dict[str, Any]:
    """The gate's published rules and its published limits."""
    return {
        "gate_version": HTML_GATE_VERSION,
        "scanner_version": CLAIM_SCANNER_VERSION,
        "scanned_projections": [
            "visible text, nodes joined with a space",
            "concatenated text, so markup inside a phrase does not break it",
            "textual and data- attribute values, plus comments",
            "the raw markup",
        ],
        "structural_refusals": [
            "INLINE_SCRIPT", "EVENT_HANDLER", "INLINE_STYLE",
            "EMBEDDED_CONTENT", "CONTROL_CHARACTER"],
        "script_policy": (
            "a script element referencing a same-origin file is permitted and "
            "checked as a URL; a script with no src, or with content inside "
            "it, carries executable code in the document and is refused"),
        "url_policy": (
            "absolute internal paths, fragments and bare queries only; no "
            "scheme of any kind, so no parser decides which schemes are safe"),
        "max_display_length": MAX_DISPLAY_LENGTH,
        "limits": [
            "the scanner is lexical: it matches published patterns over "
            "folded text and performs no semantic analysis",
            "a prohibited claim phrased outside the published patterns is not "
            "detected",
            "safe-context suppression is broad, so a negated sentence "
            "suppresses matches inside it",
            "a clean scan is evidence that no published pattern matched, and "
            "is never evidence that a page is safe",
        ],
    }
