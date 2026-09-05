# Open blockers

**45 blockers across six gates, owned by 12 distinct roles.**

| Gate | Blockers |
|---|---|
| A — Scientific Data | 5 |
| B — Rules | 7 |
| C — Core Safety | 9 |
| D — Validation | 9 |
| E — Operational | 10 |
| F — THS 6 | 5 |

## By owner

| Owner | What they are blocking |
|---|---|
| scientific source approver | no source has been approved (A1) |
| data owner | dataset unpublished, snapshot incomplete and quarantined (A2, A3, A4) |
| curation lead | evidence build unapproved; no curated interpretation, approved rule, executable ruleset; 33 unlinked legacy candidates; no assessment, coverage execution or report (A5, B2–B7, C1–C4) |
| expert reviewer | curation protocol unapproved (B1) |
| safety owner | the safety gate reports BLOCKED (C5, F3) |
| platform owner | no CI run, no API assessment, no database, no migration, no audit chain, no restore, no container runtime, no staging (C6, C9, E2–E5, E7–E9) |
| clinical safety authority | the claim boundary is a draft (C7) |
| release approver | no active release; the release validation forbids proceeding (C8, F1, F2) |
| validation owner | zero validation cases, no holdout set, no computed metric, no benchmark run (D1–D5) |
| expert review chair | no protocol signatory, no named reviewer, no completed review (D6–D9) |
| security owner | the security gate reports BLOCKED (E1) |
| verification owner | the recorded verification run is stale (F5) |

No blocker is owned by "the team". A blocker whose owner is unnamed is one
nobody clears, and the `Blocker` type refuses to be constructed without one.

## The shape of the dependency

Nothing downstream of Gate A can move until a source is approved. B needs A,
C needs B, D needs C, E is independent of A–D and blocked on infrastructure,
and F needs all five.

The two roles that unblock the most are the **scientific source approver**
(one approval starts the whole scientific chain) and the **platform owner**
(a database and a CI provider clear most of Gate E and two of Gate C).

## The one blocker with no scientific or human dependency

`THS6_LEGACY_WORK_ITEMS_UNLINKED` (B7): 33 legacy rule candidates remain
unlinked to governed work items. Clearing it needs somebody to work through
33 items and either link each or record why it is not a rule candidate. It is
the smallest open item in the programme and it is still not code.

## What is not a blocker

The absence of a container runtime, a package index, a PostgreSQL server and
an argon2 package in *this* environment is recorded as an observation, not as
a defect in this software. Those absences make several conditions
unevaluable; they are not evidence that the software would fail with them
present. Equally, their presence would not by itself satisfy any condition —
it would allow the conditions to be *evaluated*.
