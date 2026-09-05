# -*- coding: utf-8 -*-
"""The ClinPGx catalog: what was ported, and what was deliberately not (WP-04).

Half of these tests assert an **absence**. That is the point: the legacy probes
worked, and the ways they were wrong are subtle enough to be reintroduced by a
well-meaning refactor. Each one is pinned here with the reason attached.

Three probe behaviours are asserted absent:

* ``get_first()`` - the first item of a result list treated as *the* answer.
  An unreviewed identity decision that belongs to WP-07.
* ``flatten_items()`` - six container keys tried in turn, then the whole
  payload wrapped in a list. An unexpected response became "one record".
* fixed sleeps, a module-level output directory, and ``quiet_404``.

Socket-free; nothing here makes a request.
"""

from __future__ import annotations

import ast
import inspect
import io
import os
import unittest

from pgx.ingestion.clinpgx import adapter, catalog, client, parsers
from pgx.ingestion.clinpgx.catalog import (
    CLINPGX_ALLOWED_HOSTS, CLINPGX_BASE_URL, CLINPGX_SOURCE_ID,
    catalog_ids, clinpgx_catalog, get_endpoint,
)
from pgx.ingestion.common.errors import ConfigurationError
from pgx.ingestion.common.pagination import PaginationStrategy

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

#: Endpoints the legacy probes actually called, with the query keys they used.
#: This is the inventory the port is checked against.
LEGACY_ENDPOINT_INTENT = {
    "/data/gene": ("symbol", "view"),
    "/data/chemical": ("name", "view"),
    "/data/guidelineAnnotation": ("relatedGenes.accessionId",
                                  "relatedChemicals.accessionId", "view"),
    "/data/variantAnnotation": ("location.genes.symbol", "view"),
    "/report/pair/{first}/{second}/{type}": ("view",),
    "/report/connectedObjects/{id}/{type}": (),
}

PARAMETERS = {
    "symbol": "CYP2C19", "name": "clopidogrel",
    "gene_accession_id": "PA124", "chemical_accession_id": "PA449053",
    "first_id": "PA124", "second_id": "PA449053",
    "result_type": "guidelineAnnotation",
    "object_id": "PA449053", "object_type": "Chemical", "view": "base",
}


def _source(module) -> str:
    """The module's full text, docstrings included."""
    return inspect.getsource(module)


def _identifiers(module) -> set:
    """Every name, attribute and function this module actually uses.

    The "defect was not ported" tests read this rather than the module text,
    for two reasons. Prose that *explains* why ``get_first`` was left behind
    must not register as ``get_first``. And, more importantly, a text scan
    would let a real reintroduction hide inside a string literal while the
    test passed - so the check is on the code's structure, where the behaviour
    actually lives.
    """
    tree = ast.parse(inspect.getsource(module))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
            if isinstance(node.value, ast.Name):
                names.add("%s.%s" % (node.value.id, node.attr))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, ast.keyword) and node.arg:
            names.add(node.arg)
    return names


def _code_of(module) -> str:
    """The module's code with docstrings stripped, for structural checks."""
    tree = ast.parse(inspect.getsource(module))
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)) or not body:
            continue
        first = body[0]
        if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            node.body = body[1:] or [ast.Pass()]
    return ast.unparse(tree)


