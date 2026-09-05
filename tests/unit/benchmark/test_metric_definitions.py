# -*- coding: utf-8 -*-
"""The registry is complete, and no threshold was invented."""

from __future__ import annotations

import unittest

from pgx.validation.metric_definitions import (FAILURE_PATH_CATALOGUE,
                                               METRIC_DEFINITIONS,
                                               METRIC_IDS, MetricKind,
                                               UNAVAILABLE_REASONS,
                                               UnavailableReason,
                                               definitions_by_id,
                                               failure_paths_by_id,
                                               registry_digest,
                                               validation_evidence_metric_ids)
from pgx.validation.vocabulary import ValidationCaseRole


class TestEveryArchitectureMetricIsDefined(unittest.TestCase):
    """``architecture.md`` section 12.3 lists ten. Each maps to a definition.

    Ten bullets, fifteen definitions: the architecture states several of them
    as "count and rate", which are two metrics with two denominators and two
    ways of being unavailable. Splitting them is the honest reading - a single
    record cannot be both an integer count and a null-when-zero rate.
    """

    #: architecture bullet -> the definitions that satisfy it.
    _REQUIRED = {
        "guideline/rule concordance": ("PGX-VAL-001",),
        "coverage correctness": ("PGX-VAL-002",),
        "unsafe false reassurance count and rate": ("PGX-VAL-003",
                                                    "PGX-VAL-004"),
        "evidence traceability rate": ("PGX-VAL-005", "PGX-VAL-006"),
        "deterministic repeatability rate": ("PGX-VAL-007", "PGX-VAL-008"),
        "holdout pass rate": ("PGX-VAL-009", "PGX-VAL-010"),
        "expert agree/partial/disagree distribution": ("PGX-VAL-011",),
        "optional expert Likert dimensions": ("PGX-VAL-012",),
        "unresolved source-conflict counts": ("PGX-VAL-013",),
        "failure-path coverage": ("PGX-VAL-014", "PGX-VAL-015"),
    }

    def test_every_architecture_metric_has_a_definition(self):
        registry = definitions_by_id()
        for bullet, metric_ids in sorted(self._REQUIRED.items()):
            for metric_id in metric_ids:
                with self.subTest(bullet=bullet, metric=metric_id):
                    self.assertIn(metric_id, registry)

    def test_the_registry_covers_the_architecture_and_nothing_stray(self):
        expected = {metric_id for ids in self._REQUIRED.values()
                    for metric_id in ids}
        self.assertEqual(set(METRIC_IDS), expected)

    def test_identifiers_are_unique_and_stable(self):
        self.assertEqual(len(set(METRIC_IDS)), len(METRIC_IDS))
        for metric_id in METRIC_IDS:
            self.assertRegex(metric_id, r"^PGX-VAL-[0-9]{3}$")


class TestNoThresholdWasInvented(unittest.TestCase):
    """A21 in spirit: a threshold after the fact describes rather than judges."""

    def test_no_metric_carries_a_threshold(self):
        for definition in METRIC_DEFINITIONS:
            with self.subTest(metric=definition.metric_id):
                self.assertIsNone(definition.threshold)
                self.assertIsNone(definition.threshold_provenance)

    def test_a_threshold_without_provenance_is_refused(self):
        from dataclasses import replace
        with self.assertRaises(ValueError):
            replace(METRIC_DEFINITIONS[0], threshold=0.95,
                    threshold_provenance=None)

    def test_a_threshold_with_provenance_is_structurally_allowed(self):
        """The mechanism exists so a real policy can use it later.

        Refusing every threshold forever would push a future policy into
        being expressed somewhere unreviewable.
        """
        from dataclasses import replace
        allowed = replace(METRIC_DEFINITIONS[0], threshold=0.95,
                          threshold_provenance="DOC-XYZ section 4, approved "
                                               "2027-01-01 by named reviewers")
        self.assertEqual(allowed.threshold, 0.95)


