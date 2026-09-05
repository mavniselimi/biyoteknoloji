# -*- coding: utf-8 -*-
"""The twelve committed WP-25 artifacts (WP-25).

Same split as WP-24, for the same reason. Some of these documents describe
*declarations* - the demonstration's steps, the contingency matrix, the
sign-off roles, the published schemas - and are identical on every machine
that checks out this commit. Others describe *this working tree at this
moment* - which artifacts are present, what they hash to, what the gates
therefore conclude - and must differ between two trees that differ.

Only the first group is offered to WP-19's reproducibility comparison.
Registering the second group there would produce a check that failed for
everybody, which is the fastest way to teach a team to ignore one.

All twelve are committed, because the point of an evidence pack is that a
reviewer can read it without running anything. The environment-measuring ones
carry their own freshness story: each records the digests it read, so a
reviewer who re-runs ``pgx-ths6 verify-pack`` learns whether the tree still
matches the pack rather than having to trust that it does.
"""

from __future__ import annotations

import io
import os
from typing import Dict, List, Mapping, Sequence, Tuple

from pgx.ths6.integrity import (MANIFEST_MEMBER_PATH, build_pack_manifest,
                                canonical_json)

__all__ = [
    "ARTIFACT_PATHS",
    "DETERMINISTIC_ARTIFACT_PATHS",
    "PACK_MEMBER_PATHS",
    "build_artifacts",
    "build_documents",
    "write_ths6_artifacts",
]

#: Every committed document, and what each one is.
ARTIFACT_PATHS: Mapping[str, str] = {
    "data/ths6/wp25-evidence-registry.json":
        "every declared artifact WP-00 to WP-24, classified, hashed and "
        "schema-checked",
    "data/ths6/wp25-claim-registry.json":
        "the claims the project might make, and what refutes each",
    "data/ths6/wp25-traceability-matrix.json":
        "requirement to implementation to test to evidence to gate, with no "
        "dangling identifier",
    "data/ths6/wp25-gate-matrix.json":
        "gates A to F rebuilt from source artifacts, with disagreements",
    "data/ths6/wp25-definition-of-done.json":
        "all fifteen P0 Definition of Done items, evaluated separately",
    "data/ths6/wp25-demo-manifest.json":
        "the representative demonstration as declared",
    "data/ths6/wp25-demo-preflight.json":
        "the preflight result: where it stops and why",
    "data/ths6/wp25-contingency-matrix.json":
        "fourteen failure scenarios and what each fallback does not prove",
    "data/ths6/wp25-signoff-matrix.json":
        "nine human roles, none signed, no mechanism to sign",
    "data/ths6/wp25-findings.json":
        "every discrepancy WP-25 noticed, with an owner and a resolution",
    "data/ths6/wp25-ths6-status.json":
        "pack integrity and THS 6 achievement, as separate fields",
    MANIFEST_MEMBER_PATH:
        "the pack manifest: two-level hashes over every member but itself",
}

#: The subset a reproducibility check may compare byte for byte. The other
#: nine measure the working tree, and a document that measures the tree is
#: supposed to differ between two trees.
DETERMINISTIC_ARTIFACT_PATHS: Tuple[str, ...] = (
    "data/ths6/wp25-contingency-matrix.json",
    "data/ths6/wp25-demo-manifest.json",
    "data/ths6/wp25-signoff-matrix.json",
)


def build_documents(root: str = ".") -> Mapping[str, Mapping[str, object]]:
    """Every WP-25 document except the pack manifest, which comes last."""
    from pgx.ths6.claim_registry import build_claim_registry
    from pgx.ths6.contingency import build_contingency_matrix
    from pgx.ths6.definition_of_done import build_definition_of_done
    from pgx.ths6.demo import build_demo_manifest, run_demo_preflight
    from pgx.ths6.evidence_registry import build_evidence_registry
    from pgx.ths6.gate_matrix import build_gate_matrix
    from pgx.ths6.signoff import build_signoff_matrix
    from pgx.ths6.traceability import build_traceability

    evidence = build_evidence_registry(root)
    gates = build_gate_matrix(root)
    dod = build_definition_of_done(root)
    trace = build_traceability(root)
    return {
        "data/ths6/wp25-evidence-registry.json": evidence,
        "data/ths6/wp25-claim-registry.json": build_claim_registry(root),
        "data/ths6/wp25-traceability-matrix.json": trace,
        "data/ths6/wp25-gate-matrix.json": gates,
        "data/ths6/wp25-definition-of-done.json": dod,
        "data/ths6/wp25-demo-manifest.json": build_demo_manifest(root),
        "data/ths6/wp25-demo-preflight.json": run_demo_preflight(root),
        "data/ths6/wp25-contingency-matrix.json":
            build_contingency_matrix(),
        "data/ths6/wp25-signoff-matrix.json": build_signoff_matrix(),
        "data/ths6/wp25-findings.json": build_findings(
            evidence, gates, dod, trace),
    }


