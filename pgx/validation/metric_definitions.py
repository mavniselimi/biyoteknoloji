# -*- coding: utf-8 -*-
"""The metric registry (WP-21): what every metric means, before any result.

The order matters and is the whole design. A metric defined after its first
result has been seen is not a measurement, it is a description of that result.
So every definition here - numerator, denominator, eligible roles, the exact
conditions under which the metric is unavailable - is written now, while this
repository has zero holdout cases and no active release, and therefore while
nobody can tune a definition to make a number look better.

Three consequences follow, and each is enforced rather than documented:

- **Thresholds are absent.** ``threshold`` is ``None`` for every metric in this
  file. A threshold is a policy decision with provenance, made by named people
  before results; there is no such policy, so there is no threshold. A
  threshold invented here would be a release criterion an implementer chose,
  which is the thing `architecture.md` section 17 lists as WP-21's non-goal.

- **Eligible roles are part of the definition.** A metric that may only be
  computed over holdout cases says so in its own record, so excluding
  development is not a rule the runner remembers to apply - it is a property
  of the metric that the runner reads.

- **Unavailability is enumerated.** Each metric names the reason codes that can
  make it unavailable. A metric that came back unavailable for a reason its
  definition never listed is a bug in the runner, and a test says so.

Nothing in this module computes anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Optional, Tuple

from pgx.validation.vocabulary import ValidationCaseRole

__all__ = [
    "FAILURE_PATH_CATALOGUE",
    "FAILURE_PATH_CATALOGUE_VERSION",
    "FailurePath",
    "METRIC_DEFINITIONS",
    "METRIC_IDS",
    "METRIC_REGISTRY_VERSION",
    "MetricDefinition",
    "MetricKind",
    "MetricStatus",
    "UNAVAILABLE_REASONS",
    "UnavailableReason",
    "definitions_by_id",
    "failure_paths_by_id",
    "registry_digest",
    "validation_evidence_metric_ids",
]

#: Bump when a definition changes meaning. A report carries this, so a number
#: computed under one registry version is never silently compared with a
#: number computed under another.
METRIC_REGISTRY_VERSION = "pgx-wp21-metric-registry/1"

#: The predeclared denominator for failure-path coverage. Versioned separately
#: because a new failure path is a change to what "complete" means, and that
#: must be visible even when no metric definition changed.
FAILURE_PATH_CATALOGUE_VERSION = "pgx-wp21-failure-paths/1"


class _MetricEnum(str, Enum):
    """String-valued and unordered, following the domain convention.

    Ordering is disabled deliberately. ``UNAVAILABLE`` is not "less than"
    ``AVAILABLE``; sorting a list of statuses would suggest a scale that does
    not exist, and the one place a scale would be actively harmful is a table
    a reader might skim for "how did we do".
    """

    def __str__(self) -> str:
        return self.value

    def __lt__(self, other: object) -> bool:  # pragma: no cover - guard
        raise TypeError("%s values are not ordered" % type(self).__name__)

    __le__ = __lt__
    __gt__ = __lt__
    __ge__ = __lt__


class MetricKind(_MetricEnum):
    """What shape a metric's value has.

    ``COUNT``
        A non-negative integer. Serialised as an integer, never as a float.

    ``RATE``
        A numerator over a denominator, serialised as a decimal string. A rate
        with a zero denominator has no value - not zero, not one hundred.

    ``DISTRIBUTION``
        A mapping from category to count, plus the denominator those counts
        are over. Used where collapsing to a single number would destroy the
        finding: expert agree/partial/disagree is three facts, not one.
    """

    COUNT = "COUNT"
    RATE = "RATE"
    DISTRIBUTION = "DISTRIBUTION"


class MetricStatus(_MetricEnum):
    """Why a metric's value is what it is - including why it is nothing.

    The distinction between the last four is the point of the enum. Collapsing
    them into "no value" would lose the only information a reader needs: who
    can change this, and what would have to happen.

    ``AVAILABLE``
        Computed from real observations. The value is a measurement.

    ``UNAVAILABLE``
        The benchmark ran and this metric could not be computed from it - most
        often a zero denominator. Something ran; this number does not exist.

    ``NOT_EXECUTED``
        No benchmark ran. Nobody looked. This is *not* a measured zero and the
        serialisation keeps them apart: ``value`` is null and ``denominator``
        is null too, where an ``UNAVAILABLE`` metric may report a real zero
        denominator it actually counted.

    ``BLOCKED``
        A precondition outside the metric's control failed - no active
        release, a dirty separation audit, restricted storage absent. The
        computation was refused rather than attempted.

    ``NOT_APPLICABLE``
        The metric genuinely does not apply to this benchmark's shape. Used
        sparingly; "does not apply" is a strong claim and is almost always
        really "unavailable".
    """

    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    NOT_EXECUTED = "NOT_EXECUTED"
    BLOCKED = "BLOCKED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class UnavailableReason(_MetricEnum):
    """Stable codes for why a metric has no value.

    A code, not a sentence, because a dashboard groups by it and a later work
    package will want to ask "which metrics are waiting on WP-22" without
    parsing prose.
    """

    ZERO_DENOMINATOR = "ZERO_DENOMINATOR"
    NO_ACTIVE_RELEASE = "NO_ACTIVE_RELEASE"
    NO_HOLDOUT_CASES = "NO_HOLDOUT_CASES"
    NO_REFERENCE_JUDGMENT = "NO_REFERENCE_JUDGMENT"
    # Replaced at WP-22. The protocol and the review module exist now; what
    # is absent is a completed review, which is a person's act. Keeping the
    # old code would have said WP-22 never happened.
    NO_COMPLETED_EXPERT_REVIEWS = "NO_COMPLETED_EXPERT_REVIEWS"
    SEPARATION_AUDIT_FAILED = "SEPARATION_AUDIT_FAILED"
    RESTRICTED_STORAGE_NOT_CONFIGURED = "RESTRICTED_STORAGE_NOT_CONFIGURED"
    RELEASE_NOT_PINNED = "RELEASE_NOT_PINNED"
    RELEASE_HASH_MISMATCH = "RELEASE_HASH_MISMATCH"
    CASE_MANIFEST_HASH_MISMATCH = "CASE_MANIFEST_HASH_MISMATCH"
    INPUT_INCOMPATIBLE = "INPUT_INCOMPATIBLE"
    BENCHMARK_NOT_EXECUTED = "BENCHMARK_NOT_EXECUTED"
    NO_ELIGIBLE_OBSERVATIONS = "NO_ELIGIBLE_OBSERVATIONS"


#: What each code means, in one line, for a reader who is not a developer.
UNAVAILABLE_REASONS: Mapping[str, str] = {
    UnavailableReason.ZERO_DENOMINATOR.value:
        "the denominator this metric divides by is zero, so there is no rate "
        "to report; zero and one hundred would both be inventions",
    UnavailableReason.NO_ACTIVE_RELEASE.value:
        "no release is registered or active, so nothing can be pinned and no "
        "benchmark can name what it measured",
    UnavailableReason.NO_HOLDOUT_CASES.value:
        "no case is held out from development, so nothing here measures "
        "generalisation",
    UnavailableReason.NO_REFERENCE_JUDGMENT.value:
        "this metric compares an output against a reference judgment, and no "
        "reference judgment has been supplied; WP-18 stores no expected "
        "answer, by design",
    UnavailableReason.NO_COMPLETED_EXPERT_REVIEWS.value:
        "this metric summarises what named experts decided under the blind "
        "protocol; the protocol and the review module exist and no expert "
        "has completed a review",
    UnavailableReason.SEPARATION_AUDIT_FAILED.value:
        "the development/holdout separation audit is not clean, so no metric "
        "may be computed from this case set at all",
    UnavailableReason.RESTRICTED_STORAGE_NOT_CONFIGURED.value:
        "holdout payloads live in restricted storage and none is configured, "
        "so the cases could not be executed",
    UnavailableReason.RELEASE_NOT_PINNED.value:
        "the benchmark plan does not pin one release with all required "
        "hashes",
    UnavailableReason.RELEASE_HASH_MISMATCH.value:
        "an observation names a release or manifest hash that disagrees with "
        "the pinned one",
    UnavailableReason.CASE_MANIFEST_HASH_MISMATCH.value:
        "the case manifest hash disagrees with the one the plan pinned",
    UnavailableReason.INPUT_INCOMPATIBLE.value:
        "the supplied input does not satisfy this metric's declared "
        "requirements",
    UnavailableReason.BENCHMARK_NOT_EXECUTED.value:
        "no benchmark run exists; nobody looked",
    UnavailableReason.NO_ELIGIBLE_OBSERVATIONS.value:
        "no observation in this run belongs to a role this metric may be "
        "computed over",
}


@dataclass(frozen=True, slots=True)
class FailurePath:
    """One way an assessment is allowed to refuse, named before it happens.

    The catalogue of these is the denominator for failure-path coverage. That
    denominator has to be predeclared: inferring it from the paths that
    happened to run would mean a benchmark exercising two paths and reporting
    "2/2 - complete", which is the most flattering possible reading of the
    least thorough possible run.
    """

    path_id: str
    title: str
    meaning: str
    expected_refusal: str

    def to_json(self) -> Mapping[str, object]:
        return {"path_id": self.path_id, "title": self.title,
                "meaning": self.meaning,
                "expected_refusal": self.expected_refusal}


#: The predeclared failure paths. Adding one changes the denominator, which is
#: why the catalogue carries its own version.
FAILURE_PATH_CATALOGUE: Tuple[FailurePath, ...] = (
    FailurePath(
        "FP-001", "Unsupported medication",
        "The medication is not in the pinned release's drug catalogue.",
        "NOT_ASSESSED with a coverage reason naming the medication; never "
        "LOW and never NO_ACTIVE_ATTENTION"),
    FailurePath(
        "FP-002", "Missing required gene or axis",
        "An axis the rule needs has no phenotype supplied.",
        "NOT_ASSESSED with coverage below FULL"),
    FailurePath(
        "FP-003", "Indeterminate phenotype",
        "A phenotype is supplied but is indeterminate for this axis.",
        "NOT_ASSESSED; indeterminate is not a calculated level"),
    FailurePath(
        "FP-004", "Partial coverage",
        "Some but not all required axes resolve.",
        "coverage PARTIAL, attention NOT_ASSESSED where the missing axis is "
        "load-bearing"),
    FailurePath(
        "FP-005", "Insufficient coverage",
        "Coverage is below the manifest's minimum for this medication.",
        "coverage INSUFFICIENT and refusal to emit an attention level"),
    FailurePath(
        "FP-006", "Conflicting sources or rules",
        "Two validated rules or two sources disagree for one axis.",
        "an explicit conflict outcome; never the more reassuring branch"),
    FailurePath(
        "FP-007", "No applicable validated rule",
        "The pinned ruleset holds no VALIDATED rule for this combination.",
        "NOT_ASSESSED; a DRAFT or DEPRECATED rule must not substitute"),
    FailurePath(
        "FP-008", "Invalid or unpinned release",
        "The release is missing, inactive, or its manifest hash disagrees.",
        "refusal before calculation; nothing persisted"),
    FailurePath(
        "FP-009", "Missing evidence reference",
        "A finding would be emitted with no resolvable evidence.",
        "refusal to emit the finding"),
    FailurePath(
        "FP-010", "Prohibited input kind or field",
        "The input carries a real-patient, genotype or raw-sequencing field.",
        "refusal at the input boundary, before any calculation"),
)


@dataclass(frozen=True, slots=True)
class MetricDefinition:
    """One metric, defined completely before any result exists.

    ``is_validation_evidence`` is the field that keeps this honest. A metric
    computed over development cases is a regression signal - useful, and not
    evidence about generalisation. Recording that on the definition rather
    than on the result means a development number cannot be relabelled later
    by whoever writes the report.
    """

    metric_id: str
    title: str
    plain_meaning: str
    kind: MetricKind
    numerator: str
    denominator: str
    eligible_roles: Tuple[ValidationCaseRole, ...]
    is_validation_evidence: bool
    required_inputs: Tuple[str, ...]
    unavailable_when: Tuple[UnavailableReason, ...]
    requires_expert_review: bool
    architecture_reference: str
    #: Decimal places for a RATE. Counts are integers and ignore this.
    decimal_places: int = 4
    #: ``None`` and, for now, necessarily ``None``. See the module docstring.
    threshold: Optional[float] = None
    threshold_provenance: Optional[str] = None
    #: Categories a DISTRIBUTION reports. Empty for other kinds.
    categories: Tuple[str, ...] = field(default_factory=tuple)
    note: str = ""

    def __post_init__(self) -> None:
        if not self.metric_id.startswith("PGX-VAL-"):
            raise ValueError("metric ids are PGX-VAL-*: %r" % self.metric_id)
        if self.threshold is not None and not self.threshold_provenance:
            raise ValueError(
                "%s carries a threshold with no provenance. A release "
                "threshold without a named, predeclared policy behind it is "
                "an implementer's opinion wearing a number's clothes."
                % self.metric_id)
        if self.kind is MetricKind.DISTRIBUTION and not self.categories:
            raise ValueError("%s is a distribution and names no categories"
                             % self.metric_id)
        if self.kind is not MetricKind.DISTRIBUTION and self.categories:
            raise ValueError("%s is not a distribution but names categories"
                             % self.metric_id)
        if self.is_validation_evidence and \
                ValidationCaseRole.DEVELOPMENT in self.eligible_roles:
            raise ValueError(
                "%s claims to be validation evidence and accepts DEVELOPMENT "
                "cases. Those cannot both be true: a development case shaped "
                "the software it would be measuring." % self.metric_id)
        if not self.eligible_roles:
            raise ValueError("%s names no eligible role" % self.metric_id)
        if not self.unavailable_when:
            raise ValueError(
                "%s lists no way to be unavailable. Every metric here can be "
                "unavailable; a metric that cannot is one that will report a "
                "number when it should report nothing." % self.metric_id)

    def accepts(self, role: ValidationCaseRole) -> bool:
        return role in self.eligible_roles

    def to_json(self) -> Mapping[str, object]:
        return {
            "metric_id": self.metric_id,
            "title": self.title,
            "plain_meaning": self.plain_meaning,
            "kind": self.kind.value,
            "numerator": self.numerator,
            "denominator": self.denominator,
            "eligible_roles": [role.value for role in self.eligible_roles],
            "is_validation_evidence": self.is_validation_evidence,
            "required_inputs": list(self.required_inputs),
            "unavailable_when": [reason.value
                                 for reason in self.unavailable_when],
            "requires_expert_review": self.requires_expert_review,
            "architecture_reference": self.architecture_reference,
            "decimal_places": self.decimal_places,
            "threshold": self.threshold,
            "threshold_provenance": self.threshold_provenance,
            "categories": list(self.categories),
            "note": self.note,
        }


_HOLDOUT = (ValidationCaseRole.INTERNAL_HOLDOUT,
            ValidationCaseRole.EXPERT_HOLDOUT)
_DEV = (ValidationCaseRole.DEVELOPMENT,)
_ALL = _DEV + _HOLDOUT
_R = UnavailableReason

#: Preconditions every metric shares. Listed on each definition rather than
#: implied, so a reader of one record sees the whole story.
_COMMON = (_R.BENCHMARK_NOT_EXECUTED, _R.NO_ACTIVE_RELEASE,
           _R.RELEASE_NOT_PINNED, _R.SEPARATION_AUDIT_FAILED,
           _R.RELEASE_HASH_MISMATCH, _R.CASE_MANIFEST_HASH_MISMATCH)

METRIC_DEFINITIONS: Tuple[MetricDefinition, ...] = (
    MetricDefinition(
        metric_id="PGX-VAL-001",
        title="Guideline and rule concordance",
        plain_meaning="Of the eligible cases where a reference judgment says "
                      "what the answer should be, how many did the system "
                      "match exactly.",
        kind=MetricKind.RATE,
        numerator="eligible observations whose calculated attention level, "
                  "coverage status and firing rule identity all equal the "
                  "reference judgment's",
        denominator="eligible observations that have a supplied reference "
                    "judgment for the pinned release",
        eligible_roles=_HOLDOUT,
        is_validation_evidence=True,
        required_inputs=("pinned release", "eligible holdout observations",
                         "immutable reference judgments"),
        unavailable_when=_COMMON + (_R.ZERO_DENOMINATOR, _R.NO_HOLDOUT_CASES,
                                    _R.NO_REFERENCE_JUDGMENT,
                                    _R.RESTRICTED_STORAGE_NOT_CONFIGURED,
                                    _R.NO_ELIGIBLE_OBSERVATIONS),
        requires_expert_review=False,
        architecture_reference="architecture.md section 12.3, first bullet",
        note="WP-18 deliberately stores no expected answer, so the "
             "denominator counts supplied reference judgments and not cases. "
             "With no judgment port wired, this is NO_REFERENCE_JUDGMENT and "
             "not a zero.",
    ),
    MetricDefinition(
        metric_id="PGX-VAL-002",
        title="Coverage correctness",
        plain_meaning="Of the eligible cases with a reference judgment, how "
                      "many had exactly the right coverage status and reason "
                      "code - independently of whether the attention level "
                      "matched.",
        kind=MetricKind.RATE,
        numerator="eligible observations whose coverage status and coverage "
                  "reason code equal the reference judgment's",
        denominator="eligible observations that have a supplied reference "
                    "judgment for the pinned release",
        eligible_roles=_HOLDOUT,
        is_validation_evidence=True,
        required_inputs=("pinned release", "eligible holdout observations",
                         "immutable reference judgments"),
        unavailable_when=_COMMON + (_R.ZERO_DENOMINATOR, _R.NO_HOLDOUT_CASES,
                                    _R.NO_REFERENCE_JUDGMENT,
                                    _R.RESTRICTED_STORAGE_NOT_CONFIGURED,
                                    _R.NO_ELIGIBLE_OBSERVATIONS),
        requires_expert_review=False,
        architecture_reference="architecture.md sections 9.2 and 12.3",
        note="Kept separate from concordance on purpose. Right answer, wrong "
             "coverage reason is a real defect that a combined metric hides.",
    ),
    MetricDefinition(
        metric_id="PGX-VAL-003",
        title="Unsafe false reassurance",
        plain_meaning="How many eligible cases produced LOW or "
                      "NO_ACTIVE_ATTENTION when the required inputs were "
                      "absent - a reader told 'no risk' where the truth is "
                      "'we did not look'.",
        kind=MetricKind.COUNT,
        numerator="eligible observations emitting LOW or NO_ACTIVE_ATTENTION "
                  "while coverage was not FULL",
        denominator="eligible observations executed under the pinned release",
        eligible_roles=_HOLDOUT,
        is_validation_evidence=True,
        required_inputs=("pinned release", "eligible holdout observations"),
        unavailable_when=_COMMON + (_R.NO_HOLDOUT_CASES,
                                    _R.RESTRICTED_STORAGE_NOT_CONFIGURED,
                                    _R.NO_ELIGIBLE_OBSERVATIONS),
        requires_expert_review=False,
        architecture_reference="architecture.md sections 3 and 12.3; "
                               "SAFETY-INV-001",
        note="This is NOT WP-20's detector result. WP-20 proved that a "
             "detector rejects 36 constructed unsafe states; that says "
             "nothing about how a real case behaves under a real release. "
             "Reusing that number here would be the exact substitution this "
             "work package exists to prevent.",
    ),
    MetricDefinition(
        metric_id="PGX-VAL-004",
        title="Unsafe false reassurance rate",
        plain_meaning="The same finding as a proportion of eligible cases.",
        kind=MetricKind.RATE,
        numerator="the PGX-VAL-003 count",
        denominator="eligible observations executed under the pinned release",
        eligible_roles=_HOLDOUT,
        is_validation_evidence=True,
        required_inputs=("pinned release", "eligible holdout observations"),
        unavailable_when=_COMMON + (_R.ZERO_DENOMINATOR, _R.NO_HOLDOUT_CASES,
                                    _R.RESTRICTED_STORAGE_NOT_CONFIGURED,
                                    _R.NO_ELIGIBLE_OBSERVATIONS),
        requires_expert_review=False,
        architecture_reference="architecture.md section 12.3, third bullet",
        note="A zero here is only meaningful beside its denominator. Zero "
             "over zero is unavailable, and the artifact keeps both numbers "
             "so a reader never has to trust the ratio alone.",
    ),
    MetricDefinition(
        metric_id="PGX-VAL-005",
        title="Evidence traceability",
        plain_meaning="How many emitted findings carried at least one "
                      "evidence reference that resolves inside the pinned "
                      "release.",
        kind=MetricKind.COUNT,
        numerator="emitted findings with at least one resolvable, pinned "
                  "evidence reference",
        denominator="emitted findings across eligible observations",
        eligible_roles=_HOLDOUT,
        is_validation_evidence=True,
        required_inputs=("pinned release", "eligible holdout observations",
                         "the release's evidence index"),
        unavailable_when=_COMMON + (_R.NO_HOLDOUT_CASES,
                                    _R.RESTRICTED_STORAGE_NOT_CONFIGURED,
                                    _R.NO_ELIGIBLE_OBSERVATIONS),
        requires_expert_review=False,
        architecture_reference="architecture.md section 12.3; SAFETY-INV-006",
        note="The denominator is findings, not cases. One case can emit "
             "several findings and a case-level denominator would let a "
             "single untraceable finding hide behind a traceable sibling.",
    ),
    MetricDefinition(
        metric_id="PGX-VAL-006",
        title="Evidence traceability rate",
        plain_meaning="The same finding as a proportion of emitted findings.",
        kind=MetricKind.RATE,
        numerator="the PGX-VAL-005 count",
        denominator="emitted findings across eligible observations",
        eligible_roles=_HOLDOUT,
        is_validation_evidence=True,
        required_inputs=("pinned release", "eligible holdout observations",
                         "the release's evidence index"),
        unavailable_when=_COMMON + (_R.ZERO_DENOMINATOR, _R.NO_HOLDOUT_CASES,
                                    _R.RESTRICTED_STORAGE_NOT_CONFIGURED,
                                    _R.NO_ELIGIBLE_OBSERVATIONS),
        requires_expert_review=False,
        architecture_reference="architecture.md section 12.3, fourth bullet",
    ),
    MetricDefinition(
        metric_id="PGX-VAL-007",
        title="Deterministic repeatability",
        plain_meaning="How many eligible cases produced a byte-identical "
                      "result on every repeat under the same pinned release.",
        kind=MetricKind.COUNT,
        numerator="eligible observations whose output hash was identical "
                  "across every declared repeat",
        denominator="eligible observations executed with at least two "
                    "declared repeats",
        eligible_roles=_ALL,
        is_validation_evidence=False,
        required_inputs=("pinned release", "observations",
                         "a repeat count of at least two"),
        unavailable_when=_COMMON + (_R.NO_ELIGIBLE_OBSERVATIONS,
                                    _R.INPUT_INCOMPATIBLE),
        requires_expert_review=False,
        architecture_reference="architecture.md sections 9.6 and 12.3; "
                               "SAFETY-INV-012",
        note="Computable over development cases too, because determinism is a "
             "software property rather than a scientific claim - so this is "
             "reported per role and marked not-validation-evidence. A single "
             "repeat cannot show repeatability, so the denominator counts "
             "only observations that actually repeated.",
    ),
    MetricDefinition(
        metric_id="PGX-VAL-008",
        title="Deterministic repeatability rate",
        plain_meaning="The same finding as a proportion of repeated cases.",
        kind=MetricKind.RATE,
        numerator="the PGX-VAL-007 count",
        denominator="eligible observations executed with at least two "
                    "declared repeats",
        eligible_roles=_ALL,
        is_validation_evidence=False,
        required_inputs=("pinned release", "observations",
                         "a repeat count of at least two"),
        unavailable_when=_COMMON + (_R.ZERO_DENOMINATOR,
                                    _R.NO_ELIGIBLE_OBSERVATIONS,
                                    _R.INPUT_INCOMPATIBLE),
        requires_expert_review=False,
        architecture_reference="architecture.md section 12.3, fifth bullet",
    ),
    MetricDefinition(
        metric_id="PGX-VAL-009",
        title="Holdout pass count",
        plain_meaning="How many holdout cases the system got fully right - "
                      "attention, coverage and evidence all correct against "
                      "the reference judgment.",
        kind=MetricKind.COUNT,
        numerator="holdout observations satisfying concordance, coverage "
                  "correctness and evidence traceability together",
        denominator="holdout observations with a supplied reference judgment",
        eligible_roles=_HOLDOUT,
        is_validation_evidence=True,
        required_inputs=("pinned release", "holdout observations",
                         "immutable reference judgments"),
        unavailable_when=_COMMON + (_R.NO_HOLDOUT_CASES,
                                    _R.NO_REFERENCE_JUDGMENT,
                                    _R.RESTRICTED_STORAGE_NOT_CONFIGURED,
                                    _R.NO_ELIGIBLE_OBSERVATIONS),
        requires_expert_review=False,
        architecture_reference="architecture.md section 12.3, sixth bullet",
        note="Reported separately for INTERNAL_HOLDOUT and EXPERT_HOLDOUT. "
             "There is no combined holdout figure: the two partitions answer "
             "different questions and pooling them would let a large, easy "
             "partition carry a small, hard one.",
    ),
    MetricDefinition(
        metric_id="PGX-VAL-010",
        title="Holdout pass rate",
        plain_meaning="The same finding as a proportion of judged holdout "
                      "cases.",
        kind=MetricKind.RATE,
        numerator="the PGX-VAL-009 count",
        denominator="holdout observations with a supplied reference judgment",
        eligible_roles=_HOLDOUT,
        is_validation_evidence=True,
        required_inputs=("pinned release", "holdout observations",
                         "immutable reference judgments"),
        unavailable_when=_COMMON + (_R.ZERO_DENOMINATOR, _R.NO_HOLDOUT_CASES,
                                    _R.NO_REFERENCE_JUDGMENT,
                                    _R.RESTRICTED_STORAGE_NOT_CONFIGURED,
                                    _R.NO_ELIGIBLE_OBSERVATIONS),
        requires_expert_review=False,
        architecture_reference="architecture.md section 12.3, sixth bullet",
    ),
    MetricDefinition(
        metric_id="PGX-VAL-011",
        title="Expert agreement distribution",
        plain_meaning="How named expert reviewers judged the system's output "
                      "on expert-holdout cases: agree, partially agree, or "
                      "disagree.",
        kind=MetricKind.DISTRIBUTION,
        numerator="expert decisions in each category",
        denominator="expert-holdout observations with a completed, "
                    "post-reveal expert decision",
        eligible_roles=(ValidationCaseRole.EXPERT_HOLDOUT,),
        is_validation_evidence=True,
        required_inputs=("pinned release", "expert-holdout observations",
                         "completed WP-22 expert review records"),
        unavailable_when=_COMMON + (_R.ZERO_DENOMINATOR,
                                    _R.NO_HOLDOUT_CASES,
                                    _R.NO_COMPLETED_EXPERT_REVIEWS,
                                    _R.RESTRICTED_STORAGE_NOT_CONFIGURED,
                                    _R.NO_ELIGIBLE_OBSERVATIONS),
        requires_expert_review=True,
        architecture_reference="architecture.md sections 12.3 and 17, WP-22",
        categories=("AGREE", "PARTIAL", "DISAGREE"),
        note="Three counts, never one score. Collapsing agree/partial/"
             "disagree into a single percentage would hide whether the "
             "disagreements clustered on the dangerous cases.",
    ),
    MetricDefinition(
        metric_id="PGX-VAL-012",
        title="Expert Likert dimensions",
        plain_meaning="Optional expert ratings on declared dimensions such as "
                      "clarity and clinical usefulness.",
        kind=MetricKind.DISTRIBUTION,
        numerator="expert ratings at each Likert point, per dimension",
        denominator="expert-holdout observations with a completed rating for "
                    "that dimension",
        eligible_roles=(ValidationCaseRole.EXPERT_HOLDOUT,),
        is_validation_evidence=True,
        required_inputs=("pinned release", "expert-holdout observations",
                         "completed WP-22 Likert responses"),
        unavailable_when=_COMMON + (_R.ZERO_DENOMINATOR,
                                    _R.NO_HOLDOUT_CASES,
                                    _R.NO_COMPLETED_EXPERT_REVIEWS,
                                    _R.RESTRICTED_STORAGE_NOT_CONFIGURED,
                                    _R.NO_ELIGIBLE_OBSERVATIONS),
        requires_expert_review=True,
        architecture_reference="architecture.md section 12.3, eighth bullet",
        categories=("1", "2", "3", "4", "5"),
        note="Optional in the architecture, so its absence is not itself a "
             "blocker; it is unavailable like any other unmeasured thing.",
    ),
    MetricDefinition(
        metric_id="PGX-VAL-013",
        title="Unresolved source conflicts",
        plain_meaning="How many eligible cases ended with two validated "
                      "sources or rules disagreeing and no declared "
                      "precedence to settle it.",
        kind=MetricKind.COUNT,
        numerator="eligible observations reporting a conflict with no "
                  "applicable precedence rule",
        denominator="eligible observations executed under the pinned release",
        eligible_roles=_ALL,
        is_validation_evidence=False,
        required_inputs=("pinned release", "observations"),
        unavailable_when=_COMMON + (_R.NO_ELIGIBLE_OBSERVATIONS,),
        requires_expert_review=False,
        architecture_reference="architecture.md section 12.3, ninth bullet; "
                               "SAFETY-INV-008",
        note="A count with no rate on purpose. One unresolved conflict is a "
             "finding to act on; expressing it as a small percentage of a "
             "large run would make it look like noise.",
    ),
    MetricDefinition(
        metric_id="PGX-VAL-014",
        title="Failure-path coverage",
        plain_meaning="How many of the predeclared failure paths this "
                      "benchmark actually exercised.",
        kind=MetricKind.COUNT,
        numerator="distinct failure path ids from the catalogue observed at "
                  "least once in this run",
        denominator="the size of the predeclared failure-path catalogue",
        eligible_roles=_ALL,
        is_validation_evidence=False,
        required_inputs=("pinned release", "observations",
                         "the predeclared failure-path catalogue"),
        unavailable_when=_COMMON + (_R.NO_ELIGIBLE_OBSERVATIONS,),
        requires_expert_review=False,
        architecture_reference="architecture.md section 12.3, tenth bullet",
        note="The denominator is the catalogue, never the set of paths that "
             "happened to run. A run touching two paths reports 2/10, not "
             "2/2.",
    ),
    MetricDefinition(
        metric_id="PGX-VAL-015",
        title="Failure-path coverage rate",
        plain_meaning="The same finding as a proportion of the catalogue.",
        kind=MetricKind.RATE,
        numerator="the PGX-VAL-014 count",
        denominator="the size of the predeclared failure-path catalogue",
        eligible_roles=_ALL,
        is_validation_evidence=False,
        required_inputs=("pinned release", "observations",
                         "the predeclared failure-path catalogue"),
        unavailable_when=_COMMON + (_R.ZERO_DENOMINATOR,
                                    _R.NO_ELIGIBLE_OBSERVATIONS),
        requires_expert_review=False,
        architecture_reference="architecture.md section 12.3, tenth bullet",
    ),
)

#: Every metric id, in registry order.
METRIC_IDS: Tuple[str, ...] = tuple(
    definition.metric_id for definition in METRIC_DEFINITIONS)


def definitions_by_id() -> Mapping[str, MetricDefinition]:
    """The registry as a lookup. Built fresh; the tuple stays authoritative."""
    return {definition.metric_id: definition
            for definition in METRIC_DEFINITIONS}


def failure_paths_by_id() -> Mapping[str, FailurePath]:
    return {path.path_id: path for path in FAILURE_PATH_CATALOGUE}


def validation_evidence_metric_ids() -> Tuple[str, ...]:
    """The metrics whose values, if ever available, are validation evidence."""
    return tuple(definition.metric_id for definition in METRIC_DEFINITIONS
                 if definition.is_validation_evidence)


def registry_digest() -> str:
    """A hash over every definition, pinned into each benchmark plan.

    A report that names this digest can be checked against the registry that
    produced it, so a definition edited after the fact is visible rather than
    silently applied to old numbers.
    """
    from pgx.domain.hashing import sha256_digest
    return sha256_digest({
        "metric_registry_version": METRIC_REGISTRY_VERSION,
        "failure_path_catalogue_version": FAILURE_PATH_CATALOGUE_VERSION,
        "metrics": [definition.to_json()
                    for definition in METRIC_DEFINITIONS],
        "failure_paths": [path.to_json()
                          for path in FAILURE_PATH_CATALOGUE],
    })
