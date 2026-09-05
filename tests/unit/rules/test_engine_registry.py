# -*- coding: utf-8 -*-
"""The engine-facing registry (WP-11, section G).

This is the only surface a rule engine will ever see, and its whole job is to
be narrow. It can list identities and load one verified frozen ruleset. It
cannot reach a DRAFT, CURATED or DEPRECATED rule, cannot see a ruleset that is
still BUILDING, and offers no method that would let a caller ask for one
(``SAFETY-INV-003``).

The production root is empty and the tests below assert that it stays empty.
That is not an oversight to be fixed later: no real rule has been approved by
anybody, so there is nothing an engine could honestly be given.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import unittest

from pgx.rules.errors import ArtifactIntegrityError, RegistryLoadError
from pgx.rules.ports import ExecutableRulesetRegistry
from pgx.rules.registry import (DEFAULT_RULESET_ROOT, FrozenRulesetRegistry,
                                load_frozen_ruleset)
from tests.fixtures.wp11.synthetic import frozen_ruleset
from tests.unit.rules._support import DEFAULT_REGISTRY_ROOT, REPO_ROOT


class TestTheDefaultRegistryIsEmpty(unittest.TestCase):

    def test_the_default_root_is_the_production_directory(self):
        self.assertEqual(DEFAULT_RULESET_ROOT,
                         os.path.join("data", "rulesets"))

    def test_the_production_registry_exposes_no_executable_ruleset(self):
        registry = FrozenRulesetRegistry(DEFAULT_REGISTRY_ROOT)
        self.assertEqual(registry.list_executable(), ())

    def test_the_production_directory_contains_no_artifact(self):
        """Only documentation and the two gate reports live there. A ruleset
        artifact appearing in this directory would mean a real ruleset had
        been frozen, which requires approvals nobody has given."""
        for name in sorted(os.listdir(DEFAULT_REGISTRY_ROOT)):
            path = os.path.join(DEFAULT_REGISTRY_ROOT, name)
            with self.subTest(entry=name):
                self.assertFalse(
                    os.path.isdir(path),
                    "%s looks like a published ruleset artifact" % name)

    def test_the_synthetic_fixtures_are_not_in_the_scanned_directory(self):
        """The fixtures live under ``tests/``. A production registry that
        scanned them would serve invented rules to an engine."""
        for root, dirs, files in os.walk(DEFAULT_REGISTRY_ROOT):
            dirs[:] = [name for name in dirs if name != "__pycache__"]
            for name in files:
                with self.subTest(file=os.path.join(root, name)):
                    self.assertNotIn("rules.ndjson", name)


class TestThePortIsNarrow(unittest.TestCase):

    def test_the_registry_port_offers_exactly_two_methods(self):
        methods = {name for name in vars(ExecutableRulesetRegistry)
                   if not name.startswith("_")}
        self.assertEqual(methods, {"list_executable", "load"})

    def test_the_registry_has_no_method_naming_an_unpublished_state(self):
        surface = {name.lower() for name in dir(FrozenRulesetRegistry)
                   if not name.startswith("_")}
        for forbidden in ("draft", "curated", "deprecated", "building",
                          "all", "unverified", "raw", "pending"):
            for name in surface:
                with self.subTest(method=name, forbidden=forbidden):
                    self.assertNotIn(forbidden, name)


class TestOnlyFrozenVerifiedRulesetsAreServed(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = os.path.join(self.tmp, "rulesets")
        os.makedirs(self.root)
        self.destination = os.path.join(self.root, "PGX-RULESET-29991231-001")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        frozen_ruleset(self.destination, count=2)
        self.registry = FrozenRulesetRegistry(self.root)

    def test_a_frozen_artifact_is_listed_and_loads(self):
        self.assertEqual(self.registry.list_executable(),
                         ("PGX-RULESET-29991231-001",))
        ruleset = self.registry.load("PGX-RULESET-29991231-001")
        self.assertEqual(ruleset.member_count, 2)

    def test_every_rule_it_serves_is_a_member_of_the_manifest(self):
        ruleset = self.registry.load("PGX-RULESET-29991231-001")
        served = {definition.rule_id.to_json()
                  for definition in ruleset.rules()}
        pinned = {member.rule_id.to_json()
                  for member in ruleset.manifest.members}
        self.assertEqual(served, pinned)

    def test_a_tampered_artifact_is_not_listed(self):
        path = os.path.join(self.destination, "rules.ndjson")
        with io.open(path, "a", encoding="utf-8") as handle:
            handle.write("\n")
        self.assertEqual(FrozenRulesetRegistry(self.root).list_executable(),
                         ())

    def test_loading_a_tampered_artifact_raises(self):
        path = os.path.join(self.destination, "rules.ndjson")
        with io.open(path, "a", encoding="utf-8") as handle:
            handle.write("\n")
        with self.assertRaises((ArtifactIntegrityError, RegistryLoadError)):
            FrozenRulesetRegistry(self.root).load("PGX-RULESET-29991231-001")

    def test_an_incomplete_directory_is_not_a_ruleset(self):
        os.remove(os.path.join(self.destination, "approval-list.json"))
        self.assertEqual(FrozenRulesetRegistry(self.root).list_executable(),
                         ())

    def test_an_unknown_identity_raises_rather_than_returning_nothing(self):
        """A registry that answered "nothing" for an unknown ruleset would let
        a caller proceed as if it had asked for an empty one."""
        with self.assertRaises(RegistryLoadError):
            self.registry.load("PGX-RULESET-19000101-999")

    def test_a_missing_root_lists_nothing_and_does_not_raise(self):
        registry = FrozenRulesetRegistry(os.path.join(self.tmp, "absent"))
        self.assertEqual(registry.list_executable(), ())


class TestLoadingFailsClosed(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.destination = os.path.join(self.tmp, "PGX-RULESET-29991231-001")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        frozen_ruleset(self.destination, count=2)

    def _rewrite(self, name, mutate):
        path = os.path.join(self.destination, name)
        with io.open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
        mutate(payload)
        with io.open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)

    def test_a_clean_artifact_loads(self):
        ruleset = load_frozen_ruleset(self.destination)
        self.assertEqual(ruleset.member_count, 2)
        self.assertTrue(ruleset.ruleset_content_hash.startswith("sha256:"))

    def test_a_manifest_naming_a_rule_the_file_does_not_hold_is_refused(self):
        self._rewrite("manifest.json",
                      lambda payload: payload["members"].append(
                          dict(payload["members"][0],
                               rule_id="00000000-0000-4000-8000-000000000009")))
        with self.assertRaises(ArtifactIntegrityError):
            load_frozen_ruleset(self.destination)

    def test_a_rule_the_manifest_does_not_pin_is_refused(self):
        self._rewrite("manifest.json",
                      lambda payload: payload["members"].pop())
        with self.assertRaises(ArtifactIntegrityError):
            load_frozen_ruleset(self.destination)

    def test_an_approval_list_missing_a_member_is_refused(self):
        self._rewrite("approval-list.json",
                      lambda payload: payload["entries"].pop())
        with self.assertRaises(ArtifactIntegrityError):
            load_frozen_ruleset(self.destination)

    def test_an_approval_entry_missing_a_role_is_refused(self):
        def _blank_reviewer(payload):
            payload["entries"][0]["reviewed_by"] = ""
        self._rewrite("approval-list.json", _blank_reviewer)
        with self.assertRaises(ArtifactIntegrityError):
            load_frozen_ruleset(self.destination)

    def test_an_empty_directory_is_refused(self):
        empty = os.path.join(self.tmp, "empty")
        os.makedirs(empty)
        with self.assertRaises((ArtifactIntegrityError, RegistryLoadError)):
            load_frozen_ruleset(empty)


class TestNothingUnpublishedIsReachable(unittest.TestCase):
    """The registry reads a directory, not a database. There is therefore no
    query it could answer about a rule that was never published - which is a
    stronger guarantee than a filter, because there is nothing to filter."""

    def test_the_registry_module_never_reads_a_repository(self):
        from tests.unit.rules._support import RULES_DIR, imports_of
        imported = imports_of(os.path.join(RULES_DIR, "registry.py"))
        for forbidden in ("sqlalchemy", "pgx.infrastructure",
                          "pgx.rules.memory", "pgx.rules.ports"):
            with self.subTest(module=forbidden):
                self.assertNotIn(forbidden, imported)

    def test_the_registry_module_names_no_unpublished_status(self):
        from tests.unit.rules._support import RULES_DIR, source
        text = source(os.path.join(RULES_DIR, "registry.py"))
        for status in ('"DRAFT"', '"CURATED"', '"BUILDING"'):
            with self.subTest(status=status):
                self.assertNotIn(status, text)


if __name__ == "__main__":
    unittest.main()
