# Security boundary

## What WP-16 built, and what it deliberately did not

WP-23 owns authentication. This layer needed two things from it and built
exactly those two: **a trusted actor and role for the audit trail**, and **a
place where a route says which roles may reach it**.

Built:

- `Principal` — a frozen value carrying `actor`, `role` and `authenticated_by`.
- Three governed roles: `DEMO_USER`, `EXPERT_REVIEWER`, `ADMIN`.
- `AccessPolicy` and a route-level check.
- A dependency that obtains a principal, replaceable in tests through one
  override.
- A production default that refuses.

Not built, and asserted absent by
`TestNoAuthenticationWasImplemented`: password hashing of any kind (Argon2,
bcrypt, scrypt, PBKDF2), sessions, signup, login, logout, JWT encoding or
decoding, cookies, CSRF tokens, or any endpoint that issues or accepts a
credential. No route path contains `login`, `token` or `session`.

## The default fails closed

`UnconfiguredAuthentication` is what a production deployment gets until WP-23
lands, and what a misconfigured one gets forever. It **never returns a
principal** — not a demo one, not an anonymous one, not an admin one for local
convenience. A resolver that returns *something* when it has verified
*nothing* is the single failure that class exists to make impossible.

It answers **503 `AUTHENTICATION_NOT_CONFIGURED`, not 401**. An operator who
has not configured authentication has a server that is not ready, not a caller
who presented bad credentials. That status code is the difference between a
deployment defect that pages someone and a client error that does not. The same
condition also fails the `authentication` readiness component, so the instance
reports itself unready rather than silently serving nothing.

`StaticTokenAuthentication` exists for development and is **refused in
production by `apps/api/config.py`** — refused outright, not merely defaulted
off, because a development convenience that can be switched on by an
environment variable eventually is. The refusal lives in the settings loader
rather than in the resolver: a resolver cannot know which environment it was
constructed in, and a check it performed on itself would be one an operator
could satisfy by setting the wrong variable.

## No role hierarchy

`ADMIN` does not implicitly satisfy an `EXPERT_REVIEWER` check. Every route
names the exact set it permits. A hierarchy is convenient right up until
someone adds a role in the middle of it, and then a gate written to mean "only
a reviewer" silently means "a reviewer or anyone above one".

The role matrix is in `docs/api/p0-contract.md` and is declared once, in
`apps/api/routes.py`. A router cannot widen it: routers call
`require_access(_ROUTE.access, _ROUTE.operation_id)` and a test asserts that no
router constructs an `AccessPolicy` or calls `roles(...)` of its own.

## A client cannot forge an actor or a role

Three independent mechanisms, and all three would have to fail:

1. **The contract refuses the names.** `actor`, `role` and `principal` are
   prohibited request fields. A body carrying any of them is refused as a
   whole, at any depth, and the value is not echoed back.
2. **No request model declares them.** Asserted over every model with
   `direction == "request"`.
3. **The context is built only from a principal.** `get_execution_context`
   takes a `Request` and a `Principal`, reads the actor and the role off the
   principal, and names no request-payload accessor — no `body`, no `json`, no
   `form`, no `query_params`, no `path_params`. Asserted by walking the
   function's syntax tree rather than by searching its text, so the docstring
   explaining the guarantee cannot satisfy the check.

No module anywhere in `apps` names an `X-Actor`, `X-Role` or `X-User` header:
asserted over string constants specifically, with docstrings excluded.

The actor and role then travel into `pgx.application.execution_context`, whose
`ExecutionContext` refuses any role outside the governed three — so even a
programming error above it cannot write an ungoverned role into an audit row.

## What reaches the audit trail

On success, the `ASSESSMENT_COMPLETED` audit event records: the input hash, the
output hash, the pinned release, the two governed status values, and — when a
request context was supplied — the actor, the role, the channel, the
correlation id and the authenticating mechanism.

On refusal, the `ASSESSMENT_REFUSED` event records the stable error code, the
location, the mode, and the same context fields. It carries **no phenotype
profile, no medication list, no case narrative, no case id and no rejected
value**: an audit row outlives the request, is read by operators who have no
reason to see case content, and is exported to places an assessment row is not.

Auditing never turns a failure into a success. The refusal audit is written
before the exception propagates, and a failure inside the audit sink is
swallowed rather than allowed to mask the refusal it was recording.

## Transport hardening

- **Bounded body.** Refused before parsing, by declared `Content-Length` and
  then by bytes actually read — a chunked request declares nothing and a lying
  one declares the wrong thing.
- **Security headers** on every response: `nosniff`, `DENY` framing,
  `no-referrer`, `same-origin` resource policy, and a content-security policy
  that permits nothing at all. This API serves no HTML, so the policy that
  matters is the one stopping a browser from treating a response as anything
  but data.
- **`Cache-Control: no-store`** by default. An assessment response carries a
  case's governed facts and an error response carries a correlation id; a
  shared cache holding either is a disclosure nobody configured on purpose. An
  immutable caching policy for a stored assessment is defensible — the document
  really is immutable — but it has to be proven per route rather than assumed.
- **CORS off by default.** No origin is allowed unless one is configured;
  credentials with a wildcard origin are refused; a wildcard origin is refused
  outright in production; at most sixteen origins, because a longer list is a
  policy nobody reviews.
- **No configuration error quotes its value.** Every `ApiConfigurationError`
  message passes through WP-02's `sanitize_message`, and the settings object
  holds no DSN at all — only whether one is configured — so a repr, a log line
  or an exception cannot carry it.

## What is not protected here, and by whom

Rate limiting, brute-force protection, token issuance, credential rotation,
session fixation and CSRF are all WP-23's. This layer's contribution is that
none of them can be *accidentally half-implemented*: there is no credential to
mishandle, because none is issued or accepted.
