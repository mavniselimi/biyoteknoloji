# -*- coding: utf-8 -*-
"""``pgx-ingest-clinpgx``: exit codes, explicit paths, and secret safety (WP-04).

Socket-free. ``plan``, ``replay-cache``, ``validate-cache`` and ``inspect-run``
are run for real, end to end - argv in, stdout and stderr captured - because a
CLI's contract is what it actually prints and returns, not what its help text
promises.

``acquire`` is exercised only through the service with a scripted transport. The
CLI's own network path is asserted to exist and to be reachable from exactly one
subcommand; it is never invoked, because WP-04 made no live ClinPGx call.
"""

from __future__ import annotations

import ast
import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest

from pgx.application import ingestion_cli
from pgx.application.ingestion_cli import (
    EXIT_CACHE_UNAVAILABLE, EXIT_CONFIGURATION_FAILURE, EXIT_OK,
    EXIT_RUN_FAILED, EXIT_VALIDATION_FAILED, NETWORK_SUBCOMMANDS, build_parser,
    main,
)
from pgx.application.ingestion_service import IngestionService
from pgx.ingestion.clinpgx.catalog import catalog_ids
from pgx.ingestion.common.cache import ResponseCache
from pgx.ingestion.common.models import AcquisitionRunId
from pgx.ingestion.common.retry import RetryPolicy

from tests.unit.ingestion._fakes import (
    RecordingSleeper, ScriptedTransport, StepClock, data_page, fixed_random,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

SECRET = "cli-ingest-s3cret"

PARAMETERS = ["--symbol", "CYP2C19", "--name", "clopidogrel",
              "--gene-accession-id", "PA124",
              "--chemical-accession-id", "PA449053"]


def _run(argv, environment=None):
    """Run the CLI for real, returning ``(exit_code, stdout, stderr)``."""
    stdout, stderr = io.StringIO(), io.StringIO()
    previous = dict(os.environ)
    if environment:
        os.environ.update(environment)
    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(argv)
    finally:
        os.environ.clear()
        os.environ.update(previous)
    return code, stdout.getvalue(), stderr.getvalue()


def _cli_source() -> str:
    with io.open(os.path.join(REPO_ROOT, "pgx", "application",
                              "ingestion_cli.py"), encoding="utf-8") as handle:
        return handle.read()


class CliTestCase(unittest.TestCase):

    def setUp(self):
        self.directory = tempfile.mkdtemp(prefix="pgx-cli-test-")
        self.cache_dir = os.path.join(self.directory, "cache")
        self.run_dir = os.path.join(self.directory, "runs")

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)

    def _populate_cache(self, endpoints=("gene_lookup",)):
        """Run an acquisition through the service so the cache has content."""
        service = IngestionService(
            cache=ResponseCache(self.cache_dir),
            transport_factory=lambda: ScriptedTransport(
                [data_page([{"id": "PA124"}]), data_page([])] * len(endpoints)),
            retry_policy=RetryPolicy(max_attempts=2),
            clock=StepClock(step_seconds=0.0), sleeper=RecordingSleeper(),
            random_source=fixed_random(), new_run_id=AcquisitionRunId.new)
        return service.acquire(
            {"symbol": "CYP2C19", "name": "clopidogrel",
             "gene_accession_id": "PA124", "chemical_accession_id": "PA449053",
             "view": "base"}, list(endpoints))


