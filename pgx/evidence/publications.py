# -*- coding: utf-8 -*-
"""Publication references, parsed structurally and never enriched (WP-08).

Standard library plus :mod:`pgx.evidence.models`.

**Structure only.** A PMID must be digits, a DOI must start ``10.`` and carry a
suffix, a year must be a plausible four-digit number, a URL must be HTTPS. That
is the whole of the validation. Nothing here looks a publication up, fills in a
missing DOI, or corrects a title.

**Nothing is merged on resemblance.** Two references are the same publication
only when they carry the same PMID or the same DOI. Titles are never compared
for similarity: two records printing the same title have not been shown to cite
the same article, and a fuzzy match here would silently collapse two citations
into one.

**A parse failure keeps the value.** An unusable PMID is recorded on the
reference as an issue, with the original text intact. Dropping it would make a
broken citation look like an absent one, and those are different findings.

**Two shapes are read.** ClinPGx gives literature either as structured objects
with ``crossReferences`` (resource ``PubMed`` / ``DOI``), or - in the derived
legacy CSVs - as ``|``-separated titles beside ``;``-separated PMIDs. The
second shape can disagree with itself, so the counts of titles, PMIDs, DOIs and
years are compared and a mismatch is reported rather than aligned by position.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from pgx.evidence.models import PublicationReference

__all__ = [
    "PUBLICATION_PARSER_VERSION",
    "ParsedPublications",
    "normalize_doi",
    "parse_literature_objects",
    "parse_parallel_lists",
    "validate_pmid",
    "validate_year",
]

#: Bumped when parsing or validation changes.
PUBLICATION_PARSER_VERSION = "pgx-evidence-publications/1"

_PMID_PATTERN = re.compile(r"^[0-9]{1,9}$")
_DOI_PATTERN = re.compile(r"^10\.[0-9]{4,9}/\S+$")

#: Years outside this range are recorded with an issue rather than accepted.
#: The lower bound predates every indexed pharmacogenomic publication; the
#: upper bound is deliberately generous, because a future-dated preprint is a
#: source fact and not this module's business to correct.
_MIN_YEAR = 1800
_MAX_YEAR = 2200


class ParsedPublications:
    """The references found in one record, plus what disagreed while reading.

    ``issues`` holds record-level problems - a count mismatch between parallel
    lists, for instance - as distinct from the per-reference ``issues`` that
    describe one unusable identifier.
    """

    __slots__ = ("references", "issues")

    def __init__(self, references: Sequence[PublicationReference],
                 issues: Sequence[str] = ()) -> None:
        self.references = tuple(references)
        self.issues = tuple(issues)

    def __len__(self) -> int:
        return len(self.references)

    @property
    def identified(self) -> Tuple[PublicationReference, ...]:
        """References carrying a PMID or a DOI."""
        return tuple(item for item in self.references if item.identity)

    def to_json(self) -> Dict[str, Any]:
        return {
            "parser_version": PUBLICATION_PARSER_VERSION,
            "reference_count": len(self.references),
            "identified_count": len(self.identified),
            "references": [item.to_json() for item in self.references],
            "issues": list(self.issues),
        }


def validate_pmid(value: Any) -> Tuple[Optional[str], Optional[str]]:
    """Return ``(pmid, problem)``. Digits only; nothing is repaired."""
    if value is None:
        return None, None
    text = str(value).strip()
    if not text:
        return None, None
    if text.casefold().startswith("pmid:"):
        text = text[5:].strip()
    if not _PMID_PATTERN.match(text):
        return text, ("%r is not a PMID: a PMID is a run of digits" % text)
    return text.lstrip("0") or "0", None


def normalize_doi(value: Any) -> Tuple[Optional[str], Optional[str]]:
    """Return ``(doi, problem)`` under a conservative normalisation.

    Case is folded and a resolver prefix is stripped, because those are
    spellings of one DOI rather than different DOIs. Nothing else is touched:
    a DOI that does not match the registrant/suffix shape is kept as written
    and reported.
    """
    if value is None:
        return None, None
    text = str(value).strip()
    if not text:
        return None, None
    lowered = text.casefold()
    for prefix in ("https://doi.org/", "http://doi.org/",
                   "https://dx.doi.org/", "http://dx.doi.org/", "doi:"):
        if lowered.startswith(prefix):
            text = text[len(prefix):]
            lowered = text.casefold()
            break
    if not _DOI_PATTERN.match(text):
        return text, ("%r is not a DOI: a DOI is 10.<registrant>/<suffix>"
                      % text)
    return lowered, None


def validate_year(value: Any) -> Tuple[Optional[int], Optional[str]]:
    """Return ``(year, problem)``. Syntax only, generously bounded."""
    if value is None:
        return None, None
    text = str(value).strip()
    if not text:
        return None, None
    try:
        year = int(text)
    except ValueError:
        return None, "%r is not a year" % text
    if not (_MIN_YEAR <= year <= _MAX_YEAR):
        return year, ("%d is outside the plausible range %d-%d"
                      % (year, _MIN_YEAR, _MAX_YEAR))
    return year, None


def _validate_url(value: Any) -> Tuple[Optional[str], Optional[str]]:
    if value is None:
        return None, None
    text = str(value).strip()
    if not text:
        return None, None
    if text.startswith("https://"):
        return text, None
    if text.startswith("http://"):
        return text, ("%r is not HTTPS; the reference is kept and the "
                      "transport is reported" % text)
    return text, "%r is not an absolute HTTP(S) URL" % text


def parse_literature_objects(payload: Any) -> ParsedPublications:
    """Read ClinPGx ``literature`` objects into structured references.

    Accepts a list of objects, a single object, or ``None``. Identifiers come
    from ``crossReferences`` entries whose ``resource`` is ``PubMed`` or
    ``DOI``; the year comes from ``year`` when present and otherwise from the
    leading four digits of ``pubDate``, which is a reading of the field the
    source supplied rather than an inference about the article.
    """
    if payload is None:
        return ParsedPublications((), ())
    if isinstance(payload, Mapping):
        entries: Sequence[Any] = [payload]
    elif isinstance(payload, (list, tuple)):
        entries = list(payload)
    else:
        return ParsedPublications(
            (), ("literature is a %s, not an object or a list"
                 % type(payload).__name__,))

    references: List[PublicationReference] = []
    issues: List[str] = []
    for ordinal, entry in enumerate(entries):
        if not isinstance(entry, Mapping):
            issues.append("literature[%d] is a %s, not an object"
                          % (ordinal, type(entry).__name__))
            continue
        problems: List[str] = []

        title = _clean(entry.get("title"))
        pmid = doi = None
        for reference in entry.get("crossReferences") or ():
            if not isinstance(reference, Mapping):
                continue
            resource = str(reference.get("resource") or "").strip().casefold()
            value = reference.get("resourceId")
            if resource == "pubmed" and pmid is None:
                pmid, problem = validate_pmid(value)
                if problem:
                    problems.append(problem)
            elif resource == "doi" and doi is None:
                doi, problem = normalize_doi(value)
                if problem:
                    problems.append(problem)

        year, problem = validate_year(
            entry.get("year") if entry.get("year") is not None
            else _year_from_pub_date(entry.get("pubDate")))
        if problem:
            problems.append(problem)

        url, problem = _validate_url(entry.get("_sameAs"))
        if problem:
            problems.append(problem)

        if title is None and pmid is None and doi is None:
            problems.append(
                "the reference carries no title, PMID or DOI; it is kept so "
                "the citation is not lost, and it identifies nothing")

        references.append(PublicationReference(
            ordinal=ordinal, title=title, pmid=pmid, doi=doi, year=year,
            url=url, raw_value=entry, issues=tuple(problems)))

    return ParsedPublications(references, issues)


def parse_parallel_lists(titles: Any, pmids: Any, dois: Any, years: Any,
                         title_separator: str = "|",
                         id_separator: str = ";") -> ParsedPublications:
    """Read the legacy CSVs' parallel publication columns.

    The legacy flattening wrote titles, PMIDs, DOIs and years as four
    independently separated strings. Nothing guarantees they line up, so the
    lengths are compared and a mismatch is reported. Positions are *not*
    reconciled by padding or truncation: pairing the third title with the third
    PMID when the lists differ in length would invent a citation.
    """
    title_list = _split(titles, title_separator)
    pmid_list = _split(pmids, id_separator)
    doi_list = _split(dois, id_separator)
    year_list = _split(years, id_separator)

    lengths = {
        "titles": len(title_list), "pmids": len(pmid_list),
        "dois": len(doi_list), "years": len(year_list),
    }
    present = {name: size for name, size in lengths.items() if size}
    issues: List[str] = []
    aligned = len(set(present.values())) <= 1
    if not aligned:
        issues.append(
            "the parallel publication columns disagree in length (%s); the "
            "entries are kept unaligned rather than paired by position"
            % ", ".join("%s=%d" % item for item in sorted(lengths.items())))

    references: List[PublicationReference] = []
    if aligned:
        count = max(present.values()) if present else 0
        for ordinal in range(count):
            problems: List[str] = []
            pmid, problem = validate_pmid(_at(pmid_list, ordinal))
            if problem:
                problems.append(problem)
            doi, problem = normalize_doi(_at(doi_list, ordinal))
            if problem:
                problems.append(problem)
            year, problem = validate_year(_at(year_list, ordinal))
            if problem:
                problems.append(problem)
            references.append(PublicationReference(
                ordinal=ordinal, title=_at(title_list, ordinal), pmid=pmid,
                doi=doi, year=year,
                raw_value={"titles": titles, "pmids": pmids, "dois": dois,
                           "years": years},
                issues=tuple(problems)))
    else:
        # Unaligned: every value is kept in its own column-scoped reference so
        # nothing is lost, and none of them claims to be a complete citation.
        for name, values in (("titles", title_list), ("pmids", pmid_list),
                             ("dois", doi_list), ("years", year_list)):
            for ordinal, value in enumerate(values):
                references.append(PublicationReference(
                    ordinal=len(references),
                    title=value if name == "titles" else None,
                    pmid=(validate_pmid(value)[0] if name == "pmids" else None),
                    doi=(normalize_doi(value)[0] if name == "dois" else None),
                    year=(validate_year(value)[0] if name == "years" else None),
                    raw_value={name: value},
                    issues=("recorded from an unaligned %s column; it is not "
                            "paired with the other columns" % name,)))

    return ParsedPublications(references, issues)


# -- helpers ------------------------------------------------------------


def _clean(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _split(value: Any, separator: str) -> List[str]:
    if value is None:
        return []
    text = str(value).strip()
    if not text:
        return []
    return [part.strip() for part in text.split(separator) if part.strip()]


def _at(values: Sequence[str], index: int) -> Optional[str]:
    return values[index] if index < len(values) else None


def _year_from_pub_date(value: Any) -> Optional[str]:
    """The leading year of an ISO-ish publication date, or ``None``.

    A reading of the field the source supplied. No date arithmetic and no
    timezone reasoning: the source wrote ``2011-05-01T00:00:00-07:00`` and the
    year it wrote is ``2011``.
    """
    if value is None:
        return None
    text = str(value).strip()
    return text[:4] if len(text) >= 4 and text[:4].isdigit() else None
