# -*- coding: utf-8 -*-
"""The final representative demonstration, and its preflight (WP-25).

A demo script that runs to the end regardless of what is behind it is a
screen recording, not evidence. So this module separates two things that are
usually written as one:

**The manifest** - the ten steps of the representative workflow, each with the
preconditions that must hold before it can be attempted, and each naming the
artifact and field the precondition is read from.

**The preflight** - an evaluation of those preconditions, in order, that
*stops at the first unmet one*. It does not carry on to see what else fails,
and it never executes a step whose preconditions are not met. Continuing past
a failed precondition produces a demonstration of the fallback path presented
as a demonstration of the system, which is the specific dishonesty this
module exists to prevent.

Three environment conditions are checked separately from the steps, because
they are requirements *of* the demonstration rather than obstacles to it: the
network must be unavailable, the language model must be off, and every P1
feature must be off. A demo that needed any of them would not be the demo the
Definition of Done describes.

There is no ``--force``, no ``--skip-preconditions`` and no fixture mode. The
preflight's answer for this repository is BLOCKED, and the correct response
to that is to fix the programme, not the preflight.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from pgx.ths6.evidence_registry import (field_at, field_is_missing,
                                        read_document)
from pgx.ths6.models import repository_relative
from pgx.ths6.vocabulary import BLOCKER_CODES, Blocker, EXIT_BLOCKED

__all__ = [
    "DEMO_MANIFEST_VERSION",
    "p1_surface_markers",
    "DEMO_STEPS",
    "ENVIRONMENT_CONDITIONS",
    "DemoStep",
    "build_demo_manifest",
    "run_demo_preflight",
]

DEMO_MANIFEST_VERSION = "pgx-wp25-demo-manifest/1"


@dataclass(frozen=True)
class Precondition:
    """One thing that must hold before a step may be attempted."""

    description: str
    source_path: str
    source_field: str
    #: The value the field must have. ``_AT_LEAST_ONE`` is a sentinel for
    #: "any positive integer", spelled as an object so a precondition cannot
    #: accidentally be satisfied by ``True``.
    required: object
    blocker_code: str
    owner: str

    def __post_init__(self) -> None:
        repository_relative(self.source_path)
        if self.blocker_code not in BLOCKER_CODES:
            raise ValueError("undeclared blocker %r" % (self.blocker_code,))

    def evaluate(self, root: str) -> Tuple[Optional[bool], str]:
        document = read_document(root, self.source_path)
        if document is None:
            return None, "artifact unreadable"
        value = field_at(document, self.source_field)
        if field_is_missing(value):
            return None, "field absent"
        if self.required is _AT_LEAST_ONE:
            met = (isinstance(value, int) and not isinstance(value, bool)
                   and value >= 1)
        else:
            met = value == self.required and (
                isinstance(value, bool) == isinstance(self.required, bool))
        return met, repr(value)


class _AtLeastOne:
    def __repr__(self) -> str:
        return "at least one"


#: "Any positive integer". A distinct object rather than the integer 1 so a
#: precondition reading ``True`` from a boolean field cannot satisfy it.
_AT_LEAST_ONE = _AtLeastOne()


@dataclass(frozen=True)
class DemoStep:
    """One step of the representative workflow."""

    step_id: str
    title: str
    #: What a viewer would see. Written so that a step which produced an
    #: empty state could not be described as having produced this.
    observable_outcome: str
    preconditions: Tuple[Precondition, ...]


_WP11 = "data/rulesets/wp11-real-gate-status.json"
_WP13 = "data/coverage/wp13-real-gate-status.json"
_WP14 = "data/assessments/wp14-real-gate-status.json"
_WP15 = "data/reports/wp15-real-gate-status.json"
_WP16 = "data/api/wp16-real-gate-status.json"
_WP17 = "data/web/wp17-real-gate-status.json"
_WP20 = "data/safety/wp20-real-gate-status.json"
_WP21 = "data/validation/wp21-real-gate-status.json"
_WP23 = "data/security/wp23-real-gate-status.json"
_WP24 = "data/deployment/wp24-real-gate-status.json"


def _p(description, path, field, required, code, owner):
    return Precondition(description=description, source_path=path,
                        source_field=field, required=required,
                        blocker_code=code, owner=owner)


#: The representative workflow, in order. Ten steps, because that is how many
#: distinct things have to work; a shorter list would be a shorter demo.
DEMO_STEPS: Tuple[DemoStep, ...] = (
    DemoStep(
        "DEMO-01", "Serve the interface with no network available",
        "the case selection page renders from local templates and local "
        "assets, with no outbound request attempted",
        (_p("the interface templates are present and render here", _WP17,
            "template_runtime_available", True,
            "THS6_DEMO_NOT_EXECUTED", "platform owner"),
         _p("the declared templates match the allowlist", _WP17,
            "templates_match_allowlist", True,
            "THS6_DEMO_NOT_EXECUTED", "platform owner"))),
    DemoStep(
        "DEMO-02", "Choose a case from the governed catalogue",
        "a case drawn from approved, governed content is listed and "
        "selectable - not a development fixture",
        (_p("at least one approved scientific source exists", _WP11,
            "upstream_state.source_registry_approved", _AT_LEAST_ONE,
            "THS6_NO_APPROVED_SOURCE", "scientific source approver"),
         _p("a canonical dataset is published", _WP11,
            "upstream_state.canonical_dataset_published", True,
            "THS6_DATASET_NOT_PUBLISHED", "data owner"))),
    DemoStep(
        "DEMO-03", "Resolve the active release version bundle",
        "the page names the software version, the dataset version and the "
        "ruleset version the result will be computed against",
        (_p("a release is active", _WP20, "active_release_available", True,
            "THS6_NO_ACTIVE_RELEASE", "release approver"),
         _p("the default registry holds an executable ruleset", _WP11,
            "rule_state.executable_rulesets_in_default_registry",
            _AT_LEAST_ONE, "THS6_NO_EXECUTABLE_RULESET", "curation lead"))),
    DemoStep(
        "DEMO-04", "Submit a phenotype profile",
        "the submitted profile is accepted, normalised and echoed back with "
        "its exact interpretation",
        (_p("at least one rule is validated", _WP11,
            "rule_state.real_validated_rules", _AT_LEAST_ONE,
            "THS6_NO_APPROVED_RULE", "curation lead"),)),
    DemoStep(
        "DEMO-05", "Compute coverage and display it as its own axis",
        "coverage is shown separately from risk, and anything not covered is "
        "shown as not covered rather than as low risk",
        (_p("at least one coverage execution exists over governed content",
            _WP13, "coverage_state.real_coverage_executions", _AT_LEAST_ONE,
            "THS6_NO_COVERAGE_EXECUTION", "curation lead"),
         _p("at least one axis is supported", _WP13,
            "coverage_state.real_supported_axes", _AT_LEAST_ONE,
            "THS6_NO_COVERAGE_EXECUTION", "curation lead"))),
    DemoStep(
        "DEMO-06", "Compute the assessment deterministically",
        "the assessment completes and the same input recomputed yields "
        "byte-identical facts",
        (_p("at least one assessment has been computed from governed "
            "content", _WP14, "assessment_state.real_completed_assessments",
            _AT_LEAST_ONE, "THS6_NO_REAL_ASSESSMENT", "curation lead"),)),
    DemoStep(
        "DEMO-07", "Render the report with evidence links",
        "each finding in the report links to the governed evidence record it "
        "came from",
        (_p("at least one report exists", _WP15, "real_report_count",
            _AT_LEAST_ONE, "THS6_NO_REAL_ASSESSMENT", "curation lead"),
         _p("the claim boundary is approved", _WP20,
            "claim_boundary_approved", True,
            "THS6_CLAIM_BOUNDARY_NOT_APPROVED",
            "clinical safety authority"))),
    DemoStep(
        "DEMO-08", "Record the governed audit event",
        "an audit event with actor, time, input hash, version bundle and "
        "output hash is written and the chain verifies",
        (_p("an audit store is available", _WP23, "audit_store_available",
            True, "THS6_DATABASE_UNAVAILABLE", "platform owner"),
         _p("the audit chain has been verified", _WP23,
            "audit_chain_verified", True, "THS6_AUDIT_CHAIN_UNVERIFIED",
            "platform owner"))),
    DemoStep(
        "DEMO-09", "Show the validation dashboard with release metrics",
        "the dashboard shows metric values attributed to the active release, "
        "not an empty state",
        (_p("at least one metric has a computed value", _WP21,
            "computed_metric_value_count", _AT_LEAST_ONE,
            "THS6_NO_COMPUTED_METRIC", "validation owner"),
         _p("the dashboard is populated rather than empty", _WP17,
            "validation_dashboard_status", "POPULATED",
            "THS6_NO_COMPUTED_METRIC", "validation owner"))),
    DemoStep(
        "DEMO-10", "Serve the whole run from a deployed staging prototype",
        "the demonstration is performed against a deployed environment "
        "answering health checks, not a developer's laptop",
        (_p("a container runtime is available", _WP24,
            "container_runtime_available", True,
            "THS6_CONTAINER_RUNTIME_UNAVAILABLE", "platform owner"),
         _p("the API has served a real assessment", _WP16,
            "real_api_assessment_count", _AT_LEAST_ONE,
            "THS6_NO_REAL_ASSESSMENT", "platform owner"))),
)


def _llm_state() -> Mapping[str, object]:
    """Read the reporting layer's own switch rather than asserting it off."""
    try:
        from pgx.reporting.llm import LLM_ENABLED, LLM_PROVIDER
    except Exception:  # pragma: no cover - module removed
        return {"readable": False, "enabled": None, "provider": None}
    return {"readable": True, "enabled": bool(LLM_ENABLED),
            "provider": LLM_PROVIDER}


