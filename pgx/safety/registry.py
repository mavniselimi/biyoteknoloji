# -*- coding: utf-8 -*-
"""Loading the invariant registry, and refusing it when it is wrong.

Every check here fails **closed**. That is the one design decision this module
makes, and it is worth stating plainly: a registry that cannot be trusted must
stop a release, not shrink to the part that still validates.

The failure modes it refuses, each of which has a plausible-looking alternative
that is wrong:

* **An invariant is missing.** The tempting behaviour is to check the eleven
  that remain. That turns deleting a safety requirement into a way of
  satisfying it.
* **An identifier is duplicated.** Two rows, one identity: a result cannot be
  attributed to either.
* **An unknown identifier appears.** A thirteenth invariant is a change to a
  reviewed document, not a code change.
* **A test selector matches nothing.** The row still reads convincingly while
  the tests behind it were renamed or deleted. This is the failure that a
  hand-maintained matrix cannot detect at all.
* **A negative control is missing, or names a fixture nobody wrote.** The
  detector is unproven.
* **A ``NOT_PRESENT`` invariant's feature has appeared.** Enforcing the safe
  absence of an LLM gateway is legitimate until somebody ships one; after
  that, the same answer is a lie.

Discovery is WP-19's. This module does not build a second test enumerator - it
asks ``pgx.verification.discovery`` what exists and checks the registry against
that, so the two cannot describe different suites.
"""

from __future__ import annotations

import importlib.util
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from pgx.safety.controls import (
    CONTROL_CATALOGUE_VERSION,
    NEGATIVE_CONTROLS,
    NegativeControl,
    controls_by_id,
)
from pgx.safety.definitions import (
    INVARIANT_DEFINITIONS,
    InvariantDefinition,
    definitions_by_id,
)
from pgx.safety.errors import (
    DuplicateInvariant,
    InvariantNotRegistered,
    NegativeControlMissing,
    RegistryError,
    SelectorError,
    UnknownInvariant,
)
from pgx.safety.vocabulary import (
    INVARIANT_IDS,
    REGISTRY_VERSION,
    ComplianceState,
    InvariantId,
)

__all__ = [
    "SafetyRegistry",
    "load_registry",
    "validate_registry",
    "selector_matches",
]


def selector_matches(module: str, selector: str) -> bool:
    """Whether ``module`` is named by ``selector``.

    Exact, or a dotted prefix. The dot is required, so ``tests.unit.web``
    cannot capture ``tests.unit.website`` by accident - the same rule WP-19
    uses, deliberately, so a selector means one thing in both packages.
    """
    return module == selector or module.startswith(selector + ".")


@dataclass(frozen=True)
class SafetyRegistry:
    """The validated registry: twelve invariants and their controls."""

    definitions: Tuple[InvariantDefinition, ...]
    controls: Tuple[NegativeControl, ...]
    #: Modules the registry's selectors resolved to, per invariant.
    resolved_modules: Mapping[str, Tuple[str, ...]]

    def definition(self, invariant_id: InvariantId) -> InvariantDefinition:
        return definitions_by_id()[invariant_id.value]

    def controls_for(self, invariant_id: InvariantId
                     ) -> Tuple[NegativeControl, ...]:
        return tuple(control for control in self.controls
                     if control.invariant_id is invariant_id)

    @property
    def invariant_count(self) -> int:
        return len(self.definitions)

    @property
    def control_count(self) -> int:
        return len(self.controls)

    def as_document(self) -> Dict[str, Any]:
        return {
            "control_catalogue_version": CONTROL_CATALOGUE_VERSION,
            "control_count": self.control_count,
            "invariant_count": self.invariant_count,
            "invariant_ids": [d.invariant_id.value for d in self.definitions],
            "invariants": [d.as_document() for d in self.definitions],
            "negative_controls": [c.as_document() for c in self.controls],
            "registry_version": REGISTRY_VERSION,
            "resolved_modules": {key: list(value) for key, value
                                 in sorted(self.resolved_modules.items())},
        }


def _module_exists(dotted: str, root: str) -> bool:
    """Whether a dotted module path names a real file under ``root``.

    Checked on the filesystem rather than by importing. Importing a fixture to
    find out whether it exists would execute it, and a registry validation must
    not have side effects.
    """
    relative = dotted.replace(".", os.sep)
    for candidate in (relative + ".py", os.path.join(relative, "__init__.py")):
        if os.path.exists(os.path.join(root, candidate)):
            return True
    return False


