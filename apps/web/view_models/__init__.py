"""Immutable presentation models. They add labels; they decide nothing.

Every model here is frozen, and every one is built from a document the client
already validated against the WP-16 contract. What a view model may add is a
closed list:

- a controlled label for a governed code, from the one label table;
- a display value, escaped and length-checked;
- layout grouping, such as pairing an axis with its findings;
- a navigation URL, built from the route table;
- accessibility text;
- fixed presentation metadata.

What a view model may not do is a longer list, and each item is a way a screen
could quietly become a second opinion:

- recompute attention or coverage;
- count findings to infer severity;
- select a worst or most important medication;
- reorder medications by status, attention or finding count;
- omit a reason code, a conflict reference or an evidence reference;
- replace a governed code with its label - both are shown, always;
- infer an effect or explanation code that the outcome left absent;
- generate a clinical sentence of any kind.

:mod:`apps.web.view_models.preservation` makes the first four mechanically
checkable: it projects the same protected facts out of the API response and
out of the built view model and refuses to render if they differ. That check
runs on every assessment page, not only in tests, because a presentation bug
that drops a reason code produces a page that looks finished.
"""
