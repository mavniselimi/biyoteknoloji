# Governed Audit Policy

| Field | Value |
|---|---|
| Document ID | `DOC-SEC-003` |
| Work package | WP-23 |
| Machine-readable | `pgx/infrastructure/audit/`, `data/security/wp23-audit-action-registry.json` |
| Event schema version | `pgx-wp23-governed-audit-event/1` |
| Status | **implemented; the stream is empty and no chain has been verified against a real store** |

---

## 1. Five trails, not one, and four of them are untouched

| Trail | Owner | Hash-linked | WP-23 changed |
|---|---|:-:|---|
| `audit_events` | WP-03 | no | nothing |
| assessment audit | WP-14 | no | nothing |
| curation audit | WP-10 | no | nothing |
| `expert_review_audit_events` | WP-22 | yes | `actor_authenticated` may now be `true` |
| `governed_audit_events` | **WP-23** | yes | new, empty |

**Nothing is backfilled into the new stream, ever.** A historical row was
written by a system with no authentication. Giving it an actor and an
assurance level would be manufacturing provenance, which is the exact failure
an audit trail exists to prevent. Migration 0011 contains no `INSERT ...
SELECT` into `governed_audit_events` and no `UPDATE` of any historical table,
and a test asserts it.

WP-18's access-ledger `actor_authenticated = false` keeps its historical
meaning. New authenticated access evidence goes to the canonical stream
instead.

---

## 2. What every event carries

| Group | Fields |
|---|---|
| identity | `event_id`, `schema_version`, `stream_id`, `sequence` |
| chain | `previous_hash`, `event_hash` |
| actor | `actor_id`, `actor_role`, `auth_mechanism`, `auth_assurance`, `session_reference` |
| time | `occurred_at` (UTC), `request_id` |
| act | `action`, `object_type`, `object_id`, `outcome`, `result_code` |
| data | `input_hash`, `output_hash` |
| release | `software_id`/`_hash`, `dataset_id`/`_hash`, `ruleset_id`/`_hash`, `release_id`, `release_manifest_hash` |
| state | `metadata.previous_state`, `metadata.new_state` |

`metadata` is a **closed vocabulary** of 15 declared keys. There is no
free-form bucket, because a mapping that accepted arbitrary keys would sooner
or later receive a request body - the place that builds an audit event is the
place that has one.

### What an event may never contain

43 field names, refused at any nesting depth:

- password, password hash, passphrase, secret, any token, CSRF token, cookie,
  authorization header, credential, API key, private key, DSN, connection
  string;
- phenotype, genotype, diplotype, VCF, medication list, patient identifier,
  MRN, date of birth, EHR extract, clinical record;
- holdout payload, expected response, expected attention level, expected
  coverage status, reviewer note, correction replacement;
- request body, payload, filesystem path, traceback.

The check walks nested mappings **and lists**. The first version of any such
check looks at top-level keys only, and the first thing to defeat it is
`{"context": {"password": ...}}`.

The refusal message names the field and never the value.

---

## 3. Assurance: a fixture cannot describe itself as a person

| Mechanism | Assurance | Production-capable |
|---|---|:-:|
| `NONE` | `NONE` | — |
| `STATIC_TOKEN` | `TEST_STATIC_TOKEN` | no |
| `SESSION` | `SESSION` | **yes** |

`auth_assurance = SESSION` requires `auth_mechanism = SESSION` **and** a
non-null `session_reference`. Enforced in `GovernedAuditEvent.__post_init__`
and again by a database check constraint - because a direct insert bypasses
the model and cannot bypass the server.

`session_reference` is the session **id**, never the token and never its
digest. A digest in an audit row would be a verifier for the cookie: anyone
holding both the row and a captured token could confirm they matched.

---

## 4. The chain

```
event_hash = sha256(canonical({previous_hash, payload}))
```

| Tamper | Detected because |
|---|---|
| edit a field | the event's own hash changes, so its successor's `previous_hash` no longer matches |
| delete an event | the sequence is no longer contiguous |
| insert an event | same |
| reorder two | both |

Serialization is canonical - sorted keys, fixed separators, ASCII-escaped - so
a chain verifies identically on any machine. A chain whose hashes depended on
insertion order would verify where it was written and fail everywhere else,
which is indistinguishable from tampering.

### Concurrency

`governed_audit_stream_head` holds one row per stream, locked `FOR UPDATE`
before each append. `SELECT max(sequence)` then insert is a read-then-write
race whose losing side is a forked chain: two events at the same sequence,
each linking to the same predecessor, both verifying in isolation. The
`pgx_governed_audit_chain_guard` trigger additionally refuses an insert whose
sequence does not follow the recorded head.

### Append-only

- the port classes declare no `update` and no `delete`;
- `SqlAlchemyAuditRepository` implements neither, not even privately;
- `trg_governed_audit_events_append_only` raises on `UPDATE` and `DELETE`.

The first two are application promises. Only the third survives someone with a
`psql` prompt.

---

## 5. Atomicity

**Successful governed change:** the state change and the audit append commit
in one transaction. If the append fails, `AuditAppendError` propagates, the
transaction does not commit, and the change is gone. A governed success nobody
can account for is worse than a refusal, because the refusal tells the
operator something happened.

**Refused operation:** `record_refusal` never raises. If it did, an audit
outage would convert every controlled refusal into a 500 - and a 500 is a
different answer from a refusal, which is how "the audit system is down"
becomes "the request was actually processed". It returns whether the event was
written, so a caller can report the gap without changing what the client sees.

Five actions are exempt from atomicity - `LOGIN_FAILED`, `SESSION_EXPIRED`,
`ASSESSMENT_REFUSED`, `RELEASE_REFUSED` and `AUDIT_CHAIN_VERIFIED`. All are
refusals or a read-only check, where a failed append loses a log line rather
than orphaning a state change.

---

## 6. Coverage: 41 governed actions

| Area | Actions |
|---|---|
| authentication | 14 - bootstrap, create, disable, enable, lock, unlock, role change, password change, login succeeded, login failed, logout, session created, session revoked, session expired |
| assessment | 3 - requested, completed, refused |
| release | 5 - registered, activated, rolled back, retired, refused |
| curation and rules | 12 - revision created/submitted, reviewed, approved, rejected, adjudicated, rule validated/deprecated, ruleset validated/frozen/reopened/retired |
| expert review | 6 - assigned, expectation recorded, result revealed, completed, correction appended, invalidated |
| audit | 1 - chain verified |

A governed action with no registry entry fails
`tests/unit/audit/test_governed_audit.py`, so the registry cannot fall behind
the code it describes.

---

## 7. Reading the trail

`pgx-audit verify` reports whether the chain is intact and, if not, at which
sequence it first is not. **It never prints an event.** A verification report
that quoted the offending record would be a content-reading command wearing an
integrity command's name.

`pgx-audit recent` prints safe projections: sequence, time, action, outcome,
object identity, actor and assurance. No input hash, no output hash, no
metadata - the hashes are joinable to the records they cover, so a reader with
a candidate input could otherwise confirm a match.

`verified` is `null` when no store was inspected and `false` only when a store
was inspected and its chain was broken. Collapsing those would let "we could
not look" read as one of the two real answers.

**Current state:** the stream is empty, no store exists, and
`audit_chain_verified` is `null` in the gate status. That is not a passing
result.
