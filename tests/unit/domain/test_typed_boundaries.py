# -*- coding: utf-8 -*-
"""Typed boundaries: operation mode, identifier derivation, port signatures.

Three WP-02 corrective findings are proven here.

**Operation mode.** ``Assessment.mode`` used to be a plain ``str``, so
``mode="PILOT"`` - a mode WP-00 disables in P0 - and ``mode="whatever"`` were
both accepted. The mode vocabulary belongs to :mod:`pgx.domain.claims`; the
domain must take the enum and consult the claim boundary, so a disabled mode
cannot enter through a string literal.

**Identifier derivation.** Deterministic derivation is safe only where the key
is a stable, curated technical key. Exposing ``derive()`` on the shared
``EntityId`` base offered it to every identifier, including scientific records
whose identity must be explicitly minted. It now exists on exactly one class.

**Port signatures.** ``object`` in a port annotation is an untyped hole: it
compiles, it reads like a type, and it enforces nothing. No port may use it.

Standard library only; the AST checks hold without SQLAlchemy installed.
"""

from __future__ import annotations

import ast
import inspect
import os
import unittest

from tests.unit.domain._fixtures import NOW, DIGEST

from pgx.domain import identifiers as identifiers_module
from pgx.domain import ports as ports_module
from pgx.domain.claims import DEFAULT_CLAIM_BOUNDARY, OperationMode
from pgx.domain.errors import (
    DomainInvariantError, InvalidIdentifierError, ModeNotPermittedError,
)
from pgx.domain.identifiers import (
    AssessmentId, EntityId, ReleaseBundleId, SourceRegistryEntryId,
)
from pgx.domain.models import Assessment

PORTS_PATH = os.path.abspath(ports_module.__file__)

#: The single identifier class permitted to derive identity from a key.
DERIVING_IDENTIFIERS = ("SourceRegistryEntryId",)


def _assessment(mode) -> Assessment:
    return Assessment(
        id=AssessmentId.new(), release_bundle_id=ReleaseBundleId.new(),
        mode=mode, input_hash=DIGEST, created_at=NOW)


class TestAssessmentModeIsTyped(unittest.TestCase):
    """``mode`` is an OperationMode checked against the WP-00 boundary."""

    def test_demo_mode_is_accepted(self):
        assessment = _assessment(OperationMode.DEMO)
        self.assertIs(assessment.mode, OperationMode.DEMO)

    def test_validation_mode_is_accepted(self):
        assessment = _assessment(OperationMode.VALIDATION)
        self.assertIs(assessment.mode, OperationMode.VALIDATION)

    def test_pilot_mode_is_refused_because_p0_disables_it(self):
        self.assertFalse(DEFAULT_CLAIM_BOUNDARY.is_mode_enabled(OperationMode.PILOT))
        with self.assertRaises(ModeNotPermittedError):
            _assessment(OperationMode.PILOT)

    def test_the_string_demo_is_refused(self):
        with self.assertRaises(DomainInvariantError) as caught:
            _assessment("DEMO")
        self.assertIn("OperationMode", str(caught.exception))

    def test_the_string_pilot_cannot_smuggle_a_disabled_mode_in(self):
        with self.assertRaises(DomainInvariantError):
            _assessment("PILOT")

    def test_an_arbitrary_string_is_refused(self):
        with self.assertRaises(DomainInvariantError):
            _assessment("clinical-production")

    def test_none_is_refused(self):
        with self.assertRaises(DomainInvariantError):
            _assessment(None)

    def test_an_integer_is_refused(self):
        with self.assertRaises(DomainInvariantError):
            _assessment(0)

    def test_mode_not_permitted_is_a_domain_invariant_error(self):
        self.assertTrue(issubclass(ModeNotPermittedError, DomainInvariantError))

    def test_the_annotation_is_the_enum_not_str(self):
        annotation = Assessment.__annotations__["mode"]
        text = annotation if isinstance(annotation, str) else getattr(
            annotation, "__name__", str(annotation))
        self.assertIn("OperationMode", text)
        self.assertNotEqual(text, "str")

    def test_the_domain_does_not_define_its_own_mode_vocabulary(self):
        source = inspect.getsource(
            __import__("pgx.domain.models", fromlist=["models"]))
        tree = ast.parse(source)
        names = {node.name for node in ast.walk(tree)
                 if isinstance(node, ast.ClassDef)}
        self.assertNotIn("OperationMode", names,
                         "the mode vocabulary must stay in pgx.domain.claims")


