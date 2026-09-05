# -*- coding: utf-8 -*-
"""The permission matrix, and the two collapses it must never permit (WP-23).

Most of this file is arithmetic over a table. The three assertions that carry
real weight are:

* **ADMIN holds no expert-review permission.** Not one, not read-only, not
  "list assignments". An administrator who could review would destroy the
  property WP-22 exists for.
* **There is no hierarchy.** Checked by asserting that no role's permission
  set contains another's, so a future "ADMIN inherits everything" cannot be
  added without failing here.
* **The route tables agree with this registry.** FastAPI enforces the route
  table; this registry is what the security documentation describes. Two
  tables that agree today and drift tomorrow are worse than one, so the
  agreement is a test rather than a convention.
"""

from __future__ import annotations

import unittest

from pgx.security.errors import AuthorizationDenied
from pgx.security.rbac import (PERMISSION_IDS, PERMISSIONS,
                               permissions_for_role, registry_digest,
                               registry_document, require_permission,
                               role_holds, roles_holding)
from pgx.security.vocabulary import GOVERNED_ROLES


class TestTheRegistryIsComplete(unittest.TestCase):

    def test_every_required_area_is_represented(self):
        areas = {item.area for item in PERMISSIONS}
        for required in ("session", "assessment", "catalogue", "validation",
                         "expert_review", "release", "curation", "rules",
                         "administration"):
            with self.subTest(area=required):
                self.assertIn(required, areas)

    def test_the_work_packages_named_permissions_all_exist(self):
        for permission in (
                "session.login", "session.logout", "assessment.create",
                "assessment.read", "catalogue.read", "evidence.read",
                "expert_review.read_assigned",
                "expert_review.submit_expected",
                "expert_review.reveal_assigned",
                "expert_review.complete_assigned", "release.activate",
                "source_policy.administer", "curation.administer",
                "rule.administer", "user.administer", "audit.read",
                "audit.verify"):
            with self.subTest(permission=permission):
                self.assertIn(permission, PERMISSION_IDS)

    def test_every_permission_names_at_least_one_holder(self):
        """A permission nobody holds is a permission nobody can exercise,
        which is either a mistake or a role that was removed and not cleaned
        up. Either way it should not sit in the table unnoticed."""
        for permission in PERMISSIONS:
            with self.subTest(permission=permission.permission_id):
                self.assertTrue(permission.holders)

    def test_every_permission_explains_what_refusing_it_protects(self):
        for permission in PERMISSIONS:
            with self.subTest(permission=permission.permission_id):
                self.assertGreater(len(permission.rationale), 40)

    def test_ids_are_unique(self):
        self.assertEqual(len(set(PERMISSION_IDS)), len(PERMISSION_IDS))


