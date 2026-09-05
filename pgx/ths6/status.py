# -*- coding: utf-8 -*-
"""The THS 6 status document (WP-25).

One document, two results, and they are never the same field.

``evidence_pack_integrity`` describes this pack: are its members present, do
their digests agree, does the whole hash to what the manifest says. It can be
``true`` on a day when nothing scientific has happened, because it is a
statement about bytes.

``ths6_achieved`` describes the programme: have all six gates passed, are all
fifteen Definition of Done items satisfied, has the representative
demonstration been executed, has every sign-off role signed. For this
repository it is ``false``, and it is false for reasons no code in this
repository can change.

The conjunction is spelled out rather than delegated, and it includes the
sign-off matrix on purpose. A programme whose gates all passed and whose
demonstration ran, with nobody willing to put their name to it, has not
achieved a standard that exists to record human accountability.

``release_may_proceed`` is a third field and is not a synonym for either. It
follows ``ths6_achieved`` and additionally requires the release-validation
aggregate WP-24 maintains, because a release is an operational act with its
own gate.

There is no ``status.ok``, no ``__bool__`` and no summary string a caller
could truth-test. Everything a caller needs is a named field whose meaning is
written next to it.
"""

from __future__ import annotations

from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from pgx.ths6.claim_registry import build_claim_registry
from pgx.ths6.contingency import build_contingency_matrix
from pgx.ths6.definition_of_done import build_definition_of_done
from pgx.ths6.demo import run_demo_preflight
from pgx.ths6.evidence_registry import build_evidence_registry, read_document
from pgx.ths6.gate_matrix import build_gate_matrix
from pgx.ths6.signoff import build_signoff_matrix
from pgx.ths6.traceability import build_traceability
from pgx.ths6.vocabulary import (EXIT_BLOCKED, EXIT_FAILURE, EXIT_SUCCESS,
                                 PACK_INTEGRITY_IS_NOT_ACHIEVEMENT,
                                 GateResult)

__all__ = [
    "THS6_STATUS_VERSION",
    "build_ths6_status",
    "exit_code_for_status",
]

THS6_STATUS_VERSION = "pgx-wp25-ths6-status/1"

_RELEASE_VALIDATION = "data/deployment/wp24-release-validation.json"


