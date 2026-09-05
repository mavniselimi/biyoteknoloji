# -*- coding: utf-8 -*-
"""Turning raw bytes into records, without interpreting them (WP-04).

Standard library only.

**Order matters and is not negotiable.** Bytes are hashed and stored *before*
anything tries to parse them. A body that turns out to be corrupt JSON is still
preserved with its digest, so a failed run can be diagnosed and replayed rather
than merely reported.

**A record is passed through untouched.** This module extracts the record list
from the declared container and hands the objects on exactly as the source sent
them. It renames no field, normalises no term, drops no unknown key and invents
no missing one. Every one of those would be a scientific judgement, and WP-04
makes none.

Contrast with the legacy ``flatten_items``, which tried ``data``, ``items``,
``results``, ``content``, ``objects`` and ``resources`` in turn and, failing all
six, wrapped the whole payload in a list. A response of the wrong shape - an
error object, an HTML page decoded as JSON - therefore became "one record" and
the probe reported success. Here the shape is **declared per endpoint** and
checked, and a mismatch is a failure.
"""

from __future__ import annotations

import json
from typing import Any, Mapping, Sequence, Tuple

from pgx.ingestion.common.errors import (
    ContentTypeError, ResponseShapeError, ResponseValidationError,
)
from pgx.ingestion.common.models import HttpResponse
from pgx.ingestion.clinpgx.catalog import EndpointDeclaration, ResponseShape

__all__ = ["extract_records", "parse_json_body", "validate_content_type"]


def validate_content_type(response: HttpResponse, expected: str) -> None:
    """Raise unless the response is the media type the endpoint declared.

    A JSON endpoint answering ``text/html`` is almost always an error page or a
    captive portal. Parsing it anyway and finding no records would look like an
    empty result, which is the one interpretation guaranteed to be wrong.
    """
    actual = response.content_type
    if not actual:
        raise ContentTypeError(
            "response carries no Content-Type; %r was expected" % expected)
    if actual != expected.split(";")[0].strip().lower():
        raise ContentTypeError(
            "expected content type %r, got %r. A response of the wrong media "
            "type is an error to report, not an empty result."
            % (expected, actual))


def parse_json_body(response: HttpResponse) -> Any:
    """Decode and parse the body, or raise a precise error.

    Both failure modes are named separately, because they have different
    causes: an undecodable body usually means a wrong content type or a
    truncated transfer, while a decodable body that is not JSON usually means an
    error page.
    """
    if not response.body:
        raise ResponseValidationError(
            "response body is empty; an endpoint that returns nothing at all "
            "cannot be distinguished from one that returned no records, so it "
            "is reported as a failure")
    try:
        text = response.body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ResponseValidationError(
            "response body is not valid UTF-8 (%s). The raw bytes are still "
            "preserved with their digest." % exc) from exc
    try:
        return json.loads(text)
    except ValueError as exc:
        raise ResponseValidationError(
            "response body is not valid JSON: %s. The raw bytes are still "
            "preserved with their digest, so the run can be diagnosed and "
            "replayed." % exc) from exc


def extract_records(payload: Any,
                    endpoint: EndpointDeclaration) -> Tuple[Any, ...]:
    """Return the records from a parsed payload, per the endpoint's declaration.

    The container is the one the endpoint declares. No fallback chain, no
    wrapping the payload when nothing matches: an unexpected shape raises
    :class:`ResponseShapeError`, so it can never be mistaken for data.
    """
    if endpoint.shape is ResponseShape.BARE_LIST:
        if not isinstance(payload, list):
            raise ResponseShapeError(
                "endpoint %r declares a bare JSON array; got %s"
                % (endpoint.endpoint_id, type(payload).__name__))
        return tuple(payload)

    if not isinstance(payload, Mapping):
        raise ResponseShapeError(
            "endpoint %r declares a JSON object at the top level; got %s"
            % (endpoint.endpoint_id, type(payload).__name__))

    node: Any = payload
    for part in endpoint.records_path:
        if not isinstance(node, Mapping) or part not in node:
            raise ResponseShapeError(
                "endpoint %r declares records at %r, which is missing from the "
                "response. This is reported rather than guessed: the legacy "
                "probe tried six container keys and wrapped the whole payload "
                "when none matched, so a wrong response became one record."
                % (endpoint.endpoint_id, ".".join(endpoint.records_path)))
        node = node[part]

    if endpoint.shape is ResponseShape.SINGLE_OBJECT:
        if isinstance(node, list):
            raise ResponseShapeError(
                "endpoint %r declares a single object; got a list of %d"
                % (endpoint.endpoint_id, len(node)))
        return (node,)

    if node is None:
        raise ResponseShapeError(
            "endpoint %r returned null at %r; null is not an empty list"
            % (endpoint.endpoint_id, ".".join(endpoint.records_path)))
    if not isinstance(node, list):
        raise ResponseShapeError(
            "endpoint %r declares a list at %r; got %s"
            % (endpoint.endpoint_id, ".".join(endpoint.records_path),
               type(node).__name__))
    # Records are handed on exactly as received. No renaming, no normalisation,
    # no dropping of unknown fields, no filling of missing ones.
    return tuple(node)
