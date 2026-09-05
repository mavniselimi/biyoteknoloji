# -*- coding: utf-8 -*-
"""The claim-safety gate every rendered report passes through (WP-15).

WP-00 published a deterministic prohibited-claim scanner. This is the place it
is actually used: no report is published until its rendered text has been
scanned and come back clean, and a non-clean scan blocks publication rather
than annotating it (``SAFETY-INV-010``).

**The scanner is not weakened to make a report pass.** If a snapshot trips a
rule, the template changes. That direction is the whole value of the check: a
scanner tuned until the current output passes is a scanner that certifies
whatever it is pointed at.

**The evidence is kept.** A clean scan is not a boolean. The manifest records
the scanner version, the boundary version, the categories that were in force,
the rule ids, the offsets, and every match a safe context suppressed - so a
reviewer can see what the scanner let through and why, instead of trusting
that something was checked.

**What this is not.** The scanner is lexical. It matches patterns over folded
text; it does not understand sentences. It will miss a prohibited claim phrased
in a way nobody wrote a pattern for, and its safe-context suppression is broad
enough that an English sentence containing the word "no" suppresses negatable
matches within it. It is defence in depth behind the structural guarantees -
controlled labels, controlled sentences, no free text and no model - and it
never certifies that a document is safe.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Sequence

from pgx.domain.claims import (CLAIM_SCANNER_VERSION, DEFAULT_CLAIM_BOUNDARY,
                               ClaimBoundary, ClaimScanResult, scan_claim_text)
from pgx.reporting.errors import ReportClaimError

__all__ = [
    "GATE_CONTRACT_VERSION",
    "SCANNER_LIMITS",
    "claim_scan_evidence",
    "require_clean_report",
    "scan_report_text",
]

GATE_CONTRACT_VERSION = "pgx-report-claim-gate/1"

#: What the scanner cannot do, recorded here rather than in a comment so the
#: gate status and the evidence note can publish it verbatim.
SCANNER_LIMITS: Sequence[str] = (
    "lexical only: it matches patterns over folded text and performs no "
    "semantic analysis",
    "a prohibited claim phrased outside the published patterns is not "
    "detected",
    "safe-context suppression is broad: a sentence containing an English "
    "negation such as 'no' or 'not' suppresses negatable matches inside it",
    "it scans the rendered text, so a claim carried only in structured data "
    "that no template renders is out of its reach",
    "a clean scan is evidence that no published pattern matched, and is "
    "never evidence that a document is safe",
)


def scan_report_text(text: str, *,
                     boundary: ClaimBoundary = DEFAULT_CLAIM_BOUNDARY,
                     languages: Optional[Sequence[str]] = None
                     ) -> ClaimScanResult:
    """Scan one rendered report. Deterministic, offline, no mutation.

    Both supported languages are scanned by default rather than only the
    report's own locale: a Turkish report carries English identifiers, and an
    English one carries the Turkish canonical warning.
    """
    return scan_claim_text(text, languages=languages, boundary=boundary)


def require_clean_report(text: str, *,
                         boundary: ClaimBoundary = DEFAULT_CLAIM_BOUNDARY,
                         languages: Optional[Sequence[str]] = None
                         ) -> ClaimScanResult:
    """Scan, and refuse to let a non-clean report proceed.

    Raises:
        ReportClaimError: at least one prohibited claim survived safe-context
            analysis. The refusal carries the categories, the rule ids and the
            offsets - and not the matched sentences, because a refusal record
            holding the prohibited sentence puts it into the log.
    """
    result = scan_report_text(text, boundary=boundary, languages=languages)
    if result.has_violations:
        raise ReportClaimError(
            "the rendered report contains %d prohibited claim match(es) in "
            "categor(ies) %s; it is not published"
            % (len(result.violations),
               ", ".join(item.value for item in result.categories)),
            code="REPORT_PROHIBITED_CLAIM", location="$.rendered",
            detail={
                "scanner_version": result.scanner_version,
                "boundary_version": result.boundary_version,
                "categories": [item.value for item in result.categories],
                "rule_ids": list(result.rule_ids),
                "offsets": [[item.start, item.end]
                            for item in result.violations],
            })
    return result


def claim_scan_evidence(result: ClaimScanResult) -> Dict[str, Any]:
    """The scan, as a record that can be stored beside a published report."""
    return {
        "gate_contract_version": GATE_CONTRACT_VERSION,
        "scanner_version": result.scanner_version,
        "boundary_version": result.boundary_version,
        "is_clean": result.is_clean,
        "text_length": result.text_length,
        "violation_count": len(result.violations),
        "categories": [item.value for item in result.categories],
        "rule_ids": list(result.rule_ids),
        "violations": [
            {"rule_id": item.rule_id, "category": item.category.value,
             "language": item.language, "start": item.start, "end": item.end,
             "severity": item.severity.value}
            for item in result.violations],
        "suppressed": [
            {"rule_id": item.rule_id, "category": item.category.value,
             "start": item.start, "end": item.end,
             "safe_context": item.safe_context.value}
            for item in result.suppressed],
        "limits": list(SCANNER_LIMITS),
    }


def gate_contract() -> Dict[str, Any]:
    """The gate's published rules, as one document."""
    return {
        "gate_contract_version": GATE_CONTRACT_VERSION,
        "scanner_version": CLAIM_SCANNER_VERSION,
        "rule": "every rendered report is scanned before publication; a "
                "non-clean scan blocks publication and is never annotated "
                "around (SAFETY-INV-010)",
        "on_violation": "the report is not written, no manifest is written, "
                        "and the refusal names the categories, rule ids and "
                        "offsets without repeating the matched text",
        "limits": list(SCANNER_LIMITS),
        "note": "the scanner is defence in depth behind controlled labels, "
                "controlled sentences, the absence of free text and the "
                "absence of any language model in this path",
    }
