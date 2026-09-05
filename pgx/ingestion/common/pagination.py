# -*- coding: utf-8 -*-
"""Declarative pagination strategies and their loop guards (WP-04).

Standard library only.

**Why this is not optional.** Neither legacy probe paged at all: each issued one
request and treated whatever came back as the answer. For an endpoint that
returns a page of results, that quietly collects an unknown fraction of the data
and reports success. This module makes "how does this endpoint paginate?" a
declared property of the endpoint, and makes "did we reach the end?" a question
with a real answer.

**Terminal means the source said stop.** :class:`PaginationState.terminal` is
``True`` only when the source signalled the end - an empty page, an absent next
cursor, or a declared last page. Exhausting the page budget is *not* terminal,
and neither is an error. That distinction is what stops a partially-collected
endpoint from being reported as complete.

**Four guards, each for a real failure:**

* ``max_pages`` and ``max_records`` bound the work.
* A repeated cursor or a repeated request key means the source is looping; each
  is detected rather than followed forever.
* An empty page terminates normally.
* A malformed or unresolvable next cursor is an error, not an end.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Mapping, Optional, Sequence, Tuple

from pgx.ingestion.common.errors import ConfigurationError, PaginationError

__all__ = [
    "DEFAULT_MAX_PAGES",
    "DEFAULT_MAX_RECORDS",
    "PageRequest",
    "PageResult",
    "PaginationSpec",
    "PaginationStrategy",
    "TerminationReason",
    "next_page_request",
    "read_next_cursor",
]

#: Bounds chosen to be generous for a real source and still finite. An
#: unbounded pager against a looping endpoint runs until something else breaks.
DEFAULT_MAX_PAGES = 200
DEFAULT_MAX_RECORDS = 200_000


class PaginationStrategy(str, Enum):
    """How an endpoint exposes more results.

    ``SINGLE_PAGE`` is a claim, not a default. Declaring it says "this endpoint
    returns everything at once", and the runner still verifies that the response
    carries no continuation signal - so an endpoint that silently starts paging
    is caught rather than half-read.
    """

    SINGLE_PAGE = "SINGLE_PAGE"
    PAGE_SIZE = "PAGE_SIZE"
    OFFSET_LIMIT = "OFFSET_LIMIT"
    CURSOR = "CURSOR"
    NEXT_LINK = "NEXT_LINK"


class TerminationReason(str, Enum):
    """Why pagination stopped. Only the first three mean "finished"."""

    SINGLE_PAGE = "SINGLE_PAGE"
    EMPTY_PAGE = "EMPTY_PAGE"
    NO_NEXT_CURSOR = "NO_NEXT_CURSOR"
    MAX_PAGES_REACHED = "MAX_PAGES_REACHED"
    MAX_RECORDS_REACHED = "MAX_RECORDS_REACHED"
    REPEATED_CURSOR = "REPEATED_CURSOR"
    REPEATED_REQUEST_KEY = "REPEATED_REQUEST_KEY"
    MALFORMED_CURSOR = "MALFORMED_CURSOR"
    ERROR = "ERROR"

    @property
    def is_terminal(self) -> bool:
        """True only when the *source* said there is nothing more.

        Running out of budget is not finishing, and neither is looping.
        """
        return self in (TerminationReason.SINGLE_PAGE,
                        TerminationReason.EMPTY_PAGE,
                        TerminationReason.NO_NEXT_CURSOR)


@dataclass(frozen=True)
class PageRequest:
    """The pagination parameters for one page."""

    page_number: int
    query: Tuple[Tuple[str, str], ...] = ()
    cursor: Optional[str] = None


@dataclass(frozen=True)
class PageResult:
    """What one page yielded."""

    records: Tuple[Any, ...]
    next_cursor: Optional[str] = None

    @property
    def is_empty(self) -> bool:
        """True when the page carried no records."""
        return not self.records


@dataclass(frozen=True)
class PaginationSpec:
    """An endpoint's declared pagination behaviour.

    Declarative on purpose: adding an endpoint should mean adding a
    declaration, never editing the runner. Parameter names are fields because
    they differ between APIs, and hard-coding one API's spelling is how a
    second source ends up needing a fork of the runner.
    """

    strategy: PaginationStrategy = PaginationStrategy.SINGLE_PAGE
    page_param: str = "page"
    size_param: str = "size"
    offset_param: str = "offset"
    limit_param: str = "limit"
    cursor_param: str = "cursor"
    page_size: int = 100
    first_page_number: int = 1
    next_cursor_path: Tuple[str, ...] = ()
    next_link_path: Tuple[str, ...] = ()
    max_pages: int = DEFAULT_MAX_PAGES
    max_records: int = DEFAULT_MAX_RECORDS

    def __post_init__(self) -> None:
        if self.page_size < 1:
            raise ConfigurationError("page_size must be at least 1")
        if self.max_pages < 1:
            raise ConfigurationError("max_pages must be at least 1")
        if self.max_records < 1:
            raise ConfigurationError("max_records must be at least 1")
        if (self.strategy is PaginationStrategy.CURSOR
                and not self.next_cursor_path):
            raise ConfigurationError(
                "a CURSOR endpoint must declare next_cursor_path; without it "
                "the runner cannot tell 'no more pages' from 'we did not look'")
        if (self.strategy is PaginationStrategy.NEXT_LINK
                and not self.next_link_path):
            raise ConfigurationError(
                "a NEXT_LINK endpoint must declare next_link_path")

    @property
    def paginates(self) -> bool:
        """True when this endpoint can return more than one page."""
        return self.strategy is not PaginationStrategy.SINGLE_PAGE

    def first_page(self) -> PageRequest:
        """Pagination parameters for the first page."""
        return next_page_request(self, page_number=self.first_page_number,
                                 cursor=None, records_seen=0)


def next_page_request(spec: PaginationSpec, page_number: int,
                      cursor: Optional[str],
                      records_seen: int) -> PageRequest:
    """Build the pagination query for one page of an endpoint."""
    if spec.strategy is PaginationStrategy.SINGLE_PAGE:
        return PageRequest(page_number=page_number, query=(), cursor=None)
    if spec.strategy is PaginationStrategy.PAGE_SIZE:
        return PageRequest(
            page_number=page_number,
            query=((spec.page_param, str(page_number)),
                   (spec.size_param, str(spec.page_size))))
    if spec.strategy is PaginationStrategy.OFFSET_LIMIT:
        return PageRequest(
            page_number=page_number,
            query=((spec.offset_param, str(records_seen)),
                   (spec.limit_param, str(spec.page_size))))
    if spec.strategy in (PaginationStrategy.CURSOR, PaginationStrategy.NEXT_LINK):
        query: Tuple[Tuple[str, str], ...] = ()
        if cursor:
            query = ((spec.cursor_param, str(cursor)),)
        if spec.strategy is PaginationStrategy.CURSOR:
            query = query + ((spec.limit_param, str(spec.page_size)),)
        return PageRequest(page_number=page_number, query=query, cursor=cursor)
    raise ConfigurationError(  # pragma: no cover - the enum is closed
        "unsupported pagination strategy %r" % (spec.strategy,))


def read_next_cursor(spec: PaginationSpec,
                     payload: Mapping[str, Any]) -> Optional[str]:
    """Read the continuation token from a parsed page, or ``None``.

    Raises :class:`PaginationError` when the field is present but unusable - a
    number, a list, an empty string. That is different from absent: absent means
    "no more pages", malformed means "we cannot tell", and conflating the two
    would let a broken response end an endpoint early and look complete.
    """
    path = (spec.next_cursor_path if spec.strategy is PaginationStrategy.CURSOR
            else spec.next_link_path)
    if not path:
        return None
    node: Any = payload
    for part in path:
        if not isinstance(node, Mapping) or part not in node:
            return None
        node = node[part]
    if node is None:
        return None
    if not isinstance(node, str):
        raise PaginationError(
            "next cursor at %s is a %s, not a string; the response cannot be "
            "followed and must not be treated as the last page"
            % (".".join(path), type(node).__name__))
    text = node.strip()
    if not text:
        raise PaginationError(
            "next cursor at %s is present but empty; that is not the same as "
            "absent, and it cannot be followed" % ".".join(path))
    return text