class TestThePlanSubcommand(CliTestCase):

    def test_it_succeeds_and_reports_no_network_use(self):
        code, out, _ = _run(["plan", "--cache-dir", self.cache_dir,
                             "--endpoint", "gene_lookup"] + PARAMETERS)
        self.assertEqual(code, EXIT_OK)
        document = json.loads(out)
        self.assertIs(document["network_used"], False)

    def test_it_shows_the_exact_request_that_would_be_made(self):
        _, out, _ = _run(["plan", "--cache-dir", self.cache_dir,
                          "--endpoint", "gene_lookup"] + PARAMETERS)
        request = json.loads(out)["requests"][0]
        self.assertEqual(request["endpoint_id"], "gene_lookup")
        self.assertTrue(request["url"].startswith("https://api.clinpgx.org/"))
        self.assertIn(["symbol", "CYP2C19"], request["safe_query"])
        self.assertTrue(request["request_key"].startswith("sha256:"))

    def test_it_reports_whether_the_cache_already_holds_the_first_page(self):
        _, before, _ = _run(["plan", "--cache-dir", self.cache_dir,
                             "--endpoint", "gene_lookup"] + PARAMETERS)
        self.assertEqual(json.loads(before)["cached_first_pages"], 0)
        self._populate_cache()
        _, after, _ = _run(["plan", "--cache-dir", self.cache_dir,
                            "--endpoint", "gene_lookup"] + PARAMETERS)
        self.assertEqual(json.loads(after)["cached_first_pages"], 1)

    def test_it_plans_the_whole_catalog_when_no_endpoint_is_named(self):
        _, out, _ = _run(["plan", "--cache-dir", self.cache_dir]
                         + PARAMETERS + ["--first-id", "PA124",
                                         "--second-id", "PA449053",
                                         "--result-type", "guidelineAnnotation",
                                         "--object-id", "PA449053",
                                         "--object-type", "Chemical"])
        self.assertEqual(json.loads(out)["request_count"], len(catalog_ids()))

    def test_an_unknown_endpoint_id_is_a_configuration_failure(self):
        code, _, err = _run(["plan", "--cache-dir", self.cache_dir,
                             "--endpoint", "not_an_endpoint"] + PARAMETERS)
        self.assertEqual(code, EXIT_CONFIGURATION_FAILURE)
        self.assertEqual(json.loads(err)["error"], "CONFIGURATION_FAILURE")

    def test_the_failure_names_the_valid_endpoint_ids(self):
        _, _, err = _run(["plan", "--cache-dir", self.cache_dir,
                          "--endpoint", "not_an_endpoint"] + PARAMETERS)
        self.assertIn("gene_lookup", json.loads(err)["detail"])


class TestTheReplayAndValidateSubcommands(CliTestCase):

    def test_replay_succeeds_from_a_populated_cache(self):
        self._populate_cache()
        code, out, _ = _run(["replay-cache", "--cache-dir", self.cache_dir,
                             "--endpoint", "gene_lookup"] + PARAMETERS)
        self.assertEqual(code, EXIT_OK)
        document = json.loads(out)
        self.assertIs(document["network_used"], False)
        self.assertEqual(document["status"], "COMPLETE")

    def test_replay_reproduces_the_original_content_hash(self):
        original = self._populate_cache()
        _, out, _ = _run(["replay-cache", "--cache-dir", self.cache_dir,
                          "--endpoint", "gene_lookup"] + PARAMETERS)
        self.assertEqual(json.loads(out)["content_hash"], original.content_hash)

    def test_replay_without_a_cache_reports_cache_unavailable(self):
        code, _out, _ = _run(["replay-cache", "--cache-dir", self.cache_dir,
                              "--endpoint", "gene_lookup"] + PARAMETERS)
        self.assertEqual(code, EXIT_CACHE_UNAVAILABLE)

    def test_replay_writes_a_manifest_when_a_run_dir_is_given(self):
        self._populate_cache()
        _run(["replay-cache", "--cache-dir", self.cache_dir,
              "--run-dir", self.run_dir, "--endpoint", "gene_lookup"]
             + PARAMETERS)
        written = os.listdir(self.run_dir)
        self.assertEqual(len(written), 1)
        self.assertTrue(written[0].startswith("acquisition-manifest-"))

    def test_validate_cache_reports_a_healthy_cache(self):
        self._populate_cache()
        code, out, _ = _run(["validate-cache", "--cache-dir", self.cache_dir])
        self.assertEqual(code, EXIT_OK)
        self.assertTrue(json.loads(out)["healthy"])

    def test_validate_cache_fails_on_a_corrupt_blob(self):
        manifest = self._populate_cache()
        cache = ResponseCache(self.cache_dir)
        digest = manifest.endpoints[0].records[0].raw_sha256
        with io.open(cache.blob_path(digest), "wb") as handle:
            handle.write(b"tampered")
        code, out, _ = _run(["validate-cache", "--cache-dir", self.cache_dir])
        self.assertEqual(code, EXIT_VALIDATION_FAILED)
        self.assertFalse(json.loads(out)["healthy"])

    def test_inspect_run_summarises_a_written_manifest(self):
        self._populate_cache()
        _run(["replay-cache", "--cache-dir", self.cache_dir,
              "--run-dir", self.run_dir, "--endpoint", "gene_lookup"]
             + PARAMETERS)
        path = os.path.join(self.run_dir, os.listdir(self.run_dir)[0])
        code, out, _ = _run(["inspect-run", "--manifest", path])
        self.assertEqual(code, EXIT_OK)
        document = json.loads(out)
        self.assertEqual(document["status"], "COMPLETE")
        self.assertIsNone(document["full"])

    def test_inspect_run_can_print_the_whole_manifest(self):
        self._populate_cache()
        _run(["replay-cache", "--cache-dir", self.cache_dir,
              "--run-dir", self.run_dir, "--endpoint", "gene_lookup"]
             + PARAMETERS)
        path = os.path.join(self.run_dir, os.listdir(self.run_dir)[0])
        _, out, _ = _run(["inspect-run", "--manifest", path, "--full"])
        self.assertIsNotNone(json.loads(out)["full"])

    def test_inspect_run_of_a_missing_file_is_a_configuration_failure(self):
        code, _, err = _run(["inspect-run", "--manifest",
                             os.path.join(self.directory, "nope.json")])
        self.assertEqual(code, EXIT_CONFIGURATION_FAILURE)
        self.assertIn("error", json.loads(err))


