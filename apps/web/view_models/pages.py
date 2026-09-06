"""The screens other than the assessment page.

Simpler models, same rules: frozen, built from validated documents, adding
labels and links and nothing else. Each one's docstring records the single
decision that makes it honest, because in every case there was a shorter
version that would have been misleading.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from apps.web.labels import ui
from apps.web.routes import web_route
from apps.web.view_models.base import display

__all__ = [
    "CaseDetailModel",
    "CaseListModel",
    "CaseSummary",
    "ErrorPageModel",
    "EvidencePageModel",
    "CorrectionSummary",
    "ExpectationSummary",
    "ExpertReviewPageModel",
    "RevealedResultSummary",
    "LoginPageModel",
    "MedicationChoice",
    "SystemPageModel",
    "ValidationBoardModel",
    "build_case_detail",
    "build_case_list",
    "build_error_page",
    "build_evidence_page",
    "build_expert_review_page",
    "build_login_page",
    "build_system_page",
    "MetricRowModel",
    "MetricSectionModel",
    "build_validation_board",
]

ABSENT_MARKER = "—"


# ---------------------------------------------------------------------------
# Case catalogue
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class CaseSummary:
    """One development case in the list."""

    case_id: str
    label: str
    case_role: str
    is_synthetic: bool
    is_validation_evidence: bool
    legacy_profile_key: Optional[str]
    observation_count: int
    demonstrates: str
    url: str


@dataclass(frozen=True, slots=True)
class CaseListModel:
    """The catalogue screen.

    Ordered by case identifier, which is also the order the sealed artifact
    stores them in. Not by phenotype, not by how many genes a case names, and
    not by anything derived from what an assessment of it would produce - the
    catalogue is a list of inputs, and any ordering that hinted at outputs
    would be a ranking assembled before a single rule had run.

    The sort happens *here* rather than being assumed of the caller. Relying
    on the artifact's order would mean the page's order was a property of
    whoever built the list - a test fixture, a future loader, a provider that
    merges two sources - and the identical inputs would render differently
    depending on which of them supplied them.
    """

    cases: Tuple[CaseSummary, ...]
    development_only_note: str
    empty_note: str
    catalog_available: bool


def build_case_list(cases: Sequence[Any], *, locale: str = "tr",
                    available: bool = True) -> CaseListModel:
    route = web_route("web.case_detail")
    summaries = tuple(
        CaseSummary(
            case_id=display(case.case_id, location="$.case_id",
                            allow_none=False),
            label=display(case.label, location="$.label"),
            case_role=case.case_role,
            is_synthetic=case.is_synthetic,
            is_validation_evidence=case.is_validation_evidence,
            legacy_profile_key=case.legacy_profile_key,
            observation_count=case.observation_count,
            demonstrates=display(case.demonstrates,
                                 location="$.demonstrates"),
            url=route.url(case_id=case.case_id))
        for case in sorted(cases, key=lambda entry: entry.case_id))
    return CaseListModel(
        cases=summaries,
        development_only_note=ui("cases.development_only", locale),
        empty_note=ui("cases.empty", locale),
        catalog_available=available)


# ---------------------------------------------------------------------------
# Case detail and submission
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class MedicationChoice:
    """One selectable medication from the pinned canonical catalogue.

    ``selected`` is always ``False`` at build time and there is no code path
    that sets it from a phenotype. Preselecting from a profile would be this
    layer deciding which medicine a phenotype is about - the association the
    governed ruleset exists to make.
    """

    canonical_key: str
    display_name: str
    declared: bool
    selected: bool = False

    def __post_init__(self) -> None:
        if self.selected:
            raise ValueError(
                "no medication is preselected; a selection is the operator's "
                "and is never derived from a phenotype")


@dataclass(frozen=True, slots=True)
class CaseDetailModel:
    """One case, its observations, and the request a submission would make."""

    case_id: str
    label: str
    case_role: str
    demonstrates: str
    migration_note: str
    no_pii_assertion: str
    legacy_profile_key: Optional[str]
    source_file: Optional[str]
    source_file_sha256: Optional[str]
    observations: Tuple[Tuple[str, str], ...]
    medications: Tuple[MedicationChoice, ...]
    medications_available: bool
    medications_note: str
    medications_unavailable_note: str
    submission_fields: Tuple[Tuple[str, str], ...]
    submission_note: str
    no_free_text_note: str
    submit_url: str
    submit_available: bool
    submit_unavailable_note: str
    csrf_token: Optional[str]


def build_case_detail(case: Any, *, drugs: Sequence[Mapping[str, Any]] = (),
                      drugs_available: bool = True,
                      submit_available: bool = False,
                      csrf_token: Optional[str] = None,
                      mode: str = "DEMO",
                      input_kind: str = "SYNTHETIC_PHENOTYPE_PROFILE",
                      locale: str = "tr") -> CaseDetailModel:
    """Build the case screen.

    ``drugs`` arrives from the WP-16 catalogue in canonical-key order and is
    kept in that order. The submission preview lists exactly the fields the
    request will carry, so what a reader sees on this page and what the client
    sends are the same list.
    """
    choices = tuple(
        MedicationChoice(
            canonical_key=display(item.get("drug"), location="$.drugs.drug",
                                  allow_none=False),
            display_name=display(item.get("display_name"),
                                 location="$.drugs.display_name"),
            declared=bool(item.get("declared")))
        for item in drugs)

    fields = (
        ("mode", mode),
        ("input_kind", input_kind),
        ("case_id", case.case_id),
        ("profile.input_contract_version", "pgx-phenotype-input/1"),
        ("profile.observations",
         "%d" % case.observation_count),
        ("medications", ui("case.medications_legend", locale)),
    )

    return CaseDetailModel(
        case_id=display(case.case_id, location="$.case_id", allow_none=False),
        label=display(case.label, location="$.label"),
        case_role=case.case_role,
        demonstrates=display(case.demonstrates, location="$.demonstrates"),
        migration_note=display(case.migration_note,
                               location="$.migration_note"),
        no_pii_assertion=display(case.no_pii_assertion,
                                 location="$.no_pii_assertion"),
        legacy_profile_key=case.legacy_profile_key,
        source_file=case.source_file,
        source_file_sha256=case.source_file_sha256,
        observations=tuple((item.gene, item.value)
                           for item in case.observations),
        medications=choices,
        medications_available=bool(drugs_available),
        medications_note=ui("case.medications_note", locale),
        medications_unavailable_note=ui("case.medications_unavailable",
                                        locale),
        submission_fields=fields,
        submission_note=ui("case.submission_preview_note", locale),
        no_free_text_note=ui("case.no_free_text", locale),
        submit_url=web_route("web.case_assess").url(case_id=case.case_id),
        submit_available=bool(submit_available),
        submit_unavailable_note=ui("case.submit_unavailable", locale),
        csrf_token=csrf_token)


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class EvidencePageModel:
    """One evidence record's provenance, and nothing it did not carry.

    ``text_fragment_count`` is shown and the fragments are not. The count
    tells a reader that source text exists behind the record; printing the
    text would put unreviewed third-party statements about medicines on a
    screen under this interface's authority.
    """

    record_uuid: str
    natural_key: str
    record_type: str
    provider_source_key: str
    origin_source_key: str
    origin_status: str
    version_status: str
    version_value: str
    source_payload_hash: str
    content_hash: str
    production_eligible: bool
    evidence_build_key: str
    evidence_build_content_hash: str
    genes: Tuple[Tuple[str, str], ...]
    drugs: Tuple[Tuple[str, str], ...]
    publications: Tuple[Tuple[str, str], ...]
    locators: Tuple[Tuple[str, str, str, str], ...]
    record_type_mapping: Tuple[Tuple[str, str], ...]
    text_fragment_count: int
    no_prose_note: str
    immutable_note: str


def build_evidence_page(document: Mapping[str, Any], *,
                        locale: str = "tr") -> EvidencePageModel:
    def _cell(value: Any, location: str) -> str:
        rendered = display(value, location=location)
        return rendered if rendered else ABSENT_MARKER

    mapping = document.get("record_type_mapping") or {}
    return EvidencePageModel(
        record_uuid=display(document.get("record_uuid"),
                            location="$.record_uuid", allow_none=False),
        natural_key=_cell(document.get("natural_key"), "$.natural_key"),
        record_type=_cell(document.get("record_type"), "$.record_type"),
        provider_source_key=_cell(document.get("provider_source_key"),
                                  "$.provider_source_key"),
        origin_source_key=_cell(document.get("origin_source_key"),
                                "$.origin_source_key"),
        origin_status=_cell(document.get("origin_status"), "$.origin_status"),
        version_status=_cell(document.get("version_status"),
                             "$.version_status"),
        version_value=_cell(document.get("version_value"), "$.version_value"),
        source_payload_hash=_cell(document.get("source_payload_hash"),
                                  "$.source_payload_hash"),
        content_hash=_cell(document.get("content_hash"), "$.content_hash"),
        production_eligible=bool(document.get("production_eligible")),
        evidence_build_key=_cell(document.get("evidence_build_key"),
                                 "$.evidence_build_key"),
        evidence_build_content_hash=_cell(
            document.get("evidence_build_content_hash"),
            "$.evidence_build_content_hash"),
        genes=tuple((_cell(item.get("canonical_key"), "$.genes.canonical_key"),
                     _cell(item.get("source_label"), "$.genes.source_label"))
                    for item in document.get("genes") or ()),
        drugs=tuple((_cell(item.get("canonical_key"), "$.drugs.canonical_key"),
                     _cell(item.get("source_label"), "$.drugs.source_label"))
                    for item in document.get("drugs") or ()),
        publications=tuple(
            (_cell(item.get("identifier_type"), "$.publications.type"),
             _cell(item.get("identifier"), "$.publications.identifier"))
            for item in document.get("publications") or ()),
        locators=tuple(
            (_cell(item.get("snapshot_id"), "$.locators.snapshot_id"),
             _cell(item.get("artifact_id"), "$.locators.artifact_id"),
             _cell(item.get("artifact_digest"), "$.locators.artifact_digest"),
             _cell(item.get("json_pointer"), "$.locators.json_pointer"))
            for item in document.get("locators") or ()),
        record_type_mapping=tuple(
            (key, _cell(mapping.get(key), "$.record_type_mapping.%s" % key))
            for key in ("record_type", "status", "map_version",
                        "production_eligible")) if mapping else (),
        text_fragment_count=int(document.get("text_fragment_count") or 0),
        no_prose_note=ui("evidence.no_prose_note", locale),
        immutable_note=ui("evidence.immutable_note", locale))


# ---------------------------------------------------------------------------
# System
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class SystemPageModel:
    """The active release and the readiness report, side by side, unmerged.

    ``version_available`` and ``readiness_available`` are separate booleans
    because the two calls fail independently. Merging them would let an
    unreadable release make a healthy readiness report look unavailable, or -
    worse - let a readable release make a blocked readiness look fine.
    """

    version_available: bool
    version_rows: Tuple[Tuple[str, str], ...]
    version_unavailable_note: str
    claim_boundary_phase: str
    claim_boundary_approved: bool
    #: Wave 4B. The two release tracks, side by side and never merged. A
    #: single "the release" row would let a reader take a provisional
    #: candidate release for a governed one, which is the one confusion this
    #: page exists to prevent.
    runtime_tracks_available: bool
    active_track: str
    candidate_rows: Tuple[Tuple[str, str], ...]
    governed_rows: Tuple[Tuple[str, str], ...]
    track_note: str
    readiness_available: bool
    readiness_status: str
    readiness_components: Tuple[Tuple[str, bool, bool, str], ...]
    blocking_failures: Tuple[str, ...]


#: The version fields shown, in a fixed order. Everything the contract
#: declares, including a field that is empty: a blank row says the release
#: pinned nothing there, and omitting it would say nobody looked.
_SYSTEM_VERSION_FIELDS: Tuple[str, ...] = (
    "api_version", "release_public_id", "release_manifest_hash",
    "active_pointer_generation", "software_version",
    "software_source_tree_hash", "dataset_public_id",
    "canonical_build_content_hash", "ruleset_public_id",
    "ruleset_content_hash", "evidence_build_key",
    "evidence_build_content_hash", "coverage_manifest_hash",
    "protocol_version", "source_policy_version")


def _track_rows(state: Mapping[str, Any], keys) -> Tuple[Tuple[str, str], ...]:
    rows = []
    for key in keys:
        value = state.get(key)
        if isinstance(value, (list, tuple)):
            value = ", ".join(str(item) for item in value)
        rows.append((key, ABSENT_MARKER if value in (None, "")
                     else str(value)))
    return tuple(rows)


def build_system_page(version: Optional[Mapping[str, Any]],
                      readiness: Optional[Mapping[str, Any]], *,
                      tracks: Optional[Mapping[str, Any]] = None,
                      locale: str = "tr") -> SystemPageModel:
    rows: List[Tuple[str, str]] = []
    if version is not None:
        for name in _SYSTEM_VERSION_FIELDS:
            value = version.get(name)
            rendered = display(value, location="$.version.%s" % name)
            rows.append((name, rendered if rendered else ABSENT_MARKER))

    components: List[Tuple[str, bool, bool, str]] = []
    if readiness is not None:
        for item in readiness.get("components") or ():
            components.append((
                display(item.get("component"),
                        location="$.readiness.component"),
                bool(item.get("ready")),
                bool(item.get("blocking")),
                display(item.get("detail"), location="$.readiness.detail")))

    candidate_state = (tracks or {}).get("candidate") or {}
    governed_state = (tracks or {}).get("governed") or {}
    return SystemPageModel(
        runtime_tracks_available=tracks is not None,
        active_track=str((tracks or {}).get("active_track") or ABSENT_MARKER),
        candidate_rows=_track_rows(candidate_state, (
            "track", "composed", "release_public_id", "dataset_public_id",
            "ruleset_key", "ruleset_content_hash", "manifest_hash",
            "permitted_modes", "authority", "review_state",
            "claim_boundary_status", "claim_boundary_is_approved",
            "rule_count", "detail")),
        governed_rows=_track_rows(governed_state, (
            "track", "composed", "release_public_id", "authority", "detail")),
        track_note=str(candidate_state.get("governed_registry_note") or ""),
        version_available=version is not None,
        version_rows=tuple(rows),
        version_unavailable_note=ui("system.version_unavailable", locale),
        claim_boundary_phase=str((version or {}).get("claim_boundary_phase")
                                 or ABSENT_MARKER),
        claim_boundary_approved=bool(
            (version or {}).get("claim_boundary_approved")),
        readiness_available=readiness is not None,
        readiness_status=str((readiness or {}).get("status") or ""),
        readiness_components=tuple(components),
        blocking_failures=tuple(
            str(item) for item in (readiness or {}).get("blocking_failures")
            or ()))


# ---------------------------------------------------------------------------
# Validation, expert review, login, errors
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ValidationBoardModel:
    """The honest empty state.

    Counts are integers where a real count exists and ``None`` where the
    architecture that would produce one does not. ``None`` renders as
    *unavailable*; it never renders as ``0``. A zero would say "we looked and
    found none", and what is true is "there is nothing here to look at yet".

    There is no rate, ratio or percentage anywhere in this model, and no field
    in which one could be stored - so no zero denominator can be turned into
    ``0%`` or ``100%`` by a template.
    """

    development_case_count: int
    internal_holdout_count: Optional[int]
    expert_holdout_count: Optional[int]
    validation_run_count: Optional[int]
    architecture_note: str
    no_run_note: str
    metrics_note: str
    separation_note: str
    no_conclusion_note: str
    blockers: Tuple[Tuple[str, str], ...]
    #: WP-21. One table per partition, never combined. Empty before WP-21 or
    #: when the committed feed is absent.
    metric_sections: Tuple["MetricSectionModel", ...] = ()
    benchmark_executed: bool = False
    release_text: str = ""
    metric_registry_version: str = ""
    not_benchmarked_note: str = ""
    no_combined_note: str = ""

    def __post_init__(self) -> None:
        for name in ("internal_holdout_count", "expert_holdout_count",
                     "validation_run_count"):
            value = getattr(self, name)
            if value is not None and value != 0:
                raise ValueError(
                    "%s must be None while the validation architecture does "
                    "not exist; a non-zero count here would be a claim this "
                    "repository cannot support" % name)
        for section in self.metric_sections:
            if section.is_development_regression and \
                    section.is_validation_evidence:
                raise ValueError(
                    "a DEVELOPMENT_REGRESSION section may not be marked "
                    "validation evidence; those cases shaped the software")


@dataclass(frozen=True, slots=True)
class MetricRowModel:
    """One metric on the dashboard, already decided about.

    ``value_text`` is what the template prints. It is either a real value or
    the *unavailable* label - never ``0`` and never ``0%``. The decision is
    made here rather than in Jinja, because a template conditional is easy to
    get subtly wrong and impossible to unit test on its own.
    """

    metric_id: str
    label: str
    numerator_text: str
    denominator_text: str
    value_text: str
    status: str
    status_text: str
    reason_text: str
    has_number: bool
    is_validation_evidence: bool


@dataclass(frozen=True, slots=True)
class MetricSectionModel:
    """One partition's table. Development is a section, never a flag."""

    section: str
    role: str
    heading: str
    is_validation_evidence: bool
    is_development_regression: bool
    case_count_text: str
    note: str
    rows: Tuple[MetricRowModel, ...]


