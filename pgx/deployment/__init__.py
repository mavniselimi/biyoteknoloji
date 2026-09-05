# -*- coding: utf-8 -*-
"""Build, deployment, performance and reliability (WP-24).

This package is where the difference between *implemented*, *configured*,
*executed*, *observed* and *verified* is made mechanical rather than
rhetorical. Every document it produces carries those states in separate
fields, and they are allowed to disagree, because in this repository they do:
the machinery exists and almost none of it has run anywhere.

Nothing here connects, builds, downloads or starts anything at import. The
modules are measurement and composition; execution happens when a command
calls one of them, and a command that could not execute says so rather than
returning a shape that reads like success.

What the package contains, and why each part is separate:

``vocabulary``
    The states themselves, plus the blocker codes and process exit codes. One
    definition, so a CLI, a schema and a gate status cannot drift.
``environment``
    A *probe*. It reports what this host actually has - a Python version, a
    container runtime that answered, a package index that resolved - and never
    what the code supports. Every BLOCKED status in WP-24 traces back to one
    of its findings.
``secrets``
    ``*_FILE`` configuration reading, and only there. Values read here never
    reach a log line, a readiness detail, an exception or an artifact.
``composition``
    The real deployment provider: engines, request-scoped sessions,
    repositories, and the transaction in which a governed change and its audit
    record either both happen or neither does.
``rate_limit_store``
    The PostgreSQL counter, as one atomic statement. A read-then-write here
    would lose exactly the race it exists to win.
``provenance``/``runtime_assets``/``packaging``/``image``
    What was built, from what, containing what. Including the source-tree
    manifest that stands in for a commit hash this repository does not have.
``migration``/``smoke``/``performance``/``reliability``/``rollback``
``backup_execution``/``supply_chain``
    Operations. Each records what it did, or records that it did not and why.
``release_validation``/``gate_status``/``artifacts``
    The aggregate. It inspects the other documents; it never assumes them.

The rule the whole package is written against: an absent deployment, an
unstarted container, an unexecuted migration, an unrun scan, a missing
release and an absent human approval are each a distinct state with a named
owner, and none of them is a pass.
"""

from __future__ import annotations

from pgx.deployment.vocabulary import (  # noqa: F401
    DEPLOYMENT_VOCABULARY_VERSION,
    EXIT_BLOCKED,
    EXIT_FAILURE,
    EXIT_SUCCESS,
    EXIT_USAGE,
    DeploymentBlocker,
    DeploymentEnvironmentKind,
    ExecutionState,
)

__all__ = [
    "DEPLOYMENT_VOCABULARY_VERSION",
    "EXIT_BLOCKED",
    "EXIT_FAILURE",
    "EXIT_SUCCESS",
    "EXIT_USAGE",
    "DeploymentBlocker",
    "DeploymentEnvironmentKind",
    "ExecutionState",
]