class TestExitCodes(unittest.TestCase):

    def test_every_code_is_distinct(self):
        codes = [EXIT_OK, EXIT_RUN_FAILED, EXIT_CONFIGURATION_FAILURE,
                 EXIT_CACHE_UNAVAILABLE, EXIT_VALIDATION_FAILED]
        self.assertEqual(len(set(codes)), len(codes))

    def test_only_success_is_zero(self):
        self.assertEqual(EXIT_OK, 0)
        for code in (EXIT_RUN_FAILED, EXIT_CONFIGURATION_FAILURE,
                     EXIT_CACHE_UNAVAILABLE, EXIT_VALIDATION_FAILED):
            self.assertNotEqual(code, 0)

    def test_a_failed_run_and_a_config_failure_are_distinguishable(self):
        """A scheduler must be able to tell 'retry' from 'fix the command'."""
        self.assertNotEqual(EXIT_RUN_FAILED, EXIT_CONFIGURATION_FAILURE)


class TestExplicitPathsAndSafeArguments(unittest.TestCase):

    def setUp(self):
        self.parser = build_parser()

    @contextlib.contextmanager
    def _quiet(self):
        with contextlib.redirect_stderr(io.StringIO()):
            yield

    def test_a_cache_directory_is_always_required(self):
        for command in ("plan", "acquire", "replay-cache", "validate-cache"):
            with self.subTest(command=command):
                with self._quiet(), self.assertRaises(SystemExit):
                    self.parser.parse_args([command])

    def test_there_is_no_default_output_directory(self):
        """Importing the legacy probe decided where data went."""
        self.assertNotIn("clinpgx_outputs", _cli_source())
        self.assertNotIn('default="."', _cli_source())

    def test_a_subcommand_is_required(self):
        with self._quiet(), self.assertRaises(SystemExit):
            self.parser.parse_args([])

    def test_endpoints_are_selected_by_catalog_id_only(self):
        arguments = self.parser.parse_args(
            ["plan", "--cache-dir", "/tmp/x", "--endpoint", "gene_lookup"])
        self.assertEqual(arguments.endpoints, ["gene_lookup"])
        source = _cli_source()
        self.assertNotIn('"--path"', source)
        self.assertNotIn('"--url"', source)
        self.assertNotIn('"--base-url"', source)

    def test_the_endpoint_option_lists_the_valid_ids(self):
        rendered = self.parser.format_help()
        self.assertIn("plan", rendered)

    def test_the_acquire_subcommand_declares_that_it_uses_the_network(self):
        source = _cli_source()
        self.assertIn("MAKES NETWORK REQUESTS", source)
        self.assertEqual(NETWORK_SUBCOMMANDS, ("acquire",))