def _text(value: Any, fallback: str) -> str:
    """A count, or the unavailable label. Never a coerced zero."""
    if value is None:
        return fallback
    return str(value)


def _metric_rows(section: Mapping[str, Any], locale: str
                 ) -> Tuple[MetricRowModel, ...]:
    unavailable = ui("status.unavailable", locale)
    status_text = {
        "AVAILABLE": "",
        "UNAVAILABLE": unavailable,
        "NOT_EXECUTED": ui("status.not_executed", locale),
        "BLOCKED": ui("status.blocked", locale),
        "NOT_APPLICABLE": unavailable,
    }
    rows = []
    for metric in section.get("metrics", ()):
        status = str(metric.get("status", "UNAVAILABLE"))
        has_number = bool(metric.get("has_number")) and status == "AVAILABLE"
        rows.append(MetricRowModel(
            metric_id=str(metric.get("metric_id", "")),
            label=str(metric.get("label", "")),
            numerator_text=_text(metric.get("numerator"), unavailable),
            denominator_text=_text(metric.get("denominator"), unavailable),
            # The single most important line on this page: a metric without a
            # number prints the unavailable label, whatever its numerator was.
            value_text=(str(metric.get("value")) if has_number
                        else unavailable),
            status=status,
            status_text=status_text.get(status, unavailable),
            reason_text=str(metric.get("unavailable_reason") or ""),
            has_number=has_number,
            is_validation_evidence=bool(
                metric.get("is_validation_evidence"))))
    return tuple(rows)


