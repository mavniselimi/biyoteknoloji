# WP-17 — Visual system

257 lines of hand-written CSS and 68 lines of hand-written JavaScript, both
served from `apps/web/static/`. No framework, no bundler, no CDN, no remote
font, no icon set, no build step.

## The constraint the design is built around

This interface displays a **research/prototype** output that is explicitly not
a clinical decision. The one failure mode worth designing against is a screen
that *looks* like a product which has already decided something. So:

- **No green anywhere.** `tests/unit/web/test_safety.py` scans the stylesheet
  (comments stripped, so an explanatory comment does not trip it) and fails on
  a green hue. Green reads as "cleared", and nothing in this system clears
  anything.
- **No styling that marks the absence of attention as good.**
  `NO_ACTIVE_ATTENTION` has no rule of its own. It is a governed code with a
  governed label, rendered the same way as every other, because "no active
  attention finding" is not the same statement as "safe" and the interface must
  not make it look like one.
- **Every status rule changes a border, not only a hue.** Colour is never the
  sole carrier of a status: each status renders its governed code as text, its
  label as text, and a border treatment. The page is readable in greyscale, and
  it is readable with the stylesheet switched off entirely.

## Palette

Eight ink and paper tokens, one accent, two status marks, one blocked state.
All defined once, at `:root`, in `apps/web/static/css/app.css`.

| Token | Value | Used for |
| --- | --- | --- |
| `--ink` | `#16191d` | body text |
| `--ink-muted` / `--ink-faint` | `#4a5058` / `#6b7280` | secondary and tertiary text |
| `--paper` / `--paper-sunken` | `#ffffff` / `#f4f5f7` | page and inset backgrounds |
| `--rule` / `--rule-strong` | `#cfd4da` / `#9aa1aa` | separators |
| `--accent` / `--accent-soft` | `#1f3a5f` / `#e8edf4` | links, focus, skip link |
| `--attention-mark` | `#6b4d00` | the attention half of a status pair |
| `--coverage-mark` | `#123c4a` | the coverage half |
| `--blocked` / `--blocked-soft` | `#7a1f1f` / `#fbeaea` | unavailable, refused, error |

The two status marks are deliberately *different in hue from each other and
neither of them alarming*. Attention findings are not warnings; coverage is not
a score.

## Type and measure

A system font stack (`-apple-system`, `Segoe UI`, `Roboto`, …, `sans-serif`)
and a system monospace stack, both ending in a generic family, so no font file
is ever fetched. Body copy is capped at `--measure: 68ch`. Governed codes,
hashes and identifiers are always monospace, and always shown in full — a
truncated hash is a hash nobody can check.

## Spacing

Five steps, `0.25rem` to `2.5rem`, all in `rem` so they scale with the reader's
own text size. No fixed pixel heights on anything that holds text.

## Focus

`:focus-visible` gets a 3px solid outline in the accent colour with an offset,
and there is no rule anywhere that removes an outline. A skip link precedes
every page's content.

## Motion

One `@media (prefers-reduced-motion: reduce)` block that removes the handful of
transitions. There is no animation that conveys state.

## Print

`@media print` keeps the clinical warning visible and expands link targets. A
page printed from this interface must not lose the sentence that says what it
is — printing is exactly when a screen becomes a document someone hands to
somebody else.

## JavaScript

`apps/web/static/js/app.js` is progressive enhancement only: the page is fully
usable with scripts disabled, and the script adds no information the server did
not already render. It uses `textContent` and never `innerHTML`,
`XMLHttpRequest`, `fetch`, `WebSocket`, `eval` or `document.write` — asserted
by `tests/unit/web/test_security.py`, which strips comments before scanning so
that a comment *naming* a forbidden API does not pass or fail the check by
accident.

The claim gate refuses any inline script, any `on*` attribute and any inline
`style` attribute in rendered HTML, so this file is the only script the
interface can run.

## What has not been verified

**Nobody has looked at this in a browser.** There is no browser binary and no
browser automation package in the environment this was built in, so every claim
on this page about how it *looks* — the contrast of those hex values, whether
the status pair holds together at 200% zoom, whether the focus ring is visible
against the accent background — is **UNVERIFIED**. The contrast ratios were
chosen against WCAG's thresholds arithmetically and have not been measured by a
tool. `tests/integration/web/test_browser_e2e.py` contains the tests that would
verify them, written and skipped.
