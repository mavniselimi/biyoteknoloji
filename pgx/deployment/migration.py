# -*- coding: utf-8 -*-
"""Running migrations, as an operator action (WP-24).

Never on start-up. That is the whole design constraint, and it is not a style
preference: an application that upgraded its own schema would apply ``0011``
from whichever replica booted first, concurrently, against a database whose
``downgrade()`` refuses to run while any user, session or governed audit event
exists. The failure mode is a half-migrated schema that cannot be rolled back
by the tool that half-migrated it.

So migration is a command a person runs, once, with the target printed first.
This module is what that command calls, and it does four things:

1. reports the chain's head **from the revision files**, without a database;
2. confirms there is exactly one head, because a branched history has no
   answer to "are we up to date";
3. reports the database's current revision, when one is reachable;
4. upgrades, when asked, and reports what changed.

Every one of them can report BLOCKED, and the difference between "no database"
and "the database is behind" is preserved: they need different actions from
different people.
"""

from __future__ import annotations

import ast
import io
import os
from typing import Mapping, Optional, Sequence, Tuple

from pgx.deployment.vocabulary import ExecutionState, blocker

__all__ = [
    "MIGRATION_RESULT_VERSION",
    "chain_heads",
    "current_database_revision",
    "migration_status",
    "upgrade_to_head",
]

MIGRATION_RESULT_VERSION = "pgx-wp24-migration-result/1"

MIGRATIONS_DIRECTORY = os.path.join("migrations", "versions")


def _revision_files(root: str) -> Sequence[str]:
    directory = os.path.join(root, MIGRATIONS_DIRECTORY)
    if not os.path.isdir(directory):
        return ()
    return tuple(sorted(
        name for name in os.listdir(directory)
        if name.endswith(".py") and not name.startswith("__")))


def chain_heads(root: str = ".") -> Mapping[str, object]:
    """Read the revision graph from the files, with the AST.

    Text matching is wrong here for a reason this repository has already hit
    once: ``down_revision: Union[str, None] = "0010_..."`` contains the word
    ``None`` in its *annotation*, and a line-matching version of this found no
    parents at all and reported a chain of eleven heads.
    """
    revisions = {}
    downs = {}
    for name in _revision_files(root):
        path = os.path.join(root, MIGRATIONS_DIRECTORY, name)
        with io.open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        revision = down = None
        for node in tree.body:
            if not isinstance(node, ast.AnnAssign) or \
                    not isinstance(node.target, ast.Name) or \
                    not isinstance(node.value, ast.Constant):
                continue
            if node.target.id == "revision":
                revision = node.value.value
            elif node.target.id == "down_revision":
                down = node.value.value
        if revision:
            revisions[revision] = name
            if down:
                downs[revision] = down
    parents = set(downs.values())
    heads = sorted(set(revisions) - parents)
    return {
        "revision_count": len(revisions),
        "file_count": len(_revision_files(root)),
        "heads": heads,
        "single_head": len(heads) == 1,
        "head": heads[0] if len(heads) == 1 else None,
        "note": (
            "Read with the AST, not by matching text: a down_revision "
            "annotation contains the word None and a line-matching reader "
            "finds no parents at all."),
    }


def current_database_revision(engine: object) -> Tuple[Optional[str], str]:
    """The revision stamped in the database, or ``(None, reason)``.

    Reads ``alembic_version`` directly. Importing Alembic here would load
    every revision module to answer a one-row question, and a syntax error in
    an unrelated revision would then look like an unreachable database.
    """
    try:
        from sqlalchemy import text

        with engine.connect() as connection:  # type: ignore[attr-defined]
            rows = list(connection.execute(
                text("SELECT version_num FROM alembic_version")).scalars())
    except Exception as error:  # noqa: BLE001 - reason, never a DSN
        return None, type(error).__name__
    if not rows:
        return None, "no revision is stamped: no migration has been run"
    if len(rows) > 1:
        return None, ("more than one revision is stamped, so there is no "
                      "single answer to which head this database is at")
    return rows[0], ""


