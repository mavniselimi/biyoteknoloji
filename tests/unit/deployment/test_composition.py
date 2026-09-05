# -*- coding: utf-8 -*-
"""The runtime composition (WP-24).

The tests that matter here are about *transaction shape*, not about final
state. "The change and the audit record are both in the database" is
satisfied by two separate commits, and two separate commits is exactly the
bug: the second can fail after the first succeeded, leaving a governed change
nobody can account for.

So these assert the ordering of ``flush``, ``commit``, ``rollback`` and
``close`` on a recording session, and they assert that two request scopes get
two sessions. Neither is observable from a query.
"""

from __future__ import annotations

import unittest

from pgx.deployment.composition import (CompositionResult,
                                        DeploymentComposition, RequestScope,
                                        compose_from_environment,
                                        current_scope)
from pgx.deployment.errors import DeploymentBlocked
from tests.fixtures.wp24.doubles import (CountingSessionFactory,
                                         FakeRateLimitStore)


def _composition(*, fail_on_flush: bool = False):
    from pgx.security.csrf import SessionBoundCsrf
    from pgx.security.rate_limit import RateLimiter
    from pgx.security.sessions import SessionPolicy

    factory = CountingSessionFactory(fail_on_flush=fail_on_flush)
    store = FakeRateLimitStore()
    composition = DeploymentComposition(
        engine=object(), session_factory=factory, hasher=object(),
        csrf=SessionBoundCsrf(), policy=SessionPolicy(),
        limiter_factory=lambda: RateLimiter(store=store))
    return composition, factory, store


class TestOneSessionPerRequest(unittest.TestCase):
    """A session belongs to one request and is closed when it ends."""

    def test_two_scopes_never_share_a_session(self):
        """The classic web bug, asserted rather than assumed.

        An application-scoped session is shared by every concurrent request
        in the worker, and one caller's commit publishes another's
        half-finished work. Two scopes must produce two sessions.
        """
        composition, factory, _ = _composition()
        with composition.request_scope() as first:
            first.session
        with composition.request_scope() as second:
            second.session
        self.assertEqual(len(factory.sessions), 2)
        self.assertIsNot(factory.sessions[0], factory.sessions[1])

    def test_the_session_is_closed_when_the_scope_ends(self):
        composition, factory, _ = _composition()
        with composition.request_scope() as scope:
            scope.session
        self.assertTrue(factory.sessions[0].closed)
        self.assertIn("close", factory.sessions[0].calls)

    def test_the_session_is_closed_even_when_the_request_raises(self):
        """A leaked session holds a connection until the pool is exhausted,
        which presents as a deployment that works and then stops."""
        composition, factory, _ = _composition()
        with self.assertRaises(ValueError):
            with composition.request_scope() as scope:
                scope.session
                raise ValueError("the handler failed")
        self.assertTrue(factory.sessions[0].closed)

    def test_closing_rolls_back_first(self):
        """A session returned to the pool with an open transaction holds
        locks the next borrower waits on."""
        composition, factory, _ = _composition()
        with composition.request_scope() as scope:
            scope.session
        calls = factory.sessions[0].calls
        self.assertLess(calls.index("rollback"), calls.index("close"))

    def test_a_scope_that_touches_nothing_opens_no_session(self):
        """A health check must not take a connection from the pool."""
        composition, factory, _ = _composition()
        with composition.request_scope() as scope:
            self.assertFalse(scope.session_opened)
        self.assertEqual(factory.sessions, [])

    def test_a_capability_outside_a_request_raises_rather_than_leaking(self):
        """Raising is the correct failure. An implicit scope here would leak
        one connection per call, silently."""
        with self.assertRaises(DeploymentBlocked) as caught:
            current_scope()
        self.assertEqual(caught.exception.code,
                         "DEPLOY_COMPOSITION_INCOMPLETE")

    def test_a_closed_scope_refuses_to_hand_out_its_session(self):
        composition, _, _ = _composition()
        scope = composition.new_scope()
        scope.close()
        with self.assertRaises(RuntimeError):
            scope.session


class TestTheGovernedTransaction(unittest.TestCase):
    """A governed change and its audit record are one transaction."""

    def test_the_body_commits_once(self):
        composition, factory, _ = _composition()
        with composition.request_scope() as scope:
            with scope.governed_transaction() as session:
                session.add(object())
        calls = factory.sessions[0].calls
        self.assertEqual(calls.count("commit"), 1)

    def test_an_audit_failure_rolls_the_change_back(self):
        """The whole point. A system that could make a change it did not
        record - or record one it did not make - has an audit trail that
        answers no question."""
        composition, factory, _ = _composition()
        with self.assertRaises(RuntimeError):
            with composition.request_scope() as scope:
                with scope.governed_transaction() as session:
                    session.add(object())
                    raise RuntimeError("the audit sink is unavailable")
        calls = factory.sessions[0].calls
        self.assertNotIn("commit", calls)
        self.assertIn("rollback", calls)

    def test_the_change_and_the_record_share_one_session(self):
        """Not "both were written". Share one.

        The authentication service and the audit sink a single request uses
        must be backed by the same session, or their writes are two
        transactions that happened to both succeed.
        """
        composition, factory, _ = _composition()
        with composition.request_scope() as scope:
            store_a = scope.user_store()
            store_b = scope.audit_store()
            self.assertIs(store_a._session, store_b._session)
        self.assertEqual(len(factory.sessions), 1)

    def test_services_are_memoised_within_one_scope(self):
        composition, _, _ = _composition()
        with composition.request_scope() as scope:
            self.assertIs(scope.audit_service(), scope.audit_service())
            self.assertIs(scope.user_store(), scope.user_store())