def environment_conditions(root: str = ".") -> Tuple[Mapping[str, object],
                                                     ...]:
    """The three conditions the demonstration must satisfy to count.

    Requirements of the demo rather than obstacles to it: a demonstration
    that needed the network, the language model or a P1 feature would not be
    the demonstration the Definition of Done describes.
    """
    llm = _llm_state()
    document = read_document(root, _WP24)
    index_reachable = field_at(document, "package_index_reachable")
    return (
        {"condition_id": "DEMO-ENV-01",
         "description": "the network is unavailable to the demonstration",
         "source": "%s.package_index_reachable" % _WP24,
         "observed": (None if field_is_missing(index_reachable)
                      else index_reachable),
         "required": False,
         "met": (None if field_is_missing(index_reachable)
                 else index_reachable is False),
         "note": "reachability of a package index is the strongest network "
                 "signal this repository records; it is evidence about the "
                 "environment, not proof that a running demo made no "
                 "outbound request"},
        {"condition_id": "DEMO-ENV-02",
         "description": "the language model is off",
         "source": "pgx/reporting/llm.py:LLM_ENABLED",
         "observed": llm["enabled"],
         "required": False,
         "met": (llm["enabled"] is False) if llm["readable"] else None,
         "note": "read from the module constant rather than asserted; the "
                 "reporting layer refuses with REPORT_LLM_DISABLED when it "
                 "is off"},
        {"condition_id": "DEMO-ENV-03",
         "description": "every P1 feature is off",
         "source": "pgx/safety/definitions.py: absence markers of every "
                   "invariant whose blocker is owned by P1",
         "observed": _p1_surface_state(root),
         "required": "NOT_PRESENT",
         "met": _p1_surface_state(root) == "NOT_PRESENT",
         "markers_checked": list(p1_surface_markers()),
         "note": "checked by looking for the modules that would implement "
                 "each P1 surface, not by reading a flag: a default-off flag "
                 "in a build that ships the feature is a flag somebody can "
                 "turn on"},
    )


