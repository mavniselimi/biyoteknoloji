# -*- coding: utf-8 -*-
"""What Wave 3 retrieved from the first-release sources, and under what terms.

This module holds four things and keeps them apart on purpose:

1. **The interface** - who publishes it, at what URL, under which licence, with
   what the licence actually says, and where that statement was read.
2. **The retrieval** - which document, which version of it, when this project
   looked, and what the project can honestly say about instants and hashes.
3. **The extraction** - the recommendation rows as the source states them, in
   the source's own phenotype vocabulary.
4. **The representability verdict** - separately, per row, whether this
   project's five-value phenotype vocabulary can carry that row at all.

Keeping (3) and (4) apart is the whole point. A table that silently dropped the
rows this project cannot represent would read as a complete transcription of
the guideline, and the first thing built on it would apply to phenotypes nobody
checked. Every row the source states is recorded; the ones that cannot cross
into the project's vocabulary are recorded *and marked*, and downstream they
become coverage gaps rather than rules.

**How these documents were obtained.** A browser agent driven by this session
opened one guideline page at a time on the publisher's own public web
interface, in the order a reader would, and read the rendered page. That is not
a human download, not a documented programmatic interface, and not a bulk
export. It is agent-assisted targeted retrieval, and
:data:`RETRIEVAL_CLASSIFICATION` says so in the one place every consumer of
this module reads. The existing ``AcquisitionMode`` vocabulary in
``pgx.scientific.models`` has no member that means this; see ``AB-07`` in
:mod:`pgx.closure.authority` for why Wave 3 recorded that gap instead of
widening the production vocabulary to close it.

**What was not captured, and why it is stated rather than approximated.** The
retrieval tool returns rendered page text, not the HTTP response body, so no
byte-level hash of the document the server served exists. The hashes here are
over *this project's extraction* - they detect drift in what was transcribed,
not drift in what was published. Likewise the tool returns no per-request
timestamp, so each retrieval records the calendar date it happened on and a
measured instant it provably preceded, rather than a second-precision instant
nobody measured.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Tuple

from pgx.domain.hashing import sha256_digest

__all__ = [
    "GROUNDING_VERSION",
    "INTERFACES",
    "LICENCE_BASES",
    "RETRIEVALS",
    "RETRIEVAL_CLASSIFICATION",
    "RETRIEVAL_LIMITS",
    "GuidelineRetrieval",
    "LicenceBasis",
    "SourceInterface",
    "extraction_digest",
]

GROUNDING_VERSION = "pgx-wave03-source-grounding/1"

#: One string, read by the report, the manifest and the tests, so that no
#: consumer can describe the retrieval more favourably than another.
RETRIEVAL_CLASSIFICATION = "AGENT_ASSISTED_TARGETED_RETRIEVAL"

#: The honest limits of what was captured. Each is a thing a reader might
#: otherwise assume, so each is denied by name.
RETRIEVAL_LIMITS: Tuple[str, ...] = (
    "no byte-level hash of the served document exists: the retrieval tool "
    "returns rendered page text, not the HTTP response body",
    "no per-request timestamp exists: each retrieval records the date it "
    "happened on and a measured instant it provably preceded",
    "no full text of any guideline, supplement or publication is stored in "
    "this repository; only the recommendation rows and the citation",
    "no source's programmatic interface was called, and no page other than "
    "the ones named here was fetched",
    "the reading is this project's own; none of the cited organizations has "
    "seen it, reviewed it, or endorsed it",
)


def _text(value: object, name: str, limit: int = 4000) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("%s must be a non-empty string" % name)
    if len(value) > limit:
        raise ValueError("%s exceeds %d characters" % (name, limit))
    return value


@dataclass(frozen=True, slots=True)
class LicenceBasis:
    """The permission this project is relying on, and where it was read.

    ``statement_verbatim`` is a short quotation of the licence's own operative
    sentence. It is quoted rather than summarised because a paraphrase of a
    licence is not a licence, and because the difference between "free of
    restriction" and "free for non-commercial use" is exactly the difference a
    summary loses.
    """

    basis_key: str
    organization: str
    licence_identifier: str
    statement_verbatim: str
    evidence_url: str
    permits: Tuple[str, ...]
    does_not_cover: Tuple[str, ...]

    def __post_init__(self) -> None:
        for name in ("basis_key", "organization", "licence_identifier",
                     "statement_verbatim", "evidence_url"):
            _text(getattr(self, name), name)

    def to_json(self) -> Dict[str, Any]:
        return {
            "basis_key": self.basis_key,
            "does_not_cover": list(self.does_not_cover),
            "evidence_url": self.evidence_url,
            "licence_identifier": self.licence_identifier,
            "organization": self.organization,
            "permits": list(self.permits),
            "statement_verbatim": self.statement_verbatim,
        }


LICENCE_BASES: Tuple[LicenceBasis, ...] = (
    LicenceBasis(
        basis_key="cpic.cc0",
        organization="Clinical Pharmacogenetics Implementation Consortium",
        licence_identifier="CC0-1.0",
        statement_verbatim=(
            "All curated content published by CPIC is available free of "
            "restriction under the CC0 1.0 Universal (CC0 1.0) Public Domain "
            "Dedication"),
        evidence_url=(
            "https://github.com/cpicpgx/cpic-data/blob/master/LICENSE.md"),
        permits=(
            "storing the recommendation content in this repository",
            "producing derivative works, including computable rules",
            "redistribution",
            "commercial use",
        ),
        does_not_cover=(
            "the peer-reviewed publications themselves, which are published "
            "by their journals under the journals' terms",
            "any content on a host other than the ones this dedication names",
            "the manner of acquisition: a licence to reuse content is not "
            "permission to crawl, bulk-download or call an interface",
        )),
    LicenceBasis(
        basis_key="clinpgx.robots",
        organization="ClinPGx",
        licence_identifier="NOT_A_LICENCE_ROBOTS_DIRECTIVE_ONLY",
        statement_verbatim=(
            "User-agent: SiteimproveBot / Disallow: /literature/"),
        evidence_url="https://www.clinpgx.org/robots.txt",
        permits=(
            "retrieving the guideline and guidelineAnnotation paths used "
            "here, which no directive disallows for any agent",
        ),
        does_not_cover=(
            "reuse of ClinPGx-authored content, which this basis says "
            "nothing about",
            "the ClinPGx API at api.clinpgx.org, whose terms this project "
            "has not been able to read and therefore may not call",
            "anything under /literature/, which is disallowed for at least "
            "one named agent and which this project did not fetch",
        )),
)


@dataclass(frozen=True, slots=True)
class SourceInterface:
    """One public interface, and what this project may do with it."""

    interface_key: str
    organization: str
    interface_url: str
    interface_kind: str
    licence_basis_key: str
    citation_requirement: str
    prohibited_here: Tuple[str, ...]

    def to_json(self) -> Dict[str, Any]:
        return {
            "citation_requirement": self.citation_requirement,
            "interface_key": self.interface_key,
            "interface_kind": self.interface_kind,
            "interface_url": self.interface_url,
            "licence_basis_key": self.licence_basis_key,
            "organization": self.organization,
            "prohibited_here": list(self.prohibited_here),
        }


INTERFACES: Tuple[SourceInterface, ...] = (
    SourceInterface(
        interface_key="clinpgx.guideline_annotation",
        organization="ClinPGx (publishing CPIC-authored guideline content)",
        interface_url="https://www.clinpgx.org/guidelineAnnotation/",
        interface_kind="PUBLIC_WEB_PAGE",
        licence_basis_key="cpic.cc0",
        citation_requirement=(
            "cite the CPIC guideline publication by PMID and DOI, and name "
            "the ClinPGx annotation identifier the rows were read from"),
        prohibited_here=(
            "calling api.clinpgx.org: its terms have not been read",
            "crawling, bulk download, or fetching any page not named in "
            "RETRIEVALS",
            "storing the linked supplements, publications or Excel "
            "recommendation files",
        )),
    SourceInterface(
        interface_key="cpic.licence_declaration",
        organization="Clinical Pharmacogenetics Implementation Consortium",
        interface_url=(
            "https://github.com/cpicpgx/cpic-data/blob/master/LICENSE.md"),
        interface_kind="PUBLIC_REPOSITORY_FILE",
        licence_basis_key="cpic.cc0",
        citation_requirement=(
            "quote the dedication's operative sentence and link the file it "
            "was read from"),
        prohibited_here=(
            "cloning or downloading the cpic-data repository contents",
            "treating the licence as permission to use any interface",
        )),
)


@dataclass(frozen=True, slots=True)
class GuidelineRetrieval:
    """One document this project actually opened."""

    retrieval_key: str
    interface_key: str
    guideline_id: str
    guideline_url: str
    annotation_id: str
    annotation_url: str
    title: str
    guideline_version_label: str
    retrieved_on: str
    observed_not_later_than: str
    publication_year: str
    pmid: str
    doi: str
    pmcid: Optional[str]
    genes: Tuple[str, ...]
    drug: str

    def __post_init__(self) -> None:
        for name in ("retrieval_key", "interface_key", "guideline_id",
                     "guideline_url", "annotation_id", "annotation_url",
                     "title", "guideline_version_label", "retrieved_on",
                     "observed_not_later_than", "publication_year", "pmid",
                     "doi", "drug"):
            _text(getattr(self, name), name)
        if not self.genes:
            raise ValueError("a retrieval must name at least one gene")

    def to_json(self) -> Dict[str, Any]:
        return {
            "annotation_id": self.annotation_id,
            "annotation_url": self.annotation_url,
            "doi": self.doi,
            "drug": self.drug,
            "genes": list(self.genes),
            "guideline_id": self.guideline_id,
            "guideline_url": self.guideline_url,
            "guideline_version_label": self.guideline_version_label,
            "interface_key": self.interface_key,
            "observed_not_later_than": self.observed_not_later_than,
            "pmcid": self.pmcid,
            "pmid": self.pmid,
            "publication_year": self.publication_year,
            "retrieval_classification": RETRIEVAL_CLASSIFICATION,
            "retrieval_key": self.retrieval_key,
            "retrieved_on": self.retrieved_on,
            "title": self.title,
        }


#: The instant every Wave 3 retrieval provably preceded, measured on the
#: execution host after the last of them completed. Not the retrieval instant:
#: an upper bound on it, which is the strongest true statement available.
_OBSERVED_BOUND = "2026-09-06T12:09:12Z"
_RETRIEVED_ON = "2026-09-06"


RETRIEVALS: Tuple[GuidelineRetrieval, ...] = (
    GuidelineRetrieval(
        retrieval_key="cpic.clopidogrel.cyp2c19",
        interface_key="clinpgx.guideline_annotation",
        guideline_id="PA166251443",
        guideline_url="https://www.clinpgx.org/guideline/PA166251443",
        annotation_id="PA166104948",
        annotation_url="https://www.clinpgx.org/guidelineAnnotation/PA166104948",
        title="Annotation of CPIC Guideline for clopidogrel and CYP2C19",
        guideline_version_label="2022 Update",
        retrieved_on=_RETRIEVED_ON,
        observed_not_later_than=_OBSERVED_BOUND,
        publication_year="2022",
        pmid="35034351",
        doi="10.1002/cpt.2526",
        pmcid=None,
        genes=("CYP2C19",),
        drug="clopidogrel"),
    GuidelineRetrieval(
        retrieval_key="cpic.omeprazole.cyp2c19",
        interface_key="clinpgx.guideline_annotation",
        guideline_id="PA166251441",
        guideline_url="https://www.clinpgx.org/guideline/PA166251441",
        annotation_id="PA166219103",
        annotation_url="https://www.clinpgx.org/guidelineAnnotation/PA166219103",
        title=("Annotation of CPIC Guideline for lansoprazole, omeprazole, "
               "pantoprazole and CYP2C19"),
        guideline_version_label="August 2020 (published 2021)",
        retrieved_on=_RETRIEVED_ON,
        observed_not_later_than=_OBSERVED_BOUND,
        publication_year="2021",
        pmid="32770672",
        doi="10.1002/cpt.2015",
        pmcid="PMC7868475",
        genes=("CYP2C19",),
        drug="omeprazole"),
    GuidelineRetrieval(
        retrieval_key="cpic.amitriptyline.cyp2c19_cyp2d6",
        interface_key="clinpgx.guideline_annotation",
        guideline_id="PA166251445",
        guideline_url="https://www.clinpgx.org/guideline/PA166251445",
        annotation_id="PA166105006",
        annotation_url="https://www.clinpgx.org/guidelineAnnotation/PA166105006",
        title=("Annotation of CPIC Guideline for amitriptyline and CYP2C19, "
               "CYP2D6"),
        guideline_version_label=(
            "2016 Update, with the October 2019 CYP2D6 genotype-to-phenotype "
            "translation change applied by CPIC after publication"),
        retrieved_on=_RETRIEVED_ON,
        observed_not_later_than=_OBSERVED_BOUND,
        publication_year="2017",
        pmid="27997040",
        doi="10.1002/cpt.597",
        pmcid="PMC5478479",
        genes=("CYP2C19", "CYP2D6"),
        drug="amitriptyline"),
    GuidelineRetrieval(
        retrieval_key="cpic.codeine.cyp2d6",
        interface_key="clinpgx.guideline_annotation",
        guideline_id="PA166251454",
        guideline_url="https://www.clinpgx.org/guideline/PA166251454",
        annotation_id="PA166104996",
        annotation_url="https://www.clinpgx.org/guidelineAnnotation/PA166104996",
        title="Annotation of CPIC Guideline for codeine and CYP2D6",
        guideline_version_label=(
            "December 2020 opioids guideline (supersedes the 2014 and 2012 "
            "codeine guidelines)"),
        retrieved_on=_RETRIEVED_ON,
        observed_not_later_than=_OBSERVED_BOUND,
        publication_year="2021",
        pmid="33387367",
        doi="10.1002/cpt.2149",
        pmcid="PMC8249478",
        genes=("CYP2D6",),
        drug="codeine"),
)


def extraction_digest(payload: object) -> str:
    """Hash of what this project transcribed, never of what the source served.

    Named for what it is. A function called ``content_hash`` here would be read
    as pinning the upstream document, and the first stale-source check built on
    that reading would silently always pass.
    """
    return sha256_digest(payload)