def _metric_sections(feed: Optional[Mapping[str, Any]], locale: str
                     ) -> Tuple[MetricSectionModel, ...]:
    if not feed:
        return ()
    unavailable = ui("status.unavailable", locale)
    headings = {
        "DEVELOPMENT_REGRESSION": ui("validation.section_development", locale),
        "INTERNAL_HOLDOUT": ui("validation.section_internal", locale),
        "EXPERT_HOLDOUT": ui("validation.section_expert", locale),
    }
    sections = []
    for section in feed.get("sections", ()):
        name = str(section.get("section", ""))
        development = bool(section.get("is_development_regression"))
        sections.append(MetricSectionModel(
            section=name, role=str(section.get("role", "")),
            heading=headings.get(name, name),
            is_validation_evidence=bool(
                section.get("is_validation_evidence")),
            is_development_regression=development,
            case_count_text=_text(section.get("case_count"), unavailable),
            note=ui("validation.development_warning" if development
                    else "validation.holdout_evidence_note", locale),
            rows=_metric_rows(section, locale)))
    return tuple(sections)


def build_validation_board(*, development_case_count: int,
                           blockers: Sequence[Tuple[str, str]] = (),
                           feed: Optional[Mapping[str, Any]] = None,
                           locale: str = "tr") -> ValidationBoardModel:
    """Build the board from the committed public feed.

    ``feed`` is the WP-21 dashboard feed - aggregates only, already checked
    for restricted material twice before it reaches here. When it is absent
    the board renders exactly what it rendered before WP-21 existed: an empty
    state with no numbers in it.
    """
    unavailable = ui("status.unavailable", locale)
    return ValidationBoardModel(
        development_case_count=int(development_case_count),
        internal_holdout_count=None,
        expert_holdout_count=None,
        validation_run_count=None,
        architecture_note=ui("validation.architecture_missing", locale),
        no_run_note=ui("validation.no_run", locale),
        metrics_note=ui("validation.metrics_unavailable", locale),
        separation_note=ui("validation.separation_note", locale),
        no_conclusion_note=ui("validation.no_conclusion", locale),
        blockers=tuple(blockers),
        metric_sections=_metric_sections(feed, locale),
        benchmark_executed=bool(feed and feed.get("benchmark_executed")),
        release_text=_text(feed and feed.get("release_public_id"),
                           unavailable),
        metric_registry_version=str(
            (feed or {}).get("metric_registry_version") or ""),
        not_benchmarked_note=ui("validation.not_benchmarked", locale),
        no_combined_note=ui("validation.no_combined", locale))


