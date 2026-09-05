# -*- coding: utf-8 -*-
"""The blind review protocol and its approval contract (WP-22).

A protocol is a document plus the fact that named people approved it. This
module models the second half, and it fails closed.

**Why approval is a structure rather than a boolean.** A boolean can be set.
An approval here is a list of signatories, each with a name, an affiliation, a
role and a decision date, plus the digest of the exact protocol text they
signed. ``is_approved`` is computed from that list and cannot be assigned. So
"approve the protocol" is not something code can do - it requires supplying
people, and there is no path in this repository that invents one.

**Why the text digest is part of it.** An approval that did not name the bytes
it approved would survive an edit to the protocol. It does not: change
``docs/validation/expert-protocol.md`` and every existing signature stops
matching, which is the correct outcome - a protocol amended after approval has
not been approved.

The committed manifest in this repository has an empty signatory list and
``approved: false``. That is the truthful state and no fixture, flag or
environment variable changes it in production; the TEST-ONLY approved protocol
used by workflow tests is constructed in the test suite and injected.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import io
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from pgx.expert_review.errors import ProtocolNotApprovedError

__all__ = [
    "PROTOCOL_DOCUMENT_PATH",
    "PROTOCOL_VERSION",
    "REQUIRED_SIGNATORY_ROLES",
    "ExpertProtocol",
    "ProtocolSignatory",
    "load_protocol",
    "protocol_document_digest",
    "require_approved",
]

PROTOCOL_VERSION = "pgx-wp22-expert-protocol/1"

#: The document this manifest is about. Read for its digest, never parsed.
PROTOCOL_DOCUMENT_PATH = "docs/validation/expert-protocol.md"

#: Approval needs all four. A protocol signed only by the people who built the
#: software is not an independent protocol, which is why the scientific and
#: independent roles are separate rows rather than optional extras.
REQUIRED_SIGNATORY_ROLES: Tuple[str, ...] = (
    "PRODUCT_TECHNICAL_OWNER",
    "SCIENTIFIC_ADVISOR",
    "RISK_MANAGEMENT_OWNER",
    "INDEPENDENT_REVIEWER",
)

_NAME = re.compile(r"^[^\x00-\x1f]{2,120}$")


def protocol_document_digest(root: str) -> Optional[str]:
    """The digest of the protocol text, or ``None`` when it is absent.

    ``None`` rather than an exception: a repository without the document has a
    documented state (undocumented protocol) that the gate reports, and
    raising here would turn a reportable condition into a crash.
    """
    path = os.path.join(root, *PROTOCOL_DOCUMENT_PATH.split("/"))
    if not os.path.isfile(path):
        return None
    with io.open(path, "rb") as handle:
        return "sha256:" + hashlib.sha256(handle.read()).hexdigest()


@dataclass(frozen=True, slots=True)
class ProtocolSignatory:
    """One named person who approved one exact version of the protocol.

    Every field is required. A signatory with no affiliation, no date or no
    digest is not a weaker signature - it is not a signature, and accepting
    one would let an approval be assembled out of blanks.
    """

    name: str
    affiliation: str
    role: str
    decided_on: str
    approved_document_digest: str
    #: Where the signature itself lives - a signed PDF, a minuted decision, a
    #: change-control record. Free text, required, and never a URL this code
    #: fetches: the reference is for a human auditor.
    record_reference: str

    def __post_init__(self) -> None:
        for name, value in (("name", self.name),
                            ("affiliation", self.affiliation),
                            ("record_reference", self.record_reference)):
            if not _NAME.match(str(value or "")):
                raise ValueError(
                    "a protocol signatory needs a real %s; a blank one is not "
                    "a weaker signature, it is not a signature" % name)
        if self.role not in REQUIRED_SIGNATORY_ROLES:
            raise ValueError("unknown signatory role %r" % self.role)
        try:
            _dt.date.fromisoformat(str(self.decided_on))
        except (TypeError, ValueError):
            raise ValueError("decided_on is an ISO date") from None
        if not re.match(r"^sha256:[0-9a-f]{64}$",
                        str(self.approved_document_digest or "")):
            raise ValueError(
                "a signatory approves an exact document digest; an approval "
                "that did not name the bytes would survive an edit to them")

    def to_json(self) -> Dict[str, Any]:
        return {"name": self.name, "affiliation": self.affiliation,
                "role": self.role, "decided_on": self.decided_on,
                "approved_document_digest": self.approved_document_digest,
                "record_reference": self.record_reference}


@dataclass(frozen=True, slots=True)
class ExpertProtocol:
    """The protocol manifest: which document, which version, who approved it.

    ``is_approved`` is a property, not a field. There is deliberately no way
    to construct an approved protocol without supplying four signatories whose
    digests match the document - which is to say, without four people having
    actually approved it.
    """

    protocol_version: str
    document_path: str
    document_digest: Optional[str]
    status: str
    signatories: Tuple[ProtocolSignatory, ...] = field(default_factory=tuple)
    note: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "signatories", tuple(self.signatories))

    @property
    def is_documented(self) -> bool:
        return self.document_digest is not None

    @property
    def is_approved(self) -> bool:
        """Four required roles, all signing the current document digest.

        Every clause matters. Missing a role means the approval is not
        independent. A signature on a different digest means the document
        changed after signing. An undocumented protocol cannot be approved at
        all, because there is nothing to have approved.
        """
        if self.document_digest is None or not self.signatories:
            return False
        signed_roles = set()
        for signatory in self.signatories:
            if signatory.approved_document_digest != self.document_digest:
                return False
            signed_roles.add(signatory.role)
        return signed_roles.issuperset(set(REQUIRED_SIGNATORY_ROLES))

    @property
    def missing_signatory_roles(self) -> Tuple[str, ...]:
        signed = {item.role for item in self.signatories}
        return tuple(role for role in REQUIRED_SIGNATORY_ROLES
                     if role not in signed)

    def protocol_hash(self) -> str:
        """Pinned into every assignment, expectation, reveal and completion.

        Covers the document digest and the approval state together, so a
        review carries which protocol text *and* which approval condition it
        was conducted under. A review begun under an approval that was later
        withdrawn is detectable rather than indistinguishable.
        """
        from pgx.domain.hashing import sha256_digest
        return sha256_digest({
            "protocol_version": self.protocol_version,
            "document_path": self.document_path,
            "document_digest": self.document_digest,
            "approved": self.is_approved,
            "signatory_roles": sorted(item.role for item in self.signatories),
        })

    def to_json(self) -> Dict[str, Any]:
        return {
            "protocol_version": self.protocol_version,
            "document_path": self.document_path,
            "document_digest": self.document_digest,
            "documented": self.is_documented,
            "status": self.status,
            "approved": self.is_approved,
            "required_signatory_roles": list(REQUIRED_SIGNATORY_ROLES),
            "signatory_count": len(self.signatories),
            "missing_signatory_roles": list(self.missing_signatory_roles),
            "signatories": [item.to_json() for item in self.signatories],
            "protocol_hash": self.protocol_hash(),
            "note": self.note,
        }


def load_protocol(root: str,
                  signatories: Sequence[ProtocolSignatory] = ()
                  ) -> ExpertProtocol:
    """The protocol as this repository actually holds it.

    ``signatories`` defaults to empty and there is no code path that populates
    it from disk. That is not an oversight: a signature list read from a file
    somebody could edit is not an approval record, and building one would put
    the approval of a clinical protocol one text editor away.

    When real approvals exist they will arrive through a change to this
    function that names where they are read from and how they are verified -
    a visible change, reviewed as such.
    """
    digest = protocol_document_digest(root)
    return ExpertProtocol(
        protocol_version=PROTOCOL_VERSION,
        document_path=PROTOCOL_DOCUMENT_PATH,
        document_digest=digest,
        status=("DRAFT / AWAITING HUMAN AND SCIENTIFIC REVIEW"),
        signatories=tuple(signatories),
        note=("The protocol document exists and is not approved. Approval "
              "requires four named people signing the exact document digest; "
              "no code path in this repository can supply them."
              if digest else
              "No protocol document is committed, so there is nothing to "
              "approve."))


def require_approved(protocol: ExpertProtocol) -> None:
    """Raise unless the protocol is approved. Called before anything else.

    First check in every governed operation, deliberately: an unapproved
    protocol must not be able to produce a partial record, a permit, an audit
    event or a receipt.
    """
    if not protocol.is_approved:
        raise ProtocolNotApprovedError(
            details={"documented": protocol.is_documented,
                     "missing_signatory_roles":
                         list(protocol.missing_signatory_roles)})
