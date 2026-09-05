# -*- coding: utf-8 -*-
"""The five validation layers (WP-11).

Layered because the layers fail for different reasons and different people fix
them:

A. **Structural** - is this a well-formed rule document at all? An author fixes
   it.
B. **Reference** - does everything it names exist? A curator fixes it by
   selecting real entities and real evidence.
C. **Lifecycle** - is this transition legal, from this state, by this actor?
   Process, not science.
D. **Provenance eligibility** - does the approved curation metadata permit
   encoding this as an executable rule? This layer reads decisions people
   already made. **It makes no scientific judgment of its own**, and could not:
   it has no way to know whether a conclusion is correct, only whether the
   people who reached it recorded it as supported, applicable and unconflicted.
E. **Ruleset compatibility** - do these members belong in one set?

Every layer returns *all* its issues rather than the first. An author fixing
one problem per round-trip is an author who stops fixing them.

Each issue carries a stable machine-readable code, a JSON location, a severity
and a human-readable explanation. The codes are declared as data in
:data:`ISSUE_CODES` so a caller can branch on them and a test can assert that
no code exists without a documented meaning.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import (Any, Dict, Iterable, List, Mapping, Optional, Sequence,
                    Tuple)

from pgx.curation.vocabulary import (Applicability, ConclusionState,
                                     ConflictState, CurationRole)
from pgx.curation.workflow.approval import validate_rule_approval_envelope
from pgx.domain.enums import CurationStatus, RuleStatus, RulesetStatus
from pgx.domain.hashing import sha256_digest
from pgx.rules.conflicts import detect_conflicts
from pgx.rules.lifecycle import (RULE_TRANSITION_REQUIREMENTS,
                                 RULE_VALIDATION_ROLES,
                                 ineligible_conclusion_reason)
from pgx.rules.models import (ComputableRuleDefinition, RuleLifecycleRecord,
                              allowed_rule_transitions)
from pgx.rules.schema import rule_document_issues

__all__ = [
    "ISSUE_CODES",
    "SEVERITIES",
    "ValidationContext",
    "ValidationIssue",
    "ValidationReport",
    "validate_rule",
    "validate_ruleset_members",
]

SEVERITIES: Tuple[str, ...] = ("ERROR", "WARNING", "INFO")

#: Every issue this validator can report, with its layer and meaning. A code
#: without an entry here cannot be constructed, so a report can never contain
#: an issue nobody documented.
ISSUE_CODES: Mapping[str, Mapping[str, str]] = {
    # -- A. structural --------------------------------------------------
    "RULE_DOC_NOT_OBJECT": {"layer": "A", "meaning": "the document is not a JSON object"},
    "RULE_DOC_UNKNOWN_FIELD": {"layer": "A", "meaning": "a field this schema does not have"},
    "RULE_DOC_MISSING_FIELD": {"layer": "A", "meaning": "a required field is absent"},
    "RULE_DOC_SCHEMA_VERSION": {"layer": "A", "meaning": "written against a different schema version"},
    "RULE_DOC_DIGEST_INVALID": {"layer": "A", "meaning": "a hash field is not a sha256:<hex> digest"},
    "RULE_DOC_TIMESTAMP_INVALID": {"layer": "A", "meaning": "a timestamp is unreadable"},
    "RULE_DOC_TIMESTAMP_NAIVE": {"layer": "A", "meaning": "a timestamp has no timezone"},
    "RULE_DOC_VERSION_INVALID": {"layer": "A", "meaning": "rule_version is not a positive integer"},
    "RULE_DOC_EVIDENCE_DUPLICATE": {"layer": "A", "meaning": "an evidence record is cited twice"},
    "RULE_DOC_OUTCOME_INVALID": {"layer": "A", "meaning": "the outcome is not one controlled attention level"},
    "RULE_DOC_PROVENANCE_INVALID": {"layer": "A", "meaning": "provenance is not an object"},
    "RULE_DOC_HASH_MISMATCH": {"layer": "A", "meaning": "the declared content hash does not match the content"},
    "RULE_COND_NOT_OBJECT": {"layer": "A", "meaning": "the condition is not a JSON object"},
    "RULE_COND_UNKNOWN_KEY": {"layer": "A", "meaning": "the condition carries a key this grammar lacks"},
    "RULE_COND_MISSING_KEY": {"layer": "A", "meaning": "the condition is missing a required key"},
    "RULE_COND_KIND_UNSUPPORTED": {"layer": "A", "meaning": "the condition kind is not PGX_AXIS"},
    "RULE_COND_SCHEMA_VERSION": {"layer": "A", "meaning": "the condition targets another grammar version"},
    "RULE_COND_PROHIBITED_CONSTRUCT": {"layer": "A", "meaning": "a wildcard, regex, negation or expression"},
    "RULE_COND_ENTITY_INVALID": {"layer": "A", "meaning": "the gene or drug is not a canonical key"},
    "RULE_COND_OPERATOR_UNSUPPORTED": {"layer": "A", "meaning": "the phenotype operator is not EXACT or ONE_OF"},
    "RULE_COND_PHENOTYPE_EMPTY": {"layer": "A", "meaning": "the phenotype set is empty"},
    "RULE_COND_PHENOTYPE_DUPLICATE": {"layer": "A", "meaning": "the phenotype set repeats a member"},
    "RULE_COND_PHENOTYPE_UNSUPPORTED": {"layer": "A", "meaning": "a phenotype a rule may not be keyed on"},
    "RULE_COND_PHENOTYPE_INVALID": {"layer": "A", "meaning": "the phenotype match is malformed"},
    "RULE_COND_EXACT_CARDINALITY": {"layer": "A", "meaning": "EXACT names other than exactly one phenotype"},
    # -- B. reference ---------------------------------------------------
    "RULE_REF_GENE_UNKNOWN": {"layer": "B", "meaning": "the gene is not in the canonical dataset"},
    "RULE_REF_DRUG_UNKNOWN": {"layer": "B", "meaning": "the drug is not in the canonical dataset"},
    "RULE_REF_DATASET_UNKNOWN": {"layer": "B", "meaning": "the pinned dataset does not exist"},
    "RULE_REF_INTERPRETATION_MISSING": {"layer": "B", "meaning": "the curated interpretation does not exist"},
    "RULE_REF_REVISION_MISSING": {"layer": "B", "meaning": "the curation revision does not exist"},
    "RULE_REF_REVISION_HASH_MISMATCH": {"layer": "B", "meaning": "the revision was altered after it was reviewed"},
    "RULE_REF_ENVELOPE_MISSING": {"layer": "B", "meaning": "no approval envelope names this rule"},
    "RULE_REF_EVIDENCE_MISSING": {"layer": "B", "meaning": "a cited evidence record does not resolve"},
    "RULE_REF_EVIDENCE_OUT_OF_BUILD": {"layer": "B", "meaning": "a cited record is outside the pinned build"},
    # -- C. lifecycle ---------------------------------------------------
    "RULE_LC_ILLEGAL_TRANSITION": {"layer": "C", "meaning": "a transition the lifecycle does not have"},
    "RULE_LC_CURATION_NOT_CURATED": {"layer": "C", "meaning": "the source interpretation is not CURATED"},
    "RULE_LC_IMMUTABLE": {"layer": "C", "meaning": "content changed after validation"},
    "RULE_LC_ACTOR_ROLE": {"layer": "C", "meaning": "the actor holds no role permitting this act"},
    "RULE_LC_SEPARATION": {"layer": "C", "meaning": "author, reviewer and approver are not distinct"},
    "RULE_LC_VERSION_STALE": {"layer": "C", "meaning": "somebody else moved this rule first"},
    # -- D. provenance eligibility --------------------------------------
    "RULE_ELIG_CONCLUSION_STATE": {"layer": "D", "meaning": "the conclusion cannot be honestly encoded"},
    "RULE_ELIG_APPLICABILITY": {"layer": "D", "meaning": "the applicability constraint is inexpressible"},
    "RULE_ELIG_CONFLICT_OPEN": {"layer": "D", "meaning": "an unresolved disagreement is recorded"},
    "RULE_ELIG_PROTOCOL_MISMATCH": {"layer": "D", "meaning": "the protocol pinned is not the one in force"},
    "RULE_ELIG_SOURCE_POLICY": {"layer": "D", "meaning": "the source policy does not permit this use"},
    "RULE_ELIG_EVIDENCE_NOT_APPROVED": {"layer": "D", "meaning": "the evidence build is not approved for rules"},
    "RULE_ELIG_ENVELOPE_INVALID": {"layer": "D", "meaning": "the approval envelope is incomplete or inconsistent"},
    "RULE_ELIG_BLOCKER": {"layer": "D", "meaning": "an unresolved blocker is recorded upstream"},
    # -- E. ruleset compatibility ---------------------------------------
    "RULESET_EMPTY": {"layer": "E", "meaning": "an empty ruleset cannot validate"},
    "RULESET_MEMBER_NOT_VALIDATED": {"layer": "E", "meaning": "a member is not a VALIDATED rule"},
    "RULESET_MEMBER_DEPRECATED": {"layer": "E", "meaning": "a member has been withdrawn"},
    "RULESET_MEMBER_DUPLICATE": {"layer": "E", "meaning": "a rule appears twice in membership"},
    "RULESET_MEMBER_HASH_MISMATCH": {"layer": "E", "meaning": "a member's content no longer matches what was pinned"},
    "RULESET_SCHEMA_INCOMPATIBLE": {"layer": "E", "meaning": "members were written against different schema versions"},
    "RULESET_CONFLICT_UNRESOLVED": {"layer": "E", "meaning": "a blocking conflict between members"},
    "RULESET_BOUNDARY_INCOMPATIBLE": {"layer": "E", "meaning": "members pin different dataset or protocol boundaries"},
}


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """One problem, addressable by whoever owns its layer."""

    code: str
    location: str
    severity: str
    message: str

    def __post_init__(self) -> None:
        if self.code not in ISSUE_CODES:
            raise KeyError(
                "%s is not a declared issue code; add it to ISSUE_CODES with "
                "its layer and meaning rather than reporting an undocumented "
                "failure" % self.code)
        if self.severity not in SEVERITIES:
            raise ValueError("severity must be one of %s" % ", ".join(SEVERITIES))

    @property
    def layer(self) -> str:
        return ISSUE_CODES[self.code]["layer"]

    @property
    def blocking(self) -> bool:
        return self.severity == "ERROR"

    def sort_key(self) -> Tuple[str, ...]:
        return (self.layer, self.location, self.code, self.message)

    def to_json(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "layer": self.layer,
            "location": self.location,
            "severity": self.severity,
            "message": self.message,
            "meaning": ISSUE_CODES[self.code]["meaning"],
        }


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """Every issue found, deterministically ordered and hashable.

    The hash covers the issues only. A validation result recorded against a
    rule has to be comparable across runs, and a report whose digest moved with
    the clock would not be.
    """

    issues: Tuple[ValidationIssue, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "issues",
                           tuple(sorted(self.issues, key=lambda i: i.sort_key())))

    @property
    def errors(self) -> Tuple[ValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.blocking)

    @property
    def passed(self) -> bool:
        return not self.errors

    @property
    def codes(self) -> Tuple[str, ...]:
        return tuple(sorted({issue.code for issue in self.issues}))

    def result_hash(self) -> str:
        return sha256_digest({"issues": [issue.to_json() for issue in self.issues]})

    def to_json(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "issue_count": len(self.issues),
            "error_count": len(self.errors),
            "issues": [issue.to_json() for issue in self.issues],
            "result_hash": self.result_hash(),
        }

    def merged_with(self, other: "ValidationReport") -> "ValidationReport":
        return ValidationReport(issues=self.issues + other.issues)


@dataclass(frozen=True)
class ValidationContext:
    """Everything the validator checks *against*, supplied by the caller.

    Pure by construction: this module reads nothing from a database or a file.
    A caller assembles the facts, so a test can describe an approved world
    without touching the real protocol or evidence build - which must stay
    exactly as they are.
    """

    known_gene_keys: frozenset = frozenset()
    known_drug_keys: frozenset = frozenset()
    known_dataset_public_ids: frozenset = frozenset()
    known_evidence_uuids: frozenset = frozenset()
    interpretation_status: Optional[CurationStatus] = None
    curation_revision_id: Optional[str] = None
    curation_revision_hash: Optional[str] = None
    conclusion_state: Optional[ConclusionState] = None
    applicability: Optional[Applicability] = None
    conflict_state: Optional[ConflictState] = None
    conflict_material: bool = False
    unresolved_blockers: Tuple[str, ...] = ()
    protocol_version: Optional[str] = None
    protocol_content_hash: Optional[str] = None
    source_policy_version: Optional[str] = None
    source_policy_content_hash: Optional[str] = None
    source_policy_permits_rules: bool = False
    evidence_build_content_hash: Optional[str] = None
    evidence_build_approved_for_rules: bool = False
    approval_envelope: Optional[Mapping[str, Any]] = None
    envelope_role_lookup: Optional[Mapping[str, Any]] = None
    actor_id: Optional[str] = None
    actor_roles: frozenset = frozenset()


def _issue(code: str, location: str, message: str,
           severity: str = "ERROR") -> ValidationIssue:
    return ValidationIssue(code=code, location=location, severity=severity,
                           message=message)


def validate_rule(
    definition: ComputableRuleDefinition,
    context: ValidationContext,
    *,
    target_status: RuleStatus = RuleStatus.VALIDATED,
    lifecycle: Optional[RuleLifecycleRecord] = None,
) -> ValidationReport:
    """Run every applicable layer and return every issue.

    ``target_status`` selects how strict the run is: reaching ``CURATED``
    requires the curation chain, and reaching ``VALIDATED`` additionally
    requires the approval envelope, the eligibility layer and actor separation.
    """
    issues: List[ValidationIssue] = []

    # -- A. structural ---------------------------------------------------
    for raw in rule_document_issues(definition.to_json()):
        issues.append(_issue(raw["code"], raw["location"], raw["message"],
                             raw.get("severity", "ERROR")))

    condition = definition.condition
    provenance = definition.provenance

    # -- B. reference ----------------------------------------------------
    # An empty catalogue does not disable these checks. It used to: each one
    # was guarded by "if the caller supplied a catalogue", which meant a
    # caller who passed nothing got a clean report on a rule naming entities
    # that exist nowhere. An empty catalogue means nothing is known to exist,
    # so everything the rule names is unknown, and that is what is reported.
    if condition.gene_canonical_key not in context.known_gene_keys:
        issues.append(_issue(
            "RULE_REF_GENE_UNKNOWN", "$.condition.gene_id",
            "%s is not a canonical gene in this dataset; a rule may only name "
            "entities WP-07 allocated" % condition.gene_canonical_key))
    if condition.drug_canonical_key not in context.known_drug_keys:
        issues.append(_issue(
            "RULE_REF_DRUG_UNKNOWN", "$.condition.drug_id",
            "%s is not a canonical drug in this dataset"
            % condition.drug_canonical_key))
    if provenance.dataset_public_id.to_json() not in \
            context.known_dataset_public_ids:
        issues.append(_issue(
            "RULE_REF_DATASET_UNKNOWN", "$.provenance.dataset_public_id",
            "dataset %s does not exist" % provenance.dataset_public_id))

    missing = sorted(set(provenance.evidence_record_uuids)
                     - set(context.known_evidence_uuids))
    for value in missing:
        issues.append(_issue(
            "RULE_REF_EVIDENCE_MISSING", "$.provenance.evidence_record_uuids",
            "evidence record %s does not resolve in the pinned build; a "
            "finding without a resolvable citation is an assertion "
            "(SAFETY-INV-006)" % value))

    if context.evidence_build_content_hash and \
            provenance.evidence_build_content_hash != context.evidence_build_content_hash:
        issues.append(_issue(
            "RULE_REF_EVIDENCE_OUT_OF_BUILD",
            "$.provenance.evidence_build_content_hash",
            "the rule pins evidence build %s but %s is in force; the citations "
            "were resolved against a different set of bytes"
            % (provenance.evidence_build_content_hash[:23],
               context.evidence_build_content_hash[:23])))

    # -- C. lifecycle ----------------------------------------------------
    if lifecycle is not None:
        permitted = allowed_rule_transitions()[lifecycle.status]
        if target_status not in permitted and target_status is not lifecycle.status:
            issues.append(_issue(
                "RULE_LC_ILLEGAL_TRANSITION", "$.status",
                "a %s rule cannot move to %s; permitted: %s"
                % (lifecycle.status.value, target_status.value,
                   ", ".join(item.value for item in permitted) or "nothing")))
        if lifecycle.is_immutable and \
                lifecycle.content_hash != definition.content_hash():
            issues.append(_issue(
                "RULE_LC_IMMUTABLE", "$.content_hash",
                "rule %s is %s and its content is fixed; a correction is a new "
                "version in the same family" % (definition.rule_id,
                                                lifecycle.status.value)))

    if target_status in (RuleStatus.CURATED, RuleStatus.VALIDATED):
        if context.interpretation_status is not None and \
                context.interpretation_status is not CurationStatus.CURATED:
            issues.append(_issue(
                "RULE_LC_CURATION_NOT_CURATED", "$.provenance.interpretation_id",
                "the source interpretation is %s. A rule may only encode a "
                "conclusion somebody accepted; encoding a %s item would make "
                "the whole curation workflow decorative."
                % (context.interpretation_status.value,
                   context.interpretation_status.value)))
        if context.curation_revision_id is not None and \
                context.curation_revision_id != provenance.curation_revision_id:
            issues.append(_issue(
                "RULE_REF_REVISION_MISSING", "$.provenance.curation_revision_id",
                "the rule names revision %s; the interpretation's approved "
                "revision is %s" % (provenance.curation_revision_id,
                                    context.curation_revision_id)))
        if context.curation_revision_hash is not None and \
                context.curation_revision_hash != provenance.curation_revision_hash:
            issues.append(_issue(
                "RULE_REF_REVISION_HASH_MISMATCH",
                "$.provenance.curation_revision_hash",
                "the rule pins revision hash %s but the stored revision hashes "
                "to %s; the revision was altered after it was reviewed"
                % (provenance.curation_revision_hash[:23],
                   context.curation_revision_hash[:23])))

    if target_status is RuleStatus.VALIDATED:
        if context.actor_roles and not (context.actor_roles & RULE_VALIDATION_ROLES):
            issues.append(_issue(
                "RULE_LC_ACTOR_ROLE", "$.actor",
                "%s holds %s; validating a rule requires one of %s"
                % (context.actor_id or "the actor",
                   ", ".join(sorted(role.value for role in context.actor_roles))
                   or "no role",
                   ", ".join(sorted(role.value for role in RULE_VALIDATION_ROLES)))))
        if context.actor_id and context.actor_id.strip().lower() == \
                definition.created_by.strip().lower():
            issues.append(_issue(
                "RULE_LC_SEPARATION", "$.actor",
                "%s authored this rule and cannot validate it; one person "
                "checking their own work is not an independent review"
                % context.actor_id))

        # -- D. provenance eligibility -----------------------------------
        if context.conclusion_state is not None:
            reasons = ineligible_conclusion_reason(
                context.conclusion_state,
                context.applicability or Applicability.UNCLEAR,
                context.conflict_state or ConflictState.UNRESOLVED,
                context.conflict_material)
            for reason in reasons:
                code = ("RULE_ELIG_CONCLUSION_STATE" if reason.startswith("conclusion")
                        else "RULE_ELIG_APPLICABILITY" if reason.startswith("applicability")
                        else "RULE_ELIG_CONFLICT_OPEN")
                issues.append(_issue(code, "$.provenance.interpretation_id", reason))

        if context.protocol_version is not None and (
                context.protocol_version != provenance.protocol_version
                or context.protocol_content_hash != provenance.protocol_content_hash):
            issues.append(_issue(
                "RULE_ELIG_PROTOCOL_MISMATCH", "$.provenance.protocol_version",
                "the rule was written under protocol %s/%s; %s/%s is in force"
                % (provenance.protocol_version,
                   provenance.protocol_content_hash[:15],
                   context.protocol_version,
                   (context.protocol_content_hash or "")[:15])))

        if not context.source_policy_permits_rules:
            issues.append(_issue(
                "RULE_ELIG_SOURCE_POLICY", "$.provenance.source_policy_version",
                "no approved source policy permits building executable rules "
                "from these sources"))
        elif context.source_policy_version is not None and (
                context.source_policy_version != provenance.source_policy_version
                or context.source_policy_content_hash
                != provenance.source_policy_content_hash):
            issues.append(_issue(
                "RULE_ELIG_SOURCE_POLICY", "$.provenance.source_policy_version",
                "the rule pins source policy %s; %s is in force"
                % (provenance.source_policy_version,
                   context.source_policy_version)))

        if not context.evidence_build_approved_for_rules:
            issues.append(_issue(
                "RULE_ELIG_EVIDENCE_NOT_APPROVED",
                "$.provenance.evidence_build_content_hash",
                "the pinned evidence build is not approved for rule "
                "construction; a quarantined build is not an executable source"))

        for blocker in sorted(set(context.unresolved_blockers)):
            issues.append(_issue(
                "RULE_ELIG_BLOCKER", "$.provenance",
                "unresolved upstream blocker: %s" % blocker))

        envelope = context.approval_envelope
        if envelope is None:
            issues.append(_issue(
                "RULE_REF_ENVELOPE_MISSING", "$.provenance.approval_envelope_hash",
                "no WP-10 rule approval envelope names this rule version; a "
                "rule cannot be validated on the strength of a hash alone"))
        else:
            verdict = validate_rule_approval_envelope(
                envelope, role_lookup=context.envelope_role_lookup)
            if not verdict.valid:
                for missing in verdict.missing:
                    issues.append(_issue(
                        "RULE_ELIG_ENVELOPE_INVALID",
                        "$.approval_envelope.%s" % missing,
                        "approval envelope is missing %s" % missing))
                for violation in verdict.violations:
                    issues.append(_issue(
                        "RULE_ELIG_ENVELOPE_INVALID", "$.approval_envelope",
                        violation))
            declared = str(envelope.get("rule_content_hash") or "")
            if declared and declared != definition.content_hash():
                issues.append(_issue(
                    "RULE_ELIG_ENVELOPE_INVALID",
                    "$.approval_envelope.rule_content_hash",
                    "the envelope approves content %s; this rule hashes to %s. "
                    "The approval names different bytes than the rule that would "
                    "ship." % (declared[:23], definition.content_hash()[:23])))
            envelope_hash = sha256_digest(dict(envelope))
            if envelope_hash != provenance.approval_envelope_hash:
                issues.append(_issue(
                    "RULE_ELIG_ENVELOPE_INVALID",
                    "$.provenance.approval_envelope_hash",
                    "the rule pins envelope hash %s; the supplied envelope "
                    "hashes to %s"
                    % (provenance.approval_envelope_hash[:23],
                       envelope_hash[:23])))

    return ValidationReport(issues=tuple(issues))


def validate_ruleset_members(
    definitions: Sequence[ComputableRuleDefinition],
    lifecycles: Mapping[str, RuleLifecycleRecord],
    *,
    pinned_hashes: Optional[Mapping[str, str]] = None,
) -> ValidationReport:
    """Layer E: do these members belong in one set?

    ``pinned_hashes`` is what the ruleset's membership recorded when each rule
    was added. Comparing it against the definition now is what catches a member
    whose content changed after it was pinned.
    """
    issues: List[ValidationIssue] = []

    if not definitions:
        issues.append(_issue(
            "RULESET_EMPTY", "$.members",
            "an empty ruleset cannot validate. A frozen empty set would let a "
            "release claim rule membership it does not have."))
        return ValidationReport(issues=tuple(issues))

    seen: Dict[str, int] = {}
    for definition in definitions:
        rule_id = definition.rule_id.to_json()
        seen[rule_id] = seen.get(rule_id, 0) + 1
    for rule_id, count in sorted(seen.items()):
        if count > 1:
            issues.append(_issue(
                "RULESET_MEMBER_DUPLICATE", "$.members",
                "rule %s appears %d times; a rule counted twice would be "
                "weighted twice by anything reading the set" % (rule_id, count)))

    schema_versions = {definition.rule_schema_version for definition in definitions}
    if len(schema_versions) > 1:
        issues.append(_issue(
            "RULESET_SCHEMA_INCOMPATIBLE", "$.members",
            "members were written against %d different rule schema versions: %s"
            % (len(schema_versions), ", ".join(sorted(schema_versions)))))

    for definition in sorted(definitions, key=lambda item: item.sort_key()):
        rule_id = definition.rule_id.to_json()
        lifecycle = lifecycles.get(rule_id)
        location = "$.members[%s]" % rule_id
        if lifecycle is None:
            issues.append(_issue(
                "RULESET_MEMBER_NOT_VALIDATED", location,
                "rule %s has no lifecycle record, so its status is unknown; an "
                "unknown status is not VALIDATED" % rule_id))
            continue
        if lifecycle.status is RuleStatus.DEPRECATED:
            issues.append(_issue(
                "RULESET_MEMBER_DEPRECATED", location,
                "rule %s was withdrawn on %s: %s"
                % (rule_id,
                   lifecycle.deprecated_at.date() if lifecycle.deprecated_at else "?",
                   lifecycle.deprecation_reason or "no reason recorded")))
        elif lifecycle.status is not RuleStatus.VALIDATED:
            issues.append(_issue(
                "RULESET_MEMBER_NOT_VALIDATED", location,
                "rule %s is %s; only VALIDATED rules enter a ruleset "
                "(SAFETY-INV-003)" % (rule_id, lifecycle.status.value)))
        if lifecycle.content_hash != definition.content_hash():
            issues.append(_issue(
                "RULESET_MEMBER_HASH_MISMATCH", location,
                "rule %s hashes to %s but its lifecycle record pins %s; the "
                "content changed after it was validated"
                % (rule_id, definition.content_hash()[:23],
                   lifecycle.content_hash[:23])))
        if pinned_hashes is not None:
            pinned = pinned_hashes.get(rule_id)
            if pinned is not None and pinned != definition.content_hash():
                issues.append(_issue(
                    "RULESET_MEMBER_HASH_MISMATCH", location,
                    "membership pinned %s for rule %s; it now hashes to %s"
                    % (pinned[:23], rule_id, definition.content_hash()[:23])))

    report = detect_conflicts(definitions)
    for finding in report.blocking:
        code = ("RULESET_BOUNDARY_INCOMPATIBLE"
                if finding.kind.endswith("BOUNDARY_CONFLICT")
                else "RULESET_CONFLICT_UNRESOLVED")
        issues.append(_issue(
            code, "$.members",
            "%s: %s" % (finding.kind, finding.detail)))

    return ValidationReport(issues=tuple(issues))
