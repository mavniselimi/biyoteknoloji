# RBAC Matrix

| Field | Value |
|---|---|
| Document ID | `DOC-SEC-002` |
| Work package | WP-23 |
| Machine-readable | `pgx/security/rbac.py`, `data/security/wp23-rbac-registry.json` |
| Registry version | `pgx-wp23-rbac-registry/1` |

> There is **no role hierarchy**. Every permission names its holders
> explicitly. `role_hierarchy` is `null` in the published registry - not an
> empty object, which would read as a hierarchy that happens to be empty
> today.

---

## The matrix

| Permission | DEMO_USER | EXPERT_REVIEWER | ADMIN |
|---|:--:|:--:|:--:|
| `session.login` | ✅ | ✅ | ✅ |
| `session.logout` | ✅ | ✅ | ✅ |
| `session.read_self` | ✅ | ✅ | ✅ |
| `assessment.create` | ✅ | ✅ | ✅ |
| `assessment.read` | ✅ | ✅ | ✅ |
| `catalogue.read` | ✅ | ✅ | ✅ |
| `evidence.read` | ✅ | ✅ | ✅ |
| `validation.read_public` | ✅ | ✅ | ✅ |
| `expert_review.list_assigned` | — | ✅ | **—** |
| `expert_review.read_assigned` | — | ✅ | **—** |
| `expert_review.submit_expected` | — | ✅ | **—** |
| `expert_review.reveal_assigned` | — | ✅ | **—** |
| `expert_review.complete_assigned` | — | ✅ | **—** |
| `expert_review.append_correction` | — | ✅ | **—** |
| `release.register` | — | — | ✅ |
| `release.activate` | — | — | ✅ |
| `release.rollback` | — | — | ✅ |
| `release.retire` | — | — | ✅ |
| `source_policy.administer` | — | — | ✅ |
| `curation.administer` | — | — | ✅ |
| `rule.administer` | — | — | ✅ |
| `ruleset.administer` | — | — | ✅ |
| `user.administer` | — | — | ✅ |
| `audit.read` | — | — | ✅ |
| `audit.verify` | — | — | ✅ |

25 permissions. DEMO_USER holds 8, EXPERT_REVIEWER 14, ADMIN 19.

---

## The two rules that matter

### ADMIN is not a reviewer

Every `expert_review.*` cell in the ADMIN column is empty, and that is the
point rather than an oversight. A review is evidence only if the reviewer did
not build the thing they reviewed; an administrator who could review would
destroy the property WP-22 exists for.

An administrator who must review holds a **second account** whose exact role
is `EXPERT_REVIEWER`. Even then, WP-22's assignment check and payload permit
still apply: this registry grants the ability to *attempt* an operation and
never grants an assignment.

### Authentication does not grant curation authority

`curation.administer` permits operating the curation tooling. It is **not**
authority to author, review or adjudicate a revision. WP-09's
separation-of-duty rules govern those, and no application role overrides them
- which is why this registry deliberately contains no permission naming a
curation *decision*.

---

## Why containment is safe here

`DEMO_USER`'s permissions are a subset of both other roles'. That is
architecture.md §13's explicit design - *"EXPERT_REVIEWER: demo permissions
plus assigned blind reviews"* - written out permission by permission rather
than inherited.

The subset is data, not a rule. `role_holds` is literal set membership and
consults no ordering, so the containment cannot become an inheritance
mechanism by accident. What is forbidden, and asserted by test, is the pair
that would collapse separation of duty:

- ADMIN must not contain EXPERT_REVIEWER;
- EXPERT_REVIEWER must not contain ADMIN.

Each holds something the other does not, so neither can be satisfied by two
empty sets.

---

## Route tables agree with this registry

FastAPI enforces the roles declared in `apps/api/routes.py` and
`apps/web/routes.py`. This registry is what the security documentation and the
published artifact describe. Two tables that agree today and drift tomorrow
are worse than one, so `tests/unit/security/test_rbac.py` maps every non-public
route to its permission and asserts the declared roles are exactly the
registry's holders.

A route with no mapping fails that test. It cannot be added silently.
