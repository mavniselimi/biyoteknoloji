# -*- coding: utf-8 -*-
"""What to do when the demonstration goes wrong (WP-25).

Fourteen scenarios, each with a detection signal, a fallback, and - the field
that makes this document honest rather than reassuring - **what the fallback
does not prove**.

That last field exists because a contingency matrix is where overstatement
usually enters a project. "If the database is unavailable, show the cached
result" reads as resilience. It is resilience about availability and it is
silence about correctness, and a viewer watching the fallback has no way to
tell which they are being shown. So every row here says out loud what a
viewer would be entitled to conclude, and what they would not.

Two kinds of row, kept apart:

* **Presentation fallbacks** are permitted. The interface degrades, says so
  on screen, and continues. Losing a stylesheet is not a scientific event.
* **Substance fallbacks are refused.** There is no row that substitutes a
  fixture for governed content, a cached number for a computed one, or a
  rehearsal for a deployment. Where the honest response is to stop, the row
  says stop, and ``permitted`` is false.

A fallback that changed what the audience believes about the science is not a
fallback; it is the demonstration of a different system.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Mapping, Sequence, Tuple

__all__ = [
    "CONTINGENCY_MATRIX_VERSION",
    "SCENARIOS",
    "ContingencyScenario",
    "build_contingency_matrix",
]

CONTINGENCY_MATRIX_VERSION = "pgx-wp25-contingency-matrix/1"


@dataclass(frozen=True)
class ContingencyScenario:
    """One thing that can go wrong, and the only honest response to it."""

    scenario_id: str
    title: str
    #: How the operator knows it happened, without guessing.
    detection: str
    #: What to do. When ``permitted`` is false this is "stop and say so".
    response: str
    #: What a viewer may conclude from the fallback having worked.
    proves: str
    #: What a viewer may **not** conclude. Never empty.
    does_not_prove: str
    #: Whether continuing the demonstration after this response is honest.
    permitted: bool
    owner: str

    def __post_init__(self) -> None:
        for name in ("detection", "response", "proves", "does_not_prove",
                     "owner"):
            if not getattr(self, name).strip():
                raise ValueError("%s states its %s" % (self.scenario_id,
                                                       name))

    def to_json(self) -> Mapping[str, object]:
        return {"scenario_id": self.scenario_id, "title": self.title,
                "detection": self.detection, "response": self.response,
                "proves": self.proves, "does_not_prove": self.does_not_prove,
                "continuation_permitted": self.permitted, "owner": self.owner}


def _s(scenario_id, title, detection, response, proves, does_not_prove,
       permitted, owner):
    return ContingencyScenario(
        scenario_id=scenario_id, title=title, detection=detection,
        response=response, proves=proves, does_not_prove=does_not_prove,
        permitted=permitted, owner=owner)


SCENARIOS: Tuple[ContingencyScenario, ...] = (
    _s("CONT-01", "The venue has no network",
       "an outbound request times out, or the operator is told in advance",
       "continue unchanged: the demonstration is specified to run offline "
       "and every asset is served locally",
       "that the demonstration does not depend on a network",
       "anything about the correctness of what is displayed",
       True, "platform owner"),
    _s("CONT-02", "The projector or display fails",
       "no image reaches the screen",
       "continue on the operator's screen and read the steps aloud; the run "
       "is unchanged",
       "nothing about the system either way",
       "that a run seen by fewer people is a different run",
       True, "presenter"),
    _s("CONT-03", "A stylesheet or font fails to load",
       "the page renders unstyled",
       "continue: the content is the same and the interface says which "
       "assets are missing",
       "that the interface degrades without hiding anything",
       "anything about the science; a stylesheet is not a finding",
       True, "platform owner"),
    _s("CONT-04", "The database is unavailable mid-run",
       "readiness reports the database component blocking",
       "stop the affected step and show the readiness page naming the "
       "missing component. Do not display a previously computed result as "
       "though it were computed now",
       "that the system fails closed and names what is missing",
       "that an assessment was computed; nothing was",
       False, "platform owner"),
    _s("CONT-05", "The container runtime will not start the image",
       "the runtime returns an error or no daemon answers",
       "stop. Announce that the deployed path is unavailable and do not "
       "substitute a local process while describing it as staging",
       "nothing; a failed start is a failed start",
       "that a local process is a deployment. LOCAL_STAGING_REHEARSAL is "
       "not staging and must never be presented as it",
       False, "platform owner"),
    _s("CONT-06", "No approved dataset is available",
       "the source registry reports zero approved sources, or the canonical "
       "dataset is not published",
       "stop before the case selection step. State that the corpus is "
       "unapproved and that no governed result can be produced",
       "that the system refuses to compute from unapproved content",
       "that the pipeline works on real data; it has not been asked to",
       False, "scientific source approver"),
    _s("CONT-07", "No executable ruleset is registered",
       "the default registry reports zero executable rulesets",
       "stop before the assessment step and say that no approved rule "
       "exists to evaluate",
       "that the engine refuses to run without governed rules",
       "that any rule is correct; none has been approved to be wrong",
       False, "curation lead"),
    _s("CONT-08", "A safety invariant fails during the run",
       "the safety gate reports a failing invariant",
       "stop the entire demonstration immediately. A failing safety "
       "invariant is not a presentation problem",
       "that the invariant fires",
       "nothing that would justify continuing",
       False, "safety owner"),
    _s("CONT-09", "The assessment produces no findings",
       "the result is empty rather than absent",
       "show the empty result with its coverage axis. An empty finding set "
       "with full coverage and an empty one with no coverage are different "
       "answers and the interface distinguishes them",
       "that missing data is not shown as low risk",
       "that the case has no pharmacogenomic implication",
       True, "curation lead"),
    _s("CONT-10", "The audience asks for a real patient case",
       "a spoken request during the demonstration",
       "decline. The case model refuses real-patient, genotype and raw "
       "sequencing fields at any depth, and no such ingestion exists",
       "that the boundary is structural rather than a policy somebody "
       "follows",
       "that the system could handle such a case safely if asked",
       True, "presenter"),
    _s("CONT-11", "The audience asks about clinical validation",
       "a spoken question during the demonstration",
       "answer that none has been performed, without qualification, and "
       "name what is missing: zero validation cases, no holdout set, no "
       "computed metric, no completed expert review",
       "nothing; it is an answer, not a result",
       "any softened version of the answer. There is no partial clinical "
       "validation here to describe",
       True, "presenter"),
    _s("CONT-12", "The expert reviewer is unavailable",
       "the named reviewer does not attend",
       "state that no expert review has been completed at all, which is the "
       "standing position and not a consequence of their absence",
       "nothing",
       "that a review would have happened but for the absence",
       True, "expert review chair"),
    _s("CONT-13", "The evidence pack fails its own integrity check",
       "verify-pack exits non-zero",
       "stop and show the failure. Do not rebuild the pack during the "
       "demonstration to make the check pass",
       "that the pack is self-checking",
       "that the underlying evidence was ever different from what the "
       "failure says",
       False, "WP-25 evidence owner"),
    _s("CONT-14", "A gate appears to pass unexpectedly",
       "a gate reports PASS where the recorded state is BLOCKED",
       "stop and treat it as a defect in the pack, not as good news. "
       "Re-run the gate from source artifacts and compare",
       "nothing until the disagreement is resolved",
       "that the programme advanced. An unexplained PASS is the most "
       "likely shape of a bug in this software",
       False, "WP-25 evidence owner"),
)


def build_contingency_matrix() -> Mapping[str, object]:
    """The matrix, with the permitted and refused rows counted separately."""
    permitted = [item.scenario_id for item in SCENARIOS if item.permitted]
    refused = [item.scenario_id for item in SCENARIOS if not item.permitted]
    return {
        "contingency_matrix_version": CONTINGENCY_MATRIX_VERSION,
        "scenario_count": len(SCENARIOS),
        "continuation_permitted_ids": permitted,
        "continuation_refused_ids": refused,
        "scenarios": [item.to_json() for item in SCENARIOS],
        "substitution_permitted": False,
        "note": (
            "No row substitutes a fixture for governed content, a cached "
            "number for a computed one, or a local rehearsal for a "
            "deployment. Where the honest response is to stop, the row says "
            "stop."),
    }