def validate_registry(root: str,
                      known_modules: Optional[Sequence[str]] = None,
                      definitions: Sequence[InvariantDefinition] =
                      INVARIANT_DEFINITIONS,
                      controls: Sequence[NegativeControl] = NEGATIVE_CONTROLS
                      ) -> SafetyRegistry:
    """Validate the registry against the tree, or refuse it.

    ``known_modules`` is the set of test modules that actually exist. It
    defaults to WP-19's discovery, so the safety registry and the verification
    inventory are checked against one enumeration rather than two.

    Every problem is collected before raising. A registry with four faults
    should be read once by a person, not four times by a build.
    """
    issues: List[str] = []

    # -- exactly SAFETY-INV-001..012, once each ---------------------------
    seen: Dict[str, int] = {}
    for definition in definitions:
        identifier = definition.invariant_id.value
        seen[identifier] = seen.get(identifier, 0) + 1

    duplicates = sorted(key for key, count in seen.items() if count > 1)
    if duplicates:
        raise DuplicateInvariant(
            "an invariant identifier appears more than once, so a result "
            "cannot be attributed to a single invariant", duplicates)

    missing = [identifier for identifier in INVARIANT_IDS
               if identifier not in seen]
    if missing:
        raise InvariantNotRegistered(
            "the registry does not contain every required safety invariant; "
            "deleting a safety requirement must not be a way of satisfying it",
            missing)

    unknown = sorted(key for key in seen if key not in INVARIANT_IDS)
    if unknown:
        raise UnknownInvariant(
            "an identifier outside SAFETY-INV-001..012 appeared; a new "
            "invariant is a change to docs/risk-management/safety-contract.md, "
            "which is a reviewed document", unknown)

    # -- ordering, so the artifact and the document read the same way -----
    ordered = [definition.invariant_id.value for definition in definitions]
    if ordered != list(INVARIANT_IDS):
        issues.append("invariants are not in SAFETY-INV-001..012 order: %s"
                      % ", ".join(ordered))

    # -- every selector resolves to a test module that exists -------------
    if known_modules is None:
        known_modules = _discover_modules(root)
    resolved: Dict[str, Tuple[str, ...]] = {}
    for definition in definitions:
        matched_all: List[str] = []
        if not definition.test_selectors:
            issues.append("%s has no test selector, so nothing exercises it"
                          % definition.invariant_id.value)
        for selector in definition.test_selectors:
            matched = [module for module in known_modules
                       if selector_matches(module, selector)]
            if not matched:
                issues.append(
                    "%s selector %r matches no test module that exists"
                    % (definition.invariant_id.value, selector))
            matched_all.extend(matched)
        resolved[definition.invariant_id.value] = tuple(sorted(set(matched_all)))

    if issues and any("matches no test module" in issue for issue in issues):
        raise SelectorError(
            "the registry names tests that do not exist; a row that reads "
            "convincingly while its tests were renamed is worse than no row",
            issues)

    # -- every invariant has at least one negative control ----------------
    # Built from the sequence that was passed in, not from the module-level
    # catalogue: a validator that ignored its own argument would be untestable
    # and would silently validate the wrong data.
    catalogue = {control.control_id: control for control in controls}
    control_issues: List[str] = []
    for definition in definitions:
        if not definition.negative_controls:
            control_issues.append(
                "%s has no negative control, so its detector is unproven"
                % definition.invariant_id.value)
            continue
        for control_id in definition.negative_controls:
            control = catalogue.get(control_id)
            if control is None:
                control_issues.append(
                    "%s names negative control %r, which is not in the "
                    "catalogue" % (definition.invariant_id.value, control_id))
                continue
            if control.invariant_id is not definition.invariant_id:
                control_issues.append(
                    "%s claims control %r, which belongs to %s"
                    % (definition.invariant_id.value, control_id,
                       control.invariant_id.value))
            if not _module_exists(control.fixture, root):
                control_issues.append(
                    "control %r names fixture %r, which does not exist"
                    % (control_id, control.fixture))

    # -- catalogue entries must belong to a registered invariant ----------
    registered = {definition.invariant_id for definition in definitions}
    for control in controls:
        if control.invariant_id not in registered:
            control_issues.append(
                "control %r belongs to unregistered invariant %s"
                % (control.control_id, control.invariant_id.value))

    if control_issues:
        raise NegativeControlMissing(
            "a negative control is missing or misdeclared; a detector nobody "
            "has shown to reject anything is a detector nobody has shown to "
            "work", control_issues)

    # -- a NOT_PRESENT answer must still be true --------------------------
    for definition in definitions:
        if definition.implementation_state is not ComplianceState.NOT_PRESENT:
            continue
        if not definition.absence_markers:
            issues.append(
                "%s is NOT_PRESENT but names no absence markers, so nothing "
                "would notice if the feature shipped"
                % definition.invariant_id.value)
        appeared = [marker for marker in definition.absence_markers
                    if os.path.exists(os.path.join(root, *marker.split("/")))]
        if appeared:
            issues.append(
                "%s is recorded NOT_PRESENT but the feature has appeared (%s); "
                "NOT_PRESENT must never excuse an unsafe feature that exists"
                % (definition.invariant_id.value, ", ".join(sorted(appeared))))

    if issues:
        raise RegistryError("the safety registry is not internally consistent",
                            issues)

    return SafetyRegistry(tuple(definitions), tuple(controls), resolved)


def _discover_modules(root: str) -> Tuple[str, ...]:
    """Test modules that exist, from WP-19's discovery.

    Imported lazily so that ``pgx.safety`` does not depend on WP-19 at import
    time - the registry is readable, and its shape checkable, without running a
    discovery pass.
    """
    from pgx.verification.discovery import discover
    return discover(root).modules


def load_registry(root: str) -> SafetyRegistry:
    """The validated registry for the repository at ``root``."""
    return validate_registry(root)