class TestNumeratorsAndDenominatorsAreExplicit(unittest.TestCase):

    def test_every_metric_states_both(self):
        for definition in METRIC_DEFINITIONS:
            with self.subTest(metric=definition.metric_id):
                self.assertGreater(len(definition.numerator), 10)
                self.assertGreater(len(definition.denominator), 10)

    def test_every_metric_can_be_unavailable(self):
        for definition in METRIC_DEFINITIONS:
            with self.subTest(metric=definition.metric_id):
                self.assertTrue(definition.unavailable_when)
                for reason in definition.unavailable_when:
                    self.assertIn(reason.value, UNAVAILABLE_REASONS)

    def test_every_rate_can_report_a_zero_denominator(self):
        for definition in METRIC_DEFINITIONS:
            if definition.kind is not MetricKind.RATE:
                continue
            with self.subTest(metric=definition.metric_id):
                self.assertIn(UnavailableReason.ZERO_DENOMINATOR,
                              definition.unavailable_when)


class TestDevelopmentIsNeverValidationEvidence(unittest.TestCase):
    """A6, at the level of the definition rather than the computation."""

    def test_no_evidence_metric_accepts_development(self):
        for definition in METRIC_DEFINITIONS:
            if not definition.is_validation_evidence:
                continue
            with self.subTest(metric=definition.metric_id):
                self.assertNotIn(ValidationCaseRole.DEVELOPMENT,
                                 definition.eligible_roles)

    def test_the_combination_is_refused_at_construction(self):
        from dataclasses import replace
        evidence = definitions_by_id()["PGX-VAL-001"]
        with self.assertRaises(ValueError):
            replace(evidence,
                    eligible_roles=(ValidationCaseRole.DEVELOPMENT,))

    def test_some_metrics_are_deliberately_not_evidence(self):
        """Determinism and failure-path coverage are software properties.

        Marking everything as evidence would be the easy lie; marking nothing
        would make the flag useless. The split is the finding.
        """
        evidence = set(validation_evidence_metric_ids())
        self.assertIn("PGX-VAL-001", evidence)
        self.assertNotIn("PGX-VAL-007", evidence)
        self.assertNotIn("PGX-VAL-014", evidence)


class TestTheFailurePathCatalogueIsPredeclared(unittest.TestCase):

    _REQUIRED = ("unsupported medication", "missing required gene",
                 "indeterminate phenotype", "partial coverage",
                 "insufficient coverage", "conflicting source",
                 "no applicable validated rule", "invalid/unpinned release",
                 "missing evidence reference", "prohibited input")

    def test_it_has_at_least_the_ten_required_paths(self):
        self.assertGreaterEqual(len(FAILURE_PATH_CATALOGUE), 10)

    def test_every_required_kind_of_failure_appears(self):
        titles = " ".join(path.title.lower()
                          for path in FAILURE_PATH_CATALOGUE)
        meanings = " ".join(path.meaning.lower()
                            for path in FAILURE_PATH_CATALOGUE)
        haystack = titles + " " + meanings
        for required in ("medication", "gene", "indeterminate", "partial",
                         "insufficient", "conflict", "validated rule",
                         "release", "evidence", "prohibited"):
            with self.subTest(kind=required):
                self.assertIn(required, haystack)

    def test_path_ids_are_unique(self):
        catalogue = failure_paths_by_id()
        self.assertEqual(len(catalogue), len(FAILURE_PATH_CATALOGUE))


class TestTheRegistryDigestPinsTheDefinitions(unittest.TestCase):

    def test_it_is_stable_across_calls(self):
        self.assertEqual(registry_digest(), registry_digest())

    def test_it_changes_when_a_definition_changes(self):
        """A digest that survived an edit would pin nothing."""
        import pgx.validation.metric_definitions as module
        from dataclasses import replace
        original = module.METRIC_DEFINITIONS
        before = registry_digest()
        try:
            module.METRIC_DEFINITIONS = original[:-1] + (
                replace(original[-1], title="something else"),)
            self.assertNotEqual(registry_digest(), before)
        finally:
            module.METRIC_DEFINITIONS = original
        self.assertEqual(registry_digest(), before)
