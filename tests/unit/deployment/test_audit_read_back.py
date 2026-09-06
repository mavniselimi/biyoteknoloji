# -*- coding: utf-8 -*-
"""Reading a stored audit event back (Wave 4B).

``row_to_audit_event`` converted ``action`` and ``outcome`` through their
enums and passed ``auth_mechanism`` and ``auth_assurance`` as the raw strings
the database returns. ``GovernedAuditEvent.__post_init__`` requires enum
instances, so every read of a stored event raised "an audit event records both
the mechanism and its assurance".

That is worse than it sounds. Appending an event reads the head first, so the
chain could never advance past its first event: the first governed action in a
deployment's life succeeded and the second failed, permanently, with an error
naming neither the cause nor the field.

Nothing caught it because no deployment had ever recorded two governed
actions. A unit test with a fabricated row does now, and a real PostgreSQL
with a second action is what surfaced it.
"""

from __future__ import annotations

import datetime as _dt
import unittest

from pgx.deployment.stores import row_to_audit_event
from pgx.security.vocabulary import AuthAssurance, AuthMechanism


class _Row:
    """The shape SQLAlchemy hands back: enums as the strings they are stored as."""

    def __init__(self, **overrides):
        self.event_id = "EVT-0123456789abcdef0123456789abcdef"
        self.stream_id = "pgx-governed"
        self.sequence = 2
        self.action = "USER_CREATED"
        self.outcome = "SUCCESS"
        self.result_code = "CREATED"
        self.object_type = "USER"
        self.object_id = "USR-0123456789abcdef0123"
        self.occurred_at = _dt.datetime(2026, 9, 6, 22, 0,
                                        tzinfo=_dt.timezone.utc)
        self.actor_id = "demo-bootstrap"
        self.actor_role = "ADMIN"
        self.auth_mechanism = "NONE"
        self.auth_assurance = "NONE"
        self.session_reference = None
        self.request_id = None
        for name in ("input_hash", "output_hash", "software_id",
                     "software_hash", "dataset_id", "dataset_hash",
                     "ruleset_id", "ruleset_hash", "release_id",
                     "release_manifest_hash", "previous_hash"):
            setattr(self, name, None)
        self.schema_version = "pgx-wp23-governed-audit-event/1"
        self.event_metadata = {}
        self.event_hash = "sha256:" + "0" * 64
        for name, value in overrides.items():
            setattr(self, name, value)


class TestAStoredEventReadsBack(unittest.TestCase):

    def test_a_setup_event_reads_back(self):
        event = row_to_audit_event(_Row())
        self.assertIs(event.auth_mechanism, AuthMechanism.NONE)
        self.assertIs(event.auth_assurance, AuthAssurance.NONE)

    def test_a_session_authenticated_event_reads_back(self):
        """The row that blocked every deployment's second governed action.

        A login writes ``LOGIN_SUCCEEDED`` and ``SESSION_CREATED`` under
        ``SESSION`` / ``SESSION``; the next append has to read one of them.
        """
        event = row_to_audit_event(_Row(
            action="SESSION_CREATED", result_code="SESSION_CREATED",
            object_type="SESSION", object_id="SES-0123456789abcdef0123",
            actor_id="jury", actor_role="DEMO_USER",
            auth_mechanism="SESSION", auth_assurance="SESSION",
            session_reference="SES-0123456789abcdef0123"))
        self.assertIs(event.auth_mechanism, AuthMechanism.SESSION)
        self.assertIs(event.auth_assurance, AuthAssurance.SESSION)

    def test_every_mechanism_and_assurance_value_reads_back(self):
        """The whole vocabulary, so a new member cannot be forgotten here."""
        for mechanism in AuthMechanism:
            assurance = (AuthAssurance.SESSION
                         if mechanism is AuthMechanism.SESSION
                         else AuthAssurance.NONE)
            with self.subTest(mechanism=mechanism.value):
                event = row_to_audit_event(_Row(
                    auth_mechanism=mechanism.value,
                    auth_assurance=assurance.value,
                    session_reference=("SES-0123456789abcdef0123"
                                       if mechanism is AuthMechanism.SESSION
                                       else None)))
                self.assertIs(event.auth_mechanism, mechanism)
                self.assertIs(event.auth_assurance, assurance)

    def test_an_unknown_stored_value_raises_rather_than_passing_through(self):
        """A row nobody wrote is refused, not carried into the chain."""
        with self.assertRaises(ValueError):
            row_to_audit_event(_Row(auth_mechanism="MAGIC"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
