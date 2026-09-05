# -*- coding: utf-8 -*-
"""SAFETY-INV-010 negative controls: prohibited claims on a release surface.

``LEGACY-BUG-012``: legacy carried source summaries containing dosing language
straight into user-facing output. Safe templates are the primary control, but
templates drift and summaries carry text nobody wrote for this purpose, so the
scanner is the deterministic last line.

Every string here is synthetic and refers to invented chemicals. None is
medical advice; each exists to be **blocked**.
"""

from __future__ import annotations

from typing import Sequence, Tuple

#: ``(surface, text, expected_blocking)``. Both directions: a clean surface
#: must pass, because a scanner that blocks safe output gets switched off.
#:
#: Every ``True`` entry was verified against the shipped scanner rather than
#: assumed - see ``KNOWN_SCANNER_GAPS`` below for phrasings it does *not*
#: catch, which are recorded as a finding instead of being quietly swapped out.
SURFACES: Tuple[Tuple[str, str, bool], ...] = (
    ("report/clean",
     "SYNTHDRUG-1 icin CYP2D6 ekseni degerlendirilemedi. Bu bir tedavi "
     "onerisi degildir; kararlar hekim tarafindan verilir.", False),
    ("api/clean",
     "Coverage is INSUFFICIENT for this axis. This output is not a diagnosis "
     "and does not recommend any treatment.", False),
    ("template/clean",
     "Not assessed / outside current scope. Bu sonuc klinik karar yerine "
     "gecmez.", False),

    ("report/recommendation",
     "SYNTHDRUG-2 tedavisine baslayin.", True),
    ("api/dose",
     "Reduce the dose to 25 mg daily for this phenotype.", True),
    ("template/reassurance",
     "Herhangi bir bulgu yok, bu ilac bu hasta icin guvenlidir.", True),
)

#: Phrasings that are unambiguously prohibited and that the shipped scanner
#: does **not** currently match. Measured, not guessed: each was run through
#: ``scan_claim_text`` and came back clean.
#:
#: This is a finding about ``pgx/domain/claims.py``, not about WP-20. It is
#: recorded here rather than fixed here for a deliberate reason: the pattern
#: registry is a reviewed governance artifact, and quietly adding Turkish and
#: English clinical phrasings to it on an implementer's judgement would be the
#: kind of unreviewed claim this whole system exists to prevent. WP-20 reports
#: the gap, counts it, and supplements it with structural checks.
#:
#: ``test_invariant_010.TestTheScannerHasKnownGaps`` asserts these are still
#: missed, so the day WP-00 closes one, the test says so.
KNOWN_SCANNER_GAPS: Tuple[Tuple[str, str], ...] = (
    ("tr/first-person-recommendation",
     "Bu hasta icin SYNTHDRUG-2 kullanmanizi oneririz."),
    ("en/first-person-recommendation",
     "We recommend SYNTHDRUG-2 for this patient."),
    ("en/imperative-medication-change",
     "Start SYNTHDRUG-2 for this patient."),
    ("tr/dosing-imperative",
     "Dozu 25 mg gunluk olarak azaltin."),
)


def report_carries_recommendation() -> Sequence[Tuple[str, str, bool]]:
    """NC-INV-010-REPORT-CARRIES-RECOMMENDATION."""
    return (("report/recommendation", SURFACES[3][1], True),)


def api_string_carries_dose() -> Sequence[Tuple[str, str, bool]]:
    """NC-INV-010-API-STRING-CARRIES-DOSE."""
    return (("api/dose", SURFACES[4][1], True),)


def template_carries_reassurance() -> Sequence[Tuple[str, str, bool]]:
    """NC-INV-010-TEMPLATE-CARRIES-REASSURANCE."""
    return (("template/reassurance", SURFACES[5][1], True),)


def permissive_scanner(text: str):
    """A scanner that finds nothing, ever.

    What the detector must catch: the surfaces above are genuinely prohibited,
    so a scanner reporting them clean is the failure. This double stands in for
    a scanner whose pattern registry was emptied, or whose call site was
    commented out to unblock a release.
    """

    class _Result:
        has_violations = False
        violations = ()

    return _Result()


UNSAFE_SUBJECTS = {
    "NC-INV-010-REPORT-CARRIES-RECOMMENDATION": report_carries_recommendation,
    "NC-INV-010-API-STRING-CARRIES-DOSE": api_string_carries_dose,
    "NC-INV-010-TEMPLATE-CARRIES-REASSURANCE": template_carries_reassurance,
}
