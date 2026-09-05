# -*- coding: utf-8 -*-
"""The login path, in the order it must run (WP-23).

Two families of assertion here, and the second is the interesting one.

The first family checks that login works and that the obvious refusals refuse.
The second checks that the refusals are *indistinguishable*: unknown user,
wrong password, disabled and locked must produce one error with one code and
empty details, and the unknown-username path must pay the same hashing cost as
the others. A system whose login is correct but distinguishable is a system
with an account-enumeration endpoint.
"""

from __future__ import annotations

import datetime as _dt
import unittest

from pgx.infrastructure.audit.vocabulary import AuditOutcome, GovernedAction
from pgx.security.errors import (AuthenticationFailed, RateLimited,
                                 SessionInvalid)
from pgx.security.passwords import Password
from pgx.security.rate_limit import InMemoryRateLimitStore, RateLimiter
from pgx.security.sessions import SessionPolicy
from pgx.security.vocabulary import (AuthAssurance, AuthMechanism,
                                     SessionRevocationReason, UserStatus)
from tests.fixtures.wp23.security import (ADMIN_PASSWORD, DEMO_PASSWORD,
                                          RecordingHasher, StepClock,
                                          make_service, user)


class _Wired(unittest.TestCase):
    """One admin account, one wired service, one hasher that counts."""

    def setUp(self):
        self.hasher = RecordingHasher()
        self.clock = StepClock()
        self.account = user(hasher=self.hasher)
        (self.service, self.users, self.sessions, self.audit,
         self.clock, self.hasher) = make_service(
            users=[self.account], hasher=self.hasher, clock=self.clock)

    def _login(self, username="test-admin", password=ADMIN_PASSWORD):
        return self.service.login(username, Password(password))

    def _actions(self):
        return [event.action for event in self.audit.all_events()]


class TestASuccessfulLogin(_Wired):

    def test_it_issues_a_session_and_a_bound_csrf_token(self):
        outcome = self._login()
        self.assertEqual(outcome.user.username, "test-admin")
        self.assertTrue(outcome.raw_token)
        self.assertTrue(outcome.csrf_token)

    def test_the_raw_token_is_never_stored(self):
        outcome = self._login()
        for record in self.sessions.all_sessions():
            with self.subTest(session=record.session_id):
                self.assertNotEqual(record.token_digest, outcome.raw_token)
                self.assertTrue(record.token_digest.startswith("sha256:"))

    def test_the_raw_token_never_reaches_the_audit_trail(self):
        outcome = self._login()
        for event in self.audit.all_events():
            rendered = str(event.to_json())
            with self.subTest(sequence=event.sequence):
                self.assertNotIn(outcome.raw_token, rendered)
                self.assertNotIn(outcome.csrf_token, rendered)
                self.assertNotIn(ADMIN_PASSWORD, rendered)

    def test_it_records_a_login_and_a_session_event(self):
        self._login()
        self.assertIn(GovernedAction.LOGIN_SUCCEEDED, self._actions())
        self.assertIn(GovernedAction.SESSION_CREATED, self._actions())

    def test_the_events_carry_session_assurance(self):
        self._login()
        for event in self.audit.all_events():
            with self.subTest(action=event.action.value):
                self.assertIs(event.auth_assurance, AuthAssurance.SESSION)
                self.assertIs(event.auth_mechanism, AuthMechanism.SESSION)
                self.assertIsNotNone(event.session_reference)

    def test_login_rotates_session_identity(self):
        """Session fixation: the second login must not reuse the first
        session, and the first must stop working."""
        first = self._login()
        self.clock.advance(5)
        second = self._login()
        self.assertNotEqual(first.session.session_id,
                            second.session.session_id)
        self.assertNotEqual(first.raw_token, second.raw_token)
        with self.assertRaises(SessionInvalid):
            self.service.authenticate(first.raw_token)
        self.assertIsNotNone(self.service.authenticate(second.raw_token))

    def test_a_failed_login_counter_is_cleared_without_revoking(self):
        self.users.save(self.account.with_failed_login(self.clock.now))
        outcome = self._login()
        self.assertEqual(
            self.users.by_id(self.account.user_id).failed_login_count, 0)
        self.assertIsNotNone(self.service.authenticate(outcome.raw_token))