class TestTheCatalogIsWellFormed(unittest.TestCase):

    def test_every_endpoint_id_is_unique(self):
        ids = [item.endpoint_id for item in clinpgx_catalog()]
        self.assertEqual(len(set(ids)), len(ids))

    def test_catalog_ids_are_sorted_and_complete(self):
        self.assertEqual(catalog_ids(),
                         tuple(sorted(item.endpoint_id
                                      for item in clinpgx_catalog())))

    def test_every_endpoint_declares_required_or_optional(self):
        for endpoint in clinpgx_catalog():
            with self.subTest(endpoint=endpoint.endpoint_id):
                self.assertIsInstance(endpoint.required, bool)

    def test_at_least_one_endpoint_is_required(self):
        self.assertTrue(any(item.required for item in clinpgx_catalog()))

    def test_at_least_one_endpoint_is_optional(self):
        self.assertTrue(any(not item.required for item in clinpgx_catalog()))

    def test_every_endpoint_declares_a_shape_and_a_records_path(self):
        for endpoint in clinpgx_catalog():
            with self.subTest(endpoint=endpoint.endpoint_id):
                self.assertIsNotNone(endpoint.shape)
                self.assertTrue(endpoint.records_path
                                or endpoint.shape.value == "BARE_LIST")

    def test_every_endpoint_declares_a_pagination_strategy(self):
        for endpoint in clinpgx_catalog():
            with self.subTest(endpoint=endpoint.endpoint_id):
                self.assertIsInstance(endpoint.pagination.strategy,
                                      PaginationStrategy)

    def test_every_endpoint_documents_its_purpose_and_its_limits(self):
        """A record's meaning is not obvious from its endpoint."""
        for endpoint in clinpgx_catalog():
            with self.subTest(endpoint=endpoint.endpoint_id):
                self.assertGreater(len(endpoint.purpose), 20)
                self.assertGreater(len(endpoint.limitations), 20)

    def test_every_endpoint_records_where_it_came_from(self):
        for endpoint in clinpgx_catalog():
            with self.subTest(endpoint=endpoint.endpoint_id):
                self.assertTrue(endpoint.legacy_origin.startswith(
                    "clinpgx_probe"), endpoint.legacy_origin)

    def test_every_path_starts_at_the_root(self):
        for endpoint in clinpgx_catalog():
            with self.subTest(endpoint=endpoint.endpoint_id):
                self.assertTrue(endpoint.path_template.startswith("/"))

    def test_an_unknown_endpoint_id_is_refused_with_the_valid_choices(self):
        with self.assertRaises(ConfigurationError) as caught:
            get_endpoint("no_such_endpoint")
        self.assertIn("gene_lookup", str(caught.exception))


class TestLegacyRequestIntentWasPorted(unittest.TestCase):
    """Every endpoint the probes called has a catalog entry."""

    def test_the_base_url_matches_the_legacy_probe(self):
        self.assertEqual(CLINPGX_BASE_URL, "https://api.clinpgx.org/v1")

    def test_the_host_allowlist_is_exactly_the_legacy_host(self):
        self.assertEqual(CLINPGX_ALLOWED_HOSTS, ("api.clinpgx.org",))

    def test_the_gene_endpoint_is_ported_with_its_query_keys(self):
        query = dict(get_endpoint("gene_lookup").query_for(PARAMETERS))
        self.assertEqual(query["symbol"], "CYP2C19")
        self.assertEqual(query["view"], "base")

    def test_the_chemical_endpoint_is_ported_with_its_query_keys(self):
        query = dict(get_endpoint("chemical_lookup").query_for(PARAMETERS))
        self.assertEqual(query["name"], "clopidogrel")

    def test_the_guideline_pair_query_uses_the_accession_id_keys(self):
        query = dict(get_endpoint(
            "guideline_annotation_by_pair").query_for(PARAMETERS))
        self.assertEqual(query["relatedGenes.accessionId"], "PA124")
        self.assertEqual(query["relatedChemicals.accessionId"], "PA449053")

    def test_the_three_legacy_guideline_param_sets_are_separate_endpoints(self):
        """The probe merged them; merging is a resolution decision."""
        for endpoint_id in ("guideline_annotation_by_pair",
                            "guideline_annotation_by_gene",
                            "guideline_annotation_by_chemical"):
            with self.subTest(endpoint=endpoint_id):
                self.assertEqual(get_endpoint(endpoint_id).path_template,
                                 "/data/guidelineAnnotation")

    def test_the_variant_endpoint_uses_the_legacy_location_filter(self):
        query = dict(get_endpoint(
            "variant_annotation_by_gene").query_for(PARAMETERS))
        self.assertEqual(query["location.genes.symbol"], "CYP2C19")

    def test_the_pair_report_path_is_built_from_explicit_parameters(self):
        path = get_endpoint("pair_report").path_for(PARAMETERS)
        self.assertEqual(path, "/report/pair/PA124/PA449053/guidelineAnnotation")

    def test_the_connected_objects_path_is_built_from_explicit_parameters(self):
        path = get_endpoint("connected_objects").path_for(PARAMETERS)
        self.assertEqual(path,
                         "/report/connectedObjects/PA449053/Chemical")

    def test_a_missing_path_parameter_is_refused_rather_than_guessed(self):
        with self.assertRaises(ConfigurationError):
            get_endpoint("pair_report").path_for({"first_id": "PA124"})

    def test_every_legacy_path_has_a_catalog_entry(self):
        declared = {endpoint.path_template for endpoint in clinpgx_catalog()}
        for path in ("/data/gene", "/data/chemical", "/data/guidelineAnnotation",
                     "/data/variantAnnotation"):
            self.assertIn(path, declared)
        self.assertTrue(any(item.startswith("/report/pair/")
                            for item in declared))
        self.assertTrue(any(item.startswith("/report/connectedObjects/")
                            for item in declared))