@dataclass(frozen=True, slots=True)
class ExpectationSummary:
    """A locked expectation, as the reviewer's own receipt.

    Rendered only to the reviewer who wrote it, and only in their own
    assignment's page. It carries the revision hash so they can see what was
    recorded, and the server timestamp so they can see they did not choose it.
    """

    revision: int
    recorded_at: str
    revision_hash: str
    expected_attention_level: str
    expected_coverage_status: str
    expected_coverage_reason: str
    expected_rule_id: str
    requires_traceable_evidence: bool
    rationale_codes: Tuple[str, ...]
    reviewer_note: str


@dataclass(frozen=True, slots=True)
class RevealedResultSummary:
    """The system result. Constructed only from a reveal record.

    There is no default and no ``None`` variant: a page either has one of
    these because a reveal happened, or has nothing at all. The blinded page
    holds ``None`` for the whole object rather than an object of empty
    strings, so a template that rendered it unguarded would show nothing
    rather than blanks that look like measurements.
    """

    attention_level: str
    coverage_status: str
    coverage_reason: str
    firing_rule_id: str
    finding_count: int
    traceable_finding_count: int
    output_hash: str
    revealed_at: str
    pinned_expectation_hash: str


@dataclass(frozen=True, slots=True)
class CorrectionSummary:
    """One appended amendment, in the reviewer's own history."""

    kind: str
    reason_code: str
    recorded_at: str
    after_reveal: bool
    correction_hash: str


