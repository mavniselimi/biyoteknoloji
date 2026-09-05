# WP-11 schema validation evidence

| Field | Value |
|---|---|
| Document ID | `DOC-EVID-013` |
| Work package | WP-11 — Computable Rule Specification and Validated Rule Registry |
| What this proves | migration 0008's schema is valid PostgreSQL and its constraints and triggers behave as designed |
| What this does **not** prove | anything about Alembic's runner, its revision chain, or `alembic_version` stamping — and nothing at all about whether any rule is scientifically correct |

---

## 1. This is not Alembic

Alembic and SQLAlchemy cannot be installed in this environment. What was
executed is `build/wp11-schema.sql`, rendered from
`migrations/versions/0008_wp11_rules_and_rulesets.py` by
`scripts/render_wp11_schema.py`, which reads the migration's AST and emits the
equivalent DDL. Because the SQL is *derived* rather than hand-maintained, the
two cannot drift; a test asserts the renderer reads that file.

Running the rendered SQL proves the schema is valid PostgreSQL and that its
constraints and triggers refuse what they were written to refuse. It proves
nothing about Alembic's runner. **A26** — the migration applying and reverting
under Alembic itself — remains **BLOCKED** for the same reason WP-02 through
WP-10 recorded it as blocked.

Reproduce with:

```
python3 scripts/render_wp11_schema.py --out build/wp11-schema.sql
python3 scripts/render_wp11_schema.py --direction downgrade \
    --out build/wp11-schema-downgrade.sql
createdb pgx_wp11 --template <a database holding 0001-0007>
psql -d pgx_wp11 -v ON_ERROR_STOP=1 -f build/wp11-schema.sql
```

## 2. The 0007 → 0008 → 0007 → 0008 cycle

```
$ psql --version
psql (PostgreSQL) 16.13 (Ubuntu 16.13-0ubuntu0.24.04.1)

$ psql -d pgx_wp11_d -v ON_ERROR_STOP=1 -f build/wp11-schema.sql
0008 applied

$ psql -d pgx_wp11_d -At -c "SELECT table_name || ' ' || count(*) ..."
computable_rules 39
ruleset_rules 7
ruleset_versions 29

$ psql -d pgx_wp11_d -v ON_ERROR_STOP=1 -f build/wp11-schema-downgrade.sql
downgrade ok
computable_rules 11        # exactly the 0001 shape
ruleset_rules 2            # exactly the 0002 shape
ruleset_versions 8         # exactly the 0002 shape
wp11 tables remaining: 0

$ psql -d pgx_wp11_d -v ON_ERROR_STOP=1 -f build/wp11-schema.sql
re-upgrade ok
columns in schema before=576 after=576
computable_rules 39 / ruleset_versions 29 / ruleset_rules 7
```

The three pre-existing tables return to their exact pre-WP-11 shapes and back
again, and the whole schema's column count is identical before and after the
round trip.

## 3. The ORM and the database agree, column for column

The SQLAlchemy adapters read these columns by name, so a model missing one is
a runtime failure rather than a documentation problem. Every mapped column
name was extracted from `pgx/infrastructure/db/models.py` by AST and compared
against `information_schema.columns` on the live database:

```
computable_rules       39 columns   identical sets
ruleset_versions       29 columns   identical sets
ruleset_rules           7 columns   identical sets
rule_lifecycle_events  11 columns   identical sets
ruleset_builds         11 columns   identical sets
ruleset_approvals      14 columns   identical sets
rule_evidence           2 columns   identical sets
```

## 4. The behavioural drill: 24 probes

Each probe attempts something the schema is meant to permit or refuse. Run
against a clean database holding 0001–0008.

| # | Probe | Outcome |
|---|---|---|
| 1 | a rule authors `NOT_ASSESSED` | REFUSED `ck_computable_rules_outcome_is_authorable` |
| 2 | a rule jumps `DRAFT → VALIDATED` | REFUSED — not a transition this lifecycle has |
| 3 | a status change without advancing `lifecycle_version` | REFUSED — a status change must advance it |
| 4 | `DRAFT → CURATED` | ACCEPTED |
| 5 | `CURATED → VALIDATED` with no evidence link | REFUSED (`SAFETY-INV-006`) |
| 6 | the same with evidence | ACCEPTED |
| 7 | editing a `VALIDATED` rule's content | REFUSED — a correction is a new version |
| 8 | deleting a rule | REFUSED — withdrawal is `DEPRECATED` |
| 9 | the validator is the author | REFUSED `ck_computable_rules_validator_is_not_author` |
| 10 | one family/version pair twice | REFUSED `uq_computable_rules_family_version` |
| 11 | a ruleset jumps `BUILDING → FROZEN` | REFUSED — there is no such edge |
| 12 | pinning a rule that is not `VALIDATED` | REFUSED |
| 13 | membership pinning the wrong content hash | REFUSED |
| 14 | a correct member | ACCEPTED |
| 15 | the same member twice | REFUSED `pk_ruleset_rules` |
| 16 | `BUILDING → VALIDATED → FROZEN` | ACCEPTED |
| 17 | changing a frozen ruleset's membership | REFUSED |
| 18 | changing a frozen ruleset's manifest hash | REFUSED |
| 19 | unfreezing a frozen ruleset | REFUSED — `FROZEN → BUILDING` does not exist |
| 20 | `FROZEN → RETIRED` | ACCEPTED, artifact path retained |
| 21 | editing a build record | REFUSED — append-only trigger |
| 22 | an approval naming one person twice | REFUSED `ck_ruleset_approvals_reviewer_is_not_author` |
| 23 | the thirteen new audit actions | ACCEPTED |
| 24 | an invented audit action `RULE_AUTO_APPROVED` | REFUSED `ck_audit_events_action_enum` |

## 5. The downgrade refuses to destroy approved work

With one `VALIDATED` rule and one frozen-then-retired ruleset in the database:

```
$ psql -d pgx_wp11_drill -v ON_ERROR_STOP=1 -f build/wp11-schema-downgrade.sql
ERROR:  refusing to downgrade: this database holds 1 approved rule(s) and
        0 frozen ruleset(s). Those rows record that named people approved a
        scientific claim, and a frozen ruleset may be cited by a release or a
        historical assessment. Export them and decide explicitly what replaces
        this schema.

$ psql -d pgx_wp11_drill -At -c "SELECT count(*) FROM information_schema.tables
    WHERE table_name IN ('rule_lifecycle_events','ruleset_builds','ruleset_approvals')"
3
```

The refusal is atomic: all three WP-11 tables are still present afterwards.

## 6. What none of this proves

The database refuses malformed and unauthorised *shapes*. It cannot tell
whether a rule is scientifically correct, whether the people named in an
approval record are real, or whether they hold the credentials the record
claims. Those are questions for people and, for the identity half, for WP-23.
No rule in this repository has been through any of it: the real registry is
empty, and `data/rulesets/wp11-real-gate-status.json` says why.
