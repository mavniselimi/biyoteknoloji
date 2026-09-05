# -*- coding: utf-8 -*-
"""Session-bound CSRF and declared rate limits (WP-23).

The CSRF assertions are all variations on one property: a token is worth
exactly one session. WP-17's development verifier held a single
process-global token, which meant a token scraped from any page worked on
every request from every user - honest as a fixture, useless as a defence. The
replacement binds the token to per-session key material, so "a token for one
session must not work for another" is true because the MAC key differs, not
because a check compares two ids.
"""

from __future__ import annotations

import datetime as _dt
import unittest

from pgx.security.csrf import (CSRF_TOKEN_VERSION, SessionBoundCsrf,
                               UnconfiguredCsrfService, new_csrf_secret)
from pgx.security.errors import CsrfFailure, RateLimited
from pgx.security.rate_limit import (POLICIES, POLICY_IDS,
                                     InMemoryRateLimitStore, RateLimiter,
                                     policy_document, scope_key)

NOW = _dt.datetime(2026, 9, 5, 12, 0, tzinfo=_dt.timezone.utc)


class TestCsrfTokensAreSessionBound(unittest.TestCase):

    def setUp(self):
        self.service = SessionBoundCsrf()
        self.secret_a = new_csrf_secret()
        self.secret_b = new_csrf_secret()
        self.token_a = self.service.issue(binding="session-a",
                                          secret=self.secret_a, now=NOW)

    def test_a_token_verifies_against_its_own_session(self):
        self.service.verify(self.token_a, binding="session-a",
                            secret=self.secret_a, now=NOW)

    def test_a_token_from_another_session_is_refused(self):
        """The property the process-global fixture could not have."""
        with self.assertRaises(CsrfFailure):
            self.service.verify(self.token_a, binding="session-b",
                                secret=self.secret_b, now=NOW)

    def test_the_same_binding_with_a_different_secret_is_refused(self):
        """Rotation changes the secret. This is why rotation invalidates."""
        with self.assertRaises(CsrfFailure):
            self.service.verify(self.token_a, binding="session-a",
                                secret=self.secret_b, now=NOW)

    def test_missing_malformed_and_expired_tokens_all_refuse(self):
        cases = {
            "missing": (None, NOW),
            "empty": ("", NOW),
            "no version": ("deadbeef", NOW),
            "wrong version": ("9.deadbeef", NOW),
            "no mac": (CSRF_TOKEN_VERSION + ".", NOW),
            "expired": (self.token_a, NOW + _dt.timedelta(hours=4)),
        }
        for label, (token, when) in cases.items():
            with self.subTest(case=label):
                with self.assertRaises(CsrfFailure):
                    self.service.verify(token, binding="session-a",
                                        secret=self.secret_a, now=when)

    def test_every_refusal_uses_the_same_code(self):
        """A caller who could tell "expired" from "wrong session" could probe
        the binding."""
        codes = set()
        for token, when in ((None, NOW), ("9.x", NOW),
                            (self.token_a, NOW + _dt.timedelta(hours=4))):
            try:
                self.service.verify(token, binding="session-a",
                                    secret=self.secret_a, now=when)
            except CsrfFailure as error:
                codes.add(error.code)
        self.assertEqual(codes, {"CSRF_TOKEN_INVALID"})

    def test_the_token_does_not_contain_the_session_identifier(self):
        """A page that is cached, screenshotted or pasted into a bug report
        must not hand over the session's name."""
        self.assertNotIn("session-a", self.token_a)
        self.assertNotIn(self.secret_a, self.token_a)

    def test_a_token_stays_valid_within_its_lifetime(self):
        for minutes in (0, 5, 30, 55):
            with self.subTest(minutes=minutes):
                self.service.verify(
                    self.token_a, binding="session-a", secret=self.secret_a,
                    now=NOW + _dt.timedelta(minutes=minutes))

    def test_issuing_without_a_secret_refuses(self):
        with self.assertRaises(CsrfFailure) as raised:
            self.service.issue(binding="session-a", secret="", now=NOW)
        self.assertEqual(raised.exception.code, "CSRF_NOT_CONFIGURED")

    def test_an_unconfigured_service_issues_nothing_and_accepts_nothing(self):
        service = UnconfiguredCsrfService()
        self.assertFalse(service.configured)
        for call in (lambda: service.issue(binding="s", secret="x", now=NOW),
                     lambda: service.verify("t", binding="s", secret="x",
                                            now=NOW)):
            with self.subTest():
                with self.assertRaises(CsrfFailure) as raised:
                    call()
                self.assertEqual(raised.exception.code,
                                 "CSRF_NOT_CONFIGURED")

    def test_an_unreasonable_lifetime_is_refused(self):
        for seconds in (10, 48 * 3600):
            with self.subTest(seconds=seconds):
                with self.assertRaises(ValueError):
                    SessionBoundCsrf(lifetime_seconds=seconds)


