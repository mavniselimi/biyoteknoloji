# Gate B — Rules

**Result: BLOCKED.** 0 of 7 mandatory conditions met. 7 blockers.

`architecture.md` §20: *approved curation protocol, validated/frozen ruleset,
complete approval metadata.*

| # | Condition | Field in `data/rulesets/wp11-real-gate-status.json` | Required | Observed |
|---|---|---|---|---|
| B1 | the curation protocol is approved | `upstream_state.curation_protocol_approved` | true | false |
| B2 | at least one interpretation is curated | `curation_state.curated_interpretations` | ≥ 1 | 0 |
| B3 | at least one rule approval envelope is eligible | `curation_state.eligible_rule_approval_envelopes` | ≥ 1 | 0 |
| B4 | at least one rule is validated | `rule_state.real_validated_rules` | ≥ 1 | 0 |
| B5 | at least one ruleset is frozen | `rule_state.real_frozen_rulesets` | ≥ 1 | 0 |
| B6 | the default registry holds an executable ruleset | `rule_state.executable_rulesets_in_default_registry` | ≥ 1 | 0 |
| B7 | no legacy rule candidate is unlinked | `curation_state.unlinked_work_items` | 0 | 33 |

## Blockers and owners

| Code | Owner |
|---|---|
| `THS6_CURATION_PROTOCOL_NOT_APPROVED` | expert reviewer |
| `THS6_NO_CURATED_INTERPRETATION` | curation lead |
| `THS6_NO_APPROVED_RULE` (×2) | curation lead |
| `THS6_NO_EXECUTABLE_RULESET` (×2) | curation lead |
| `THS6_LEGACY_WORK_ITEMS_UNLINKED` | curation lead |

## What exists

The curation protocol document, the field dictionary, the role matrix, the
approval gates, the review checklist, the inter-curator exercise structure,
the work-item model, the rule condition language, the approval envelope
schema, the ruleset build machinery and a real build attempt that ran and
correctly produced nothing.

1,559 legacy work items were allocated; 1,526 are linked and 33 are not.

The protocol's status is `AWAITING_EXPERT_REVIEW`. Everything downstream of it
is zero, and that is the correct behaviour of a system that refuses to build
rules from unapproved content rather than a failure of the build.

## B7 is the only condition a person could clear without a scientific decision

The other six need an approved protocol and curated content. B7 needs somebody
to work through 33 legacy candidates and either link each to a governed work
item or record why it is not a rule candidate. It is the smallest piece of
Gate B and it is still not code.
