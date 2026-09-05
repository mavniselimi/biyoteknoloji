# WP-17 — WCAG 2.1 AA structural baseline

## What this document claims, and what it does not

**Claims:** every item marked ✅ below is asserted by a test that renders the
real templates and parses the real HTML. Jinja2 is installed in the environment
this was built in, so those tests execute on every run — they are not skipped
and they are not aspirational.

**Does not claim:** that this interface has been audited, that it has been
tested with a screen reader, or that its contrast ratios have been measured.
Every item still marked ⚠️ is a real WCAG requirement that needs more than a
browser, and it is listed rather than omitted so the gap stays visible.

The structural tests are in `tests/unit/web/test_accessibility.py` (29 tests)
and run wherever the templates render. The behavioural ones are in
`tests/integration/web/test_browser_e2e.py` and **have now run in a real
browser** — see the second table below.

## Structure — verified

| # | Requirement | Status | Test |
| --- | --- | --- | --- |
| 1.3.1 | Every page has `header`, `nav`, `main`, `footer` landmarks | ✅ | `test_every_page_has_the_document_landmarks` |
| 1.3.1 | Exactly one `h1` per page | ✅ | `test_every_page_has_exactly_one_h1` |
| 1.3.1 | The `h1` is the first heading in source order | ✅ | `test_the_h1_is_the_first_heading` |
| 1.3.1 | No heading level is skipped | ✅ | `test_no_heading_level_is_skipped` |
| 1.3.1 | No heading is empty | ✅ | `test_no_heading_is_empty` |
| 1.3.1 | Every table has a `caption` | ✅ | `test_every_table_has_a_caption` |
| 1.3.1 | Every table header cell declares `scope` | ✅ | `test_every_table_has_header_cells_with_a_scope` |
| 1.3.1 | Medication selection uses `fieldset` + `legend` | ✅ | `test_the_medication_selection_uses_a_fieldset_and_legend` |
| 2.4.1 | Skip link, first in the document, targeting `#main` | ✅ | `test_every_page_has_a_skip_link_targeting_main` |
| 2.4.4 | No link text is "here", "click", "more" or a bare URL | ✅ | `test_every_link_has_meaningful_text` |
| 2.4.8 | Navigation marks the current page with `aria-current` | ✅ | `test_the_navigation_marks_the_current_page` |
| 1.3.1 | The navigation landmark is named | ✅ | `test_the_navigation_landmark_is_named` |
| 3.3.2 | Every form control has an associated label | ✅ | `test_every_form_control_is_labelled` |
| 3.3.2 | A disabled control states why it is disabled | ✅ | `test_a_disabled_control_explains_itself` |
| 3.1.1 | `lang` is declared on `html` | ✅ | rendered by `base.html`, asserted in `test_pages.py` |
| 1.4.10 | The stylesheet declares a narrow-viewport layout | ✅ | `test_the_stylesheet_declares_a_narrow_viewport_layout` |
| — | Every page declares a viewport meta | ✅ | `test_every_page_declares_a_viewport` |

## Not colour alone — verified

| # | Requirement | Status | Test |
| --- | --- | --- | --- |
| 1.4.1 | Every status renders its governed code **and** its label as text | ✅ | `test_every_status_pair_shows_both_code_and_label` |
| 1.4.1 | Readiness states are words, not colours | ✅ | `test_readiness_states_are_words_not_colours` |
| 1.4.1 | No stylesheet rule encodes a status by hue alone | ✅ | `test_the_stylesheet_never_encodes_a_status_by_colour_alone` |
| — | `NO_ACTIVE_ATTENTION` is not styled as success | ✅ | `test_no_active_attention_is_not_styled_as_success` |

## Motion, focus and print — verified structurally

