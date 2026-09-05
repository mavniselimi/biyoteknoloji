# -*- coding: utf-8 -*-
"""Deterministic renderers (WP-15).

Two output formats, one property: **the same report, template and locale
render byte for byte identically, on any machine, at any time.**

What that forbids is a list, and every item on it is a thing renderers
normally do:

* no timestamp - not "generated at", not a build date, not a clock read;
* no path - not the artifact's own, not the ruleset's, not a temporary
  directory a fixture happened to use;
* no environment value - no hostname, no user, no process id, no version of
  Python;
* no random or generated id;
* no dictionary iteration order and no set iteration order; every collection
  is sorted or was already canonically ordered upstream.

The consequence is that a byte difference between two renders is always a
difference in the facts or in the template, which is what makes a checksum of
the rendered document worth recording.

**Everything that came from data is escaped.** A case label, a medication
name, a canonical key, a rationale reference or an evidence id could each
contain a backtick, a pipe, a bracket, an angle bracket or a newline. Rendered
raw, those turn a value into a heading, a link, an HTML element, an extra
table column, or a whole new section. :func:`escape_markdown` is applied to
every one of them, and the tests that matter here are the ones that feed a
report a case id like ``# Rapor onaylandi`` and check what comes out.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from pgx.reporting.errors import ReportRenderError
from pgx.reporting.structured import StructuredReport
from pgx.reporting.templates import (FIELD_LABELS, MEDICATION_QUESTIONS,
                                     label, require_locale)

__all__ = [
    "MARKDOWN_ESCAPES",
    "UNSAFE_IN_CODE_SPAN",
    "RENDERER_VERSION",
    "escape_markdown",
    "render_json",
    "render_markdown",
    "rendered_checksum",
]

RENDERER_VERSION = "pgx-report-renderer/1"

#: Characters that change Markdown structure when they appear in a value.
#: ``&``, ``<`` and ``>`` are handled first, as HTML entities, so an inline
#: ``<script>`` or a stray ``&lt;`` cannot survive into rendered HTML.
#:
#: Deliberately not the whole punctuation set. ``(``, ``)``, ``{``, ``}``,
#: ``!`` and ``^`` create no structure on their own - ``!`` needs a following
#: ``[`` and ``)`` a preceding ``]``, and both brackets are escaped here - so
#: escaping them would only make every label in the document unreadable, which
#: is its own kind of failure.
MARKDOWN_ESCAPES = "\\`*_[]#+|~"

#: Characters that make a code span the wrong container for a value.
#:
#: A code span renders its contents literally, so most of these are already
#: inert inside one - but "inert once a Markdown renderer has run" is a
#: weaker property than "not present in the document at all", and a document
#: is read by more things than a Markdown renderer. A value carrying any of
#: them is rendered as escaped inline text instead, where it is inert in both
#: senses.
#:
#: ``_`` and ``-`` are deliberately **absent**. Governed codes are full of
#: them - ``NOT_ASSESSED``, ``DRUG_NOT_IN_CANONICAL_DATASET``,
#: ``PGX-REL-29991231-001`` - and escaping those would print a code that is
#: no longer the code, which is the one thing the report must not do. It
#: would also break the safe-status line check, which looks for the literal
#: token ``NOT_ASSESSED`` on a rendered line.
UNSAFE_IN_CODE_SPAN = "`|<>&*[]()#+~\\"

_LEADING_BLOCK = re.compile(r"^(\s*)([-+*>=.]|#{1,6}|\d+[.)])")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def escape_markdown(value: Any) -> str:
    r"""Render one data-supplied value as inert Markdown text.

    Four passes, in this order and for these reasons:

    1. **Control characters** become a visible ``\\xNN`` escape. Deleting them
       would make two different values render identically; leaving them would
       put a terminal escape sequence into a document somebody opens.
    2. **Line breaks and tabs** become ``\\n``, ``\\r`` and ``\\t`` as text. A
       value containing a newline could otherwise close a table, start a
       heading, or open a fenced block that swallows the rest of the report.
    3. **HTML** ``&``, ``<`` and ``>`` become entities, so no element and no
       entity can be introduced by data.
    4. **Markdown metacharacters** are backslash-escaped, and a leading block
       marker is escaped as well, so a value cannot begin a heading, a list
       item, a blockquote or a setext underline.

    ``None`` renders as an empty string rather than as ``"None"``: absence is
    reported by the section that owns it, in a controlled sentence, not by a
    Python repr leaking into a document.
    """
    if value is None:
        return ""
    text = value if isinstance(value, str) else str(value)
    text = _CONTROL.sub(lambda match: "\\x%02X" % ord(match.group(0)), text)
    text = (text.replace("\r\n", "\\n").replace("\n", "\\n")
                .replace("\r", "\\r").replace("\t", "\\t"))
    text = (text.replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;"))
    out: List[str] = []
    for character in text:
        if character in MARKDOWN_ESCAPES:
            out.append("\\")
        out.append(character)
    text = "".join(out)
    return _LEADING_BLOCK.sub(lambda match: "%s\\%s" % (match.group(1),
                                                        match.group(2)), text)


def _code(value: Any) -> str:
    r"""A governed code, shown verbatim inside a code span.

    A code span renders its contents literally, so the backslash escaping
    :func:`escape_markdown` applies would be *shown* rather than applied - an
    identifier would arrive on the page as ``SYNTHETIC\_PHENOTYPE\_PROFILE``,
    which is no longer the governed value the report is required to print. So
    the neutralisation here is exactly what a code span cannot survive:

    * control characters and line breaks, escaped as visible text, because a
      newline ends the span and the table row with it;
    * ``|``, escaped, because a pipe ends the table cell even inside a span;
    * a backtick, which would close the span - and rather than mangling the
      value, such a value is rendered through :func:`escape_markdown` as inert
      text instead, so it is still shown and still cannot do anything.

    Everything else - angle brackets, ampersands, asterisks, underscores - is
    literal inside a code span and inert by construction.
    """
    if value is None or value == "":
        return ""
    text = value if isinstance(value, str) else str(value)
    text = _CONTROL.sub(lambda match: "\\x%02X" % ord(match.group(0)), text)
    text = (text.replace("\r\n", "\\n").replace("\n", "\\n")
                .replace("\r", "\\r").replace("\t", "\\t"))
    if any(character in text for character in UNSAFE_IN_CODE_SPAN):
        return escape_markdown(text)
    return "`%s`" % text


def _codes(values: Iterable[Any], locale: str) -> str:
    rendered = [_code(item) for item in values if item not in (None, "")]
    if not rendered:
        return escape_markdown(label(FIELD_LABELS, "none_recorded", locale,
                                     table_name="field"))
    return ", ".join(rendered)


def _field(name: str, locale: str) -> str:
    return escape_markdown(label(FIELD_LABELS, name, locale,
                                 table_name="field"))


def _row(cells: Sequence[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def _status_block(status, locale: str) -> List[str]:
    """Attention and coverage, in one table, always both.

    Rendered from :class:`~pgx.reporting.structured.OverallStatus`, which
    cannot hold one without the other, so there is no code path here that
    could emit a level with no coverage beside it.
    """
    lines = [
        _row([_field("field", locale), _field("value", locale)]),
        _row(["---", "---"]),
        _row([_field("attention_code", locale), _code(status.attention_code)]),
        _row([_field("attention", locale),
              escape_markdown(status.attention_label)]),
        _row([_field("coverage_code", locale), _code(status.coverage_code)]),
        _row([_field("coverage", locale),
              escape_markdown(status.coverage_label)]),
    ]
    lines.append("")
    lines.append(escape_markdown(status.adjacency_note))
    for sentence in status.qualifier_statements:
        lines.append("")
        lines.append(escape_markdown(sentence))
    if status.reason_codes:
        lines.append("")
        lines.append(_row([_field("reason_code", locale),
                           _field("reason", locale)]))
        lines.append(_row(["---", "---"]))
        for code, text in zip(status.reason_codes, status.reason_labels):
            lines.append(_row([_code(code), escape_markdown(text)]))
    lines.append("")
    return lines


def _axis_table(axes, locale: str) -> List[str]:
    if not axes:
        return []
    lines = [
        _row([_field("gene", locale), _field("coverage_code", locale),
              _field("coverage", locale), _field("phenotype", locale),
              _field("observation_state", locale),
              _field("reason_code", locale), _field("evidence", locale),
              _field("conflict", locale)]),
        _row(["---"] * 8),
    ]
    for axis in axes:
        lines.append(_row([
            _code(axis.gene_canonical_key),
            _code(axis.coverage_code),
            escape_markdown(axis.coverage_label),
            _code(axis.observed_phenotype) if axis.observed_phenotype
            else escape_markdown(label(FIELD_LABELS, "none_recorded", locale,
                                       table_name="field")),
            escape_markdown(axis.observation_state_label),
            _codes(axis.reason_codes, locale),
            _codes(axis.evidence_references, locale),
            _codes(axis.conflict_references, locale),
        ]))
    lines.append("")
    return lines


def _finding_block(finding, locale: str) -> List[str]:
    lines = [
        _row([_field("field", locale), _field("value", locale)]),
        _row(["---", "---"]),
        _row([_field("gene", locale), _code(finding.gene_canonical_key)]),
        _row([_field("phenotype", locale), _code(finding.phenotype)]),
        _row([_field("finding_attention_code", locale),
              _code(finding.attention_code)]),
        _row([_field("finding_attention", locale),
              escape_markdown(finding.attention_label)]),
        _row([_field("rule", locale), _code(finding.rule_id)]),
        _row([_field("rule_version", locale), _code(finding.rule_version)]),
        _row([_field("rule_content_hash", locale),
              _code(finding.rule_content_hash)]),
        _row([_field("rationale_reference", locale),
              _code(finding.rationale_reference)]),
        _row([_field("curation_revision", locale),
              "%s %s" % (_code(finding.curation_revision_id),
                         _code(finding.curation_revision_hash))]),
        _row([_field("effect_code", locale),
              _codes([finding.effect_code], locale)]),
        _row([_field("explanation_code", locale),
              _codes([finding.explanation_code], locale)]),
        _row([_field("evidence", locale),
              _codes(finding.evidence_references, locale)]),
    ]
    if finding.codes_absent_statement:
        lines.append("")
        lines.append(escape_markdown(finding.codes_absent_statement))
    lines.append("")
    return lines


def _answers_block(section, locale: str) -> List[str]:
    lines = [
        _row([_field("field", locale), _field("answer", locale)]),
        _row(["---", "---"]),
    ]
    labels = dict(section.answers)
    for identifier, _text in MEDICATION_QUESTIONS:
        answer = dict(labels.get(identifier, {}))
        parts: List[str] = []
        for value in answer.get("values", ()) or ():
            parts.append(escape_markdown(value))
        for code in answer.get("codes", ()) or ():
            if code:
                parts.append(_code(code))
        for reference in answer.get("references", ()) or ():
            if reference:
                parts.append(_code(reference))
        for text in answer.get("statements", ()) or ():
            if text:
                parts.append(escape_markdown(text))
        if not parts:
            parts.append(escape_markdown(
                label(FIELD_LABELS, "none_recorded", locale,
                      table_name="field")))
        lines.append(_row([escape_markdown(identifier), " ".join(parts)]))
    lines.append("")
    return lines


def _provenance_block(report: StructuredReport, locale: str) -> List[str]:
    provenance = dict(report.release_provenance)
    pairs = (
        ("release", ("release_public_id", "release_manifest_hash")),
        ("software", ("software_version", "software_source_tree_hash")),
        ("dataset", ("dataset_public_id", "canonical_build_content_hash")),
        ("ruleset", ("ruleset_public_id", "ruleset_content_hash")),
        ("evidence_build", ("evidence_build_key",
                            "evidence_build_content_hash")),
        ("coverage_manifest", ("coverage_manifest_hash",)),
        ("protocol", ("protocol_version", "protocol_content_hash")),
        ("source_policy", ("source_policy_version",
                           "source_policy_content_hash")),
    )
    lines = [
        _row([_field("field", locale), _field("value", locale)]),
        _row(["---", "---"]),
    ]
    for name, keys in pairs:
        values = [provenance.get(key) for key in keys]
        lines.append(_row([_field(name, locale), _codes(values, locale)]))
    lines.append(_row([_field("pointer_generation", locale),
                       _code(dict(report.pointer_audit).get(
                           "active_pointer_generation"))]))
    lines.append("")
    return lines


def _hash_block(report: StructuredReport, locale: str) -> List[str]:
    return [
        _row([_field("field", locale), _field("value", locale)]),
        _row(["---", "---"]),
        _row([_field("input_hash", locale), _code(report.input_hash)]),
        _row([_field("output_hash", locale), _code(report.output_hash)]),
        _row([_field("coverage_result_hash", locale),
              _code(report.coverage_result_hash)]),
        _row([_field("canonical_result_hash", locale),
              _code(report.canonical_result_hash)]),
        _row([_field("report_hash", locale), _code(report.report_hash())]),
        _row([_field("report_schema_version", locale),
              _code(report.report_schema_version)]),
        _row([_field("template_version", locale),
              _code(report.template_version)]),
        _row([_field("engine_contract_version", locale),
              _code(report.engine_contract_version)]),
        _row([_field("locale", locale), _code(report.locale)]),
        "",
    ]


def render_markdown(report: StructuredReport) -> str:
    """Render one structured report as Markdown, deterministically."""
    if not isinstance(report, StructuredReport):
        raise ReportRenderError(
            "only a validated StructuredReport is rendered; got %r"
            % type(report).__name__,
            code="REPORT_INPUT_INVALID", location="$.report")
    locale = require_locale(report.locale)
    titles = dict(report.section_titles)
    lines: List[str] = []

    lines.append("# " + escape_markdown(titles["report"]))
    lines.append("")
    lines.append("> " + escape_markdown(report.canonical_warning))
    lines.append("")

    lines.append("## " + escape_markdown(titles["disclaimer"]))
    lines.append("")
    lines.append(escape_markdown(report.disclaimer))
    lines.append("")
    lines.append(_row([_field("field", locale), _field("value", locale)]))
    lines.append(_row(["---", "---"]))
    lines.append(_row([_field("assessment_id", locale),
                       _code(report.assessment_id)]))
    lines.append(_row([_field("case_id", locale),
                       _codes([report.case_id], locale)]))
    lines.append(_row([_field("mode", locale),
                       "%s %s" % (_code(report.mode_code),
                                  escape_markdown(report.mode_label))]))
    lines.append(_row([_field("input_kind", locale),
                       "%s %s" % (_code(report.input_kind_code),
                                  escape_markdown(report.input_kind_label))]))
    lines.append("")

    lines.append("## " + escape_markdown(titles["summary"]))
    lines.append("")
    lines.extend(_status_block(report.overall, locale))

    lines.append("## " + escape_markdown(titles["profile"]))
    lines.append("")
    lines.append(escape_markdown(report.profile_note))
    lines.append("")
    lines.append(_row([_field("gene", locale),
                       _field("observation_state", locale),
                       _field("phenotype", locale),
                       _field("reason_code", locale)]))
    lines.append(_row(["---"] * 4))
    for observation in report.profile_observations:
        lines.append(_row([
            _code(observation.get("gene_id")),
            _code(observation.get("status")),
            _codes([observation.get("phenotype")], locale),
            _codes([observation.get("reason_code")], locale),
        ]))
    lines.append("")

    lines.append("## " + escape_markdown(titles["medications"]))
    lines.append("")
    for section in report.medications:
        lines.append("### " + escape_markdown(section.requested_value))
        lines.append("")
        lines.append(_row([_field("field", locale), _field("value", locale)]))
        lines.append(_row(["---", "---"]))
        lines.append(_row([_field("drug", locale),
                           _code(section.drug_canonical_key)]))
        lines.append(_row([_field("requested_value", locale),
                           escape_markdown(section.requested_value)]))
        lines.append("")
        lines.extend(_status_block(section.status, locale))

        lines.append("#### " + escape_markdown(titles["axes"]))
        lines.append("")
        axis_lines = _axis_table(section.axes, locale)
        if axis_lines:
            lines.extend(axis_lines)
        else:
            lines.append(escape_markdown(
                label(FIELD_LABELS, "none_recorded", locale,
                      table_name="field")))
            lines.append("")

        lines.append("#### " + escape_markdown(titles["findings"]))
        lines.append("")
        if section.findings:
            for finding in section.findings:
                lines.extend(_finding_block(finding, locale))
        else:
            lines.append(escape_markdown(
                label(FIELD_LABELS, "none_recorded", locale,
                      table_name="field")))
            lines.append("")

        lines.append("#### " + escape_markdown(titles["not_assessed"]))
        lines.append("")
        not_assessed = _axis_table(section.not_assessed_axes, locale)
        if not_assessed:
            lines.extend(not_assessed)
        else:
            lines.append(escape_markdown(
                label(FIELD_LABELS, "none_recorded", locale,
                      table_name="field")))
            lines.append("")

        lines.append("#### " + escape_markdown(titles["conflicts"]))
        lines.append("")
        lines.append(_codes(section.conflict_references, locale))
        lines.append("")
        conflicts = _axis_table(section.conflict_axes, locale)
        if conflicts:
            lines.extend(conflicts)

        lines.extend(_answers_block(section, locale))

    lines.append("## " + escape_markdown(titles["uncertainty"]))
    lines.append("")
    if report.uncertainty:
        lines.append(_row([_field("kind", locale), _field("subject", locale),
                           _field("statement", locale),
                           _field("codes", locale),
                           _field("references", locale)]))
        lines.append(_row(["---"] * 5))
        for item in report.uncertainty:
            lines.append(_row([
                _code(item.kind), _code(item.subject),
                escape_markdown(item.statement_text),
                _codes(item.codes, locale),
                _codes(item.references, locale),
            ]))
    else:
        lines.append(escape_markdown(
            label(FIELD_LABELS, "none_recorded", locale, table_name="field")))
    lines.append("")

    lines.append("## " + escape_markdown(titles["provenance"]))
    lines.append("")
    lines.extend(_provenance_block(report, locale))

    lines.append("## " + escape_markdown(titles["hashes"]))
    lines.append("")
    lines.extend(_hash_block(report, locale))

    lines.append("## " + escape_markdown(titles["warning"]))
    lines.append("")
    lines.append("> " + escape_markdown(report.canonical_warning))

    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n"


def render_json(report: StructuredReport) -> str:
    """Render one structured report as canonical JSON.

    Sorted keys and a fixed indent, so the JSON form is byte-stable under the
    same rule the Markdown form is.
    """
    if not isinstance(report, StructuredReport):
        raise ReportRenderError(
            "only a validated StructuredReport is rendered; got %r"
            % type(report).__name__,
            code="REPORT_INPUT_INVALID", location="$.report")
    return json.dumps(report.to_json(), ensure_ascii=False, sort_keys=True,
                      indent=2) + "\n"


def rendered_checksum(text: str) -> str:
    """The digest of the rendered bytes themselves.

    Distinct from ``report_hash``, which covers the validated report. This one
    covers the document: a renderer change that alters spacing changes this
    and not that, which is exactly the difference an operator needs to see.
    """
    from pgx.domain.hashing import sha256_digest
    return sha256_digest({"renderer_version": RENDERER_VERSION,
                          "bytes": text})
