# -*- coding: utf-8 -*-
"""The governed transaction boundary, asserted where HTTP draws it (Wave 4B).

WP-24 built ``RequestScope.governed_transaction`` and nothing under ``apps/``
ever entered it. ``RequestScope.close`` rolls back anything uncommitted, so
every governed mutation served over HTTP was flushed and then discarded.

The symptom was the worst kind. A login wrote its user session row, appended
its audit events, returned ``Set-Cookie`` - and then the scope closed and
rolled all of it back. The browser held a token for a session the store had
never heard of, the next request answered 401, and nothing raised, logged or
recorded a failure anywhere. Every unit test passed the whole time, because
each one drove the service directly and opened its own transaction.

These tests drive the middleware instead, which is the only place the mistake
was visible.
"""

from __future__ import annotations

import asyncio
import unittest

from apps.api.deployment import SAFE_METHODS, RequestScopeMiddleware


class _Session:
    def __init__(self, log):
        self._log = log

    def commit(self):
        self._log.append("commit")

    def rollback(self):
        self._log.append("rollback")


class _Scope:
    def __init__(self, log):
        self._log = log
        self.session = _Session(log)

    def governed_transaction(self):
        log = self._log

        class _Transaction:
            def __enter__(inner):
                log.append("begin")
                return self.session

            def __exit__(inner, exc_type, exc, tb):
                if exc_type is None:
                    self.session.commit()
                else:
                    self.session.rollback()
                return False

        return _Transaction()


class _Composition:
    def __init__(self):
        self.log = []
        self.scope = _Scope(self.log)

    def request_scope(self):
        composition = self

        class _Entered:
            def __enter__(inner):
                composition.log.append("scope")
                return composition.scope

            def __exit__(inner, exc_type, exc, tb):
                composition.log.append("close")
                return False

        return _Entered()


def _run(method, *, raises=False):
    composition = _Composition()

    async def app(scope, receive, send):
        composition.log.append("handler")
        if raises:
            raise RuntimeError("the handler failed")

    middleware = RequestScopeMiddleware(app, composition)
    coroutine = middleware({"type": "http", "method": method}, None, None)
    if raises:
        with unittest.TestCase().assertRaises(RuntimeError):
            asyncio.run(coroutine)
    else:
        asyncio.run(coroutine)
    return composition.log


class TestAMutationCommits(unittest.TestCase):

    def test_a_post_runs_inside_a_governed_transaction(self):
        """The defect, stated as the thing that must be true.

        Without ``begin`` and ``commit`` around the handler, a login writes a
        session row, issues a cookie for it, and rolls it back.
        """
        self.assertEqual(_run("POST"),
                         ["scope", "begin", "handler", "commit", "close"])

    def test_every_unsafe_method_commits(self):
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            with self.subTest(method=method):
                self.assertIn("commit", _run(method))

    def test_a_refusal_response_still_commits_its_audit_row(self):
        """A handler that returns a refusal has not raised.

        A refused login records ``LOGIN_FAILED``. Rolling that back would
        leave the limiter and the audit trail disagreeing about whether the
        attempt happened.
        """
        self.assertEqual(_run("POST").count("rollback"), 0)

    def test_a_raising_handler_rolls_the_change_and_its_audit_back_together(self):
        log = _run("POST", raises=True)
        self.assertEqual(log, ["scope", "begin", "handler", "rollback",
                               "close"])
        self.assertNotIn("commit", log)


class TestAReadCommitsNothing(unittest.TestCase):

    def test_a_get_opens_no_transaction(self):
        """A read path that could commit is a read path that eventually does."""
        self.assertEqual(_run("GET"), ["scope", "handler", "close"])

    def test_every_safe_method_opens_no_transaction(self):
        for method in sorted(SAFE_METHODS):
            with self.subTest(method=method):
                log = _run(method)
                self.assertNotIn("begin", log)
                self.assertNotIn("commit", log)

    def test_the_safe_set_is_exactly_the_methods_that_change_nothing(self):
        self.assertEqual(SAFE_METHODS,
                         frozenset({"GET", "HEAD", "OPTIONS", "TRACE"}))

    def test_a_lowercase_method_is_still_matched(self):
        """A scope carrying ``post`` must not skip the transaction."""
        self.assertIn("commit", _run("post"))


