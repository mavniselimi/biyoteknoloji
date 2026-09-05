# -*- coding: utf-8 -*-
"""A minimal internal curation console, as pure functions (WP-10).

No web framework, no server, no socket. A handler takes a request mapping and
returns a ``FormResponse``; rendering a page is a function from data to a
string. Whatever eventually serves this - WP-16's API, a local script, nothing
at all - is somebody else's decision, and making it here would be inventing the
web layer a work package away from where it belongs.

What the console has to get right, and why:

**Source text and curator text never share a visual channel.** A curator
reading a page must be able to tell what a source said from what a colleague
concluded. Here they are different blocks, with different labels and different
styling, and the source block is marked as unreviewed input. A console that
blurred the two would let a curator adopt an upstream claim believing a
colleague had already checked it.

**Everything is escaped.** Source text arrives from files this project did not
write. It is escaped on the way out - once, at render time, in one function -
and no template interpolates raw text anywhere.

**GET-like handlers never mutate.** The read handlers are literally incapable
of it: they receive a read-only façade over the service exposing only
``gate_status`` and ``history``. That is structural rather than disciplined; a
mutating call in a read handler is an ``AttributeError``, not a code review
finding.

**Every mutating form carries the version it was rendered from.** A curator who
opened a page, went to lunch and came back submits the version they saw, and
the service refuses it if the world moved. A form without that field is
rejected here rather than defaulted, because a default would silently mean
"whatever it is now".

**The form supplies no role field.** There is no widget for it, no accepted
parameter and no default. The actor id goes to the injected RoleProvider and
whatever that says is what the actor may do. A form that posted its own roles
would be an authentication system, and a bad one.

**Approval disappears when the gates are shut.** Not disabled with a tooltip -
absent, and replaced by the list of blockers with the owner of each. Against
this repository that is what every real work item shows.
"""

from __future__ import annotations

import html as _html
from dataclasses import dataclass, field
from typing import (Any, Callable, Dict, List, Mapping, Optional, Sequence,
                    Tuple)

from pgx.curation.vocabulary import ConflictState
from pgx.curation.workflow.errors import WorkflowError
from pgx.curation.workflow.models import ReviewDecision
from pgx.curation.workflow.policy import GATE_CODES
from pgx.domain.enums import CurationStatus

__all__ = [
    "FORM_FIELDS",
    "READ_ROUTES",
    "WRITE_ROUTES",
    "FormResponse",
    "ReadOnlyWorkflowView",
    "escape",
    "handle",
    "render_history",
    "render_review_form",
    "render_revision_editor",
    "render_work_item_detail",
    "render_work_item_list",
]

#: Read-only routes. Named so a test can assert the split rather than infer it.
READ_ROUTES: Tuple[str, ...] = ("list", "detail", "editor", "evidence",
                                "review-form", "history")

#: Mutating routes. Each requires ``expected_version``.
WRITE_ROUTES: Tuple[str, ...] = ("save-revision", "submit-revision",
                                 "record-review")

#: Every field a form may send, with its meaning. ``role`` is absent and its
#: absence is asserted by test: there is no spelling of it that this module
#: accepts.
FORM_FIELDS: Mapping[str, str] = {
    "actor_id": "who is acting; roles are resolved from it, never sent with it",
    "work_item_id": "which work item",
    "revision_id": "which revision",
    "expected_version": "the version the page was rendered from",
    "payload_json": "the curator's structured conclusion",
    "evidence_included": "evidence record uuids cited",
    "evidence_excluded": "evidence record uuids deliberately set aside",
    "note": "free text from the curator",
    "decision": "a ReviewDecision name",
    "rationale": "the reviewer's stated reason",
    "findings": "individual reviewer findings",
    "conflict_state": "a ConflictState name",
    "conflict_material": "whether an identified conflict changes the answer",
    "rationale_complete": "whether the structured rationale is complete",
}

