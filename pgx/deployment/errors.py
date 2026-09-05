# -*- coding: utf-8 -*-
"""Deployment errors (WP-24).

Three classes, and the distinction between them is the distinction the exit
codes make: something was wrong (``DeploymentFailure``), something has not
happened (``DeploymentBlocked``), or the request could not be honoured as
asked (``DeploymentUsageError``).

Nothing here ever carries a secret. A configuration error names the *variable*
that is wrong, never the value it held - a message quoting a rejected DSN is
the same disclosure the rejection existed to prevent, arriving through the
error path.
"""

from __future__ import annotations

from typing import Mapping, Optional

from pgx.deployment.vocabulary import (EXIT_BLOCKED, EXIT_FAILURE, EXIT_USAGE,
                                       DEPLOYMENT_BLOCKER_CODES)

__all__ = [
    "DeploymentBlocked",
    "DeploymentError",
    "DeploymentFailure",
    "DeploymentUsageError",
    "SecretConfigurationError",
]


class DeploymentError(RuntimeError):
    """Base. Carries the exit code the caller should return."""

    exit_code = EXIT_FAILURE

    def __init__(self, message: str, *,
                 details: Optional[Mapping[str, object]] = None) -> None:
        super().__init__(message)
        self.details: Mapping[str, object] = dict(details or {})


class DeploymentFailure(DeploymentError):
    """The operation ran and something was wrong with the result."""

    exit_code = EXIT_FAILURE


class DeploymentBlocked(DeploymentError):
    """The operation did not run, and a named precondition is why.

    Requires a declared blocker code and an owner, so that a refusal reaching
    a log is searchable and attributable rather than a sentence.
    """

    exit_code = EXIT_BLOCKED

    def __init__(self, code: str, *, owner: str,
                 detail: Optional[str] = None,
                 details: Optional[Mapping[str, object]] = None) -> None:
        if code not in DEPLOYMENT_BLOCKER_CODES:
            raise ValueError(
                "%r is not a declared WP-24 blocker code" % (code,))
        self.code = code
        self.owner = owner
        self.detail = detail or DEPLOYMENT_BLOCKER_CODES[code]
        super().__init__(self.detail, details=details)


class DeploymentUsageError(DeploymentError):
    """The request was malformed: unknown target, missing argument, or a
    contract the command refuses to honour (a broad target, for instance)."""

    exit_code = EXIT_USAGE


class SecretConfigurationError(DeploymentUsageError):
    """Secret configuration is absent, ambiguous or unreadable.

    Names the variable and the problem. Never the value, never the file's
    contents, and never a length - a length is a fact about a secret.
    """

    def __init__(self, variable: str, problem: str) -> None:
        super().__init__("%s: %s" % (variable, problem),
                         details={"variable": variable})
        self.variable = variable