class TestLegacyDefectsWereNotPorted(unittest.TestCase):
    """Each absence, with the reason it matters."""

    MODULES = (catalog, adapter, parsers, client)

    def test_no_module_selects_the_first_result(self):
        """get_first() made an unreviewed identity decision."""
        for module in self.MODULES:
            names = _identifiers(module)
            with self.subTest(module=module.__name__):
                for token in ("get_first", "first_match", "first_item",
                              "pick_first"):
                    self.assertNotIn(token, names)

    def test_no_module_indexes_the_first_element_of_a_record_list(self):
        """`items[0]` is the same decision spelled differently."""
        for module in self.MODULES:
            tree = ast.parse(inspect.getsource(module))
            with self.subTest(module=module.__name__):
                for node in ast.walk(tree):
                    if not isinstance(node, ast.Subscript):
                        continue
                    index = node.slice
                    if (isinstance(index, ast.Constant) and index.value == 0
                            and isinstance(node.value, ast.Name)
                            and "record" in node.value.id.lower()):
                        self.fail("%s indexes a record list at [0]"
                                  % module.__name__)

    def test_no_module_reimplements_flatten_items(self):
        """Six container keys tried in turn, then the payload wrapped."""
        for module in self.MODULES:
            names = _identifiers(module)
            code = _code_of(module)
            with self.subTest(module=module.__name__):
                self.assertNotIn("flatten_items", names)
                for key in ('"items"', '"results"', '"content"',
                            '"objects"', '"resources"'):
                    self.assertNotIn(key, code,
                                     "%s looks like a fallback container key"
                                     % key)

    def test_the_records_container_is_declared_not_guessed(self):
        for endpoint in clinpgx_catalog():
            with self.subTest(endpoint=endpoint.endpoint_id):
                self.assertEqual(endpoint.records_path, ("data",))

    def test_no_module_declares_a_fixed_request_delay(self):
        """``REQUEST_DELAY_SECONDS = 0.6`` sat before every legacy call."""
        for module in self.MODULES:
            names = _identifiers(module)
            with self.subTest(module=module.__name__):
                for token in ("REQUEST_DELAY_SECONDS", "REQUEST_DELAY",
                              "sleep_softly"):
                    self.assertNotIn(token, names)

    def test_the_only_sleep_is_the_injected_sleeper(self):
        """A default sleeper must exist; an unconditional delay must not.

        The distinction matters: backoff *should* sleep, which is why the
        production default calls ``time.sleep``. What was not ported is a fixed
        pause before every request regardless of what the server said. So the
        rule is that any sleep is reachable only through the injected
        ``sleeper``, and tests replace it.
        """
        tree = ast.parse(inspect.getsource(adapter))
        sleeping_functions = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            for inner in ast.walk(node):
                if (isinstance(inner, ast.Attribute) and inner.attr == "sleep"
                        and isinstance(inner.value, ast.Name)
                        and inner.value.id == "time"):
                    sleeping_functions.add(node.name)
        self.assertEqual(sleeping_functions, {"_sleep"},
                         "only the injectable default sleeper may sleep")
        self.assertIn("sleeper", _identifiers(adapter),
                      "the sleeper must be injectable")

    def test_no_module_declares_a_global_output_directory(self):
        """OUT_DIR made importing the probe decide where data went."""
        for module in self.MODULES:
            names = _identifiers(module)
            with self.subTest(module=module.__name__):
                for token in ("OUT_DIR", "clinpgx_outputs", "makedirs",
                              "mkdir", "write_text", "save_json", "write_csv"):
                    self.assertNotIn(token, names)

    def test_no_module_swallows_a_404(self):
        """quiet_404 made a missing record look like an empty one."""
        for module in self.MODULES:
            names = _identifiers(module)
            with self.subTest(module=module.__name__):
                self.assertNotIn("quiet_404", names)

    def test_no_module_performs_scientific_normalisation(self):
        """Renaming or interpreting a source field is WP-07 and later."""
        for module in self.MODULES:
            names = _identifiers(module)
            with self.subTest(module=module.__name__):
                for token in ("summarize_annotation", "make_mvp_edge_row",
                              "html_to_text", "rank_key", "dedupe_by_id",
                              "attention_level", "normalize_phenotype",
                              "summarize_gene", "summarize_chemical"):
                    self.assertNotIn(token, names)

    def test_no_module_imports_requests(self):
        """The production transport is stdlib; no dependency was added."""
        for module in self.MODULES:
            tree = ast.parse(_source(module))
            imported = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module)
            with self.subTest(module=module.__name__):
                self.assertNotIn("requests", {name.split(".")[0]
                                              for name in imported})

    def test_the_variant_endpoint_does_not_truncate_or_rank(self):
        """The probe kept 30 items after a hand-written heuristic."""
        endpoint = get_endpoint("variant_annotation_by_gene")
        self.assertIn("no ranking, filtering or truncation",
                      endpoint.limitations)