class TestDeriveIsRestrictedToOneIdentifier(unittest.TestCase):
    """Only a curated technical key may produce a deterministic identity."""

    def _identifier_classes(self):
        return [
            (name, value) for name, value in vars(identifiers_module).items()
            if inspect.isclass(value) and issubclass(value, EntityId)
        ]

    def test_the_base_class_does_not_offer_derive(self):
        self.assertFalse(hasattr(EntityId, "derive"))

    def test_exactly_the_declared_identifiers_offer_derive(self):
        offering = sorted(
            name for name, value in self._identifier_classes()
            if "derive" in vars(value))
        self.assertEqual(offering, sorted(DERIVING_IDENTIFIERS))

    def test_no_other_identifier_inherits_derive(self):
        for name, value in self._identifier_classes():
            if name in DERIVING_IDENTIFIERS or name == "EntityId":
                continue
            self.assertFalse(hasattr(value, "derive"),
                             "%s must not expose derive()" % name)

    def test_derivation_is_deterministic(self):
        first = SourceRegistryEntryId.derive("clinpgx")
        second = SourceRegistryEntryId.derive("clinpgx")
        self.assertEqual(first, second)

    def test_different_keys_derive_different_identities(self):
        self.assertNotEqual(SourceRegistryEntryId.derive("clinpgx"),
                            SourceRegistryEntryId.derive("cpic"))

    def test_an_empty_key_is_refused(self):
        with self.assertRaises(InvalidIdentifierError):
            SourceRegistryEntryId.derive("")

    def test_a_whitespace_key_is_refused(self):
        with self.assertRaises(InvalidIdentifierError):
            SourceRegistryEntryId.derive("   ")


class TestPortsDeclareNoUntypedHoles(unittest.TestCase):
    """``object`` in a signature is an annotation that enforces nothing."""

    @classmethod
    def setUpClass(cls):
        with open(PORTS_PATH, encoding="utf-8") as handle:
            cls.source = handle.read()
        cls.tree = ast.parse(cls.source)

    def _annotations(self):
        """Yield (function name, annotation node) for every port method."""
        for node in ast.walk(self.tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            arguments = list(node.args.args) + list(node.args.kwonlyargs)
            for argument in arguments:
                if argument.arg in ("self", "cls"):
                    continue
                if argument.annotation is not None:
                    yield node.name, argument.arg, argument.annotation
            if node.returns is not None:
                yield node.name, "return", node.returns

    def test_no_parameter_or_return_is_annotated_object(self):
        offenders = [
            (function, argument)
            for function, argument, annotation in self._annotations()
            if isinstance(annotation, ast.Name) and annotation.id == "object"
        ]
        self.assertEqual(offenders, [])

    def test_no_annotation_contains_object_anywhere(self):
        offenders = []
        for function, argument, annotation in self._annotations():
            for node in ast.walk(annotation):
                if isinstance(node, ast.Name) and node.id == "object":
                    offenders.append((function, argument))
        self.assertEqual(offenders, [])

    def test_every_port_parameter_is_annotated(self):
        unannotated = []
        for node in ast.walk(self.tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for argument in list(node.args.args) + list(node.args.kwonlyargs):
                if argument.arg in ("self", "cls"):
                    continue
                if argument.annotation is None:
                    unannotated.append((node.name, argument.arg))
        self.assertEqual(unannotated, [])

    def test_listing_methods_take_domain_identifier_types(self):
        expected = {
            "list_for_dataset_version": "DatasetVersionId",
            "list_by_status": "CurationStatus",
        }
        seen = {}
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.FunctionDef) or node.name not in expected:
                continue
            for argument in node.args.args:
                if argument.arg in ("self", "cls"):
                    continue
                seen.setdefault(node.name, ast.unparse(argument.annotation))
        for name, annotation in expected.items():
            self.assertIn(name, seen, "%s is not declared in ports.py" % name)
            self.assertIn(annotation, seen[name])

    def test_context_manager_exit_is_typed(self):
        exits = [node for node in ast.walk(self.tree)
                 if isinstance(node, ast.FunctionDef) and node.name == "__exit__"]
        self.assertTrue(exits, "no __exit__ declared on the unit of work port")
        for node in exits:
            annotations = [ast.unparse(a.annotation) for a in node.args.args
                           if a.arg not in ("self", "cls")]
            self.assertTrue(annotations)
            for annotation in annotations:
                self.assertNotEqual(annotation, "object")
            joined = " ".join(annotations)
            self.assertIn("BaseException", joined)
            self.assertIn("TracebackType", joined)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
