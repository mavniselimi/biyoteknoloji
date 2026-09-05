# -*- coding: utf-8 -*-
"""The human sign-off matrix, unsigned (WP-25).

Nine roles. Every one of them unsigned, and there is deliberately **no code
path in this repository that can sign one**. Not a command, not a flag, not a
fixture, not a test helper. The matrix records what each role would be
attesting to and what evidence they would have to have seen; producing the
signature is a human act performed outside this software, and a repository
that could manufacture one would have made the signature worthless.

There are no example names. A placeholder like "Dr A. Example" in a governance
document is the single easiest thing in a project to mistake for a real
signatory - it survives a copy-paste into a slide, and by then nobody
remembers it was a placeholder. So ``signatory`` is ``None`` everywhere, and
the schema requires it to be null.

``attests_to`` is written in the first person on purpose. A role signing "the
validation set is adequate for the intended use" is making a personal claim;
"validation adequacy confirmed" is a passive sentence nobody said.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Tuple

__all__ = [
    "SIGNOFF_MATRIX_VERSION",
    "SIGNOFF_ROLES",
    "SignoffRole",
    "build_signoff_matrix",
]

SIGNOFF_MATRIX_VERSION = "pgx-wp25-signoff-matrix/1"


@dataclass(frozen=True)
class SignoffRole:
    """One role that would have to sign before THS 6 could be claimed."""

    role_id: str
    role: str
    #: First person, because a signature is a personal claim.
    attests_to: str
    #: What this role would have to have seen. Named artifacts, not "the
    #: evidence".
    must_have_reviewed: Tuple[str, ...]
    gate_ids: Tuple[str, ...]
    #: Always None. There is no code path that sets it.
    signatory: None = None
    signed: bool = False

    def to_json(self) -> Mapping[str, object]:
        return {"role_id": self.role_id, "role": self.role,
                "attests_to": self.attests_to,
                "must_have_reviewed": list(self.must_have_reviewed),
                "gate_ids": list(self.gate_ids),
                "signatory": None, "signed": False,
                "signature_recorded_at": None}


SIGNOFF_ROLES: Tuple[SignoffRole, ...] = (
    SignoffRole(
        "SIGN-01", "Scientific source approver",
        "I have reviewed each registered source against the source review "
        "checklist and I approve its use as scientific evidence.",
        ("config/scientific-sources.json",
         "docs/scientific/source-review-checklist.md",
         "docs/scientific/source-strategy.md"),
        ("GATE-A",)),
    SignoffRole(
        "SIGN-02", "Data owner",
        "I confirm the canonical dataset is built from a complete, sealed "
        "snapshot and that its published identity is immutable.",
        ("data/canonical/PGX-DATA-20260830-900/manifest.json",
         "data/canonical/PGX-DATA-20260830-900/dq-report.json"),
        ("GATE-A",)),
    SignoffRole(
        "SIGN-03", "Curation lead",
        "I confirm every interpretation was curated under the approved "
        "protocol and that each rule carries complete approval metadata.",
        ("docs/scientific/curation-protocol-v1.md",
         "data/rulesets/wp11-real-gate-status.json"),
        ("GATE-B",)),
    SignoffRole(
        "SIGN-04", "Clinical safety authority",
        "I approve the claim boundary: what this system may state, what it "
        "may not, and the wording of each refusal.",
        ("docs/architecture/intended-purpose.md",
         "docs/risk-management/safety-contract.md",
         "data/safety/wp20-real-gate-status.json"),
        ("GATE-C",)),
    SignoffRole(
        "SIGN-05", "Validation owner",
        "I confirm the validation set is adequate for the intended use and "
        "that the holdout set was not used in rule development.",
        ("data/validation/wp18-real-gate-status.json",
         "data/validation/wp18-separation-audit.json",
         "docs/validation/holdout-separation-policy.md"),
        ("GATE-D",)),
    SignoffRole(
        "SIGN-06", "Expert review chair",
        "I confirm the review protocol was approved before review began and "
        "that each recorded review was performed blind-first.",
        ("docs/validation/expert-protocol.md",
         "data/expert-review/wp22-protocol-manifest.json",
         "data/expert-review/wp22-real-gate-status.json"),
        ("GATE-D",)),
    SignoffRole(
        "SIGN-07", "Security owner",
        "I confirm authentication, authorisation and the audit trail were "
        "exercised against real governed stores and that the chain verifies.",
        ("data/security/wp23-real-gate-status.json",
         "docs/security/rbac-matrix.md", "docs/security/audit-policy.md"),
        ("GATE-E",)),
    SignoffRole(
        "SIGN-08", "Platform owner",
        "I confirm the staging deployment, its health checks, its backup and "
        "restore, and its reliability drills were executed and observed.",
        ("data/deployment/wp24-real-gate-status.json",
         "data/deployment/wp24-gate-e-status.json",
         "docs/operations/staging-deployment-runbook.md"),
        ("GATE-E",)),
    SignoffRole(
        "SIGN-09", "Release approver",
        "I authorise this release: I have read the evidence pack, I accept "
        "its stated limitations, and I accept responsibility for the "
        "decision.",
        ("data/deployment/wp24-release-validation.json",
         "data/ths6/wp25-ths6-status.json",
         "docs/ths6/final/executive-summary.md"),
        ("GATE-F",)),
)


def build_signoff_matrix() -> Mapping[str, object]:
    """The matrix. Every row unsigned, and nothing here can change that."""
    return {
        "signoff_matrix_version": SIGNOFF_MATRIX_VERSION,
        "role_count": len(SIGNOFF_ROLES),
        "signed_count": 0,
        "unsigned_role_ids": [item.role_id for item in SIGNOFF_ROLES],
        "roles": [item.to_json() for item in SIGNOFF_ROLES],
        "signature_mechanism": None,
        "signature_mechanism_note": (
            "null, and not an omission: this repository contains no command, "
            "flag, fixture or helper that records a signature. Signing is a "
            "human act performed outside this software, and a repository "
            "that could manufacture one would have made the signature "
            "worthless."),
        "example_names_used": False,
        "note": (
            "Nine roles, none signed. No example or placeholder name appears "
            "anywhere in this matrix, because a placeholder in a governance "
            "document survives a copy-paste and a reader's memory of it "
            "being a placeholder does not."),
    }
