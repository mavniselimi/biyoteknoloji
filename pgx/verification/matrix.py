# -*- coding: utf-8 -*-
"""Which requirement is verified by which tests, and what nothing verifies.

The matrix is the part an auditor reads. It answers three questions, and the
third is the one that makes it worth building:

1. For each requirement, which tests exercise it?
2. For each category, is there anything in it at all?
3. **What is not covered?** A requirement whose selectors match no test, a
   critical test that serves no requirement, a safety invariant with nothing
   mapped to it, a category with nothing in it.

The third is why the matrix is computed from live discovery rather than
maintained by hand. A hand-written matrix answers question 1 and cannot answer
question 3, because a requirement whose tests were deleted still has a row.
Here, ``selectors`` are resolved against the real inventory on every build, so
the row empties itself and the emptiness is the finding.

Nothing here runs a test. The matrix says what *should* verify a requirement;
whether it did is a result, and results come from ``runner``. Keeping the two
apart is what stops "a test exists" from being rendered as "the requirement
holds".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Mapping, Tuple

from pgx.verification.inventory import Inventory
from pgx.verification.model import (
    Category,
    Criticality,
    Outcome,
    REQUIRED_CATEGORIES,
)
from pgx.verification.requirements import (
    REQUIREMENTS,
    SAFETY_INVARIANT_MAP,
    SAFETY_MAP_DISCLAIMER,
    Requirement,
    selectors_match,
)

__all__ = [
    "MATRIX_SCHEMA_VERSION",
    "RequirementCoverage",
    "CategoryCoverage",
    "Matrix",
    "build_matrix",
]

MATRIX_SCHEMA_VERSION = "pgx-wp19-requirement-matrix/1"


@dataclass(frozen=True)
class RequirementCoverage:
    """One requirement and the tests claimed to verify it."""

    requirement: Requirement
    test_ids: Tuple[str, ...]
    modules: Tuple[str, ...]
    #: Categories the matching tests fall into. A requirement covered only by
    #: BLOCKED categories is a requirement nothing executes for.
    categories: Tuple[Category, ...]

    @property
    def is_covered(self) -> bool:
        """Whether any test at all matches. Not whether any test passed."""
        return bool(self.test_ids)

    def as_document(self) -> Dict[str, object]:
        # Modules are listed; test identifiers are represented by a count and
        # a digest, for the same reason the inventory does it - see
        # ``pgx.verification.artifacts``. A renamed test still changes the
        # digest, so the row cannot go quietly out of date.
        from pgx.verification.artifacts import test_id_digest
        document = dict(self.requirement.as_document())
        document.update({
            "categories": [category.value for category in self.categories],
            "is_covered": self.is_covered,
            "module_count": len(self.modules),
            "modules": list(self.modules),
            "test_count": len(self.test_ids),
            "test_id_sha256": test_id_digest(self.test_ids),
        })
        return document


@dataclass(frozen=True)
class CategoryCoverage:
    """One category and what is in it."""

    category: Category
    test_ids: Tuple[str, ...]
    modules: Tuple[str, ...]
    #: What can be said before anything runs. ``MISSING`` when the category is
    #: empty; otherwise ``BLOCKED``, because "a test exists" is not "a test
    #: passed" and only an execution may upgrade this.
    static_outcome: Outcome

    def as_document(self) -> Dict[str, object]:
        from pgx.verification.artifacts import test_id_digest
        return {
            "category": self.category.value,
            "module_count": len(self.modules),
            "modules": list(self.modules),
            "static_outcome": self.static_outcome.value,
            "test_count": len(self.test_ids),
            "test_id_sha256": test_id_digest(self.test_ids),
        }


@dataclass(frozen=True)
class Matrix:
    """The full mapping, and everything it could not map."""

    requirements: Tuple[RequirementCoverage, ...]
    categories: Tuple[CategoryCoverage, ...]
    safety_map: Mapping[str, Tuple[str, ...]]
    #: Requirements whose selectors matched nothing. Each is a claim in the
    #: registry that no test supports.
    uncovered_requirements: Tuple[str, ...]
    #: Tests marked P0_CRITICAL that serve no requirement. Each is either a
    #: missing requirement or a mis-set criticality; both need a human.
    unmapped_critical_modules: Tuple[str, ...]
    #: Tests that serve no requirement and are not critical. Reported for
    #: completeness, not as a fault.
    unmapped_supporting_modules: Tuple[str, ...]
    #: Safety invariants with no test mapped. Mapping gaps, not gate failures.
    unmapped_safety_invariants: Tuple[str, ...]
    #: Safety-map selectors that match no module - a stale map entry.
    stale_safety_selectors: Tuple[str, ...]
    empty_categories: Tuple[str, ...]

    @property
    def is_complete(self) -> bool:
        """Every requirement has tests, every critical test has a requirement,
        and every required category has something in it.

        Deliberately does not consider the safety map: an unmapped invariant is
        a WP-20 gap, and letting it fail WP-19's completeness check would push
        this package into claiming a gate it does not own.
        """
        return not (self.uncovered_requirements
                    or self.unmapped_critical_modules
                    or self.empty_categories)

    def as_document(self) -> Dict[str, object]:
        return {
            "categories": [item.as_document() for item in self.categories],
            "empty_categories": list(self.empty_categories),
            "is_complete": self.is_complete,
            "matrix_schema_version": MATRIX_SCHEMA_VERSION,
            "requirements": [item.as_document() for item in self.requirements],
            "safety_invariant_map": {
                key: list(value)
                for key, value in sorted(self.safety_map.items())},
            "safety_map_disclaimer": SAFETY_MAP_DISCLAIMER,
            "stale_safety_selectors": list(self.stale_safety_selectors),
            "unmapped_critical_modules": list(self.unmapped_critical_modules),
            "unmapped_safety_invariants":
                list(self.unmapped_safety_invariants),
            "unmapped_supporting_modules":
                list(self.unmapped_supporting_modules),
            "uncovered_requirements": list(self.uncovered_requirements),
        }


def build_matrix(inventory: Inventory) -> Matrix:
    """Resolve every selector against ``inventory`` and report the gaps."""
    modules = sorted({entry.module for entry in inventory.entries})

    requirement_coverage: List[RequirementCoverage] = []
    uncovered: List[str] = []
    for requirement in REQUIREMENTS:
        matching = tuple(entry for entry in inventory.entries
                         if selectors_match(entry.module,
                                            requirement.selectors))
        coverage = RequirementCoverage(
            requirement=requirement,
            test_ids=tuple(sorted(entry.test_id for entry in matching)),
            modules=tuple(sorted({entry.module for entry in matching})),
            categories=tuple(sorted(
                {entry.category for entry in matching},
                key=lambda category: category.value)),
        )
        requirement_coverage.append(coverage)
        if not coverage.is_covered:
            uncovered.append(requirement.requirement_id)

    category_coverage: List[CategoryCoverage] = []
    empty: List[str] = []
    for category in REQUIRED_CATEGORIES:
        matching = tuple(entry for entry in inventory.entries
                         if entry.category is category)
        if not matching:
            empty.append(category.value)
        category_coverage.append(CategoryCoverage(
            category=category,
            test_ids=tuple(sorted(entry.test_id for entry in matching)),
            modules=tuple(sorted({entry.module for entry in matching})),
            static_outcome=(Outcome.MISSING if not matching
                            else Outcome.BLOCKED),
        ))

    unmapped_critical: List[str] = []
    unmapped_supporting: List[str] = []
    seen: Dict[str, Criticality] = {}
    for entry in inventory.entries:
        if entry.requirements:
            continue
        # Record the strongest criticality seen for the module: a module is
        # only supporting if every test in it is.
        current = seen.get(entry.module)
        if current is None or entry.criticality is Criticality.P0_CRITICAL:
            seen[entry.module] = entry.criticality
    for module, criticality in sorted(seen.items()):
        if criticality is Criticality.P0_CRITICAL:
            unmapped_critical.append(module)
        else:
            unmapped_supporting.append(module)

    unmapped_invariants: List[str] = []
    stale_selectors: List[str] = []
    for invariant, selectors in sorted(SAFETY_INVARIANT_MAP.items()):
        matched_any = False
        for selector in selectors:
            if any(selectors_match(module, (selector,)) for module in modules):
                matched_any = True
            else:
                stale_selectors.append("%s -> %s" % (invariant, selector))
        if not selectors or not matched_any:
            unmapped_invariants.append(invariant)

    return Matrix(
        requirements=tuple(requirement_coverage),
        categories=tuple(category_coverage),
        safety_map={key: tuple(value)
                    for key, value in SAFETY_INVARIANT_MAP.items()},
        uncovered_requirements=tuple(sorted(uncovered)),
        unmapped_critical_modules=tuple(unmapped_critical),
        unmapped_supporting_modules=tuple(unmapped_supporting),
        unmapped_safety_invariants=tuple(unmapped_invariants),
        stale_safety_selectors=tuple(sorted(stale_selectors)),
        empty_categories=tuple(empty),
    )
