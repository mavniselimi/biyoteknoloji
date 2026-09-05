"""One validated request document into one canonical assessment input.

This is the only place a caller's bytes become a question the engine will
answer, so it is the place where three things are true at once.

**Nothing is inferred.** A phenotype token this contract version does not
recognise becomes an observation recorded as uninterpretable - never a guess,
never the nearest match, never a lookup in a synonym table nobody governs.
Medication keys are passed through exactly as given: a key the pinned dataset
does not contain comes back as ``UNSUPPORTED_DRUG`` with a governed reason
code, which is a result, and dropping it would be a silent one.

**Nothing is invented.** Mode, input kind, case id, requested release and the
observations all come from the request. The actor and the role do not: they
come from the authenticated principal, through
:class:`~pgx.application.execution_context.ExecutionContext`, and there is no
argument here that could carry them.

**Nothing is re-implemented.** The profile is built by WP-12's
:func:`~pgx.engine.phenotype_normalization.normalize_profile` and the input by
WP-14's :func:`~pgx.application.assessment_models.build_assessment_input`.
A second normaliser in the API layer would be a second place for ``RAPID`` to
start meaning ``ULTRARAPID`` (SAFETY-INV-004), which is exactly the failure
WP-12 exists to make impossible.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

from apps.api.contracts.validate import (ContractViolation, Issue,
                                        validate_document)
from pgx.application.assessment_models import build_assessment_input
from pgx.domain.claims import OperationMode, PermittedInputKind
from pgx.engine.phenotype_normalization import (INPUT_CONTRACT_VERSION,
                                                normalize_profile)

__all__ = [
    "REQUEST_ADAPTER_VERSION",
    "adapt_assessment_request",
    "observations_to_mapping",
]

REQUEST_ADAPTER_VERSION = "pgx-api-request-adapter/1"


def observations_to_mapping(observations: Sequence[Mapping[str, Any]]
                            ) -> Mapping[str, Any]:
    """The wire's list of observations as the normaliser's gene-to-value map.

    A list on the wire and a mapping in the application is not an accident of
    taste. JSON object keys have no defined order and no length bound, and a
    duplicated key is resolved silently by every parser - so a profile sent as
    an object could quietly lose an observation between two clients. A list
    preserves what was sent.

    Which is why the collapse into a mapping has to refuse a repeated gene
    rather than let the later entry win. WP-12 raises when two *different*
    keys normalise to one canonical gene, but two identical keys never reach
    it: they would collapse here first, and a client that sent
    ``[{POOR}, {NORMAL}]`` for one gene would receive a confident assessment
    of whichever one happened to be last. Refused instead, at the location of
    the duplicate.

    Raises:
        ContractViolation: two observations name the same gene.
    """
    mapping: Dict[str, Any] = {}
    issues: List[Issue] = []
    for index, entry in enumerate(observations):
        gene = entry["gene"]
        if gene in mapping:
            issues.append(Issue("$.profile.observations[%d].gene" % index,
                                "DUPLICATE_ITEM"))
            continue
        mapping[gene] = entry["value"]
    if issues:
        raise ContractViolation("PhenotypeProfileRequest", issues)
    return mapping


def adapt_assessment_request(payload: Mapping[str, Any], *,
                             known_gene_keys: Optional[Sequence[str]] = None):
    """Turn a validated create-assessment document into an ``AssessmentInput``.

    Args:
        payload: the request document. Re-validated here against the contract
            rather than trusted: this function is reachable from a test, a
            future transport and the router, and "the caller already
            validated" is the assumption that eventually stops being true.
        known_gene_keys: the pinned release's gene catalogue, when the caller
            has one. Left ``None`` deliberately on the P0 path - the release
            is pinned *inside* the service, after this adapter has run, so the
            API layer does not have a catalogue to check against and must not
            resolve one for itself. Coverage reports an unknown gene with a
            governed reason code, which is the governed answer.

    Returns:
        A canonical :class:`~pgx.application.assessment_models.AssessmentInput`.

    Raises:
        ContractViolation: the document does not satisfy the request contract.
        PhenotypeProfileError: the observations cannot form a profile - two
            gene keys naming one canonical gene, for instance.
        AssessmentInputError: the canonical input refuses the document, for
            example because it carries a field P0 does not accept.
    """
    validate_document("AssessmentCreateRequest", payload)

    profile_document = payload["profile"]
    profile = normalize_profile(
        observations_to_mapping(profile_document["observations"]),
        profile_id=profile_document.get("profile_id"),
        known_gene_keys=known_gene_keys,
        require_known_genes=bool(known_gene_keys),
        contract_version=profile_document.get("input_contract_version")
        or INPUT_CONTRACT_VERSION)

    # ``build_assessment_input`` reads ``release_id``; the wire contract calls
    # the same thing ``requested_release_public_id`` because that is what it
    # is. Mapped here, in one line, rather than renamed on either side: the
    # application name predates this API and the wire name has to say which
    # kind of id it wants.
    return build_assessment_input(
        {"medications": list(payload["medications"]),
         "case_id": payload.get("case_id"),
         "release_id": payload.get("requested_release_public_id")},
        profile=profile,
        mode=OperationMode(payload["mode"]),
        input_kind=PermittedInputKind(payload["input_kind"]))