#: Field names this module refuses outright. Sending one is an attempt to
#: decide from the form something the form does not get to decide.
_REFUSED_FIELDS: Mapping[str, str] = {
    "role": "roles come from the injected provider, never from a form",
    "roles": "roles come from the injected provider, never from a form",
    "actor_roles": "roles come from the injected provider, never from a form",
    "as_role": "roles come from the injected provider, never from a form",
    "status": "a status is reached by a transition, not typed into a form",
    "force": "there is no override for a closed gate",
    "skip_gates": "there is no override for a closed gate",
    "approved_by": "approval is recorded by the act of reviewing, not asserted",
}


def escape(value: Any) -> str:
    """Escape once, here, for everything that reaches a page.

    One function so that "was this escaped" has one answer. ``quote=True``
    because values are interpolated into attributes as well as into text.
    """
    if value is None:
        return ""
    return _html.escape(str(value), quote=True)


@dataclass(frozen=True)
class FormResponse:
    """What a handler returns.

    ``status`` is an integer for the benefit of whatever eventually serves
    this; nothing here interprets it. ``mutated`` is stated rather than
    inferred, so a test can assert that a read handler returned False without
    reaching into the store.
    """

    status: int
    body: str
    content_type: str = "text/html; charset=utf-8"
    route: str = ""
    mutated: bool = False
    data: Mapping[str, Any] = field(default_factory=dict)

    def to_json(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "route": self.route,
            "mutated": self.mutated,
            "content_type": self.content_type,
            "data": dict(self.data),
        }


class ReadOnlyWorkflowView:
    """A façade exposing only the service's read operations.

    The read handlers are given one of these instead of the service. There is
    no ``review``, no ``submit`` and no ``create_revision`` on it, so a read
    handler cannot mutate even by mistake - the attribute is not there.
    """

    def __init__(self, service: Any) -> None:
        self._service = service

    def gate_status(self, **kwargs: Any) -> Dict[str, Any]:
        return self._service.gate_status(**kwargs)

    def history(self, work_item_id: str) -> Dict[str, Any]:
        return self._service.history(work_item_id)

    def __repr__(self) -> str:
        return "<ReadOnlyWorkflowView: gate_status, history>"


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------

_STYLE = """
body { font-family: system-ui, sans-serif; margin: 0; padding: 1.5rem;
       background: #fbfbfa; color: #1a1a1a; }
h1, h2, h3 { font-weight: 600; margin: 1.2rem 0 .5rem; }
table { border-collapse: collapse; width: 100%; margin: .5rem 0 1.5rem; }
th, td { border: 1px solid #d6d6d0; padding: .4rem .6rem; text-align: left;
         vertical-align: top; font-size: .92rem; }
th { background: #efefe9; }
.source-block { border-left: 4px solid #8a6d3b; background: #fdf8ef;
                padding: .6rem .8rem; margin: .4rem 0; }
.curator-block { border-left: 4px solid #2f5d8a; background: #f0f5fa;
                 padding: .6rem .8rem; margin: .4rem 0; }
.block-label { font-size: .72rem; letter-spacing: .06em; font-weight: 700;
               text-transform: uppercase; display: block; margin-bottom: .3rem; }
.source-block .block-label { color: #8a6d3b; }
.curator-block .block-label { color: #2f5d8a; }
.blocked { background: #fbf0f0; border: 1px solid #d9a0a0; padding: .8rem;
           margin: 1rem 0; }
.blocked h3 { margin-top: 0; color: #8a2f2f; }
.gate-open { color: #2f6d3b; }
.gate-shut { color: #8a2f2f; font-weight: 600; }
.state { font-family: ui-monospace, monospace; font-size: .85rem;
         background: #efefe9; padding: .1rem .35rem; border-radius: 3px; }
form { border: 1px solid #d6d6d0; background: #fff; padding: 1rem;
       margin: 1rem 0; }
label { display: block; margin: .6rem 0 .2rem; font-size: .85rem;
        font-weight: 600; }
input, textarea, select { width: 100%; box-sizing: border-box; padding: .4rem;
        font-family: inherit; font-size: .9rem; border: 1px solid #c6c6c0; }
textarea { min-height: 6rem; }
button { margin-top: .8rem; padding: .5rem 1rem; font-size: .9rem;
         cursor: pointer; }
.note { font-size: .82rem; color: #55554f; margin: .4rem 0; }
""".strip()