@dataclass(frozen=True, slots=True)
class ExpertReviewPageModel:
    """The state-aware review page.

    ``result`` is ``None`` until a reveal record exists, and there is no code
    path that sets it otherwise: :func:`build_expert_review_page` takes a
    result only when handed a reveal. A hidden element is still disclosure,
    so the guarantee has to be that the value is absent from the model rather
    than merely unrendered.

    ``forms_enabled`` is false whenever authentication, CSRF or the review
    service is missing - which is every deployment until WP-23. The forms
    render as an explanation rather than as controls, because a control that
    cannot submit is worse than none: a reviewer would fill it in.
    """

    case_id: str
    state: str
    blinded: bool
    available: bool
    forms_enabled: bool
    unavailable_note: str
    order_note: str
    no_disclosure_note: str
    blinded_note: str
    phases: Tuple[Tuple[str, str], ...]
    release_public_id: str
    protocol_version: str
    protocol_approved: bool
    protocol_note: str
    csrf_token: Optional[str] = None
    expectation: Optional[ExpectationSummary] = None
    result: Optional[RevealedResultSummary] = None
    decision: Optional[str] = None
    rated_dimensions: Tuple[str, ...] = ()
    corrections: Tuple[CorrectionSummary, ...] = ()
    rationale_choices: Tuple[str, ...] = ()
    decision_choices: Tuple[str, ...] = ()
    rating_dimensions: Tuple[str, ...] = ()
    superseded_by: str = ""

    def __post_init__(self) -> None:
        # The structural guarantee, checked rather than trusted. A blinded
        # page holding a result would be the one defect this whole work
        # package exists to prevent, so it is unconstructable.
        if self.blinded and self.result is not None:
            raise ValueError(
                "a blinded expert-review page may not carry a system result; "
                "the reviewer has not locked an expectation yet, and a hidden "
                "value is still disclosure")
        if self.forms_enabled and not self.csrf_token:
            raise ValueError(
                "a form is enabled only with a CSRF token; a control that "
                "cannot submit safely is worse than none, because a reviewer "
                "would fill it in")


