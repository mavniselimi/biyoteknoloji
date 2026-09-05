# -*- coding: utf-8 -*-
"""User lifecycle and server-side sessions (WP-23).

The assertions worth reading are the ones about *revocation*. Almost every
security bug in a session system is a state change that should have invalidated
a session and did not - a demoted admin whose old cookie still carries ADMIN, a
disabled account whose session runs until it expires on its own. So this file
checks the generation counter moves on every such change, and checks it by
enumerating the transitions rather than by testing the ones somebody
remembered.
"""

from __future__ import annotations

import datetime as _dt
import unittest

from pgx.security.errors import SessionInvalid, UserAdministrationError
from pgx.security.sessions import (DEFAULT_ABSOLUTE_SECONDS,
                                   SESSION_TOKEN_BYTES, SessionPolicy,
                                   SessionRecord, build_session,
                                   matches_token, new_session_token,
                                   token_digest)
from pgx.security.users import UserRecord, canonical_username
from pgx.security.vocabulary import (SESSION_COOKIE_NAME,
                                     SessionRevocationReason, UserStatus)
from tests.fixtures.wp23.security import NOW, RecordingHasher, user


class TestUsernamesAreGovernedIdentifiers(unittest.TestCase):

    def test_case_folding_happens_in_exactly_one_place(self):
        self.assertEqual(canonical_username("  ALICE.Smith "), "alice.smith")

    def test_an_email_address_is_not_a_username(self):
        """Deliberate. This system stores no personal data, and an email
        address is personal data that would then need protecting."""
        with self.assertRaises(UserAdministrationError):
            canonical_username("alice@example.org")

    def test_bounds_and_charset_are_enforced(self):
        for bad in ("ab", "x" * 65, "-leading", "has space", "Ünicode"):
            with self.subTest(username=bad):
                with self.assertRaises(UserAdministrationError):
                    canonical_username(bad)


class TestUserRecordInvariants(unittest.TestCase):

    def test_an_active_account_must_have_a_password_hash(self):
        with self.assertRaises(UserAdministrationError):
            UserRecord(user_id="u", username="tester", role="ADMIN",
                       password_hash="", status=UserStatus.ACTIVE,
                       auth_generation=1, failed_login_count=0,
                       locked_until=None, created_at=NOW, updated_at=NOW,
                       password_changed_at=NOW)

    def test_the_repr_never_carries_the_password_hash(self):
        record = user(hasher=RecordingHasher())
        self.assertNotIn(record.password_hash, repr(record))
        self.assertNotIn("password", repr(record).lower())

    def test_the_safe_projection_has_no_hash_field(self):
        projection = user(hasher=RecordingHasher()).safe_projection()
        for key in projection:
            with self.subTest(field=key):
                self.assertNotIn("password_hash", key)
        self.assertNotIn("password_hash", projection)

    def test_an_unknown_role_is_refused(self):
        with self.assertRaises(UserAdministrationError):
            user(role="SUPERUSER", hasher=RecordingHasher())

    def test_there_is_no_delete_transition(self):
        """DISABLED is terminal-and-reversible; nothing erases a user."""
        record = user(hasher=RecordingHasher())
        for name in ("delete", "remove", "purge", "erase", "destroy"):
            with self.subTest(method=name):
                self.assertFalse(hasattr(record, name))


class TestEveryRevokingChangeMovesTheGeneration(unittest.TestCase):
    """Enumerated, not sampled.

    Listing the transitions here means a future transition that forgets to
    bump the generation fails this test by being absent from the list, which a
    reviewer notices, rather than by silently not being covered.
    """

    def setUp(self):
        self.hasher = RecordingHasher()
        self.record = user(hasher=self.hasher)

    def _generation_moved(self, changed):
        return changed.auth_generation > self.record.auth_generation

    def test_password_change_revokes(self):
        changed = self.record.with_password("$argon2id$new", NOW)
        self.assertTrue(self._generation_moved(changed))

    def test_role_change_revokes(self):
        self.assertTrue(self._generation_moved(
            self.record.with_role("DEMO_USER", NOW)))

    def test_disable_revokes(self):
        self.assertTrue(self._generation_moved(self.record.disabled(NOW)))

    def test_enable_revokes(self):
        disabled = self.record.disabled(NOW)
        self.assertGreater(disabled.enabled(NOW).auth_generation,
                           disabled.auth_generation)

    def test_lock_revokes(self):
        locked = self.record
        for _ in range(5):
            locked = locked.with_failed_login(NOW)
        self.assertIs(locked.status, UserStatus.LOCKED)
        self.assertTrue(self._generation_moved(locked))

    def test_explicit_session_revocation_moves_it(self):
        self.assertTrue(self._generation_moved(
            self.record.with_revoked_sessions(NOW)))

    def test_a_successful_login_does_not_move_it(self):
        """The one exception, and it has to be: bumping here would revoke the
        session the login just created."""
        failed = self.record.with_failed_login(NOW)
        recovered = failed.with_successful_login(NOW)
        self.assertEqual(recovered.auth_generation, failed.auth_generation)
        self.assertEqual(recovered.failed_login_count, 0)

    def test_a_no_op_role_change_is_refused(self):
        """Refusing beats silently revoking every session for nothing."""
        with self.assertRaises(UserAdministrationError):
            self.record.with_role(self.record.role, NOW)


