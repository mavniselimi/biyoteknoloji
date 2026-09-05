# -*- coding: utf-8 -*-
"""Driver policy and credential hygiene (WP-02 corrective).

Two findings are proven here.

**Driver.** A bare ``postgresql://`` URL makes SQLAlchemy pick whatever DBAPI it
can find - in practice psycopg2, which is not a dependency of this project and
differs from psycopg 3 in JSONB adaptation. Silently connecting through it
would mean integration evidence gathered on a driver the project does not ship.
The URL is therefore normalised to ``postgresql+psycopg://`` and the
normalisation is recorded, while any *explicitly* named other driver is
rejected rather than rewritten.

**Credentials.** A driver error quotes the connection string back, so an
unsanitised message leaks a password into a log or CI transcript. No code path
that prints - ``repr``, ``str``, ``safe_url``, ``sanitize_message`` - may emit
one.

Standard library only; no connection is opened.
"""

from __future__ import annotations

import io
import os
import unittest

from pgx.infrastructure.db.config import (
    APPLICATION_DATABASE_URL_ENV, CREDENTIAL_PARAMETER_NAMES,
    REQUIRED_DRIVER_PREFIX, TEST_DATABASE_URL_ENV, DatabaseConfigurationError,
    load_database_config, normalize_driver, redact_url, sanitize_message,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))


def _read(relative: str) -> str:
    """Read a repository file, closing the handle."""
    with io.open(os.path.join(REPO_ROOT, relative), encoding="utf-8") as handle:
        return handle.read()


PASSWORD = "sup3r-s3cret-pw"
QUERY_SECRET = "qu3ry-s3cret-value"
FRAGMENT_SECRET = "fr4gment-s3cret-value"
DSN_SECRET = "dsn-s3cret-value"
BARE = "postgresql://pgx_dev:%s@localhost:5432/pgx_dev" % PASSWORD
PSYCOPG = "postgresql+psycopg://pgx_dev:%s@localhost:5432/pgx_dev" % PASSWORD


class TestDriverNormalisation(unittest.TestCase):

    def test_a_bare_postgres_url_is_normalised_to_psycopg3(self):
        url, normalised = normalize_driver(BARE)
        self.assertTrue(url.startswith(REQUIRED_DRIVER_PREFIX))
        self.assertTrue(normalised)

    def test_normalisation_preserves_everything_after_the_scheme(self):
        url, _ = normalize_driver(BARE)
        self.assertEqual(url, PSYCOPG)

    def test_an_explicit_psycopg3_url_is_left_alone(self):
        url, normalised = normalize_driver(PSYCOPG)
        self.assertEqual(url, PSYCOPG)
        self.assertFalse(normalised)

    def test_the_config_records_that_it_normalised(self):
        config = load_database_config({APPLICATION_DATABASE_URL_ENV: BARE})
        self.assertTrue(config.driver_was_normalized)
        self.assertTrue(config.url.startswith(REQUIRED_DRIVER_PREFIX))

    def test_the_config_records_when_it_did_not_normalise(self):
        config = load_database_config({APPLICATION_DATABASE_URL_ENV: PSYCOPG})
        self.assertFalse(config.driver_was_normalized)


class TestOtherDriversAreRejected(unittest.TestCase):
    """An explicitly named driver is an expectation, not a typo."""

    REJECTED = (
        "postgresql+psycopg2://u:p@h:5432/d",
        "postgresql+asyncpg://u:p@h:5432/d",
        "postgresql+pg8000://u:p@h:5432/d",
    )

    def test_each_explicit_driver_is_refused(self):
        for url in self.REJECTED:
            with self.subTest(url=url):
                with self.assertRaises(DatabaseConfigurationError):
                    load_database_config({APPLICATION_DATABASE_URL_ENV: url})

    def test_psycopg2_is_not_silently_rewritten(self):
        with self.assertRaises(DatabaseConfigurationError) as caught:
            load_database_config({
                APPLICATION_DATABASE_URL_ENV: "postgresql+psycopg2://u:p@h:5432/d"})
        self.assertIn("psycopg 3", str(caught.exception))

    def test_a_rejection_message_carries_no_password(self):
        with self.assertRaises(DatabaseConfigurationError) as caught:
            load_database_config({
                APPLICATION_DATABASE_URL_ENV:
                    "postgresql+asyncpg://u:%s@h:5432/d" % PASSWORD})
        self.assertNotIn(PASSWORD, str(caught.exception))