class TestNonHttpTrafficIsUntouched(unittest.TestCase):

    def test_a_websocket_scope_opens_no_request_scope(self):
        composition = _Composition()

        async def app(scope, receive, send):
            composition.log.append("handler")

        asyncio.run(RequestScopeMiddleware(app, composition)(
            {"type": "websocket"}, None, None))
        self.assertEqual(composition.log, ["handler"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class TestATypedRefusalIsNotAServerError(unittest.TestCase):
    """A401 is an answer; a bug is a bug. The log must tell them apart.

    An anonymous request for a page that needs a session printed a full ASGI
    exception group ending in ``UnauthenticatedError: UNAUTHENTICATED`` -
    because the only registered handler was for ``Exception``, and Starlette
    routes that one through ``ServerErrorMiddleware``, which logs the
    traceback before delegating. A log full of ordinary refusals is a log
    nobody reads when something real breaks.
    """

    def _app(self):
        import os

        from apps.api.config import load_settings
        from apps.api.factory import create_app
        from apps.api.provider import ServiceProvider

        settings = load_settings({"PGX_API_ENV": "DEVELOPMENT"})
        return create_app(settings, ServiceProvider(settings=settings))

    def _get(self, app, path):
        import asyncio

        import httpx

        async def run():
            transport = httpx.ASGITransport(app=app,
                                            raise_app_exceptions=False)
            async with httpx.AsyncClient(transport=transport,
                                         base_url="https://testserver") as c:
                return await c.get(path)

        return asyncio.run(run())

    def _captured(self, app, path):
        import io as _io
        import logging

        buffer = _io.StringIO()
        handler = logging.StreamHandler(buffer)
        root = logging.getLogger()
        root.addHandler(handler)
        previous = root.level
        root.setLevel(logging.ERROR)
        try:
            response = self._get(app, path)
        finally:
            root.removeHandler(handler)
            root.setLevel(previous)
        return response, buffer.getvalue()

    def test_an_anonymous_request_logs_no_traceback(self):
        """The refusal is typed, and the log stays empty.

        A provider with nothing composed answers 503
        ``AUTHENTICATION_NOT_CONFIGURED``; a composed one answers 401
        ``UNAUTHENTICATED``. Both are ``ApiError`` and both must reach the
        client without a traceback - the point is the handler that catches
        them, not which of the two this fixture produces.
        """
        response, log = self._captured(self._app(),
                                       "/api/v1/assessments/unknown")
        self.assertIn(response.status_code, (401, 503))
        self.assertNotIn("Traceback", log)
        self.assertEqual(log.strip(), "")

    def test_the_refusal_still_carries_the_declared_contract(self):
        response = self._get(self._app(), "/api/v1/assessments/unknown")
        body = response.json()
        self.assertIn(body["error"]["code"],
                      ("UNAUTHENTICATED", "AUTHENTICATION_NOT_CONFIGURED"))
        self.assertIn("request_id", body["error"])
        self.assertNotIn("Traceback", response.text)

    def test_an_unexpected_failure_is_not_quietly_turned_into_a_refusal(self):
        """The compensating half. Silencing refusals must not silence bugs.

        Asserted on what reaches the caller and what reaches the ASGI layer,
        rather than on a log record: the logger a server installs is the
        server's choice, and a test that pins it would break when a
        deployment configures logging differently.
        """
        import asyncio

        import httpx
        from fastapi import APIRouter

        app = self._app()
        router = APIRouter()

        @router.get("/_boom")
        async def boom():  # pragma: no cover - raised, never returned
            raise RuntimeError("a defect nobody planned for")

        app.include_router(router)

        # Through the handled path: a 500 with the catalogue's fixed message
        # and nothing of the exception's own text.
        response = self._get(app, "/_boom")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["error"]["code"], "INTERNAL_ERROR")
        self.assertNotIn("a defect nobody planned for", response.text)

        # And it is still a real exception underneath: the ASGI layer sees it
        # rather than a refusal the application decided to swallow.
        async def strict():
            transport = httpx.ASGITransport(app=app, raise_app_exceptions=True)
            async with httpx.AsyncClient(transport=transport,
                                         base_url="https://testserver") as c:
                return await c.get("/_boom")

        with self.assertRaises(RuntimeError):
            asyncio.run(strict())