class TestTheRateLimiterKeepsItsOwnTransaction(unittest.TestCase):
    """A refused login must still be counted after its rollback."""

    def test_the_limiter_is_not_backed_by_the_request_session(self):
        """If it were, the rollback that refuses a login would erase the
        evidence that it was attempted - turning the limiter off for exactly
        the caller it is watching."""
        composition, factory, store = _composition()
        with composition.request_scope() as scope:
            limiter = scope.rate_limiter()
            limiter.check("LOGIN_PER_USERNAME", "someone")
        # The hit was counted in the fake store, and the request session was
        # never used for it.
        self.assertEqual(sum(store.counts.values()), 1)
        self.assertEqual(factory.sessions, [])


class TestCompositionIsMeasuredNotDeclared(unittest.TestCase):
    """``composed`` comes from objects that were built."""

    def test_an_empty_environment_composes_nothing_and_says_why(self):
        result = compose_from_environment({})
        self.assertFalse(result.composed)
        self.assertIn("DEPLOY_DATABASE_UNAVAILABLE", result.blocker_codes)

    def test_naming_session_mode_does_not_make_a_deployment_configured(self):
        """A variable can name a configuration the host cannot provide.

        This is the substitution the whole ``composed`` field exists to
        prevent: PGX_API_AUTH_MODE=SESSION with no database, no driver and no
        Argon2 is a deployment that cannot authenticate anybody.
        """
        result = compose_from_environment({"PGX_API_AUTH_MODE": "SESSION"})
        self.assertFalse(result.composed)

    def test_every_blocker_names_an_owner(self):
        result = compose_from_environment({})
        for item in result.blockers:
            with self.subTest(code=item.code):
                self.assertTrue(item.owner.strip())

    def test_both_a_secret_and_its_file_is_refused_not_resolved(self):
        """A precedence rule would let a rotated file be ignored in favour of
        a stale variable, and nothing anywhere would say so."""
        result = compose_from_environment({
            "DATABASE_URL": "postgresql://x/y",
            "DATABASE_URL_FILE": "/run/secrets/database_url"})
        self.assertFalse(result.composed)
        self.assertIn("DEPLOY_DATABASE_UNAVAILABLE", result.blocker_codes)

    def test_the_result_document_explains_what_composed_means(self):
        document = compose_from_environment({}).to_json()
        self.assertFalse(document["composed"])
        self.assertIn("environment variable", str(document["note"]))


class TestArgon2IsNeverSubstituted(unittest.TestCase):
    """The failure is the signal."""

    def test_a_missing_argon2_blocks_composition_rather_than_downgrading(self):
        from pgx.security.passwords import argon2_available

        result = compose_from_environment({})
        if argon2_available():
            self.skipTest("argon2-cffi is installed in this environment, so "
                          "the unavailable path cannot be exercised here")
        self.assertIn("DEPLOY_ARGON2_UNAVAILABLE", result.blocker_codes)
        self.assertFalse(result.composed)

    def test_composition_imports_no_alternative_hasher(self):
        """Checked with the AST, docstrings stripped.

        The module prose names PBKDF2 and scrypt while explaining that
        neither exists, and a substring search over the source matches its
        own explanation - a mistake this repository has made often enough to
        have a habit about it.
        """
        import ast

        import pgx.deployment.composition as module
        from tests.fixtures.wp24.doubles import module_source

        tree = ast.parse(module_source(module))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef,
                                 ast.AsyncFunctionDef, ast.ClassDef)):
                body = node.body
                if body and isinstance(body[0], ast.Expr) and \
                        isinstance(body[0].value, ast.Constant) and \
                        isinstance(body[0].value.value, str):
                    node.body = body[1:]
        dumped = ast.dump(tree).lower()
        for banned in ("pbkdf2", "scrypt", "bcrypt", "md5"):
            with self.subTest(algorithm=banned):
                self.assertNotIn(banned, dumped)


class TestNothingIsSeeded(unittest.TestCase):
    """No user, password, release or approval is created by composition."""

    def test_the_composition_module_creates_no_account(self):
        import ast

        import pgx.deployment.composition as module
        from tests.fixtures.wp24.doubles import module_source

        tree = ast.parse(module_source(module))
        called = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                target = node.func
                name = getattr(target, "attr", None) or getattr(
                    target, "id", None)
                if name:
                    called.add(name)
        for forbidden in ("bootstrap_admin", "create_user", "seed",
                          "activate_release", "approve"):
            with self.subTest(call=forbidden):
                self.assertNotIn(forbidden, called)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