class TestNonPostgresBackendsAreRejected(unittest.TestCase):
    """SQLite would make an integration pass mean nothing."""

    def test_sqlite_is_refused(self):
        with self.assertRaises(DatabaseConfigurationError) as caught:
            load_database_config({APPLICATION_DATABASE_URL_ENV: "sqlite:///pgx.db"})
        self.assertIn("PostgreSQL", str(caught.exception))

    def test_mysql_is_refused(self):
        with self.assertRaises(DatabaseConfigurationError):
            load_database_config({APPLICATION_DATABASE_URL_ENV: "mysql://u:p@h/d"})

    def test_a_url_without_a_database_name_is_refused(self):
        with self.assertRaises(DatabaseConfigurationError):
            load_database_config({
                APPLICATION_DATABASE_URL_ENV: "postgresql://u:p@localhost:5432/"})

    def test_a_missing_variable_names_the_variable(self):
        with self.assertRaises(DatabaseConfigurationError) as caught:
            load_database_config({})
        self.assertIn(APPLICATION_DATABASE_URL_ENV, str(caught.exception))

    def test_the_test_variable_is_read_only_when_asked_for(self):
        config = load_database_config(
            {TEST_DATABASE_URL_ENV: PSYCOPG}, use_test_database=True)
        self.assertEqual(config.source_env_var, TEST_DATABASE_URL_ENV)
        with self.assertRaises(DatabaseConfigurationError):
            load_database_config({TEST_DATABASE_URL_ENV: PSYCOPG})


class TestCredentialsNeverReachOutput(unittest.TestCase):

    def setUp(self):
        self.config = load_database_config({APPLICATION_DATABASE_URL_ENV: PSYCOPG})

    def test_repr_hides_the_password(self):
        self.assertNotIn(PASSWORD, repr(self.config))

    def test_str_hides_the_password(self):
        self.assertNotIn(PASSWORD, str(self.config))

    def test_safe_url_hides_the_password(self):
        self.assertNotIn(PASSWORD, self.config.safe_url)
        self.assertIn("***", self.config.safe_url)

    def test_the_real_url_is_still_usable(self):
        self.assertIn(PASSWORD, self.config.url)

    def test_the_database_name_survives_redaction(self):
        self.assertEqual(self.config.database_name, "pgx_dev")
        self.assertIn("pgx_dev", self.config.safe_url)

    def test_redact_url_keeps_host_and_port(self):
        redacted = redact_url(PSYCOPG)
        self.assertIn("localhost", redacted)
        self.assertIn("5432", redacted)
        self.assertNotIn(PASSWORD, redacted)

    def test_redact_url_is_safe_on_a_non_url(self):
        self.assertEqual(redact_url("not a url"), "<invalid-url>")


class TestSanitizeMessage(unittest.TestCase):
    """Driver exceptions quote the URL back; sanitize before printing."""

    def test_a_password_inside_a_driver_message_is_removed(self):
        message = 'could not connect to "%s": timeout' % PSYCOPG
        sanitized = sanitize_message(message)
        self.assertNotIn(PASSWORD, sanitized)
        self.assertIn("***", sanitized)

    def test_surrounding_text_is_preserved(self):
        sanitized = sanitize_message("connection to %s failed" % PSYCOPG)
        self.assertTrue(sanitized.startswith("connection to "))
        self.assertTrue(sanitized.endswith(" failed"))

    def test_several_urls_in_one_message_are_all_sanitized(self):
        message = "%s and %s" % (PSYCOPG, BARE)
        self.assertNotIn(PASSWORD, sanitize_message(message))

    def test_text_without_a_url_is_unchanged(self):
        self.assertEqual(sanitize_message("relation does not exist"),
                         "relation does not exist")

    def test_a_non_string_is_coerced_not_crashed(self):
        self.assertEqual(sanitize_message(17), "17")