def p1_surface_markers() -> Tuple[str, ...]:
    """The files whose existence would mean a P1 feature had been added.

    Taken from the safety definitions rather than written out again here:
    WP-20 already declares, per invariant, which modules must not exist for
    the P1 surface it guards to be absent, and duplicating that list would
    give the project two answers to one question.
    """
    try:
        from pgx.safety.definitions import INVARIANT_DEFINITIONS
    except Exception:  # pragma: no cover - module removed
        return ()
    markers: List[str] = []
    for invariant in INVARIANT_DEFINITIONS:
        owned_by_p1 = any(
            "P1" in str(getattr(blocker, "owner", ""))
            for blocker in getattr(invariant, "blockers", ()))
        if owned_by_p1:
            markers.extend(getattr(invariant, "absence_markers", ()))
    return tuple(sorted(set(markers)))


def _p1_surface_state(root: str = ".") -> str:
    """Whether every P1 surface is genuinely absent from this tree.

    A filesystem observation, not a declaration: the question "is the P1
    feature off" is answered by looking for the modules that would implement
    it, because a flag defaulting to off in a build that ships the feature is
    a flag somebody can turn on.
    """
    markers = p1_surface_markers()
    if not markers:
        return "UNREADABLE"
    present = [path for path in markers
               if os.path.exists(os.path.join(root, *path.split("/")))]
    return "NOT_PRESENT" if not present else "PRESENT: %s" % ", ".join(
        sorted(present))