class TestTheCatalogIsSeparateFromTheRunner(unittest.TestCase):
    """Adding an endpoint must not require editing orchestration code."""

    def test_the_adapter_names_no_specific_endpoint(self):
        code = _code_of(adapter)
        for endpoint_id in catalog_ids():
            with self.subTest(endpoint=endpoint_id):
                self.assertNotIn("'%s'" % endpoint_id, code)

    def test_the_service_names_no_specific_endpoint(self):
        from pgx.application import ingestion_service

        code = _code_of(ingestion_service)
        for endpoint_id in catalog_ids():
            with self.subTest(endpoint=endpoint_id):
                self.assertNotIn("'%s'" % endpoint_id, code)

    def test_the_catalog_imports_nothing_that_makes_a_request(self):
        """The catalog is data. It cannot reach the network even by accident."""
        tree = ast.parse(_source(catalog))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        for forbidden in ("pgx.ingestion.common.http",
                          "pgx.ingestion.common.cache",
                          "pgx.ingestion.common.retry",
                          "urllib", "urllib.request", "http.client", "socket"):
            self.assertNotIn(forbidden, imported)

    def test_the_catalog_defines_no_request_function(self):
        names = _identifiers(catalog)
        for token in ("send", "urlopen", "execute_with_retry", "request_key"):
            self.assertNotIn(token, names)

    def test_a_new_endpoint_needs_only_a_declaration(self):
        """Demonstrated: build a declaration and plan it, editing nothing."""
        import tempfile

        from pgx.application.ingestion_service import IngestionService
        from pgx.ingestion.clinpgx.adapter import build_page_request
        from pgx.ingestion.clinpgx.catalog import EndpointDeclaration, ResponseShape
        from pgx.ingestion.common.cache import ResponseCache
        from pgx.ingestion.common.pagination import PaginationSpec

        invented = EndpointDeclaration(
            endpoint_id="invented_endpoint", path_template="/data/invented",
            required=False, shape=ResponseShape.DATA_LIST,
            records_path=("data",), purpose="a fixture endpoint for this test",
            limitations="not a real ClinPGx endpoint; declared here only",
            pagination=PaginationSpec(),
            build_query=lambda parameters: (("q", "x"),))
        request = build_page_request(
            invented, PARAMETERS, CLINPGX_BASE_URL, 30.0, 1, None, 0)
        self.assertEqual(request.path, "/data/invented")
        self.assertEqual(request.endpoint_id, "invented_endpoint")


class TestNoLiveCallWasMade(unittest.TestCase):

    def test_the_test_suite_declares_no_live_endpoint_call(self):
        """Every adapter test uses a scripted transport."""
        directory = os.path.dirname(os.path.abspath(__file__))
        for name in sorted(os.listdir(directory)):
            if not name.startswith("test_") or not name.endswith(".py"):
                continue
            with io.open(os.path.join(directory, name), encoding="utf-8") as handle:
                source = handle.read()
            with self.subTest(module=name):
                # Tokens are rebuilt at runtime so this test cannot match its
                # own source and pass for the wrong reason.
                live_call = "build_clinpgx_transport" + "()"
                self.assertNotIn(live_call, source)
                self.assertNotIn("urllib" + ".request.urlopen", source)
                self.assertNotIn("socket." + "create_connection", source)

    def test_the_source_id_names_a_source_not_an_endorsement(self):
        self.assertEqual(CLINPGX_SOURCE_ID, "clinpgx")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
