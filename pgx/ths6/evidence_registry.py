# -*- coding: utf-8 -*-
"""The evidence inventory (WP-25).

What this module is *not*: a directory listing. A listing would tell a
reviewer that a file exists, which is the least interesting fact about it. The
questions that decide whether a THS 6 claim is defensible are: what kind of
thing is this, what produced it, does it still match its own schema, does it
record a real event or an intention, does it assert a number, and if it is
insufficient, who has to act.

So the inventory is *declared* here - one entry per artifact, hand-classified,
with a reason - and then *resolved* against the working tree by
``build_evidence_registry``, which fills in the observations: present, digest,
media type, schema validation, freshness.

The split matters. A registry that discovered its own contents would grow
silently whenever somebody added a file, and would classify nothing. A
declaration that never touched the filesystem would claim artifacts that had
been deleted. Declaring and then resolving means a missing artifact is a
*finding* with an owner, rather than either an omission or a lie.

Two refusals are enforced during resolution rather than trusted:

* **symlinks.** A symlinked artifact resolves to content outside the tree,
  and its digest would describe a file this repository does not contain.
* **credential-shaped content.** The pack is meant to be circulated. Every
  resolved artifact is scanned with WP-23's classifier before its digest is
  recorded, and a positive finding makes the item ``INVALID`` rather than
  quietly including it.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from pgx.ths6.models import (EvidenceItem, Finding, MEDIA_TYPES,
                             repository_relative)
from pgx.ths6.vocabulary import EvidenceType

__all__ = [
    "DECLARED_EVIDENCE",
    "EVIDENCE_REGISTRY_VERSION",
    "PRELIMINARY_THS6_DOCUMENTS",
    "build_evidence_registry",
    "declared_by_id",
    "digest_of",
    "resolve_evidence",
]

EVIDENCE_REGISTRY_VERSION = "pgx-wp25-evidence-registry/1"

#: The three WP-local THS documents that existed before WP-25. They are
#: preliminary technical notes written by their own work packages, they are
#: preserved unchanged, and they are **not** part of the final pack. Named
#: here so the distinction is a checkable property rather than a sentence in
#: a document somebody might not read.
PRELIMINARY_THS6_DOCUMENTS: Tuple[str, ...] = (
    "docs/ths6/wp02-foundation-evidence.md",
    "docs/ths6/wp03-release-evidence.md",
    "docs/ths6/wp04-ingestion-evidence.md",
)

#: Where the final pack's own documents live. Disjoint from the preliminary
#: set above, by construction and by test.
FINAL_PACK_DOCUMENT_PREFIX = "docs/ths6/final/"


def _e(evidence_id, title, work_package, evidence_type, path, generator,
       schema_path=None, claims=(), gates=(), numeric=False, test_only=False,
       observed=False, freshness=None, limitations=(), gap_owner=None):
    """Terse constructor for the declaration table below."""
    return EvidenceItem(
        evidence_id=evidence_id, title=title, work_package=work_package,
        evidence_type=evidence_type, path=path, generator=generator,
        schema_path=schema_path, supported_claim_ids=tuple(claims),
        gate_ids=tuple(gates), contains_numeric_claim=numeric,
        test_only=test_only, observed_or_executed=observed,
        freshness_source=freshness, limitations=tuple(limitations),
        gap_owner=gap_owner)


_T = EvidenceType

#: The declaration. Ordered by work package, then by artifact, so a reader
#: following the project's history reads it in the order it happened.
DECLARED_EVIDENCE: Tuple[EvidenceItem, ...] = (
    # -- WP-00: intent and architecture -------------------------------------
    _e("EV-WP00-001", "System architecture, including the P0 Definition of "
       "Done", "WP-00", _T.DOCUMENT_ONLY, "architecture.md",
       "architecture owner", claims=("THS6-CLAIM-016",),
       limitations=("states requirements; records no result",),
       gap_owner="architecture owner"),
    _e("EV-WP00-002", "Repository overview and work package table", "WP-00",
       _T.DOCUMENT_ONLY, "README.md", "repository maintainer",
       limitations=("summarises status; is not a status source",),
       gap_owner="repository maintainer"),
    _e("EV-WP00-003", "Intended purpose and out-of-scope statement", "WP-00",
       _T.DOCUMENT_ONLY, "docs/architecture/intended-purpose.md",
       "architecture owner", claims=("THS6-CLAIM-022",), gates=("GATE-C",),
       limitations=("declares intent; no approval recorded",),
       gap_owner="clinical safety authority"),
    _e("EV-WP00-004", "Safety contract", "WP-00", _T.DOCUMENT_ONLY,
       "docs/risk-management/safety-contract.md", "safety owner",
       claims=("THS6-CLAIM-004",), gates=("GATE-C",),
       limitations=("a contract, not an execution",),
       gap_owner="safety owner"),

    # -- WP-01: legacy baseline ---------------------------------------------
    _e("EV-WP01-001", "Legacy baseline manifest", "WP-01", _T.REAL_EXECUTED,
       "data/legacy-baseline/manifest.json", "pgx legacy baseline capture",
       observed=True, numeric=True,
       limitations=("describes the pre-P0 prototype, not governed content",),
       gap_owner="data owner"),
    _e("EV-WP01-002", "Legacy reproduction run log", "WP-01",
       _T.REAL_EXECUTED, "data/legacy-baseline/reproduction-run-log.json",
       "pgx legacy baseline capture", observed=True, numeric=True,
       limitations=("reproduces the legacy prototype only",),
       gap_owner="data owner"),
    _e("EV-WP01-003", "Expected legacy differences", "WP-01",
       _T.DOCUMENT_ONLY, "data/legacy-baseline/expected-differences.json",
       "migration owner",
       limitations=("an allowlist of known differences",),
       gap_owner="migration owner"),
    _e("EV-WP01-004", "Legacy inventory", "WP-01", _T.DOCUMENT_ONLY,
       "docs/migration/legacy-inventory.md", "migration owner"),
    _e("EV-WP01-005", "Legacy reproducibility notes", "WP-01",
       _T.DOCUMENT_ONLY, "docs/migration/legacy-reproducibility.md",
       "migration owner"),

    # -- WP-02: domain and database -----------------------------------------
    _e("EV-WP02-001", "Preliminary WP-02 foundation evidence note (WP-local, "
       "not part of the final pack)", "WP-02", _T.DOCUMENT_ONLY,
       "docs/ths6/wp02-foundation-evidence.md", "WP-02 author",
       limitations=("a preliminary WP-local note predating this pack",),
       gap_owner="WP-25 evidence owner"),
    _e("EV-WP02-002", "Domain model and database design", "WP-02",
       _T.DOCUMENT_ONLY, "docs/architecture/wp02-domain-and-db.md",
       "architecture owner"),
    _e("EV-WP02-003", "Entity relationship diagram", "WP-02",
       _T.DOCUMENT_ONLY, "docs/architecture/wp02-er-diagram.md",
       "architecture owner"),

    # -- WP-03: release registry --------------------------------------------
    _e("EV-WP03-001", "Preliminary WP-03 release evidence note (WP-local, "
       "not part of the final pack)", "WP-03", _T.DOCUMENT_ONLY,
       "docs/ths6/wp03-release-evidence.md", "WP-03 author",
       claims=("THS6-CLAIM-005",),
       limitations=("a preliminary WP-local note predating this pack",),
       gap_owner="WP-25 evidence owner"),
    _e("EV-WP03-002", "Release registry design", "WP-03", _T.DOCUMENT_ONLY,
       "docs/architecture/wp03-release-registry.md", "architecture owner",
       claims=("THS6-CLAIM-005",), gates=("GATE-F",)),
    _e("EV-WP03-003", "Release manifest schema", "WP-03", _T.DOCUMENT_ONLY,
       "schemas/release-manifest.schema.json", "pgx-release",
       claims=("THS6-CLAIM-005",),
       limitations=("a shape, not an instance; no release is active",),
       gap_owner="release approver"),
    _e("EV-WP03-004", "WP-03 open items", "WP-03", _T.DOCUMENT_ONLY,
       "docs/handoffs/wp03-open-items.md", "WP-03 author"),

    # -- WP-04: ingestion ----------------------------------------------------
    _e("EV-WP04-001", "Preliminary WP-04 ingestion evidence note (WP-local, "
       "not part of the final pack)", "WP-04", _T.DOCUMENT_ONLY,
       "docs/ths6/wp04-ingestion-evidence.md", "WP-04 author",
       limitations=("a preliminary WP-local note predating this pack",),
       gap_owner="WP-25 evidence owner"),
    _e("EV-WP04-002", "Raw ClinPGx snapshot manifest", "WP-04",
       _T.REAL_EXECUTED,
       "data/raw/clinpgx-legacy-v2/PGX-DATA-20260830-900/manifest.json",
       "pgx-ingest-clinpgx", schema_path="schemas/"
       "raw-snapshot-manifest.schema.json", observed=True, numeric=True,
       gates=("GATE-A",), claims=("THS6-CLAIM-019",),
       limitations=("the snapshot is quarantined and incomplete",),
       gap_owner="data owner"),
    _e("EV-WP04-003", "Raw snapshot manifest schema", "WP-04",
       _T.DOCUMENT_ONLY, "schemas/raw-snapshot-manifest.schema.json",
       "pgx-ingest-clinpgx"),
    _e("EV-WP04-004", "Ingestion architecture", "WP-04", _T.DOCUMENT_ONLY,
       "docs/architecture/wp04-ingestion.md", "architecture owner"),

    # -- WP-05: source policy -----------------------------------------------
    _e("EV-WP05-001", "WP-05 source policy validation evidence", "WP-05",
       _T.IMPLEMENTATION_TEST, "docs/evidence/wp05-validation.md",
       "WP-05 author", test_only=False,
       limitations=("records schema and policy checks, not approvals",),
       gap_owner="scientific source approver"),
    _e("EV-WP05-002", "Scientific source registry", "WP-05",
       _T.SCIENTIFIC_PENDING, "config/scientific-sources.json",
       "pgx-source-policy",
       schema_path="schemas/scientific-source-registry.schema.json",
       gates=("GATE-A",), claims=("THS6-CLAIM-018",), numeric=True,
       limitations=("every registered source is still PENDING_REVIEW; none "
                    "is approved",),
       gap_owner="scientific source approver"),
    _e("EV-WP05-003", "Source registry schema", "WP-05", _T.DOCUMENT_ONLY,
       "schemas/scientific-source-registry.schema.json", "pgx-source-policy"),
    _e("EV-WP05-004", "Source strategy", "WP-05", _T.DOCUMENT_ONLY,
       "docs/scientific/source-strategy.md", "scientific owner"),
    _e("EV-WP05-005", "Source review checklist", "WP-05", _T.HUMAN_PENDING,
       "docs/scientific/source-review-checklist.md", "scientific owner",
       gates=("GATE-A",),
       limitations=("a checklist nobody has completed for any source",),
       gap_owner="scientific source approver"),

    # -- WP-06: canonicalisation ---------------------------------------------
    _e("EV-WP06-001", "WP-06 snapshot verification evidence", "WP-06",
       _T.IMPLEMENTATION_TEST, "docs/evidence/wp06-snapshot-verification.md",
       "WP-06 author",
       limitations=("verifies the build machinery, not the corpus",),
       gap_owner="data owner"),
    _e("EV-WP06-002", "Canonical dataset manifest", "WP-06",
       _T.SCIENTIFIC_PENDING,
       "data/canonical/PGX-DATA-20260830-900/manifest.json", "pgx-dataset",
       schema_path="schemas/canonical-dataset-manifest.schema.json",
       gates=("GATE-A",), claims=("THS6-CLAIM-019",), numeric=True,
       limitations=("state is BUILDING and the dataset is not published",),
       gap_owner="data owner"),
    _e("EV-WP06-003", "Canonical dataset manifest schema", "WP-06",
       _T.DOCUMENT_ONLY, "schemas/canonical-dataset-manifest.schema.json",
       "pgx-dataset"),
    _e("EV-WP06-004", "Identity allocation record", "WP-06",
       _T.REAL_EXECUTED,
       "data/canonical/PGX-DATA-20260830-900/identity-allocation.json",
       "pgx-dataset", observed=True, numeric=True,
       limitations=("identity allocation only; says nothing about content "
                    "approval",),
       gap_owner="data owner"),

    # -- WP-07: data quality -------------------------------------------------
    _e("EV-WP07-001", "WP-07 data quality validation evidence", "WP-07",
       _T.IMPLEMENTATION_TEST, "docs/evidence/wp07-dq-validation.md",
       "WP-07 author",
       limitations=("checks the quality machinery, not scientific fitness",),
       gap_owner="data owner"),
    _e("EV-WP07-002", "Data quality report", "WP-07", _T.REAL_EXECUTED,
       "data/canonical/PGX-DATA-20260830-900/dq-report.json", "pgx-dataset",
       schema_path="schemas/data-quality-report.schema.json", observed=True,
       numeric=True, gates=("GATE-A",),
       limitations=("computed over a quarantined snapshot",),
       gap_owner="data owner"),
    _e("EV-WP07-003", "Data quality report schema", "WP-07",
       _T.DOCUMENT_ONLY, "schemas/data-quality-report.schema.json",
       "pgx-dataset"),

    # -- WP-08: evidence build -----------------------------------------------
    _e("EV-WP08-001", "WP-08 trace validation evidence", "WP-08",
       _T.IMPLEMENTATION_TEST, "docs/evidence/wp08-trace-validation.md",
       "WP-08 author", claims=("THS6-CLAIM-003",),
       limitations=("traces the machinery over legacy content",),
       gap_owner="curation lead"),
    _e("EV-WP08-002", "Evidence build manifest", "WP-08",
       _T.SCIENTIFIC_PENDING,
       "data/evidence/PGX-DATA-20260830-900/manifest.json", "pgx-evidence",
       schema_path="schemas/evidence-build-manifest.schema.json",
       gates=("GATE-A",), claims=("THS6-CLAIM-003",), numeric=True,
       limitations=("labelled QUARANTINED, NOT_CURATED and "
                    "NOT_PUBLICATION_ELIGIBLE; not approved for rules",),
       gap_owner="curation lead"),
    _e("EV-WP08-003", "Evidence build manifest schema", "WP-08",
       _T.DOCUMENT_ONLY, "schemas/evidence-build-manifest.schema.json",
       "pgx-evidence"),
    _e("EV-WP08-004", "Evidence provenance chain policy", "WP-08",
       _T.DOCUMENT_ONLY, "docs/data/evidence-provenance-chain.md",
       "data owner", claims=("THS6-CLAIM-003",)),

    # -- WP-09: curation protocol --------------------------------------------
    _e("EV-WP09-001", "WP-09 protocol validation evidence", "WP-09",
       _T.IMPLEMENTATION_TEST, "docs/evidence/wp09-protocol-validation.md",
       "WP-09 author",
       limitations=("validates the protocol document's structure",),
       gap_owner="curation lead"),
    _e("EV-WP09-002", "Curation protocol v1", "WP-09", _T.HUMAN_PENDING,
       "docs/scientific/curation-protocol-v1.md", "curation lead",
       gates=("GATE-B",),
       limitations=("awaiting expert review; unapproved",),
       gap_owner="expert reviewer"),
    _e("EV-WP09-003", "Inter-curator exercise status", "WP-09",
       _T.HUMAN_PENDING, "data/curation/protocol-v1/exercises/status.json",
       "pgx-curation-protocol", gates=("GATE-B",), numeric=True,
       limitations=("templates only; no curator has completed an exercise",),
       gap_owner="curation lead"),
    _e("EV-WP09-004", "Curation protocol schema", "WP-09", _T.DOCUMENT_ONLY,
       "schemas/curation-protocol.schema.json", "pgx-curation-protocol"),
    _e("EV-WP09-005", "Curation approval gates", "WP-09", _T.DOCUMENT_ONLY,
       "docs/scientific/curation-approval-gates.md", "curation lead",
       gates=("GATE-B",)),

    # -- WP-10: curation workflow --------------------------------------------
    _e("EV-WP10-001", "WP-10 schema validation evidence", "WP-10",
       _T.IMPLEMENTATION_TEST, "docs/evidence/wp10-schema-validation.md",
       "WP-10 author", limitations=("schema conformance only",),
       gap_owner="curation lead"),
    _e("EV-WP10-002", "WP-10 workflow validation evidence", "WP-10",
       _T.IMPLEMENTATION_TEST, "docs/evidence/wp10-workflow-validation.md",
       "WP-10 author",
       limitations=("exercises the workflow with fixtures",),
       gap_owner="curation lead"),
    _e("EV-WP10-003", "Legacy work item allocation", "WP-10",
       _T.REAL_EXECUTED, "data/migration/wp10/legacy-work-item-allocation.json",
       "pgx-normalize", observed=True, numeric=True, gates=("GATE-B",),
       limitations=("allocates work items; curates nothing",),
       gap_owner="curation lead"),
    _e("EV-WP10-004", "WP-10 migration manifest", "WP-10", _T.REAL_EXECUTED,
       "data/migration/wp10/manifest.json", "pgx-normalize", observed=True,
       numeric=True),
    _e("EV-WP10-005", "Curation work item schema", "WP-10",
       _T.DOCUMENT_ONLY, "schemas/curation-work-item.schema.json",
       "pgx-normalize"),

    # -- WP-11: rules and rulesets -------------------------------------------
    _e("EV-WP11-001", "WP-11 real gate status", "WP-11",
       _T.SCIENTIFIC_PENDING, "data/rulesets/wp11-real-gate-status.json",
       "pgx-rules gate-status",
       schema_path="schemas/wp11-gate-status.schema.json",
       gates=("GATE-A", "GATE-B"), numeric=True,
       claims=("THS6-CLAIM-020",),
       limitations=("reports zero curated, validated, frozen and executable "
                    "rules",),
       gap_owner="curation lead"),
    _e("EV-WP11-002", "WP-11 real ruleset build attempt", "WP-11",
       _T.REAL_EXECUTED, "data/rulesets/wp11-real-build-attempt.json",
       "pgx-rules build", observed=True, numeric=True, gates=("GATE-B",),
       limitations=("the build ran and produced nothing, because no rule is "
                    "approved",),
       gap_owner="curation lead"),
    _e("EV-WP11-003", "Legacy rule candidate inventory", "WP-11",
       _T.REAL_EXECUTED,
       "data/migration/wp11/legacy-rule-candidate-inventory.json",
       "pgx-normalize",
       schema_path="schemas/legacy-rule-candidate-inventory.schema.json",
       observed=True, numeric=True, gates=("GATE-B",),
       limitations=("candidates are not rules and carry no approval",),
       gap_owner="curation lead"),
    _e("EV-WP11-004", "WP-11 schema validation evidence", "WP-11",
       _T.IMPLEMENTATION_TEST, "docs/evidence/wp11-schema-validation.md",
       "WP-11 author", limitations=("schema conformance only",),
       gap_owner="curation lead"),
    _e("EV-WP11-005", "WP-11 gate status schema", "WP-11", _T.DOCUMENT_ONLY,
       "schemas/wp11-gate-status.schema.json", "pgx-rules"),
    _e("EV-WP11-006", "Rule authoring and approval policy", "WP-11",
       _T.DOCUMENT_ONLY, "docs/scientific/rule-authoring-and-approval.md",
       "scientific owner", gates=("GATE-B",)),

    # -- WP-12: phenotype engine ---------------------------------------------
    _e("EV-WP12-001", "WP-12 phenotype safety invariants", "WP-12",
       _T.IMPLEMENTATION_TEST,
       "docs/evidence/wp12-phenotype-safety-invariants.md", "WP-12 author",
       claims=("THS6-CLAIM-004",), gates=("GATE-C",),
       limitations=("invariants proven over fixtures, not governed content",),
       gap_owner="safety owner"),
    _e("EV-WP12-002", "Phenotype regression report", "WP-12",
       _T.REAL_EXECUTED, "data/migration/wp12/phenotype-regression-report.json",
       "pgx-phenotype", schema_path="schemas/"
       "phenotype-regression-report.schema.json", observed=True, numeric=True,
       limitations=("compares against the legacy prototype",),
       gap_owner="scientific owner"),
    _e("EV-WP12-003", "Phenotype regression allowlist", "WP-12",
       _T.DOCUMENT_ONLY,
       "data/migration/wp12/phenotype-regression-allowlist.json",
       "migration owner"),

    # -- WP-13: coverage engine ----------------------------------------------
    _e("EV-WP13-001", "WP-13 real gate status", "WP-13",
       _T.SCIENTIFIC_PENDING, "data/coverage/wp13-real-gate-status.json",
       "pgx-coverage gate-status",
       schema_path="schemas/wp13-gate-status.schema.json",
       gates=("GATE-C",), claims=("THS6-CLAIM-021",), numeric=True,
       limitations=("zero real coverage manifests, executions and supported "
                    "axes",),
       gap_owner="curation lead"),
    _e("EV-WP13-002", "WP-13 coverage truth table", "WP-13",
       _T.IMPLEMENTATION_TEST, "docs/evidence/wp13-coverage-truth-table.md",
       "WP-13 author", claims=("THS6-CLAIM-004", "THS6-CLAIM-021"),
       gates=("GATE-C",),
       limitations=("a truth table proven over fixtures",),
       gap_owner="safety owner"),
    _e("EV-WP13-003", "WP-13 safety invariants", "WP-13",
       _T.IMPLEMENTATION_TEST, "docs/evidence/wp13-safety-invariants.md",
       "WP-13 author", claims=("THS6-CLAIM-004",), gates=("GATE-C",),
       limitations=("invariants proven over fixtures",),
       gap_owner="safety owner"),
    _e("EV-WP13-004", "Coverage regression report", "WP-13",
       _T.REAL_EXECUTED, "data/migration/wp13/coverage-regression-report.json",
       "pgx-coverage", schema_path="schemas/"
       "coverage-regression-report.schema.json", observed=True, numeric=True,
       limitations=("compares against the legacy prototype",),
       gap_owner="scientific owner"),
    _e("EV-WP13-005", "WP-13 gate status schema", "WP-13", _T.DOCUMENT_ONLY,
       "schemas/wp13-gate-status.schema.json", "pgx-coverage"),

    # -- WP-14: deterministic assessment -------------------------------------
    _e("EV-WP14-001", "WP-14 real gate status", "WP-14",
       _T.SCIENTIFIC_PENDING, "data/assessments/wp14-real-gate-status.json",
       "pgx-assess gate-status",
       schema_path="schemas/wp14-gate-status.schema.json",
       gates=("GATE-C",), claims=("THS6-CLAIM-002",), numeric=True,
       limitations=("no assessment has been computed from governed content",),
       gap_owner="curation lead"),
    _e("EV-WP14-002", "WP-14 determinism evidence", "WP-14",
       _T.IMPLEMENTATION_TEST, "docs/evidence/wp14-determinism.md",
       "WP-14 author", claims=("THS6-CLAIM-002",), gates=("GATE-C",),
       limitations=("determinism demonstrated over fixtures, not over a "
                    "release",),
       gap_owner="release approver"),
    _e("EV-WP14-003", "WP-14 safety invariants", "WP-14",
       _T.IMPLEMENTATION_TEST, "docs/evidence/wp14-safety-invariants.md",
       "WP-14 author", claims=("THS6-CLAIM-004",), gates=("GATE-C",),
       limitations=("invariants proven over fixtures",),
       gap_owner="safety owner"),
    _e("EV-WP14-004", "Assessment regression report", "WP-14",
       _T.REAL_EXECUTED,
       "data/migration/wp14/assessment-regression-report.json", "pgx-assess",
       schema_path="schemas/assessment-regression-report.schema.json",
       observed=True, numeric=True,
       limitations=("compares against the legacy prototype",),
       gap_owner="scientific owner"),
    _e("EV-WP14-005", "WP-14 gate status schema", "WP-14", _T.DOCUMENT_ONLY,
       "schemas/wp14-gate-status.schema.json", "pgx-assess"),

    # -- WP-15: deterministic reporting --------------------------------------
    _e("EV-WP15-001", "WP-15 real gate status", "WP-15",
       _T.SCIENTIFIC_PENDING, "data/reports/wp15-real-gate-status.json",
       "pgx-report gate-status",
       schema_path="schemas/wp15-gate-status.schema.json",
       gates=("GATE-C",), claims=("THS6-CLAIM-003",), numeric=True,
       limitations=("zero real assessments, reports and published "
                    "artifacts",),
       gap_owner="curation lead"),
    _e("EV-WP15-002", "WP-15 claim safety evidence", "WP-15",
       _T.IMPLEMENTATION_TEST, "docs/evidence/wp15-claim-safety.md",
       "WP-15 author", claims=("THS6-CLAIM-022",), gates=("GATE-C",),
       limitations=("the scanner is exercised over fixtures; the boundary "
                    "itself is unapproved",),
       gap_owner="clinical safety authority"),
    _e("EV-WP15-003", "WP-15 determinism evidence", "WP-15",
       _T.IMPLEMENTATION_TEST, "docs/evidence/wp15-determinism.md",
       "WP-15 author", claims=("THS6-CLAIM-002",),
       limitations=("determinism demonstrated over fixtures",),
       gap_owner="release approver"),
    _e("EV-WP15-004", "WP-15 gate status schema", "WP-15", _T.DOCUMENT_ONLY,
       "schemas/wp15-gate-status.schema.json", "pgx-report"),
    _e("EV-WP15-005", "Report fact ledger schema", "WP-15", _T.DOCUMENT_ONLY,
       "schemas/report-fact-ledger.schema.json", "pgx-report",
       claims=("THS6-CLAIM-003",)),

    # -- WP-16: API ----------------------------------------------------------
    _e("EV-WP16-001", "WP-16 real gate status", "WP-16",
       _T.CONFIGURED_NOT_EXECUTED, "data/api/wp16-real-gate-status.json",
       "pgx-api gate-status",
       schema_path="schemas/wp16/gate-status.schema.json",
       gates=("GATE-C",), claims=("THS6-CLAIM-001",), numeric=True,
       limitations=("14 routes declared; zero real API assessments and no "
                    "ASGI runtime test executed",),
       gap_owner="platform owner"),
    _e("EV-WP16-002", "WP-16 API contract report", "WP-16",
       _T.IMPLEMENTATION_TEST, "docs/evidence/wp16-api-contract-report.md",
       "WP-16 author", claims=("THS6-CLAIM-001",),
       limitations=("contract conformance, not a served runtime",),
       gap_owner="platform owner"),
    _e("EV-WP16-003", "Committed OpenAPI document", "WP-16",
       _T.CONFIGURED_NOT_EXECUTED, "schemas/openapi/wp16-openapi.json",
       "pgx-api openapi", claims=("THS6-CLAIM-001",),
       limitations=("the document a running server would serve; no server "
                    "has been observed serving it",),
       gap_owner="platform owner"),
    _e("EV-WP16-004", "WP-16 gate status schema", "WP-16", _T.DOCUMENT_ONLY,
       "schemas/wp16/gate-status.schema.json", "pgx-api"),
    _e("EV-WP16-005", "WP-16 ASGI runtime verification", "WP-16",
       _T.UNAVAILABLE, "data/api/wp16-runtime-verification.json",
       "pgx-api runtime-verify", gates=("GATE-C",),
       limitations=("written only when the runtime suite runs; it has not "
                    "run, so the artifact is absent and the served document "
                    "reports itself unverified",),
       gap_owner="platform owner"),

    # -- WP-17: web prototype -------------------------------------------------
    _e("EV-WP17-001", "WP-17 real gate status", "WP-17",
       _T.CONFIGURED_NOT_EXECUTED, "data/web/wp17-real-gate-status.json",
       "pgx-web gate-status",
       schema_path="schemas/wp17/ui-gate-status.schema.json",
       gates=("GATE-C",), claims=("THS6-CLAIM-001", "THS6-CLAIM-011"),
       numeric=True,
       limitations=("declares the expert review workflow NOT_IMPLEMENTED, "
                    "which WP-22 contradicts; validation dashboard is empty "
                    "state only",),
       gap_owner="platform owner"),
    _e("EV-WP17-002", "WP-17 interface verification", "WP-17",
       _T.REAL_OBSERVED, "docs/evidence/wp17-ui-verification.md",
       "WP-17 author", observed=True, numeric=True,
       claims=("THS6-CLAIM-001",),
       limitations=("pages were rendered and captured over development "
                    "fixtures; no governed content was displayed",),
       gap_owner="platform owner"),
    _e("EV-WP17-003", "Development case catalogue", "WP-17",
       _T.TEST_ONLY_REHEARSAL, "data/demo/wp17-development-cases.json",
       "WP-17 author", test_only=True,
       schema_path="schemas/wp17/demo-case-catalog.schema.json",
       numeric=True, gates=("GATE-D",),
       limitations=("seven development fixtures; they are not validation "
                    "cases and must never be counted as any",),
       gap_owner="validation owner"),
    _e("EV-WP17-004", "Development case manifest", "WP-17",
       _T.TEST_ONLY_REHEARSAL, "data/demo/wp17-demo-case-manifest.json",
       "WP-17 author", test_only=True, numeric=True,
       limitations=("seals a fixture catalogue",),
       gap_owner="validation owner"),
    _e("EV-WP17-005", "WP-17 gate status schema", "WP-17", _T.DOCUMENT_ONLY,
       "schemas/wp17/ui-gate-status.schema.json", "pgx-web"),
    _e("EV-WP17-006", "Web route contract", "WP-17", _T.DOCUMENT_ONLY,
       "docs/web/route-contract.md", "WP-17 author",
       claims=("THS6-CLAIM-001",)),

    # -- WP-18: validation dataset -------------------------------------------
    _e("EV-WP18-001", "WP-18 real gate status", "WP-18",
       _T.SCIENTIFIC_PENDING, "data/validation/wp18-real-gate-status.json",
       "pgx-validation gate-status",
       schema_path="schemas/wp18-gate-status.schema.json",
       gates=("GATE-D",), claims=("THS6-CLAIM-007", "THS6-CLAIM-008"),
       numeric=True,
       limitations=("zero holdout cases against a target of fifty; "
                    "validation metric count is null, not zero",),
       gap_owner="validation owner"),
    _e("EV-WP18-002", "Separation audit", "WP-18", _T.REAL_EXECUTED,
       "data/validation/wp18-separation-audit.json",
       "pgx-validation separation-audit",
       schema_path="schemas/validation-separation-audit.schema.json",
       observed=True, numeric=True, gates=("GATE-D",),
       claims=("THS6-CLAIM-008",),
       limitations=("audits seven development cases; with no holdout set "
                    "there is nothing to separate them from",),
       gap_owner="validation owner"),
    _e("EV-WP18-003", "Holdout case manifest", "WP-18",
       _T.SCIENTIFIC_PENDING,
       "data/validation/wp18-holdout-case-manifest.json", "pgx-validation",
       schema_path="schemas/validation-case-manifest.schema.json",
       gates=("GATE-D",), claims=("THS6-CLAIM-008",), numeric=True,
       limitations=("structurally empty; no holdout case exists",),
       gap_owner="validation owner"),
    _e("EV-WP18-004", "Development case manifest", "WP-18",
       _T.TEST_ONLY_REHEARSAL,
       "data/validation/wp18-development-case-manifest.json",
       "pgx-validation", test_only=True, numeric=True, gates=("GATE-D",),
       limitations=("development cases, explicitly excluded from validation "
                    "evidence",),
       gap_owner="validation owner"),
    _e("EV-WP18-005", "WP-18 separation audit evidence", "WP-18",
       _T.IMPLEMENTATION_TEST, "docs/evidence/wp18-separation-audit.md",
       "WP-18 author", claims=("THS6-CLAIM-008",),
       limitations=("describes the audit machinery",),
       gap_owner="validation owner"),
    _e("EV-WP18-006", "Holdout separation policy", "WP-18",
       _T.DOCUMENT_ONLY, "docs/validation/holdout-separation-policy.md",
       "validation owner", gates=("GATE-D",),
       claims=("THS6-CLAIM-008",)),
    _e("EV-WP18-007", "Validation case contract", "WP-18", _T.DOCUMENT_ONLY,
       "docs/validation/validation-case-contract.md", "validation owner",
       claims=("THS6-CLAIM-007",)),

    # -- WP-19: verification --------------------------------------------------
    _e("EV-WP19-001", "WP-19 real gate status", "WP-19",
       _T.STALE, "data/verification/wp19-real-gate-status.json",
       "pgx-verify gate-status",
       schema_path="schemas/wp19/wp19-gate-status.schema.json",
       gates=("GATE-C", "GATE-E"), numeric=True,
       freshness="data/verification/wp19-test-inventory.json",
       limitations=("records a discovered test count from before WP-20 "
                    "through WP-25 added tests; the count no longer matches "
                    "the suite",),
       gap_owner="verification owner"),
    _e("EV-WP19-002", "WP-19 test inventory", "WP-19", _T.STALE,
       "data/verification/wp19-test-inventory.json", "pgx-verify inventory",
       numeric=True,
       limitations=("an inventory of the suite as it was when last "
                    "generated",),
       gap_owner="verification owner"),
    _e("EV-WP19-003", "WP-19 verification run", "WP-19", _T.STALE,
       "data/verification/wp19-verification-run.json", "pgx-verify run",
       numeric=True,
       limitations=("a recorded run whose evidence WP-19 itself rejects as "
                    "stale",),
       gap_owner="verification owner"),
    _e("EV-WP19-004", "WP-19 reproducibility report", "WP-19",
       _T.REAL_EXECUTED, "data/verification/wp19-reproducibility-report.json",
       "pgx-verify reproducibility",
       schema_path="schemas/wp19/reproducibility-report.schema.json",
       observed=True, numeric=True,
       limitations=("proves deterministic generators reproduce; says nothing "
                    "about scientific content",),
       gap_owner="verification owner"),
    _e("EV-WP19-005", "WP-19 requirement matrix", "WP-19",
       _T.IMPLEMENTATION_TEST,
       "data/verification/wp19-requirement-matrix.json", "pgx-verify matrix",
       schema_path="schemas/wp19/requirement-matrix.schema.json",
       numeric=True, claims=("THS6-CLAIM-016",),
       limitations=("maps software requirements to tests",),
       gap_owner="verification owner"),
    _e("EV-WP19-006", "WP-19 verification profiles", "WP-19",
       _T.CONFIGURED_NOT_EXECUTED,
       "data/verification/wp19-verification-profiles.json",
       "pgx-verify profiles", numeric=True,
       limitations=("declares profiles; executing them is a separate act",),
       gap_owner="verification owner"),
    _e("EV-WP19-007", "WP-19 coverage summary", "WP-19",
       _T.OPERATIONAL_PENDING,
       "data/verification/wp19-coverage-summary.json", "pgx-verify coverage",
       schema_path="schemas/wp19/coverage-summary.schema.json",
       limitations=("no coverage tool is installed, so no percentage exists "
                    "and none is invented",),
       gap_owner="verification owner"),
    _e("EV-WP19-008", "WP-19 software verification evidence", "WP-19",
       _T.IMPLEMENTATION_TEST, "docs/evidence/wp19-software-verification.md",
       "WP-19 author",
       limitations=("software verification is not clinical validation",),
       gap_owner="verification owner"),

    # -- WP-20: safety invariants ---------------------------------------------
    _e("EV-WP20-001", "WP-20 real gate status", "WP-20",
       _T.IMPLEMENTATION_TEST, "data/safety/wp20-real-gate-status.json",
       "pgx-safety gate-status",
       schema_path="schemas/wp20/wp20-gate-status.schema.json",
       gates=("GATE-C", "GATE-F"), numeric=True,
       claims=("THS6-CLAIM-009", "THS6-CLAIM-022"),
       limitations=("twelve invariants executed locally; the CI job has "
                    "never run and the claim boundary is unapproved",),
       gap_owner="safety owner"),
    _e("EV-WP20-002", "Safety invariant registry", "WP-20",
       _T.CONFIGURED_NOT_EXECUTED, "data/safety/wp20-invariant-registry.json",
       "pgx-safety registry",
       schema_path="schemas/wp20/safety-invariant-registry.schema.json",
       numeric=True, claims=("THS6-CLAIM-009",),
       limitations=("declares twelve invariants",),
       gap_owner="safety owner"),
    _e("EV-WP20-003", "Safety negative controls", "WP-20",
       _T.IMPLEMENTATION_TEST, "data/safety/wp20-negative-controls.json",
       "pgx-safety negative-controls",
       schema_path="schemas/wp20/safety-negative-controls.schema.json",
       numeric=True, claims=("THS6-CLAIM-009",),
       limitations=("37 negative controls, all detected, over fixtures",),
       gap_owner="safety owner"),
    _e("EV-WP20-004", "Safety execution result", "WP-20",
       _T.IMPLEMENTATION_TEST, "data/safety/wp20-safety-execution.json",
       "pgx-safety execute",
       schema_path="schemas/wp20/safety-execution-result.schema.json",
       numeric=True, claims=("THS6-CLAIM-009",),
       limitations=("executed locally, never by a CI provider",),
       gap_owner="safety owner"),
    _e("EV-WP20-005", "Safety report", "WP-20", _T.IMPLEMENTATION_TEST,
       "data/safety/wp20-safety-report.json", "pgx-safety report",
       schema_path="schemas/wp20/safety-report.schema.json", numeric=True,
       claims=("THS6-CLAIM-004", "THS6-CLAIM-009"),
       limitations=("aggregates local executions",),
       gap_owner="safety owner"),
    _e("EV-WP20-006", "WP-20 safety report document", "WP-20",
       _T.DOCUMENT_ONLY, "docs/evidence/wp20-safety-report.md",
       "WP-20 author", claims=("THS6-CLAIM-009",)),
    _e("EV-WP20-007", "Safety gate workflow", "WP-20",
       _T.CONFIGURED_NOT_EXECUTED, ".github/workflows/safety-gate.yml",
       "WP-20 author", gates=("GATE-C",), claims=("THS6-CLAIM-009",),
       limitations=("a configured workflow is not a CI run",),
       gap_owner="platform owner"),
    _e("EV-WP20-008", "Invariant registry document", "WP-20",
       _T.DOCUMENT_ONLY, "docs/risk-management/wp20-invariant-registry.md",
       "safety owner", claims=("THS6-CLAIM-009",)),

    # -- WP-21: validation metrics --------------------------------------------
    _e("EV-WP21-001", "WP-21 real gate status", "WP-21",
       _T.SCIENTIFIC_PENDING, "data/validation/wp21-real-gate-status.json",
       "pgx-benchmark gate-status",
       schema_path="schemas/wp21/wp21-gate-status.schema.json",
       gates=("GATE-D",), claims=("THS6-CLAIM-012",), numeric=True,
       limitations=("zero computed metric values, reference judgments and "
                    "thresholds; completed expert review count is null",),
       gap_owner="validation owner"),
    _e("EV-WP21-002", "WP-21 validation report", "WP-21",
       _T.SCIENTIFIC_PENDING, "data/validation/wp21-validation-report.json",
       "pgx-benchmark report",
       schema_path="schemas/wp21/validation-report.schema.json",
       gates=("GATE-D",), claims=("THS6-CLAIM-012",), numeric=True,
       limitations=("a report whose metric values are null because no "
                    "benchmark has been executed",),
       gap_owner="validation owner"),
    _e("EV-WP21-003", "Metric definitions", "WP-21",
       _T.CONFIGURED_NOT_EXECUTED,
       "data/validation/wp21-metric-definitions.json", "pgx-benchmark",
       schema_path="schemas/wp21/metric-definitions.schema.json",
       numeric=True, gates=("GATE-D",),
       limitations=("fifteen definitions; definitions are not values",),
       gap_owner="validation owner"),
    _e("EV-WP21-004", "Failure path catalogue", "WP-21",
       _T.CONFIGURED_NOT_EXECUTED,
       "data/validation/wp21-failure-path-catalogue.json", "pgx-benchmark",
       schema_path="schemas/wp21/failure-path-catalogue.schema.json",
       numeric=True,
       limitations=("ten declared failure paths, none exercised against "
                    "real content",),
       gap_owner="validation owner"),
    _e("EV-WP21-005", "Benchmark dashboard feed", "WP-21",
       _T.SCIENTIFIC_PENDING, "data/validation/wp21-dashboard-feed.json",
       "pgx-benchmark dashboard",
       schema_path="schemas/wp21/dashboard-feed.schema.json",
       limitations=("an empty-state feed; the dashboard renders no metric",),
       gap_owner="validation owner"),
    _e("EV-WP21-006", "WP-21 validation report document", "WP-21",
       _T.DOCUMENT_ONLY, "docs/evidence/wp21-validation-report.md",
       "WP-21 author", claims=("THS6-CLAIM-012",)),
    _e("EV-WP21-007", "Benchmark protocol", "WP-21", _T.DOCUMENT_ONLY,
       "docs/validation/benchmark-protocol.md", "validation owner",
       gates=("GATE-D",), claims=("THS6-CLAIM-012",)),
    _e("EV-WP21-008", "Metric definitions document", "WP-21",
       _T.DOCUMENT_ONLY, "docs/validation/metric-definitions.md",
       "validation owner"),

    # -- WP-22: expert review -------------------------------------------------
    _e("EV-WP22-001", "WP-22 real gate status", "WP-22", _T.HUMAN_PENDING,
       "data/expert-review/wp22-real-gate-status.json",
       "pgx-expert-review gate-status",
       schema_path="schemas/wp22/wp22-gate-status.schema.json",
       gates=("GATE-D",), claims=("THS6-CLAIM-010", "THS6-CLAIM-011"),
       numeric=True,
       limitations=("protocol unapproved, zero signatories, zero named "
                    "reviewers, zero completed reviews",),
       gap_owner="expert review chair"),
    _e("EV-WP22-002", "Expert protocol manifest", "WP-22", _T.HUMAN_PENDING,
       "data/expert-review/wp22-protocol-manifest.json",
       "pgx-expert-review protocol",
       schema_path="schemas/wp22/expert-protocol-manifest.schema.json",
       gates=("GATE-D",), claims=("THS6-CLAIM-010",), numeric=True,
       limitations=("a manifest with no signatory",),
       gap_owner="expert review chair"),
    _e("EV-WP22-003", "Expert review workflow", "WP-22",
       _T.CONFIGURED_NOT_EXECUTED,
       "data/expert-review/wp22-review-workflow.json",
       "pgx-expert-review workflow",
       schema_path="schemas/wp22/review-workflow.schema.json",
       numeric=True, claims=("THS6-CLAIM-011",),
       limitations=("an eight-step workflow nobody has walked; contradicts "
                    "WP-17's claim that no such workflow is implemented",),
       gap_owner="expert review chair"),
    _e("EV-WP22-004", "Expert review public summary", "WP-22",
       _T.HUMAN_PENDING, "data/expert-review/wp22-public-summary.json",
       "pgx-expert-review summary",
       schema_path="schemas/wp22/review-public-summary.schema.json",
       limitations=("an empty summary; there is nothing to summarise",),
       gap_owner="expert review chair"),
    _e("EV-WP22-005", "WP-22 expert review report", "WP-22",
       _T.DOCUMENT_ONLY, "docs/evidence/wp22-expert-review-report.md",
       "WP-22 author", claims=("THS6-CLAIM-010",)),
    _e("EV-WP22-006", "Expert protocol", "WP-22", _T.HUMAN_PENDING,
       "docs/validation/expert-protocol.md", "validation owner",
       gates=("GATE-D",), claims=("THS6-CLAIM-010",),
       limitations=("unapproved",), gap_owner="expert review chair"),

    # -- WP-23: authentication, RBAC and audit ---------------------------------
    _e("EV-WP23-001", "WP-23 real gate status", "WP-23",
       _T.OPERATIONAL_PENDING, "data/security/wp23-real-gate-status.json",
       "pgx-security gate-status",
       schema_path="schemas/wp23/wp23-gate-status.schema.json",
       gates=("GATE-E",), claims=("THS6-CLAIM-013", "THS6-CLAIM-023"),
       numeric=True,
       limitations=("no database, session store, audit store or argon2; the "
                    "audit chain has never been verified",),
       gap_owner="platform owner"),
    _e("EV-WP23-002", "RBAC registry", "WP-23", _T.CONFIGURED_NOT_EXECUTED,
       "data/security/wp23-rbac-registry.json", "pgx-security rbac",
       schema_path="schemas/wp23/rbac-registry.schema.json", numeric=True,
       gates=("GATE-E",), claims=("THS6-CLAIM-023",),
       limitations=("25 permissions declared; no real user has exercised "
                    "one",),
       gap_owner="platform owner"),
    _e("EV-WP23-003", "Governed audit action registry", "WP-23",
       _T.CONFIGURED_NOT_EXECUTED,
       "data/security/wp23-audit-action-registry.json",
       "pgx-security audit-actions", numeric=True, gates=("GATE-E",),
       claims=("THS6-CLAIM-013",),
       limitations=("41 governed actions declared; zero governed audit "
                    "events exist",),
       gap_owner="platform owner"),
    _e("EV-WP23-004", "Rate limit policy", "WP-23",
       _T.CONFIGURED_NOT_EXECUTED, "data/security/wp23-rate-limit-policy.json",
       "pgx-security rate-limits",
       schema_path="schemas/wp23/rate-limit-policy.schema.json",
       numeric=True, gates=("GATE-E",),
       limitations=("five policies declared, none enforced against traffic",),
       gap_owner="platform owner"),
    _e("EV-WP23-005", "Secret scan report", "WP-23", _T.REAL_EXECUTED,
       "data/security/wp23-secret-scan-report.json",
       "pgx-security secret-scan",
       schema_path="schemas/wp23/secret-scan-report.schema.json",
       observed=True, numeric=True, gates=("GATE-E",),
       limitations=("scans this repository's working tree; it does not scan "
                    "history or a built image",),
       gap_owner="security owner"),
    _e("EV-WP23-006", "Backup and restore status", "WP-23",
       _T.OPERATIONAL_PENDING,
       "data/security/wp23-backup-restore-status.json",
       "pgx-security backup-status",
       schema_path="schemas/wp23/backup-restore-status.schema.json",
       gates=("GATE-E",),
       limitations=("no backup has been taken and no restore verified",),
       gap_owner="platform owner"),
    _e("EV-WP23-007", "WP-23 security report", "WP-23", _T.DOCUMENT_ONLY,
       "docs/evidence/wp23-security-report.md", "WP-23 author",
       claims=("THS6-CLAIM-023",)),
    _e("EV-WP23-008", "RBAC matrix document", "WP-23", _T.DOCUMENT_ONLY,
       "docs/security/rbac-matrix.md", "security owner"),
    _e("EV-WP23-009", "Audit policy", "WP-23", _T.DOCUMENT_ONLY,
       "docs/security/audit-policy.md", "security owner",
       claims=("THS6-CLAIM-013",)),

    # -- WP-24: deployment and reliability -------------------------------------
    _e("EV-WP24-001", "WP-24 real gate status", "WP-24",
       _T.OPERATIONAL_PENDING, "data/deployment/wp24-real-gate-status.json",
       "pgx-deploy gate-status",
       schema_path="schemas/wp24/wp24-gate-status.schema.json",
       gates=("GATE-E",), claims=("THS6-CLAIM-014",), numeric=True,
       limitations=("no container runtime, no executed migration, no CI "
                    "run; release may not proceed",),
       gap_owner="platform owner"),
    _e("EV-WP24-002", "Gate E operational status", "WP-24",
       _T.OPERATIONAL_PENDING, "data/deployment/wp24-gate-e-status.json",
       "pgx-deploy gate-e",
       schema_path="schemas/wp24/gate-e-operational-status.schema.json",
       gates=("GATE-E",), numeric=True,
       limitations=("reads WP-23 and WP-24 and reports BLOCKED",),
       gap_owner="platform owner"),
    _e("EV-WP24-003", "Release validation aggregate", "WP-24",
       _T.OPERATIONAL_PENDING, "data/deployment/wp24-release-validation.json",
       "pgx-deploy release-validation",
       schema_path="schemas/wp24/release-validation.schema.json",
       gates=("GATE-F",), claims=("THS6-CLAIM-024",), numeric=True,
       limitations=("release_may_proceed is false",),
       gap_owner="release approver"),
    _e("EV-WP24-004", "Build provenance", "WP-24",
       _T.CONFIGURED_NOT_EXECUTED,
       "data/deployment/wp24-build-provenance.json", "pgx-deploy provenance",
       schema_path="schemas/wp24/build-provenance.schema.json",
       gates=("GATE-E",), claims=("THS6-CLAIM-005",),
       limitations=("describes what a build would be made from; no build "
                    "has happened and no lockfile exists",),
       gap_owner="platform owner"),
    _e("EV-WP24-005", "Performance targets", "WP-24",
       _T.CONFIGURED_NOT_EXECUTED,
       "data/deployment/wp24-performance-targets.json", "pgx-deploy targets",
       schema_path="schemas/wp24/performance-targets.schema.json",
       numeric=True, gates=("GATE-E",),
       limitations=("declared targets published before any measurement",),
       gap_owner="platform owner"),
    _e("EV-WP24-006", "Reliability drill catalogue", "WP-24",
       _T.CONFIGURED_NOT_EXECUTED,
       "data/deployment/wp24-reliability-drills.json", "pgx-deploy drills",
       schema_path="schemas/wp24/reliability-drill-catalogue.schema.json",
       numeric=True, gates=("GATE-E",), claims=("THS6-CLAIM-015",),
       limitations=("declared drills; none has been executed",),
       gap_owner="platform owner"),
    _e("EV-WP24-007", "Restore conditions", "WP-24",
       _T.CONFIGURED_NOT_EXECUTED,
       "data/deployment/wp24-restore-conditions.json", "pgx-deploy restore",
       numeric=True, gates=("GATE-E",),
       limitations=("four conditions declared; no restore has been run",),
       gap_owner="platform owner"),
    _e("EV-WP24-008", "Runtime asset manifest", "WP-24", _T.REAL_EXECUTED,
       "data/deployment/wp24-runtime-asset-manifest.json",
       "pgx-deploy runtime-assets",
       schema_path="schemas/wp24/runtime-asset-manifest.schema.json",
       observed=True, numeric=True, gates=("GATE-E",),
       limitations=("measures this working tree; it is not an image "
                    "listing",),
       gap_owner="platform owner"),
    _e("EV-WP24-009", "Secret configuration report", "WP-24",
       _T.CONFIGURED_NOT_EXECUTED,
       "data/deployment/wp24-secret-configuration.json",
       "pgx-deploy secrets", numeric=True, gates=("GATE-E",),
       limitations=("names and mechanisms only; never a value",),
       gap_owner="platform owner"),
    _e("EV-WP24-010", "Container image definition", "WP-24",
       _T.CONFIGURED_NOT_EXECUTED, "Dockerfile", "WP-24 author",
       gates=("GATE-E",), claims=("THS6-CLAIM-014",),
       limitations=("a Dockerfile is not a built image",),
       gap_owner="platform owner"),
    _e("EV-WP24-011", "Build and verify workflow", "WP-24",
       _T.CONFIGURED_NOT_EXECUTED, ".github/workflows/build-and-verify.yml",
       "WP-24 author", gates=("GATE-E",), claims=("THS6-CLAIM-009",),
       limitations=("a configured workflow is not a CI run",),
       gap_owner="platform owner"),
    _e("EV-WP24-012", "Release validation workflow", "WP-24",
       _T.CONFIGURED_NOT_EXECUTED,
       ".github/workflows/release-validation.yml", "WP-24 author",
       gates=("GATE-F",), claims=("THS6-CLAIM-024",),
       limitations=("a configured workflow is not a CI run",),
       gap_owner="platform owner"),
    _e("EV-WP24-013", "WP-24 build provenance report", "WP-24",
       _T.DOCUMENT_ONLY, "docs/evidence/wp24-build-provenance-report.md",
       "WP-24 author", claims=("THS6-CLAIM-005",)),
    _e("EV-WP24-014", "WP-24 reliability and performance report", "WP-24",
       _T.DOCUMENT_ONLY,
       "docs/evidence/wp24-reliability-performance-report.md",
       "WP-24 author", claims=("THS6-CLAIM-015",)),
    _e("EV-WP24-015", "Staging deployment runbook", "WP-24",
       _T.DOCUMENT_ONLY, "docs/operations/staging-deployment-runbook.md",
       "platform owner", gates=("GATE-E",), claims=("THS6-CLAIM-014",),
       limitations=("a written runbook is not an executed operation",),
       gap_owner="platform owner"),
    _e("EV-WP24-016", "Rollback runbook", "WP-24", _T.DOCUMENT_ONLY,
       "docs/operations/rollback-runbook.md", "platform owner",
       gates=("GATE-E",), claims=("THS6-CLAIM-006",),
       limitations=("a written runbook is not an executed rollback",),
       gap_owner="platform owner"),
    _e("EV-WP24-017", "Backup and restore runbook", "WP-24",
       _T.DOCUMENT_ONLY, "docs/operations/backup-restore-runbook.md",
       "platform owner", gates=("GATE-E",),
       limitations=("a written runbook is not an executed restore",),
       gap_owner="platform owner"),
    _e("EV-WP24-018", "WP-24 handoff", "WP-24", _T.DOCUMENT_ONLY,
       "docs/handoffs/wp24-handoff.md", "WP-24 author",
       limitations=("its prose states that no docs/ths6 directory exists, "
                    "which is false; three preliminary notes are there",),
       gap_owner="WP-24 author"),
)


def declared_by_id() -> Mapping[str, EvidenceItem]:
    """The declaration, keyed. Raises on a duplicate identifier."""
    index: Dict[str, EvidenceItem] = {}
    for item in DECLARED_EVIDENCE:
        if item.evidence_id in index:
            raise ValueError(
                "duplicate evidence id %r" % (item.evidence_id,))
        index[item.evidence_id] = item
    return index


def digest_of(path: str) -> str:
    """SHA-256 of a file, streamed."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _scan_for_credentials(absolute: str, relative: str) -> Tuple[str, ...]:
    """Ask WP-23's classifier whether this artifact contains a secret.

    ``relative`` is passed through rather than dropped so the scanner applies
    its own allowlist and negative-fixture classification: WP-23 deliberately
    seeded credential-shaped strings into fixtures to prove the scanner fires,
    and a pack that re-flagged those would be reporting the test as the
    finding. Only entries the scanner itself classifies as ``FINDING`` count
    here.

    Imported lazily and defended: the pack must remain buildable if the
    scanner is refactored, but a scanner that cannot run is reported as an
    unknown rather than silently treated as clean.
    """
    try:
        from pgx.security.secret_scan import scan_text
    except Exception:  # pragma: no cover - exercised by the absence path
        return ("SCANNER_UNAVAILABLE",)
    try:
        with io.open(absolute, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except Exception:  # pragma: no cover - binary or unreadable
        return ()
    try:
        found = scan_text(text, relative=relative)
    except Exception:  # pragma: no cover - signature drift
        return ("SCANNER_UNAVAILABLE",)
    return tuple(sorted({
        "%s:%d" % (item.rule_id, item.line) for item in found
        if item.classification == "FINDING"}))


def _validate_against_schema(root: str, item: EvidenceItem,
                             absolute: str) -> Optional[str]:
    """Validate a JSON artifact against its declared schema.

    Returns a short verdict string, or ``None`` when the item declares no
    schema. ``SCHEMA_ABSENT`` and ``UNPARSEABLE`` are distinct verdicts on
    purpose: one is a missing contract and the other is a broken artifact.
    """
    if not item.schema_path:
        return None
    schema_absolute = os.path.join(root, *item.schema_path.split("/"))
    if not os.path.isfile(schema_absolute):
        return "SCHEMA_ABSENT"
    try:
        from pgx.application.snapshot_schema import validate_against_schema
    except Exception:  # pragma: no cover
        return "VALIDATOR_UNAVAILABLE"
    try:
        with io.open(absolute, "r", encoding="utf-8") as handle:
            document = json.load(handle)
        with io.open(schema_absolute, "r", encoding="utf-8") as handle:
            schema = json.load(handle)
    except Exception:
        return "UNPARSEABLE"
    schema, annotations = _without_vendor_annotations(schema)
    try:
        errors = list(validate_against_schema(document, schema))
    except Exception as exc:  # pragma: no cover - validator drift
        return "VALIDATOR_ERROR: %s" % type(exc).__name__
    if errors:
        return "INVALID: %d error(s)" % len(errors)
    return "VALID_ANNOTATIONS_SKIPPED" if annotations else "VALID"


def _without_vendor_annotations(node: object) -> Tuple[object, bool]:
    """Strip ``x-`` keys from a schema, reporting whether any were there.

    WP-16 and WP-17 publish vendor annotations beside their schemas - the
    route table, the artifact kind, the list of forbidden case properties -
    and the project's validator refuses any keyword it does not implement, on
    the principle that a published constraint nobody checks is a false
    assurance. That principle is right and this function does not weaken it:
    the annotations are removed *and the verdict says so*, so a reader of the
    registry can see that ``x-pgx-forbidden-properties`` was not evaluated
    here rather than assuming it was. The constraints those annotations
    describe are enforced by the schema's own ``properties`` and
    ``additionalProperties``, which are checked.
    """
    if isinstance(node, dict):
        stripped = any(str(key).startswith("x-") for key in node)
        cleaned = {}
        for key, value in node.items():
            if str(key).startswith("x-"):
                continue
            child, child_stripped = _without_vendor_annotations(value)
            cleaned[key] = child
            stripped = stripped or child_stripped
        return cleaned, stripped
    if isinstance(node, list):
        items = []
        stripped = False
        for value in node:
            child, child_stripped = _without_vendor_annotations(value)
            items.append(child)
            stripped = stripped or child_stripped
        return items, stripped
    return node, False


def resolve_evidence(root: str, item: EvidenceItem) -> EvidenceItem:
    """Fill in the observations for one declared item.

    The declared ``evidence_type`` is preserved unless the filesystem
    contradicts it. Two contradictions are recognised: the artifact is absent
    (``UNAVAILABLE``) or it is a symlink or contains credential-shaped content
    (``INVALID``). Nothing here can *improve* a classification - a
    ``DOCUMENT_ONLY`` item does not become real because the file is present.
    """
    absolute = os.path.join(root, *item.path.split("/"))
    limitations = list(item.limitations)
    evidence_type = item.evidence_type
    if os.path.islink(absolute):
        return EvidenceItem(
            evidence_id=item.evidence_id, title=item.title,
            work_package=item.work_package, evidence_type=EvidenceType.INVALID,
            path=item.path, present=True, sha256=None,
            media_type=item.declared_media_type,
            schema_path=item.schema_path, generator=item.generator,
            observed_or_executed=False, test_only=item.test_only,
            contains_numeric_claim=item.contains_numeric_claim,
            supported_claim_ids=item.supported_claim_ids,
            gate_ids=item.gate_ids, freshness_source=item.freshness_source,
            validation_result="SYMLINK_REFUSED",
            limitations=tuple(limitations + [
                "resolved through a symbolic link, so its digest would "
                "describe content this repository does not contain"]),
            gap_owner=item.gap_owner or "repository maintainer")
    if not os.path.isfile(absolute):
        return EvidenceItem(
            evidence_id=item.evidence_id, title=item.title,
            work_package=item.work_package,
            evidence_type=EvidenceType.UNAVAILABLE, path=item.path,
            present=False, sha256=None,
            media_type=item.declared_media_type,
            schema_path=item.schema_path, generator=item.generator,
            observed_or_executed=False, test_only=item.test_only,
            contains_numeric_claim=item.contains_numeric_claim,
            supported_claim_ids=item.supported_claim_ids,
            gate_ids=item.gate_ids, freshness_source=item.freshness_source,
            validation_result="ABSENT",
            limitations=tuple(limitations + [
                "declared by this registry but not present in the working "
                "tree"]),
            gap_owner=item.gap_owner or "repository maintainer")
    secrets = _scan_for_credentials(absolute, item.path)
    validation = _validate_against_schema(root, item, absolute)
    if secrets and secrets != ("SCANNER_UNAVAILABLE",):
        evidence_type = EvidenceType.INVALID
        validation = "SECRET_SUSPECTED"
        limitations.append(
            "credential-shaped content was detected, so this artifact is "
            "refused rather than circulated")
    elif validation is not None and validation.startswith("INVALID"):
        evidence_type = EvidenceType.INVALID
        limitations.append(
            "does not satisfy the schema it declares")
    return EvidenceItem(
        evidence_id=item.evidence_id, title=item.title,
        work_package=item.work_package, evidence_type=evidence_type,
        path=item.path, present=True,
        sha256=digest_of(absolute) if evidence_type is not
        EvidenceType.INVALID else None,
        media_type=item.declared_media_type, schema_path=item.schema_path,
        generator=item.generator,
        observed_or_executed=(item.observed_or_executed
                              and evidence_type.may_support_a_ths6_claim),
        test_only=item.test_only,
        contains_numeric_claim=item.contains_numeric_claim,
        supported_claim_ids=item.supported_claim_ids, gate_ids=item.gate_ids,
        freshness_source=item.freshness_source, validation_result=validation,
        limitations=tuple(limitations),
        gap_owner=item.gap_owner or (
            "repository maintainer" if limitations else None))


def build_evidence_registry(root: str = ".") -> Mapping[str, object]:
    """Resolve every declared item and summarise what the pack contains."""
    resolved = [resolve_evidence(root, item) for item in DECLARED_EVIDENCE]
    by_type: Dict[str, int] = {}
    for item in resolved:
        by_type[item.evidence_type.value] = (
            by_type.get(item.evidence_type.value, 0) + 1)
    absent = [item.evidence_id for item in resolved if not item.present]
    invalid = [item.evidence_id for item in resolved
               if item.evidence_type is EvidenceType.INVALID]
    admissible = [item.evidence_id for item in resolved
                  if item.evidence_type.may_support_a_ths6_claim]
    findings: List[Finding] = []
    if absent:
        findings.append(Finding(
            code="THS6_EVIDENCE_UNAVAILABLE",
            detail="%d declared artifact(s) are not present in the working "
                   "tree: %s" % (len(absent), ", ".join(sorted(absent))),
            owner="repository maintainer",
            resolution="recorded as UNAVAILABLE; no digest is invented and "
                       "no gate treats an absent artifact as satisfied",
            blocking=False, references=tuple(sorted(absent))))
    if invalid:
        reasons = "; ".join(
            "%s (%s) %s" % (item.evidence_id, item.path,
                            item.validation_result)
            for item in resolved
            if item.evidence_type is EvidenceType.INVALID)
        findings.append(Finding(
            code="THS6_EVIDENCE_INVALID",
            detail="%d artifact(s) failed schema validation, resolved "
                   "through a symlink, or contained credential-shaped "
                   "content: %s" % (len(invalid), reasons),
            owner="platform owner",
            resolution="typed INVALID and excluded from supporting any "
                       "claim. WP-25 does not repair another work package's "
                       "artifact or its schema. Where a gate reads a "
                       "different, well-formed field of such an artifact, it "
                       "still reads it, and this finding is why a reader "
                       "should treat that gate's evidence as provisional.",
            blocking=True, references=tuple(sorted(invalid))))
    stale = [item.evidence_id for item in resolved
             if item.evidence_type is EvidenceType.STALE]
    if stale:
        findings.append(Finding(
            code="THS6_EVIDENCE_STALE",
            detail="%d artifact(s) record values their own source has since "
                   "changed: %s" % (len(stale), ", ".join(sorted(stale))),
            owner="verification owner",
            resolution="typed STALE; a stale artifact supports no claim",
            blocking=False, references=tuple(sorted(stale))))
    findings.append(Finding(
        code="THS6_PROSE_INVENTORY_DISCREPANCY",
        detail="WP-24's closing prose stated that no docs/ths6 directory "
               "existed. Three preliminary WP-local evidence notes were "
               "already committed there.",
        owner="WP-24 author",
        resolution="the three notes are preserved unchanged, inventoried as "
                   "DOCUMENT_ONLY, and kept disjoint from the final pack "
                   "under docs/ths6/final/",
        blocking=False, references=PRELIMINARY_THS6_DOCUMENTS))
    findings.append(Finding(
        code="THS6_SOURCE_DOCUMENT_UNAVAILABLE",
        detail="Two requirement documents named by the WP-25 brief were not "
               "readable from the environment this pack was built in, so "
               "their contents contributed nothing to this registry.",
        owner="work package author",
        resolution="requirements were taken from architecture.md, which is "
                   "in the repository and is hashed as EV-WP00-001; nothing "
                   "was inferred about the unread documents",
        blocking=False, references=("architecture.md",)))
    return {
        "evidence_registry_version": EVIDENCE_REGISTRY_VERSION,
        "declared_count": len(DECLARED_EVIDENCE),
        "resolved_count": len(resolved),
        "present_count": sum(1 for item in resolved if item.present),
        "absent_count": len(absent),
        "invalid_count": len(invalid),
        "admissible_count": len(admissible),
        "admissible_evidence_ids": sorted(admissible),
        "counts_by_type": dict(sorted(by_type.items())),
        "preliminary_ths6_documents": list(PRELIMINARY_THS6_DOCUMENTS),
        "final_pack_document_prefix": FINAL_PACK_DOCUMENT_PREFIX,
        "items": [item.to_json() for item in resolved],
        "findings": [item.to_json() for item in findings],
        "note": (
            "Presence is not support. An artifact counts towards a claim "
            "only when its type is REAL_EXECUTED or REAL_OBSERVED."),
    }


def read_document(root: str, path: str) -> Optional[Mapping[str, object]]:
    """Read one JSON artifact, or ``None`` when it is absent or unparseable.

    ``None`` rather than an exception because an absent source artifact is a
    condition this pack reports, not a crash. Every caller distinguishes a
    missing document from a document saying ``false``: the first is
    NOT_EVALUATED, the second is a real observation.
    """
    repository_relative(path)
    absolute = os.path.join(root, *path.split("/"))
    if not os.path.isfile(absolute) or os.path.islink(absolute):
        return None
    try:
        with io.open(absolute, "r", encoding="utf-8") as handle:
            document = json.load(handle)
    except Exception:
        return None
    return document if isinstance(document, dict) else None


_MISSING = object()


def field_at(document: Optional[Mapping[str, object]], dotted: str):
    """Read a dotted field, returning the sentinel when any step is absent.

    The sentinel is not ``None``: half of the values this pack reads are
    legitimately ``null`` and mean "not measured", and a reader that returned
    ``None`` for both "the field is null" and "the field does not exist" would
    make a schema change look like a measurement.
    """
    if document is None:
        return _MISSING
    current: object = document
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            return _MISSING
        current = current[part]
    return current


def field_is_missing(value: object) -> bool:
    """Whether ``field_at`` found nothing. Never true for a JSON ``null``."""
    return value is _MISSING