def build_ths6_status(root: str = ".",
                      *, pack_integrity: Optional[bool] = None
                      ) -> Mapping[str, object]:
    """Aggregate every WP-25 result into one honest status document.

    ``pack_integrity`` is passed in rather than computed here so that the
    pack's own verification and the programme's status cannot be produced by
    the same call and mistaken for one result. When it is ``None`` the field
    is reported as unevaluated, which is not the same as failing.
    """
    gates = build_gate_matrix(root)
    dod = build_definition_of_done(root)
    demo = run_demo_preflight(root)
    claims = build_claim_registry(root)
    evidence = build_evidence_registry(root)
    trace = build_traceability(root)
    signoff = build_signoff_matrix()
    contingency = build_contingency_matrix()

    all_gates_pass = bool(gates["all_gates_pass"])
    dod_satisfied = set(dod["satisfied_dod_ids"])  # type: ignore[arg-type]
    all_dod_satisfied = (
        len(dod_satisfied) == int(dod["enumerated_count"]))  # type: ignore
    demo_executed = bool(demo["demo_executed"])
    all_signed = int(signoff["signed_count"]) == int(  # type: ignore
        signoff["role_count"])
    ths6_achieved = bool(all_gates_pass and all_dod_satisfied
                         and demo_executed and all_signed)

    validation = read_document(root, _RELEASE_VALIDATION)
    release_validation_permits = bool(
        validation is not None
        and validation.get("release_may_proceed") is True)
    release_may_proceed = bool(ths6_achieved and release_validation_permits)

    unmet = []
    if not all_gates_pass:
        unmet.append("gates %s are not PASS"
                     % ", ".join(sorted(
                         set(gates["results"]) -  # type: ignore[arg-type]
                         set(gates["passing_gate_ids"]))))  # type: ignore
    if not all_dod_satisfied:
        unmet.append("%d of %d Definition of Done items are not satisfied"
                     % (int(dod["enumerated_count"]) - len(  # type: ignore
                         dod_satisfied), dod["enumerated_count"]))
    if not demo_executed:
        unmet.append("the representative demonstration has not been executed "
                     "(preflight stopped at %s)" % demo["stopped_at_step_id"])
    if not all_signed:
        unmet.append("%d of %d sign-off roles are unsigned"
                     % (int(signoff["role_count"]) - int(  # type: ignore
                         signoff["signed_count"]), signoff["role_count"]))

    return {
        "ths6_status_version": THS6_STATUS_VERSION,
        "work_package": "WP-25",

        # -- what this work package built ---------------------------------
        "implementation_status": "IMPLEMENTED",
        "implementation_note": (
            "The evidence pack software is implemented: the registries, the "
            "gate matrix, the Definition of Done registry, the demo "
            "preflight, the contingency matrix and the pack integrity check "
            "all run and produce results. That is a statement about "
            "software. Whether the programme has achieved THS 6 is the "
            "separate question below, and the answer is no."),

        # -- the pack ------------------------------------------------------
        "evidence_pack_integrity": pack_integrity,
        "evidence_pack_integrity_note": PACK_INTEGRITY_IS_NOT_ACHIEVEMENT,

        # -- the programme -------------------------------------------------
        "ths6_achieved": ths6_achieved,
        "release_may_proceed": release_may_proceed,
        "ths6_achievement_conditions": {
            "all_gates_pass": all_gates_pass,
            "all_definition_of_done_items_satisfied": all_dod_satisfied,
            "representative_demonstration_executed": demo_executed,
            "all_signoff_roles_signed": all_signed,
        },
        "release_condition_release_validation_permits":
            release_validation_permits,
        "unmet_conditions": unmet,

        # -- the numbers a reader will want --------------------------------
        "gate_results": gates["results"],
        "passing_gate_count": gates["passing_gate_count"],
        "gate_count": gates["gate_count"],
        "total_gate_blocker_count": gates["total_blocker_count"],
        "source_artifact_disagreement_count": gates["disagreement_count"],
        "definition_of_done_enumerated_count": dod["enumerated_count"],
        "definition_of_done_declared_count_in_prose":
            dod["declared_count_in_wp25_prose"],
        "definition_of_done_satisfied_count": len(dod_satisfied),
        "claim_count": claims["claim_count"],
        "supported_claim_count": len(claims["supported_claim_ids"]),
        "contradicted_claim_count": len(claims["contradicted_claim_ids"]),
        "evidence_item_count": evidence["declared_count"],
        "admissible_evidence_count": evidence["admissible_count"],
        "traceability_row_count": trace["row_count"],
        "traceability_has_dangling_reference":
            trace["has_dangling_reference"],
        "demo_preflight_state": demo["preflight_state"],
        "demo_stopped_at_step_id": demo["stopped_at_step_id"],
        "contingency_scenario_count": contingency["scenario_count"],
        "signoff_role_count": signoff["role_count"],
        "signed_signoff_count": signoff["signed_count"],
        "blocker_owners": gates["blocker_owners"],

        # -- boundaries ----------------------------------------------------
        "not_clinical_validation": (
            "Nothing in this document is clinical validation, scientific "
            "validation or expert review. It is an inventory of artifacts "
            "and an evaluation of gates. A complete, internally consistent "
            "evidence pack describing a blocked programme is exactly what "
            "this repository should produce today."),
        "override_available": False,
        "note": (
            "Pack integrity and THS 6 achievement are separate fields and "
            "are never derived from one another."),
    }


def exit_code_for_status(status: Mapping[str, object]) -> int:
    """The exit code the ``status`` command earns.

    ``0`` only when the programme has actually achieved THS 6. While it has
    not, the command exits ``2`` - blocked - because a caller wiring this
    into a script should not be able to treat "we produced a document" as
    "we passed".
    """
    if status.get("ths6_achieved") is True:
        return EXIT_SUCCESS
    if status.get("traceability_has_dangling_reference") is True:
        return EXIT_FAILURE
    for value in (status.get("gate_results") or {}).values():  # type: ignore
        if value == GateResult.FAIL.value:
            return EXIT_FAILURE
    return EXIT_BLOCKED
