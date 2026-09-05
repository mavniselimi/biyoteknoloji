"""Proof that presentation lost nothing.

The assessment page is the one screen where dropping a value would be both
easy and invisible: a template that forgets a reason code renders a complete-
looking page, and the missing code is the explanation of why part of the
question went unanswered.

So the check is mechanical. :func:`response_facts` projects the protected
facts out of the WP-16 response; :func:`view_model_facts` projects the same
shape out of the built view model; :func:`require_preserved` compares them and
refuses if they differ. The projection is deliberately dumb - sorted, fully
enumerated, no summarising - because a clever projection is one that can agree
with a view model for the wrong reason.

**What "protected" covers.** Identity and hashes; the overall status pair with
every reason code; every medication with its own status pair, axis counts,
axes and findings; every axis's coverage, reason codes, observed phenotype,
evidence references and conflict references; every finding's rule identity,
version, hash, rationale reference, curation identity, effect and explanation
codes, and evidence references; every observation; and the complete release
provenance.

**What it deliberately excludes.** Labels, URLs, headings and accessibility
text - everything the view model is *allowed* to add. Including them would
make the check assert that presentation exists rather than that facts survive.

This runs on every assessment page, not only in tests. A test proves the check
works on the cases somebody thought of; running it in production is what
catches the case nobody did.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Sequence, Tuple

__all__ = [
    "FactPreservationError",
    "PROTECTED_ASSESSMENT_FACTS",
    "require_preserved",
    "response_facts",
    "view_model_facts",
]


class FactPreservationError(Exception):
    """A view model does not carry every fact its response carried.

    Names the differing paths and never the values: the values are governed
    facts about a case, and a refusal record holding them puts case content
    into a log.
    """

    def __init__(self, differences: Sequence[str]) -> None:
        self.differences = tuple(differences)
        super().__init__(
            "the presentation model differs from the response at %d "
            "location(s): %s"
            % (len(self.differences), ", ".join(self.differences[:12])))


#: The top-level keys the projection covers. Listed so a reader can see the
#: scope without reading the projection, and asserted against the projection
#: by the test suite so the list cannot drift from what is checked.
PROTECTED_ASSESSMENT_FACTS: Tuple[str, ...] = (
    "assessment_id", "mode", "input_kind", "case_id",
    "input_hash", "output_hash", "coverage_result_hash", "persisted",
    "status", "medications", "observations", "release", "warnings",
)


def _status(status: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "attention": status.get("attention"),
        "coverage": status.get("coverage"),
        # A list, not a set: the order is the engine's and a page that
        # reordered them would be presenting a different explanation.
        "reason_codes": list(status.get("coverage_reason_codes") or ()),
    }


def _axis(axis: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "gene": axis.get("gene"),
        "drug": axis.get("drug"),
        "coverage": axis.get("coverage"),
        "reason_codes": list(axis.get("coverage_reason_codes") or ()),
        "observed_phenotype": axis.get("observed_phenotype"),
        "observation_state": axis.get("observation_state"),
        "declaration_id": axis.get("declaration_id"),
        "evidence_references": list(axis.get("evidence_references") or ()),
        "conflict_references": list(axis.get("conflict_references") or ()),
    }


def _finding(finding: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "gene": finding.get("gene"),
        "drug": finding.get("drug"),
        "phenotype": finding.get("phenotype"),
        "attention": finding.get("attention"),
        "rule_id": finding.get("rule_id"),
        "rule_family_id": finding.get("rule_family_id"),
        "rule_version": finding.get("rule_version"),
        "rule_content_hash": finding.get("rule_content_hash"),
        "rationale_reference": finding.get("rationale_reference"),
        "curation_revision_id": finding.get("curation_revision_id"),
        "curation_revision_hash": finding.get("curation_revision_hash"),
        # Kept as ``None`` rather than normalised away. A governed outcome
        # that carries no effect code carries no effect code, and a
        # projection that turned that into an empty string would let a view
        # model invent one without the check noticing.
        "effect_code": finding.get("effect_code"),
        "explanation_code": finding.get("explanation_code"),
        "evidence_references": list(finding.get("evidence_references") or ()),
    }


def _medication(medication: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "drug": medication.get("drug"),
        "requested_value": medication.get("requested_value"),
        "status": _status(medication.get("status") or {}),
        "axis_count": medication.get("axis_count"),
        "conflicted_axis_count": medication.get("conflicted_axis_count"),
        "axes": [_axis(item) for item in medication.get("axes") or ()],
        "findings": [_finding(item)
                     for item in medication.get("findings") or ()],
    }


def _observation(observation: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "gene": observation.get("gene"),
        "status": observation.get("status"),
        "phenotype": observation.get("phenotype"),
        "reason_code": observation.get("reason_code"),
    }


def response_facts(document: Mapping[str, Any]) -> Dict[str, Any]:
    """The protected facts, projected out of a WP-16 assessment response."""
    return {
        "assessment_id": document.get("assessment_id"),
        "mode": document.get("mode"),
        "input_kind": document.get("input_kind"),
        "case_id": document.get("case_id"),
        "input_hash": document.get("input_hash"),
        "output_hash": document.get("output_hash"),
        "coverage_result_hash": document.get("coverage_result_hash"),
        "persisted": document.get("persisted"),
        "status": _status(document.get("status") or {}),
        # Medication order is the engine's canonical order. Not sorted here:
        # sorting would make a view model that reordered them still match.
        "medications": [_medication(item)
                        for item in document.get("medications") or ()],
        "observations": [_observation(item)
                         for item in document.get("observations") or ()],
        "release": dict(document.get("release") or {}),
        "warnings": list(document.get("warnings") or ()),
    }


def view_model_facts(model: Any) -> Dict[str, Any]:
    """The same projection, out of the built view model.

    The view model exposes ``fact_projection()`` rather than being introspected
    here. That keeps the two sides independent: this module does not know how
    the model is laid out, so a layout change cannot accidentally make the
    comparison trivial.
    """
    projection = model.fact_projection()
    if not isinstance(projection, Mapping):  # pragma: no cover - defensive
        raise FactPreservationError(("$",))
    return dict(projection)


def _compare(left: Any, right: Any, path: str,
             differences: List[str]) -> None:
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        for key in sorted(set(left) | set(right)):
            if key not in left or key not in right:
                differences.append("%s.%s" % (path, key))
            else:
                _compare(left[key], right[key], "%s.%s" % (path, key),
                         differences)
    elif isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            differences.append("%s[length]" % path)
            return
        for index, (one, two) in enumerate(zip(left, right)):
            _compare(one, two, "%s[%d]" % (path, index), differences)
    elif left != right:
        differences.append(path)


def require_preserved(document: Mapping[str, Any], model: Any) -> None:
    """Refuse to render a view model that does not carry the response's facts.

    Raises:
        FactPreservationError: the projections differ. The page is not
            rendered: a page missing a governed fact looks complete, and a
            reader has no way to tell that something was dropped.
    """
    differences: List[str] = []
    _compare(response_facts(document), view_model_facts(model), "$",
             differences)
    if differences:
        raise FactPreservationError(differences)