class TestQueryStringCredentialsAreMasked(unittest.TestCase):
    """The userinfo password is only one of the places a secret travels.

    psycopg accepts ``?sslpassword=`` in a URL, so masking userinfo alone left
    the real secret in the same log line, one field to the right.
    """

    def test_sslpassword_in_the_query_is_masked(self):
        redacted = redact_url(
            "postgresql+psycopg://user:%s@host/db?sslpassword=%s"
            % (PASSWORD, QUERY_SECRET))
        self.assertNotIn(QUERY_SECRET, redacted)
        self.assertNotIn(PASSWORD, redacted)

    def test_password_in_the_query_is_masked(self):
        redacted = redact_url(
            "postgresql+psycopg://u:p@h/db?password=%s&sslmode=require"
            % QUERY_SECRET)
        self.assertNotIn(QUERY_SECRET, redacted)

    def test_a_harmless_parameter_survives(self):
        redacted = redact_url(
            "postgresql+psycopg://u:p@h/db?sslmode=require&application_name=pgx")
        self.assertIn("sslmode=require", redacted)
        self.assertIn("application_name=pgx", redacted)

    def test_key_matching_is_case_insensitive(self):
        for key in ("PASSWORD", "SslPassword", "Api_Key", "TOKEN"):
            with self.subTest(key=key):
                redacted = redact_url(
                    "postgresql+psycopg://u:p@h/db?%s=%s" % (key, QUERY_SECRET))
                self.assertNotIn(QUERY_SECRET, redacted)

    def test_every_declared_credential_parameter_is_masked(self):
        for key in CREDENTIAL_PARAMETER_NAMES:
            with self.subTest(parameter=key):
                redacted = redact_url(
                    "https://api.example.com/v1?%s=%s" % (key, QUERY_SECRET))
                self.assertNotIn(QUERY_SECRET, redacted)

    def test_a_percent_encoded_query_secret_is_masked(self):
        redacted = redact_url("postgresql+psycopg://u:p@h/db?password=a%40b%23c")
        self.assertNotIn("a%40b%23c", redacted)
        self.assertNotIn("a@b#c", redacted)

    def test_a_percent_encoded_userinfo_password_is_masked(self):
        redacted = redact_url("postgresql+psycopg://u:p%40ss%3Aword@h/db")
        self.assertNotIn("p%40ss%3Aword", redacted)
        self.assertNotIn("p@ss:word", redacted)

    def test_an_opaque_query_is_withheld_whole(self):
        """No key to judge it by - it may be the secret itself."""
        redacted = redact_url("postgresql+psycopg://u:p@h/db?%s" % QUERY_SECRET)
        self.assertNotIn(QUERY_SECRET, redacted)

    def test_one_opaque_segment_withholds_the_whole_query(self):
        redacted = redact_url(
            "postgresql+psycopg://u:p@h/db?a=1&%s&b=2" % QUERY_SECRET)
        self.assertNotIn(QUERY_SECRET, redacted)

    def test_the_fragment_is_dropped(self):
        redacted = redact_url(
            "postgresql+psycopg://u:p@h/db#token=%s" % FRAGMENT_SECRET)
        self.assertNotIn(FRAGMENT_SECRET, redacted)
        self.assertNotIn("#", redacted)

    def test_host_port_and_database_still_survive(self):
        redacted = redact_url(
            "postgresql+psycopg://u:%s@localhost:55432/pgx_test?password=%s"
            % (PASSWORD, QUERY_SECRET))
        self.assertIn("localhost", redacted)
        self.assertIn("55432", redacted)
        self.assertIn("pgx_test", redacted)


