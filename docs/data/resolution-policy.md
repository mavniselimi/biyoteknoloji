# Resolution policy (WP-07)

How a submitted value becomes a canonical entity, and what happens when it
cannot.

## 1. The five stages, in order

`pgx-resolver/1`. The order is fixed by `architecture.md` 8.3.

1. Exact canonical **external ID**, namespaced.
2. Exact normalised **preferred name** or gene symbol.
3. Exact **APPROVED alias**.
4. Unique exact external **cross-reference** — a bare value in any namespace.
5. **Unresolved**, into the review queue.

At every stage there are exactly three outcomes and no fourth:

| Candidates | Result |
| --- | --- |
| 0 | advance to the next stage |
| 1 | `RESOLVED`, stop |
| 2 or more | `AMBIGUOUS`, stop **immediately** |

## 2. Why an ambiguity stops the search

A later stage never runs after an earlier one found an ambiguity. If two genes
share an approved alias (stage three is ambiguous) and only one of them happens
to carry that string as an external value (stage four would be unique), a
resolver that carried on would "resolve" a genuine collision by coincidence.

A test constructs exactly that catalog and asserts the resolver stops at stage
three with both candidates attached.

## 3. What an ambiguous outcome carries

**Every** candidate, not a selection from them. `ResolutionOutcome` refuses to
be constructed as `AMBIGUOUS` with fewer than two candidates, and refuses to be
constructed as `RESOLVED` while carrying candidates it did not choose — that
would be a silent selection wearing a resolution's clothes.

The database says the same thing:
`ck_resolution_queue_items_ambiguity_has_candidates` requires
`jsonb_array_length(candidate_keys) >= 2`.

## 4. What the resolver will never do

Each absence is enforced by a test that reads the module's AST:

- rank candidates, or score them;
- return `results[0]`, the earliest-created row, the smallest UUID, the
  alphabetically first name, or the highest source score;
- match on a substring, an edit distance, a phonetic key or an embedding;
- resolve through an alias that is merely observed rather than approved;
- mint an identity for something it could not find;
- write anything at all — `resolve` reads a catalog and returns a record.

The single-candidate branch **unpacks** rather than indexes:
`(only_candidate,) = candidates`. That raises if the length guard above it is
ever weakened, which is the exact edit that would reintroduce the legacy
`results[0]` defect. An index would keep working and quietly pick a winner.

## 5. The catalog shape

`CanonicalCatalog` builds every index eagerly and every index maps a key to a
**sorted tuple of canonical keys**, never to a single entity. A lookup that
returned one entity would have had to choose between two, and there is nowhere
in the class where such a choice could be made visible.

The indexes are eager so that "two entities share this name" is a fact about
the catalog rather than a race between two queries.

## 6. Outcome vocabulary

| Status | Meaning |
| --- | --- |
| `RESOLVED` | exactly one canonical entity matched |
| `AMBIGUOUS` | more than one matched at some stage; every candidate is carried |
| `UNRESOLVED` | nothing matched at any stage |
| `INVALID_INPUT` | the value could not be normalised at all |
| `BROKEN_REFERENCE` | a relationship names an entity the dataset does not contain |

`UNRESOLVED` and `BROKEN_REFERENCE` are genuinely different findings: an unknown
value submitted for lookup is a gap, whereas a relationship pointing at an
absent entity is a broken graph. A broken reference never creates the entity it
names.

`ReasonCode` is a stable closed vocabulary. Renaming one is a breaking change.

## 7. The review queue

Every outcome that is not `RESOLVED` becomes one queue item, undecided. WP-07
creates **no** decisions: `decided_by` is `None` on every item a build produces,
and there is no argument that would change that.

A decision, when a human eventually records one, requires a named reviewer, an
instant and a rationale — all three, or the item stays undecided — and may only
choose a key that was actually among the candidates. Both rules are enforced in
the dataclass and again in the database
(`ck_resolution_queue_decision_is_complete`,
`ck_resolution_queue_choice_was_a_candidate`). `chosen_canonical_key` may be
`NULL`: "none of these" is a real answer.

An item whose candidate set later narrows to one is still unresolved, because
nobody chose.

## 8. Ambiguity stays storable

`gene_aliases` and `drug_aliases` keep their `0001` composite primary key
`(gene_id, normalized_alias)`. No globally unique constraint on the alias alone
is added, in `0005` or anywhere else. The same alias may legitimately belong to
two genes, and a constraint that refused to store that would not remove the
ambiguity — only this project's ability to see it.

`GeneRepository.find_by_alias` has returned a `Sequence` since WP-02 for the
same reason, and `AliasReviewRepository.find_by_alias` does too.

## 9. Observed on the real snapshot

All 29 gene and drug references from the 13 pair queries resolve at stage two.
The resolution queue is empty, and no alias is approved because nobody has
approved one.