def _page(title: str, body: str) -> str:
    """Wrap a fragment in a deterministic document.

    No script tag, no external stylesheet, no timestamp: the same inputs render
    byte-identical output, which is what makes a snapshot test meaningful.
    """
    return (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n"
        "<meta charset=\"utf-8\">\n"
        "<title>%s</title>\n<style>\n%s\n</style>\n</head>\n<body>\n"
        "%s\n"
        "<p class=\"note\">Internal curation console. Not a public interface, "
        "not an authenticated one, and not a server: these pages are rendered "
        "by a function and served by nothing. Identity and access control are "
        "owned by WP-23.</p>\n"
        "</body>\n</html>\n" % (escape(title), _STYLE, body))


def _source_block(label: str, text: Any) -> str:
    """Upstream text, marked as upstream and escaped."""
    return ('<div class="source-block"><span class="block-label">%s '
            '&mdash; unreviewed upstream text</span>%s</div>'
            % (escape(label), escape(text)))


def _curator_block(label: str, text: Any) -> str:
    """Project text, marked as project text and escaped."""
    return ('<div class="curator-block"><span class="block-label">%s '
            '&mdash; written by this project</span>%s</div>'
            % (escape(label), escape(text)))


def _gate_table(gates: Optional[Mapping[str, Any]]) -> str:
    if not gates or gates.get("gates") is None:
        reason = (gates or {}).get(
            "blocked_reason", "no gate evaluation is available")
        return '<p class="note">%s</p>' % escape(reason)
    rows = []
    for gate in gates["gates"]:
        code = gate["code"]
        owner = GATE_CODES.get(code, {}).get("owner", "")
        rows.append(
            "<tr><td class=\"%s\">%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
            % ("gate-open" if gate["passed"] else "gate-shut",
               "open" if gate["passed"] else "SHUT",
               escape(code), escape(gate["detail"]), escape(owner)))
    return ("<table><tr><th>Gate</th><th>Code</th><th>Detail</th>"
            "<th>Who can open it</th></tr>%s</table>" % "".join(rows))


def _blockers(gates: Optional[Mapping[str, Any]]) -> str:
    if not gates or gates.get("gates") is None:
        return ""
    shut = [g for g in gates["gates"] if not g["passed"]]
    if not shut:
        return ""
    items = "".join(
        "<li><strong>%s</strong>: %s <em>(%s)</em></li>"
        % (escape(g["code"]), escape(g["detail"]),
           escape(GATE_CODES.get(g["code"], {}).get("owner", "unassigned")))
        for g in shut)
    return ('<div class="blocked"><h3>%d of %d approval gates are shut</h3>'
            '<ul>%s</ul><p class="note">No approval control is shown while '
            'any gate is shut. The gates are not advisory and there is no '
            'override.</p></div>'
            % (len(shut), len(gates["gates"]), items))


def _hidden(name: str, value: Any) -> str:
    return '<input type="hidden" name="%s" value="%s">' % (
        escape(name), escape(value))


def render_work_item_list(items: Sequence[Mapping[str, Any]],
                          *, counts: Optional[Mapping[str, int]] = None,
                          title: str = "Curation work items") -> str:
    """The index. Read-only: it contains no form and no action."""
    summary = ""
    if counts:
        summary = "<p>%s</p>" % " &middot; ".join(
            "%s: <span class=\"state\">%d</span>" % (escape(k), v)
            for k, v in sorted(counts.items()))
    rows = "".join(
        "<tr><td>%s</td><td><span class=\"state\">%s</span></td>"
        "<td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
        % (escape(item.get("work_item_id")), escape(item.get("status")),
           escape(item.get("version")), escape(item.get("gene_canonical_key")),
           escape(item.get("drug_canonical_key")),
           escape(", ".join(item.get("tags") or ())))
        for item in items)
    body = (
        "<h1>%s</h1>%s"
        "<table><tr><th>Work item</th><th>State</th><th>Version</th>"
        "<th>Gene</th><th>Drug</th><th>Tags</th></tr>%s</table>"
        "<p class=\"note\">This page performs no action. Everything that "
        "changes state is a separate submission carrying the version it was "
        "rendered from.</p>"
        % (escape(title), summary, rows or
           "<tr><td colspan=\"6\">no work items</td></tr>"))
    return _page(title, body)