def build_findings(evidence: Mapping[str, object],
                   gates: Mapping[str, object],
                   dod: Mapping[str, object],
                   trace: Mapping[str, object]) -> Mapping[str, object]:
    """Every discrepancy, gathered so none is only in one document.

    A finding recorded in exactly one place is one a reader has to already
    know to look for. Gathering them costs nothing and makes the pack
    answerable to a single question: what did this work package notice.
    """
    collected: List[Mapping[str, object]] = []
    collected.extend(evidence.get("findings", ()))  # type: ignore[arg-type]
    collected.extend(dod.get("findings", ()))  # type: ignore[arg-type]
    for gate in gates.get("gates", ()):  # type: ignore[union-attr]
        collected.extend(gate.get("findings", ()))
    blocking = [item for item in collected if item.get("blocking")]
    return {
        "findings_version": "pgx-wp25-findings/1",
        "finding_count": len(collected),
        "blocking_finding_count": len(blocking),
        "findings": sorted(collected, key=lambda item: (
            str(item.get("code")), str(item.get("detail")))),
        "source_artifact_disagreements":
            gates.get("source_artifact_disagreements", []),
        "disagreement_count": gates.get("disagreement_count", 0),
        "dangling_traceability_references": trace.get("dangling", {}),
        "note": (
            "A finding says a document, a count or an artifact is wrong. A "
            "blocker says a condition is unmet. They are different things "
            "and are counted separately."),
    }


#: Everything the pack contains: the artifacts, the schemas, and the final
#: documentation. Assembled by ``pgx.ths6.pack``.
def PACK_MEMBER_PATHS(root: str = ".") -> Tuple[str, ...]:
    """The pack's members, discovered from the three directories it spans.

    Discovered rather than declared because the documentation set is the one
    part of this pack a human edits, and a declared list would drift the
    first time somebody added a page. The three roots are fixed; what is
    inside them is measured.
    """
    members: List[str] = list(ARTIFACT_PATHS)
    for directory in ("schemas/wp25", "docs/ths6/final"):
        absolute = os.path.join(root, *directory.split("/"))
        if not os.path.isdir(absolute):
            continue
        for name in sorted(os.listdir(absolute)):
            if name.startswith("."):
                continue
            path = os.path.join(absolute, name)
            if os.path.isfile(path):
                members.append("%s/%s" % (directory, name))
    return tuple(sorted(set(members)))


def write_ths6_artifacts(root: str = ".") -> Sequence[str]:
    """Write all twelve, manifest last. Returns the paths written."""
    documents = dict(build_documents(root))
    written: List[str] = []
    for relative, document in sorted(documents.items()):
        _write(root, relative, document)
        written.append(relative)
    # The status document is written before the manifest and after everything
    # else: it reports pack integrity, which is only knowable once the other
    # documents exist, and it is itself a member the manifest must cover.
    from pgx.ths6.status import build_ths6_status
    status = build_ths6_status(root, pack_integrity=None)
    _write(root, "data/ths6/wp25-ths6-status.json", status)
    written.append("data/ths6/wp25-ths6-status.json")
    manifest = build_pack_manifest(
        root, PACK_MEMBER_PATHS(root),
        pack_version=str(status["ths6_status_version"]))
    _write(root, MANIFEST_MEMBER_PATH, manifest)
    written.append(MANIFEST_MEMBER_PATH)
    return tuple(written)


def _write(root: str, relative: str, document: Mapping[str, object]) -> None:
    path = os.path.join(root, *relative.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w", encoding="utf-8") as handle:
        handle.write(canonical_json(document))


def build_artifacts(root: str) -> Mapping[str, str]:
    """The deterministic subset, rendered. WP-19's generator signature.

    Only the declarations. The registries, the gate matrix, the Definition of
    Done evaluation, the preflight, the findings, the status and the pack
    manifest all measure the working tree, and comparing one of those byte
    for byte between two machines would fail for everybody.
    """
    from pgx.application.ths6_schema import build_schemas
    from pgx.ths6.contingency import build_contingency_matrix
    from pgx.ths6.demo import build_demo_manifest
    from pgx.ths6.signoff import build_signoff_matrix

    documents = {
        "data/ths6/wp25-contingency-matrix.json":
            canonical_json(build_contingency_matrix()),
        "data/ths6/wp25-demo-manifest.json":
            canonical_json(build_demo_manifest(root)),
        "data/ths6/wp25-signoff-matrix.json":
            canonical_json(build_signoff_matrix()),
    }
    for relative, schema in build_schemas().items():
        documents[relative] = canonical_json(schema)
    return documents
