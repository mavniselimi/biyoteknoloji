# -*- coding: utf-8 -*-
"""Synthetic validation cases for WP-18 tests. Nothing here is real.

Every case is built from the TESTGENE/testdrug world WP-13 and WP-14 use, so
no fixture in this file names a real gene, a real drug, a real person or a
real source. In particular there is **no expert holdout payload** here that
could be mistaken for one somebody authored: the expert-holdout fixtures carry
obviously synthetic content and exist to exercise refusals.

The fixtures are deliberately awkward in one place. ``development_pair`` and
``holdout_from_same_family`` share a derivation family and differ in content,
because that is the pair no content fingerprint can catch and the partition
must still refuse - and a fixture set that only contained obvious duplicates
would let that rule pass untested.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Dict, Mapping, Optional

from pgx.validation.cases import (Provenance, RestrictedPayload,
                                  ValidationCaseId, ValidationCaseMetadata)
from pgx.validation.compatibility import ReleaseCompatibility, UNPINNED
from pgx.validation.fingerprint import content_fingerprint
from pgx.validation.vocabulary import (DataClassification, ValidationCaseRole,
                                       VisibilityLevel)

NOW = _dt.datetime(2026, 3, 1, 12, 0, tzinfo=_dt.timezone.utc)

GENE_1 = "GENE:TESTGENE1"
GENE_2 = "GENE:TESTGENE2"
DRUG_1 = "DRUG:testdrug-alpha"
DRUG_2 = "DRUG:testdrug-beta"

NO_PII = ("This case is synthetic. It carries no data belonging to any real "
          "person and no clinical text.")

#: A citable-looking but obviously invented source. Named so a reader cannot
#: mistake it for a real publication.
SYNTHETIC_CITATION = "TEST-SYNTHETIC vignette set, table 1 (not a real source)"


def content(gene: str = GENE_1, value: str = "POOR",
            drug: str = DRUG_1) -> Dict[str, Any]:
    return {"observations": [{"gene": gene, "value": value}],
            "medications": [drug]}


def provenance(*, development: bool = False, source: str = "TEST-SOURCE/1",
               method: str = "TEST synthetic authoring",
               citation: Optional[str] = SYNTHETIC_CITATION,
               digest: Optional[str] = None) -> Provenance:
    return Provenance(source_identity=source, derivation_method=method,
                      derived_from_development=development,
                      citation=citation, source_digest=digest,
                      author="TEST-author")


def case(case_id: str, role: ValidationCaseRole, *,
         body: Optional[Mapping[str, Any]] = None,
         prov: Optional[Provenance] = None,
         compatibility: Optional[ReleaseCompatibility] = None,
         visibility: Optional[VisibilityLevel] = None,
         payload_hash: Optional[str] = None) -> ValidationCaseMetadata:
    """One synthetic case. Defaults are the honest ones for its role."""
    body = content() if body is None else body
    if prov is None:
        prov = provenance(development=(role is
                                       ValidationCaseRole.DEVELOPMENT))
    return ValidationCaseMetadata(
        case_id=ValidationCaseId(case_id),
        role=role,
        classification=DataClassification.SYNTHETIC,
        provenance=prov,
        content_fingerprint=content_fingerprint(body),
        no_pii_assertion=NO_PII,
        created_at=NOW,
        compatibility=compatibility or UNPINNED("1.0.0"),
        visibility=visibility,
        payload_hash=payload_hash)


def payload(body: Optional[Mapping[str, Any]] = None) -> RestrictedPayload:
    return RestrictedPayload(content() if body is None else body)


def development_case(case_id: str = "PGX-VAL-DEV-TEST-1",
                     **kwargs: Any) -> ValidationCaseMetadata:
    return case(case_id, ValidationCaseRole.DEVELOPMENT, **kwargs)


def internal_holdout_case(case_id: str = "PGX-VAL-INT-TEST-1",
                          **kwargs: Any) -> ValidationCaseMetadata:
    """An independent internal holdout. Different source *and* content.

    The distinct default source is not decoration. Sharing ``TEST-SOURCE/1``
    with the development fixture would put the two in one derivation family,
    and the audit would - correctly - refuse the pair. A fixture set whose
    ordinary case was already a violation would make every other test in this
    package fight the fixture instead of the code.
    """
    kwargs.setdefault("body", content(gene=GENE_2, value="NORMAL",
                                      drug=DRUG_2))
    kwargs.setdefault("prov", provenance(development=False,
                                         source="TEST-SOURCE/holdout-int"))
    return case(case_id, ValidationCaseRole.INTERNAL_HOLDOUT, **kwargs)


def expert_holdout_case(case_id: str = "PGX-VAL-EXP-TEST-1",
                        **kwargs: Any) -> ValidationCaseMetadata:
    kwargs.setdefault("body", content(gene=GENE_2, value="POOR", drug=DRUG_2))
    kwargs.setdefault("prov", provenance(development=False,
                                         source="TEST-SOURCE/holdout-exp"))
    return case(case_id, ValidationCaseRole.EXPERT_HOLDOUT, **kwargs)
