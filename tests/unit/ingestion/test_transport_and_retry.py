# -*- coding: utf-8 -*-
"""Transport policy, retry, backoff and rate limits (WP-04).

Socket-free. The sleeper records delays instead of sleeping, so the real
backoff arithmetic is exercised and the suite still finishes in milliseconds.

The tests that matter most here are the negative ones. Retrying a 401 is not
merely wasteful: it looks like a brute-force attempt from the far end. Retrying
a 429 that was really quota exhaustion makes the quota worse. Each
non-retryable status is asserted individually, with the transport's call count
as the evidence.
"""

from __future__ import annotations

import datetime as _dt
import unittest

from pgx.ingestion.common.errors import (
    ConfigurationError, PermanentTransportError, ResponseTooLargeError,
    ResponseValidationError, RetryBudgetExhaustedError, SecurityPolicyError,
    TransientTransportError,
)
from pgx.ingestion.common.http import (
    CREDENTIAL_HEADER_NAMES, TransportPolicy, parse_rate_limit,
    parse_retry_after, request_key,
)
from pgx.ingestion.common.models import HttpRequest, HttpResponse
from pgx.ingestion.common.retry import (
    NON_RETRYABLE_STATUSES, RETRYABLE_STATUSES, RetryPolicy, execute_with_retry,
)

from tests.unit.ingestion._fakes import (
    EPOCH, FrozenClock, RecordingSleeper, ScriptedTransport, StepClock,
    data_page, fixed_random, json_response, raw_response,
)

REQUEST = HttpRequest(
    method="GET", base_url="https://api.clinpgx.org/v1", path="/data/gene",
    endpoint_id="gene_lookup", query=(("symbol", "CYP2C19"),),
    timeout_seconds=30.0)


def _run(script, policy=None, clock=None, sleeper=None, random_value=0.5):
    """Execute one retried request against a scripted transport."""
    transport = ScriptedTransport(script)
    sleeper = sleeper or RecordingSleeper()
    outcome = execute_with_retry(
        transport=transport, request=REQUEST,
        policy=policy or RetryPolicy(),
        clock=clock or StepClock(step_seconds=0.0),
        sleeper=sleeper, random_source=fixed_random(random_value))
    return outcome, transport, sleeper


class TestSuccessPath(unittest.TestCase):

    def test_a_200_returns_immediately(self):
        outcome, transport, sleeper = _run([data_page([{"id": 1}])])
        self.assertTrue(outcome.succeeded)
        self.assertEqual(transport.call_count, 1)
        self.assertEqual(sleeper.delays, [], "a success must not sleep")

    def test_one_attempt_is_recorded(self):
        outcome, _, _ = _run([data_page([])])
        self.assertEqual(len(outcome.attempts), 1)
        self.assertEqual(outcome.attempts[0].attempt_number, 1)
        self.assertEqual(outcome.attempts[0].status_code, 200)

    def test_the_body_is_returned_byte_for_byte(self):
        body = b'{"data": [{"weird": "\xc3\xa7"}]}'
        outcome, _, _ = _run([raw_response(body)])
        self.assertEqual(outcome.response.body, body)


class TestTransientFailuresAreRetried(unittest.TestCase):

    def test_a_timeout_is_retried_then_succeeds(self):
        outcome, transport, sleeper = _run([
            TransientTransportError("request timed out"),
            data_page([{"id": 1}])])
        self.assertTrue(outcome.succeeded)
        self.assertEqual(transport.call_count, 2)
        self.assertEqual(len(sleeper.delays), 1)

    def test_a_connection_error_is_retried(self):
        outcome, transport, _ = _run([
            TransientTransportError("connection reset by peer"),
            TransientTransportError("connection reset by peer"),
            data_page([])])
        self.assertTrue(outcome.succeeded)
        self.assertEqual(transport.call_count, 3)

    def test_each_retryable_status_is_retried(self):
        for status in RETRYABLE_STATUSES:
            with self.subTest(status=status):
                outcome, transport, _ = _run([
                    json_response({"error": "x"}, status_code=status),
                    data_page([])])
                self.assertTrue(outcome.succeeded)
                self.assertEqual(transport.call_count, 2)

    def test_every_attempt_is_recorded_including_the_failures(self):
        outcome, _, _ = _run([
            json_response({}, status_code=503),
            json_response({}, status_code=503),
            data_page([])])
        self.assertEqual(len(outcome.attempts), 3)
        self.assertEqual([a.status_code for a in outcome.attempts],
                         [503, 503, 200])
        self.assertEqual(outcome.attempts[0].error_code, "HTTP_503")
        self.assertIn("retryable", outcome.attempts[0].retry_reason)


