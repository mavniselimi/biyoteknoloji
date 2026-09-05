# -*- coding: utf-8 -*-
"""The strict five-step entity resolver (WP-07).

Standard library plus :mod:`pgx.normalization`.

**The order is the contract** (``architecture.md`` 8.3):

1. exact canonical external ID;
2. exact normalised preferred name or gene symbol;
3. exact **APPROVED** alias;
4. unique exact external cross-reference;
5. unresolved, into the review queue.

At every stage: zero candidates advances to the next stage, exactly one
resolves and stops, **two or more stops immediately as ambiguous**. A later
stage never runs after an earlier one found an ambiguity, because doing so
would let a coincidental uniqueness downstream silently settle a genuine
collision upstream.

**What this resolver will not do**, each absence enforced by a test:

* rank candidates, or score them;
* return ``results[0]``, the earliest-created row, the smallest UUID, the
  alphabetically first name or the highest source score;
* match on a substring, an edit distance, a phonetic key or an embedding;
* resolve through an alias that is merely observed rather than approved;
* mint an identity for something it could not find.

The legacy resolver did the first two of those, which is the defect this work
package exists to remove; the rest have never been permitted.

**No side effects.** ``resolve`` reads a catalog and returns a record. It does
not create entities, does not allocate UUIDs and does not write a queue item -
the caller does that with what it returns, so a resolution can be re-run
without changing anything.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from pgx.normalization.errors import NormalizationError
from pgx.normalization.models import (
    CanonicalEntity,
    EntityType,
    RawLocator,
    ReasonCode,
    ResolutionMethod,
    ResolutionOutcome,
    ResolutionStatus,
)
from pgx.normalization.normalize import (
    ExternalIdentifier,
    normalize_drug_name,
    normalize_external_id,
    normalize_gene_symbol,
)

__all__ = [
    "RESOLVER_POLICY_VERSION",
    "CanonicalCatalog",
    "EntityResolver",
]

#: Bumped when the order or the matching rules change. Recorded in the
#: canonical manifest: a build is only comparable with one resolved under the
#: same policy.
RESOLVER_POLICY_VERSION = "pgx-resolver/1"

#: Which reason code an ambiguity at each stage reports.
_AMBIGUOUS_REASON = {
    ResolutionMethod.EXTERNAL_ID: ReasonCode.AMBIGUOUS_EXTERNAL_ID,
    ResolutionMethod.PREFERRED_NAME: ReasonCode.AMBIGUOUS_PREFERRED_NAME,
    ResolutionMethod.APPROVED_ALIAS: ReasonCode.AMBIGUOUS_APPROVED_ALIAS,
    ResolutionMethod.CROSS_REFERENCE: ReasonCode.AMBIGUOUS_CROSS_REFERENCE,
}

_MATCHED_REASON = {
    ResolutionMethod.EXTERNAL_ID: ReasonCode.MATCHED_EXTERNAL_ID,
    ResolutionMethod.PREFERRED_NAME: ReasonCode.MATCHED_PREFERRED_NAME,
    ResolutionMethod.APPROVED_ALIAS: ReasonCode.MATCHED_APPROVED_ALIAS,
    ResolutionMethod.CROSS_REFERENCE: ReasonCode.MATCHED_CROSS_REFERENCE,
}


class CanonicalCatalog:
    """An immutable index of canonical entities, built once and only read.

    Every index maps a key to a **sorted tuple of canonical keys**, never to a
    single entity. That shape is the point: a lookup that returned one entity
    would have had to choose between two, and there is nowhere in this class
    where such a choice could be made visible.

    The indexes are built eagerly so that "two entities share this name" is a
    fact about the catalog rather than a race between two queries.
    """

    def __init__(self, entities: Iterable[CanonicalEntity]) -> None:
        by_key: Dict[str, CanonicalEntity] = {}
        by_external: Dict[str, List[str]] = {}
        by_name: Dict[Tuple[str, str], List[str]] = {}
        by_alias: Dict[Tuple[str, str], List[str]] = {}

        for entity in entities:
            if entity.canonical_key in by_key:
                raise ValueError(
                    "duplicate canonical key %r in the catalog; a canonical key "
                    "names exactly one entity" % entity.canonical_key)
            by_key[entity.canonical_key] = entity
            for identifier in entity.external_ids:
                by_external.setdefault(identifier.to_json(), []).append(
                    entity.canonical_key)
            by_name.setdefault(
                (entity.entity_type.value, entity.normalized_value), []
            ).append(entity.canonical_key)
            for alias in entity.approved_aliases:
                by_alias.setdefault(
                    (entity.entity_type.value, alias.normalized_alias), []
                ).append(entity.canonical_key)

        self._by_key = dict(by_key)
        self._by_external = {k: tuple(sorted(set(v))) for k, v in by_external.items()}
        self._by_name = {k: tuple(sorted(set(v))) for k, v in by_name.items()}
        self._by_alias = {k: tuple(sorted(set(v))) for k, v in by_alias.items()}

    def __len__(self) -> int:
        return len(self._by_key)

    @property
    def canonical_keys(self) -> Tuple[str, ...]:
        return tuple(sorted(self._by_key))

    def get(self, canonical_key: str) -> Optional[CanonicalEntity]:
        return self._by_key.get(canonical_key)

    def entities_of(self, entity_type: EntityType) -> Tuple[CanonicalEntity, ...]:
        return tuple(sorted(
            (entity for entity in self._by_key.values()
             if entity.entity_type is entity_type),
            key=lambda item: item.canonical_key))

    # -- lookups: each returns every candidate, always ---------------------

    def by_external_id(self, identifier: ExternalIdentifier) -> Tuple[str, ...]:
        """Every entity carrying this exact namespaced identifier."""
        return self._by_external.get(identifier.to_json(), ())

    def by_normalized_value(self, entity_type: EntityType,
                            normalized_value: str) -> Tuple[str, ...]:
        """Every entity whose canonical symbol or name is exactly this."""
        return self._by_name.get((entity_type.value, normalized_value), ())

    def by_approved_alias(self, entity_type: EntityType,
                          normalized_alias: str) -> Tuple[str, ...]:
        """Every entity carrying this alias **with APPROVED status**.

        A pending, rejected or deprecated alias is not in this index at all, so
        there is no code path by which one could resolve.
        """
        return self._by_alias.get((entity_type.value, normalized_alias), ())

    def by_any_external_value(self, entity_type: EntityType,
                              value: str) -> Tuple[str, ...]:
        """Every entity of this type carrying ``value`` in **any** namespace.

        Stage four, and the only place a bare value crosses namespaces - which
        is exactly why it is last and why more than one hit is an ambiguity
        rather than a match. Two namespaces agreeing on a string is a weaker
        fact than either agreeing with itself.
        """
        found = []
        for key, entity in self._by_key.items():
            if entity.entity_type is not entity_type:
                continue
            if any(identifier.value == value for identifier in entity.external_ids):
                found.append(key)
        return tuple(sorted(found))


class EntityResolver:
    """Resolves submitted values against a catalog. Reads only.

    Args:
        catalog: the canonical entities to resolve against.
    """

    policy_version = RESOLVER_POLICY_VERSION

    def __init__(self, catalog: CanonicalCatalog) -> None:
        self._catalog = catalog

    @property
    def catalog(self) -> CanonicalCatalog:
        return self._catalog

    def resolve(
        self,
        entity_type: EntityType,
        submitted_value: object,
        external_id: Optional[Tuple[str, str]] = None,
        locator: Optional[RawLocator] = None,
    ) -> ResolutionOutcome:
        """Run the five stages in order and return the first decisive answer.

        Args:
            entity_type: gene or drug.
            submitted_value: the value as the source wrote it. Kept verbatim in
                the outcome whatever happens to it.
            external_id: an optional ``(namespace, value)`` pair the source
                supplied. Stage one uses it; its absence simply skips that
                stage rather than failing.
            locator: where the value was read from, carried into the outcome so
                a queue item can be traced back without a second lookup.
        """
        normalized, invalid = self._normalize(entity_type, submitted_value)
        if invalid is not None:
            return invalid

        # -- stage 1: exact canonical external ID -------------------------
        if external_id is not None:
            outcome = self._stage_external_id(
                entity_type, submitted_value, normalized, external_id, locator)
            if outcome is not None:
                return outcome

        # -- stage 2: exact normalised preferred name / symbol -------------
        candidates = self._catalog.by_normalized_value(entity_type, normalized)
        outcome = self._decide(
            ResolutionMethod.PREFERRED_NAME, entity_type, submitted_value,
            normalized, candidates, locator,
            matched_field="normalized_symbol" if entity_type is EntityType.GENE
            else "normalized_name")
        if outcome is not None:
            return outcome

        # -- stage 3: exact APPROVED alias ---------------------------------
        candidates = self._catalog.by_approved_alias(entity_type, normalized)
        outcome = self._decide(
            ResolutionMethod.APPROVED_ALIAS, entity_type, submitted_value,
            normalized, candidates, locator, matched_field="approved_alias")
        if outcome is not None:
            return outcome

        # -- stage 4: unique exact external cross-reference -----------------
        candidates = self._catalog.by_any_external_value(entity_type, normalized)
        outcome = self._decide(
            ResolutionMethod.CROSS_REFERENCE, entity_type, submitted_value,
            normalized, candidates, locator, matched_field="external_id_value")
        if outcome is not None:
            return outcome

        # -- stage 5: unresolved --------------------------------------------
        return ResolutionOutcome(
            entity_type=entity_type,
            submitted_value=str(submitted_value),
            normalized_value=normalized,
            status=ResolutionStatus.UNRESOLVED,
            method=ResolutionMethod.NONE,
            reason=ReasonCode.NO_CANDIDATE_FOUND,
            locator=locator,
            detail=("no exact match at any stage. No fuzzy, substring or "
                    "distance-based fallback exists, so this value goes to "
                    "review rather than to a guess."))

    def resolve_reference(
        self,
        entity_type: EntityType,
        submitted_value: object,
        external_id: Optional[Tuple[str, str]] = None,
        locator: Optional[RawLocator] = None,
    ) -> ResolutionOutcome:
        """Resolve a reference that the catalog is expected to satisfy.

        Identical to :meth:`resolve` except that an unresolved value is
        reported as ``BROKEN_REFERENCE`` rather than ``UNRESOLVED``. The two
        are genuinely different findings: an unknown value submitted for
        lookup is a gap, whereas a relationship pointing at an entity the
        dataset does not contain is a broken graph.
        """
        outcome = self.resolve(entity_type, submitted_value, external_id, locator)
        if outcome.status is not ResolutionStatus.UNRESOLVED:
            return outcome
        return ResolutionOutcome(
            entity_type=outcome.entity_type,
            submitted_value=outcome.submitted_value,
            normalized_value=outcome.normalized_value,
            status=ResolutionStatus.BROKEN_REFERENCE,
            method=ResolutionMethod.NONE,
            reason=ReasonCode.REFERENCED_ENTITY_ABSENT,
            locator=locator,
            detail=("a relationship references this entity, and the canonical "
                    "catalog does not contain it"))

    # -- internals ---------------------------------------------------------

    def _normalize(self, entity_type: EntityType, submitted_value: object):
        """Return ``(normalized, None)`` or ``(None, invalid_outcome)``."""
        if submitted_value is None or (isinstance(submitted_value, str)
                                       and not submitted_value.strip()):
            return None, ResolutionOutcome(
                entity_type=entity_type,
                submitted_value="" if submitted_value is None else str(submitted_value),
                normalized_value=None,
                status=ResolutionStatus.INVALID_INPUT,
                method=ResolutionMethod.NONE,
                reason=ReasonCode.MISSING_VALUE,
                detail="the source supplied no value for this reference")
        try:
            if entity_type is EntityType.GENE:
                return normalize_gene_symbol(submitted_value), None
            return normalize_drug_name(submitted_value), None
        except NormalizationError as exc:
            return None, ResolutionOutcome(
                entity_type=entity_type,
                submitted_value=str(submitted_value),
                normalized_value=None,
                status=ResolutionStatus.INVALID_INPUT,
                method=ResolutionMethod.NONE,
                reason=ReasonCode.NOT_NORMALIZABLE,
                detail=str(exc))

    def _stage_external_id(self, entity_type, submitted_value, normalized,
                           external_id, locator):
        namespace, value = external_id
        try:
            identifier, problem = normalize_external_id(namespace, value)
        except NormalizationError as exc:
            return ResolutionOutcome(
                entity_type=entity_type,
                submitted_value=str(submitted_value),
                normalized_value=normalized,
                status=ResolutionStatus.INVALID_INPUT,
                method=ResolutionMethod.EXTERNAL_ID,
                reason=ReasonCode.NOT_NORMALIZABLE,
                locator=locator, detail=str(exc))
        candidates = self._catalog.by_external_id(identifier)
        return self._decide(
            ResolutionMethod.EXTERNAL_ID, entity_type, submitted_value,
            normalized, candidates, locator,
            matched_field=identifier.namespace,
            detail=problem)

    @staticmethod
    def _decide(method, entity_type, submitted_value, normalized, candidates,
                locator, matched_field=None, detail=None):
        """Turn a candidate set into an outcome, or ``None`` to try the next stage.

        Three cases and no fourth. There is deliberately no branch that
        narrows, ranks or prefers: ``len(candidates) > 1`` returns immediately
        with every candidate attached.
        """
        if not candidates:
            return None
        if len(candidates) == 1:
            # Unpacked, never indexed. ``candidates[0]`` and "the only
            # candidate" are the same expression written two ways, and only
            # one of them still raises if the guard above is ever weakened -
            # which is the exact edit that would reintroduce the legacy defect.
            (only_candidate,) = candidates
            return ResolutionOutcome(
                entity_type=entity_type,
                submitted_value=str(submitted_value),
                normalized_value=normalized,
                status=ResolutionStatus.RESOLVED,
                method=method,
                reason=_MATCHED_REASON[method],
                canonical_key=only_candidate,
                matched_field=matched_field,
                locator=locator,
                detail=detail)
        return ResolutionOutcome(
            entity_type=entity_type,
            submitted_value=str(submitted_value),
            normalized_value=normalized,
            status=ResolutionStatus.AMBIGUOUS,
            method=method,
            reason=_AMBIGUOUS_REASON[method],
            candidate_keys=tuple(candidates),
            matched_field=matched_field,
            locator=locator,
            detail=("%d candidates matched at the %s stage. Resolution stops "
                    "here: a later stage must not break an ambiguity found by "
                    "an earlier one." % (len(candidates), method.value)))
