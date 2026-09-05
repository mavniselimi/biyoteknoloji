# -*- coding: utf-8 -*-
"""SAFETY-INV-001 negative controls: absence rendered as reassurance.

Both of these are what `risk_engine.py` did. The legacy engine returned
top-level risk ``none`` for a drug it had never heard of and rendered it as
*"Düşük / uyarı yok"* - low, no warning (``LEGACY-BUG-002``). A clinician
reading that sees "we checked and it's fine" where the truth was "we have no
data at all".

In-memory only; nothing here touches the real aggregator.
"""

from __future__ import annotations

from typing import Any, Sequence

from pgx.domain.enums import AttentionLevel, CoverageStatus


def absence_mapped_to_low(levels: Sequence[Any], *,
                          coverage: Any) -> AttentionLevel:
    """NC-INV-001-ABSENCE-MAPPED-TO-LOW - the legacy behaviour, exactly.

    Nothing calculated becomes ``LOW`` whatever the coverage was. Note how
    reasonable it looks: no rule fired, so nothing is wrong, so the risk is
    low. The step from "no finding" to "low risk" is the whole defect.
    """
    present = [level for level in levels
               if level is not AttentionLevel.NOT_ASSESSED]
    if present:
        for candidate in (AttentionLevel.HIGH, AttentionLevel.MEDIUM,
                          AttentionLevel.LOW):
            if candidate in present:
                return candidate
    return AttentionLevel.LOW


def not_assessed_counted_in_maximum(levels: Sequence[Any], *,
                                    coverage: Any) -> AttentionLevel:
    """NC-INV-001-NOT-ASSESSED-IN-MAXIMUM - absence treated as a level.

    Here ``NOT_ASSESSED`` is kept in the pool and ordered below ``LOW``, so a
    medication with one unassessed axis and one genuinely low finding reports
    ``LOW`` - and, more dangerously, an all-unassessed medication under
    incomplete coverage reports ``NO_ACTIVE_ATTENTION`` because the maximum of
    an empty comparison falls through to the reassuring end.
    """
    order = [AttentionLevel.HIGH, AttentionLevel.MEDIUM, AttentionLevel.LOW,
             AttentionLevel.NOT_ASSESSED, AttentionLevel.NO_ACTIVE_ATTENTION]
    pool = list(levels)
    for candidate in order:
        if candidate in pool:
            if candidate is AttentionLevel.NOT_ASSESSED:
                return AttentionLevel.LOW
            return candidate
    return AttentionLevel.NO_ACTIVE_ATTENTION


UNSAFE_SUBJECTS = {
    "NC-INV-001-ABSENCE-MAPPED-TO-LOW": absence_mapped_to_low,
    "NC-INV-001-NOT-ASSESSED-IN-MAXIMUM": not_assessed_counted_in_maximum,
}
