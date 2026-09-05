# -*- coding: utf-8 -*-
"""The image, the compose topology and the build (WP-24).

These run on a host with no container runtime, which is the point: a
Dockerfile whose only test is "it builds on the machine that has Docker" is
untested everywhere else, and the properties that matter here - a non-root
user, no compiler in the runtime stage, no `COPY data/`, no secret - are
readable from the file.

The runtime behaviour that genuinely needs a daemon is exercised through an
injected runner, so the container code paths are executed rather than skipped.
"""

from __future__ import annotations

import io
import os
import unittest

from pgx.deployment.image import (DEFAULT_IMAGE_REFERENCE, build_image,
                                  compare_images)
from pgx.deployment.packaging import (SOURCE_DATE_EPOCH, STAGED_FOR_BUILD,
                                      build_distributions_twice,
                                      verify_lockfile)
from pgx.deployment.provenance import (build_provenance, compare_provenance,
                                       source_revision, source_tree_manifest)
from pgx.deployment.runtime_assets import (FORBIDDEN_IMAGE_PREFIXES,
                                           RUNTIME_ASSETS,
                                           build_runtime_asset_manifest,
                                           forbidden_paths_in,
                                           verify_runtime_assets)
from pgx.deployment.vocabulary import ExecutionState
from tests.fixtures.wp24.doubles import fake_runner

REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def _read(relative):
    with io.open(os.path.join(REPO_ROOT, relative), encoding="utf-8") as fh:
        return fh.read()


class TestTheDockerfile(unittest.TestCase):
    """Read, not built. The properties that matter are in the text."""

    def setUp(self):
        self.text = _read("Dockerfile")
        self.stages = self.text.split("FROM ")

    def test_the_runtime_stage_runs_as_a_non_root_user(self):
        self.assertIn("USER 10001:10001", self.text)

    def test_the_runtime_stage_contains_no_compiler(self):
        """A compiler in a runtime image is a tool an attacker who gets a
        shell no longer has to bring."""
        runtime = self.text.split("AS runtime", 1)[1]
        for tool in ("build-essential", "gcc", "libpq-dev", "make"):
            with self.subTest(tool=tool):
                self.assertNotIn(tool, runtime)

    def test_the_builder_stage_has_the_compiler_the_runtime_does_not(self):
        builder = self.text.split("AS builder", 1)[1].split("AS runtime")[0]
        self.assertIn("build-essential", builder)

    def test_the_base_image_is_the_supported_python_series(self):
        from pgx.deployment.environment import DEPLOYMENT_PYTHON_SERIES

        self.assertIn("FROM python:%s" % DEPLOYMENT_PYTHON_SERIES, self.text)

    def test_no_data_directory_is_copied_wholesale(self):
        """`COPY data/` ships the raw snapshot, the legacy baseline and
        anything a later work package puts there - including a restricted
        holdout payload."""
        for line in self.text.splitlines():
            stripped = line.strip()
            if not stripped.upper().startswith("COPY"):
                continue
            with self.subTest(line=stripped):
                self.assertNotRegex(stripped, r"COPY\s+data\s+")
                self.assertNotRegex(stripped, r"COPY\s+--[^ ]+\s+data\s+")

    def test_every_copied_data_directory_holds_a_declared_runtime_asset(self):
        """The image's COPY lines and the allowlist must agree.

        A directory copied in that holds no declared asset is one nobody can
        justify; a declared asset in a directory nobody copies is an image
        that will report the artifact unavailable at run time.
        """
        copied = set()
        for line in self.text.splitlines():
            stripped = line.strip()
            if "/app/data/" not in stripped:
                continue
            source = stripped.split()[-2]
            copied.add(source)
        declared = {os.path.dirname(asset.path) for asset in RUNTIME_ASSETS
                    if asset.path.startswith("data/")}
        self.assertTrue(declared <= copied,
                        "declared but not copied: %s" % (declared - copied))

    def test_no_migration_runs_at_start_up(self):
        """An application that upgraded its own schema would apply 0011 from
        whichever replica booted first, concurrently, against a database
        whose downgrade refuses to run."""
        for line in self.text.splitlines():
            stripped = line.strip()
            if stripped.startswith(("CMD", "ENTRYPOINT")):
                with self.subTest(line=stripped):
                    self.assertNotIn("alembic", stripped)
                    self.assertNotIn("upgrade", stripped)

    def test_the_healthcheck_is_liveness_only(self):
        """Readiness in a HEALTHCHECK restarts a container because its
        database was briefly unreachable."""
        healthcheck = [line for line in self.text.splitlines()
                       if "health" in line.lower()
                       and "CMD" in line]
        self.assertTrue(healthcheck)
        joined = " ".join(healthcheck)
        self.assertIn("/health/live", joined)
        self.assertNotIn("/health/ready", joined)

    def test_argon2_importability_is_checked_at_build_time(self):
        """The WP-23 handoff: a build that cannot hash a password must fail
        rather than fall back."""
        self.assertIn("import argon2", self.text)

    def test_the_lockfile_is_installed_frozen(self):
        """`uv sync --frozen` refuses when uv.lock disagrees with
        pyproject.toml. A build that silently re-resolved would produce an
        image the lockfile does not describe."""
        self.assertIn("uv sync --frozen", self.text)

    def test_no_secret_or_credential_appears(self):
        lowered = self.text.lower()
        for token in ("password=", "secret=", "token=", "api_key",
                      "-----begin"):
            with self.subTest(token=token):
                self.assertNotIn(token, lowered)


