# -*- coding: utf-8 -*-
"""Deliberately unsafe strings, one per scanner rule (WP-23, TEST-ONLY).

Every value below is invented, matches no real system, and authenticates
nobody. They exist for one purpose: to prove that each detection rule
actually detects something. A rule with no fixture proving it fires is a rule
nobody has run, and the first time anyone finds out is when it fails to catch
a real secret.

This file is classified as a negative fixture by
:data:`pgx.security.secret_scan.NEGATIVE_FIXTURES` - **classified, not
ignored**. Findings here still appear in the scan output with their
classification, so a real secret committed into this file would still be
visible to a reader. What the classification changes is only that these do
not count toward the blocking total.

The key shapes below are structurally valid and cryptographically worthless:
the private key body is the word "NOT" repeated, and every token is a fixed
literal with an obviously synthetic body.
"""

from __future__ import annotations

from typing import Mapping, Tuple

__all__ = ["NEGATIVE_CONTROLS", "controls_for_rule"]

#: One unsafe string per rule id. Each is written so that a reader can see at
#: a glance it is synthetic, while still matching the rule's shape exactly -
#: a control that did not match would prove nothing.
NEGATIVE_CONTROLS: Mapping[str, Tuple[str, ...]] = {
    "SEC-001-PRIVATE-KEY": (
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "NOTNOTNOTNOTNOTNOTNOTNOTNOTNOTNOTNOTNOTNOTNOTNOTNOTNOTNOTNOT\n"
        "-----END RSA PRIVATE KEY-----",
        "-----BEGIN OPENSSH PRIVATE KEY-----",
    ),
    "SEC-002-CLOUD-TOKEN": (
        "AKIA" + "NOTAREALKEYID000",
        "ghp_" + "0notarealgithubtokenvalue0000000000000",
        "xoxb-" + "000000000000-notarealslacktoken",
    ),
    "SEC-003-BEARER-LITERAL": (
        'Authorization: "Bearer not-a-real-bearer-token-value"',
        "Cookie: __Host-pgx_session=not-a-real-session-value",
    ),
    "SEC-004-PASSWORD-ASSIGNMENT": (
        'password = "n0t-a-real-password-value"',
        'client_secret: "n0t-a-real-client-secret"',
    ),
    "SEC-005-DSN-CREDENTIAL": (
        "postgresql+psycopg://appuser:n0tarealpassword@db.invalid:5432/pgx",
        "mongodb://svcacct:n0tarealpassword@cluster.invalid/records",
    ),
    "SEC-007-ARGON2-HASH": (
        "$argon2id$v=19$m=65536,t=3,p=4$"
        "bm90YXJlYWxzYWx0dmFs$bm90YXJlYWxoYXNodmFsdWVub3RhcmVhbA",
    ),
}


def controls_for_rule(rule_id: str) -> Tuple[str, ...]:
    """The unsafe strings that must make ``rule_id`` fire."""
    if rule_id not in NEGATIVE_CONTROLS:
        raise KeyError(
            "%r has no negative control; a rule nobody has proven detects "
            "anything is a rule nobody has run" % rule_id)
    return NEGATIVE_CONTROLS[rule_id]
