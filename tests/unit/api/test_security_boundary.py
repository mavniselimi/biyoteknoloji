# -*- coding: utf-8 -*-
"""G. The authentication stub boundary and the role matrix.

WP-23 owns authentication. What is asserted here is that WP-16 did not build
any of it, that the default refuses, and that a client cannot supply an actor
or a role by any route.
"""

from __future__ import annotations

import ast
import os
import unittest

from apps.api.config import ApiSettings, Environment, load_settings, \
    ApiConfigurationError
from apps.api.contracts.spec import PROHIBITED_REQUEST_FIELDS
from apps.api.errors import ApiError, status_for_code
from apps.api.routes import ROUTES, ROUTES_BY_OPERATION, STUB_OPERATIONS
from apps.api.security import (PUBLIC, AccessPolicy, AuthMode, Principal,
                               PrincipalResolver, Role,
                               StaticTokenAuthentication,
                               UnconfiguredAuthentication, authorize, roles)
from pgx.application.execution_context import GOVERNED_ACTOR_ROLES
from tests.fixtures.wp16.synthetic import (ADMIN_PRINCIPAL, DEMO_PRINCIPAL,
                                           REVIEWER_PRINCIPAL,
                                           TEST_DEMO_TOKEN, TEST_PRINCIPALS,
                                           TEST_REVIEWER_TOKEN)
from tests.unit.api._support import (API_DIR, api_modules,
                                     identifiers_of, source, tree)


class TestTheGovernedRoles(unittest.TestCase):

    def test_there_are_exactly_three(self):
        self.assertEqual({role.value for role in Role},
                         {"DEMO_USER", "EXPERT_REVIEWER", "ADMIN"})

    def test_the_transport_and_the_application_agree(self):
        """Two vocabularies that must never drift: the API establishes a role
        and the application records it in an audit row."""
        self.assertEqual({role.value for role in Role},
                         set(GOVERNED_ACTOR_ROLES))

    def test_there_is_no_implicit_hierarchy(self):
        reviewer_only = roles(Role.EXPERT_REVIEWER)
        for principal in (DEMO_PRINCIPAL, ADMIN_PRINCIPAL):
            with self.subTest(role=principal.role.value):
                with self.assertRaises(ApiError) as caught:
                    authorize(reviewer_only, principal, operation_id="x")
                self.assertEqual(caught.exception.code, "FORBIDDEN_ROLE")


class TestThePrincipalContract(unittest.TestCase):

    def test_a_principal_records_only_what_an_audit_row_needs(self):
        """Still a closed set; WP-23 added ``assurance`` to it.

        The point of the assertion was never the exact three names - it was
        that a principal carries no display name, no email address and no
        group membership, because none is needed to authorise a route and
        each would be personal data travelling through a layer with no reason
        to hold it. ``assurance`` is a governed enum value, not personal data,
        and without it an audit row cannot tell a person from a fixture.
        """
        self.assertEqual(sorted(DEMO_PRINCIPAL.audit_fields()),
                         ["actor", "assurance", "authenticated_by", "role"])
        for forbidden in ("email", "name", "display_name", "groups",
                          "phone", "given_name"):
            with self.subTest(field=forbidden):
                self.assertNotIn(forbidden, DEMO_PRINCIPAL.audit_fields())

    def test_a_static_token_principal_never_claims_session_assurance(self):
        """A fixture proves a test ran, not that a person acted."""
        self.assertNotEqual(DEMO_PRINCIPAL.assurance, "SESSION")
        self.assertFalse(DEMO_PRINCIPAL.is_session_authenticated)

    def test_session_assurance_requires_a_named_session(self):
        with self.assertRaises(ValueError):
            Principal(actor="TEST-actor", role=Role.ADMIN,
                      authenticated_by="session/1", assurance="SESSION")

    def test_an_unsafe_actor_is_refused(self):
        for actor in ("has space", "a\x07b", "", "x" * 200, "-leading"):
            with self.subTest(actor=repr(actor)):
                with self.assertRaises(ValueError):
                    Principal(actor=actor, role=Role.ADMIN,
                              authenticated_by="static-token/1")

    def test_a_principal_is_immutable(self):
        with self.assertRaises(Exception):
            DEMO_PRINCIPAL.actor = "someone-else"  # type: ignore[misc]


