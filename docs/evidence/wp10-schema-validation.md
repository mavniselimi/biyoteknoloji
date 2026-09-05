# WP-10 schema validation evidence

| Field | Value |
|---|---|
| Document ID | `DOC-EVID-011` |
| Work package | WP-10 — Curation Workflow and Approval Governance |
| What this proves | migration 0007's schema is valid PostgreSQL and its constraints and triggers behave as designed |
| What this does **not** prove | anything about Alembic's runner, its revision chain, or `alembic_version` stamping |

---

## 1. This is not Alembic

Alembic and SQLAlchemy cannot be installed in this environment. What was
executed is `build/wp10-schema.sql`, rendered from
`migrations/versions/0007_wp10_curation_workflow.py` by
`scripts/render_wp10_schema.py`, which reads the migration's AST and emits the
equivalent DDL. Because the SQL is *derived* rather than hand-maintained, the
two cannot drift; a test asserts the renderer reads that file.

Running the rendered SQL proves the schema is valid PostgreSQL and that its
constraints and triggers refuse what they were written to refuse. It proves
nothing about Alembic's runner. **A26** — the migration applying and reverting
under Alembic itself — remains **BLOCKED** for the same reason WP-02 through
WP-08 recorded it as blocked.

Reproduce with:

```
python3 scripts/render_wp10_schema.py --out build/wp10-schema.sql
python3 scripts/render_wp10_schema.py --direction downgrade \
    --out build/wp10-downgrade.sql
createdb pgx_wp10 --template <a database holding 0001-0006>
psql -d pgx_wp10 -v ON_ERROR_STOP=1 -f build/wp10-schema.sql
```

## 2. The 0006 → 0007 → 0006 → 0007 cycle

```
$ psql --version
psql (PostgreSQL) 16.13 (Ubuntu 16.13-0ubuntu0.24.04.1)

$ createdb pgx_wp10_ev --template pgx_wp08   # WP-02..WP-08 schema already applied

$ psql -v ON_ERROR_STOP=1 -f build/wp10-schema.sql   # 0006 -> 0007
  11 CREATE INDEX
  7 CREATE TRIGGER
  7 CREATE TABLE
  4 CREATE FUNCTION
  2 ALTER TABLE
  1 COMMIT
  1 BEGIN

$ SELECT count(*) ... curation tables
7 curation tables, 7 triggers, 38 check constraints

$ psql -f build/wp10-downgrade.sql   # 0007 -> 0006, empty database
COMMIT
0 curation tables remain

$ psql -f build/wp10-schema.sql   # 0006 -> 0007 again
COMMIT
7 curation tables
```

Seven tables, seven triggers, thirty-eight check constraints, and two
`ALTER TABLE` statements — the drop and recreate of
`ck_audit_events_action_enum`, which is a widening: every action the old
constraint admitted, the new one admits. The downgrade removes exactly what the
upgrade created, and re-applying produces the same seven tables.

Both directions are wrapped in a single transaction, as Alembic runs them. A
schema that failed halfway is not a state this project accepts, and — more
importantly for the downgrade — a refusal that arrived after eight tables were
gone would have refused nothing.

## 3. The constraints and triggers, exercised

Twenty statements, each written to be refused for a stated reason, plus the
legal transitions that must still work.