def _review_text(value: Any) -> str:
    """One review field, escaped and bounded. Named to avoid colliding with
    WP-21's ``_text``, which takes a fallback and means something else."""
    return "" if value is None else display(str(value), location="$.field",
                                            allow_none=True) or ""


def build_expert_review_page(case_id: str, *, view: Any = None,
                             protocol: Any = None,
                             csrf_token: Optional[str] = None,
                             forms_enabled: bool = False,
                             locale: str = "tr") -> ExpertReviewPageModel:
    """Build the page from a service view, or the controlled empty state.

    ``view`` is ``None`` when there is no assignment, no service, or no
    approved protocol - and the three are deliberately indistinguishable on
    the rendered page. A reviewer who could tell "no such case" from "not
    yours" would have an enumeration tool for the holdout set.
    """
    from pgx.expert_review.vocabulary import (DECISION_VALUES,
                                              LIKERT_DIMENSIONS,
                                              RATIONALE_CODES)

    approved = bool(protocol is not None and getattr(protocol, "is_approved",
                                                     False))
    if view is None:
        return ExpertReviewPageModel(
            case_id=display(case_id, location="$.case_id", allow_none=False),
            state="", blinded=True, available=False, forms_enabled=False,
            unavailable_note=ui("expert.unavailable", locale),
            order_note=ui("expert.order", locale),
            no_disclosure_note=ui("expert.no_case_disclosure", locale),
            blinded_note=ui("expert.blinded", locale),
            phases=(
                (ui("expert.phase_expected", locale),
                 ui("status.unavailable", locale)),
                (ui("expert.phase_reveal", locale),
                 ui("status.unavailable", locale)),
                (ui("expert.phase_complete", locale),
                 ui("status.unavailable", locale)),
            ),
            release_public_id="", protocol_version="",
            protocol_approved=approved,
            protocol_note=ui("expert.protocol_draft", locale))

    assignment = view.assignment
    state = view.state.value
    done = ui("expert.phase_done", locale)
    pending = ui("expert.phase_pending", locale)
    order = {"ASSIGNED": 0, "EXPECTATION_RECORDED": 1,
             "RESULT_REVEALED": 2, "COMPLETED": 3}.get(state, 0)

    expectation = None
    if view.expectation is not None:
        item = view.expectation
        expectation = ExpectationSummary(
            revision=item.revision,
            recorded_at=item.recorded_at.isoformat().replace("+00:00", "Z"),
            revision_hash=item.revision_hash(),
            expected_attention_level=_review_text(item.expected_attention_level),
            expected_coverage_status=_review_text(item.expected_coverage_status),
            expected_coverage_reason=_review_text(item.expected_coverage_reason),
            expected_rule_id=_review_text(item.expected_rule_id),
            requires_traceable_evidence=item.requires_traceable_evidence,
            rationale_codes=tuple(item.rationale_codes),
            reviewer_note=_review_text(item.reviewer_note))

    result = None
    reveal = view.reveal_record
    if reveal is not None:
        result = RevealedResultSummary(
            attention_level=_review_text(reveal.result_attention_level),
            coverage_status=_review_text(reveal.result_coverage_status),
            coverage_reason=_review_text(reveal.result_coverage_reason),
            firing_rule_id=_review_text(reveal.result_firing_rule_id),
            finding_count=reveal.result_finding_count,
            traceable_finding_count=reveal.result_traceable_finding_count,
            output_hash=reveal.result_output_hash,
            revealed_at=reveal.revealed_at.isoformat().replace("+00:00", "Z"),
            pinned_expectation_hash=reveal.expectation_revision_hash)

    completion = view.completion
    return ExpertReviewPageModel(
        case_id=display(assignment.case_id, location="$.case_id",
                        allow_none=False),
        state=state, blinded=view.blinded, available=True,
        forms_enabled=bool(forms_enabled and csrf_token
                           and state not in ("COMPLETED", "INVALIDATED")),
        csrf_token=csrf_token if forms_enabled else None,
        unavailable_note="", order_note=ui("expert.order", locale),
        no_disclosure_note=ui("expert.no_case_disclosure", locale),
        blinded_note=ui("expert.blinded", locale),
        phases=(
            (ui("expert.phase_expected", locale),
             done if order >= 1 else pending),
            (ui("expert.phase_reveal", locale),
             done if order >= 2 else pending),
            (ui("expert.phase_complete", locale),
             done if order >= 3 else pending),
        ),
        release_public_id=_review_text(assignment.release_public_id),
        protocol_version=_review_text(assignment.protocol_version),
        protocol_approved=approved,
        protocol_note=("" if approved
                       else ui("expert.protocol_draft", locale)),
        expectation=expectation, result=result,
        decision=(None if completion is None else completion.decision.value),
        rated_dimensions=(() if completion is None
                          else tuple(sorted(completion.rating_map()))),
        corrections=tuple(
            CorrectionSummary(
                kind=item.kind.value, reason_code=_review_text(item.reason_code),
                recorded_at=item.recorded_at.isoformat().replace("+00:00",
                                                                 "Z"),
                after_reveal=item.after_reveal,
                correction_hash=item.correction_hash())
            for item in view.corrections),
        rationale_choices=tuple(RATIONALE_CODES),
        decision_choices=tuple(DECISION_VALUES),
        rating_dimensions=tuple(LIKERT_DIMENSIONS))