class TestTheDefaultFailsClosed(unittest.TestCase):

    def test_the_unconfigured_resolver_never_returns_a_principal(self):
        resolver = UnconfiguredAuthentication()
        for credential in (None, "", "anything", "Bearer x"):
            with self.subTest(credential=repr(credential)):
                with self.assertRaises(ApiError) as caught:
                    resolver.resolve(credential)
                self.assertEqual(caught.exception.code,
                                 "AUTHENTICATION_NOT_CONFIGURED")

    def test_an_unconfigured_provider_reports_unavailability_not_bad_input(self):
        with self.assertRaises(ApiError) as caught:
            UnconfiguredAuthentication().resolve("x")
        self.assertEqual(status_for_code(caught.exception.code), 503)

    def test_the_default_settings_configure_no_authentication(self):
        settings = load_settings({})
        self.assertEqual(settings.environment, Environment.PRODUCTION)
        self.assertEqual(settings.auth_mode, AuthMode.UNCONFIGURED)
        self.assertFalse(settings.authentication_configured)

    def test_development_tokens_are_refused_in_production(self):
        with self.assertRaises(ApiConfigurationError):
            load_settings({"PGX_API_AUTH_MODE": "STATIC_TOKEN"})
        with self.assertRaises(ApiConfigurationError):
            ApiSettings(environment=Environment.PRODUCTION,
                        auth_mode=AuthMode.STATIC_TOKEN)


class TestTheDevelopmentResolver(unittest.TestCase):

    def test_a_known_token_resolves_to_its_principal(self):
        resolver = StaticTokenAuthentication(TEST_PRINCIPALS)
        self.assertEqual(resolver.resolve(TEST_DEMO_TOKEN), DEMO_PRINCIPAL)
        self.assertEqual(resolver.resolve(TEST_REVIEWER_TOKEN),
                         REVIEWER_PRINCIPAL)

    def test_an_unknown_or_missing_token_is_unauthenticated(self):
        resolver = StaticTokenAuthentication(TEST_PRINCIPALS)
        for credential in (None, "", "TEST-TOKEN-not-issued-0001"):
            with self.subTest(credential=repr(credential)):
                with self.assertRaises(ApiError) as caught:
                    resolver.resolve(credential)
                self.assertEqual(caught.exception.code, "UNAUTHENTICATED")

    def test_it_refuses_to_exist_without_tokens(self):
        with self.assertRaises(ValueError):
            StaticTokenAuthentication({})


class TestTheRoleMatrix(unittest.TestCase):
    """Every route's access policy, asserted against §13."""

    EXPECTED = {
        "createAssessment": ("ADMIN", "DEMO_USER", "EXPERT_REVIEWER"),
        "getAssessment": ("ADMIN", "DEMO_USER", "EXPERT_REVIEWER"),
        "listDrugs": ("ADMIN", "DEMO_USER", "EXPERT_REVIEWER"),
        "listGenes": ("ADMIN", "DEMO_USER", "EXPERT_REVIEWER"),
        "getEvidenceRecord": ("ADMIN", "DEMO_USER", "EXPERT_REVIEWER"),
        # Every expert-review operation, including the three WP-22 added.
        # Exactly EXPERT_REVIEWER on all six: ADMIN reaching one would make an
        # administrator's action indistinguishable from an expert's opinion.
        "listExpertReviewAssignments": ("EXPERT_REVIEWER",),
        "getExpertReviewState": ("EXPERT_REVIEWER",),
        "submitExpertReviewExpected": ("EXPERT_REVIEWER",),
        "revealExpertReviewResult": ("EXPERT_REVIEWER",),
        "completeExpertReview": ("EXPERT_REVIEWER",),
        "appendExpertReviewCorrection": ("EXPERT_REVIEWER",),
    }
    PUBLIC_OPERATIONS = ("getLiveness", "getReadiness", "getSystemVersion")

    def test_every_route_declares_a_policy(self):
        # Eleven at WP-16; fourteen after WP-22 replaced three expert-review
        # stubs with six real operations. Pinned so a route cannot appear
        # without a test noticing.
        self.assertEqual(len(ROUTES), 14)
        for route in ROUTES:
            with self.subTest(operation=route.operation_id):
                self.assertIsInstance(route.access, AccessPolicy)

    def test_the_matrix_is_exactly_as_declared(self):
        for operation_id, expected in self.EXPECTED.items():
            with self.subTest(operation=operation_id):
                route = ROUTES_BY_OPERATION[operation_id]
                self.assertFalse(route.access.public)
                self.assertEqual(route.access.role_names, expected)

    def test_only_the_declared_operations_are_public(self):
        public = tuple(route.operation_id for route in ROUTES
                       if route.access.public)
        self.assertEqual(sorted(public), sorted(self.PUBLIC_OPERATIONS))

    def test_no_public_route_reveals_a_case_or_an_assessment(self):
        for operation_id in self.PUBLIC_OPERATIONS:
            route = ROUTES_BY_OPERATION[operation_id]
            with self.subTest(operation=operation_id):
                self.assertNotIn("assessment", route.path)
                self.assertNotIn("expert-review", route.path)
                self.assertNotIn("evidence", route.path)


