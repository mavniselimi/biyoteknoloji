# -*- coding: utf-8 -*-
"""Declarative ClinPGx endpoint catalog (WP-04).

Standard library only. **Data, not behaviour** - there is no request logic in
this module, and adding an endpoint must never require editing the runner. A
test asserts the separation, because a catalog the orchestration code has to
know about is not a catalog.

Every declaration states, explicitly:

* a stable ID (the only way a CLI may select an endpoint);
* the path, and how the query is built from parameters;
* **required or optional** - the single field that decides whether a failure
  fails the run;
* the pagination strategy;
* the expected top-level response shape and where records live;
* what the endpoint is for, and what its data does *not* mean.

The endpoint set and query spellings come from the legacy probes. Three probe
behaviours were deliberately **not** ported, and each is recorded as a note on
the endpoint it affected:

1. ``get_first()`` - taking the first item of a result list as *the* answer.
   That is an unreviewed identity decision, and it belongs to WP-07.
2. ``flatten_items()`` - trying six container keys and, failing all of them,
   wrapping the whole payload in a list. A completely unexpected response
   became "one record" and the probe reported success.
3. ``quiet_404`` - swallowing 404s silently, so a missing required record was
   indistinguishable from an empty one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Mapping, Optional, Tuple

from pgx.ingestion.common.errors import ConfigurationError
from pgx.ingestion.common.pagination import PaginationSpec, PaginationStrategy

__all__ = [
    "CLINPGX_ALLOWED_HOSTS",
    "CLINPGX_BASE_URL",
    "CLINPGX_SOURCE_ID",
    "EndpointDeclaration",
    "ResponseShape",
    "catalog_ids",
    "clinpgx_catalog",
    "get_endpoint",
]

#: Ported verbatim from ``clinpgx_probe_v2.BASE_URL``.
CLINPGX_BASE_URL = "https://api.clinpgx.org/v1"

#: The only host the ClinPGx transport may contact.
CLINPGX_ALLOWED_HOSTS: Tuple[str, ...] = ("api.clinpgx.org",)

#: Identifier used in manifests. It names a *source of raw records*, and
#: carries no statement about that source's release eligibility - that is WP-05.
CLINPGX_SOURCE_ID = "clinpgx"


class ResponseShape(str, Enum):
    """The top-level JSON shape an endpoint is declared to return.

    Declared per endpoint and checked on every response. The legacy probe
    guessed instead, which is why a wrong shape could pass as data.
    """

    #: ``{"data": [...]}`` - the shape ClinPGx uses for collections.
    DATA_LIST = "DATA_LIST"
    #: A bare JSON array.
    BARE_LIST = "BARE_LIST"
    #: ``{"data": {...}}`` or a single object - one record, not a collection.
    SINGLE_OBJECT = "SINGLE_OBJECT"


@dataclass(frozen=True)
class EndpointDeclaration:
    """One endpoint, described rather than implemented.

    ``build_query`` is a pure function from parameters to query pairs. It makes
    no request and reads nothing global, so a plan can be computed - and
    asserted in a test - without a transport existing.
    """

    endpoint_id: str
    path_template: str
    required: bool
    shape: ResponseShape
    records_path: Tuple[str, ...]
    purpose: str
    limitations: str
    pagination: PaginationSpec = field(default_factory=PaginationSpec)
    path_params: Tuple[str, ...] = ()
    build_query: Optional[Callable[[Mapping[str, Any]], Tuple[Tuple[str, str], ...]]] = None
    legacy_origin: str = ""

    def __post_init__(self) -> None:
        if not self.endpoint_id or not self.endpoint_id.strip():
            raise ConfigurationError("every endpoint needs a stable ID")
        if not self.path_template.startswith("/"):
            raise ConfigurationError(
                "endpoint %r path must start with '/'" % self.endpoint_id)

    def path_for(self, parameters: Mapping[str, Any]) -> str:
        """Fill the path template, refusing to guess a missing parameter."""
        values = {}
        for name in self.path_params:
            if name not in parameters or parameters[name] in (None, ""):
                raise ConfigurationError(
                    "endpoint %r needs path parameter %r"
                    % (self.endpoint_id, name))
            values[name] = str(parameters[name])
        try:
            return self.path_template.format(**values)
        except KeyError as exc:  # pragma: no cover - defensive
            raise ConfigurationError(
                "endpoint %r path template needs %s" % (self.endpoint_id, exc)
            ) from exc

    def query_for(self, parameters: Mapping[str, Any]) -> Tuple[Tuple[str, str], ...]:
        """Build the query pairs for this endpoint."""
        if self.build_query is None:
            return ()
        return tuple(self.build_query(parameters))

    def to_json(self) -> Mapping[str, Any]:
        """Machine-readable description, for the plan output and the docs."""
        return {
            "endpoint_id": self.endpoint_id,
            "path_template": self.path_template,
            "required": self.required,
            "shape": self.shape.value,
            "records_path": list(self.records_path),
            "pagination_strategy": self.pagination.strategy.value,
            "page_size": self.pagination.page_size,
            "max_pages": self.pagination.max_pages,
            "path_params": list(self.path_params),
            "purpose": self.purpose,
            "limitations": self.limitations,
            "legacy_origin": self.legacy_origin,
        }


def _view_base(parameters: Mapping[str, Any]) -> Tuple[Tuple[str, str], ...]:
    """The ``view`` parameter every legacy call passed."""
    return (("view", str(parameters.get("view", "base"))),)


def _gene_lookup(parameters: Mapping[str, Any]) -> Tuple[Tuple[str, str], ...]:
    return (("symbol", str(parameters["symbol"])),) + _view_base(parameters)


def _chemical_lookup(parameters: Mapping[str, Any]) -> Tuple[Tuple[str, str], ...]:
    return (("name", str(parameters["name"])),) + _view_base(parameters)


def _guideline_by_pair(parameters: Mapping[str, Any]) -> Tuple[Tuple[str, str], ...]:
    return (
        ("relatedGenes.accessionId", str(parameters["gene_accession_id"])),
        ("relatedChemicals.accessionId", str(parameters["chemical_accession_id"])),
    ) + _view_base(parameters)


def _guideline_by_gene(parameters: Mapping[str, Any]) -> Tuple[Tuple[str, str], ...]:
    return ((
        "relatedGenes.accessionId", str(parameters["gene_accession_id"]),
    ),) + _view_base(parameters)


def _guideline_by_chemical(parameters: Mapping[str, Any]) -> Tuple[Tuple[str, str], ...]:
    return ((
        "relatedChemicals.accessionId", str(parameters["chemical_accession_id"]),
    ),) + _view_base(parameters)


def _variant_by_gene(parameters: Mapping[str, Any]) -> Tuple[Tuple[str, str], ...]:
    return ((
        "location.genes.symbol", str(parameters["symbol"]),
    ),) + _view_base(parameters)


#: Collections are declared as paged. The legacy probes never paged, so the
#: page/size spelling below is an assumption that needs live confirmation -
#: recorded in docs/migration/clinpgx-probe-intent.md. Declaring SINGLE_PAGE
#: instead would be the more dangerous guess: it would silently accept one page
#: of a paged endpoint as the whole endpoint.
_COLLECTION_PAGINATION = PaginationSpec(
    strategy=PaginationStrategy.PAGE_SIZE,
    page_param="page", size_param="size", page_size=100,
    first_page_number=1, max_pages=200)

_CATALOG: Tuple[EndpointDeclaration, ...] = (
    EndpointDeclaration(
        endpoint_id="gene_lookup",
        path_template="/data/gene",
        required=True,
        shape=ResponseShape.DATA_LIST,
        records_path=("data",),
        pagination=_COLLECTION_PAGINATION,
        build_query=_gene_lookup,
        purpose=(
            "Retrieve the raw ClinPGx gene records matching a symbol."),
        limitations=(
            "Returns every match. Choosing which match is the canonical gene is "
            "WP-07's resolution problem, not this adapter's: the legacy probe's "
            "get_first() made that choice silently and unreviewably."),
        legacy_origin="clinpgx_probe_v2.resolve_gene"),
    EndpointDeclaration(
        endpoint_id="chemical_lookup",
        path_template="/data/chemical",
        required=True,
        shape=ResponseShape.DATA_LIST,
        records_path=("data",),
        pagination=_COLLECTION_PAGINATION,
        build_query=_chemical_lookup,
        purpose=(
            "Retrieve the raw ClinPGx chemical records matching a name."),
        limitations=(
            "Chemical name recognition is not pharmacogenetic coverage. A match "
            "here says the source knows the name, nothing more."),
        legacy_origin="clinpgx_probe_v2.resolve_chemical"),
    EndpointDeclaration(
        endpoint_id="guideline_annotation_by_pair",
        path_template="/data/guidelineAnnotation",
        required=True,
        shape=ResponseShape.DATA_LIST,
        records_path=("data",),
        pagination=_COLLECTION_PAGINATION,
        build_query=_guideline_by_pair,
        purpose=(
            "Guideline annotations for one gene/chemical pair, keyed by "
            "accession ID."),
        limitations=(
            "Raw guideline text. It is not a curated interpretation and not a "
            "computable rule; turning it into either is WP-09 to WP-11."),
        legacy_origin="clinpgx_probe_v2.query_guideline_annotations (param set 1)"),
    EndpointDeclaration(
        endpoint_id="guideline_annotation_by_gene",
        path_template="/data/guidelineAnnotation",
        required=False,
        shape=ResponseShape.DATA_LIST,
        records_path=("data",),
        pagination=_COLLECTION_PAGINATION,
        build_query=_guideline_by_gene,
        purpose=(
            "Guideline annotations related to a gene, without a chemical "
            "filter. The legacy probe issued this because some relationships "
            "appear only on one side of the pair."),
        limitations=(
            "Optional: broader than the pair query and used for completeness "
            "comparison, not as the primary source for a pair."),
        legacy_origin="clinpgx_probe_v2.query_guideline_annotations (param set 2)"),
    EndpointDeclaration(
        endpoint_id="guideline_annotation_by_chemical",
        path_template="/data/guidelineAnnotation",
        required=False,
        shape=ResponseShape.DATA_LIST,
        records_path=("data",),
        pagination=_COLLECTION_PAGINATION,
        build_query=_guideline_by_chemical,
        purpose=(
            "Guideline annotations related to a chemical, without a gene "
            "filter."),
        limitations=(
            "Optional, for the same reason as the by-gene variant. The legacy "
            "probe merged all three param sets and deduplicated by ID; that "
            "merge is a resolution decision and is not performed here."),
        legacy_origin="clinpgx_probe_v2.query_guideline_annotations (param set 3)"),
    EndpointDeclaration(
        endpoint_id="variant_annotation_by_gene",
        path_template="/data/variantAnnotation",
        required=False,
        shape=ResponseShape.DATA_LIST,
        records_path=("data",),
        pagination=_COLLECTION_PAGINATION,
        build_query=_variant_by_gene,
        purpose=(
            "Variant annotations located in a gene."),
        limitations=(
            "High volume. The legacy probe kept 30 items after ranking them by "
            "a hand-written heuristic; no ranking, filtering or truncation "
            "happens here, because a heuristic that decides what is worth "
            "keeping is a scientific judgement."),
        legacy_origin="clinpgx_probe_v2.query_variant_annotations_by_gene"),
    EndpointDeclaration(
        endpoint_id="pair_report",
        path_template="/report/pair/{first_id}/{second_id}/{result_type}",
        required=False,
        shape=ResponseShape.DATA_LIST,
        records_path=("data",),
        pagination=PaginationSpec(strategy=PaginationStrategy.SINGLE_PAGE),
        path_params=("first_id", "second_id", "result_type"),
        build_query=_view_base,
        purpose=(
            "Pre-joined report for a gene/chemical pair and one result type."),
        limitations=(
            "The legacy probe tried twelve spellings of result_type and kept "
            "whichever returned anything. Here result_type is an explicit "
            "parameter: the caller states which report is wanted."),
        legacy_origin="clinpgx_probe_v2.report_pair / try_pair_all_types"),
    EndpointDeclaration(
        endpoint_id="connected_objects",
        path_template="/report/connectedObjects/{object_id}/{object_type}",
        required=False,
        shape=ResponseShape.DATA_LIST,
        records_path=("data",),
        pagination=PaginationSpec(strategy=PaginationStrategy.SINGLE_PAGE),
        path_params=("object_id", "object_type"),
        purpose=(
            "Objects ClinPGx links to a given object."),
        limitations=(
            "A link in the source is not evidence of a pharmacogenetic "
            "relationship."),
        legacy_origin="clinpgx_probe_v2.connected_objects"),
)


def clinpgx_catalog() -> Tuple[EndpointDeclaration, ...]:
    """Return the full endpoint catalog."""
    return _CATALOG


def catalog_ids() -> Tuple[str, ...]:
    """Every endpoint ID, sorted. The only legal way to name an endpoint."""
    return tuple(sorted(item.endpoint_id for item in _CATALOG))


def get_endpoint(endpoint_id: str) -> EndpointDeclaration:
    """Return one declaration by ID, or raise with the valid choices."""
    for declaration in _CATALOG:
        if declaration.endpoint_id == endpoint_id:
            return declaration
    raise ConfigurationError(
        "unknown endpoint %r; the catalog declares %s"
        % (endpoint_id, ", ".join(catalog_ids())))