class TestOnlyAcquireCanReachTheNetwork(unittest.TestCase):

    def test_the_transport_is_built_in_exactly_one_place(self):
        tree = ast.parse(_cli_source())
        builders = [node for node in ast.walk(tree)
                    if isinstance(node, ast.Call)
                    and getattr(node.func, "id", None)
                    == "build_clinpgx_transport"]
        self.assertEqual(len(builders), 1)

    def test_every_non_network_subcommand_passes_network_false(self):
        tree = ast.parse(_cli_source())
        calls = [node for node in ast.walk(tree)
                 if isinstance(node, ast.Call)
                 and getattr(node.func, "id", None) == "_build_service"]
        self.assertTrue(calls)
        network_true = [call for call in calls
                        for keyword in call.keywords
                        if keyword.arg == "network"
                        and getattr(keyword.value, "value", None) is True]
        self.assertEqual(len(network_true), 1,
                         "exactly one subcommand may request a transport")

    def test_the_cli_imports_no_network_module_at_module_level(self):
        tree = ast.parse(_cli_source())
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = getattr(node, "module", "") or ""
                names = {alias.name for alias in node.names}
                self.assertNotIn("urllib", module)
                self.assertNotIn("urllib", names)
                self.assertNotIn("socket", names)

    def test_the_cli_needs_no_database(self):
        source = _cli_source()
        for token in ("sqlalchemy", "DATABASE_URL", "SqlAlchemyUnitOfWork",
                      "create_session_factory"):
            self.assertNotIn(token, source)


class TestNoCredentialReachesTheOutput(CliTestCase):

    def test_a_token_in_the_environment_never_appears_in_plan_output(self):
        code, out, err = _run(
            ["plan", "--cache-dir", self.cache_dir,
             "--endpoint", "gene_lookup"] + PARAMETERS,
            environment={"CLINPGX_API_TOKEN": SECRET})
        self.assertEqual(code, EXIT_OK)
        self.assertNotIn(SECRET, out + err)

    def test_a_token_never_reaches_the_request_key(self):
        _, with_token, _ = _run(
            ["plan", "--cache-dir", self.cache_dir,
             "--endpoint", "gene_lookup"] + PARAMETERS,
            environment={"CLINPGX_API_TOKEN": SECRET})
        _, without_token, _ = _run(
            ["plan", "--cache-dir", self.cache_dir,
             "--endpoint", "gene_lookup"] + PARAMETERS)
        self.assertEqual(json.loads(with_token)["requests"][0]["request_key"],
                         json.loads(without_token)["requests"][0]["request_key"])

    def test_a_token_never_reaches_a_written_manifest(self):
        self._populate_cache()
        _run(["replay-cache", "--cache-dir", self.cache_dir,
              "--run-dir", self.run_dir, "--endpoint", "gene_lookup"]
             + PARAMETERS, environment={"CLINPGX_API_TOKEN": SECRET})
        path = os.path.join(self.run_dir, os.listdir(self.run_dir)[0])
        with io.open(path, encoding="utf-8") as handle:
            self.assertNotIn(SECRET, handle.read())

    def test_a_token_never_reaches_the_cache(self):
        self._populate_cache()
        for root, _dirs, files in os.walk(self.cache_dir):
            for name in files:
                with io.open(os.path.join(root, name), "rb") as handle:
                    self.assertNotIn(SECRET.encode(), handle.read())

    def test_failure_output_goes_through_the_redactor(self):
        source = _cli_source()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and getattr(node.func, "id", None) == "_fail"):
                rendered = ast.unparse(node)
                if "UNKNOWN_COMMAND" in rendered:
                    continue
                self.assertIn("_redact", rendered,
                              "unredacted failure output: %s" % rendered[:80])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
