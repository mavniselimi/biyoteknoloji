"""One stored assessment as one response document.

Two callers reach this module and there is deliberately one builder behind
both. ``POST /assessments`` arrives with a freshly executed and persisted
result; ``GET /assessments/{id}`` arrives with a read model reconstructed from
rows. Work package §9 requires the two to return semantically identical
governed facts, and the way to guarantee that is not to write two serialisers
and test them against each other - it is to write one and give it two feeds.
:func:`build_assessment_document` is that one, and everything either entry
point does before calling it is assemble its arguments.

What the document must not lose is easier to state as a list, because every
item on it is a way a reader could be misled:

- **Attention and coverage travel together.** They are one ``status`` object,
  not two sibling keys, at every level - overall and per medication. No
  serialisation of this contract can carry one without the other
  (SAFETY-INV-001).
- **``NOT_ASSESSED`` survives verbatim.** It is never mapped to "no finding",
  never omitted because a medication has no findings, and never softened.
- **``SOURCE_CONFLICT`` survives verbatim**, with its axes and their conflict
  references. A conflict is preserved, never resolved and never presented as
  reassurance (SAFETY-INV-008).
- **Every reason code is preserved**, overall and per medication and per axis.
  Reason codes are the only thing that explains a partial answer.
- **Effect and explanation text are never invented.** The governed outcome
  carries ``effect_code`` and ``explanation_code`` that are presently
  ``None``; ``None`` is serialised as ``None``. Filling them with prose here
  would be this layer authoring a scientific claim.
- **The pinned release is reported, not the active one.** A release activated
  after an assessment was stored changes nothing about that assessment, and
  this module never reads the active pointer to find out what it is.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Dict, List, Mapping, Optional, Sequence

from apps.api import API_VERSION
from apps.api.contracts.spec import CONTRACT_VERSION
from apps.api.errors import ApiError
from pgx.application.assessment_snapshot import verify_input_snapshot
from pgx.domain.claims import canonical_clinical_warning
from pgx.domain.hashing import sha256_digest
from pgx.engine.risk import embedded_coverage_result, hashed_projection

__all__ = [
    "assessment_document_from_read_model",
    "assessment_document_from_result",
    "build_assessment_document",
]

#: The provenance fields a response reports, in the order the contract
#: declares them. ``active_pointer_generation`` is absent on purpose: it is
#: pointer audit metadata, excluded from the output hash by
#: :data:`pgx.engine.risk.POINTER_AUDIT_FIELDS`, and reporting it beside
#: hashed provenance would invite a reader to treat it as part of the pinned
#: identity. It is reported by ``GET /system/version``, where it describes the
#: pointer rather than the assessment.
_PROVENANCE_FIELDS = (
    "release_public_id", "release_manifest_hash", "software_version",
    "software_source_tree_hash", "dataset_public_id",
    "canonical_build_content_hash", "ruleset_public_id",
    "ruleset_content_hash", "evidence_build_key",
    "evidence_build_content_hash", "coverage_manifest_hash",
    "protocol_version", "protocol_content_hash", "source_policy_version",
    "source_policy_content_hash")

_FINDING_FIELDS = (
    ("gene", "gene_id"), ("drug", "drug_id"), ("phenotype", "phenotype"),
    ("attention", "attention_level"), ("rule_id", "rule_id"),
    ("rule_family_id", "rule_family_id"), ("rule_version", "rule_version"),
    ("rule_content_hash", "rule_content_hash"),
    ("rationale_reference", "rationale_reference"),
    ("curation_revision_id", "curation_revision_id"),
    ("curation_revision_hash", "curation_revision_hash"),
    ("effect_code", "effect_code"),
    ("explanation_code", "explanation_code"))

_AXIS_FIELDS = (
    ("gene", "gene_id"), ("drug", "drug_id"), ("coverage", "status"),
    ("coverage_reason_codes", "reason_codes"),
    ("observed_phenotype", "observed_phenotype"),
    ("observation_state", "observation_state"),
    ("declaration_id", "declaration_id"))


class _SerialisationRefused(ApiError):
    """Raised when a stored document does not agree with itself.

    Its own class so the mapper cannot confuse it with a caller error: this
    means the bytes on disk and the hashes beside them disagree, which is a
    server-side integrity failure and is answered as one.
    """


def _list(value: Any) -> List[Any]:
    return list(value or ())


def _isoformat(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, _dt.datetime):
        moment = (value if value.tzinfo is not None
                  else value.replace(tzinfo=_dt.timezone.utc))
        return moment.astimezone(_dt.timezone.utc).isoformat()
    return str(value)


def _status_block(attention: Any, coverage: Any,
                  reason_codes: Sequence[str]) -> Dict[str, Any]:
    """Attention and coverage, in one object, always both."""
    return {"attention": attention, "coverage": coverage,
            "coverage_reason_codes": _list(reason_codes)}


def _axes_by_drug(coverage_result: Mapping[str, Any]
                  ) -> Mapping[str, List[Mapping[str, Any]]]:
    index: Dict[str, List[Mapping[str, Any]]] = {}
    for medication in coverage_result.get("medications") or ():
        reference = medication.get("medication") or {}
        key = reference.get("drug_id") or reference.get("requested_value")
        index.setdefault(key, []).extend(medication.get("axes") or ())
    return index


def _axis_document(axis: Mapping[str, Any]) -> Dict[str, Any]:
    document = {name: axis.get(source) for name, source in _AXIS_FIELDS}
    document["coverage_reason_codes"] = _list(document["coverage_reason_codes"])
    # Evidence and conflicts are carried as identities, never as resolved
    # content: an old assessment's evidence stays auditable by the identity it
    # cited, and looking it up here would answer from whatever the current
    # build holds.
    document["evidence_references"] = _list(axis.get("evidence_references"))
    document["conflict_references"] = _list(axis.get("conflict_references"))
    return document


def _finding_document(finding: Mapping[str, Any]) -> Dict[str, Any]:
    document = {name: finding.get(source) for name, source in _FINDING_FIELDS}
    document["evidence_references"] = _list(finding.get("evidence_references"))
    return document


def _medication_document(medication: Mapping[str, Any],
                         axes: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    return {
        "drug": medication.get("drug_id"),
        "requested_value": medication.get("requested_value"),
        "status": _status_block(medication.get("attention_level"),
                                medication.get("coverage_status"),
                                medication.get("coverage_reason_codes") or ()),
        "axis_count": medication.get("axis_count"),
        "conflicted_axis_count": medication.get("conflicted_axis_count"),
        "axes": [_axis_document(axis) for axis in axes],
        "findings": [_finding_document(item)
                     for item in medication.get("findings") or ()],
    }


def _observation_documents(input_snapshot: Mapping[str, Any]
                           ) -> List[Dict[str, Any]]:
    """The recorded observations, without the caller's raw text.

    The snapshot stores four keys per observation and ``raw_value`` is not one
    of them, so there is nothing to strip here - but the omission is the point
    and is stated rather than left to be noticed: echoing a caller's supplied
    token back into a rendered response is how a stored string becomes an
    injection vector, and the governed status and reason code say everything a
    reader needs about a value that could not be interpreted.
    """
    profile = input_snapshot.get("profile") or {}
    documents = []
    for observation in profile.get("observations") or ():
        documents.append({
            "gene": observation.get("gene_id"),
            "status": observation.get("status"),
            "phenotype": observation.get("phenotype"),
            "reason_code": observation.get("reason_code"),
        })
    return documents


def build_assessment_document(*, assessment_id: str, created_at: Any,
                              input_hash: str, output_hash: str,
                              input_snapshot: Mapping[str, Any],
                              computation: Mapping[str, Any],
                              persisted: bool) -> Dict[str, Any]:
    """Serialise one assessment, after checking it agrees with itself.

    Args:
        assessment_id: the stored identity.
        created_at: when it was recorded. Not part of any hash.
        input_hash: the question's hash, as recorded.
        output_hash: the answer's hash, as recorded.
        input_snapshot: the canonical input document, verified here against
            ``input_hash`` before any of it is read.
        computation: the canonical computation document - exactly what
            ``AssessmentComputation.to_json`` produced and what was stored.
        persisted: whether this assessment is on disk. ``False`` is refused:
            a response that looked like a stored assessment but described an
            in-memory calculation would be indistinguishable from the real
            thing to every client that received it.

    Raises:
        _SerialisationRefused: the document does not hash back to what it
            claims, the coverage result is missing or does not match its hash,
            or the assessment was never persisted. Nothing partial is
            returned: a half-verified assessment is one whose trustworthy half
            cannot be told from its other half.
    """
    if not persisted:
        raise _SerialisationRefused(
            "PERSISTENCE_REFUSED",
            details={"issues": [{"location": "$.persisted",
                                 "code": "NOT_PERSISTED"}]})

    # 1. The question still describes itself.
    verify_input_snapshot(input_snapshot, input_hash=input_hash)

    # 2. The answer still hashes to what is recorded beside it. Recomputed
    #    from the document rather than trusted, using the engine's own
    #    projection so that what is checked is what was hashed.
    recomputed = sha256_digest(hashed_projection(computation))
    if recomputed != output_hash or \
            recomputed != computation.get("output_hash"):
        raise _SerialisationRefused(
            "STORED_RESULT_INCONSISTENT",
            details={"issues": [{"location": "$.output_hash",
                                 "code": "HASH_MISMATCH"}]})
    if computation.get("input_hash") != input_hash:
        raise _SerialisationRefused(
            "STORED_RESULT_INCONSISTENT",
            details={"issues": [{"location": "$.input_hash",
                                 "code": "HASH_MISMATCH"}]})

    # 3. The coverage detail is present and matches the hash beside it. This
    #    raises rather than returning a document without axes: coverage
    #    without its axes cannot show which parts of a question went
    #    unanswered.
    coverage_result = embedded_coverage_result(computation)

    provenance = computation.get("release_provenance") or {}
    axes = _axes_by_drug(coverage_result)
    medications = [
        _medication_document(medication,
                             axes.get(medication.get("drug_id"), ()))
        for medication in computation.get("medications") or ()]

    return {
        "contract_version": CONTRACT_VERSION,
        "assessment_id": assessment_id,
        "mode": input_snapshot.get("mode"),
        "input_kind": input_snapshot.get("input_kind"),
        "case_id": input_snapshot.get("case_id"),
        "created_at": _isoformat(created_at),
        "input_hash": input_hash,
        "output_hash": output_hash,
        "coverage_result_hash": computation.get("coverage_result_hash"),
        "status": _status_block(
            computation.get("overall_attention"),
            computation.get("overall_coverage"),
            computation.get("overall_coverage_reason_codes") or ()),
        "medications": medications,
        "observations": _observation_documents(input_snapshot),
        "release": {name: provenance.get(name)
                    for name in _PROVENANCE_FIELDS},
        "warnings": _list(computation.get("warnings")),
        "clinical_warning": canonical_clinical_warning(),
        "persisted": True,
    }


def assessment_document_from_result(result: Any, *,
                                    input_snapshot: Mapping[str, Any]
                                    ) -> Dict[str, Any]:
    """The POST path: one freshly executed and persisted result.

    Takes the input snapshot as an argument rather than rebuilding it from the
    result, because the result carries the calculation and not the question -
    and a snapshot assembled from the answer could not be used to check the
    answer.
    """
    return build_assessment_document(
        assessment_id=result.assessment_id.to_json(),
        created_at=result.created_at,
        input_hash=result.input_hash,
        output_hash=result.output_hash,
        input_snapshot=input_snapshot,
        computation=result.computation.to_json(),
        persisted=bool(result.persisted))


def assessment_document_from_read_model(read_model: Any) -> Dict[str, Any]:
    """The GET path: one assessment reconstructed from stored rows.

    The read model has already verified the row against its snapshots; this
    verifies the document against its hashes again on the way out. Twice is
    intentional and cheap: the two checks cover different failures - one that
    the rows and the document agree, one that the document has not been
    altered between being read and being serialised.
    """
    return build_assessment_document(
        assessment_id=read_model.assessment_id,
        created_at=read_model.created_at or read_model.completed_at,
        input_hash=read_model.input_hash,
        output_hash=read_model.output_hash,
        input_snapshot=read_model.input_snapshot,
        computation=read_model.computation,
        persisted=True)
