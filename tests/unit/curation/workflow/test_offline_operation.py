# -*- coding: utf-8 -*-
"""The workflow runs with the network switched off (WP-10).

Asserted by breaking `socket.socket` rather than by reading imports. An import
check catches a module that names `requests`; it does not catch one that
reaches the network through a library three levels down. Making the syscall
fail catches both.
"""

from __future__ import annotations

import contextlib
import io
import json
import socket
import unittest

from pgx.application import curation_workflow_cli as cli
from pgx.curation.vocabulary import ConflictState
from pgx.curation.workflow import forms
from pgx.curation.workflow.models import ReviewDecision
from tests.support.workflow_fixtures import (TEST_CURATOR, TEST_REVIEWER,
                                             TEST_STEWARD, build_service,
                                             evidence_snapshot, seed_raw,
                                             steward_verification)


class _NoNetwork:
    """Every socket constructor raises for the duration of the block."""

    def __enter__(self):
        self._saved = (socket.socket, socket.create_connection,
                       socket.getaddrinfo)

        def refuse(*args, **kwargs):
            raise AssertionError(
                "this code reached the network; WP-10 is offline")

        socket.socket = refuse
        socket.create_connection = refuse
        socket.getaddrinfo = refuse
        return self

    def __exit__(self, exc_type, exc, tb):
        (socket.socket, socket.create_connection,
         socket.getaddrinfo) = self._saved


class TestTheServiceNeedsNoNetwork(unittest.TestCase):

    def test_a_complete_workflow_runs_with_sockets_broken(self):
        with _NoNetwork():
            service, store = build_service()
            item = seed_raw(store)
            revision = service.create_revision(
                actor_id=TEST_CURATOR, work_item_id=item.work_item_id,
                expected_version=0, payload={"c": 1},
                evidence=evidence_snapshot())
            service.record_provenance_verification(
                actor_id=TEST_STEWARD, work_item_id=item.work_item_id,
                verification=steward_verification())
            service.submit(actor_id=TEST_CURATOR,
                           work_item_id=item.work_item_id,
                           revision_id=revision.revision.revision_id,
                           expected_version=1)
            approved = service.review(
                actor_id=TEST_REVIEWER, work_item_id=item.work_item_id,
                revision_id=revision.revision.revision_id,
                expected_version=2, decision=ReviewDecision.APPROVE,
                rationale="Independently re-read the cited evidence and agree.",
                conflict_state=ConflictState.NONE_IDENTIFIED,
                rationale_complete=True)
        self.assertEqual(approved.work_item.status.value, "CURATED")


class TestTheCliNeedsNoNetwork(unittest.TestCase):

    def _run(self, argv):
        buffer = io.StringIO()
        with _NoNetwork(), contextlib.redirect_stdout(buffer):
            code = cli.main(argv)
        return code, buffer.getvalue()

    def test_import_legacy_runs_offline(self):
        code, output = self._run(["import-legacy"])
        self.assertEqual(code, cli.EXIT_OK)
        self.assertEqual(json.loads(output)["counts"]["work_items"], 1559)

    def test_list_and_show_run_offline(self):
        _code, listing = self._run(["list", "--limit", "1"])
        work_item_id = json.loads(listing)["work_items"][0]["work_item_id"]
        code, _output = self._run(["show", work_item_id])
        self.assertEqual(code, cli.EXIT_OK)

    def test_gate_status_runs_offline(self):
        _code, listing = self._run(["list", "--limit", "1"])
        work_item_id = json.loads(listing)["work_items"][0]["work_item_id"]
        code, _output = self._run(["gate-status", work_item_id])
        self.assertEqual(code, cli.EXIT_REFUSED)

    def test_render_form_runs_offline(self):
        _code, listing = self._run(["list", "--limit", "1"])
        work_item_id = json.loads(listing)["work_items"][0]["work_item_id"]
        code, output = self._run(["render-form", "detail",
                                  "--work-item", work_item_id])
        self.assertEqual(code, cli.EXIT_OK)
        self.assertIn("<!DOCTYPE html>", output)


class TestTheConsoleNeedsNoNetwork(unittest.TestCase):

    def test_every_read_route_renders_with_sockets_broken(self):
        with _NoNetwork():
            service, store = build_service()
            item = seed_raw(store)
            for route in forms.READ_ROUTES:
                params = {"work_item_id": item.work_item_id}
                if route == "list":
                    params["items"] = []
                with self.subTest(route=route):
                    response = forms.handle(
                        route, {"method": "GET", "params": params},
                        service=service)
                    self.assertEqual(response.status, 200)


class TestTheGuardItselfWorks(unittest.TestCase):
    """A test that cannot fail proves nothing."""

    def test_a_socket_inside_the_block_raises(self):
        with _NoNetwork():
            with self.assertRaises(AssertionError):
                socket.socket()

    def test_sockets_work_again_afterwards(self):
        with _NoNetwork():
            pass
        sock = socket.socket()
        sock.close()


if __name__ == "__main__":
    unittest.main()