class TestTheExpertReviewRoutes(unittest.TestCase):
    """WP-22 made these service-backed. The boundary they guarded is unchanged.

    Until WP-22 this class asserted that the three routes were 501 stubs
    consulting nothing. They now execute the blind protocol, so the
    assertions move to their successors - what the stubs achieved by doing
    nothing, the implementation must achieve by doing the right thing.
    Deleting the class when the stubs went would have retired the boundary at
    the moment it started to matter.
    """

    _OPERATIONS = ("listExpertReviewAssignments", "getExpertReviewState",
                   "submitExpertReviewExpected", "revealExpertReviewResult",
                   "completeExpertReview", "appendExpertReviewCorrection")

    def test_no_route_is_a_stub_any_more(self):
        self.assertEqual(dict(STUB_OPERATIONS), {})
        for operation_id in self._OPERATIONS:
            with self.subTest(operation=operation_id):
                route = ROUTES_BY_OPERATION[operation_id]
                self.assertTrue(route.implemented)
                self.assertNotEqual(route.success_status, 501)

    def test_each_requires_exactly_the_reviewer_role(self):
        """ADMIN does not imply it. An administrator's action must remain
        distinguishable from an independent expert's."""
        for operation_id in self._OPERATIONS:
            route = ROUTES_BY_OPERATION[operation_id]
            with self.subTest(operation=operation_id):
                self.assertFalse(route.access.public)
                self.assertEqual(route.access.role_names,
                                 ("EXPERT_REVIEWER",))

    def test_the_router_reaches_a_store_only_through_the_provider(self):
        """The successor to "consults no store".

        The router may now consult one - that is the point of the work
        package - but only through the injected provider, and never by
        constructing a session, committing, or touching persistence itself.
        """
        path = os.path.join(API_DIR, "routers", "expert_review.py")
        names = identifiers_of(path)
        for forbidden in ("session", "commit", "Session", "engine",
                          "execute", "SqlAlchemyExpertReviewRepository"):
            with self.subTest(name=forbidden):
                self.assertNotIn(forbidden, names)
        self.assertIn("get_provider", names)

    def test_the_router_fails_closed_without_a_service(self):
        """No service configured - this repository's state - refuses before
        anything is consulted, so the 503 cannot vary by case."""
        import inspect
        from apps.api.routers import expert_review
        source = inspect.getsource(expert_review._service)
        self.assertIn("EXPERT_REVIEW_NOT_AVAILABLE", source)
        for handler in ("get_state", "submit_expected", "reveal_result",
                        "complete_review", "append_correction",
                        "list_assignments"):
            body = inspect.getsource(getattr(expert_review, handler))
            with self.subTest(handler=handler):
                # _service(provider) is the first statement after the
                # signature in every handler.
                self.assertIn("_service(provider)", body)

    def test_the_pre_reveal_response_model_has_no_result_field(self):
        """A hidden value is still disclosure, so the shape has nowhere to
        put one - rather than having one that is filtered."""
        from apps.api.contracts.spec import MODELS
        state = MODELS["ExpertReviewStateResponse"]
        names = {field.name for field in state.fields}
        for forbidden in ("result", "attention_level", "coverage_status",
                          "firing_rule_id", "output_hash", "decision"):
            with self.subTest(field=forbidden):
                self.assertNotIn(forbidden, names)

    def test_the_reveal_response_is_the_only_one_carrying_a_result(self):
        from apps.api.contracts.spec import MODELS
        carrying = sorted(
            name for name, model in MODELS.items()
            if model.direction == "response" and name.startswith("ExpertReview")
            and "result" in {field.name for field in model.fields})
        self.assertEqual(carrying, ["ExpertReviewRevealResponse"])

    def test_a_missing_assignment_and_an_unknown_case_share_one_code(self):
        """Three distinguishable refusals would be an enumeration tool for
        the holdout set."""
        from pgx.expert_review.errors import NotAssignedError
        self.assertEqual(NotAssignedError().code,
                         "EXPERT_REVIEW_NOT_ASSIGNED")
        self.assertEqual(NotAssignedError().details, {})


