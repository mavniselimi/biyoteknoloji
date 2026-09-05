"""Deterministic, release-bound pagination for the read-only catalogues.

A cursor here is not an offset. It carries the release and dataset it was
produced against, and the last key it stopped at, and it is refused against
any other release.

That refusal is the reason this module exists rather than a page number. A
catalogue page describes what one governed release covers. If a client fetched
page one against release A, a release was activated, and page two came back
from release B, the client would hold one list assembled from two coverage
manifests with nothing marking the seam - and would reasonably read it as a
single answer about a single release. Refusing the stale cursor turns that
into a visible error the client can act on, at the cost of one retry.

Keys, not offsets, for the ordering itself: an offset shifts when the
underlying collection changes, so an item can be skipped or repeated between
pages. Ordering by canonical key and resuming *after* the last key returned
means every item appears exactly once for any collection that has not changed,
and for one that has, an item is never silently skipped.
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from apps.api.contracts.spec import LIMITS
from apps.api.errors import ApiError, RequestContractError

__all__ = [
    "CURSOR_VERSION",
    "Cursor",
    "CursorReleaseMismatch",
    "Page",
    "decode_cursor",
    "encode_cursor",
    "paginate",
]

CURSOR_VERSION = "pgx-catalogue-cursor/1"


class CursorReleaseMismatch(ApiError):
    """A cursor was made against a different release than the one in force."""


@dataclass(frozen=True, slots=True)
class Cursor:
    """Where a listing stopped, and which release it was listing."""

    collection: str
    release_public_id: str
    dataset_public_id: str
    coverage_manifest_hash: str
    after_key: str
    cursor_version: str = CURSOR_VERSION

    def binds_to(self, context: Mapping[str, Any]) -> bool:
        """Whether this cursor describes the release now in force."""
        return (self.release_public_id == context.get("release_public_id")
                and self.dataset_public_id == context.get("dataset_public_id")
                and self.coverage_manifest_hash
                == context.get("coverage_manifest_hash"))


@dataclass(frozen=True, slots=True)
class Page:
    """One page of a catalogue, and how to ask for the next."""

    items: Tuple[Any, ...]
    page_size: int
    total: int
    next_cursor: Optional[str]

    def page_info(self) -> Dict[str, Any]:
        return {"page_size": self.page_size, "returned": len(self.items),
                "total": self.total, "next_cursor": self.next_cursor}


def encode_cursor(cursor: Cursor) -> str:
    """Serialise a cursor as one URL-safe token.

    Base64url of canonical JSON: opaque enough that a client does not build
    one by hand, and not encrypted, because there is nothing secret in it -
    every field is a public identity the same client can read off the response
    it came from. Pretending otherwise by encrypting it would only make a
    failure harder to diagnose.
    """
    document = {
        "cursor_version": cursor.cursor_version,
        "collection": cursor.collection,
        "release_public_id": cursor.release_public_id,
        "dataset_public_id": cursor.dataset_public_id,
        "coverage_manifest_hash": cursor.coverage_manifest_hash,
        "after_key": cursor.after_key,
    }
    raw = json.dumps(document, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=True).encode("utf-8")
    token = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    if len(token) > LIMITS["max_cursor_length"]:  # pragma: no cover - defensive
        raise RequestContractError(
            "REQUEST_CONTRACT_VIOLATION",
            details={"issues": [{"location": "$.cursor",
                                 "code": "VALUE_TOO_LONG"}]})
    return token


def decode_cursor(token: str, *, collection: str,
                  context: Mapping[str, Any]) -> Cursor:
    """Read a cursor token, or refuse it.

    Raises:
        RequestContractError: the token is not a cursor this API produced, or
            names a different collection. Malformed input is a client error
            and the rejected token is not echoed back.
        CursorReleaseMismatch: the token is well formed and was produced
            against a different release, dataset or coverage manifest. Its own
            code, and a 409 rather than a 400, because the client did nothing
            wrong: the release moved underneath them, and the remedy is to
            start the listing again rather than to fix the request.
    """
    if not isinstance(token, str) or not token or \
            len(token) > LIMITS["max_cursor_length"]:
        raise RequestContractError(
            "REQUEST_CONTRACT_VIOLATION",
            details={"issues": [{"location": "$.cursor",
                                 "code": "PATTERN_MISMATCH"}]})
    padding = "=" * (-len(token) % 4)
    try:
        raw = base64.urlsafe_b64decode(token + padding)
        document = json.loads(raw.decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, ValueError):
        raise RequestContractError(
            "REQUEST_CONTRACT_VIOLATION",
            details={"issues": [{"location": "$.cursor",
                                 "code": "PATTERN_MISMATCH"}]}) from None
    if not isinstance(document, dict) or \
            document.get("cursor_version") != CURSOR_VERSION or \
            document.get("collection") != collection or \
            not isinstance(document.get("after_key"), str):
        raise RequestContractError(
            "REQUEST_CONTRACT_VIOLATION",
            details={"issues": [{"location": "$.cursor",
                                 "code": "PATTERN_MISMATCH"}]})

    cursor = Cursor(
        collection=collection,
        release_public_id=str(document.get("release_public_id") or ""),
        dataset_public_id=str(document.get("dataset_public_id") or ""),
        coverage_manifest_hash=str(
            document.get("coverage_manifest_hash") or ""),
        after_key=document["after_key"])
    if not cursor.binds_to(context):
        raise CursorReleaseMismatch(
            "CURSOR_RELEASE_MISMATCH",
            details={"issues": [{"location": "$.cursor",
                                 "code": "RELEASE_CHANGED"}]})
    return cursor


def paginate(keys: Sequence[str], *, collection: str,
             context: Mapping[str, Any], page_size: Optional[int] = None,
             cursor_token: Optional[str] = None) -> Page:
    """One deterministic page of an ordered key sequence.

    Args:
        keys: every key in the collection, already sorted. Sorting is the
            caller's because the caller knows the canonical order; this
            asserts it rather than re-imposing one, so a collection that
            arrives unsorted fails here instead of paginating incoherently.
        collection: the catalogue's name, recorded in the cursor so a drugs
            cursor cannot be replayed against genes.
        context: the pinned release identity the cursor binds to.
        page_size: bounded by the contract's ``max_page_size``. A request for
            more is refused rather than silently reduced: a client that asked
            for 5000 and received 100 without being told has no way to know
            its list is incomplete.
        cursor_token: where to resume, or ``None`` for the first page.

    Raises:
        RequestContractError: the page size is outside its bounds, or the
            cursor is malformed.
        CursorReleaseMismatch: the cursor was made against another release.
    """
    ordered = list(keys)
    if ordered != sorted(ordered):  # pragma: no cover - defensive
        raise ValueError(
            "a catalogue is paginated in canonical key order; this one "
            "arrived unsorted, and paginating it would return items twice")

    size = LIMITS["default_page_size"] if page_size is None else int(page_size)
    if size < 1 or size > LIMITS["max_page_size"]:
        raise RequestContractError(
            "REQUEST_CONTRACT_VIOLATION",
            details={"issues": [{"location": "$.page_size",
                                 "code": "OUT_OF_RANGE"}],
                     "limit": LIMITS["max_page_size"]})

    start = 0
    if cursor_token is not None:
        cursor = decode_cursor(cursor_token, collection=collection,
                               context=context)
        # Resume strictly after the last key returned. Bisection rather than
        # an index lookup, so a key that has since disappeared from the
        # collection resumes at the right place instead of restarting.
        import bisect
        start = bisect.bisect_right(ordered, cursor.after_key)

    window = tuple(ordered[start:start + size])
    exhausted = start + size >= len(ordered)
    next_cursor = None
    if window and not exhausted:
        next_cursor = encode_cursor(Cursor(
            collection=collection,
            release_public_id=str(context.get("release_public_id") or ""),
            dataset_public_id=str(context.get("dataset_public_id") or ""),
            coverage_manifest_hash=str(
                context.get("coverage_manifest_hash") or ""),
            after_key=window[-1]))
    return Page(items=window, page_size=size, total=len(ordered),
                next_cursor=next_cursor)
