# -*- coding: utf-8 -*-
"""SAFETY-INV-011 negative controls: real-data shapes that must be refused.

The intended purpose, the privacy posture, the security model and the whole
validation argument are scoped to synthetic and protocol-defined input.
Accepting real data silently invalidates all four at once.

**Nothing here is real.** These are the *shapes* a prohibited payload takes -
a key named ``patient_name`` whose value is the literal string
``"NEGATIVE-CONTROL"``, a ``vcf`` field carrying a placeholder. No genotype, no
person, no laboratory result. The point is the field name and its depth, not
the value.

The permitted payloads matter as much: ``CYP2D6`` is public gene nomenclature
and a drug name is a drug name. A detector that refused those would make the
product unusable for the thing it exists to do.
"""

from __future__ import annotations

from typing import Any, Dict, Sequence, Tuple

_PLACEHOLDER = "NEGATIVE-CONTROL"


def permitted_payload() -> Dict[str, Any]:
    """The safe control: a synthetic phenotype profile and a medication list.

    Contains gene symbols and drug names on purpose. Both are public
    nomenclature and neither is patient data.
    """
    return {
        "profile": {
            "kind": "SYNTHETIC_PHENOTYPE_PROFILE",
            "phenotypes": {"CYP2D6": "POOR", "CYP2C19": "RAPID"},
        },
        "medications": ["SYNTHDRUG-1", "SYNTHDRUG-2"],
    }


def nested_genotype_payload() -> Dict[str, Any]:
    """NC-INV-011-NESTED-GENOTYPE-FIELD - four levels down.

    The field a top-level scan misses. Real request bodies nest, and a check
    that only walks the first level of keys is the commonest version of this
    control that does not work.
    """
    return {
        "profile": {
            "kind": "SYNTHETIC_PHENOTYPE_PROFILE",
            "metadata": {
                "provenance": {
                    "upstream": {"genotype": _PLACEHOLDER},
                },
            },
        },
        "medications": ["SYNTHDRUG-1"],
    }


def patient_identifier_payload() -> Dict[str, Any]:
    """NC-INV-011-PATIENT-IDENTIFIER - a direct identifier, inside a list."""
    return {
        "profile": {"kind": "SYNTHETIC_PHENOTYPE_PROFILE"},
        "subjects": [
            {"patient_name": _PLACEHOLDER, "mrn": _PLACEHOLDER,
             "date_of_birth": _PLACEHOLDER},
        ],
        "medications": ["SYNTHDRUG-1"],
    }


def raw_sequencing_payload() -> Dict[str, Any]:
    """NC-INV-011-RAW-SEQUENCING-PAYLOAD - VCF, diplotype, star allele."""
    return {
        "profile": {"kind": "SYNTHETIC_PHENOTYPE_PROFILE"},
        "attachments": {
            "vcf": _PLACEHOLDER,
            "diplotype": _PLACEHOLDER,
            "star_allele": _PLACEHOLDER,
        },
        "medications": ["SYNTHDRUG-1"],
    }


def pilot_mode_payload() -> Dict[str, Any]:
    """NC-INV-011-PILOT-MODE-REQUESTED - the mode that is disabled in P0.

    ``PILOT`` exists in the enum so that the disabled state is explicit,
    testable and auditable rather than merely absent. Requesting it is a
    request to accept real data.
    """
    return {
        "mode": "PILOT",
        "profile": {"kind": "SYNTHETIC_PHENOTYPE_PROFILE"},
        "medications": ["SYNTHDRUG-1"],
    }


def top_level_only_detector(payload: Any) -> Sequence[str]:
    """A detector that walks one level and stops.

    Catches ``{"genotype": ...}`` and misses the same key four levels down. It
    is the shape of check that passes review because the test that exercised it
    used a flat fixture.
    """
    prohibited = ("patient_name", "mrn", "date_of_birth", "genotype",
                  "diplotype", "star_allele", "vcf", "fastq", "bam")
    if not isinstance(payload, dict):
        return ()
    return tuple("$.%s" % key for key in payload
                 if str(key).lower() in prohibited)


def payload_cases() -> Tuple[Tuple[str, Any, bool], ...]:
    """``(label, payload, expected_prohibited)`` - both directions."""
    return (
        ("permitted/synthetic-profile", permitted_payload(), False),
        ("permitted/gene-symbols",
         {"phenotypes": {"CYP2D6": "POOR", "CYP3A4": "NORMAL"}}, False),
        ("prohibited/nested-genotype", nested_genotype_payload(), True),
        ("prohibited/patient-identifier", patient_identifier_payload(), True),
        ("prohibited/raw-sequencing", raw_sequencing_payload(), True),
    )


UNSAFE_SUBJECTS = {
    "NC-INV-011-NESTED-GENOTYPE-FIELD": nested_genotype_payload,
    "NC-INV-011-PATIENT-IDENTIFIER": patient_identifier_payload,
    "NC-INV-011-RAW-SEQUENCING-PAYLOAD": raw_sequencing_payload,
    "NC-INV-011-PILOT-MODE-REQUESTED": pilot_mode_payload,
}
