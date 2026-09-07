# 11. Rule and release lineage

Every assessment the software returns can be walked back to a manually
downloaded guideline document, and the interface shows the walk.

## The chain

```
manual download of an approved source document
        │
        ▼
capture row              id: capture:row:CYP2C19|clopidogrel|
        │                    CYP2C19 intermediate metabolizer|ACS and/or PCI
        │                snapshot manifest sha256:4075ce58…8210d4
        ▼
canonical dataset        PGX-DATA-20260906-001
        │                build hash sha256:9c0ebc65…d3c0d
        │                DQ decision DQD-2710a01c386e9a1885f62a8e
        │                            ACCEPTED_FOR_CANDIDATE_USE
        ▼
interpretation           CANDIDATE-INTERP:clopidogrel|CYP2C19|INTERMEDIATE
        │                hash sha256:b50448bd…5d43d
        │                citation PMID 35034351, DOI 10.1002/cpt.2526
        │                annotation PA166104948
        ▼
candidate rule           CANDIDATE-RULE:clopidogrel|CYP2C19|INTERMEDIATE
        │                hash sha256:a61004f8…9ad5b9
        │                joint: false   care setting: ACS_OR_PCI
        ▼
frozen candidate ruleset PGX-CANDIDATE-RULESET-WAVE03B
        │                content hash sha256:29ca1949…c7c71a
        │                26 rules · 12 joint · 13 recorded refusals
        ▼
active candidate release PGX-CANDIDATE-REL-20260906-001
        │                manifest hash sha256:0cd22a88…581d01
        │                authority PROJECT_TEAM_PROVISIONAL
        │                review    PENDING_EXTERNAL_EXPERT_REVIEW
        │                modes     DEMO, VALIDATION   (PILOT prohibited)
        ▼
assessment shown to the user
```

## What the interface shows, per finding

The release identifier, the ruleset key and content hash, the matched rule key
and its content hash, whether the rule was joint or single-gene, the
interpretation key, the citations, the capture record identifiers, the
authority state, the review state, and the refusal list for anything that was
not answered.

## What is *not* in the chain, and would be in a governed one

- **No WP-10 curation approval envelope.** No approving curator exists.
- **No WP-11 registered ruleset.** `is_governed_ruleset: false`.
- **No WP-13 governed release registration.** The release is not in the
  registry and the governed active-release pointer does not exist. It was not
  written, and this wave did not write it.
- **No `SOURCE_APPROVED` authority.** Rules stop at
  `SOURCE_GROUNDED_INTERNAL_DECISION`.
- **No approving human at any step.** The one human attestation this project
  holds covers the source policy and explicitly does not cover any generated
  rule (section 4).

The lineage is complete and it is entirely internal. Every hash in it proves
that a thing did not change. None of them proves that the thing was right.
