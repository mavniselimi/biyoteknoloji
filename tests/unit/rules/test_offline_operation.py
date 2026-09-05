# -*- coding: utf-8 -*-
"""WP-11 runs with the network switched off.

Asserted by breaking ``socket.socket`` rather than by reading imports. An
import check catches a module that names ``requests``; it does not catch one
that reaches the network through a library three levels down. Making the
syscall fail catches both.

This matters more here than anywhere else in the pipeline. A rule is the thing
that will eventually be executed, and a build that could reach the network is
a build whose output depends on what some server said at the moment it ran.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import socket
import tempfile
import unittest
from contextlib import redirect_stdout

from pgx.application import rules_cli
from pgx.rules.registry import FrozenRulesetRegistry
from pgx.rules.serialization import verify_checksums
from tests.fixtures.wp11.synthetic import frozen_ruleset
from tests.unit.rules._support import REPO_ROOT


class _NoNetwork:
    """Every socket constructor raises for the duration of the block."""

    def __enter__(self):
        self._saved = (socket.socket, socket.create_connection,
                       socket.getaddrinfo)

        def refuse(*args, **kwargs):
            raise AssertionError(
                "this code reached the network; WP-11 is offline")

        socket.socket = refuse
        socket.create_connection = refuse
        socket.getaddrinfo = refuse
        return self

    def __exit__(self, exc_type, exc, tb):
        (socket.socket, socket.create_connection,
         socket.getaddrinfo) = self._saved


class TestTheWholeWalkRunsOffline(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = os.path.join(self.tmp, "rulesets")
        os.makedirs(self.root)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_draft_to_frozen_to_served_with_sockets_broken(self):
        destination = os.path.join(self.root, "PGX-RULESET-29991231-001")
        with _NoNetwork():
            _service, _store, _definitions, result = frozen_ruleset(
                destination, count=2)
            verify_checksums(destination)
            registry = FrozenRulesetRegistry(self.root)
            served = registry.list_executable()
        self.assertEqual(served, ("PGX-RULESET-29991231-001",))
        self.assertEqual(result.ruleset.status.value, "FROZEN")


class TestTheCliRunsOffline(unittest.TestCase):

    def _run(self, *argv):
        buffer = io.StringIO()
        with _NoNetwork():
            with redirect_stdout(buffer):
                code = rules_cli.main(list(argv))
        return code, json.loads(buffer.getvalue())

    def test_gate_status_runs_offline(self):
        _code, payload = self._run("gate-status", "--repo-root", REPO_ROOT)
        self.assertTrue(payload["blockers"])

    def test_legacy_inventory_runs_offline(self):
        _code, payload = self._run("legacy-inventory", "--repo-root",
                                   REPO_ROOT)
        self.assertEqual(payload["counts"]["eligible_for_rule_creation"], 0)

    def test_list_issue_codes_runs_offline(self):
        _code, payload = self._run("list-issue-codes")
        self.assertTrue(payload["issue_codes"])


class TestNoModuleImportsANetworkClient(unittest.TestCase):
    """Belt as well as braces: the syscall test above catches reaching the
    network, and this catches the import that would make it easy to."""

    def test_no_rules_module_imports_a_client_library(self):
        from tests.unit.rules._support import (RULE_APPLICATION_MODULES,
                                               APPLICATION_DIR, imports_of,
                                               rules_modules)
        paths = rules_modules() + [os.path.join(APPLICATION_DIR, name)
                                   for name in RULE_APPLICATION_MODULES]
        for path in paths:
            roots = {name.split(".")[0] for name in imports_of(path)}
            with self.subTest(module=os.path.basename(path)):
                for forbidden in ("requests", "httpx", "urllib", "socket",
                                  "aiohttp", "ftplib", "smtplib",
                                  "http", "boto3"):
                    self.assertNotIn(forbidden, roots)


if __name__ == "__main__":
    unittest.main()
