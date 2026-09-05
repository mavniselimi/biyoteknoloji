"""The drug and gene catalogues, read from the pinned governed artifacts.

Everything these produce is *read*. Coverage comes from the coverage manifest
that the release pinned; canonical identity comes from the canonical entity
index that the same release pinned. Nothing here counts an axis the manifest
did not declare, decides that a drug is "well covered", or arranges the list
by anything but canonical key.

The ordering deserves its own sentence, because it is the one a product
instinct would change. A catalogue sorted by attention, by number of findings,
by "most relevant", or by any score would be this layer ranking medications -
which is the thing SAFETY-INV-005 exists to forbid, and which a client would
reasonably read as a recommendation about which drug to look at first. The
order is the canonical key, always, and the only thing it means is
alphabetical.

Coverage per drug is reported as counts and identities, never as a verdict.
``supported_axis_count`` and ``verified_axis_count`` are facts about the
manifest. "Fully covered" is not offered as a boolean anywhere a drug is
concerned, because a drug's coverage depends on which genes a particular case
supplies, and a badge computed without a case would be answering a question
nobody asked with a value that looks like it applies to theirs.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from apps.api.catalog import Page, paginate
from apps.api.contracts.spec import CONTRACT_VERSION
from pgx.domain.enums import Phenotype

__all__ = [
    "DRUG_COLLECTION",
    "GENE_COLLECTION",
    "catalogue_context",
    "drug_collection_document",
    "gene_collection_document",
    "supported_phenotype_vocabulary",
]

DRUG_COLLECTION = "drugs"
GENE_COLLECTION = "genes"


def catalogue_context(provenance: Any) -> Dict[str, Any]:
    """The release identity every catalogue answer is bound to.

    Also what a cursor binds to, which is why it is built once here rather
    than assembled separately in each route: two nearly-identical context
    dictionaries would eventually differ by one key, and the symptom would be
    a cursor that is refused for no visible reason.
    """
    document = provenance.to_json() if hasattr(provenance, "to_json") \
        else dict(provenance)
    return {
        "release_public_id": document.get("release_public_id"),
        "dataset_public_id": document.get("dataset_public_id"),
        "ruleset_public_id": document.get("ruleset_public_id"),
        "coverage_manifest_hash": document.get("coverage_manifest_hash"),
    }


def supported_phenotype_vocabulary() -> List[str]:
    """The phenotype tokens an observation may carry, in governed order.

    Read off the governed enum rather than listed here. ``RAPID`` and
    ``ULTRARAPID`` are two entries and stay two entries; a vocabulary that
    collapsed them would be this module performing the exact substitution
    SAFETY-INV-004 forbids.
    """
    return [item.value for item in Phenotype]


def _display_name(canonical_key: str) -> str:
    """A controlled display value derived from the canonical key alone.

    Not a brand name, not a label from a source record, and not free text: the
    catalogue's job is to name what the release covers, and a display string
    taken from an ingested payload would be unreviewed source prose in a
    response. The transformation is mechanical and reversible, so nothing here
    can assert anything the key does not already say.
    """
    _, _, tail = canonical_key.partition(":")
    return tail.replace("-", " ").replace("_", " ").strip() or canonical_key


def _drug_summary(canonical_key: str, manifest: Any,
                  aliases: Sequence[str] = ()) -> Dict[str, Any]:
    declaration = manifest.declaration_for(canonical_key) \
        if hasattr(manifest, "declaration_for") else None
    if declaration is None:
        return {
            "drug": canonical_key,
            "display_name": _display_name(canonical_key),
            "aliases": list(aliases),
            "declared": False,
            "declaration_id": None,
            "expected_gene_keys": [],
            "supported_axis_count": 0,
            "verified_axis_count": 0,
        }
    axes = tuple(declaration.supported_axes)
    return {
        "drug": canonical_key,
        "display_name": _display_name(canonical_key),
        "aliases": list(aliases),
        "declared": True,
        "declaration_id": declaration.declaration_id,
        "expected_gene_keys": sorted(declaration.expected_gene_keys),
        "supported_axis_count": len(axes),
        # An axis is verified when the manifest says its rule reference and
        # evidence resolve. Counted, not summarised: "3 of 4" is a fact, and
        # "mostly covered" would be a judgement.
        "verified_axis_count": sum(1 for axis in axes if axis.is_verified),
    }


def drug_collection_document(*, manifest: Any, provenance: Any,
                             drug_keys: Optional[Sequence[str]] = None,
                             aliases: Optional[Mapping[str, Sequence[str]]] = None,
                             page_size: Optional[int] = None,
                             cursor_token: Optional[str] = None
                             ) -> Dict[str, Any]:
    """One page of the drug catalogue for the pinned release.

    Args:
        manifest: the governed coverage manifest the release pinned.
        provenance: that release's pinned provenance.
        drug_keys: the canonical drug catalogue. Defaults to the keys the
            manifest declares. Supplying the release's full catalogue is the
            more honest listing: a drug present in the dataset with no
            declaration appears with ``declared: false`` rather than being
            invisible, and invisible is what a client would read as "not a
            drug" rather than "not covered".
        aliases: approved alternative keys per drug, from the canonical build.
        page_size: bounded by the contract.
        cursor_token: where to resume; refused if made for another release.
    """
    context = catalogue_context(provenance)
    keys = sorted(drug_keys if drug_keys is not None
                  else manifest.declared_drug_keys)
    alias_index = dict(aliases or {})
    page: Page = paginate(keys, collection=DRUG_COLLECTION, context=context,
                          page_size=page_size, cursor_token=cursor_token)
    return {
        "contract_version": CONTRACT_VERSION,
        "release": context,
        "page": page.page_info(),
        "items": [_drug_summary(key, manifest,
                                sorted(alias_index.get(key, ())))
                  for key in page.items],
    }


def _gene_index(manifest: Any, drug_keys: Sequence[str]
                ) -> Mapping[str, Dict[str, Any]]:
    """Which genes the manifest declares, and what it declares about each."""
    index: Dict[str, Dict[str, Any]] = {}
    for drug_key in drug_keys:
        declaration = manifest.declaration_for(drug_key)
        if declaration is None:
            continue
        for gene_key in declaration.expected_gene_keys:
            entry = index.setdefault(gene_key, {
                "expected_for_drugs": set(),
                "supported_axis_count": 0,
                "supported_phenotypes": set(),
                "fully_declared": True,
            })
            entry["expected_for_drugs"].add(drug_key)
            axes = tuple(declaration.axes_for_gene(gene_key))
            entry["supported_axis_count"] += len(axes)
            for axis in axes:
                phenotype = getattr(axis.phenotype, "value", axis.phenotype)
                entry["supported_phenotypes"].add(phenotype)
            if not axes:
                # The gene is expected for this drug and the manifest declares
                # no axis for the pair. Recorded, because a gene that looks
                # fully declared while one of its drugs has no rule is exactly
                # the impression SAFETY-INV-001 forbids.
                entry["fully_declared"] = False
    return index


def gene_collection_document(*, manifest: Any, provenance: Any,
                             gene_keys: Optional[Sequence[str]] = None,
                             page_size: Optional[int] = None,
                             cursor_token: Optional[str] = None
                             ) -> Dict[str, Any]:
    """One page of the supported genes, with the phenotype vocabulary.

    ``supported_phenotypes`` per gene is what the manifest's axes actually
    declare, which is usually narrower than the vocabulary an observation may
    use. Both are reported: the vocabulary says what may be sent, the per-gene
    list says what has a governed rule behind it, and reporting only the first
    would suggest coverage the manifest does not claim.
    """
    context = catalogue_context(provenance)
    drug_keys = sorted(manifest.declared_drug_keys)
    index = _gene_index(manifest, drug_keys)
    keys = sorted(gene_keys if gene_keys is not None else index)
    page: Page = paginate(keys, collection=GENE_COLLECTION, context=context,
                          page_size=page_size, cursor_token=cursor_token)
    items = []
    for key in page.items:
        entry = index.get(key)
        if entry is None:
            items.append({
                "gene": key, "display_name": _display_name(key),
                "supported_phenotypes": [], "expected_for_drugs": [],
                "supported_axis_count": 0, "fully_declared": False,
            })
            continue
        items.append({
            "gene": key,
            "display_name": _display_name(key),
            "supported_phenotypes": sorted(entry["supported_phenotypes"]),
            "expected_for_drugs": sorted(entry["expected_for_drugs"]),
            "supported_axis_count": entry["supported_axis_count"],
            "fully_declared": bool(entry["fully_declared"]),
        })
    return {
        "contract_version": CONTRACT_VERSION,
        "release": context,
        "page": page.page_info(),
        "items": items,
        "phenotype_vocabulary": supported_phenotype_vocabulary(),
    }
