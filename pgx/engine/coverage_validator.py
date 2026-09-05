# -*- coding: utf-8 -*-
"""Validating a coverage manifest against the artifacts it pins (WP-13).

The manifest's own constructor enforces what a well-formed declaration looks
like. This module enforces the harder half: whether the declaration is *true
of* the frozen ruleset, dataset and evidence build it claims to describe.

It fails closed everywhere. A check that cannot be performed - an evidence
resolver that was not supplied, a rule whose content hash cannot be compared -
is a failure, not a pass. A coverage manifest is the document that says what a
system is able to evaluate; one that was accepted because a check was skipped
would be a claim nobody verified, wearing the appearance of one that was.

Every issue carries a stable code and a location, and every issue found is
reported: an author fixing one problem per round-trip is an author who gives up.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from pgx.domain.hashing import sha256_digest
from pgx.engine.coverage_manifest import (COVERAGE_MANIFEST_SCHEMA_VERSION,
                                          RulesetCoverageManifest)

__all__ = [
    "MANIFEST_ISSUE_CODES",
    "ManifestValidationReport",
    "validate_coverage_manifest",
]

#: Every way a manifest can be untrue of what it pins, with what each means.
#: Published so a CLI can list them and a reader can see the whole surface
#: without reading the function.
MANIFEST_ISSUE_CODES: Mapping[str, str] = {
    "COVERAGE_SCHEMA_VERSION_UNSUPPORTED":
        "the manifest was written against another coverage schema version and "
        "is not reinterpreted under this one",
    "COVERAGE_RULESET_IDENTITY_MISMATCH":
        "the manifest names a different frozen ruleset than the one supplied",
    "COVERAGE_RULESET_HASH_MISMATCH":
        "the ruleset identity agrees but its content hash does not; the "
        "ruleset was rebuilt and this manifest describes coverage that no "
        "longer exists",
    "COVERAGE_DATASET_MISMATCH":
        "the manifest pins a different canonical dataset than the ruleset does",
    "COVERAGE_EVIDENCE_BUILD_MISMATCH":
        "the manifest pins a different evidence build than the ruleset does",
    "COVERAGE_PROTOCOL_MISMATCH":
        "the manifest pins a different curation protocol than the ruleset does",
    "COVERAGE_SOURCE_POLICY_MISMATCH":
        "the manifest pins a different source policy than the ruleset does",
    "COVERAGE_DRUG_NOT_IN_CATALOGUE":
        "a declared drug is not in the pinned canonical dataset; coverage "
        "cannot be declared for a chemical the dataset does not have",
    "COVERAGE_GENE_NOT_IN_CATALOGUE":
        "an expected gene is not in the pinned canonical dataset",
    "COVERAGE_AXIS_RULE_NOT_A_MEMBER":
        "a supported axis names a rule that is not a member of this frozen "
        "ruleset",
    "COVERAGE_AXIS_RULE_HASH_MISMATCH":
        "the named rule is a member but its content differs from what the "
        "declaration recorded",
    "COVERAGE_AXIS_RULE_DOES_NOT_COVER":
        "the named rule's condition does not cover the exact declared axis",
    "COVERAGE_AXIS_EVIDENCE_MISSING":
        "a supported axis names no evidence, or names evidence that does not "
        "resolve in the pinned build (SAFETY-INV-006)",
    "COVERAGE_AXIS_RULE_NOT_VALIDATED":
        "the frozen ruleset carries no approval record evidencing that the "
        "named rule was validated, or evidences a different content than the "
        "axis claims; only validated rules may support a coverage claim "
        "(SAFETY-INV-003)",
    "COVERAGE_APPROVAL_INCOMPLETE":
        "the declaration's approval metadata is missing a named party",
    "COVERAGE_CONTENT_HASH_MISMATCH":
        "the manifest's declared content hash does not match its content",
    "COVERAGE_EVIDENCE_RESOLVER_MISSING":
        "no evidence resolver was supplied, so evidence resolvability could "
        "not be checked; an unperformed check is a failure, not a pass",
    "COVERAGE_STRUCTURAL_AXES_COPIED":
        "every declared expected gene is exactly the set of genes the ruleset "
        "has rules for, and no axis is unsupported. That is what copying "
        "structural_axes produces: a scope no reviewer chose, under which no "
        "drug can ever be incompletely covered",
}


@dataclass(frozen=True, slots=True)
class ManifestValidationReport:
    """Every way one manifest fails, or none."""

    issues: Tuple[Mapping[str, Any], ...] = ()

    @property
    def passed(self) -> bool:
        return not self.issues

    @property
    def codes(self) -> Tuple[str, ...]:
        return tuple(sorted({issue["code"] for issue in self.issues}))

    def to_json(self) -> Dict[str, Any]:
        return {"passed": self.passed,
                "issue_count": len(self.issues),
                "issues": [dict(issue) for issue in self.issues],
                "codes": list(self.codes)}

    def result_hash(self) -> str:
        return sha256_digest(self.to_json())


def _issue(code: str, location: str, message: str) -> Dict[str, Any]:
    return {"code": code, "location": location, "message": message}


def validate_coverage_manifest(
    manifest: RulesetCoverageManifest, *, frozen_ruleset,
    drug_catalogue: Sequence[str] = (), gene_catalogue: Sequence[str] = (),
    evidence_resolver=None, declared_content_hash: Optional[str] = None,
) -> ManifestValidationReport:
    """Check a manifest against the ruleset, dataset and evidence it pins.

    Every check that can be performed is performed, and every failure is
    reported rather than the first.
    """
    issues: List[Dict[str, Any]] = []

    if manifest.coverage_schema_version != COVERAGE_MANIFEST_SCHEMA_VERSION:
        issues.append(_issue(
            "COVERAGE_SCHEMA_VERSION_UNSUPPORTED", "$.coverage_schema_version",
            "manifest declares %r; this validator implements %r"
            % (manifest.coverage_schema_version,
               COVERAGE_MANIFEST_SCHEMA_VERSION)))

    ruleset_manifest = frozen_ruleset.manifest
    if manifest.ruleset_public_id != ruleset_manifest.public_id.to_json():
        issues.append(_issue(
            "COVERAGE_RULESET_IDENTITY_MISMATCH", "$.ruleset_public_id",
            "manifest pins %s; the supplied ruleset is %s"
            % (manifest.ruleset_public_id,
               ruleset_manifest.public_id.to_json())))
    if manifest.ruleset_content_hash != frozen_ruleset.ruleset_content_hash:
        issues.append(_issue(
            "COVERAGE_RULESET_HASH_MISMATCH", "$.ruleset_content_hash",
            "manifest pins %s; the supplied ruleset hashes to %s"
            % (manifest.ruleset_content_hash,
               frozen_ruleset.ruleset_content_hash)))
    if manifest.dataset_public_id != \
            ruleset_manifest.dataset_public_id.to_json() or \
            manifest.canonical_build_content_hash != \
            ruleset_manifest.canonical_build_content_hash:
        issues.append(_issue(
            "COVERAGE_DATASET_MISMATCH", "$.dataset_public_id",
            "manifest and ruleset pin different canonical datasets"))
    if manifest.evidence_build_content_hash != \
            ruleset_manifest.evidence_build_content_hash:
        issues.append(_issue(
            "COVERAGE_EVIDENCE_BUILD_MISMATCH", "$.evidence_build_content_hash",
            "manifest and ruleset pin different evidence builds"))
    if manifest.protocol_content_hash != ruleset_manifest.protocol_content_hash:
        issues.append(_issue(
            "COVERAGE_PROTOCOL_MISMATCH", "$.protocol_content_hash",
            "manifest and ruleset pin different curation protocols"))
    if manifest.source_policy_content_hash != \
            ruleset_manifest.source_policy_content_hash:
        issues.append(_issue(
            "COVERAGE_SOURCE_POLICY_MISMATCH", "$.source_policy_content_hash",
            "manifest and ruleset pin different source policies"))

    if declared_content_hash is not None and \
            declared_content_hash != manifest.content_hash():
        issues.append(_issue(
            "COVERAGE_CONTENT_HASH_MISMATCH", "$.content_hash",
            "declared %s, computed %s"
            % (declared_content_hash, manifest.content_hash())))

    if evidence_resolver is None:
        issues.append(_issue(
            "COVERAGE_EVIDENCE_RESOLVER_MISSING", "$",
            "no evidence resolver supplied; SAFETY-INV-006 cannot be checked "
            "and this validator does not pass a check it did not run"))

    members = {definition.rule_id.to_json(): definition
               for definition in frozen_ruleset.rules()}
    #: The frozen artifact's own evidence of governance: one approval record
    #: per member rule, naming who validated it and what was validated. Read
    #: here rather than trusted, because membership and validation are
    #: separate facts and this is the only place the second one is checked.
    approvals = {record.rule_id.to_json(): record
                 for record in frozen_ruleset.approvals}
    drugs = set(drug_catalogue)
    genes = set(gene_catalogue)

    ruleset_genes = {definition.condition.gene_canonical_key
                     for definition in frozen_ruleset.rules()}

    for declaration in manifest.declarations:
        where = "$.declarations[%s]" % declaration.drug_canonical_key
        if drugs and declaration.drug_canonical_key not in drugs:
            issues.append(_issue(
                "COVERAGE_DRUG_NOT_IN_CATALOGUE", where + ".drug_id",
                "%s is not in the pinned canonical dataset"
                % declaration.drug_canonical_key))
        for gene in declaration.expected_gene_keys:
            if genes and gene not in genes:
                issues.append(_issue(
                    "COVERAGE_GENE_NOT_IN_CATALOGUE",
                    where + ".expected_gene_keys",
                    "%s is not in the pinned canonical dataset" % gene))

        for axis in declaration.supported_axes:
            location = "%s.supported_axes[%s]" % (where, axis.phenotype.value)
            member = members.get(axis.rule_id)
            if member is None:
                issues.append(_issue(
                    "COVERAGE_AXIS_RULE_NOT_A_MEMBER", location,
                    "rule %s is not a member of ruleset %s"
                    % (axis.rule_id, manifest.ruleset_public_id)))
                continue
            approval = approvals.get(axis.rule_id)
            if approval is None:
                issues.append(_issue(
                    "COVERAGE_AXIS_RULE_NOT_VALIDATED", location,
                    "ruleset %s carries no approval record for rule %s, so "
                    "nothing here evidences that it was validated "
                    "(SAFETY-INV-003)"
                    % (manifest.ruleset_public_id, axis.rule_id)))
            elif approval.rule_content_hash != axis.rule_content_hash:
                issues.append(_issue(
                    "COVERAGE_AXIS_RULE_NOT_VALIDATED", location,
                    "the approval record for rule %s evidences content %s; "
                    "this axis claims %s. What was validated is not what is "
                    "being relied on."
                    % (axis.rule_id, approval.rule_content_hash,
                       axis.rule_content_hash)))
            if member.content_hash() != axis.rule_content_hash:
                issues.append(_issue(
                    "COVERAGE_AXIS_RULE_HASH_MISMATCH", location,
                    "rule %s hashes to %s; the declaration recorded %s"
                    % (axis.rule_id, member.content_hash(),
                       axis.rule_content_hash)))
            condition = member.condition
            covers = (condition.drug_canonical_key == axis.drug_canonical_key
                      and condition.gene_canonical_key ==
                      axis.gene_canonical_key
                      and axis.phenotype in condition.phenotype.values)
            if not covers:
                issues.append(_issue(
                    "COVERAGE_AXIS_RULE_DOES_NOT_COVER", location,
                    "rule %s is %s, which does not cover axis %s"
                    % (axis.rule_id, condition, axis.axis_key)))
            if not axis.evidence_references:
                issues.append(_issue(
                    "COVERAGE_AXIS_EVIDENCE_MISSING", location,
                    "axis %s names no evidence (SAFETY-INV-006)"
                    % (axis.axis_key,)))
            elif evidence_resolver is not None:
                unresolved = [item for item in axis.evidence_references
                              if not evidence_resolver(item)]
                if unresolved:
                    issues.append(_issue(
                        "COVERAGE_AXIS_EVIDENCE_MISSING", location,
                        "axis %s cites evidence that does not resolve: %s"
                        % (axis.axis_key, ", ".join(sorted(unresolved)))))

    # The structural-axes tell. A manifest whose expected scope is exactly the
    # set of genes the ruleset has rules for, with every axis supported, is
    # what copying WP-11's inventory produces - and under it no drug can ever
    # be reported as incompletely covered, because nothing was ever expected
    # that is not already present.
    if manifest.declarations and ruleset_genes:
        looks_copied = all(
            set(declaration.expected_gene_keys) == {
                axis.gene_canonical_key
                for axis in declaration.supported_axes}
            and declaration.supported_axes
            for declaration in manifest.declarations)
        if looks_copied:
            issues.append(_issue(
                "COVERAGE_STRUCTURAL_AXES_COPIED", "$.declarations",
                "every declared expected gene is exactly a gene this ruleset "
                "already has a rule for. That may be a correct scope, and it "
                "is also precisely what copying structural_axes produces, so "
                "it needs a reviewer to say which - it is not accepted "
                "silently."))

    if not manifest.approval.declared_by or not manifest.approval.reviewed_by \
            or not manifest.approval.approved_by:
        issues.append(_issue(
            "COVERAGE_APPROVAL_INCOMPLETE", "$.approval",
            "a coverage declaration names a declarer, a reviewer and an "
            "approver"))

    return ManifestValidationReport(
        issues=tuple(sorted(issues,
                            key=lambda item: (item["location"], item["code"]))))
