# -*- coding: utf-8 -*-
"""Shared helpers for the WP-17 tests.

Two things: the module inventories the boundary tests read source with, and a
small standard-library HTML inspector the accessibility and safety tests use.

The inspector parses with :mod:`html.parser` rather than a third-party
library. Not because a third-party one is unavailable - lxml and BeautifulSoup
happen to be installed here - but because these assertions are about what a
*browser* receives, and a check that needed an optional dependency would be a
check that silently stops running in the environment where it matters.
"""

from __future__ import annotations

import ast
import io
import os
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", ".."))
WEB_DIR = os.path.join(REPO_ROOT, "apps", "web")
TEMPLATE_DIR = os.path.join(WEB_DIR, "templates")
STATIC_DIR = os.path.join(WEB_DIR, "static")

#: The half that decides things. All of it imports and runs in this
#: environment, including the template renderer - Jinja2 is installed here.
FRAMEWORK_FREE_MODULES: Tuple[str, ...] = (
    "__init__.py",
    "artifacts.py",
    "claim_gate.py",
    "client.py",
    "config.py",
    "demo_cases.py",
    "demo_migration.py",
    "errors.py",
    "gate_status.py",
    "labels.py",
    "pages.py",
    "render.py",
    "routes.py",
    "security.py",
    "submission.py",
    # WP-21: reads one committed JSON file and returns it. No framework, no
    # benchmark engine, no port to restricted storage.
    "validation_feed.py",
    os.path.join("view_models", "__init__.py"),
    os.path.join("view_models", "assessment.py"),
    # Wave 4B. The candidate track's assessment model: a separate page,
    # because a candidate answer and a governed one carry different
    # authorities and a reader must be able to tell which is in front of them.
    os.path.join("view_models", "candidate_assessment.py"),
    os.path.join("view_models", "base.py"),
    os.path.join("view_models", "pages.py"),
    os.path.join("view_models", "preservation.py"),
)

#: The half that only wires. None of it imports where FastAPI is absent.
FRAMEWORK_BOUND_MODULES: Tuple[str, ...] = (
    "dependencies.py",
    "factory.py",
    "main.py",
    os.path.join("routers", "__init__.py"),
    os.path.join("routers", "pages.py"),
)

#: Packages the interface may never import. The engine and the ORM are the
#: point: a page must reach governed facts through the API client, never by
#: recomputing them or by reading a row.
FORBIDDEN_IMPORT_ROOTS: Tuple[str, ...] = (
    "risk_engine", "gemini_report_generator", "alternative_ranker",
    "candidate_onboarding", "clinpgx_probe", "clinpgx_probe_v2",
    "sqlalchemy", "alembic", "psycopg", "psycopg2",
    "google", "openai", "anthropic", "requests", "urllib", "socket",
    "http",
)

#: ``pgx`` subpackages a web module may never import directly.
FORBIDDEN_PGX_PREFIXES: Tuple[str, ...] = (
    "pgx.engine", "pgx.rules", "pgx.coverage", "pgx.infrastructure",
    "pgx.curation", "pgx.normalization", "pgx.evidence", "pgx.ingestion",
    "pgx.scientific",
)


def module_path(relative: str) -> str:
    return os.path.join(WEB_DIR, relative)


def web_modules() -> List[str]:
    """Every Python module physically present under ``apps/web``."""
    found: List[str] = []
    for root, _dirs, files in os.walk(WEB_DIR):
        if "__pycache__" in root:
            continue
        for name in sorted(files):
            if name.endswith(".py"):
                found.append(os.path.join(root, name))
    return sorted(found)


def template_paths() -> List[str]:
    return sorted(os.path.join(TEMPLATE_DIR, name)
                  for name in os.listdir(TEMPLATE_DIR)
                  if name.endswith(".html"))


def source(path: str) -> str:
    with io.open(path, encoding="utf-8") as handle:
        return handle.read()


def tree(path: str) -> ast.Module:
    return ast.parse(source(path), filename=path)


def imports_of(path: str) -> Set[str]:
    found: Set[str] = set()
    for node in ast.walk(tree(path)):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def identifiers_of(path: str) -> Set[str]:
    names: Set[str] = set()
    for node in ast.walk(tree(path)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.alias):
            names.add((node.asname or node.name).split(".")[0])
    return names


# ---------------------------------------------------------------------------
# A small standard-library HTML inspector
# ---------------------------------------------------------------------------

@dataclass
class Element:
    """One element, with the attributes and text a check might ask about."""

    tag: str
    attrs: Dict[str, str]
    text: str = ""
    depth: int = 0


