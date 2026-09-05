# -*- coding: utf-8 -*-
"""``pgx-deploy`` - the one documented deployment command (WP-24).

Every operational action goes through here, and every one of them returns a
process exit code a pipeline can branch on:

    0  the work ran and the condition held
    1  the work ran and something was wrong
    2  blocked, not executed, or stale - not a software failure, a statement
       that the thing being asked about did not happen
    3  the request was malformed: unknown target, missing argument, or a
       contract this command refuses to honour

Exit 2 is the one that matters. Most subcommands return it in this repository,
and they should: there is no container runtime, no package index, no database,
no release and no approval. A command that exited 0 for "nothing happened"
would let a pipeline treat an absent deployment as a successful one.

**Mutating subcommands print their exact target first.** Not "the database" -
the host, the port and the database name, with the credential removed. A
migration or a restore aimed at the wrong server is the kind of mistake that
is obvious in hindsight and invisible in a command line, and printing the
target is the cheapest possible guard against it.

**There is no subcommand that deletes a volume.** ``stop`` stops containers
and never passes ``-v``. Destroying a database volume is a decision a person
makes with a command they typed, not one a deployment tool offers as an
option - and a tool that offered it would eventually be run with it by
somebody who meant ``--verbose``.

**Nothing here creates a user, a release, an approval or an expert.** Those
are people's acts. `pgx-auth bootstrap-admin` is interactive and audited as a
bootstrap; this command has no path to it.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Mapping, Optional, Sequence

from pgx.deployment.vocabulary import (EXIT_BLOCKED, EXIT_FAILURE,
                                       EXIT_SUCCESS, EXIT_USAGE,
                                       DeploymentEnvironmentKind,
                                       ExecutionState, exit_code_for)

__all__ = ["main"]

_COMPOSE_PROJECT = "pgx_wp24_rehearsal"
_COMPOSE_FILE = "docker-compose.wp24.yml"


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def _emit(document: Mapping[str, Any], *, as_json: bool,
          lines: Sequence[str] = ()) -> None:
    if as_json:
        print(json.dumps(document, indent=2, sort_keys=True,
                         ensure_ascii=True))
        return
    for line in lines:
        print(line)
    for entry in document.get("blockers") or []:
        print("  %-42s %s" % (entry.get("code"), entry.get("owner")))
        print("    %s" % entry.get("detail"))


def _state_line(label: str, value: Any) -> str:
    shown = "null" if value is None else str(value)
    return "%-30s %s" % (label, shown)


def _redacted_target(url: Optional[str]) -> str:
    """The target, with the credential removed. Printed before every mutation.

    Uses WP-02's redactor rather than a second implementation: that one
    already handles userinfo, query parameters and libpq DSN forms, and a
    simpler one here would miss ``?sslpassword=`` exactly as the original did.
    """
    if not url:
        return "(none configured)"
    from pgx.infrastructure.db.config import redact_url

    return redact_url(url)


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def _cmd_preflight(args: argparse.Namespace) -> int:
    from pgx.deployment.environment import probe_environment
    from pgx.deployment.migration import chain_heads
    from pgx.deployment.packaging import verify_lockfile
    from pgx.deployment.runtime_assets import verify_runtime_assets
    from pgx.deployment.secrets import secret_configuration_report

    report = probe_environment()
    assets = verify_runtime_assets(args.root)
    lock = verify_lockfile(args.root)
    chain = chain_heads(args.root)
    document = {
        "environment": dict(report.to_json()),
        "runtime_assets": dict(assets),
        "lockfile": dict(lock),
        "migration_chain": dict(chain),
        "secret_configuration": dict(secret_configuration_report()),
        "blockers": list(lock.get("blockers") or []),
    }
    ready = bool(report.can_build_image and report.can_resolve_dependencies
                 and assets["satisfied"] and lock["lockfile_present"])
    document["state"] = (ExecutionState.VERIFIED.value if ready
                         else ExecutionState.BLOCKED.value)
    _emit(document, as_json=args.format == "json", lines=[
        _state_line("python", "%s (deployment pins %s)" % (
            report.python_version, "3.11")),
        _state_line("container runtime", report.container_runtime_available),
        _state_line("package index", report.package_index_reachable),
        _state_line("argon2 importable", report.modules.get("argon2")),
        _state_line("psycopg importable", report.modules.get("psycopg")),
        _state_line("build backend", report.can_build_distributions),
        _state_line("supply-chain tool", report.supply_chain_tool),
        _state_line("runtime assets satisfied", assets["satisfied"]),
        _state_line("lockfile present", lock["lockfile_present"]),
        _state_line("migration heads", chain["heads"]),
        "",
    ])
    return EXIT_SUCCESS if ready else EXIT_BLOCKED


def _cmd_lock(args: argparse.Namespace) -> int:
    from pgx.deployment.packaging import lock_dependencies, verify_lockfile

    result = (verify_lockfile(args.root) if args.check
              else lock_dependencies(args.root))
    _emit(dict(result), as_json=args.format == "json", lines=[
        _state_line("lockfile present", result["lockfile_present"]),
        _state_line("state", result["state"]), ""])
    return exit_code_for(ExecutionState(str(result["state"])))


def _cmd_build(args: argparse.Namespace) -> int:
    from pgx.deployment.artifacts import write_generated_artifact
    from pgx.deployment.image import build_image
    from pgx.deployment.packaging import build_distributions_twice
    from pgx.deployment.provenance import build_provenance

    distributions = build_distributions_twice(args.root)
    image = build_image(args.root, reference=args.reference)
    provenance = build_provenance(
        args.root,
        image_repository=args.reference.split(":")[0],
        image_tag=args.reference.split(":")[-1],
        image_digest=image.get("image_digest"),
        base_image_digest=image.get("base_image_digest"))
    document = {
        "distributions": dict(distributions),
        "image": dict(image),
        "provenance": dict(provenance),
        "blockers": list(distributions.get("blockers") or [])
        + list(image.get("blockers") or []),
    }
    path = write_generated_artifact(args.root, "wp24-build-result.json",
                                    document)
    states = [ExecutionState(str(distributions["state"])),
              ExecutionState(str(image["state"]))]
    worst = (ExecutionState.BLOCKED
             if any(item is ExecutionState.BLOCKED for item in states)
             else ExecutionState.EXECUTED)
    document["state"] = worst.value
    _emit(document, as_json=args.format == "json", lines=[
        _state_line("distribution build", distributions["state"]),
        _state_line("reproducible", distributions.get("reproducible")),
        _state_line("image build", image["state"]),
        _state_line("image digest", image.get("image_digest")),
        _state_line("source manifest",
                    provenance["source_tree_manifest_hash"][:26] + "..."),
        _state_line("source revision", provenance["source_revision"]),
        _state_line("written", path), ""])
    return exit_code_for(worst)


def _cmd_migrate(args: argparse.Namespace) -> int:
    from pgx.deployment.migration import migration_status, upgrade_to_head
    from pgx.deployment.secrets import read_secret

    try:
        material = read_secret("DATABASE_URL", required=not args.dry_run)
    except Exception as error:  # noqa: BLE001 - the message names no value
        print("configuration error: %s" % error, file=sys.stderr)
        return EXIT_USAGE
    url = material.value if material else None

    # The exact target, before anything runs. The credential is removed; the
    # host, port and database name are not, because they are what a wrong
    # target looks like.
    print("target: %s" % _redacted_target(url))
    print("action: alembic upgrade head")
    if args.dry_run or url is None:
        status = migration_status(args.root)
        _emit(dict(status), as_json=args.format == "json", lines=[
            _state_line("state", status["state"]),
            _state_line("chain head", status["chain"]["head"]),
            _state_line("executed", status["executed"]), ""])
        return exit_code_for(ExecutionState(str(status["state"])))
    result = upgrade_to_head(url, root=args.root)
    _emit(dict(result), as_json=args.format == "json", lines=[
        _state_line("state", result["state"]),
        _state_line("applied head", result.get("applied_head")), ""])
    return exit_code_for(ExecutionState(str(result["state"])))


def _cmd_staging_up(args: argparse.Namespace) -> int:
    import shutil
    import subprocess  # noqa: S404 - starting the topology is the point

    print("project: %s" % _COMPOSE_PROJECT)
    print("file:    %s" % _COMPOSE_FILE)
    print("action:  docker compose up -d (no volume is removed by any "
          "pgx-deploy subcommand)")
    if shutil.which("docker") is None:
        print("blocked: no container runtime", file=sys.stderr)
        return EXIT_BLOCKED
    argv = ["docker", "compose", "-p", _COMPOSE_PROJECT,
            "-f", os.path.join(args.root, _COMPOSE_FILE)]
    for profile in args.profile or []:
        argv += ["--profile", profile]
    argv += ["up", "-d"]
    completed = subprocess.run(argv, check=False)  # noqa: S603
    return EXIT_SUCCESS if completed.returncode == 0 else EXIT_FAILURE


def _cmd_stop(args: argparse.Namespace) -> int:
    import shutil
    import subprocess  # noqa: S404

    print("project: %s" % _COMPOSE_PROJECT)
    print("action:  docker compose stop")
    print("volumes: NOT removed. There is no pgx-deploy subcommand that "
          "deletes one.")
    if shutil.which("docker") is None:
        return EXIT_BLOCKED
    completed = subprocess.run(  # noqa: S603
        ["docker", "compose", "-p", _COMPOSE_PROJECT,
         "-f", os.path.join(args.root, _COMPOSE_FILE), "stop"], check=False)
    return EXIT_SUCCESS if completed.returncode == 0 else EXIT_FAILURE


def _cmd_smoke(args: argparse.Namespace) -> int:
    from pgx.deployment.artifacts import write_generated_artifact
    from pgx.deployment.smoke import smoke_check

    kind = DeploymentEnvironmentKind(args.environment)
    result = smoke_check(args.url, environment=kind, ca_bundle=args.ca_bundle)
    write_generated_artifact(args.root, "wp24-smoke-result.json",
                             dict(result))
    _emit(dict(result), as_json=args.format == "json", lines=[
        _state_line("state", result["state"]),
        _state_line("environment", result["environment_kind"]),
        _state_line("rehearsal label", result.get("rehearsal_label")),
        _state_line("liveness", (result.get("liveness") or {}).get("status")
                    if result.get("liveness") else None),
        _state_line("readiness", (result.get("readiness") or {}).get(
            "reported_status") if result.get("readiness") else None), ""])
    return exit_code_for(ExecutionState(str(result["state"])))


def _cmd_performance(args: argparse.Namespace) -> int:
    from pgx.deployment.artifacts import write_generated_artifact
    from pgx.deployment.performance import execute_run

    # No release resolver is wired here on purpose. A CLI that could reach
    # into a database to find "a release" would eventually find a development
    # fixture, and the measurement would carry its id into a report.
    result = execute_run(
        environment=DeploymentEnvironmentKind(args.environment))
    write_generated_artifact(args.root, "wp24-performance-result.json",
                             dict(result))
    _emit(dict(result), as_json=args.format == "json", lines=[
        _state_line("state", result["state"]),
        _state_line("attempts required", result["attempts_required"]),
        _state_line("attempted", result["attempted"]),
        _state_line("p50 ms", result["latency_p50_ms"]),
        _state_line("p95 ms", result["latency_p95_ms"]),
        _state_line("throughput rps", result["throughput_rps"]),
        _state_line("error rate", result["error_rate"]), ""])
    return exit_code_for(ExecutionState(str(result["state"])))


def _cmd_backup(args: argparse.Namespace) -> int:
    from pgx.deployment.backup_execution import backup_execution_status

    print("action: backup")
    print("target: %s" % (args.destination or "(none configured)"))
    result = backup_execution_status(destination=args.destination)
    _emit(dict(result), as_json=args.format == "json", lines=[
        _state_line("state", result["state"]),
        _state_line("operational status", result["operational_status"]),
        _state_line("destination kind", result["destination_kind"]), ""])
    return exit_code_for(ExecutionState(str(result["state"])))


def _cmd_restore_verify(args: argparse.Namespace) -> int:
    from pgx.deployment.backup_execution import (backup_execution_status,
                                                 evaluate_restore)

    print("action: restore verification")
    print("target: %s (must be a SEPARATE database from the source)"
          % _redacted_target(args.target_url))
    evaluation = evaluate_restore()
    result = backup_execution_status(restore=evaluation,
                                     local_rehearsal=args.local_rehearsal)
    _emit(dict(result), as_json=args.format == "json", lines=[
        _state_line("state", result["state"]),
        _state_line("conditions satisfied", "%s of %s"
                    % (evaluation["satisfied_count"],
                       evaluation["condition_count"])),
        _state_line("restore verified", result["restore_verified"]), ""])
    return exit_code_for(ExecutionState(str(result["state"])))


def _cmd_rollback(args: argparse.Namespace) -> int:
    from pgx.deployment.rollback import image_rollback_drill

    result = image_rollback_drill(
        environment=DeploymentEnvironmentKind(args.environment))
    _emit(dict(result), as_json=args.format == "json", lines=[
        _state_line("state", result["state"]),
        _state_line("previous image", result.get("previous_image")),
        _state_line("candidate image", result.get("candidate_image")), ""])
    return exit_code_for(ExecutionState(str(result["state"])))


def _cmd_release_validation(args: argparse.Namespace) -> int:
    from pgx.deployment.artifacts import (canonical_json,
                                          write_deployment_artifacts)
    from pgx.deployment.environment import probe_environment
    from pgx.deployment.gate_status import (build_gate_e_status,
                                            build_wp24_gate_status)
    from pgx.deployment.packaging import verify_lockfile
    from pgx.deployment.provenance import build_provenance
    from pgx.deployment.release_validation import build_release_validation

    environment = probe_environment()
    validation = build_release_validation(
        args.root, lockfile=verify_lockfile(args.root))
    gate = build_wp24_gate_status(args.root,
                                  environment=dict(environment.to_json()),
                                  release_validation=validation)
    gate_e = build_gate_e_status(args.root, wp24=gate)
    if args.write:
        write_deployment_artifacts(args.root, documents={
            "data/deployment/wp24-real-gate-status.json": gate,
            "data/deployment/wp24-release-validation.json": validation,
            "data/deployment/wp24-gate-e-status.json": gate_e,
            "data/deployment/wp24-build-provenance.json":
                build_provenance(args.root),
        })
    document = {"release_validation": dict(validation),
                "wp24_gate_status": dict(gate),
                "gate_e": dict(gate_e),
                "blockers": list(validation.get("blockers") or [])}
    _emit(document, as_json=args.format == "json", lines=[
        _state_line("WP-24 implementation", gate["implementation_status"]),
        _state_line("WP-24 deployment gate", gate["deployment_gate_status"]),
        _state_line("Gate E", gate_e["gate_e_status"]),
        _state_line("required gates satisfied", "%s of %s"
                    % (validation["satisfied_required_count"],
                       validation["required_gate_count"])),
        _state_line("release_may_proceed",
                    validation["release_may_proceed"]), ""])
    return (EXIT_SUCCESS if validation["release_may_proceed"]
            else EXIT_BLOCKED)


def _cmd_status(args: argparse.Namespace) -> int:
    return _cmd_release_validation(args)


def _cmd_artifacts(args: argparse.Namespace) -> int:
    from pgx.deployment.artifacts import write_deployment_artifacts

    for relative in write_deployment_artifacts(args.root):
        print("wrote %s" % relative)
    return EXIT_SUCCESS


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

class _Parser(argparse.ArgumentParser):
    """Exit 3 on a malformed request, not argparse's 2.

    Two is already taken, and it means something specific here: blocked, not
    executed or stale. A pipeline that saw 2 from an unknown subcommand would
    read a typo as "the deployment has not happened yet" and carry on.
    """

    def error(self, message: str):  # type: ignore[override]
        self.print_usage(sys.stderr)
        print("%s: error: %s" % (self.prog, message), file=sys.stderr)
        raise SystemExit(EXIT_USAGE)


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="pgx-deploy",
        description=(
            "WP-24 deployment operations. Exit 0 only for work that ran and "
            "held; 1 for a failure; 2 for blocked, not executed or stale; 3 "
            "for a malformed request. No subcommand deletes a volume, "
            "creates a user, activates a release or approves anything."))
    parser.add_argument("--root", default=".",
                        help="repository root (default: the current "
                             "directory)")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    subparsers = parser.add_subparsers(dest="command", required=True,
                                       parser_class=_Parser)

    subparsers.add_parser(
        "preflight",
        help="measure this host: runtime, index, modules, assets, chain"
    ).set_defaults(handler=_cmd_preflight)

    lock = subparsers.add_parser(
        "lock", help="generate uv.lock, or verify it with --check")
    lock.add_argument("--check", action="store_true",
                      help="frozen check: does uv.lock match pyproject.toml?")
    lock.set_defaults(handler=_cmd_lock)

    build = subparsers.add_parser(
        "build", help="build distributions twice and the application image")
    build.add_argument("--reference", default="pgx-platform:wp24-local",
                       help="local image reference; there is no registry "
                            "path anywhere in this project")
    build.set_defaults(handler=_cmd_build)

    migrate = subparsers.add_parser(
        "migrate", help="alembic upgrade head against the configured target")
    migrate.add_argument("--dry-run", action="store_true",
                         help="report the chain and the database revision "
                              "without applying anything")
    migrate.set_defaults(handler=_cmd_migrate)

    up = subparsers.add_parser(
        "staging-up", help="start the isolated rehearsal topology")
    up.add_argument("--profile", action="append",
                    help="compose profile (local, staging, ops, restore)")
    up.set_defaults(handler=_cmd_staging_up)

    subparsers.add_parser(
        "stop", help="stop the topology. Never removes a volume."
    ).set_defaults(handler=_cmd_stop)

    smoke = subparsers.add_parser(
        "smoke", help="probe a running deployment")
    smoke.add_argument("--url", help="base URL of the deployment")
    smoke.add_argument("--environment", default="LOCAL_REHEARSAL",
                       choices=[item.value for item
                                in DeploymentEnvironmentKind])
    smoke.add_argument("--ca-bundle",
                       help="CA to verify against. There is no option that "
                            "disables verification.")
    smoke.set_defaults(handler=_cmd_smoke)

    performance = subparsers.add_parser(
        "performance",
        help="the 1000-assessment run. Refuses without an eligible release.")
    performance.add_argument("--environment", default="LOCAL_REHEARSAL",
                             choices=[item.value for item
                                      in DeploymentEnvironmentKind])
    performance.set_defaults(handler=_cmd_performance)

    backup = subparsers.add_parser("backup", help="take a backup")
    backup.add_argument("--destination",
                        help="where the backup goes. A temporary directory "
                             "beside the source database is not one.")
    backup.set_defaults(handler=_cmd_backup)

    restore = subparsers.add_parser(
        "restore-verify",
        help="verify a restore against all four runbook conditions")
    restore.add_argument("--target-url",
                         help="the SEPARATE database to restore into")
    restore.add_argument("--local-rehearsal", action="store_true",
                         help="label the result LOCAL_REHEARSAL_VERIFIED "
                              "rather than an operational verification")
    restore.set_defaults(handler=_cmd_restore_verify)

    rollback = subparsers.add_parser(
        "rollback", help="the deployment rollback drill")
    rollback.add_argument("--environment", default="LOCAL_REHEARSAL",
                          choices=[item.value for item
                                   in DeploymentEnvironmentKind])
    rollback.set_defaults(handler=_cmd_rollback)

    validation = subparsers.add_parser(
        "release-validation",
        help="aggregate every gate. Exit 0 only when all are VERIFIED.")
    validation.add_argument("--write", action="store_true",
                            help="write the committed artifacts")
    validation.set_defaults(handler=_cmd_release_validation)

    status = subparsers.add_parser("status", help="alias for "
                                                  "release-validation")
    status.add_argument("--write", action="store_true")
    status.set_defaults(handler=_cmd_status)

    subparsers.add_parser(
        "artifacts", help="write the committed WP-24 artifacts"
    ).set_defaults(handler=_cmd_artifacts)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        return int(args.handler(args))
    except KeyboardInterrupt:  # pragma: no cover
        return EXIT_FAILURE
    except Exception as error:  # noqa: BLE001
        from pgx.deployment.errors import DeploymentError

        if isinstance(error, DeploymentError):
            print("%s: %s" % (type(error).__name__, error), file=sys.stderr)
            return int(error.exit_code)
        raise


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