class TestLockoutIsTimeBounded(unittest.TestCase):

    def test_a_lock_expires_without_a_scheduler(self):
        record = user(hasher=RecordingHasher())
        for _ in range(5):
            record = record.with_failed_login(NOW)
        self.assertTrue(record.is_locked_at(NOW))
        later = NOW + _dt.timedelta(seconds=901)
        self.assertFalse(record.is_locked_at(later))
        self.assertTrue(record.may_authenticate_at(later))

    def test_a_disabled_account_never_authenticates(self):
        record = user(hasher=RecordingHasher()).disabled(NOW)
        self.assertFalse(record.may_authenticate_at(
            NOW + _dt.timedelta(days=365)))


class TestSessionTokensAndDigests(unittest.TestCase):

    def test_the_token_carries_at_least_256_bits(self):
        self.assertGreaterEqual(SESSION_TOKEN_BYTES * 8, 256)
        tokens = {new_session_token() for _ in range(64)}
        self.assertEqual(len(tokens), 64)
        for token in tokens:
            with self.subTest(length=len(token)):
                self.assertGreaterEqual(len(token), 43)

    def test_only_a_digest_is_stored(self):
        token = new_session_token()
        record = build_session(
            session_id="s-1", user_id="u-1", role="ADMIN", token=token,
            csrf_secret="x" * 32, auth_generation=1, now=NOW,
            policy=SessionPolicy())
        self.assertEqual(record.token_digest, token_digest(token))
        for value in (repr(record), str(record.safe_projection())):
            with self.subTest(rendering=value[:40]):
                self.assertNotIn(token, value)
                self.assertNotIn(record.token_digest, value)
                self.assertNotIn(record.csrf_secret, value)

    def test_a_record_cannot_be_built_holding_a_raw_token(self):
        with self.assertRaises(SessionInvalid):
            SessionRecord(
                session_id="s", user_id="u", role="ADMIN",
                token_digest=new_session_token(), csrf_secret="x" * 32,
                auth_generation=1, created_at=NOW, last_seen_at=NOW,
                idle_expires_at=NOW, absolute_expires_at=NOW)

    def test_matching_is_by_digest_and_rejects_another_token(self):
        token = new_session_token()
        record = build_session(
            session_id="s-1", user_id="u-1", role="ADMIN", token=token,
            csrf_secret="x" * 32, auth_generation=1, now=NOW,
            policy=SessionPolicy())
        self.assertTrue(matches_token(record, token))
        self.assertFalse(matches_token(record, new_session_token()))
        self.assertFalse(matches_token(record, ""))


class TestExpiryIsAnExactBoundary(unittest.TestCase):

    def setUp(self):
        self.policy = SessionPolicy(idle_seconds=600, absolute_seconds=3600)
        self.record = build_session(
            session_id="s-1", user_id="u-1", role="ADMIN",
            token=new_session_token(), csrf_secret="x" * 32,
            auth_generation=1, now=NOW, policy=self.policy)

    def test_now_equal_to_expiry_is_expired(self):
        """``now >= expires_at``. The boundary belongs to the expired side,
        and it is written once so two call sites cannot disagree by a second.
        """
        boundary = self.record.expires_at
        self.assertTrue(self.record.is_expired_at(boundary))
        self.assertFalse(self.record.is_expired_at(
            boundary - _dt.timedelta(microseconds=1)))
        self.assertTrue(self.record.is_expired_at(
            boundary + _dt.timedelta(microseconds=1)))

    def test_idle_expiry_ends_an_unused_session(self):
        idle = NOW + _dt.timedelta(seconds=600)
        self.assertTrue(self.record.is_expired_at(idle))
        self.assertIs(self.record.expiry_reason_at(idle),
                      SessionRevocationReason.IDLE_EXPIRED)

    def test_touching_slides_idle_but_never_absolute(self):
        record = self.record
        for step in range(1, 8):
            record = record.touched(NOW + _dt.timedelta(seconds=300 * step),
                                    self.policy)
        self.assertEqual(record.absolute_expires_at,
                         self.record.absolute_expires_at)
        absolute = self.record.absolute_expires_at
        self.assertTrue(record.is_expired_at(absolute))
        self.assertIs(record.expiry_reason_at(absolute),
                      SessionRevocationReason.ABSOLUTE_EXPIRED)

    def test_touching_never_pushes_idle_past_absolute(self):
        late = self.record.absolute_expires_at - _dt.timedelta(seconds=30)
        touched = self.record.touched(late, self.policy)
        self.assertLessEqual(touched.idle_expires_at,
                             touched.absolute_expires_at)


class TestTheCookiePolicyCannotBeWeakened(unittest.TestCase):

    def test_secure_and_httponly_are_not_configurable_off(self):
        """A flag that could turn either off is a flag somebody sets while
        testing over plain HTTP and never sets back."""
        for kwargs in ({"cookie_secure": False}, {"cookie_http_only": False}):
            with self.subTest(**kwargs):
                with self.assertRaises(ValueError):
                    SessionPolicy(**kwargs)

    def test_samesite_none_is_refused(self):
        with self.assertRaises(ValueError):
            SessionPolicy(cookie_same_site="None")

    def test_the_cookie_name_uses_the_host_prefix(self):
        """``__Host-`` is enforced by the browser: it requires Secure, Path=/
        and no Domain, so a widened scope stops the cookie being accepted
        rather than silently broadening it."""
        self.assertTrue(SESSION_COOKIE_NAME.startswith("__Host-"))

    def test_a_path_other_than_root_is_refused(self):
        with self.assertRaises(ValueError):
            SessionPolicy(cookie_path="/app")

    def test_an_absolute_bound_below_the_idle_bound_is_refused(self):
        with self.assertRaises(ValueError):
            SessionPolicy(idle_seconds=3600, absolute_seconds=600)

    def test_the_default_absolute_bound_is_finite_and_short(self):
        self.assertLessEqual(DEFAULT_ABSOLUTE_SECONDS, 7 * 24 * 3600)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