@dataclass(frozen=True, slots=True)
class LoginPageModel:
    """The login page. A real form when a real provider is composed.

    WP-17's version was a shell whose ``__post_init__`` refused
    ``logout_available=True``, because there were no sessions and a sign-out
    control that appeared to work would have implied one existed. WP-23
    supplies sessions, so the refusal moves to what is now the dangerous
    combination: **a form with no CSRF token**. A login form that could post
    without one lets an attacker log a victim into the attacker's account, and
    everything the victim then does happens in a session the attacker
    controls.

    ``failed`` is a single boolean with a single message. There is no field
    for *why* a login failed, because the page must not tell an unknown
    username apart from a wrong password.
    """

    required_note: str
    not_configured_note: str
    owner_note: str
    no_signup_note: str
    authentication_configured: bool
    logout_available: bool
    logout_note: str
    form_enabled: bool = False
    csrf_token: Optional[str] = None
    failed: bool = False
    failure_note: str = ""
    rate_limited: bool = False
    rate_limited_note: str = ""
    actor: Optional[str] = None
    role: Optional[str] = None
    signed_in: bool = False

    def __post_init__(self) -> None:
        if self.form_enabled and not self.csrf_token:
            raise ValueError(
                "a login form is enabled only with a pre-auth CSRF token; a "
                "form that could post without one lets an attacker log a "
                "victim into the attacker's account")
        if self.logout_available and not self.signed_in:
            raise ValueError(
                "a sign-out control is offered only to a signed-in session; "
                "one offered otherwise would imply a session existed")
        if self.signed_in and not self.actor:
            raise ValueError(
                "a signed-in page names the actor it signed in; one that did "
                "not would be asserting a session with no subject")
        # Nothing about the failure may be specific. One boolean, one
        # message, whatever went wrong.
        if self.failed and self.failure_note and \
                any(marker in self.failure_note.lower()
                    for marker in ("unknown user", "no such user",
                                   "wrong password", "disabled", "locked")):
            raise ValueError(
                "the login failure message must not distinguish an unknown "
                "username from a wrong password")