| # | Requirement | Status | Test |
| --- | --- | --- | --- |
| 2.3.3 | `prefers-reduced-motion` is honoured | ✅ | `test_the_stylesheet_honours_reduced_motion` |
| 2.4.7 | No rule removes a focus outline | ✅ | `test_focus_is_never_removed` |
| — | The clinical warning survives printing | ✅ | `test_the_warning_survives_printing` |

## Without JavaScript — verified

| # | Requirement | Status | Test |
| --- | --- | --- | --- |
| — | No page requires a script to show its content | ✅ | `test_no_page_requires_a_script_to_show_its_content` |
| — | The only script is local and deferred | ✅ | `test_the_only_script_is_deferred_and_local` |
| — | Governed facts are present as text, not injected | ✅ | `test_every_page_still_carries_its_governed_facts_as_text` |

## The status pair — verified structurally

| # | Requirement | Status | Test |
| --- | --- | --- | --- |
| 1.3.2 | Attention and coverage are consecutive in source order | ✅ | `test_they_are_consecutive_in_source_order` |
| 1.3.1 | The two halves of each pair sit at the same depth | ✅ | `test_the_two_halves_of_each_pair_sit_at_the_same_depth` |
| — | Neither half is inside a collapsible region | ✅ | `test_neither_is_inside_a_collapsible_region` |

## Verified in a real browser

Chromium 141.0.7390.37, launched by Playwright, driving pages served by Uvicorn
on loopback. `tests/integration/web/test_browser_e2e.py`, 11 passing tests.

| # | Requirement | Status | Test |
| --- | --- | --- | --- |
| 1.4.4 | The status pair survives a 640×480 viewport with both halves intact | ✅ | `test_the_status_pair_stays_together_at_200_percent_zoom` |
| 2.1.1 | Every interactive element is reachable by keyboard | ✅ | `test_every_interactive_element_is_reachable_by_keyboard` |
| 2.1.2 | Tabbing does not trap focus | ✅ | the same test — focus keeps moving through the full set |
| — | The warning is visible in a 1280×800 viewport without scrolling | ✅ | `test_the_warning_is_visible_without_scrolling` |
| — | The warning cannot be dismissed at runtime | ✅ | `test_the_warning_cannot_be_dismissed` |
| — | The page is usable with JavaScript disabled | ✅ | `test_the_page_works_with_javascript_disabled` |
| — | The page requests nothing from a remote origin | ✅ | `test_the_page_requests_nothing_from_a_remote_origin` |
| — | No console error and no page error | ✅ | `test_the_console_is_clean` |

Seven full-page captures are in `tests/fixtures/wp17/browser/`. They are real
browser captures, written during that run; see
`docs/evidence/wp17-ui-verification.md`.

## Still NOT verified, and what each would need

| # | Requirement | Status | What it needs |
| --- | --- | --- | --- |
| 1.4.3 | Contrast ratio ≥ 4.5:1 for body text, ≥ 3:1 for large text and UI borders | ⚠️ | a measuring tool; the hex values were chosen against the thresholds arithmetically and have not been measured |
| 1.4.11 | Non-text contrast for borders and focus indicators | ⚠️ | the same |
| 2.4.3 | Focus order follows meaning | ⚠️ | a human reading the order; reachability is verified, *sequence* is a judgement |
| 2.4.7 | The focus indicator is visibly distinguishable | ⚠️ | a measuring tool or a human; that it is declared and never removed is verified structurally |
| 4.1.2 | Assistive technology announces the status pair as one unit | ⚠️ | a screen reader. No automated substitute exists, and none is claimed |
| — | WCAG 2.1 AA conformance as a whole | ⚠️ | an audit. Nothing in this repository is one |

## Running them yourself

```
pip install -e '.[web]' --group dev
playwright install chromium
python -m unittest tests.integration.web.test_browser_e2e
```

`TestTheBrowserRuntimeIsReportedHonestly` in that module never skips on a host
with no browser: it fails if an image is committed while nothing could have
produced it, and if the gate status disagrees with the host about whether a
browser can be launched.
