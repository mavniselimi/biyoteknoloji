"""Turn a form submission into a WP-16 assessment request.

The narrowest module in the interface, because it is the only one that turns
operator input into an API call. What it accepts is a case identifier the
catalogue already knows and a list of canonical medication keys the pinned
release already published. Everything else in the request - the mode, the
input kind, the contract version, the observations - comes from the sealed
case, not from the browser.

**There is no free text anywhere in this path.** No patient field, no
narrative, no dose, no diagnosis, no genotype. Not because they are filtered
out, but because there is no parameter for them: the function takes a case and
a tuple of keys, and a field the form did not have cannot arrive.

**A medication that is not in the request contract's shape is refused here**
rather than sent and rejected. The operator gets a page; the API gets no
malformed call.

**Order is not preserved from the form.** Browsers submit checkbox values in
document order, which is canonical-key order, and the request contract
requires uniqueness. Sorting is applied anyway so a hand-built request cannot
express an ordering - a "first choice" would be a ranking, and a ranking of
medicines is what SAFETY-INV-005 forbids.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Mapping, Sequence, Tuple

from apps.web.errors import WebError

__all__ = ["build_assessment_request"]

#: The same pattern the WP-16 request contract enforces. Checked here so a
#: value that could not be accepted never becomes a request.
_DRUG_KEY = re.compile(r"^DRUG:[a-z0-9][a-z0-9\-.+_]{0,48}$")

#: P0 accepts synthetic phenotype profiles in demonstration mode. Both are
#: fixed here rather than offered as form fields: a browser that could choose
#: the operating mode could ask for a mode the claim boundary disables, and
#: the refusal would look like a bug rather than a boundary.
_MODE = "DEMO"
_INPUT_KIND = "SYNTHETIC_PHENOTYPE_PROFILE"


def build_assessment_request(case: Any, *, medications: Sequence[str],
                             max_medications: int = 32) -> Dict[str, Any]:
    """Build the request document for one development case.

    Args:
        case: a :class:`~apps.web.demo_cases.DevelopmentCase` from the sealed
            catalogue. Its observations are used verbatim.
        medications: the canonical keys the operator selected.
        max_medications: the contract's own bound, passed in so the form and
            the request agree on one number.

    Raises:
        WebError: no medication was selected, too many were, one is not a
            canonical key, or one was selected twice. Each is a
            ``REQUEST_CONTRACT_VIOLATION`` - the same code the API would
            return - so a reader sees one vocabulary whichever layer caught it.
    """
    selected = tuple(str(item) for item in medications)
    if not selected:
        raise WebError("REQUEST_CONTRACT_VIOLATION",
                       details={"issues": [{"location": "$.medications",
                                            "code": "TOO_FEW_ITEMS"}]})
    if len(selected) > max_medications:
        raise WebError("REQUEST_CONTRACT_VIOLATION",
                       details={"issues": [{"location": "$.medications",
                                            "code": "TOO_MANY_ITEMS"}],
                                "limit": max_medications})
    if len(set(selected)) != len(selected):
        raise WebError("REQUEST_CONTRACT_VIOLATION",
                       details={"issues": [{"location": "$.medications",
                                            "code": "DUPLICATE_ITEM"}]})
    for value in selected:
        if _DRUG_KEY.match(value) is None:
            raise WebError(
                "REQUEST_CONTRACT_VIOLATION",
                # The location, never the value: a rejected key is text the
                # browser supplied, and echoing it into a page is how a
                # refusal becomes a reflection.
                details={"issues": [{"location": "$.medications",
                                     "code": "PATTERN_MISMATCH"}]})

    return {
        "mode": _MODE,
        "input_kind": _INPUT_KIND,
        "case_id": case.case_id,
        "profile": {
            "input_contract_version": "pgx-phenotype-input/1",
            "profile_id": case.case_id,
            "observations": [item.to_json() for item in case.observations],
        },
        "medications": sorted(selected),
    }
