# -*- coding: utf-8 -*-
"""The language-model boundary (WP-15).

There is no provider here. Not a disabled Gemini client, not an OpenAI client
behind a feature flag, not an abstract base class with one concrete subclass
somebody could enable with an environment variable. What exists is a port that
raises, and a contract document saying why.

**Why the boundary is drawn this far out.** The failure a model introduces
into this particular product is not a wrong number; it is a *smoother
sentence*. A model handed a ``NOT_ASSESSED`` medication produces fluent text
about there being nothing of concern. A model handed a finding with no effect
code produces a plausible mechanism. A model handed partial coverage drops the
caveat because the paragraph reads better without it. None of those is visible
in a hash, none trips a lexical scanner reliably, and each is exactly the
reassurance ``SAFETY-INV-001`` exists to prevent.

**What the port would receive if it were ever implemented.** An
already-validated :class:`~pgx.reporting.structured.StructuredReport` - after
fact preservation, after safe-status validation, after the claim gate. Never a
phenotype profile, never a case narrative, never raw evidence text. That
ordering is the point: anything a model could do would be to *restate* a
document that was already complete and already checked, and the restatement
would then have to pass the same gate again.

P0 report generation is entirely offline. It does not import an SDK, does not
read an API key, does not open a socket, and produces a complete report with
the network unavailable.
"""

from __future__ import annotations

from typing import Any, Dict

from pgx.reporting.errors import ReportError

__all__ = [
    "LLM_ENABLED",
    "LLM_PROVIDER",
    "DisabledNarrationPort",
    "llm_boundary_contract",
]

#: Not a feature flag. There is nothing behind it to enable.
LLM_ENABLED = False

#: No provider is implemented, so there is no name to record.
LLM_PROVIDER = None


class DisabledNarrationPort:
    """The port a future narration provider would implement. It raises.

    Present so the boundary is a named, testable thing rather than an absence
    somebody has to notice. Every method refuses with a stable code.
    """

    enabled: bool = LLM_ENABLED
    provider = LLM_PROVIDER

    def narrate(self, report: Any) -> str:
        """Refuse. No provider is implemented and none is enabled."""
        raise ReportError(
            "no language-model provider is implemented and none is enabled. "
            "P0 report generation is offline: it needs no SDK, no API key and "
            "no network, and a report produced without one is the complete "
            "report rather than a degraded fallback.",
            code="REPORT_LLM_DISABLED", location="$.llm")

    def is_available(self) -> bool:
        return False


def llm_boundary_contract() -> Dict[str, Any]:
    """The boundary's published rules, as one document."""
    return {
        "llm_enabled": LLM_ENABLED,
        "provider_implemented": False,
        "provider": LLM_PROVIDER,
        "requires_api_key": False,
        "requires_network": False,
        "sends_case_content_anywhere": False,
        "would_receive": "an already-validated StructuredReport, after fact "
                         "preservation, safe-status validation and the claim "
                         "gate",
        "would_never_receive": ["a phenotype profile", "a case narrative",
                                "raw evidence text", "an unvalidated report"],
        "rule": "production P0 report generation works fully offline with "
                "language-model functionality disabled, and the offline "
                "report is the complete report rather than a fallback",
    }