def render_work_item_detail(work_item: Mapping[str, Any],
                            *, gates: Optional[Mapping[str, Any]] = None,
                            revision: Optional[Mapping[str, Any]] = None,
                            provenance: Optional[Mapping[str, Any]] = None
                            ) -> str:
    """One work item: its state, its legacy input, its revision, its gates."""
    title = "Work item %s" % work_item.get("work_item_id")
    parts = [
        "<h1>%s</h1>" % escape(title),
        "<p>State <span class=\"state\">%s</span> at version "
        "<span class=\"state\">%s</span></p>"
        % (escape(work_item.get("status")), escape(work_item.get("version"))),
    ]

    legacy = work_item.get("legacy_values") or {}
    if legacy:
        parts.append("<h2>Legacy input</h2>")
        parts.append(
            "<p class=\"note\">Imported from a WP-08 proposal. These values "
            "have not been reviewed by anyone and are not a conclusion of "
            "this project.</p>")
        for key in sorted(legacy):
            parts.append(_source_block(key, legacy[key]))

    if revision:
        parts.append("<h2>Current revision</h2>")
        parts.append(
            "<p>Revision <span class=\"state\">%s</span> by %s under protocol "
            "%s</p>" % (escape(revision.get("revision_number")),
                        escape(revision.get("authored_by")),
                        escape(revision.get("protocol_version"))))
        payload = revision.get("payload") or {}
        for key in sorted(payload):
            parts.append(_curator_block(key, payload[key]))
        evidence = (revision.get("evidence") or {}).get(
            "evidence_record_uuids") or ()
        parts.append("<p class=\"note\">Cites %d evidence record(s).</p>"
                     % len(evidence))
    else:
        parts.append("<h2>Current revision</h2>")
        parts.append("<p class=\"note\">This work item has no revision. "
                     "Nothing has been claimed about it.</p>")

    if provenance:
        parts.append(
            "<h2>Provenance</h2><p class=\"note\">Verified by %s; every trace "
            "verified: %s</p>"
            % (escape(provenance.get("verified_by")),
               escape(provenance.get("all_traces_verified"))))

    parts.append("<h2>Approval gates</h2>")
    parts.append(_blockers(gates))
    parts.append(_gate_table(gates))
    return _page(title, "".join(parts))