class TestTheDockerignore(unittest.TestCase):
    """An ignore file states intent; the post-build audit measures result."""

    def setUp(self):
        self.entries = {line.strip() for line in _read(".dockerignore")
                        .splitlines()
                        if line.strip() and not line.startswith("#")}

    def test_secrets_and_keys_are_excluded(self):
        for entry in (".env", "*.pem", "*.key", "deploy/secrets/",
                      "deploy/tls/"):
            with self.subTest(entry=entry):
                self.assertIn(entry, self.entries)

    def test_restricted_and_baseline_data_is_excluded(self):
        for entry in ("data/raw/", "data/holdout/", "data/legacy-baseline/",
                      "data/_to_delete/", "_to_delete/"):
            with self.subTest(entry=entry):
                self.assertIn(entry, self.entries)

    def test_every_frozen_legacy_script_is_excluded(self):
        """architecture.md section 15 step 10: legacy entry points are
        evidence, never application startup code."""
        for entry in ("risk_engine.py", "gemini_report_generator.py",
                      "alternative_ranker.py", "candidate_onboarding.py",
                      "clean_mvp_seed_dataset.py", "clinpgx_probe.py",
                      "clinpgx_probe_v2.py"):
            with self.subTest(entry=entry):
                self.assertIn(entry, self.entries)

    def test_the_test_suite_is_excluded(self):
        """Not because it is secret - because it carries the WP-20 unsafe
        controls, which are deliberately dangerous code that exists to be
        detected."""
        self.assertIn("tests/", self.entries)


class TestTheComposeTopology(unittest.TestCase):
    def setUp(self):
        self.text = _read("docker-compose.wp24.yml")

    def test_the_project_name_is_isolated_and_explicit(self):
        """Compose derives a project name from the directory when none is
        given, which would make this topology share a namespace with the
        development one."""
        self.assertIn("name: pgx_wp24_rehearsal", self.text)

    def test_the_required_services_exist(self):
        for service in ("app:", "postgres:", "postgres-restore-target:",
                        "proxy:", "ops:"):
            with self.subTest(service=service):
                self.assertIn("  %s" % service, self.text)

    def test_the_restore_target_is_a_separate_server_on_its_own_volume(self):
        self.assertIn("pgx_wp24_restore_data", self.text)
        self.assertIn("pgx_wp24_data", self.text)

    def test_the_app_port_is_not_published_in_the_staging_service(self):
        """A published app port is a plaintext path around the terminator."""
        app_block = self.text.split("  app:", 1)[1].split("  app-local:")[0]
        self.assertIn("expose:", app_block)
        self.assertNotIn("ports:", app_block)

    def test_resource_limits_are_bounded(self):
        """An unconstrained container makes a latency number that describes
        the host rather than the software."""
        for token in ("cpus:", "memory:", "pids_limit:"):
            with self.subTest(token=token):
                self.assertIn(token, self.text)

    def test_the_container_drops_capabilities_and_is_read_only(self):
        for token in ("cap_drop:", "no-new-privileges:true", "read_only: true"):
            with self.subTest(token=token):
                self.assertIn(token, self.text)

    def test_nothing_runs_an_operation_on_start_up(self):
        for forbidden in ("alembic upgrade", "pgx-db-seed",
                          "bootstrap-admin", "pgx-ingest", "release activate"):
            with self.subTest(command=forbidden):
                self.assertNotIn(forbidden, self.text)

    def test_secrets_are_files_not_environment_variables(self):
        """An environment variable is visible in `docker inspect`, in a crash
        dump and in the process table."""
        self.assertIn("DATABASE_URL_FILE:", self.text)
        self.assertIn("POSTGRES_PASSWORD_FILE:", self.text)
        self.assertIn("secrets:", self.text)

    def test_no_credential_value_is_committed(self):
        for line in self.text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            with self.subTest(line=stripped):
                self.assertNotIn("POSTGRES_PASSWORD:", stripped)

    def test_the_development_compose_file_is_untouched_by_wp24(self):
        """WP-02's file keeps its semantics: `postgres-test` uses tmpfs and a
        separate port, which is what stops `alembic downgrade base` from
        reaching a developer's data."""
        development = _read("docker-compose.yml")
        self.assertIn("postgres-test:", development)
        self.assertIn("tmpfs:", development)
        self.assertNotIn("pgx_wp24", development)

    def test_the_proxy_terminates_tls_without_weakening_the_cookie(self):
        caddyfile = _read("deploy/proxy/Caddyfile")
        self.assertIn("tls1.2", caddyfile)
        self.assertIn("X-Forwarded-Proto", caddyfile)
        # Comments stripped before the scan. The file *explains* that there
        # is no `tls internal` here, and the first version of this assertion
        # matched that explanation - the same mistake this repository has now
        # made in a scanner, a docstring and a config file.
        directives = "\n".join(
            line for line in caddyfile.splitlines()
            if not line.strip().startswith("#"))
        self.assertNotIn("tls internal", directives)
        self.assertIn("auto_https off", directives)