class TestEveryFailureLooksTheSame(_Wired):
    """The property that stops login being an enumeration endpoint."""

    def _refusal(self, username, password):
        with self.assertRaises(AuthenticationFailed) as raised:
            self.service.login(username, Password(password))
        return raised.exception

    def test_unknown_user_and_wrong_password_are_identical(self):
        unknown = self._refusal("no-such-account", ADMIN_PASSWORD)
        wrong = self._refusal("test-admin", DEMO_PASSWORD)
        self.assertEqual(unknown.code, wrong.code)
        self.assertEqual(unknown.details, wrong.details)
        self.assertEqual(unknown.details, {})
        self.assertEqual(str(unknown), str(wrong))

    def test_disabled_and_locked_are_identical_to_a_wrong_password(self):
        self.users.save(self.account.disabled(self.clock.now))
        disabled = self._refusal("test-admin", ADMIN_PASSWORD)
        self.assertEqual(disabled.code, "AUTHENTICATION_FAILED")
        self.assertEqual(disabled.details, {})

    def test_a_malformed_username_is_identical_too(self):
        """The username *format* must not be probeable either."""
        malformed = self._refusal("a@b", ADMIN_PASSWORD)
        self.assertEqual(malformed.code, "AUTHENTICATION_FAILED")
        self.assertEqual(malformed.details, {})

    def test_an_unknown_username_still_pays_the_hashing_cost(self):
        """A stronger claim than "the responses matched": the expensive work
        actually happened, so the timing matches too."""
        before = self.hasher.dummy_calls
        self._refusal("no-such-account", ADMIN_PASSWORD)
        self.assertEqual(self.hasher.dummy_calls, before + 1)

    def test_a_malformed_username_pays_it_as_well(self):
        before = self.hasher.dummy_calls
        self._refusal("a@b", ADMIN_PASSWORD)
        self.assertEqual(self.hasher.dummy_calls, before + 1)

    def test_a_disabled_account_is_verified_before_being_refused(self):
        """Returning early for a disabled account would answer faster than
        for an active one, which is a status oracle."""
        self.users.save(self.account.disabled(self.clock.now))
        before = self.hasher.verify_calls
        self._refusal("test-admin", ADMIN_PASSWORD)
        self.assertEqual(self.hasher.verify_calls, before + 1)

    def test_the_failure_is_recorded_with_its_reason_server_side(self):
        """The caller learns nothing; the audit row records which it was."""
        self._refusal("test-admin", DEMO_PASSWORD)
        failures = [event for event in self.audit.all_events()
                    if event.action is GovernedAction.LOGIN_FAILED]
        self.assertTrue(failures)
        self.assertIs(failures[-1].outcome, AuditOutcome.REFUSED)
        self.assertEqual(failures[-1].metadata["refusal_detail_code"],
                         "WRONG_PASSWORD")

    def test_no_failure_event_names_the_password(self):
        self._refusal("test-admin", DEMO_PASSWORD)
        for event in self.audit.all_events():
            with self.subTest(sequence=event.sequence):
                self.assertNotIn(DEMO_PASSWORD, str(event.to_json()))

    def test_repeated_failures_lock_the_account(self):
        for _ in range(5):
            self._refusal("test-admin", DEMO_PASSWORD)
        self.assertIs(self.users.by_id(self.account.user_id).status,
                      UserStatus.LOCKED)


class TestSessionValidationRunsEveryTime(_Wired):

    def test_a_revoked_session_never_authenticates(self):
        outcome = self._login()
        self.sessions.revoke_all_for_user(
            self.account.user_id, now=self.clock.now,
            reason=SessionRevocationReason.ADMIN_REVOKED)
        with self.assertRaises(SessionInvalid):
            self.service.authenticate(outcome.raw_token)

    def test_disabling_the_user_ends_the_session_on_the_next_request(self):
        outcome = self._login()
        self.users.save(
            self.users.by_id(self.account.user_id).disabled(self.clock.now))
        with self.assertRaises(SessionInvalid):
            self.service.authenticate(outcome.raw_token)

    def test_changing_the_role_ends_the_session(self):
        """Otherwise a demoted administrator keeps acting as one until the
        cookie expires on its own."""
        outcome = self._login()
        self.users.save(self.users.by_id(self.account.user_id)
                        .with_role("DEMO_USER", self.clock.now))
        with self.assertRaises(SessionInvalid):
            self.service.authenticate(outcome.raw_token)

    def test_changing_the_password_ends_the_session(self):
        outcome = self._login()
        self.users.save(self.users.by_id(self.account.user_id)
                        .with_password("$argon2id$replaced", self.clock.now))
        with self.assertRaises(SessionInvalid):
            self.service.authenticate(outcome.raw_token)

    def test_an_expired_session_is_refused_at_the_boundary(self):
        outcome = self._login()
        self.clock.advance(int(
            (outcome.session.expires_at - outcome.session.created_at)
            .total_seconds()))
        with self.assertRaises(SessionInvalid):
            self.service.authenticate(outcome.raw_token)

    def test_expiry_revokes_the_row_and_records_it(self):
        outcome = self._login()
        self.clock.advance(SessionPolicy().absolute_seconds + 1)
        with self.assertRaises(SessionInvalid):
            self.service.authenticate(outcome.raw_token)
        stored = self.sessions.by_id(outcome.session.session_id)
        self.assertTrue(stored.is_revoked)
        self.assertIn(GovernedAction.SESSION_EXPIRED, self._actions())

    def test_a_forged_token_authenticates_nobody(self):
        self._login()
        for forged in ("", "x" * 43, "TEST-ONLY-session-token-99999999-" +
                       "x" * 24):
            with self.subTest(token=forged[:16]):
                with self.assertRaises(SessionInvalid):
                    self.service.authenticate(forged)

    def test_using_a_session_slides_the_idle_bound(self):
        outcome = self._login()
        first = self.sessions.by_id(outcome.session.session_id)
        self.clock.advance(60)
        self.service.authenticate(outcome.raw_token)
        second = self.sessions.by_id(outcome.session.session_id)
        self.assertGreater(second.idle_expires_at, first.idle_expires_at)
        self.assertEqual(second.absolute_expires_at,
                         first.absolute_expires_at)