def render_revision_editor(work_item: Mapping[str, Any],
                           *, evidence_options: Sequence[Mapping[str, Any]] = (),
                           gates: Optional[Mapping[str, Any]] = None,
                           payload_json: str = "") -> str:
    """The curator's editor.

    Editable only while the work item is RAW. For anything else the form is
    replaced by the reason, because rendering a disabled editor invites
    somebody to wonder how to enable it.
    """
    title = "Edit %s" % work_item.get("work_item_id")
    status = str(work_item.get("status"))
    parts = ["<h1>%s</h1>" % escape(title),
             "<p>State <span class=\"state\">%s</span> at version "
             "<span class=\"state\">%s</span></p>"
             % (escape(status), escape(work_item.get("version")))]

    legacy = work_item.get("legacy_values") or {}
    if legacy:
        parts.append("<h2>Upstream values, for reference only</h2>")
        for key in sorted(legacy):
            parts.append(_source_block(key, legacy[key]))

    if status != CurationStatus.RAW.value:
        parts.append(
            "<div class=\"blocked\"><h3>Not editable</h3><p>Revisions are "
            "written while a work item is RAW; this one is %s. A submitted "
            "revision is immutable, and a correction is a new revision after "
            "a change request or a new work item.</p></div>" % escape(status))
        return _page(title, "".join(parts))

    options = "".join(
        "<option value=\"%s\">%s</option>"
        % (escape(opt.get("uuid")), escape(opt.get("label", opt.get("uuid"))))
        for opt in evidence_options)
    parts.append(
        "<form method=\"post\" action=\"save-revision\">"
        "%s%s"
        "<label for=\"actor_id\">Your actor id</label>"
        "<input id=\"actor_id\" name=\"actor_id\" required>"
        "<p class=\"note\">Roles are resolved from this id by the configured "
        "role provider. This form has no role field, and one sent anyway is "
        "refused rather than honoured.</p>"
        "<label for=\"payload_json\">Structured conclusion (WP-09 payload, "
        "JSON)</label>"
        "<textarea id=\"payload_json\" name=\"payload_json\" required>%s"
        "</textarea>"
        "<label for=\"evidence_included\">Evidence cited</label>"
        "<select id=\"evidence_included\" name=\"evidence_included\" multiple>"
        "%s</select>"
        "<label for=\"evidence_excluded\">Evidence deliberately set aside"
        "</label>"
        "<select id=\"evidence_excluded\" name=\"evidence_excluded\" multiple>"
        "%s</select>"
        "<label for=\"note\">Note</label>"
        "<input id=\"note\" name=\"note\">"
        "<button type=\"submit\">Save revision</button>"
        "<p class=\"note\">Saving writes an immutable revision and leaves the "
        "work item RAW. Submitting it for review is a separate act.</p>"
        "</form>"
        % (_hidden("work_item_id", work_item.get("work_item_id")),
           _hidden("expected_version", work_item.get("version")),
           escape(payload_json), options, options))

    if work_item.get("current_revision_id"):
        parts.append(
            "<form method=\"post\" action=\"submit-revision\">"
            "%s%s%s"
            "<label for=\"submit_actor_id\">Your actor id</label>"
            "<input id=\"submit_actor_id\" name=\"actor_id\" required>"
            "<label for=\"submit_note\">Note to the reviewer</label>"
            "<input id=\"submit_note\" name=\"note\">"
            "<button type=\"submit\">Submit for independent review</button>"
            "<p class=\"note\">After submission this revision is frozen. It "
            "cannot be edited, only superseded by a new revision after a "
            "change request.</p></form>"
            % (_hidden("work_item_id", work_item.get("work_item_id")),
               _hidden("revision_id", work_item.get("current_revision_id")),
               _hidden("expected_version", work_item.get("version"))))

    parts.append("<h2>Approval gates</h2>")
    parts.append(_blockers(gates))
    parts.append(_gate_table(gates))
    return _page(title, "".join(parts))


def render_evidence_trace(work_item: Mapping[str, Any],
                          traces: Sequence[Mapping[str, Any]]) -> str:
    """Each cited record beside the upstream text it came from."""
    title = "Evidence trace for %s" % work_item.get("work_item_id")
    parts = ["<h1>%s</h1>" % escape(title),
             "<p class=\"note\">Upstream text is shown so a curator can read "
             "what a source actually said. It is not a finding of this "
             "project and is never styled as one.</p>"]
    if not traces:
        parts.append("<p class=\"note\">No evidence is cited.</p>")
    for trace in traces:
        parts.append("<h2>%s</h2>" % escape(trace.get("evidence_record_uuid")))
        parts.append(
            "<p class=\"note\">source %s version %s &middot; raw artifact %s"
            "</p>" % (escape(trace.get("source")),
                      escape(trace.get("source_version")),
                      escape(trace.get("raw_artifact_id"))))
        if trace.get("source_text") is not None:
            parts.append(_source_block("Source statement",
                                       trace.get("source_text")))
        if trace.get("curator_note"):
            parts.append(_curator_block("Curator note",
                                        trace.get("curator_note")))
    return _page(title, "".join(parts))