class TestDsnCredentialsAreMasked(unittest.TestCase):
    """libpq errors are not URLs, and were previously passed through whole."""

    def test_bare_key_value(self):
        message = sanitize_message(
            "connection failed: password=%s host=localhost dbname=pgx_test"
            % DSN_SECRET)
        self.assertNotIn(DSN_SECRET, message)

    def test_spaces_around_the_equals_sign(self):
        self.assertNotIn(DSN_SECRET, sanitize_message(
            "DSN: password = %s host=localhost" % DSN_SECRET))

    def test_single_quoted_value(self):
        self.assertNotIn(DSN_SECRET, sanitize_message(
            "DSN: password='%s' host=localhost" % DSN_SECRET))

    def test_double_quoted_value(self):
        self.assertNotIn(DSN_SECRET, sanitize_message(
            'DSN: password="%s" host=localhost' % DSN_SECRET))

    def test_sslpassword_key(self):
        self.assertNotIn(DSN_SECRET, sanitize_message(
            "libpq: sslpassword=%s sslmode=require" % DSN_SECRET))

    def test_sslpassword_is_not_matched_as_password_leaving_a_prefix(self):
        message = sanitize_message("sslpassword=%s" % DSN_SECRET)
        self.assertNotIn(DSN_SECRET, message)
        self.assertNotIn("ssl***", message)

    def test_key_matching_is_case_insensitive(self):
        for key in ("PASSWORD", "PassWord", "SSLPASSWORD"):
            with self.subTest(key=key):
                self.assertNotIn(DSN_SECRET, sanitize_message(
                    "%s=%s" % (key, DSN_SECRET)))

    def test_neighbouring_fields_survive(self):
        message = sanitize_message(
            "password=%s host=localhost dbname=pgx_test" % DSN_SECRET)
        self.assertIn("host=localhost", message)
        self.assertIn("dbname=pgx_test", message)

    def test_several_dsn_secrets_are_all_masked(self):
        message = sanitize_message(
            "a password=%s and b sslpassword=%s" % (DSN_SECRET, QUERY_SECRET))
        self.assertNotIn(DSN_SECRET, message)
        self.assertNotIn(QUERY_SECRET, message)

    def test_a_url_and_a_dsn_in_one_message_are_both_masked(self):
        message = sanitize_message(
            "%s failed; password=%s" % (PSYCOPG, DSN_SECRET))
        self.assertNotIn(PASSWORD, message)
        self.assertNotIn(DSN_SECRET, message)

    def test_two_urls_in_one_message_are_both_masked(self):
        message = sanitize_message(
            "postgresql://a:%s@h/db and postgresql://b:%s@h/db"
            % (PASSWORD, DSN_SECRET))
        self.assertNotIn(PASSWORD, message)
        self.assertNotIn(DSN_SECRET, message)

    def test_a_url_ending_a_sentence_is_still_recognised(self):
        message = sanitize_message(
            "could not reach postgresql://u:%s@h/db." % PASSWORD)
        self.assertNotIn(PASSWORD, message)
        self.assertTrue(message.endswith("."))


class TestTheSanitizerIsFailSafe(unittest.TestCase):
    """It must never raise, and never fail open."""

    def test_malformed_urls_do_not_raise(self):
        for candidate in ("://", "not a url", "postgresql://h:notaport/db",
                          "postgresql://", "%", "postgresql://[::1/db"):
            with self.subTest(url=candidate):
                self.assertIsInstance(redact_url(candidate), str)

    def test_an_invalid_port_does_not_leak_the_password(self):
        redacted = redact_url("postgresql://u:%s@h:notaport/db" % PASSWORD)
        self.assertNotIn(PASSWORD, redacted)

    def test_an_ipv6_host_survives(self):
        self.assertIn("[::1]", redact_url("postgresql://u:p@[::1]:5432/db"))

    def test_non_string_input_is_coerced(self):
        self.assertEqual(sanitize_message(17), "17")
        self.assertEqual(redact_url(None), "<invalid-url>")

    def test_an_innocent_message_is_left_alone(self):
        for text in ('relation "genes" does not exist',
                     "could not translate host name",
                     "FATAL: database \"pgx_test\" does not exist"):
            with self.subTest(text=text):
                self.assertEqual(sanitize_message(text), text)