class TestPermanentFailuresAreNotRetried(unittest.TestCase):
    """The call count is the evidence."""

    def test_each_non_retryable_status_is_attempted_once(self):
        for status in NON_RETRYABLE_STATUSES:
            with self.subTest(status=status):
                outcome, transport, sleeper = _run([
                    json_response({"error": "x"}, status_code=status)])
                self.assertFalse(outcome.succeeded)
                self.assertEqual(transport.call_count, 1,
                                 "status %d must not be retried" % status)
                self.assertEqual(sleeper.delays, [])
                self.assertIsInstance(outcome.error, PermanentTransportError)

    def test_a_404_names_itself_in_the_error(self):
        outcome, _, _ = _run([json_response({}, status_code=404)])
        self.assertIn("404", str(outcome.error))
        self.assertEqual(outcome.error.status_code, 404)

    def test_a_permanent_transport_error_is_not_retried(self):
        outcome, transport, _ = _run([PermanentTransportError("gone", 410)])
        self.assertEqual(transport.call_count, 1)
        self.assertIsInstance(outcome.error, PermanentTransportError)

    def test_a_response_validation_error_is_not_retried(self):
        """Re-fetching corrupt JSON produces corrupt JSON."""
        outcome, transport, _ = _run([ResponseValidationError("corrupt JSON")])
        self.assertEqual(transport.call_count, 1)

    def test_a_configuration_error_propagates_rather_than_retrying(self):
        transport = ScriptedTransport([ConfigurationError("no timeout")])
        with self.assertRaises(ConfigurationError):
            execute_with_retry(transport, REQUEST, RetryPolicy(),
                               clock=StepClock(step_seconds=0.0),
                               sleeper=RecordingSleeper(),
                               random_source=fixed_random())
        self.assertEqual(transport.call_count, 1)

    def test_a_security_policy_error_propagates(self):
        transport = ScriptedTransport([SecurityPolicyError("host refused")])
        with self.assertRaises(SecurityPolicyError):
            execute_with_retry(transport, REQUEST, RetryPolicy(),
                               clock=StepClock(step_seconds=0.0),
                               sleeper=RecordingSleeper(),
                               random_source=fixed_random())

    def test_a_policy_listing_ingestion_error_still_refuses_a_refused_host(self):
        """Non-retryable classes are checked before the retryable list."""
        from pgx.ingestion.common.errors import IngestionError

        policy = RetryPolicy(retryable_exceptions=(IngestionError,))
        self.assertFalse(policy.should_retry_exception(
            SecurityPolicyError("host refused")))
        self.assertFalse(policy.should_retry_exception(
            PermanentTransportError("404", 404)))


