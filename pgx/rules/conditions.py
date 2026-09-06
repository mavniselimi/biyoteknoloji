# -*- coding: utf-8 -*-
"""The declarative condition language (WP-11).

One kind of condition exists: ``PGX_AXIS`` - one canonical gene, one canonical
drug, and an explicit phenotype match. That is the whole language.

**Why it is this small.** A rule condition is a scientific claim that a
reviewer has to be able to check by reading it, and that an engine has to
evaluate identically every time. Both properties die the moment the language
can express something a person has to *interpret*. A regex, a wildcard, a
negation, a range or a boolean tree can all be written faster than they can be
reviewed, and each one lets a rule apply to cases nobody looked at. So none of
them exists here - not disabled, not discouraged: absent, with the parser
refusing them by name so the refusal is legible rather than accidental.

**Phenotype matching.** Two operators:

``EXACT``
    exactly one phenotype.

``ONE_OF``
    an explicitly enumerated, duplicate-free, non-empty set.

There is no third operator and no implicit expansion. ``SAFETY-INV-004`` is the
reason: the legacy matcher let ``RAPID`` and ``ULTRARAPID`` match each other,
silently applying rules outside the evidence that justified them. A rule that
applies to both says so, in a list, and a reviewer sees both names. This module
therefore never derives one phenotype from another, has no synonym table, no
prefix matching, and no ordinal comparison - and a test asserts the absence.

``INDETERMINATE`` is refused as a rule phenotype. It means "we could not
determine this", which is a statement about the input rather than a phenotype a
rule can be *about*; a rule keyed on it would be answering a question nobody
asked. Downstream that case is a coverage result, not a rule match.

**What this module does not do.** It does not evaluate a condition against a
patient. WP-11 ships the schema, canonicalisation, validation, an expansion
used only for comparing rules with each other, and a typed representation for
the engine. Matching is WP-12's.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, Iterable, Mapping, Sequence, Tuple

from pgx.domain.enums import Phenotype
from pgx.normalization.errors import NormalizationError
from pgx.normalization.models import EntityType, canonical_key_for
from pgx.normalization.normalize import (normalize_drug_name,
                                         normalize_gene_symbol)
from pgx.domain.hashing import sha256_digest
from pgx.domain.immutable import FrozenMapping, freeze_json
from pgx.rules.errors import ConditionGrammarError

__all__ = [
    "CONDITION_KIND",
    "CONDITION_SCHEMA_VERSION",
    "PHENOTYPE_OPERATORS",
    "PROHIBITED_CONDITION_CONSTRUCTS",
    "RULE_PHENOTYPES",
    "CanonicalAxis",
    "GeneRequirement",
    "JOINT_CONDITION_KIND",
    "JointRuleCondition",
    "PhenotypeMatch",
    "RuleCondition",
    "parse_condition",
]

#: Bumped when the grammar changes. A condition written under one version is
#: not readable under another without a deliberate migration, because "the
#: parser guessed" is not an acceptable answer about a clinical rule.
CONDITION_SCHEMA_VERSION = "pgx-rule-condition/1"

#: The only condition kind. Named as a constant so adding a second one is a
#: visible decision in this file rather than a string appearing in a caller.
JOINT_CONDITION_KIND = "PGX_JOINT_AXIS"
CONDITION_KIND = "PGX_AXIS"

#: The only two phenotype operators.
PHENOTYPE_OPERATORS: Tuple[str, ...] = ("EXACT", "ONE_OF")

#: Phenotypes a rule may be keyed on. ``INDETERMINATE`` is deliberately absent:
#: it describes a failure to determine the input, not a biological state a rule
#: can make a claim about.
RULE_PHENOTYPES: Tuple[Phenotype, ...] = (
    Phenotype.POOR,
    Phenotype.INTERMEDIATE,
    Phenotype.NORMAL,
    Phenotype.RAPID,
    Phenotype.ULTRARAPID,
)

#: Constructs refused by name, with the reason. Data rather than prose so the
#: parser, the schema and the tests cite one list, and so that adding a
#: construct means deleting a line somebody has to justify.
PROHIBITED_CONDITION_CONSTRUCTS: Mapping[str, str] = {
    "*": "a wildcard applies a rule to cases nobody reviewed",
    "ANY": "a catch-all applies a rule to cases nobody reviewed",
    "ALL": "a catch-all applies a rule to cases nobody reviewed",
    "DEFAULT": "a default case is a rule with no stated scope",
    "NOT": "a negation defines a rule by what it is not, which cannot be reviewed",
    "REGEX": "a regex is an expression language, not a reviewable claim",
    "MATCH": "pattern matching is an expression language",
    "RANGE": "a range over an unordered vocabulary has no defined meaning",
    "BETWEEN": "a range over an unordered vocabulary has no defined meaning",
    "LIKE": "fuzzy matching applies a rule to cases nobody reviewed",
    "IN_SET": "use ONE_OF, which requires every member to be listed",
    "EXPR": "an expression is code",
    "EVAL": "an expression is code",
    "SQL": "an expression is code",
    "TEMPLATE": "a template is evaluated, which makes it code",
    "AND": "a boolean tree is a language; one axis per rule keeps it reviewable",
    "OR": "a boolean tree is a language; one axis per rule keeps it reviewable",
}

#: Keys a condition mapping may carry. Anything else is refused rather than
#: ignored: a key the parser skips is a claim nobody checked and nobody sees.
#: Which WP-07 normaliser owns each key prefix. Spelled as a mapping so a
#: third entity type cannot be added here without saying how it is spelled.
_ENTITY_TYPES = {"GENE:": EntityType.GENE, "DRUG:": EntityType.DRUG}
_NORMALIZERS = {EntityType.GENE: normalize_gene_symbol,
                EntityType.DRUG: normalize_drug_name}

_CONDITION_KEYS = frozenset({"kind", "gene_id", "drug_id", "phenotype"})
_PHENOTYPE_KEYS = frozenset({"operator", "values"})


def _reject_construct(text: str, location: str) -> None:
    """Refuse a value that names a construct this grammar does not have."""
    folded = str(text).strip().upper()
    reason = PROHIBITED_CONDITION_CONSTRUCTS.get(folded)
    if reason is not None:
        raise ConditionGrammarError(
            "%s at %s is not part of this condition grammar: %s"
            % (folded, location, reason),
            code="RULE_COND_PROHIBITED_CONSTRUCT", location=location)


def _require_canonical_key(value: Any, prefix: str, field: str) -> str:
    """A canonical entity key, spelled exactly as WP-07 would allocate it.

    The test is idempotency under WP-07's own normaliser: a key is valid when
    re-normalising its entity name reproduces the key unchanged. WP-07 is
    imported rather than re-described here on purpose. A second copy of the
    grammar would drift from the first, and the day it did, a rule would name
    an entity the canonical dataset does not contain while looking perfectly
    well formed.

    It is what refuses ``GENE:CYP2D6 or any hepatic gene``: the remainder is
    not a gene symbol, so no allocation would ever have produced that key.
    Note what this check is *not* - it is spelling, not existence. Whether the
    entity exists in the canonical build is checked by the validator against
    the real dataset, because no amount of grammar can know that.
    """
    if not isinstance(value, str) or not value.strip():
        raise ConditionGrammarError(
            "%s must be a non-empty canonical key such as %sexample" % (field, prefix),
            code="RULE_COND_ENTITY_INVALID", location="$." + field)
    text = value.strip()
    _reject_construct(text, "$." + field)
    if not text.startswith(prefix):
        raise ConditionGrammarError(
            "%s must be a canonical key beginning %r, got %r. A rule names the "
            "entity WP-07 allocated, not a spelling a source happened to use."
            % (field, prefix, text),
            code="RULE_COND_ENTITY_INVALID", location="$." + field)
    remainder = text[len(prefix):]
    if not remainder or remainder != remainder.strip():
        raise ConditionGrammarError(
            "%s has an empty or padded entity name: %r" % (field, text),
            code="RULE_COND_ENTITY_INVALID", location="$." + field)
    entity_type = _ENTITY_TYPES[prefix]
    try:
        allocated = canonical_key_for(
            entity_type, _NORMALIZERS[entity_type](remainder))
    except NormalizationError as error:
        raise ConditionGrammarError(
            "%s is not a canonical key WP-07 could have allocated: %s"
            % (field, error),
            code="RULE_COND_ENTITY_INVALID", location="$." + field)
    if allocated != text:
        raise ConditionGrammarError(
            "%s is spelled %r, but WP-07 would allocate %r for that entity "
            "name. A rule names the allocated key exactly."
            % (field, text, allocated),
            code="RULE_COND_ENTITY_INVALID", location="$." + field)
    return text


@dataclass(frozen=True, slots=True)
class PhenotypeMatch:
    """An explicit phenotype match: one value, or an enumerated set.

    ``values`` is a tuple in canonical order, and the canonical order is the
    declaration order of :data:`RULE_PHENOTYPES` rather than alphabetical. That
    is not cosmetic: a reader scanning ``[POOR, INTERMEDIATE, NORMAL]`` sees the
    metaboliser spectrum in the order it is usually discussed, and two rules
    listing the same phenotypes in different source order produce the same
    canonical form and therefore the same hash.
    """

    operator: str
    values: Tuple[Phenotype, ...]

    def __post_init__(self) -> None:
        if self.operator not in PHENOTYPE_OPERATORS:
            raise ConditionGrammarError(
                "phenotype operator %r is not one of %s"
                % (self.operator, ", ".join(PHENOTYPE_OPERATORS)),
                code="RULE_COND_OPERATOR_UNSUPPORTED",
                location="$.phenotype.operator")
        if not self.values:
            raise ConditionGrammarError(
                "a phenotype match lists at least one phenotype; an empty set "
                "matches nothing and hides that fact",
                code="RULE_COND_PHENOTYPE_EMPTY", location="$.phenotype.values")
        for index, value in enumerate(self.values):
            if not isinstance(value, Phenotype):
                raise ConditionGrammarError(
                    "phenotype[%d] must be a Phenotype, got %r"
                    % (index, type(value).__name__),
                    code="RULE_COND_PHENOTYPE_UNSUPPORTED",
                    location="$.phenotype.values[%d]" % index)
            if value not in RULE_PHENOTYPES:
                raise ConditionGrammarError(
                    "%s may not key a rule. It describes what could not be "
                    "determined about an input, not a state a rule can make a "
                    "claim about; downstream that is a coverage result."
                    % value.value,
                    code="RULE_COND_PHENOTYPE_UNSUPPORTED",
                    location="$.phenotype.values[%d]" % index)
        if len(set(self.values)) != len(self.values):
            duplicates = sorted({value.value for value in self.values
                                 if self.values.count(value) > 1})
            raise ConditionGrammarError(
                "phenotype list repeats %s. A repeated member says nothing "
                "extra and makes two spellings of one rule."
                % ", ".join(duplicates),
                code="RULE_COND_PHENOTYPE_DUPLICATE",
                location="$.phenotype.values")
        if self.operator == "EXACT" and len(self.values) != 1:
            raise ConditionGrammarError(
                "EXACT names exactly one phenotype, got %d. A rule applying to "
                "several says so with ONE_OF, where every member is visible."
                % len(self.values),
                code="RULE_COND_EXACT_CARDINALITY",
                location="$.phenotype.values")
        # Canonical order, computed once at construction.
        order = {value: index for index, value in enumerate(RULE_PHENOTYPES)}
        object.__setattr__(self, "values",
                           tuple(sorted(self.values, key=lambda item: order[item])))

    @property
    def phenotypes(self) -> FrozenSet[Phenotype]:
        """The matched set, for comparison between rules only.

        Explicitly not a matcher. WP-12 decides whether a patient's phenotype
        is in this set; WP-11 uses it to ask whether two *rules* overlap.
        """
        return frozenset(self.values)

    def to_json(self) -> Dict[str, Any]:
        return {"operator": self.operator,
                "values": [value.value for value in self.values]}


@dataclass(frozen=True, slots=True)
class RuleCondition:
    """One canonical gene, one canonical drug, one explicit phenotype match."""

    gene_canonical_key: str
    drug_canonical_key: str
    phenotype: PhenotypeMatch
    kind: str = CONDITION_KIND
    condition_schema_version: str = CONDITION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.kind != CONDITION_KIND:
            raise ConditionGrammarError(
                "condition kind %r is not supported; the only kind is %r"
                % (self.kind, CONDITION_KIND),
                code="RULE_COND_KIND_UNSUPPORTED", location="$.kind")
        if self.condition_schema_version != CONDITION_SCHEMA_VERSION:
            raise ConditionGrammarError(
                "condition schema version %r is not %r; this parser will not "
                "guess at the difference"
                % (self.condition_schema_version, CONDITION_SCHEMA_VERSION),
                code="RULE_COND_SCHEMA_VERSION", location="$.condition_schema_version")
        object.__setattr__(self, "gene_canonical_key", _require_canonical_key(
            self.gene_canonical_key, "GENE:", "gene_id"))
        object.__setattr__(self, "drug_canonical_key", _require_canonical_key(
            self.drug_canonical_key, "DRUG:", "drug_id"))
        if not isinstance(self.phenotype, PhenotypeMatch):
            raise ConditionGrammarError(
                "phenotype must be a PhenotypeMatch", location="$.phenotype")

    # -- canonical form -------------------------------------------------

    def to_json(self) -> Dict[str, Any]:
        """The canonical serialised form. Key order is fixed by the hasher."""
        return {
            "kind": self.kind,
            "condition_schema_version": self.condition_schema_version,
            "gene_id": self.gene_canonical_key,
            "drug_id": self.drug_canonical_key,
            "phenotype": self.phenotype.to_json(),
        }

    def frozen(self) -> FrozenMapping:
        """A deeply immutable mapping, for storing on a frozen domain object."""
        return freeze_json(self.to_json())

    def content_hash(self) -> str:
        """Digest of the canonical form.

        Deterministic and order-independent: two conditions listing the same
        phenotypes in different order canonicalise to one form and hash alike.
        """
        return sha256_digest(self.to_json())

    # -- comparison support (rules against rules, never against a patient) --

    def expand(self) -> Tuple["CanonicalAxis", ...]:
        """Every ``(gene, drug, phenotype)`` axis this condition covers.

        Used only to compare rules with each other - overlap, duplication,
        conflicting outcomes. Expansion is not evaluation: nothing here is
        given a patient, and the result is a set of axes, not a decision.
        """
        return tuple(
            CanonicalAxis(gene_canonical_key=self.gene_canonical_key,
                          drug_canonical_key=self.drug_canonical_key,
                          phenotype=value)
            for value in self.phenotype.values)

    def __str__(self) -> str:
        return "%s/%s %s{%s}" % (
            self.gene_canonical_key, self.drug_canonical_key,
            self.phenotype.operator,
            ",".join(value.value for value in self.phenotype.values))


@dataclass(frozen=True, slots=True)
class GeneRequirement:
    """One gene of a joint condition, and the phenotypes it accepts.

    A joint condition is a tuple of these plus one drug. Each carries its own
    :class:`PhenotypeMatch`, so the operators available on one axis are exactly
    the operators available on any axis - there is no weaker grammar hiding
    inside the joint form.
    """

    gene_canonical_key: str
    phenotype: PhenotypeMatch

    def __post_init__(self) -> None:
        object.__setattr__(self, "gene_canonical_key", _require_canonical_key(
            self.gene_canonical_key, "GENE:", "gene_id"))
        if not isinstance(self.phenotype, PhenotypeMatch):
            raise ConditionGrammarError(
                "phenotype must be a PhenotypeMatch",
                location="$.genes[].phenotype")

    def to_json(self) -> Dict[str, Any]:
        return {"gene_id": self.gene_canonical_key,
                "phenotype": self.phenotype.to_json()}


@dataclass(frozen=True, slots=True)
class JointRuleCondition:
    """Several canonical genes, one canonical drug, one explicit combination.

    **Why this exists.** CPIC's tricyclic antidepressant guideline states an
    amitriptyline recommendation as a two-dimensional CYP2C19 x CYP2D6 table,
    and that table is *not* the pointwise combination of its two single-gene
    tables. Encoding the two axes separately and taking the strongest of the
    two answers happens to land near the guideline for most cells, and "happens
    to" is not a property a pharmacogenomic rule may rest on.

    **What it refuses.** Every gene it names must be present and must match.
    There is no partial evaluation, no fallback to a single gene, and no
    default for an absent axis - an absent gene means the condition does not
    apply, which downstream is a coverage answer rather than a finding. That is
    the whole reason a joint condition is a distinct type instead of a flag on
    :class:`RuleCondition`: a caller that has not been taught about joint
    conditions cannot accidentally evaluate one as if it were single-gene,
    because it is not the same class.

    **What it does not add.** The same phenotype operators, the same refusal of
    wildcards, negation, ranges and implicit expansion, the same refusal of
    ``INDETERMINATE``. A joint condition is more specific than a simple one,
    never looser.
    """

    genes: Tuple[GeneRequirement, ...]
    drug_canonical_key: str
    kind: str = JOINT_CONDITION_KIND
    condition_schema_version: str = CONDITION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.kind != JOINT_CONDITION_KIND:
            raise ConditionGrammarError(
                "joint condition kind %r is not supported; the only kind is %r"
                % (self.kind, JOINT_CONDITION_KIND),
                code="RULE_COND_KIND_UNSUPPORTED", location="$.kind")
        if self.condition_schema_version != CONDITION_SCHEMA_VERSION:
            raise ConditionGrammarError(
                "condition schema version %r is not %r; this parser will not "
                "guess at the difference"
                % (self.condition_schema_version, CONDITION_SCHEMA_VERSION),
                code="RULE_COND_SCHEMA_VERSION",
                location="$.condition_schema_version")
        requirements = tuple(self.genes or ())
        if len(requirements) < 2:
            raise ConditionGrammarError(
                "a joint condition names at least two genes; one gene is a "
                "simple condition and must be written as one, so that nothing "
                "reading a rule has to ask which kind it really is",
                code="RULE_COND_JOINT_TOO_FEW_GENES", location="$.genes")
        for item in requirements:
            if not isinstance(item, GeneRequirement):
                raise ConditionGrammarError(
                    "joint condition genes are GeneRequirement values",
                    location="$.genes")
        keys = [item.gene_canonical_key for item in requirements]
        if len(set(keys)) != len(keys):
            raise ConditionGrammarError(
                "a joint condition names each gene once; a repeated gene "
                "would let one axis be constrained twice, and the two "
                "constraints could disagree",
                code="RULE_COND_JOINT_GENE_REPEATED", location="$.genes")
        # Canonical order, so two rules naming the same genes in different
        # source order produce one form and therefore one hash.
        object.__setattr__(self, "genes",
                           tuple(sorted(requirements,
                                        key=lambda item:
                                        item.gene_canonical_key)))
        object.__setattr__(self, "drug_canonical_key", _require_canonical_key(
            self.drug_canonical_key, "DRUG:", "drug_id"))

    @property
    def gene_keys(self) -> Tuple[str, ...]:
        return tuple(item.gene_canonical_key for item in self.genes)

    @property
    def joint_axis_key(self) -> str:
        """The identity of the axis this condition is about.

        Genes joined by ``+`` in canonical order, then the drug. Distinct by
        construction from any single-gene axis key, so a joint axis and a
        simple axis can never collide in a coverage table.
        """
        return "%s|%s" % ("+".join(self.gene_keys), self.drug_canonical_key)

    def to_json(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "condition_schema_version": self.condition_schema_version,
            "drug_id": self.drug_canonical_key,
            "genes": [item.to_json() for item in self.genes],
        }

    def frozen(self) -> FrozenMapping:
        return freeze_json(self.to_json())

    def content_hash(self) -> str:
        return sha256_digest(self.to_json())

    def matches(self, observed: Mapping[str, Phenotype]) -> bool:
        """Whether an observed phenotype map satisfies every named gene.

        ``observed`` maps canonical gene key to phenotype. A gene this
        condition names that is absent from the map returns ``False`` - not an
        error and not a partial match. The caller decides what an absent gene
        means for coverage; this only answers whether the rule applies.
        """
        for item in self.genes:
            value = observed.get(item.gene_canonical_key)
            if value is None or value not in item.phenotype.phenotypes:
                return False
        return True

    def expand(self) -> Tuple[Tuple["CanonicalAxis", ...], ...]:
        """Every combination this condition covers, for rule-to-rule comparison.

        Returns tuples of axes rather than axes, because a joint condition
        covers *combinations*: two rules overlap only when they cover the same
        combination, not merely when they mention the same gene.
        """
        import itertools
        per_gene = [
            [CanonicalAxis(gene_canonical_key=item.gene_canonical_key,
                           drug_canonical_key=self.drug_canonical_key,
                           phenotype=value)
             for value in item.phenotype.values]
            for item in self.genes]
        return tuple(tuple(combination)
                     for combination in itertools.product(*per_gene))

    def __str__(self) -> str:
        return "%s %s" % (self.drug_canonical_key, " & ".join(
            "%s%s{%s}" % (item.gene_canonical_key, item.phenotype.operator,
                          ",".join(v.value for v in item.phenotype.values))
            for item in self.genes))


@dataclass(frozen=True, slots=True)
class CanonicalAxis:
    """One fully expanded ``(gene, drug, phenotype)`` triple.

    A comparison key, not a rule and not a finding.

    Deliberately **not** ``order=True``. Dataclass ordering would compare the
    ``Phenotype`` members with ``<``, and :class:`~pgx.domain.enums.Phenotype`
    refuses that: the values are a vocabulary, not a scale, and comparing
    ``POOR < RAPID`` as magnitudes is a domain error the enum exists to catch.
    Sorting therefore goes through :meth:`sort_key`, which orders phenotypes by
    their declaration index - a presentation choice, carrying no claim that one
    is greater than another.
    """

    gene_canonical_key: str
    drug_canonical_key: str
    phenotype: Phenotype

    def sort_key(self) -> Tuple[Any, ...]:
        """Deterministic ordering that makes no magnitude claim."""
        order = {value: index for index, value in enumerate(RULE_PHENOTYPES)}
        return (self.gene_canonical_key, self.drug_canonical_key,
                order.get(self.phenotype, len(RULE_PHENOTYPES)),
                self.phenotype.value)

    def __lt__(self, other: "CanonicalAxis") -> bool:
        if not isinstance(other, CanonicalAxis):
            return NotImplemented
        return self.sort_key() < other.sort_key()

    def to_json(self) -> Dict[str, Any]:
        return {
            "gene_id": self.gene_canonical_key,
            "drug_id": self.drug_canonical_key,
            "phenotype": self.phenotype.value,
        }

    def __str__(self) -> str:
        return "%s|%s|%s" % (self.gene_canonical_key, self.drug_canonical_key,
                             self.phenotype.value)


def parse_condition(payload: Any) -> RuleCondition:
    """Parse a serialised condition, refusing everything the grammar lacks.

    Unknown keys are an error rather than an omission. A parser that ignored
    ``{"regex": "CYP2.*"}`` would accept a rule whose author believed it meant
    something, store a condition that means something else, and give both a
    hash that says they agree.
    """
    if not isinstance(payload, Mapping):
        raise ConditionGrammarError(
            "a condition is a JSON object, got %r" % type(payload).__name__,
            code="RULE_COND_NOT_OBJECT")

    unknown = sorted(set(payload) - _CONDITION_KEYS - {"condition_schema_version"})
    if unknown:
        hints = []
        for key in unknown:
            reason = PROHIBITED_CONDITION_CONSTRUCTS.get(key.strip().upper())
            hints.append("%s%s" % (key, " (%s)" % reason if reason else ""))
        raise ConditionGrammarError(
            "condition carries key(s) this grammar does not have: %s. Permitted "
            "keys are %s." % (", ".join(hints), ", ".join(sorted(_CONDITION_KEYS))),
            code="RULE_COND_UNKNOWN_KEY")

    for name in ("kind", "gene_id", "drug_id", "phenotype"):
        if name not in payload:
            raise ConditionGrammarError(
                "condition is missing %r" % name,
                code="RULE_COND_MISSING_KEY", location="$." + name)

    kind = payload["kind"]
    if not isinstance(kind, str):
        raise ConditionGrammarError("kind must be a string",
                                    code="RULE_COND_KIND_UNSUPPORTED",
                                    location="$.kind")
    _reject_construct(kind, "$.kind")
    if kind != CONDITION_KIND:
        raise ConditionGrammarError(
            "condition kind %r is not supported; the only kind is %r"
            % (kind, CONDITION_KIND),
            code="RULE_COND_KIND_UNSUPPORTED", location="$.kind")

    version = payload.get("condition_schema_version", CONDITION_SCHEMA_VERSION)
    if version != CONDITION_SCHEMA_VERSION:
        raise ConditionGrammarError(
            "condition schema version %r is not %r" % (version, CONDITION_SCHEMA_VERSION),
            code="RULE_COND_SCHEMA_VERSION",
            location="$.condition_schema_version")

    phenotype = payload["phenotype"]
    if not isinstance(phenotype, Mapping):
        raise ConditionGrammarError(
            "phenotype must be an object with an operator and values",
            code="RULE_COND_PHENOTYPE_INVALID", location="$.phenotype")
    unknown_pheno = sorted(set(phenotype) - _PHENOTYPE_KEYS)
    if unknown_pheno:
        raise ConditionGrammarError(
            "phenotype carries key(s) this grammar does not have: %s"
            % ", ".join(unknown_pheno),
            code="RULE_COND_UNKNOWN_KEY", location="$.phenotype")
    for name in ("operator", "values"):
        if name not in phenotype:
            raise ConditionGrammarError(
                "phenotype is missing %r" % name,
                code="RULE_COND_MISSING_KEY", location="$.phenotype." + name)

    operator = phenotype["operator"]
    if not isinstance(operator, str):
        raise ConditionGrammarError(
            "phenotype operator must be a string",
            code="RULE_COND_OPERATOR_UNSUPPORTED", location="$.phenotype.operator")
    _reject_construct(operator, "$.phenotype.operator")
    if operator not in PHENOTYPE_OPERATORS:
        raise ConditionGrammarError(
            "phenotype operator %r is not one of %s. There is no wildcard, "
            "range, negation or pattern operator."
            % (operator, ", ".join(PHENOTYPE_OPERATORS)),
            code="RULE_COND_OPERATOR_UNSUPPORTED", location="$.phenotype.operator")

    raw_values = phenotype["values"]
    if isinstance(raw_values, str) or not isinstance(raw_values, Sequence):
        raise ConditionGrammarError(
            "phenotype values must be a list of phenotype names, got %r"
            % type(raw_values).__name__,
            code="RULE_COND_PHENOTYPE_INVALID", location="$.phenotype.values")

    parsed = []
    for index, item in enumerate(raw_values):
        location = "$.phenotype.values[%d]" % index
        if not isinstance(item, str):
            raise ConditionGrammarError(
                "phenotype value must be a string, got %r" % type(item).__name__,
                code="RULE_COND_PHENOTYPE_UNSUPPORTED", location=location)
        _reject_construct(item, location)
        try:
            parsed.append(Phenotype(item.strip()))
        except ValueError:
            raise ConditionGrammarError(
                "%r is not a phenotype in this project's vocabulary (%s)"
                % (item, ", ".join(value.value for value in RULE_PHENOTYPES)),
                code="RULE_COND_PHENOTYPE_UNSUPPORTED", location=location) from None

    return RuleCondition(
        gene_canonical_key=payload["gene_id"],
        drug_canonical_key=payload["drug_id"],
        phenotype=PhenotypeMatch(operator=operator, values=tuple(parsed)),
        kind=kind)
