# The curation role matrix

| Field | Value |
|---|---|
| Document ID | `DOC-SCI-011` |
| Work package | WP-10 — Curation Workflow and Approval Governance |
| Status | **No identity currently holds any of these roles. The production assignment set is empty and stays empty until WP-23.** |

---

## 1. Read this first

The six roles below are **not accounts and not credentials**. This project has
no authentication. `curation_role_assignments` is created empty by migration
0007 and has no rows; every role lookup against it raises, and no real workflow
operation can run.

That is deliberate. A role table with rows in it, and no way to prove who is
using them, would be worse than no role table: it would produce an audit trail
naming people who never acted. WP-23 owns identity; until it exists, nobody
holds a role.

What follows is therefore the *design* of separation of duties, enforced by
code and by database constraints, waiting for real people to be bound to it.

## 2. The matrix

| Role | Writes a revision | Submits for review | Reviews / approves | Adjudicates | Verifies provenance | Approves the protocol |
|---|:--:|:--:|:--:|:--:|:--:|:--:|
| `SCIENTIFIC_CURATOR` | ✅ | ✅ (own only) | ❌ | ❌ | ❌ | ❌ |
| `INDEPENDENT_SCIENTIFIC_REVIEWER` | ❌ | ❌ | ✅ (not own) | ❌ | ❌ | ❌ |
| `ADJUDICATOR` | ❌ | ❌ | ✅ (not own) | ✅ (not a party) | ❌ | ❌ |
| `DATA_PROVENANCE_STEWARD` | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ |
| `PROTOCOL_OWNER` | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ (WP-09) |
| `ENGINEERING_OBSERVER` | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |

`ENGINEERING_OBSERVER` may read. It exists so that "an engineer looked at this"
is expressible without that engineer accidentally holding a scientific
permission.

## 3. The separations, and why each one exists

**A curator may not review their own revision.** One person checking their own
conclusion is not an independent review; it is the same judgement applied
twice. Enforced in four places: the review record's own constructor, the
service's role check, `GATE_REVIEWER_NOT_INDEPENDENT`, and a database check
constraint plus a trigger. The trigger compares the reviewer against the
*stored* revision, so a review row that misstated its author is refused too.

**A curator may only submit their own revision.** Somebody submitting a
colleague's draft would put a conclusion up for review that its author had not
finished.

**An adjudicator may not be a party to the dispute.** Somebody breaking a tie
they are a side of is not adjudicating.

**A steward may not advance a conclusion.** Confirming that evidence traces to
raw bytes is a plumbing check. A system that let it stand in for a scientific
one would be treating a filesystem question as a scientific judgement.

**A protocol owner may not approve a curation.** Owning the document that says
how curation is done is not the same as judging one conclusion, and WP-09's
approval model keeps them apart.

**An engineering observer may not do anything.** Including — especially —
approve.

## 4. How a role is obtained

It is looked up, never asserted.

The service takes an **actor id** and resolves roles through an injected
`RoleProvider`. It refuses an `ActorContext` passed in place of an id, so a
caller cannot hand in its own permissions. An `ActorContext` cannot be
constructed with roles directly either: it must have been issued by a provider.

There is no `--role` flag, no `--as` flag, no role form field and no override
anywhere. The CLI refuses `--role`, `--as`, `--as-role`, `--reviewer-role`,
`--grant`, `--force`, `--skip-gates` and `--approve` **by name**, so the error
explains why rather than saying "unrecognized argument"; and argparse
abbreviation is switched off, because `--role` was otherwise silently accepted
as a prefix of `--roles`.

## 5. Synthetic actors

The test suite uses five actors prefixed `TEST-`, each holding exactly one
role. The prefix and a `synthetic` flag must agree in both directions — an id
starting `TEST-` must declare itself synthetic, and one that does not must
not — enforced by the value object and by a database check constraint.

So a fixture cannot appear in an audit trail looking like a person, and a
person cannot be handed a fixture's id.

**None of these names belongs to anyone.** `TEST-curator-1` read no evidence.
`TEST-reviewer-1` checked nothing. They are the smallest thing that makes the
state machine exercisable at all, given that the successful path has to be
testable and the real world offers no approved protocol to test it against.

The offline CLI can load a role file, and refuses one naming any actor without
the `TEST-` prefix: assigning a role to a named person is authentication, and
a JSON file is not an authentication system.

## 6. What is still missing

| Missing | Owner |
|---|---|
| Authenticated identities | WP-23 |
| Binding a person to a role | WP-23 |
| A named expert approving the protocol | a scientist, not code |
| Two named curators completing the WP-09 exercise | scientists, not code |

Until the first two exist, every role in the matrix above is a design, and
every real workflow operation in this repository fails before it reaches the
state machine.