def render_review_form(work_item: Mapping[str, Any],
                       *, gates: Optional[Mapping[str, Any]] = None,
                       revision: Optional[Mapping[str, Any]] = None) -> str:
    """The reviewer's page.

    ``APPROVE`` is offered only when every gate is open. When any is shut the
    option is absent from the select - not disabled, not hidden by styling -
    and the blockers are listed with their owners in its place.
    """
    title = "Review %s" % work_item.get("work_item_id")
    status = str(work_item.get("status"))
    parts = ["<h1>%s</h1>" % escape(title),
             "<p>State <span class=\"state\">%s</span> at version "
             "<span class=\"state\">%s</span></p>"
             % (escape(status), escape(work_item.get("version")))]

    if revision:
        parts.append("<h2>Revision under review</h2>")
        parts.append("<p class=\"note\">Revision %s by %s. Content hash %s."
                     "</p>" % (escape(revision.get("revision_number")),
                               escape(revision.get("authored_by")),
                               escape(revision.get("content_hash"))))
        for key in sorted(revision.get("payload") or {}):
            parts.append(_curator_block(key, (revision["payload"])[key]))

    if status != CurationStatus.UNDER_REVIEW.value:
        parts.append(
            "<div class=\"blocked\"><h3>Not under review</h3><p>Only an "
            "UNDER_REVIEW work item can be reviewed; this one is %s.</p>"
            "</div>" % escape(status))
        return _page(title, "".join(parts))

    parts.append(_blockers(gates))
    gates_open = bool(gates and gates.get("passed"))

    decisions = [d for d in ReviewDecision
                 if d is not ReviewDecision.APPROVE or gates_open]
    options = "".join("<option value=\"%s\">%s</option>"
                      % (escape(d.value), escape(d.value)) for d in decisions)
    conflicts = "".join("<option value=\"%s\">%s</option>"
                        % (escape(c.value), escape(c.value))
                        for c in ConflictState)

    parts.append(
        "<form method=\"post\" action=\"record-review\">"
        "%s%s%s"
        "<label for=\"review_actor_id\">Your actor id</label>"
        "<input id=\"review_actor_id\" name=\"actor_id\" required>"
        "<p class=\"note\">You may not review a revision you authored. The "
        "check is made against the stored revision, not against this form.</p>"
        "<label for=\"decision\">Decision</label>"
        "<select id=\"decision\" name=\"decision\" required>%s</select>"
        "%s"
        "<label for=\"rationale\">Rationale</label>"
        "<textarea id=\"rationale\" name=\"rationale\" required></textarea>"
        "<label for=\"conflict_state\">Conflict state</label>"
        "<select id=\"conflict_state\" name=\"conflict_state\">%s</select>"
        "<button type=\"submit\">Record review</button>"
        "</form>"
        % (_hidden("work_item_id", work_item.get("work_item_id")),
           _hidden("revision_id", work_item.get("submitted_revision_id")),
           _hidden("expected_version", work_item.get("version")),
           options,
           "" if gates_open else
           "<p class=\"note\">APPROVE is not offered: it requires every gate "
           "open. Rejecting, requesting changes and referring to adjudication "
           "remain available, because a reviewer must be able to refuse a "
           "conclusion precisely when it cannot be approved.</p>",
           conflicts))

    parts.append("<h2>Approval gates</h2>")
    parts.append(_gate_table(gates))
    return _page(title, "".join(parts))