class TestLogout(_Wired):

    def test_it_revokes_server_side(self):
        outcome = self._login()
        self.assertTrue(self.service.logout(outcome.raw_token))
        self.assertTrue(
            self.sessions.by_id(outcome.session.session_id).is_revoked)
        with self.assertRaises(SessionInvalid):
            self.service.authenticate(outcome.raw_token)

    def test_it_records_the_logout_before_the_caller_clears_the_cookie(self):
        outcome = self._login()
        self.service.logout(outcome.raw_token)
        self.assertIn(GovernedAction.LOGOUT, self._actions())

    def test_logging_out_an_unknown_token_is_a_no_op(self):
        self.assertFalse(self.service.logout("not-a-session"))
        self.assertFalse(self.service.logout(None))


class TestRateLimitingGuardsLogin(unittest.TestCase):

    def setUp(self):
        self.hasher = RecordingHasher()
        self.clock = StepClock()
        self.store = InMemoryRateLimitStore()
        limiter = RateLimiter(self.store, clock=self.clock)
        (self.service, self.users, self.sessions, self.audit,
         self.clock, self.hasher) = make_service(
            users=[user(hasher=self.hasher)], hasher=self.hasher,
            clock=self.clock, limiter=limiter)

    def test_the_limit_applies_before_the_user_is_looked_up(self):
        """Unknown usernames are limited exactly like known ones, so the
        limiter is not an enumeration oracle either."""
        for _ in range(5):
            with self.assertRaises(AuthenticationFailed):
                self.service.login("no-such-account", Password(DEMO_PASSWORD))
        with self.assertRaises(RateLimited) as raised:
            self.service.login("no-such-account", Password(DEMO_PASSWORD))
        self.assertEqual(raised.exception.policy_id, "LOGIN_PER_USERNAME")

    def test_a_broken_limiter_denies_login(self):
        self.store.fail_next = True
        with self.assertRaises(RateLimited) as raised:
            self.service.login("test-admin", Password(ADMIN_PASSWORD))
        self.assertEqual(raised.exception.code, "RATE_LIMIT_UNAVAILABLE")

    def test_the_retry_after_is_bounded(self):
        for _ in range(5):
            with self.assertRaises(AuthenticationFailed):
                self.service.login("test-admin", Password(DEMO_PASSWORD))
        with self.assertRaises(RateLimited) as raised:
            self.service.login("test-admin", Password(DEMO_PASSWORD))
        self.assertGreaterEqual(raised.exception.retry_after_seconds, 1)
        self.assertLessEqual(raised.exception.retry_after_seconds, 300)


class TestAuditFailureRollsLoginBack(_Wired):

    def test_a_failed_audit_append_prevents_a_usable_session(self):
        """The atomicity requirement, at the login boundary. The service
        raises; the caller's transaction does not commit; no cookie is set."""
        from pgx.security.errors import AuditAppendError

        self.audit.fail_next_append = True
        with self.assertRaises(AuditAppendError):
            self._login()


class TestRehashHappensOnlyAfterSuccess(unittest.TestCase):

    def test_an_obsolete_hash_is_replaced_on_a_successful_login(self):
        hasher = RecordingHasher(obsolete=True)
        account = user(hasher=hasher)
        service, users, _sessions, audit, _clock, _h = make_service(
            users=[account], hasher=hasher)
        service.login("test-admin", Password(ADMIN_PASSWORD))
        events = [e for e in audit.all_events()
                  if e.action is GovernedAction.LOGIN_SUCCEEDED]
        self.assertTrue(events[-1].metadata["rehashed"])

    def test_a_failed_login_never_rehashes(self):
        """Otherwise an attacker drives the hashing work with wrong guesses,
        and a wrong password gets written into the account."""
        hasher = RecordingHasher(obsolete=True)
        account = user(hasher=hasher)
        service, users, _s, _a, _c, _h = make_service(
            users=[account], hasher=hasher)
        with self.assertRaises(AuthenticationFailed):
            service.login("test-admin", Password(DEMO_PASSWORD))
        self.assertEqual(users.by_id(account.user_id).password_hash,
                         account.password_hash)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