class TestRuntimeAssets(unittest.TestCase):
    def test_every_asset_carries_a_reason(self):
        for asset in RUNTIME_ASSETS:
            with self.subTest(path=asset.path):
                self.assertGreaterEqual(len(asset.reason), 10)

    def test_the_manifest_is_satisfied_in_this_repository(self):
        result = verify_runtime_assets(REPO_ROOT)
        self.assertEqual(result["missing_required"], [])
        self.assertTrue(result["satisfied"])

    def test_a_changed_asset_is_reported_as_a_mismatch(self):
        manifest = build_runtime_asset_manifest(REPO_ROOT)
        pinned = {entry["path"]: entry["sha256"]
                  for entry in manifest["assets"] if entry["sha256"]}
        first = sorted(pinned)[0]
        pinned[first] = "sha256:" + "0" * 64
        result = verify_runtime_assets(REPO_ROOT, expected=pinned)
        self.assertIn(first, result["checksum_mismatches"])
        self.assertFalse(result["satisfied"])

    def test_the_manifest_hash_ignores_what_one_host_observed(self):
        """Two builds of the same source produce the same manifest hash even
        when one is missing a file - and the missing file is reported
        separately, where it cannot be mistaken for a different manifest."""
        first = build_runtime_asset_manifest(REPO_ROOT)
        second = build_runtime_asset_manifest(REPO_ROOT)
        self.assertEqual(first["manifest_hash"], second["manifest_hash"])

    def test_forbidden_paths_are_detected_in_a_listing(self):
        offenders = forbidden_paths_in([
            "pgx/domain/enums.py",
            "data/holdout/case-001.json",
            "tests/unit/test_x.py",
            ".env",
            "deploy/tls/server.key",
            "data/demo/wp17-development-cases.json",
        ])
        self.assertIn("data/holdout/case-001.json", offenders)
        self.assertIn("tests/unit/test_x.py", offenders)
        self.assertIn(".env", offenders)
        self.assertIn("deploy/tls/server.key", offenders)
        self.assertNotIn("pgx/domain/enums.py", offenders)
        self.assertNotIn("data/demo/wp17-development-cases.json", offenders)

    def test_holdout_is_forbidden_even_though_it_does_not_exist(self):
        """It does not exist yet. The prefix is here so that the day it does,
        an image cannot quietly acquire it."""
        self.assertIn("data/holdout/", FORBIDDEN_IMAGE_PREFIXES)