class TestRateLimitPoliciesAreDeclaredBeforeResults(unittest.TestCase):

    def test_login_and_assessment_are_both_covered(self):
        self.assertIn("LOGIN_PER_USERNAME", POLICY_IDS)
        self.assertIn("LOGIN_PER_ORIGIN", POLICY_IDS)
        self.assertIn("ASSESSMENT_PER_ACTOR", POLICY_IDS)

    def test_every_policy_bounds_its_retry_after_by_its_window(self):
        """A Retry-After longer than the window tells a client to wait longer
        than the limit lasts."""
        for policy in POLICIES:
            with self.subTest(policy=policy.policy_id):
                self.assertGreaterEqual(policy.retry_after_seconds, 1)
                self.assertLessEqual(policy.retry_after_seconds,
                                     policy.window_seconds)

    def test_every_policy_explains_itself(self):
        for policy in POLICIES:
            with self.subTest(policy=policy.policy_id):
                self.assertGreater(len(policy.rationale), 40)

    def test_the_document_reports_no_performance_result(self):
        """WP-24 owns throughput and latency; this document declares limits.

        The disclaimer field is excluded from the scan rather than the scan
        being softened. ``no_performance_claim`` is the sentence that *says*
        no result is reported, so it necessarily contains the words a naive
        substring search is looking for - and a search that matched its own
        disclaimer would have been "fixed" by deleting the disclaimer, which
        is the wrong repair.
        """
        document = policy_document()
        self.assertIn("no_performance_claim", document)
        self.assertIn("WP-24", document["no_performance_claim"])
        scanned = {key: value for key, value in document.items()
                   if key != "no_performance_claim"}
        rendered = str(scanned).lower()
        for forbidden in ("p95", "p50", "throughput", "requests per second",
                          "latency", "benchmark result"):
            with self.subTest(term=forbidden):
                self.assertNotIn(forbidden, rendered)


class TestTheLimiterDeniesRatherThanAllows(unittest.TestCase):

    def setUp(self):
        self.clock = [NOW]
        self.store = InMemoryRateLimitStore()
        self.limiter = RateLimiter(self.store, clock=lambda: self.clock[0])

    def test_the_limit_is_enforced_at_the_declared_count(self):
        for _ in range(5):
            self.limiter.check("LOGIN_PER_USERNAME", "someone")
        with self.assertRaises(RateLimited):
            self.limiter.check("LOGIN_PER_USERNAME", "someone")

    def test_a_new_window_resets_it(self):
        for _ in range(5):
            self.limiter.check("LOGIN_PER_USERNAME", "someone")
        self.clock[0] = NOW + _dt.timedelta(seconds=300)
        self.limiter.check("LOGIN_PER_USERNAME", "someone")

    def test_a_backend_failure_denies(self):
        """Allow-on-error is the design that turns a database blip into an
        unlimited password-guessing window."""
        self.store.fail_next = True
        with self.assertRaises(RateLimited) as raised:
            self.limiter.check("LOGIN_PER_USERNAME", "someone")
        self.assertEqual(raised.exception.code, "RATE_LIMIT_UNAVAILABLE")

    def test_no_backend_at_all_denies(self):
        with self.assertRaises(RateLimited) as raised:
            RateLimiter(None).check("ASSESSMENT_PER_ACTOR", "someone")
        self.assertEqual(raised.exception.code, "RATE_LIMIT_UNAVAILABLE")

    def test_check_returns_nothing_that_could_read_as_permission(self):
        """There is no truthy return value, so no call site can treat "the
        limiter said fine" as an authorisation."""
        self.assertIsNone(self.limiter.check("ASSESSMENT_PER_ACTOR", "x"))

    def test_an_undeclared_policy_raises_rather_than_not_limiting(self):
        with self.assertRaises(KeyError):
            self.limiter.check("LOGIN_PER_USERNAEM", "someone")

    def test_separate_identities_have_separate_budgets(self):
        for _ in range(5):
            self.limiter.check("LOGIN_PER_USERNAME", "first")
        self.limiter.check("LOGIN_PER_USERNAME", "second")


class TestKeysAreDigests(unittest.TestCase):

    def test_no_identity_is_stored_in_the_clear(self):
        for identity in ("alice", "203.0.113.7", "user@example.org"):
            with self.subTest(identity=identity):
                key = scope_key(identity)
                self.assertTrue(key.startswith("sha256:"))
                self.assertNotIn(identity, key)

    def test_the_document_states_the_proxy_header_policy(self):
        """A spoofable header used as a limit key is a limit an attacker
        sets."""
        note = policy_document()["proxy_header_policy"]
        self.assertIn("X-Forwarded-For", note)
        self.assertIn("not trusted", note)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
