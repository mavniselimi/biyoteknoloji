"""Request correlation identity, and the one rule about where it may not go.

Every response carries an ``X-Request-ID``. It exists so an operator reading a
log line, an audit row and a client's bug report can tell they are looking at
the same request. It is *correlation* metadata: it says which call this was,
never what the call concluded.

That distinction is the whole of this module's safety content. A request id
must reach the audit trail and must not reach ``input_hash``, ``output_hash``,
``coverage_result_hash`` or any report hash. Those hashes are the mechanism by
which two runs of the same question are recognised as the same answer; mixing
a per-call random value into one would make every assessment unique, which
does not make the system safer - it makes the determinism claim untestable and
quietly false. Nothing in this module is reachable from the hashing path, and
:mod:`tests.unit.api.test_request_context` asserts that a changed request id
leaves every semantic hash byte-identical.

**The acceptance contract, stated once.** A caller may supply
``X-Request-ID``. It is accepted only if it is a canonical lowercase UUID -
36 characters, the shape :func:`uuid.UUID` produces. Anything else is
*rejected* with ``REQUEST_ID_INVALID`` rather than quietly replaced.

Rejecting is the less obvious half, so: silently generating a substitute would
mean the server's logs and the client's logs name different ids for the same
call, and the client would have no way to notice. A header that is nearly a
UUID is far more often a client defect or an injection probe than a benign
variation, and a defect that surfaces as a 400 on the first call is cheaper
than one that surfaces as an unreproducible support ticket. The absent header
is the benign case, and that one is generated.
"""

from __future__ import annotations

import re
import uuid
from typing import Optional

__all__ = [
    "REQUEST_ID_HEADER",
    "REQUEST_ID_PATTERN",
    "generate_request_id",
    "is_valid_request_id",
    "resolve_request_id",
]

REQUEST_ID_HEADER = "X-Request-ID"

#: The exact accepted shape. Lowercase hexadecimal, canonical dashes, any
#: version nibble. Deliberately not ``uuid.UUID(value)``: that constructor
#: accepts braces, URNs, uppercase and a bare 32-character run, so using it
#: would mean the value a client sent and the value the server logs could
#: differ by punctuation while both "validated".
REQUEST_ID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

#: The rendered length, kept as a constant so the length check reads as a
#: cheap guard rather than as a second, subtly different, format rule.
REQUEST_ID_LENGTH = 36


def generate_request_id() -> str:
    """A fresh correlation id for a request that arrived without one."""
    return str(uuid.uuid4())


def is_valid_request_id(value: object) -> bool:
    """Whether ``value`` is a request id this API will echo back unchanged."""
    if not isinstance(value, str) or len(value) != REQUEST_ID_LENGTH:
        return False
    return REQUEST_ID_PATTERN.match(value) is not None


def resolve_request_id(supplied: Optional[str]) -> str:
    """Return the request id for this call, or refuse the supplied one.

    Args:
        supplied: the raw ``X-Request-ID`` header value, or ``None`` when the
            caller sent none.

    Returns:
        The caller's id when it is canonical, otherwise a generated one.

    Raises:
        RequestContractError: the caller sent a header that is not a canonical
            UUID. The rejected value is not echoed - a client that sent
            ``<script>`` in a header should not receive it back in a body.
    """
    from apps.api.errors import RequestContractError

    if supplied is None:
        return generate_request_id()
    if is_valid_request_id(supplied):
        return supplied
    raise RequestContractError(
        "REQUEST_ID_INVALID",
        details={"issues": [{"location": "$.headers." + REQUEST_ID_HEADER,
                             "code": "PATTERN_MISMATCH"}]})
