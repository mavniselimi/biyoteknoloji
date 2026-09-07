# 3. Scientific source strategy

Full detail: `docs/scientific/source-strategy.md`,
`docs/scientific/source-conflict-policy.md`,
`docs/scientific/licensing-and-reuse-matrix.md`.

## The sources actually used in this release

Four, and only four, carry an `APPROVED_WITH_RESTRICTIONS` status:

| Source key | What it is | Permitted here |
|---|---|---|
| `cpic.database` | CPIC's own dataset | manual download, internal derivation |
| `cpic.publications` | CPIC guideline papers | manual download, citation, manual review |
| `clinpgx.website` | ClinPGx web content | manual download, internal derivation |
| `dpwg.knmp` | DPWG official publications | manual download, citation, manual review |

The rules in this release cite CPIC guideline material and ClinPGx annotation
identifiers. Each rule names its own citation — for example
`PMID 35034351, DOI 10.1002/cpt.2526` — and its source annotation identifier,
in `data/candidate-rulesets/PGX-CANDIDATE-RULESET-WAVE03B/rules.ndjson`.

## The sixteen sources deliberately not used

Every other source in the registry sits at `PENDING_REVIEW` and contributes
nothing: FDA and TITCK drug labels, EMA, Health Canada, PMDA, Swissmedic, AHA,
AusNZ, CPNDS, RNPGx, PubMed literature at large, the ClinPGx API, the CPIC
API, and three internal legacy stores.

Two of those deserve a note, because their absence is easy to misread:

- **FDA and TITCK were deferred, not consulted and found silent.** The H01
  decision states explicitly that deferring them may not be treated as
  evidence that a first-release axis is regulator-supported. No rule in this
  release makes an FDA-supported claim.
- **The CPIC and ClinPGx APIs are prohibited**, not merely unused. Their
  service terms were not established, and the source policy refuses automated
  acquisition under unknown terms. Every row in this dataset was entered by
  hand from a manually downloaded document.

## How acquisition is constrained

The approved modes are `MANUAL_DOWNLOAD` and `INTERNAL_DERIVATION`. Scraping,
crawling, bulk download, automated acquisition of any kind, and verbatim
redistribution of publication or label full text are all prohibited. That is
why this repository contains normalised derived rows and citations rather than
guideline text.

## What that means for the science

The scope is small because the acquisition method is slow and manual, not
because the small scope was judged scientifically sufficient. Whether four
drugs and two genes is a defensible first release at all is question **Q03** in
section 16.

## Source conflict

Where two approved sources disagree, the engine does not choose. If more than
one rule matches an observation the axis returns `SOURCE_CONFLICT` with
`VALIDATED_RULES_CONFLICT` and no attention level. In this release no such
conflict is currently reachable — the twenty-six rules are mutually exclusive
by construction — so the behaviour is implemented and untested by real
disagreement. Whether the policy is right, and whether "refuse" is the right
answer rather than "prefer the more conservative source", is question **Q04**.
