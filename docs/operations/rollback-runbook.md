# Rollback runbook (WP-24)

| Field | Value |
|---|---|
| Document ID | `DOC-OPS-024-D` |
| Status | **Neither rollback has been exercised.** No second image and no second release exist. |

---

## 0. Two different operations share one word

Conflating them is how a deployment ends up serving an old image against a new
schema — or deciding that rolling back a release means editing one.

| | Deployment rollback | Governed release rollback |
|---|---|---|
| What moves | the running image | the active-release pointer |
| Owner | WP-24 | WP-03's release service |
| Touches the schema | **never** | never |
| Touches history | never | never |
| Audited | health before and after | a governed audit event |

## 1. Deployment rollback

### The rule

**It must not downgrade the database.** `0011`'s `downgrade()` refuses while
any user, session or governed audit event exists, and that refusal is correct:
dropping those tables destroys the account history and the integrity chain
together.

So an image rollback is only safe between two images that both work against the
current schema. That is a property of the two images, which is why the drill
records **both identities** rather than "the previous one".

### The procedure

```bash
# 1. Record what is running now, by identity - not by tag.
docker image inspect --format '{{.Id}}' pgx-platform:current

# 2. Record the candidate.
docker image inspect --format '{{.Id}}' pgx-platform:candidate

# 3. Check the candidate's health before switching.
pgx-deploy smoke --url https://staging.example --environment STAGING

# 4. Switch. The compose file's `image:` is repointed and the service
#    recreated; no database command runs.

# 5. Health after.
pgx-deploy smoke --url https://staging.example --environment STAGING

# 6. Record.
pgx-deploy rollback --environment STAGING
```

### Why identities, not tags

A tag is a name somebody can move. Two rollback records that both say
`pgx-platform:latest` describe an operation nobody can reconstruct.
`image_rollback_drill()` reports a blocker when either image is identified by
tag alone, and another when the two identities are the same — because then no
rollback took place.

`database_downgraded: true` makes the drill a **failure**, not a success. A
rollback that downgraded the schema is not the operation this drill is for, and
letting it pass would put the procedure in a runbook.

## 2. Governed release rollback

WP-03's release service performs it. WP-24 does not reimplement the eligibility
rules — a second implementation would be a second place for them to be wrong.

What WP-24 records:

- **two eligible releases existed.** A rollback needs somewhere to go, and
  manufacturing a second release as evidence would make the drill describe a
  release nobody approved.
- **the pointer transition was audited.** An unaudited release transition is a
  change to what the system asserts, made by nobody.
- **no manifest was edited.** A release is immutable. Rolling back means
  pointing somewhere else, not changing where you were pointing — so the
  history stays readable and a rolled-back release is still exactly what it was
  when it was active.

## 3. Current status

`BLOCKED`. There is one image identity at most and zero eligible releases.

The machinery is exercised against clearly labelled test doubles
(`tests/fixtures/wp24/doubles.py`), and those results carry
`TEST_ONLY_REHEARSAL`, which never closes a gate. The operational drill stays
blocked, and the label travels with the result rather than being applied by
whoever writes the report.