def build_demo_manifest(root: str = ".") -> Mapping[str, object]:
    """The demonstration as declared, before anything is evaluated.

    Deterministic: every field is a declaration, so two machines checking out
    the same commit produce identical bytes. ``root`` is accepted only so the
    declared environment requirements can be built from the same code path
    the preflight measures them with.
    """
    return {
        "demo_manifest_version": DEMO_MANIFEST_VERSION,
        "step_count": len(DEMO_STEPS),
        "steps": [
            {"step_id": step.step_id, "title": step.title,
             "observable_outcome": step.observable_outcome,
             "precondition_count": len(step.preconditions),
             "preconditions": [
                 {"description": item.description,
                  "source_path": item.source_path,
                  "source_field": item.source_field,
                  "required": (repr(item.required)
                               if item.required is _AT_LEAST_ONE
                               else item.required),
                  "blocker_code": item.blocker_code, "owner": item.owner}
                 for item in step.preconditions]}
            for step in DEMO_STEPS],
        # Declared, never observed. The manifest says what the
        # demonstration requires; the preflight is where those requirements
        # are measured. Keeping the observation out of the manifest is what
        # lets the manifest be compared byte for byte between machines - a
        # document that measured the host would differ between two honest
        # builds and would teach a team to ignore the comparison.
        "environment_requirements": [
            {"condition_id": item["condition_id"],
             "description": item["description"],
             "source": item["source"], "required": item["required"],
             "note": item["note"]}
            for item in environment_conditions(root)],
        "force_available": False,
        "note": (
            "The preflight stops at the first unmet precondition and does "
            "not execute the step it guards. There is no force flag and no "
            "fixture mode."),
    }


def run_demo_preflight(root: str = ".") -> Mapping[str, object]:
    """Evaluate preconditions in order, stopping at the first unmet one."""
    evaluated: List[Mapping[str, object]] = []
    blockers: List[Blocker] = []
    stopped_at: Optional[str] = None
    for step in DEMO_STEPS:
        if stopped_at is not None:
            evaluated.append({
                "step_id": step.step_id, "title": step.title,
                "state": "NOT_ATTEMPTED",
                "reason": "an earlier step's precondition was not met, and "
                          "the preflight does not evaluate past the first "
                          "stop",
                "preconditions": []})
            continue
        results = []
        step_met = True
        for item in step.preconditions:
            met, observed = item.evaluate(root)
            results.append({
                "description": item.description,
                "source_path": item.source_path,
                "source_field": item.source_field,
                "observed": observed,
                "met": met})
            if met is not True:
                step_met = False
                blockers.append(Blocker(
                    code=item.blocker_code,
                    detail="%s: %s (observed %s)"
                           % (step.step_id, item.description, observed),
                    owner=item.owner))
                break
        evaluated.append({
            "step_id": step.step_id, "title": step.title,
            "state": "PRECONDITIONS_MET" if step_met else "BLOCKED",
            "reason": ("every precondition holds; the step was not executed "
                       "because a later one is blocked" if step_met else
                       "a precondition is not met"),
            "preconditions": results})
        if not step_met:
            stopped_at = step.step_id
    environment = list(environment_conditions(root))
    unmet_environment = [item["condition_id"] for item in environment
                         if item["met"] is not True]
    ready = stopped_at is None and not unmet_environment
    return {
        "demo_manifest_version": DEMO_MANIFEST_VERSION,
        "step_count": len(DEMO_STEPS),
        "stopped_at_step_id": stopped_at,
        "steps_with_preconditions_met": sum(
            1 for item in evaluated
            if item["state"] == "PRECONDITIONS_MET"),
        "steps_not_attempted": sum(1 for item in evaluated
                                   if item["state"] == "NOT_ATTEMPTED"),
        "demo_executed": False,
        "demo_execution_note": (
            "false, and not a placeholder: no step was executed. The "
            "preflight decides whether execution would be honest, and for "
            "this repository it is not."),
        "preflight_state": "READY" if ready else "BLOCKED",
        "environment_conditions": environment,
        "unmet_environment_condition_ids": unmet_environment,
        "steps": evaluated,
        "blockers": [item.to_json() for item in blockers],
        "blocker_count": len(blockers),
        "exit_code": 0 if ready else EXIT_BLOCKED,
        "force_available": False,
        "note": (
            "A demonstration that ran past an unmet precondition would "
            "demonstrate the fallback path while being presented as the "
            "system."),
    }
