# Source conflict policy

| Field | Value |
|---|---|
| Document ID | `DOC-SCI-004` |
| Work package | WP-05 |
| Machine-readable form | `config/scientific-sources.json`, `conflicts[]`; `pgx/scientific/conflict.py` |
| Status | **No conflicts recorded. No sources are approved, so none can yet disagree in published output.** |

> This document defines minimal source-conflict behaviour: detect, record,
> block. It contains no precedence rule, and adding one would be a change to
> the project's scientific position, not a refactor.

---

## 1. What counts as a conflict

Two or more **registered** sources making incompatible statements about the
same subject - a gene/drug pair, an allele's function, a diplotype-to-phenotype
mapping.

Not a conflict: a parsing bug, a data-quality problem, a missing value, or two
sources describing different things. A conflict between sources this project
has no policy for is a registry gap, and `SourcePolicyRegistry` refuses to hold
one, so the gap is reported as what it is.

## 2. Detection is narrow and mechanical

`detect_conflicts` compares statements the caller has already extracted and
normalised. It performs no interpretation of scientific text.

- Two sources whose normalised values are equal produce nothing.
- Two sources whose normalised values differ produce one `OPEN` conflict with
  materiality `UNDETERMINED`, naming every source involved.
- One source making two different statements about the same subject is also a
  conflict. A source that contradicts itself is not one this project can cite
  without somebody looking.

Whatever normalisation the caller applied is the normalisation that decides
whether two sources disagree, and it is visible in the `SourceStatement`
records rather than buried in a comparison function.

Detection is deterministic: subjects are processed in sorted order, source keys
are sorted inside each record, and the conflict key is built from the subject
plus the sorted keys. The same disagreement discovered twice produces one
record, and `alpha` disagreeing with `beta` is the same conflict as `beta`
disagreeing with `alpha`.

## 3. There is no precedence rule

**This project has no rule that CPIC outranks DPWG, that a regulator label
outranks a guideline, or that the newest publication supersedes the older one.**

There is no precedence table, no ranking function, no merge, and no "prefer"
helper anywhere in `pgx/scientific`. A test reads the module's identifiers and
fails if one appears, and a second test fails if any real source body is named
in the module at all - because a precedence rule hidden as a constant would
have to name one.

The reason is not neutrality for its own sake. A global precedence order
silently answers every future disagreement, including ones nobody has looked
at, using a judgement made once in a different context. Which statement
prevails is a scientific decision about a specific disagreement, and it is
recorded as one.

## 4. Lifecycle

| Status | Meaning | Blocks? |
|---|---|---|
| `OPEN` | Recorded; nobody has looked | Yes, if material or undetermined |
| `UNDER_REVIEW` | A named reviewer is working on it | Yes, if material or undetermined |
| `RESOLVED` | A named reviewer decided how it is handled | No |
| `ACCEPTED_VARIANCE` | A named reviewer decided the disagreement may stand, with a reason | No |

| Materiality | Meaning | Blocks while unsettled? |
|---|---|---|
| `MATERIAL` | Could change what the system outputs | Yes |
| `NON_MATERIAL` | Somebody judged it cannot | No |
| `UNDETERMINED` | Nobody has judged | **Yes** |

`UNDETERMINED` blocks alongside `MATERIAL`. Deciding that a disagreement does
not matter is itself a review decision, and until somebody makes it the system
must assume it could change output.

## 5. Settling a conflict

A conflict is settled only by a `ConflictResolution` carrying:

- `decision_summary` - what was decided;
- `rationale` - why;
- `decided_by` - a named human;
- `decided_at` - when;
- `preferred_source_key` - optional, and if given it must be one of the sources
  actually in conflict.

A status of `RESOLVED` or `ACCEPTED_VARIANCE` without a resolution is refused,
and a resolution attached to an unsettled status is refused too - a decision
hidden behind the wrong status is worse than no decision. Both rules hold in
the model and as check constraints in migration `0003`.

**Deleting a conflict is not resolving it.** `ConflictRegister` is immutable
and offers no `remove`, `delete`, `discard`, `pop` or `clear`. A settled
conflict is a new record carrying its resolution.

## 6. Blast radius

An unresolved conflict blocks only the sources it names. A dataset citing A and
B is not held up by a disagreement between C and D. `ConflictRegister.
blocking_for` and `ReleaseService._check_source_policy` both scope by the
sources actually cited.

## 7. Where conflicts surface

| Surface | Behaviour |
|---|---|
| `pgx-source-policy validate` | `CONFLICT_UNRESOLVED`, `CONFLICT_MATERIALITY_UNDETERMINED` |
| `pgx-source-policy evaluate-publication` | Verdict `BLOCKED` for a dataset citing an involved source |
| Release activation | `CompatibilityCode.SOURCE_CONFLICT_UNRESOLVED` |
| Database | `source_conflicts`, with the settled/unsettled check constraints |

## 8. What this does not cover

Detecting conflicts requires normalised statements to compare, and producing
those is canonical resolution and curation - WP-07 and WP-09 onward. WP-05
supplies the model, the detector and the gate; nothing in this repository
currently feeds them, because no source is approved and no dataset is built.