class TestBounds(unittest.TestCase):

    def test_max_attempts_is_honoured(self):
        policy = RetryPolicy(max_attempts=3)
        outcome, transport, _ = _run(
            [json_response({}, status_code=503) for _ in range(5)], policy)
        self.assertEqual(transport.call_count, 3)
        self.assertIsInstance(outcome.error, RetryBudgetExhaustedError)
        self.assertEqual(outcome.error.attempts, 3)

    def test_a_single_attempt_policy_never_retries(self):
        outcome, transport, _ = _run(
            [json_response({}, status_code=503)], RetryPolicy(max_attempts=1))
        self.assertEqual(transport.call_count, 1)

    def test_the_elapsed_budget_stops_a_slow_retry_loop(self):
        """Attempts alone are not enough: five waits of 300s is 25 minutes."""
        policy = RetryPolicy(max_attempts=10, max_elapsed_seconds=5.0)
        outcome, transport, _ = _run(
            [json_response({}, status_code=503) for _ in range(10)],
            policy, clock=StepClock(step_seconds=4.0))
        self.assertIsInstance(outcome.error, RetryBudgetExhaustedError)
        self.assertLess(transport.call_count, 10)
        self.assertEqual(outcome.attempts[-1].error_code, "MAX_ELAPSED_EXCEEDED")

    def test_a_frozen_clock_never_trips_the_elapsed_budget(self):
        policy = RetryPolicy(max_attempts=3, max_elapsed_seconds=0.001)
        outcome, transport, _ = _run(
            [json_response({}, status_code=503) for _ in range(3)],
            policy, clock=FrozenClock())
        self.assertEqual(transport.call_count, 3)

    def test_backoff_grows_exponentially_and_is_capped(self):
        policy = RetryPolicy(initial_delay_seconds=1.0, multiplier=2.0,
                             max_delay_seconds=5.0, jitter_ratio=0.0)
        self.assertEqual([policy.base_delay(n) for n in range(1, 6)],
                         [1.0, 2.0, 4.0, 5.0, 5.0])

    def test_jitter_stays_within_its_ratio(self):
        policy = RetryPolicy(jitter_ratio=0.25)
        for value in (0.0, 0.25, 0.5, 0.75, 1.0):
            with self.subTest(random_value=value):
                delay = policy.apply_jitter(4.0, value)
                self.assertGreaterEqual(delay, 3.0)
                self.assertLessEqual(delay, 5.0)

    def test_zero_jitter_is_exact(self):
        policy = RetryPolicy(jitter_ratio=0.0)
        self.assertEqual(policy.apply_jitter(4.0, 0.99), 4.0)

    def test_jitter_never_goes_negative(self):
        policy = RetryPolicy(jitter_ratio=1.0)
        self.assertGreaterEqual(policy.apply_jitter(1.0, 0.0), 0.0)

    def test_an_invalid_policy_is_refused(self):
        for kwargs in ({"max_attempts": 0}, {"multiplier": 0.5},
                       {"jitter_ratio": 2.0}, {"initial_delay_seconds": -1},
                       {"max_delay_seconds": -1}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ConfigurationError):
                    RetryPolicy(**kwargs)

    def test_the_suite_never_actually_sleeps(self):
        _, _, sleeper = _run([
            json_response({}, status_code=503),
            json_response({}, status_code=503),
            data_page([])])
        self.assertGreater(sleeper.total, 0.0, "backoff was computed")
        self.assertIsInstance(sleeper.delays[0], float)


class TestRetryAfter(unittest.TestCase):

    def test_seconds_form_is_honoured(self):
        policy = RetryPolicy(initial_delay_seconds=0.5, max_delay_seconds=60.0)
        _, _, sleeper = _run([
            json_response({}, status_code=429,
                          headers={"Retry-After": "12"}),
            data_page([])], policy)
        self.assertEqual(sleeper.delays, [12.0])

    def test_http_date_form_is_honoured(self):
        when = (EPOCH + _dt.timedelta(seconds=30)).strftime(
            "%a, %d %b %Y %H:%M:%S GMT")
        policy = RetryPolicy(max_delay_seconds=60.0)
        _, _, sleeper = _run([
            json_response({}, status_code=503, headers={"Retry-After": when}),
            data_page([])], policy, clock=FrozenClock())
        self.assertAlmostEqual(sleeper.delays[0], 30.0, places=0)

    def test_a_retry_after_is_clamped_to_the_maximum_delay(self):
        """A server cannot park a run for an hour."""
        policy = RetryPolicy(max_delay_seconds=10.0)
        _, _, sleeper = _run([
            json_response({}, status_code=429,
                          headers={"Retry-After": "3600"}),
            data_page([])], policy)
        self.assertEqual(sleeper.delays, [10.0])

    def test_a_malformed_retry_after_falls_back_to_backoff(self):
        policy = RetryPolicy(initial_delay_seconds=2.0, jitter_ratio=0.0)
        _, _, sleeper = _run([
            json_response({}, status_code=503,
                          headers={"Retry-After": "soon please"}),
            data_page([])], policy)
        self.assertEqual(sleeper.delays, [2.0])

    def test_a_past_date_yields_no_wait_rather_than_a_negative_one(self):
        past = (EPOCH - _dt.timedelta(seconds=60)).strftime(
            "%a, %d %b %Y %H:%M:%S GMT")
        self.assertEqual(parse_retry_after(past, EPOCH), 0.0)

    def test_the_header_is_recorded_on_the_attempt(self):
        outcome, _, _ = _run([
            json_response({}, status_code=429, headers={"Retry-After": "7"}),
            data_page([])])
        self.assertEqual(outcome.attempts[0].retry_after_seconds, 7.0)

    def test_absent_and_empty_headers_return_none(self):
        self.assertIsNone(parse_retry_after(None))
        self.assertIsNone(parse_retry_after("   "))