def render_history(history: Mapping[str, Any]) -> str:
    """Everything that happened, including what was superseded."""
    item = history.get("work_item") or {}
    title = "History of %s" % item.get("work_item_id")
    parts = ["<h1>%s</h1>" % escape(title)]

    parts.append("<h2>Revisions</h2><table><tr><th>#</th><th>Author</th>"
                 "<th>Parent</th><th>Content hash</th></tr>")
    for rev in history.get("revisions") or ():
        parts.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
                     % (escape(rev.get("revision_number")),
                        escape(rev.get("authored_by")),
                        escape(rev.get("parent_revision_id") or "-"),
                        escape(rev.get("content_hash"))))
    parts.append("</table>")

    parts.append("<h2>Reviews</h2><p class=\"note\">Every review is listed. "
                 "A review that asked for changes before a later approval is "
                 "part of how the conclusion was reached and is not "
                 "superseded away.</p>"
                 "<table><tr><th>Decision</th><th>Reviewer</th><th>Author</th>"
                 "<th>Rationale</th></tr>")
    for review in history.get("reviews") or ():
        parts.append("<tr><td><span class=\"state\">%s</span></td><td>%s</td>"
                     "<td>%s</td><td>%s</td></tr>"
                     % (escape(review.get("decision")),
                        escape(review.get("reviewed_by")),
                        escape(review.get("author_actor_id")),
                        escape(review.get("rationale"))))
    parts.append("</table>")

    adjudications = history.get("adjudications") or ()
    if adjudications:
        parts.append("<h2>Adjudications</h2>")
        for record in adjudications:
            parts.append(
                "<p>%s by %s</p>" % (escape(record.get("decision")),
                                     escape(record.get("adjudicated_by"))))
            parts.append(_curator_block(
                "Curator position",
                (record.get("curator_position") or {}).get("position")))
            parts.append(_curator_block(
                "Reviewer position",
                (record.get("reviewer_position") or {}).get("position")))
            parts.append("<p class=\"note\">Both positions are preserved. An "
                         "adjudication settles which reading the project "
                         "adopts; it does not erase the disagreement.</p>")
    return _page(title, "".join(parts))


# ---------------------------------------------------------------------------
# handlers
# ---------------------------------------------------------------------------

def _refuse_forbidden(params: Mapping[str, Any]) -> None:
    for name, why in _REFUSED_FIELDS.items():
        if name in params:
            raise WorkflowError("form field %r is refused: %s" % (name, why))


def _required_version(params: Mapping[str, Any]) -> int:
    """No default, ever.

    A missing version cannot mean "current": the whole purpose of the field is
    that the caller states which world they were looking at.
    """
    raw = params.get("expected_version")
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        raise WorkflowError(
            "expected_version is required. Without it this submission would "
            "mean 'whatever the version is now', which is exactly the "
            "assumption optimistic concurrency exists to refuse.")
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise WorkflowError("expected_version must be an integer, got %r"
                            % (raw,))


def _required(params: Mapping[str, Any], name: str) -> str:
    value = params.get(name)
    if value is None or not str(value).strip():
        raise WorkflowError("%s is required" % name)
    return str(value).strip()


def handle(route: str, request: Mapping[str, Any], *,
           service: Any,
           read_view: Optional[ReadOnlyWorkflowView] = None) -> FormResponse:
    """Dispatch one request.

    Read routes are handed a ``ReadOnlyWorkflowView`` and never the service, so
    the separation is enforced by what is reachable rather than by convention.
    A write route reached by a GET-like method is refused before anything is
    read, because a state change behind a link is a state change somebody can
    be tricked into making.
    """
    method = str(request.get("method", "GET")).upper()
    params: Mapping[str, Any] = request.get("params") or {}

    if route in READ_ROUTES:
        view = read_view or ReadOnlyWorkflowView(service)
        return _handle_read(route, params, view)

    if route not in WRITE_ROUTES:
        return FormResponse(status=404, route=route,
                            body=_page("Unknown route",
                                       "<h1>No route %s</h1>" % escape(route)))

    if method != "POST":
        return FormResponse(
            status=405, route=route,
            body=_page("Method not allowed",
                       "<h1>%s requires a POST</h1><p>A state change reached "
                       "by following a link is a state change somebody can be "
                       "tricked into making.</p>" % escape(route)))

    try:
        _refuse_forbidden(params)
        return _handle_write(route, params, service)
    except Exception as exc:  # surfaced as a page, never swallowed
        return FormResponse(
            status=400, route=route, mutated=False,
            data={"error": type(exc).__name__, "detail": str(exc)},
            body=_page("Refused",
                       "<div class=\"blocked\"><h3>%s</h3><p>%s</p></div>"
                       % (escape(type(exc).__name__), escape(str(exc)))))