class TestAClientCannotForgeAnActorOrRole(unittest.TestCase):

    def test_actor_role_and_principal_are_prohibited_request_fields(self):
        for name in ("actor", "role", "principal"):
            with self.subTest(field=name):
                self.assertIn(name, PROHIBITED_REQUEST_FIELDS)

    def test_no_request_model_declares_an_actor_or_a_role(self):
        from apps.api.contracts.spec import MODELS
        for name, model in MODELS.items():
            if model.direction != "request":
                continue
            with self.subTest(model=name):
                self.assertEqual(
                    {field.name for field in model.fields}
                    & {"actor", "role", "principal"}, set())

    def test_the_execution_context_is_built_only_from_a_principal(self):
        """The mechanical guarantee, read as identifiers rather than as text.

        The function that builds the audit context takes a principal and a
        request, reads the actor and the role off the principal, and names no
        request-payload accessor at all. Checked by walking the syntax tree:
        a text search would match this docstring, which is the failure mode
        every boundary test in this repository is written to avoid.
        """
        path = os.path.join(API_DIR, "dependencies.py")
        found = [node for node in ast.walk(tree(path))
                 if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and node.name == "get_execution_context"]
        self.assertEqual(len(found), 1)
        function = found[0]
        arguments = {argument.arg for argument in function.args.args}
        self.assertEqual(arguments, {"request", "principal"})

        attributes = {node.attr for node in ast.walk(function)
                      if isinstance(node, ast.Attribute)}
        called = {node.func.attr for node in ast.walk(function)
                  if isinstance(node, ast.Call)
                  and isinstance(node.func, ast.Attribute)}
        self.assertIn("actor", attributes)
        self.assertIn("role", attributes)
        for forbidden in ("body", "json", "form", "query_params",
                          "path_params"):
            with self.subTest(accessor=forbidden):
                self.assertNotIn(forbidden, attributes)
                self.assertNotIn(forbidden, called)

    def test_no_module_reads_an_actor_or_role_header(self):
        """No string constant anywhere names such a header.

        A string check rather than an identifier check, because a header name
        *is* a string literal - so this walks string constants specifically
        and never sees a docstring, which ``ast.get_docstring`` removes from
        the node it would otherwise be a constant of.
        """
        for path in api_modules():
            literals = set()
            module = tree(path)
            for node in ast.walk(module):
                if isinstance(node, ast.Constant) and isinstance(node.value,
                                                                 str):
                    literals.add(node.value.lower())
            docstrings = {ast.get_docstring(node) or ""
                          for node in ast.walk(module)
                          if isinstance(node, (ast.Module, ast.ClassDef,
                                               ast.FunctionDef,
                                               ast.AsyncFunctionDef))}
            literals -= {text.lower() for text in docstrings}
            with self.subTest(module=os.path.basename(path)):
                for header in ("x-actor", "x-role", "x-user"):
                    self.assertFalse(
                        any(header in value for value in literals),
                        "%s names a %s header" % (path, header))


class TestNoAuthenticationWasImplemented(unittest.TestCase):
    """WP-23's surface must be absent, not half-present."""

    FORBIDDEN_IDENTIFIERS = frozenset({
        "argon2", "bcrypt", "scrypt", "pbkdf2", "hashpw", "checkpw",
        "jwt", "encode_jwt", "decode_jwt", "set_cookie", "SessionMiddleware",
        "csrf", "CSRFProtect", "login", "logout", "signup", "register_user",
        "password", "verify_password", "hash_password"})

    def test_no_api_module_implements_authentication(self):
        for path in api_modules():
            with self.subTest(module=os.path.basename(path)):
                self.assertEqual(
                    identifiers_of(path) & self.FORBIDDEN_IDENTIFIERS, set())

    def test_no_route_issues_or_accepts_a_credential(self):
        for route in ROUTES:
            with self.subTest(operation=route.operation_id):
                self.assertNotIn("login", route.path)
                self.assertNotIn("token", route.path)
                self.assertNotIn("session", route.path)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