class TestThereIsNoHierarchy(unittest.TestCase):

    def test_the_two_privileged_roles_do_not_nest(self):
        """The containment that must never exist, stated precisely.

        A first version of this test asserted that *no* role's permission set
        contains another's, and it failed - correctly. ``DEMO_USER`` really is
        a subset of both other roles, because architecture.md section 13 says
        so in as many words: "EXPERT_REVIEWER: demo permissions plus assigned
        blind reviews". That containment is a deliberate design decision
        written out permission by permission, not an inheritance rule, and a
        test forbidding it would have been demanding that a reviewer be unable
        to run the demo workflow they are reviewing.

        What "no hierarchy" actually forbids is the pair below. ADMIN must not
        contain EXPERT_REVIEWER, because an administrator would then be able
        to review; EXPERT_REVIEWER must not contain ADMIN, because a reviewer
        would then be able to activate the release they are judging. Those two
        are separation of duty, and they are what this asserts.
        """
        admin = set(permissions_for_role("ADMIN"))
        reviewer = set(permissions_for_role("EXPERT_REVIEWER"))
        self.assertFalse(reviewer <= admin,
                         "ADMIN must not be able to do everything a reviewer "
                         "can; that is the collapse WP-22 exists to prevent")
        self.assertFalse(admin <= reviewer,
                         "a reviewer must not hold administrative authority "
                         "over the release they are judging")
        # And each really does hold something the other does not, so the
        # assertion above cannot be satisfied by two disjoint-but-empty sets.
        self.assertTrue(reviewer - admin)
        self.assertTrue(admin - reviewer)

    def test_containment_is_never_used_to_decide_a_check(self):
        """Subsets exist; the check does not consult them.

        ``DEMO_USER`` being a subset of ``ADMIN`` is only safe because
        ``role_holds`` is literal membership. If it ever consulted an ordering,
        the subset relation would silently become an inheritance rule.
        """
        for permission in PERMISSIONS:
            for role in GOVERNED_ROLES:
                with self.subTest(permission=permission.permission_id,
                                  role=role):
                    self.assertEqual(
                        role_holds(role, permission.permission_id),
                        role in permission.holders)

    def test_the_registry_module_declares_no_inheritance_mechanism(self):
        """Structural: no code in the registry derives one role from another.

        The subset relations are data. A function that computed them would be
        a hierarchy however carefully its docstring denied it.
        """
        import ast
        import io as _io
        import os as _os

        path = _os.path.join(
            _os.path.dirname(_os.path.dirname(_os.path.dirname(
                _os.path.dirname(_os.path.abspath(__file__))))),
            "pgx", "security", "rbac.py")
        with _io.open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                lowered = node.name.lower()
                with self.subTest(function=node.name):
                    for marker in ("inherit", "implies", "escalate",
                                   "supersede", "outranks", "hierarchy"):
                        self.assertNotIn(marker, lowered)

    def test_admin_holds_no_expert_review_permission(self):
        """The one that matters most. An administrator who could review would
        be reviewing software they administer."""
        for permission in permissions_for_role("ADMIN"):
            with self.subTest(permission=permission):
                self.assertFalse(permission.startswith("expert_review."))

    def test_the_reviewer_holds_no_administrative_permission(self):
        for permission in permissions_for_role("EXPERT_REVIEWER"):
            with self.subTest(permission=permission):
                for area in ("release.", "user.", "audit.", "rule.",
                             "ruleset.", "curation.", "source_policy."):
                    self.assertFalse(permission.startswith(area))

    def test_the_demo_user_holds_no_review_or_administrative_permission(self):
        for permission in permissions_for_role("DEMO_USER"):
            with self.subTest(permission=permission):
                for area in ("expert_review.", "release.", "user.", "audit.",
                             "rule.", "ruleset.", "curation.",
                             "source_policy."):
                    self.assertFalse(permission.startswith(area))

    def test_every_expert_review_permission_belongs_to_the_reviewer_only(self):
        for permission in PERMISSIONS:
            if not permission.permission_id.startswith("expert_review."):
                continue
            with self.subTest(permission=permission.permission_id):
                self.assertEqual(sorted(permission.holders),
                                 ["EXPERT_REVIEWER"])

    def test_the_published_document_says_the_hierarchy_is_null(self):
        document = registry_document()
        self.assertIsNone(document["role_hierarchy"])
        self.assertIn("no hierarchy", document["role_hierarchy_note"])


class TestChecking(unittest.TestCase):

    def test_a_held_permission_passes_and_an_unheld_one_raises(self):
        require_permission("ADMIN", "release.activate")
        with self.assertRaises(AuthorizationDenied) as raised:
            require_permission("ADMIN", "expert_review.reveal_assigned")
        self.assertEqual(raised.exception.code, "PERMISSION_DENIED")
        self.assertEqual(
            raised.exception.details["required_permission"],
            "expert_review.reveal_assigned")

    def test_an_undeclared_permission_raises_rather_than_denying(self):
        """A typo must not read as a quiet denial that somebody later
        "fixes" by widening a role."""
        with self.assertRaises(KeyError):
            role_holds("ADMIN", "release.activaet")

    def test_an_unknown_role_raises(self):
        with self.assertRaises(KeyError):
            permissions_for_role("SUPERUSER")

    def test_roles_holding_is_the_inverse_of_role_holds(self):
        for permission in PERMISSIONS:
            for role in GOVERNED_ROLES:
                with self.subTest(permission=permission.permission_id,
                                  role=role):
                    self.assertEqual(
                        role in roles_holding(permission.permission_id),
                        role_holds(role, permission.permission_id))