class TestRateLimitMetadata(unittest.TestCase):

    def test_standard_headers_are_read(self):
        response = json_response({}, headers={
            "X-RateLimit-Limit": "100", "X-RateLimit-Remaining": "42",
            "X-RateLimit-Reset": "30.5"})
        info = parse_rate_limit(response)
        self.assertEqual((info.limit, info.remaining, info.reset_seconds),
                         (100, 42, 30.5))

    def test_the_unprefixed_spelling_is_also_read(self):
        response = json_response({}, headers={
            "RateLimit-Limit": "60", "RateLimit-Remaining": "1"})
        info = parse_rate_limit(response)
        self.assertEqual((info.limit, info.remaining), (60, 1))

    def test_absence_is_recorded_as_absence_not_invented(self):
        info = parse_rate_limit(json_response({}))
        self.assertTrue(info.is_empty)
        self.assertIsNone(info.limit)

    def test_a_malformed_value_becomes_none_rather_than_raising(self):
        info = parse_rate_limit(json_response({}, headers={
            "X-RateLimit-Limit": "lots"}))
        self.assertIsNone(info.limit)


class TestTransportPolicy(unittest.TestCase):

    def setUp(self):
        self.policy = TransportPolicy(allowed_hosts=("api.clinpgx.org",))

    def test_an_empty_allowlist_is_refused(self):
        with self.assertRaises(ConfigurationError):
            TransportPolicy(allowed_hosts=())

    def test_http_is_refused(self):
        with self.assertRaises(SecurityPolicyError):
            self.policy.check_url("http://api.clinpgx.org/v1/data/gene")

    def test_an_unlisted_host_is_refused(self):
        with self.assertRaises(SecurityPolicyError):
            self.policy.check_url("https://evil.example.com/v1/data/gene")

    def test_the_allowed_host_is_permitted(self):
        self.policy.check_url("https://api.clinpgx.org/v1/data/gene")

    def test_a_cross_host_redirect_is_refused(self):
        with self.assertRaises(SecurityPolicyError) as caught:
            self.policy.check_redirect("https://api.clinpgx.org/v1/x",
                                       "https://evil.example.com/y")
        self.assertIn("cross-host", str(caught.exception))

    def test_a_same_host_redirect_is_permitted(self):
        self.policy.check_redirect("https://api.clinpgx.org/v1/x",
                                   "https://api.clinpgx.org/v1/y")

    def test_a_missing_timeout_is_refused(self):
        for value in (None, 0, -1):
            with self.subTest(timeout=value):
                with self.assertRaises(ConfigurationError):
                    self.policy.check_timeout(value)

    def test_an_unbounded_timeout_is_refused(self):
        with self.assertRaises(ConfigurationError):
            self.policy.check_timeout(10_000.0)

    def test_a_reasonable_timeout_is_accepted(self):
        self.policy.check_timeout(30.0)


class TestNoNetworkAtImportTime(unittest.TestCase):
    """Importing a module must not open a connection."""

    def test_importing_the_ingestion_packages_opens_nothing(self):
        import socket

        original = socket.socket
        calls = []

        def _forbidden(*args, **kwargs):
            calls.append(args)
            raise AssertionError("a socket was created during import")

        socket.socket = _forbidden
        try:
            import importlib

            for name in ("pgx.ingestion.common.http",
                         "pgx.ingestion.common.cache",
                         "pgx.ingestion.clinpgx.catalog",
                         "pgx.ingestion.clinpgx.client",
                         "pgx.ingestion.clinpgx.adapter",
                         "pgx.application.ingestion_service",
                         "pgx.application.ingestion_cli"):
                importlib.reload(importlib.import_module(name))
        finally:
            socket.socket = original
        self.assertEqual(calls, [])

    def test_building_the_clinpgx_transport_opens_nothing(self):
        import socket

        from pgx.ingestion.clinpgx.client import build_clinpgx_transport

        original = socket.socket
        socket.socket = lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("a socket was created"))
        try:
            transport = build_clinpgx_transport(env={})
        finally:
            socket.socket = original
        self.assertIsNotNone(transport)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
