# -*- coding: utf-8 -*-
"""Failure types for the assessment engine (WP-14).

Every type carries a stable machine-readable ``code``. Different causes must
not collapse into one generic result: "the claim boundary is not approved",
"the ruleset artifact was tampered with" and "this phenotype was never
supplied" have different owners and different remedies, and a caller that
could not tell them apart would have to guess which.

Note what is *not* here. There is no error for "nothing could be assessed".
``NOT_ASSESSED`` is a calculated result - the honest answer to a question -
and a caller able to catch it as an exception might be tempted to swallow it.
Absence is reported, never raised.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

__all__ = [
    "AssessmentEngineError",
    "AssessmentInputError",
    "AssessmentReleaseError",
    "AssessmentArtifactError",
    "AssessmentExecutionError",
    "AssessmentPersistenceError",
    "FAILURE_CODES",
]

#: Every refusal this work package can produce, with what each means and who
#: owns clearing it. Published as data so the CLI can list them and a reader
#: can see the whole surface without reading five modules.
FAILURE_CODES: Mapping[str, str] = {
    "ASSESSMENT_CLAIM_BOUNDARY_NOT_APPROVED":
        "the claim boundary carries no approval from named humans, so no "
        "assessment may execute in any mode",
    "ASSESSMENT_MODE_NOT_PERMITTED":
        "the requested operation mode is not enabled by the claim boundary",
    "ASSESSMENT_INPUT_KIND_NOT_PERMITTED":
        "the supplied input kind is not one the claim boundary permits",
    "ASSESSMENT_INPUT_INVALID":
        "the assessment input could not be read as a canonical input",
    "ASSESSMENT_ACTIVE_RELEASE_MISSING":
        "no release is active, so there is nothing to pin an assessment to",
    "ASSESSMENT_RELEASE_NOT_ACTIVE":
        "the requested release exists but is not ACTIVE; a new assessment "
        "executes only against a release that is active when pinned",
    "ASSESSMENT_RELEASE_MANIFEST_INVALID":
        "the release manifest does not hash to what the release record pins",
    "ASSESSMENT_DATASET_NOT_PUBLISHED":
        "the pinned dataset is not PUBLISHED",
    "ASSESSMENT_RULESET_NOT_FROZEN":
        "the pinned ruleset is not FROZEN; a merely VALIDATED ruleset is not "
        "executable (SAFETY-INV-003)",
    "ASSESSMENT_RULESET_ARTIFACT_INVALID":
        "the frozen ruleset artifact could not be loaded or does not hash to "
        "what the release pins",
    "ASSESSMENT_COVERAGE_MANIFEST_MISSING":
        "no approved coverage manifest exists for this ruleset and dataset",
    "ASSESSMENT_COVERAGE_MANIFEST_INVALID":
        "the coverage manifest is not true of the artifacts it pins, or more "
        "than one manifest claims the same ruleset and dataset",
    "ASSESSMENT_VERSION_MISMATCH":
        "two pinned artifacts disagree about which dataset, ruleset or "
        "evidence build they belong to",
    "ASSESSMENT_RULE_NOT_EXECUTABLE":
        "a rule a FULL axis depends on is not a validated member of the "
        "frozen ruleset",
    "ASSESSMENT_RULE_HASH_MISMATCH":
        "a rule's content hash disagrees with what coverage recorded; the "
        "artifact has changed underneath the manifest",
    "ASSESSMENT_RULE_DID_NOT_MATCH":
        "coverage reported an axis FULL but its rule does not match the "
        "observed phenotype; one of the two is wrong and neither may be "
        "trusted",
    "ASSESSMENT_EVIDENCE_MISSING":
        "a rule a FULL axis depends on cites no resolvable evidence "
        "(SAFETY-INV-006)",
    "ASSESSMENT_CONFLICT_UNRESOLVED":
        "two validated member rules cover the same axis; WP-11 should have "
        "refused the ruleset, and this engine will not pick between them",
    "ASSESSMENT_ENTITY_NOT_RESOLVABLE":
        "a canonical drug or gene key does not resolve to exactly one stable "
        "identity in the pinned canonical dataset; a fresh identity is never "
        "minted to fill the gap",
    "ASSESSMENT_INPUT_SNAPSHOT_INVALID":
        "the stored input snapshot is incomplete, carries a value it must not "
        "hold, or does not hash back to the assessment input hash",
    "ASSESSMENT_PERSISTENCE_REFUSED":
        "the calculated assessment could not be stored, so nothing was stored",
    "ASSESSMENT_CONCURRENT_STATE_ERROR":
        "the persisted state moved underneath this assessment",
}


class AssessmentEngineError(Exception):
    """Base class for every assessment failure."""

    def __init__(self, message: str, *,
                 code: str = "ASSESSMENT_INPUT_INVALID",
                 location: str = "$",
                 detail: Optional[Mapping[str, Any]] = None) -> None:
        super().__init__(message)
        self.code = code
        self.location = location
        self.detail = dict(detail or {})

    def to_json(self) -> dict:
        """The refusal as a structured, auditable record.

        Deliberately carries no input values and no prose about a case: a
        refusal is logged, and an audit row holding a phenotype profile or a
        clinical sentence is a disclosure waiting to happen.
        """
        return {
            "refused": True,
            "code": self.code,
            "location": self.location,
            "meaning": FAILURE_CODES.get(self.code, ""),
            "detail": dict(self.detail),
        }


class AssessmentInputError(AssessmentEngineError):
    """The input could not be read, or names something the boundary forbids."""


class AssessmentReleaseError(AssessmentEngineError):
    """No release could be pinned, or the one requested may not execute."""


class AssessmentArtifactError(AssessmentEngineError):
    """A pinned artifact is missing, unreadable, or not what it claims to be.

    Always a refusal rather than a downgrade. An artifact that does not verify
    cannot produce a partially trustworthy result: the part that looks fine
    was read from the same file as the part that does not.
    """


class AssessmentExecutionError(AssessmentEngineError):
    """Calculation could not proceed on artifacts that appeared valid.

    Raised when coverage and the ruleset disagree - a FULL axis whose rule is
    absent, changed, or does not match. That combination is corruption, not an
    uncovered axis, and silently reporting it as absence would hide the
    disagreement behind an answer that looks routine.
    """


class AssessmentPersistenceError(AssessmentEngineError):
    """The result could not be stored, and nothing partial was left behind."""
