"""The page frame every screen shares.

:class:`PageContext` carries what is on every page regardless of what the page
is about: the canonical warning, the navigation, the environment, the request
id and the locale.

**The warning is fetched, never stored.** :attr:`PageContext.warning` calls
:func:`pgx.domain.claims.canonical_clinical_warning` at build time. No template
contains the text, no route may supply one, and there is no parameter through
which a caller could substitute a shorter version. A page built without a
context has no warning and therefore does not render: the base template reads
it unconditionally, and the environment uses ``StrictUndefined``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from apps.web import DEFAULT_LOCALE, WEB_VERSION
from apps.web.claim_gate import check_display_value
from apps.web.labels import ui
from apps.web.routes import NAVIGATION, WebRoute, web_route
from pgx.domain.claims import canonical_clinical_warning

__all__ = [
    "NavigationItem",
    "PageContext",
    "StatusPair",
    "display",
]


def display(value: Any, *, location: str, allow_none: bool = True) -> str:
    """One value on its way to a template: checked, never coerced silently.

    ``None`` becomes the empty string only when the caller says it may.
    Elsewhere a ``None`` reaching a template is a missing governed fact, and
    rendering it as blank is how an absent code becomes an absent problem.
    """
    if value is None:
        if allow_none:
            return ""
        raise ValueError("a required display value is missing at %s" % location)
    return check_display_value(str(value), location=location)


@dataclass(frozen=True, slots=True)
class NavigationItem:
    """One navigation entry, with whether it is the page being shown."""

    name: str
    url: str
    text: str
    is_current: bool


@dataclass(frozen=True, slots=True)
class StatusPair:
    """Attention and coverage, in one object, at every level.

    This type exists so that "display attention without coverage" is not
    something a template can express. There is no attention-only view model
    anywhere in this package: a medication has a :class:`StatusPair`, an
    assessment has a :class:`StatusPair`, and each carries both codes, both
    labels and the reason codes together.

    Both the governed code and its label are kept. The code is what a reader
    can search, cite and compare with an API response; the label is what makes
    it readable. Showing only the label would hide the vocabulary; showing
    only the code would be a token nobody wrote a meaning for.
    """

    attention_code: str
    attention_label: str
    coverage_code: str
    coverage_label: str
    reason_codes: Tuple[str, ...]
    reason_labels: Tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.attention_code or not self.coverage_code:
            raise ValueError(
                "a status pair carries both an attention code and a coverage "
                "code; neither is ever displayed without the other")
        if len(self.reason_codes) != len(self.reason_labels):
            raise ValueError("every reason code carries its label")

    @property
    def is_not_assessed(self) -> bool:
        """Whether this reads as *not assessed*, for layout emphasis only.

        Used to choose a heading modifier, never to change wording: the label
        comes from the governed table either way. Notably this is *not* used
        to pick a colour on its own - see the stylesheet, where every status
        carries a text label and a pattern as well as a hue.
        """
        return self.attention_code == "NOT_ASSESSED"

    @property
    def is_partial(self) -> bool:
        return self.coverage_code in ("PARTIAL", "INSUFFICIENT")

    @property
    def is_conflicted(self) -> bool:
        return self.coverage_code == "SOURCE_CONFLICT"

    def to_json(self) -> Dict[str, Any]:
        return {
            "attention_code": self.attention_code,
            "attention_label": self.attention_label,
            "coverage_code": self.coverage_code,
            "coverage_label": self.coverage_label,
            "reason_codes": list(self.reason_codes),
            "reason_labels": list(self.reason_labels),
        }


def build_status_pair(status: Mapping[str, Any], locale: str) -> StatusPair:
    """Build the pair from a WP-16 ``status`` object, losing nothing.

    Every reason code in the response appears in the pair, in the order the
    response gave. They are not sorted, deduplicated or filtered: the order is
    the engine's and the set is the engine's.
    """
    from apps.web.labels import (attention_label, coverage_label,
                                 coverage_reason_label)

    codes = tuple(str(code) for code in status.get("coverage_reason_codes")
                  or ())
    return StatusPair(
        attention_code=str(status.get("attention") or ""),
        attention_label=attention_label(str(status.get("attention") or ""),
                                        locale),
        coverage_code=str(status.get("coverage") or ""),
        coverage_label=coverage_label(str(status.get("coverage") or ""),
                                      locale),
        reason_codes=codes,
        reason_labels=tuple(coverage_reason_label(code, locale)
                            for code in codes))


@dataclass(frozen=True, slots=True)
class PageContext:
    """Everything every page carries."""

    locale: str
    title: str
    route_name: str
    environment: str
    warning: str
    warning_heading: str
    navigation: Tuple[NavigationItem, ...]
    request_id: str
    asset_version: str
    dependency_notice: Optional[str] = None
    web_version: str = WEB_VERSION

    def __post_init__(self) -> None:
        if not self.warning:
            raise ValueError(
                "no page renders without the canonical warning")
        if self.warning != canonical_clinical_warning(self.locale):
            raise ValueError(
                "a page's warning is the canonical one, verbatim; a route "
                "cannot supply its own")

    def to_json(self) -> Dict[str, Any]:
        return {
            "locale": self.locale,
            "title": self.title,
            "route_name": self.route_name,
            "environment": self.environment,
            "request_id": self.request_id,
            "web_version": self.web_version,
            "navigation": [item.name for item in self.navigation],
            "dependency_notice": self.dependency_notice,
        }


def build_page_context(*, route_name: str, locale: str = DEFAULT_LOCALE,
                       environment: str = "", request_id: str = "",
                       asset_version: str = "1",
                       dependency_notice: Optional[str] = None
                       ) -> PageContext:
    """Assemble the frame for one page.

    The warning comes from the canonical function on every call. Not cached,
    not passed in, not defaulted: a cached copy is a copy that survives a
    change to the governed text, and the whole reason this is one function is
    so that changing the warning changes every screen at once.
    """
    route = web_route(route_name)
    items = []
    for name in NAVIGATION:
        entry = web_route(name)
        items.append(NavigationItem(
            name=name,
            url=entry.url(),
            text=ui(entry.nav_key or entry.title_key, locale),
            is_current=(name == route_name)))
    return PageContext(
        locale=locale,
        title=ui(route.title_key, locale),
        route_name=route_name,
        environment=display(environment, location="$.environment"),
        warning=canonical_clinical_warning(locale),
        warning_heading=ui("app.warning_heading", locale),
        navigation=tuple(items),
        request_id=display(request_id, location="$.request_id"),
        asset_version=display(asset_version, location="$.asset_version"),
        dependency_notice=dependency_notice)