def migration_status(root: str = ".", *, engine: object = None,
                     expected_head: Optional[str] = None
                     ) -> Mapping[str, object]:
    """Where the chain is, where the database is, and whether they agree."""
    chain = chain_heads(root)
    expected = expected_head or chain["head"]
    blockers = []
    state = ExecutionState.CONFIGURED
    database_revision = None
    reason = ""
    if not chain["single_head"]:
        blockers.append(dict(blocker(
            "DEPLOY_MIGRATION_HEAD_MISMATCH",
            owner="whoever added a migration",
            detail=("the revision chain has %d heads; a branched history has "
                    "no answer to whether a database is up to date"
                    % len(chain["heads"]))  # type: ignore[arg-type]
        ).to_json()))
    if engine is None:
        blockers.append(dict(blocker(
            "DEPLOY_DATABASE_UNAVAILABLE",
            owner="the deployment",
            detail=("no engine was supplied, so the database's revision was "
                    "not read; the chain above is a fact about the files "
                    "only")).to_json()))
        state = ExecutionState.BLOCKED
    else:
        database_revision, reason = current_database_revision(engine)
        if database_revision is None:
            blockers.append(dict(blocker(
                "DEPLOY_MIGRATION_NOT_EXECUTED", owner="an operator",
                detail=reason).to_json()))
            state = ExecutionState.BLOCKED
        elif expected and database_revision != expected:
            blockers.append(dict(blocker(
                "DEPLOY_MIGRATION_HEAD_MISMATCH", owner="an operator",
                detail=("the database is at %s and this build expects %s"
                        % (database_revision, expected))).to_json()))
            state = ExecutionState.BLOCKED
        else:
            state = ExecutionState.VERIFIED
    return {
        "migration_result_version": MIGRATION_RESULT_VERSION,
        "state": state.value,
        "chain": chain,
        "expected_head": expected,
        "database_revision": database_revision,
        "database_revision_note": reason or None,
        "executed": database_revision is not None,
        "blockers": blockers,
        "note": (
            "A migration is an operator command. Nothing in this project "
            "runs one during application start-up, and 0011's downgrade "
            "refuses to run while any user, session or governed audit event "
            "exists - so a half-applied upgrade is not something the "
            "application can undo for itself."),
    }


def upgrade_to_head(database_url: str, *, root: str = ".",
                    runner=None) -> Mapping[str, object]:
    """Run ``alembic upgrade head`` against one named database.

    The URL is passed through the environment rather than on the command
    line: an argument is visible in the process table to every user on the
    host, and a DSN carries a password.
    """
    import subprocess  # noqa: S404 - running the migration tool is the point

    chain = chain_heads(root)
    if not chain["single_head"]:
        return {
            "migration_result_version": MIGRATION_RESULT_VERSION,
            "state": ExecutionState.BLOCKED.value, "executed": False,
            "chain": chain,
            "blockers": [dict(blocker(
                "DEPLOY_MIGRATION_HEAD_MISMATCH",
                owner="whoever added a migration",
                detail="refusing to upgrade a branched chain").to_json())],
        }
    run = runner or (lambda argv, env: subprocess.run(  # noqa: S603
        argv, cwd=root, capture_output=True, text=True, timeout=900,
        check=False, env=dict(os.environ, **env)))
    completed = run(["alembic", "upgrade", "head"],
                    {"DATABASE_URL": database_url})
    code = getattr(completed, "returncode", 1)
    if code != 0:
        return {
            "migration_result_version": MIGRATION_RESULT_VERSION,
            "state": ExecutionState.NOT_EXECUTED.value, "executed": False,
            "chain": chain,
            "blockers": [dict(blocker(
                "DEPLOY_MIGRATION_NOT_EXECUTED", owner="an operator",
                detail="alembic upgrade head exited %d" % code).to_json())],
            # The tail is truncated and the URL is never echoed: alembic
            # quotes a failing DSN back in some errors.
            "output_tail": (getattr(completed, "stderr", "") or "")
            .splitlines()[-3:],
        }
    return {
        "migration_result_version": MIGRATION_RESULT_VERSION,
        "state": ExecutionState.EXECUTED.value, "executed": True,
        "chain": chain, "applied_head": chain["head"], "blockers": [],
    }