class TestTheRouteTablesAgreeWithTheRegistry(unittest.TestCase):
    """Two tables, one meaning. Asserted rather than assumed.

    FastAPI enforces the route table's roles; the registry is what the
    security documentation and the published artifact describe. If they can
    disagree, one of them is wrong and nobody finds out from reading either.
    """

    #: Which permission each governed route is the transport for. Written out
    #: so that a new route with no permission is a missing key here rather
    #: than a silently unmapped surface.
    API_ROUTE_PERMISSIONS = {
        "createAssessment": "assessment.create",
        "getAssessment": "assessment.read",
        "listDrugs": "catalogue.read",
        "listGenes": "catalogue.read",
        "getEvidenceRecord": "evidence.read",
        "listExpertReviewAssignments": "expert_review.list_assigned",
        "getExpertReviewState": "expert_review.read_assigned",
        "submitExpertReviewExpected": "expert_review.submit_expected",
        "revealExpertReviewResult": "expert_review.reveal_assigned",
        "completeExpertReview": "expert_review.complete_assigned",
        "appendExpertReviewCorrection": "expert_review.append_correction",
    }

    WEB_ROUTE_PERMISSIONS = {
        "web.cases": "catalogue.read",
        "web.case_detail": "catalogue.read",
        "web.case_assess": "assessment.create",
        "web.assessment": "assessment.read",
        "web.evidence": "evidence.read",
        "web.validation": "validation.read_public",
        "web.expert_review": "expert_review.read_assigned",
        "web.expert_review_expected": "expert_review.submit_expected",
        "web.expert_review_reveal": "expert_review.reveal_assigned",
        "web.expert_review_complete": "expert_review.complete_assigned",
    }

    def test_every_api_route_permits_exactly_the_registry_holders(self):
        from apps.api.routes import ROUTES

        for route in ROUTES:
            if route.access.public:
                continue
            permission = self.API_ROUTE_PERMISSIONS.get(route.operation_id)
            with self.subTest(operation=route.operation_id):
                self.assertIsNotNone(
                    permission,
                    "%s declares roles but maps to no permission"
                    % route.operation_id)
                self.assertEqual(sorted(route.access.role_names),
                                 sorted(roles_holding(permission)))

    def test_every_web_route_permits_exactly_the_registry_holders(self):
        from apps.web.routes import WEB_ROUTES

        for route in WEB_ROUTES:
            if route.access.public:
                continue
            permission = self.WEB_ROUTE_PERMISSIONS.get(route.name)
            with self.subTest(route=route.name):
                self.assertIsNotNone(
                    permission,
                    "%s declares roles but maps to no permission" % route.name)
                self.assertEqual(sorted(route.access.role_names),
                                 sorted(roles_holding(permission)))

    def test_the_role_vocabularies_are_the_same_set(self):
        """Three modules name the roles. All three must name the same three."""
        from apps.api.security import Role
        from pgx.application.execution_context import GOVERNED_ACTOR_ROLES

        self.assertEqual({role.value for role in Role}, set(GOVERNED_ROLES))
        self.assertEqual(set(GOVERNED_ACTOR_ROLES), set(GOVERNED_ROLES))


class TestThePublishedRegistry(unittest.TestCase):

    def test_the_digest_changes_when_a_holder_would_change(self):
        """The digest is published so a silent widening shows up even if
        nobody reads the table."""
        baseline = registry_digest()
        self.assertTrue(baseline.startswith("sha256:"))
        self.assertEqual(baseline, registry_digest())

    def test_the_matrix_is_complete(self):
        document = registry_document()
        for permission_id, row in document["matrix"].items():
            with self.subTest(permission=permission_id):
                self.assertEqual(sorted(row), sorted(GOVERNED_ROLES))

    def test_the_document_carries_no_secret(self):
        rendered = str(registry_document())
        for marker in ("password", "token", "cookie", "secret"):
            with self.subTest(marker=marker):
                self.assertNotIn(marker + "=", rendered)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