```
INSERT 0 1
--- 1. legacy values must be namespaced ---
ERROR:  work item TEST-WI-BAD: legacy field(s) demo_risk_level are not namespaced. Legacy values are the
--- 2. a work item cannot jump RAW -> CURATED ---
ERROR:  work item TEST-WI-DB: RAW->CURATED is not a transition this workflow has. Permitted: RAW->UNDER_
--- 3. a status change must advance version ---
ERROR:  work item TEST-WI-DB: an update must advance version (was 0, offered 0). Optimistic concurrency 
--- 4. a work item cannot be deleted ---
ERROR:  curation_work_items rows are not deletable: audit events, revisions and reviews reference this q
--- 5. the legal transition works ---
INSERT 0 1
UPDATE 1
--- 6. a revision cannot be edited or deleted ---
ERROR:  UPDATE on public.curation_revisions is not permitted: a curation record states what a named pers
ERROR:  DELETE on public.curation_revisions is not permitted: a curation record states what a named pers
--- 7. revision 2 must name a parent ---
ERROR:  new row for relation "curation_revisions" violates check constraint "ck_curation_revisions_linea
--- 8. the author cannot review their own revision ---
ERROR:  TEST-curator-1 authored revision REV-1 and cannot review it: one person checking their own concl
--- 9. a review that lies about the author is refused ---
ERROR:  review records author TEST-somebody-else but revision REV-1 was authored by TEST-curator-1; the 
--- 10. a review pinning the wrong content hash is refused ---
ERROR:  review pins content hash sha256:9999999999999999999999999999999999999999999999999999999999999999
--- 11. a genuine independent review is accepted ---
INSERT 0 1
--- 12. one reviewer decides one version once ---
ERROR:  duplicate key value violates unique constraint "uq_curation_reviews_version_reviewer"
--- 13. a review cannot be edited ---
ERROR:  UPDATE on public.curation_reviews is not permitted: a curation record states what a named person
--- 14. reach CURATED, then find it immutable ---
UPDATE 1
ERROR:  work item TEST-WI-DB is CURATED: a decided conclusion is immutable. A correction is a new work i
--- 15. no role may be assigned to a non-TEST id claiming synthetic ---
ERROR:  new row for relation "curation_role_assignments" violates check constraint "ck_curation_role_ass
--- 16. an adjudicator may not be a party ---
ERROR:  new row for relation "curation_adjudications" violates check constraint "ck_curation_adjudicatio
--- 17. an adjudication must keep both positions ---
ERROR:  new row for relation "curation_adjudications" violates check constraint "ck_curation_adjudicatio
--- 18. a steward cannot claim verified while reporting problems ---
ERROR:  new row for relation "curation_provenance_verifications" violates check constraint "ck_curation_
--- 19. the new audit actions are accepted ---
INSERT 0 1
--- 20. an invented audit action is not ---
ERROR:  new row for relation "audit_events" violates check constraint "ck_audit_events_action_enum"
```

Reading the interesting ones:

- **1** is the legacy namespacing trigger. It is a trigger rather than a check
  constraint because PostgreSQL refuses a subquery inside `CHECK`, and "every
  key of this document starts with `legacy.`" cannot be written without one. It
  fires on `INSERT`, which is the operation that matters: the legacy import is a
  bulk insert, and a rule that only ran on `UPDATE` would never fire for it.
- **2, 3, 14** are the state machine, the version guard and terminal
  immutability, all in one trigger, each raising a distinct message. An operator
  needs to know *which* of the three refused them.
- **8, 9, 10** are the separation of duties. The check constraint compares two
  columns on the review row; the trigger compares one of them with the revision
  that actually exists, so a review row that lied about its author is refused
  too — and so is one pinning a content hash the stored revision does not have.
- **12** is the uniqueness that stops a reviewer deciding one work-item version
  twice. Changing your mind means reviewing the next version, not inserting a
  second row.
- **20** is the widened audit action list refusing an invented action. There is
  no `CURATION_AUTO_APPROVED`.

## 4. The 1,559 legacy work items, loaded

```
work items                : 1559
RAW                       : 1559
UNDER_REVIEW              : 0
CURATED                   : 0
REJECTED                  : 0
tagged LEGACY_MIGRATION   : 1559
with any revision         : 0
revisions                 : 0
reviews                   : 0
adjudications             : 0
curated_interpretations   : 0
role assignments          : 0
non-namespaced legacy keys: 0
--- downgrade with only RAW legacy rows ---
COMMIT
0 curation tables remain
```

Every count that must be zero is zero, and the namespacing trigger admitted all
1,559 rows without complaint. The downgrade is permitted here because these
rows assert nothing: they are questions on a queue.

## 5. The downgrade refuses a database holding a decision

```
--- downgrade with a decision present ---
ERROR:  refusing to downgrade: this database holds 1 decided work item(s), 1 review(s) and 0 adjudic
ation(s). Those rows are the only record that named people reached a scientific conclusion, and drop
ping these tables would destroy it. Export them and decide explicitly what replaces this schema.
ROLLBACK
7 curation tables still present; 1 review(s) preserved
```

The guard runs before the first `DROP` and raises inside the same transaction,
so the refusal is total: seven tables still present, the review preserved. Those
rows are the only record that named people reached a scientific conclusion, and
no migration should destroy that on an operator's behalf.

## 6. What was not touched

`0001` through `0006` are unmodified on disk; their `down_revision` chain is
asserted unbroken by test. `0007` drops no table and no column, and the only
existing table it touches is `audit_events`, whose action list it widens.