#: Elements with no end tag. ``html.parser`` reports these through
#: ``handle_starttag`` unless the source writes them as ``<br/>``, so an
#: inspector that pushed them onto an open-element stack would never pop them
#: - and every depth after the first ``<meta>`` would be wrong.
VOID_ELEMENTS = frozenset({
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr"})

#: Elements whose text belongs to their ancestor for accessibility purposes.
#: ``<h3><code>DRUG:x</code></h3>`` has an accessible name; attributing the
#: text only to the ``<code>`` would make the heading look empty.
_TEXT_BEARING_ANCESTORS = frozenset({
    "h1", "h2", "h3", "h4", "h5", "h6", "a", "caption", "th", "label",
    "legend", "button"})


class HtmlInspector(HTMLParser):
    """Parse a page into the handful of shapes the checks care about.

    Deliberately shallow: it records elements, their attributes, their text
    and the document order. It builds no tree, because none of these
    assertions need one and a hand-built tree would be a second thing to get
    right.

    Two subtleties it does handle, because getting either wrong makes the
    accessibility assertions quietly meaningless: void elements never enter
    the open-element stack, and text is accumulated into every open ancestor
    that can bear a name rather than only into the innermost element.
    """

    def __init__(self, html: str) -> None:
        super().__init__(convert_charrefs=True)
        self.elements: List[Element] = []
        self.headings: List[Tuple[str, str]] = []
        self.landmarks: List[str] = []
        self.links: List[Tuple[str, str]] = []
        self.tables: List[Dict[str, Any]] = []
        self.form_controls: List[Element] = []
        self.labels: List[Element] = []
        self.text_parts: List[str] = []
        self._open: List[Element] = []
        self._current_table: Optional[Dict[str, Any]] = None
        self.feed(html)
        self.close()

    # -- parsing -------------------------------------------------------

    def handle_starttag(self, tag: str, attrs) -> None:
        lowered = tag.lower()
        element = Element(tag=lowered,
                          attrs={(name or "").lower(): (value or "")
                                 for name, value in attrs},
                          depth=len(self._open))
        self.elements.append(element)
        if lowered not in VOID_ELEMENTS:
            self._open.append(element)

        if element.tag in ("header", "nav", "main", "footer", "aside"):
            self.landmarks.append(element.tag)
        if element.tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.headings.append((element.tag, ""))
        if element.tag == "a":
            self.links.append((element.attrs.get("href", ""), ""))
        if element.tag in ("input", "select", "textarea", "button"):
            self.form_controls.append(element)
        if element.tag == "label":
            self.labels.append(element)
        if element.tag == "table":
            self._current_table = {"caption": None, "headers": [],
                                   "scopes": [], "element": element}
            self.tables.append(self._current_table)

    def handle_startendtag(self, tag: str, attrs) -> None:
        lowered = tag.lower()
        self.handle_starttag(tag, attrs)
        if lowered not in VOID_ELEMENTS and self._open:
            self._open.pop()

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in VOID_ELEMENTS:
            return
        if lowered == "table":
            self._current_table = None
        # Pop back to the matching element rather than blindly popping one:
        # a stray end tag would otherwise unbalance every depth after it.
        for index in range(len(self._open) - 1, -1, -1):
            if self._open[index].tag == lowered:
                closed = self._open[index]
                del self._open[index:]
                self._finish(closed)
                return

    def _finish(self, element: Element) -> None:
        """Record what an element turned out to contain, once it closes."""
        text = element.text.strip()
        if element.tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            for index, (tag, existing) in enumerate(self.headings):
                if tag == element.tag and not existing:
                    self.headings[index] = (tag, text)
                    break
        elif element.tag == "a":
            for index, (href, existing) in enumerate(self.links):
                if href == element.attrs.get("href", "") and not existing:
                    self.links[index] = (href, text)
                    break
        elif element.tag == "caption" and self._current_table is not None:
            self._current_table["caption"] = text
        elif element.tag == "th" and self._current_table is not None:
            self._current_table["headers"].append(text)
            self._current_table["scopes"].append(element.attrs.get("scope"))

    def handle_data(self, data: str) -> None:
        if not self._open:
            return
        self.text_parts.append(data)
        # Into every open ancestor that can carry an accessible name, not only
        # the innermost element: <h3><code>x</code></h3> names the heading.
        for element in self._open:
            if element is self._open[-1] or \
                    element.tag in _TEXT_BEARING_ANCESTORS:
                element.text += data

    # -- queries -------------------------------------------------------

    def find(self, tag: str, **attrs: str) -> List[Element]:
        found = [item for item in self.elements if item.tag == tag]
        for name, value in attrs.items():
            found = [item for item in found
                     if item.attrs.get(name.replace("_", "-")) == value]
        return found

    def has(self, tag: str, **attrs: str) -> bool:
        return bool(self.find(tag, **attrs))

    @property
    def visible_text(self) -> str:
        return " ".join(part.strip() for part in self.text_parts
                        if part.strip())

    @property
    def heading_levels(self) -> List[int]:
        return [int(tag[1]) for tag, _text in self.headings]

    def heading_texts(self, level: int) -> List[str]:
        return [text for tag, text in self.headings
                if tag == "h%d" % level]


def inspect(html: str) -> HtmlInspector:
    return HtmlInspector(html)


def synthetic_world(**kwargs: Any):
    """The WP-14 synthetic world, imported lazily."""
    from tests.unit.application._assessment_support import (
        SyntheticAssessmentWorld)
    return SyntheticAssessmentWorld(**kwargs)
