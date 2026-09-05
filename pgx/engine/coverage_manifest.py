# -*- coding: utf-8 -*-
"""The ruleset coverage manifest (WP-13).

WP-11's `RulesetManifest.structural_axes` says which gene/drug/phenotype
triples the member rules happen to be keyed on, and its own `note` field says
that this is a membership inventory rather than a claim of clinical coverage.
This module holds the separate document that *is* such a claim, and the
difference between the two is the whole reason it exists.

**Expected scope is declared, never inferred.** For each drug the manifest
states which genes *should have been considered* - the expected scope - and
separately which phenotype-specific axes are actually supported. Nothing can
derive the first from the second. A drug with rules for one gene and none for
another looks fully covered if you read only the rules; it is the expected
scope that makes the second gene's absence visible. So expected genes cannot
come from the chemical catalogue, from every gene appearing in evidence, from
guideline presence, from the existence of one rule, or from a legacy CSV row.
They are governed scientific metadata and require a named human declaration.

What the builder *may* do is verify: given a declared axis, find the validated
member rule whose condition covers exactly that axis, check its content hash,
and attach the reference. That is checking somebody's claim, not making one.

No real approved manifest exists, and none can while the protocol is
unapproved, the dataset is `BUILDING`, the evidence build is quarantined and
no human holds a scientific role.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from pgx.domain.enums import Phenotype
from pgx.domain.hashing import ensure_utc, is_canonical_digest, sha256_digest
from pgx.domain.immutable import freeze_json
from pgx.engine.coverage_errors import CoverageManifestError
from pgx.rules.conditions import RULE_PHENOTYPES

__all__ = [
    "COVERAGE_MANIFEST_SCHEMA_VERSION",
    "CoverageDeclaration",
    "CoverageManifestApproval",
    "RulesetCoverageManifest",
    "SupportedAxis",
    "build_coverage_manifest",
]

COVERAGE_MANIFEST_SCHEMA_VERSION = "pgx-ruleset-coverage-manifest/1"


def _require_text(value: Any, field_name: str, minimum: int = 1) -> str:
    if not isinstance(value, str) or len(value.strip()) < minimum:
        raise CoverageManifestError(
            "%s must be a non-empty string" % field_name,
            code="COVERAGE_MANIFEST_FIELD_INVALID", location="$." + field_name)
    return value.strip()


def _require_digest(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not is_canonical_digest(value):
        raise CoverageManifestError(
            "%s must be a sha256:<hex> digest, got %r" % (field_name, value),
            code="COVERAGE_MANIFEST_DIGEST_INVALID",
            location="$." + field_name)
    return value


def _require_key(value: Any, prefix: str, field_name: str) -> str:
    text = _require_text(value, field_name)
    if not text.startswith(prefix):
        raise CoverageManifestError(
            "%s must be a canonical key beginning %r, got %r"
            % (field_name, prefix, text),
            code="COVERAGE_MANIFEST_KEY_INVALID", location="$." + field_name)
    return text


@dataclass(frozen=True, slots=True)
class SupportedAxis:
    """One drug-gene-phenotype axis a ruleset is declared able to evaluate.

    The rule and evidence references are attached by the builder after it has
    checked them against the frozen ruleset. A declaration that named them
    itself would be a claim nobody verified; a declaration that omitted the
    axis entirely would be a gap nobody could see.
    """

    drug_canonical_key: str
    gene_canonical_key: str
    phenotype: Phenotype
    rule_id: str = ""
    rule_version: int = 0
    rule_content_hash: str = ""
    evidence_references: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "drug_canonical_key",
                           _require_key(self.drug_canonical_key, "DRUG:",
                                        "drug_id"))
        object.__setattr__(self, "gene_canonical_key",
                           _require_key(self.gene_canonical_key, "GENE:",
                                        "gene_id"))
        if not isinstance(self.phenotype, Phenotype):
            raise CoverageManifestError(
                "a supported axis names a Phenotype",
                code="COVERAGE_MANIFEST_AXIS_INVALID", location="$.phenotype")
        if self.phenotype not in RULE_PHENOTYPES:
            raise CoverageManifestError(
                "%s may not key an axis: it is not a phenotype a rule can be "
                "written about" % self.phenotype.value,
                code="COVERAGE_MANIFEST_AXIS_INVALID", location="$.phenotype")
        object.__setattr__(self, "evidence_references",
                           tuple(sorted(set(self.evidence_references))))

    @property
    def axis_key(self) -> Tuple[str, str, str]:
        return (self.drug_canonical_key, self.gene_canonical_key,
                self.phenotype.value)

    @property
    def is_verified(self) -> bool:
        return bool(self.rule_id and self.rule_content_hash
                    and self.evidence_references)

    def to_json(self) -> Dict[str, Any]:
        return {
            "drug_id": self.drug_canonical_key,
            "gene_id": self.gene_canonical_key,
            "phenotype": self.phenotype.value,
            "rule_id": self.rule_id,
            "rule_version": self.rule_version,
            "rule_content_hash": self.rule_content_hash,
            "evidence_references": list(self.evidence_references),
        }


@dataclass(frozen=True, slots=True)
class CoverageDeclaration:
    """What one drug's coverage scope is declared to be.

    ``expected_gene_keys`` is the load-bearing field. It says which genes a
    complete assessment of this drug would have to consider, which is what
    makes a missing gene visible as a gap rather than invisible as an absence.
    """

    drug_canonical_key: str
    expected_gene_keys: Tuple[str, ...]
    supported_axes: Tuple[SupportedAxis, ...]
    declaration_id: str
    declared_by: str
    declaration_provenance: str
    conflict_references: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "drug_canonical_key",
                           _require_key(self.drug_canonical_key, "DRUG:",
                                        "drug_id"))
        _require_text(self.declaration_id, "declaration_id")
        _require_text(self.declared_by, "declared_by")
        _require_text(self.declaration_provenance, "declaration_provenance", 20)
        if not self.expected_gene_keys:
            raise CoverageManifestError(
                "drug %s declares no expected gene. A drug whose expected "
                "scope is empty can never be incompletely covered, which is "
                "the one thing coverage exists to detect."
                % self.drug_canonical_key,
                code="COVERAGE_MANIFEST_SCOPE_EMPTY",
                location="$.expected_gene_keys")
        genes = [_require_key(value, "GENE:", "expected_gene_keys")
                 for value in self.expected_gene_keys]
        if len(set(genes)) != len(genes):
            raise CoverageManifestError(
                "drug %s lists a gene twice" % self.drug_canonical_key,
                code="COVERAGE_MANIFEST_DUPLICATE_GENE",
                location="$.expected_gene_keys")
        object.__setattr__(self, "expected_gene_keys", tuple(sorted(genes)))

        seen = set()
        for axis in self.supported_axes:
            if not isinstance(axis, SupportedAxis):
                raise CoverageManifestError(
                    "supported_axes holds SupportedAxis values",
                    code="COVERAGE_MANIFEST_AXIS_INVALID",
                    location="$.supported_axes")
            if axis.drug_canonical_key != self.drug_canonical_key:
                raise CoverageManifestError(
                    "axis %s belongs to another drug than %s"
                    % (axis.axis_key, self.drug_canonical_key),
                    code="COVERAGE_MANIFEST_AXIS_OUT_OF_SCOPE",
                    location="$.supported_axes")
            if axis.gene_canonical_key not in self.expected_gene_keys:
                raise CoverageManifestError(
                    "axis %s names gene %s, which is not in this drug's "
                    "expected scope. An axis outside the declared scope is a "
                    "claim about something nobody said should be considered."
                    % (axis.axis_key, axis.gene_canonical_key),
                    code="COVERAGE_MANIFEST_AXIS_OUT_OF_SCOPE",
                    location="$.supported_axes")
            if axis.axis_key in seen:
                raise CoverageManifestError(
                    "axis %s is declared twice" % (axis.axis_key,),
                    code="COVERAGE_MANIFEST_DUPLICATE_AXIS",
                    location="$.supported_axes")
            seen.add(axis.axis_key)
        object.__setattr__(
            self, "supported_axes",
            tuple(sorted(self.supported_axes, key=lambda item: item.axis_key)))
        object.__setattr__(self, "conflict_references",
                           tuple(sorted(set(self.conflict_references))))

    def axes_for_gene(self, gene_canonical_key: str
                      ) -> Tuple[SupportedAxis, ...]:
        return tuple(axis for axis in self.supported_axes
                     if axis.gene_canonical_key == gene_canonical_key)

    def to_json(self) -> Dict[str, Any]:
        return {
            "declaration_id": self.declaration_id,
            "drug_id": self.drug_canonical_key,
            "expected_gene_keys": list(self.expected_gene_keys),
            "supported_axes": [axis.to_json() for axis in self.supported_axes],
            "conflict_references": list(self.conflict_references),
            "declared_by": self.declared_by,
            "declaration_provenance": self.declaration_provenance,
        }


@dataclass(frozen=True, slots=True)
class CoverageManifestApproval:
    """Who declared this coverage scope, who reviewed it, who approved it.

    Three distinct names, as everywhere else in this system. A coverage scope
    is a scientific claim about what a complete assessment requires, and one
    person asserting it alone is not a governed declaration.

    A well-formed approval is not a real one. Whether the people named exist
    and hold the roles claimed is authentication work owned by WP-23.
    """

    declared_by: str
    reviewed_by: str
    approved_by: str
    approved_at: str
    approval_reference: str

    def __post_init__(self) -> None:
        for name in ("declared_by", "reviewed_by", "approved_by",
                     "approved_at", "approval_reference"):
            _require_text(getattr(self, name), name)
        names = {self.declared_by.strip().lower(),
                 self.reviewed_by.strip().lower(),
                 self.approved_by.strip().lower()}
        if len(names) != 3:
            raise CoverageManifestError(
                "a coverage declaration is declared, reviewed and approved, each "
                "act by a different person; one identity performing several "
                "separated acts is review theatre",
                code="COVERAGE_MANIFEST_SEPARATION",
                location="$.approval")

    @property
    def is_synthetic(self) -> bool:
        """True when every actor is clearly a test identity."""
        return all(name.startswith("TEST-")
                   for name in (self.declared_by, self.reviewed_by,
                                self.approved_by))

    def to_json(self) -> Dict[str, Any]:
        return {
            "declared_by": self.declared_by,
            "reviewed_by": self.reviewed_by,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
            "approval_reference": self.approval_reference,
            "synthetic": self.is_synthetic,
        }


@dataclass(frozen=True, slots=True)
class RulesetCoverageManifest:
    """What one frozen ruleset is declared able to evaluate.

    Pinned to the exact ruleset, dataset, evidence build, protocol and source
    policy it was declared against, each by identity *and* hash. A manifest
    that named only identities could survive its ruleset being rebuilt
    underneath it, and would then describe coverage that no longer exists.
    """

    coverage_schema_version: str
    ruleset_public_id: str
    ruleset_version: int
    ruleset_content_hash: str
    dataset_public_id: str
    canonical_build_key: str
    canonical_build_content_hash: str
    evidence_build_key: str
    evidence_build_content_hash: str
    protocol_version: str
    protocol_content_hash: str
    source_policy_version: str
    source_policy_content_hash: str
    declarations: Tuple[CoverageDeclaration, ...]
    approval: CoverageManifestApproval
    note: str = (
        "This manifest declares what a governed ruleset can evaluate. The "
        "expected gene scope for each drug is explicitly declared scientific "
        "metadata, not derived from the rules that happen to exist: a drug "
        "whose expected scope were inferred from its rules could never be "
        "incompletely covered.")

    def __post_init__(self) -> None:
        if self.coverage_schema_version != COVERAGE_MANIFEST_SCHEMA_VERSION:
            raise CoverageManifestError(
                "coverage_schema_version %r is not %r"
                % (self.coverage_schema_version,
                   COVERAGE_MANIFEST_SCHEMA_VERSION),
                code="COVERAGE_MANIFEST_SCHEMA_VERSION",
                location="$.coverage_schema_version")
        for name in ("ruleset_public_id", "dataset_public_id",
                     "canonical_build_key", "evidence_build_key",
                     "protocol_version", "source_policy_version"):
            _require_text(getattr(self, name), name)
        for name in ("ruleset_content_hash", "canonical_build_content_hash",
                     "evidence_build_content_hash", "protocol_content_hash",
                     "source_policy_content_hash"):
            _require_digest(getattr(self, name), name)
        if not isinstance(self.ruleset_version, int) or \
                isinstance(self.ruleset_version, bool) or \
                self.ruleset_version < 1:
            raise CoverageManifestError(
                "ruleset_version counts from 1",
                code="COVERAGE_MANIFEST_FIELD_INVALID",
                location="$.ruleset_version")
        if not self.declarations:
            raise CoverageManifestError(
                "a coverage manifest declares at least one drug. An empty "
                "manifest evaluates nothing and would report every drug as "
                "insufficient while appearing to be a coverage claim.",
                code="COVERAGE_MANIFEST_EMPTY", location="$.declarations")
        seen = set()
        for declaration in self.declarations:
            if not isinstance(declaration, CoverageDeclaration):
                raise CoverageManifestError(
                    "declarations holds CoverageDeclaration values",
                    code="COVERAGE_MANIFEST_MALFORMED",
                    location="$.declarations")
            if declaration.drug_canonical_key in seen:
                raise CoverageManifestError(
                    "drug %s is declared twice; two scopes for one drug is two "
                    "answers to what a complete assessment requires"
                    % declaration.drug_canonical_key,
                    code="COVERAGE_MANIFEST_DUPLICATE_DRUG",
                    location="$.declarations")
            seen.add(declaration.drug_canonical_key)
        if not isinstance(self.approval, CoverageManifestApproval):
            raise CoverageManifestError(
                "a coverage manifest carries its approval metadata",
                code="COVERAGE_MANIFEST_UNAPPROVED", location="$.approval")
        object.__setattr__(
            self, "declarations",
            tuple(sorted(self.declarations,
                         key=lambda item: item.drug_canonical_key)))

    # -- reading --------------------------------------------------------

    @property
    def declared_drug_keys(self) -> Tuple[str, ...]:
        return tuple(item.drug_canonical_key for item in self.declarations)

    def declaration_for(self, drug_canonical_key: str
                        ) -> Optional[CoverageDeclaration]:
        for declaration in self.declarations:
            if declaration.drug_canonical_key == drug_canonical_key:
                return declaration
        return None

    @property
    def supported_axis_count(self) -> int:
        return sum(len(item.supported_axes) for item in self.declarations)

    # -- canonical form -------------------------------------------------

    def semantic_content(self) -> Dict[str, Any]:
        return {
            "coverage_schema_version": self.coverage_schema_version,
            "ruleset_public_id": self.ruleset_public_id,
            "ruleset_version": self.ruleset_version,
            "ruleset_content_hash": self.ruleset_content_hash,
            "dataset_public_id": self.dataset_public_id,
            "canonical_build_key": self.canonical_build_key,
            "canonical_build_content_hash": self.canonical_build_content_hash,
            "evidence_build_key": self.evidence_build_key,
            "evidence_build_content_hash": self.evidence_build_content_hash,
            "protocol_version": self.protocol_version,
            "protocol_content_hash": self.protocol_content_hash,
            "source_policy_version": self.source_policy_version,
            "source_policy_content_hash": self.source_policy_content_hash,
            "declaration_count": len(self.declarations),
            "declarations": [item.to_json() for item in self.declarations],
        }

    def content_hash(self) -> str:
        return sha256_digest(self.semantic_content())

    def to_json(self) -> Dict[str, Any]:
        payload = self.semantic_content()
        payload["approval"] = self.approval.to_json()
        payload["note"] = self.note
        payload["content_hash"] = self.content_hash()
        return payload


def build_coverage_manifest(*, frozen_ruleset,
                            declarations: Sequence[Mapping[str, Any]],
                            approval: CoverageManifestApproval,
                            evidence_resolver=None
                            ) -> RulesetCoverageManifest:
    """Verify explicitly declared coverage against a frozen ruleset.

    ``declarations`` supplies, per drug: the canonical drug key, the expected
    gene keys, and the exact ``(gene, phenotype)`` axes claimed as supported.
    The builder finds the validated member rule covering each *declared* axis
    and attaches its identity, version, content hash and evidence references.

    It never adds an axis and never adds a gene. Everything it writes is a
    reference to something the caller already claimed, checked against the
    ruleset - which is the difference between verifying a declaration and
    manufacturing one. A manifest cannot be made valid by handing this
    function ``structural_axes``: those name axes, not expected scope, so the
    result would declare a scope that no reviewer wrote and no drug could ever
    be incompletely covered against.

    Raises:
        CoverageManifestError: a declared axis has no validated member rule
            whose condition covers it, a referenced rule is absent from the
            ruleset, a rule's content hash disagrees, or evidence cannot be
            resolved.
    """
    manifest = frozen_ruleset.manifest
    #: One approval record per member rule, naming who validated it and what
    #: content was validated. Membership and validation are separate facts:
    #: a rule can be inside an artifact without this evidence, and a coverage
    #: claim may rest only on the second (SAFETY-INV-003).
    approvals = {record.rule_id.to_json(): record
                 for record in frozen_ruleset.approvals}
    by_axis: Dict[Tuple[str, str, str], Any] = {}
    for definition in frozen_ruleset.rules():
        condition = definition.condition
        for phenotype in condition.phenotype.values:
            key = (condition.drug_canonical_key, condition.gene_canonical_key,
                   phenotype.value)
            by_axis.setdefault(key, []).append(definition)

    built: list = []
    for raw in declarations:
        drug = _require_key(raw.get("drug_id"), "DRUG:", "drug_id")
        expected = tuple(raw.get("expected_gene_keys") or ())
        axes = []
        for claim in raw.get("supported_axes") or ():
            gene = _require_key(claim.get("gene_id"), "GENE:", "gene_id")
            phenotype = claim.get("phenotype")
            if isinstance(phenotype, str):
                try:
                    phenotype = Phenotype(phenotype)
                except ValueError:
                    raise CoverageManifestError(
                        "%r is not a phenotype" % (phenotype,),
                        code="COVERAGE_MANIFEST_AXIS_INVALID",
                        location="$.supported_axes")
            key = (drug, gene, phenotype.value)
            candidates = by_axis.get(key, [])
            if not candidates:
                raise CoverageManifestError(
                    "axis %s is declared supported, but no validated member "
                    "rule of ruleset %s covers it. A declaration is a claim "
                    "about the ruleset, and this one is not true of it."
                    % (key, manifest.public_id.to_json()),
                    code="COVERAGE_MANIFEST_AXIS_UNSUPPORTED",
                    location="$.supported_axes",
                    detail={"axis": list(key)})
            if len(candidates) > 1:
                raise CoverageManifestError(
                    "axis %s is covered by %d member rules. Which one supports "
                    "the declaration is a question this builder must not answer "
                    "by picking; WP-11 reports overlapping rules as a blocking "
                    "conflict and it should have been resolved there."
                    % (key, len(candidates)),
                    code="COVERAGE_MANIFEST_AXIS_AMBIGUOUS",
                    location="$.supported_axes",
                    detail={"axis": list(key),
                            "rule_ids": sorted(item.rule_id.to_json()
                                               for item in candidates)})
            definition = candidates[0]
            record = approvals.get(definition.rule_id.to_json())
            if record is None or \
                    record.rule_content_hash != definition.content_hash():
                raise CoverageManifestError(
                    "rule %s covering axis %s carries no approval record "
                    "evidencing that this exact content was validated. A "
                    "coverage claim rests on validated rules and this "
                    "builder does not take membership as proof of validation "
                    "(SAFETY-INV-003)."
                    % (definition.rule_id.to_json(), key),
                    code="COVERAGE_MANIFEST_RULE_NOT_VALIDATED",
                    location="$.supported_axes",
                    detail={"axis": list(key),
                            "rule_id": definition.rule_id.to_json()})
            evidence = tuple(definition.provenance.evidence_record_uuids)
            if not evidence:
                raise CoverageManifestError(
                    "rule %s covering axis %s cites no evidence "
                    "(SAFETY-INV-006)"
                    % (definition.rule_id.to_json(), key),
                    code="COVERAGE_MANIFEST_EVIDENCE_MISSING",
                    location="$.supported_axes")
            if evidence_resolver is not None:
                unresolved = [item for item in evidence
                              if not evidence_resolver(item)]
                if unresolved:
                    raise CoverageManifestError(
                        "rule %s cites evidence that does not resolve in the "
                        "pinned build: %s"
                        % (definition.rule_id.to_json(),
                           ", ".join(sorted(unresolved))),
                        code="COVERAGE_MANIFEST_EVIDENCE_UNRESOLVABLE",
                        location="$.supported_axes",
                        detail={"unresolved": sorted(unresolved)})
            axes.append(SupportedAxis(
                drug_canonical_key=drug, gene_canonical_key=gene,
                phenotype=phenotype, rule_id=definition.rule_id.to_json(),
                rule_version=definition.rule_version,
                rule_content_hash=definition.content_hash(),
                evidence_references=evidence))
        built.append(CoverageDeclaration(
            drug_canonical_key=drug, expected_gene_keys=expected,
            supported_axes=tuple(axes),
            declaration_id=_require_text(raw.get("declaration_id"),
                                         "declaration_id"),
            declared_by=_require_text(raw.get("declared_by"), "declared_by"),
            declaration_provenance=_require_text(
                raw.get("declaration_provenance"), "declaration_provenance",
                20),
            conflict_references=tuple(raw.get("conflict_references") or ())))

    return RulesetCoverageManifest(
        coverage_schema_version=COVERAGE_MANIFEST_SCHEMA_VERSION,
        ruleset_public_id=manifest.public_id.to_json(),
        ruleset_version=manifest.ruleset_version,
        ruleset_content_hash=frozen_ruleset.ruleset_content_hash,
        dataset_public_id=manifest.dataset_public_id.to_json(),
        canonical_build_key=manifest.canonical_build_key,
        canonical_build_content_hash=manifest.canonical_build_content_hash,
        evidence_build_key=manifest.evidence_build_key,
        evidence_build_content_hash=manifest.evidence_build_content_hash,
        protocol_version=manifest.protocol_version,
        protocol_content_hash=manifest.protocol_content_hash,
        source_policy_version=manifest.source_policy_version,
        source_policy_content_hash=manifest.source_policy_content_hash,
        declarations=tuple(built), approval=approval)