def _handle_read(route: str, params: Mapping[str, Any],
                 view: ReadOnlyWorkflowView) -> FormResponse:
    work_item_id = params.get("work_item_id")
    if route == "list":
        items = params.get("items") or ()
        return FormResponse(
            status=200, route=route, mutated=False,
            data={"count": len(items)},
            body=render_work_item_list(items, counts=params.get("counts")))

    gates = view.gate_status(
        work_item_id=str(work_item_id),
        reviewer_actor_id=params.get("reviewer_actor_id"),
        conflict_state=params.get("conflict_state"),
        conflict_material=params.get("conflict_material"),
        rationale_complete=params.get("rationale_complete"))
    history = view.history(str(work_item_id))
    work_item = history["work_item"]
    revisions = history.get("revisions") or []
    current = revisions[-1] if revisions else None

    if route == "detail":
        body = render_work_item_detail(work_item, gates=gates,
                                       revision=current)
    elif route == "editor":
        body = render_revision_editor(
            work_item, gates=gates,
            evidence_options=params.get("evidence_options") or ())
    elif route == "evidence":
        body = render_evidence_trace(work_item, params.get("traces") or ())
    elif route == "review-form":
        submitted_id = work_item.get("submitted_revision_id")
        submitted = next((r for r in revisions
                          if r.get("revision_id") == submitted_id), current)
        body = render_review_form(work_item, gates=gates, revision=submitted)
    else:
        body = render_history(history)

    return FormResponse(status=200, route=route, mutated=False, body=body,
                        data={"work_item_id": work_item_id,
                              "status": work_item.get("status"),
                              "version": work_item.get("version"),
                              "gates_passed": bool(gates.get("passed"))})


def _handle_write(route: str, params: Mapping[str, Any],
                  service: Any) -> FormResponse:
    from pgx.curation.workflow.models import EvidenceSelectionSnapshot
    import json as _json

    actor_id = _required(params, "actor_id")
    work_item_id = _required(params, "work_item_id")
    expected_version = _required_version(params)

    if route == "save-revision":
        payload = _json.loads(_required(params, "payload_json"))
        if not isinstance(payload, Mapping):
            raise WorkflowError("payload_json must decode to an object")
        evidence = EvidenceSelectionSnapshot(
            evidence_record_uuids=tuple(params.get("evidence_included") or ()),
            excluded_record_uuids=tuple(params.get("evidence_excluded") or ()),
            evidence_build_key=str(params.get("evidence_build_key") or ""),
            evidence_build_content_hash=str(
                params.get("evidence_build_content_hash") or ""),
            dataset_public_id=str(params.get("dataset_public_id") or ""))
        result = service.create_revision(
            actor_id=actor_id, work_item_id=work_item_id,
            expected_version=expected_version, payload=payload,
            evidence=evidence, note=str(params.get("note") or ""))
    elif route == "submit-revision":
        result = service.submit(
            actor_id=actor_id, work_item_id=work_item_id,
            revision_id=_required(params, "revision_id"),
            expected_version=expected_version,
            note=str(params.get("note") or ""))
    else:
        decision = ReviewDecision(_required(params, "decision"))
        conflict = params.get("conflict_state")
        result = service.review(
            actor_id=actor_id, work_item_id=work_item_id,
            revision_id=_required(params, "revision_id"),
            expected_version=expected_version, decision=decision,
            rationale=_required(params, "rationale"),
            findings=tuple(params.get("findings") or ()),
            conflict_state=(ConflictState(conflict) if conflict else None),
            conflict_material=params.get("conflict_material"),
            rationale_complete=params.get("rationale_complete"))

    return FormResponse(
        status=200, route=route, mutated=True,
        data=result.to_json(),
        body=_page("Recorded",
                   "<h1>%s</h1><p>%s is now <span class=\"state\">%s</span> "
                   "at version <span class=\"state\">%s</span>.</p>"
                   "<p class=\"note\">Audit action %s.</p>"
                   % (escape(route), escape(work_item_id),
                      escape(result.work_item.status.value),
                      escape(result.work_item.version),
                      escape(result.audit_action))))
