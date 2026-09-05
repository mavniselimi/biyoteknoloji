# -*- coding: utf-8 -*-
"""WP-18 - validation dataset architecture: curation versus holdout.

This package answers one question and refuses to answer a second.

The question it answers: **which side of the line is this case on, and can it
have crossed?** Development cases shaped the software. Holdout cases were held
back so that measuring against them means something. Keeping the two apart is
not a matter of labelling - a copied case, a renamed case, a case built from
the same source vignette by the same hand all cross the line while looking
like they have not - so the separation is enforced by construction and by an
audit that refuses.

The question it does not answer: **how well does the software do?** No metric,
no rate, no percentage and no denominator appears anywhere in this package.
WP-21 owns that, and it cannot start honestly until there is something to
count. Today there is not: this repository holds seven development fixtures
and zero holdout cases, and the gate status says so in those words.

Three things worth knowing before reading further:

- A validation case is two objects. ``ValidationCaseMetadata`` is publishable
  and has no field for an answer or a payload; ``RestrictedPayload`` holds the
  inputs and is never committed beside the rules it tests.
- Nothing here is authenticated. An access context is a caller's claim about
  itself, recorded as a claim. WP-23 owns identity.
- Nothing here is approved by code. No release is activated, no case is
  accepted as evidence, no claim boundary moves.
"""

from __future__ import annotations

from pgx.validation.access import (AccessContext, AccessDecision, AccessEvent,
                                   AccessLedger, decide_access)
from pgx.validation.cases import (CASE_SCHEMA_VERSION, PROHIBITED_CASE_FIELDS,
                                  Provenance, RestrictedPayload,
                                  ValidationCaseId, ValidationCaseMetadata,
                                  assert_no_prohibited_fields,
                                  default_visibility_for)
from pgx.validation.compatibility import ReleaseCompatibility
from pgx.validation.errors import (AccessDeniedError, CompatibilityError,
                                   FingerprintError, ImportRefusedError,
                                   ProvenanceError, RestrictedContentError,
                                   SeparationError, ValidationCaseError,
                                   ValidationDatasetError, VisibilityError)
from pgx.validation.fingerprint import (CONTENT_FINGERPRINT_VERSION,
                                        content_fingerprint,
                                        derivation_family_fingerprint)
from pgx.validation.manifests import (CASE_MANIFEST_VERSION,
                                      P0_TARGET_CASE_COUNT,
                                      build_case_manifest,
                                      build_holdout_manifest)
from pgx.validation.separation import (SeparationAudit, SeparationIssue,
                                       audit_partition, require_separation)
from pgx.validation.vocabulary import (VOCABULARY_VERSION, AccessAction,
                                       AccessContextKind, DataClassification,
                                       PayloadAvailability,
                                       ValidationCaseRole, VisibilityLevel)

__all__ = [
    "AccessAction",
    "AccessContext",
    "AccessContextKind",
    "AccessDecision",
    "AccessDeniedError",
    "AccessEvent",
    "AccessLedger",
    "CASE_MANIFEST_VERSION",
    "CASE_SCHEMA_VERSION",
    "CONTENT_FINGERPRINT_VERSION",
    "CompatibilityError",
    "DataClassification",
    "FingerprintError",
    "ImportRefusedError",
    "P0_TARGET_CASE_COUNT",
    "PROHIBITED_CASE_FIELDS",
    "PayloadAvailability",
    "Provenance",
    "ProvenanceError",
    "ReleaseCompatibility",
    "RestrictedContentError",
    "RestrictedPayload",
    "SeparationAudit",
    "SeparationError",
    "SeparationIssue",
    "VOCABULARY_VERSION",
    "ValidationCaseError",
    "ValidationCaseId",
    "ValidationCaseMetadata",
    "ValidationCaseRole",
    "ValidationDatasetError",
    "VisibilityError",
    "VisibilityLevel",
    "assert_no_prohibited_fields",
    "audit_partition",
    "build_case_manifest",
    "build_holdout_manifest",
    "content_fingerprint",
    "decide_access",
    "default_visibility_for",
    "derivation_family_fingerprint",
    "require_separation",
]
