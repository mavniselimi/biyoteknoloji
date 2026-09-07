#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WP-C14B intake - import one real external expert response.

Run with no arguments it writes the empty register and matrix, which is what
this repository holds today. Run with ``--response`` it imports a real one, or
refuses and writes nothing.

It cannot be used to invent a review. The refusals in
:func:`pgx.closure.wp_c14b.refusals_for` reject the blank template, any
response with a field still HUMAN_REQUIRED, an unsigned one, an unidentified
one and an empty one; and every feedback item is derived from verbatim
reviewer text, so there is no path that produces an item nobody wrote.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from pgx.closure.wp_c14b import (correction_impact_matrix,  # noqa: E402
                                 empty_matrix, empty_register,
                                 extract_feedback_items, preserved_response,
                                 refusals_for)

OUT = os.path.join(REPO, "data", "closure", "wp-c14b")
EMPTY_REASON = (
    "No external expert response exists. WP-C12 is a human step and this "
    "repository may not author it. These files are the machinery and its "
    "vocabulary, ready and empty.")

_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,39}$")


def _write(relative: str, payload: object) -> str:
    path = os.path.join(REPO, *relative.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True,
                                ensure_ascii=False) + "\n")
    return relative


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--response", default=None,
                        help="path to a completed reviewer response JSON")
    parser.add_argument("--reviewer-slug", default=None,
                        help="short lowercase identifier for the reviewer")
    args = parser.parse_args(argv)

    if args.response is None:
        _write("data/closure/wp-c14b/feedback-register.json",
               empty_register(reason=EMPTY_REASON))
        _write("data/closure/wp-c14b/correction-impact-matrix.json",
               empty_matrix(reason=EMPTY_REASON))
        print("  feedback items          0")
        print("  state                   "
              "AWAITING_GENUINE_EXTERNAL_EXPERT_RESPONSE")
        print("  reason                  no external expert response exists")
        return 0

    if not args.reviewer_slug or not _SLUG.match(args.reviewer_slug):
        sys.stderr.write("--reviewer-slug must be 2-40 lowercase characters, "
                         "digits or hyphens\n")
        return 2
    if not os.path.isfile(args.response):
        sys.stderr.write("no such response file: %s\n" % args.response)
        return 2

    with io.open(args.response, "rb") as handle:
        raw = handle.read()
    try:
        response = json.loads(raw.decode("utf-8"))
    except Exception as error:  # noqa: BLE001
        sys.stderr.write("the response is not readable JSON: %s\n" % error)
        return 2

    problems = refusals_for(response)
    if problems:
        sys.stderr.write("refusing this response; nothing was written.\n")
        for code, detail in problems:
            sys.stderr.write("  %-36s %s\n" % (code, detail))
        return 3

    preserved_relative = ("data/expert-review/wp-c12-response-%s.json"
                          % args.reviewer_slug)
    path = os.path.join(REPO, *preserved_relative.split("/"))
    if os.path.exists(path):
        sys.stderr.write(
            "%s already exists. A preserved response is never overwritten; "
            "append a correction instead.\n" % preserved_relative)
        return 3
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "wb") as handle:
        handle.write(raw)

    record = preserved_response(raw, received_relative=preserved_relative,
                               reviewer_slug=args.reviewer_slug)
    items = extract_feedback_items(response,
                                   reviewer_slug=args.reviewer_slug)

    register = empty_register(reason="")
    register.pop("empty_because")
    register["state"] = "RESPONSE_RECEIVED_DISPOSITIONS_PENDING"
    register["item_count"] = len(items)
    register["items"] = list(items)
    register["preserved_responses"] = [record]
    register["reviewers"] = [{
        "slug": args.reviewer_slug,
        "name": (response.get("reviewer") or {}).get("name"),
        "professional_qualification":
            (response.get("reviewer") or {}).get("professional_qualification"),
        "identity_verification": "NONE_PERFORMED",
        "conflict_of_interest_declared": True,
    }]
    register["reviewed_release_public_id"] = \
        response.get("reviewed_release_public_id")
    register["reviewed_frozen_combined_hash"] = \
        response.get("reviewed_frozen_combined_hash")

    _write("data/closure/wp-c14b/feedback-register.json", register)
    _write("data/closure/wp-c14b/correction-impact-matrix.json",
           correction_impact_matrix(items))

    print("  preserved               %s" % preserved_relative)
    print("  sha256                  %s" % record["sha256"])
    print("  feedback items          %d" % len(items))
    print("  dispositions            all HUMAN_REQUIRED - decide them, with "
          "a written rationale each, before any correction is made")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