def build_login_page(*, authentication_configured: bool = False,
                     form_enabled: bool = False,
                     csrf_token: Optional[str] = None,
                     failed: bool = False, rate_limited: bool = False,
                     actor: Optional[str] = None, role: Optional[str] = None,
                     locale: str = "tr") -> LoginPageModel:
    """Build the page. Authenticated pages show the actor and nothing else.

    ``actor`` and ``role`` are the only identity on the page. There is no
    display name, no email address and no personal detail, because none is
    stored - so the page has nothing to leak even to the person it belongs to.
    """
    signed_in = bool(actor)
    return LoginPageModel(
        required_note=ui("login.required", locale),
        not_configured_note=ui("login.not_configured", locale),
        owner_note=ui("login.owner", locale),
        no_signup_note=ui("login.no_signup", locale),
        authentication_configured=bool(authentication_configured),
        logout_available=signed_in,
        logout_note=(ui("login.logout_available", locale) if signed_in
                     else ui("login.logout_unavailable", locale)),
        form_enabled=bool(form_enabled and csrf_token and not signed_in),
        # Carried whenever one exists, not only when the *login* form is
        # enabled. A signed-in visitor sees no login form and does see a
        # logout form, and that form needs a token too - dropping it here
        # left every sign-out failing CSRF with 403 while the button looked
        # perfectly ordinary. ``form_enabled`` still governs the login form
        # alone, which is the question it was asking.
        csrf_token=csrf_token,
        failed=bool(failed),
        failure_note=(ui("login.failed", locale) if failed else ""),
        rate_limited=bool(rate_limited),
        rate_limited_note=(ui("login.rate_limited", locale)
                           if rate_limited else ""),
        actor=display(actor, location="$.actor",
                      allow_none=True) if actor else None,
        role=role if signed_in else None,
        signed_in=signed_in)


@dataclass(frozen=True, slots=True)
class ErrorPageModel:
    """A controlled failure page.

    Carries the API's code, the controlled explanation for it and the request
    id. It carries no exception, no traceback, no path and no value the caller
    sent - and it has no field one could be put in.
    """

    code: str
    status: int
    guidance: str
    no_partial_note: str
    request_id: str
    home_url: str


def build_error_page(code: str, *, request_id: str = "",
                     locale: str = "tr") -> ErrorPageModel:
    from apps.api.errors import status_for_code
    from apps.web.errors import guidance_for

    return ErrorPageModel(
        code=display(code, location="$.code", allow_none=False),
        status=status_for_code(code),
        guidance=guidance_for(code, locale),
        no_partial_note=ui("error.no_partial", locale),
        request_id=display(request_id, location="$.request_id"),
        home_url=web_route("web.home").url())