class TestNoCodePathPrintsARawCredential(unittest.TestCase):
    """Adversarial sweep over every representation the CLIs can emit."""

    URL = ("postgresql+psycopg://pgx_dev:%s@localhost:5432/pgx_dev"
           "?sslpassword=%s#token=%s" % (PASSWORD, QUERY_SECRET, FRAGMENT_SECRET))
    SECRETS = (PASSWORD, QUERY_SECRET, FRAGMENT_SECRET)

    def setUp(self):
        self.config = load_database_config({APPLICATION_DATABASE_URL_ENV: self.URL})

    def _assert_clean(self, label, text):
        for secret in self.SECRETS:
            self.assertNotIn(secret, text, "%s leaked a credential" % label)

    def test_safe_url_is_clean(self):
        self._assert_clean("safe_url", self.config.safe_url)

    def test_repr_is_clean(self):
        self._assert_clean("repr", repr(self.config))

    def test_str_is_clean(self):
        self._assert_clean("str", str(self.config))

    def test_format_is_clean(self):
        self._assert_clean("format", "{}".format(self.config))

    def test_an_f_string_is_clean(self):
        self._assert_clean("f-string", f"{self.config}")

    def test_a_list_repr_is_clean(self):
        self._assert_clean("container repr", repr([self.config]))

    def test_a_driver_error_quoting_the_url_is_clean(self):
        self._assert_clean("driver error", sanitize_message(
            'connection to "%s" failed: timeout' % self.URL))

    def test_a_configuration_error_is_clean(self):
        with self.assertRaises(DatabaseConfigurationError) as caught:
            load_database_config({
                APPLICATION_DATABASE_URL_ENV:
                    "postgresql+asyncpg://u:%s@h:5432/d" % PASSWORD})
        self._assert_clean("configuration error", str(caught.exception))

    def test_the_real_url_is_still_intact_for_connecting(self):
        self.assertIn(PASSWORD, self.config.url)


class TestSeedAndCheckCliSanitize(unittest.TestCase):
    """The CLIs must route failure text through the sanitizer."""

    MODULES = ("pgx/infrastructure/db/cli_seed.py",
               "pgx/infrastructure/db/cli_check.py")

    def test_each_cli_imports_the_sanitizer(self):
        for relative in self.MODULES:
            with self.subTest(module=relative):
                self.assertIn("sanitize_message", _read(relative))

    def test_no_cli_prints_a_raw_config_url(self):
        for relative in self.MODULES:
            with self.subTest(module=relative):
                self.assertNotIn(
                    "config.url", _read(relative),
                    "use config.safe_url in user-facing output")



class TestCliFailurePathsDoNotLeak(unittest.TestCase):
    """End-to-end: drive both CLIs into failure and read their stderr.

    A driver exception quotes the connection string back. These tests replace
    the worker with one that raises exactly such an exception, then assert the
    process output is clean - the sanitizer is only worth anything if it is on
    the path the user actually sees.
    """

    URL = ("postgresql+psycopg://pgx_dev:%s@localhost:5432/pgx_dev"
           "?sslpassword=%s" % (PASSWORD, QUERY_SECRET))

    def _run(self, module, attribute):
        import contextlib

        stderr = io.StringIO()
        stdout = io.StringIO()
        original = getattr(module, attribute)

        def _explode(*args, **kwargs):
            raise RuntimeError(
                'connection to "%s" failed; password=%s'
                % (self.URL, DSN_SECRET))

        setattr(module, attribute, _explode)
        try:
            with contextlib.redirect_stderr(stderr), \
                    contextlib.redirect_stdout(stdout):
                exit_code = module.main([])
        finally:
            setattr(module, attribute, original)
        return exit_code, stdout.getvalue() + stderr.getvalue()

    def test_the_seed_cli_output_is_clean(self):
        from pgx.infrastructure.db import cli_seed

        exit_code, output = self._run(cli_seed, "run_seed")
        self.assertNotEqual(exit_code, 0)
        self.assertIn("SEED_FAILURE", output)
        for secret in (PASSWORD, QUERY_SECRET, DSN_SECRET):
            self.assertNotIn(secret, output)

    def test_the_check_cli_output_is_clean(self):
        from pgx.infrastructure.db import cli_check

        exit_code, output = self._run(cli_check, "run_check")
        self.assertNotEqual(exit_code, 0)
        self.assertIn("DB_CHECK_FAILURE", output)
        for secret in (PASSWORD, QUERY_SECRET, DSN_SECRET):
            self.assertNotIn(secret, output)

    def test_both_clis_still_name_the_failure_type(self):
        from pgx.infrastructure.db import cli_check, cli_seed

        for module, attribute in ((cli_seed, "run_seed"),
                                  (cli_check, "run_check")):
            with self.subTest(module=module.__name__):
                _, output = self._run(module, attribute)
                self.assertIn("RuntimeError", output)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
