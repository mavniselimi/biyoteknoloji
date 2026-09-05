# WP-18 — Holdout separation policy

`SAFETY-INV-009`: once a holdout case informs development, the metric it later
produces measures memory rather than generalisation, and no analysis afterwards
undoes it.

That is why role is immutable, why relabelling is refused rather than logged,
and why the checks below are mechanical.

## The eight refusals

| Code | Catches |
| --- | --- |
| `ROLE_OVERLAP` | one identifier under more than one role |
| `CONTENT_DUPLICATE_ACROSS_PARTITIONS` | copy-and-rename: different identifiers, same canonical content |
| `CONTENT_DUPLICATE_WITHIN_PARTITION` | a denominator counting one case twice |
| `DERIVATION_FAMILY_SPLIT` | one source vignette worked twice, split across the line |
| `HOLDOUT_DERIVED_FROM_DEVELOPMENT` | a holdout whose author declares a development source |
| `DEVELOPMENT_RELABELLED_AS_HOLDOUT` | a case that was development yesterday |
| `HOLDOUT_PROVENANCE_MISSING` | independence that cannot be shown |
| `RELEASE_COMPATIBILITY_CONFLICT` | cases in one partition written against different pinned versions |

Reported **together**, as a list, by `audit_partition`. Somebody repairing a
dataset wants every problem at once, not a sequence of round trips.
`require_separation` raises instead, for write paths, where continuing past a
fault would write the fault to disk.

## Why four of these are not redundant

A naive check finds only the first. Consider what each of the next three sees
that the ones before it do not:

- Same content under a fresh identifier — rule 1 sees nothing; rule 2 does.
- Different content, one vignette, one method — rules 1 and 2 see nothing;
  rule 4 does. This is the important one, because it is what happens when a
  curator works from a source a rule author has already read.
- A case relabelled last week — nothing in a single snapshot distinguishes it
  from a case that was always a holdout. Rule 6 needs a previous
  `{case_id: role}` record and cannot work without one.

## Deduplication does not use names

Not filenames, not display titles, not case identifiers. A holdout copied from
a development case gets a fresh identifier *precisely because* somebody meant
it to look new, and two curators writing up one source will not type the same
title.

It uses canonical content, and it is careful in both directions. Merging two
genuinely different cases would hide one of them, which is worse than counting
one twice — so normalisation removes only differences that carry no scientific
meaning, and every scientific difference is tested to change the fingerprint.

## Visibility

| | Development | Internal holdout | Expert holdout |
| --- | --- | --- | --- |
| Metadata | visible | visible | visible |
| Payload, rule-authoring context | visible | **refused** | **refused** |
| Payload, validation run | visible | visible | **refused** |
| Payload, expert review | visible | visible | **refused until WP-22** |

Metadata is visible to everybody because a manifest publishes it anyway;
hiding a case's existence would not hide anything.

Expert-holdout payloads are refused to *every* context, including an expert.
Releasing one is the protocol WP-22 owns and it is not implemented.

## Who has seen what

Every attempt appends one event: case, actor, declared context, action,
allowed, reason code, timestamp, case role, manifest hash. Refusals included.

The actor is a **claim**. Every event carries `actor_authenticated: false`, the
schema pins it with `const`, and no code path sets it true. WP-23 owns
identity, and recording an unverified name as verified would put a lie in an
audit trail that later reads as a fact.

Append-only is enforced, not documented: no method replaces or removes an
event, `events()` returns a tuple, and each entry chains the digest of the
previous one so an edit breaks the chain at that index.

## Refusals leak nothing

The access decision never consults whether a payload exists. The loader is not
called when a read is refused. The error carries a coarse reason code and the
case identifier. There is no call that lists cases across partitions, because a
count spanning both would measure how many answers exist and let anybody watch
that number move.

## Restricted payloads are not committed here

An expert payload committed beside the rules it tests would defeat the whole
arrangement. Payloads live in restricted storage a deployment configures
through `PGX_VALIDATION_RESTRICTED_ROOT`. Nothing in this repository points at
one, and a test asserts that `data/holdout`, `data/validation/expert`,
`data/validation/restricted` and `data/validation/payloads` do not exist.