class TestBuildProvenance(unittest.TestCase):
    def test_the_source_revision_is_null_rather_than_a_placeholder(self):
        """Null so a consumer comparing two builds cannot match them on the
        word 'unknown'."""
        document = build_provenance(REPO_ROOT)
        revision = document["source_revision"]
        self.assertTrue(revision is None or
                        (isinstance(revision, str) and len(revision) == 40))
        if revision is None:
            self.assertIsNone(source_revision(REPO_ROOT))

    def test_the_source_manifest_is_deterministic(self):
        first = source_tree_manifest(REPO_ROOT)
        second = source_tree_manifest(REPO_ROOT)
        self.assertEqual(first["manifest_hash"], second["manifest_hash"])
        self.assertGreater(int(first["file_count"]), 100)

    def test_tests_are_included_in_the_source_identity(self):
        """A provenance that ignored tests would report the same identity for
        a tree whose verification had been deleted."""
        from pgx.deployment.provenance import SOURCE_EXCLUDED_PREFIXES

        self.assertNotIn("tests/", SOURCE_EXCLUDED_PREFIXES)

    def test_unhappened_things_are_null(self):
        document = build_provenance(REPO_ROOT)
        for field in ("image_digest", "built_at", "wheel_sha256",
                      "sdist_sha256", "sbom_sha256"):
            with self.subTest(field=field):
                self.assertIsNone(document[field])

    def test_comparison_excludes_timestamps_and_runner_identity(self):
        """Two reproducible builds differ in those and are the same build."""
        first = build_provenance(REPO_ROOT, built_at="2026-01-01T00:00:00Z",
                                 ci_run_id="1")
        second = build_provenance(REPO_ROOT, built_at="2026-02-02T00:00:00Z",
                                  ci_run_id="2")
        result = compare_provenance(first, second)
        self.assertTrue(result["identical"])
        self.assertIn("built_at", result["excluded_fields"])


class TestPackagingWithoutABackend(unittest.TestCase):
    """The blocked path is a real path and is exercised here."""

    def test_a_missing_build_backend_blocks_rather_than_substituting(self):
        """Substituting setuptools would build a different artifact than any
        deployment installs."""
        import importlib.util

        result = build_distributions_twice(REPO_ROOT)
        if importlib.util.find_spec("hatchling") is not None:
            self.skipTest("hatchling is importable here, so the "
                          "unavailable-backend path cannot be exercised")
        self.assertEqual(result["state"], ExecutionState.BLOCKED.value)
        self.assertIsNone(result["reproducible"])
        self.assertEqual(result["blockers"][0]["code"],
                         "DEPLOY_BUILD_BACKEND_UNAVAILABLE")

    def test_both_builds_share_one_source_date_epoch(self):
        """Two builds a second apart otherwise differ in archive mtimes while
        being identical in content, which would report irreproducibility that
        is not there."""
        self.assertEqual(SOURCE_DATE_EPOCH, "1735689600")

    def test_the_staging_set_excludes_everything_that_is_not_source(self):
        for name in ("tests", "data", ".venv", "docs", "_to_delete"):
            with self.subTest(name=name):
                self.assertNotIn(name, STAGED_FOR_BUILD)

    def test_an_absent_lockfile_is_blocked_not_fabricated(self):
        result = verify_lockfile(REPO_ROOT)
        if result["lockfile_present"]:
            self.skipTest("a lockfile exists in this checkout")
        self.assertEqual(result["state"], ExecutionState.BLOCKED.value)
        self.assertIsNone(result["lockfile_sha256"])


class TestImageBuildWithoutARuntime(unittest.TestCase):
    def test_a_cli_without_a_daemon_is_not_a_runtime(self):
        """`docker --version` answers happily with no daemon running, which
        is the false positive the liveness probe removes."""
        result = build_image(REPO_ROOT, runner=fake_runner({
            "docker --version": (0, "Docker version 27.0.0"),
            "docker info": (1, "Cannot connect to the Docker daemon"),
        }))
        self.assertEqual(result["state"], ExecutionState.BLOCKED.value)
        self.assertEqual(result["blockers"][0]["code"],
                         "DEPLOY_CONTAINER_RUNTIME_UNAVAILABLE")

    def test_the_default_reference_names_no_registry(self):
        """A registry reference in source is how a `pull` finds somebody
        else's image under a name that looks like yours."""
        self.assertNotIn("/", DEFAULT_IMAGE_REFERENCE.split(":")[0])

    def test_image_comparison_does_not_call_a_digest_difference_a_failure(
            self):
        """An image digest covers attestations and builder metadata, which
        move without a byte of the filesystem changing."""
        left = {"layer_diff_ids": ["sha256:a"], "user": "10001:10001",
                "image_digest": "sha256:one"}
        right = {"layer_diff_ids": ["sha256:a"], "user": "10001:10001",
                 "image_digest": "sha256:two"}
        result = compare_images(left, right)
        self.assertTrue(result["content_identical"])
        self.assertFalse(result["image_digests_agree"])

    def test_differing_layers_are_reported_as_different_content(self):
        result = compare_images({"layer_diff_ids": ["sha256:a"]},
                                {"layer_diff_ids": ["sha256:b"]})
        self.assertFalse(result["content_identical"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
