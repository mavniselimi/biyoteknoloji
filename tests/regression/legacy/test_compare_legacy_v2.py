# -*- coding: utf-8 -*-
"""Group F: comparison harness semantics, allowlist strictness, determinism.

    python3 -m unittest tests.regression.legacy.test_compare_legacy_v2 -v
"""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest

from tests.regression.legacy._support import ALLOWLIST_PATH, REPO_ROOT, BaselineRequiredMixin, missing_baseline_artifacts

import compare_legacy_v2 as harness
from compare_legacy_v2 import Allowlist, ConfigurationError


def write(path, text):
    with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return path


def write_json(path, obj):
    return write(path, json.dumps(obj, ensure_ascii=False))


def read_json_file(path):
    with io.open(path, encoding="utf-8") as handle:
        return json.load(handle)


class HarnessTestCase(BaselineRequiredMixin, unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="wp01-harness-")
        self.tmp = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

    def path(self, name):
        return os.path.join(self.tmp, name)

    def compare(self, legacy, candidate, allowlist=None, artifact_id=None):
        return harness.run_compare(legacy, candidate,
                                   allowlist or ALLOWLIST_PATH, None, artifact_id)


class TestJsonComparison(HarnessTestCase):

    def test_identical_json_is_a_match(self):
        a = write_json(self.path("a.json"), {"x": 1, "y": ["p", "q"]})
        b = write_json(self.path("b.json"), {"x": 1, "y": ["p", "q"]})
        report, code = self.compare(a, b)
        self.assertEqual(report["outcome"], harness.STATUS_MATCH)
        self.assertEqual(code, harness.EXIT_OK)

    def test_object_key_order_is_not_a_semantic_difference(self):
        a = write(self.path("a.json"), '{"alpha": 1, "beta": 2}')
        b = write(self.path("b.json"), '{"beta": 2, "alpha": 1}')
        report, code = self.compare(a, b)
        self.assertNotEqual(harness.sha256_file(a), harness.sha256_file(b))
        self.assertEqual(report["outcome"], harness.STATUS_MATCH)
        self.assertEqual(code, harness.EXIT_OK)

    def test_array_order_is_a_difference(self):
        a = write_json(self.path("a.json"), {"items": [1, 2]})
        b = write_json(self.path("b.json"), {"items": [2, 1]})
        report, code = self.compare(a, b)
        self.assertEqual(report["outcome"], harness.STATUS_UNEXPECTED)
        self.assertEqual(code, harness.EXIT_UNEXPECTED_DIFFERENCE)
        selectors = [d["selector"] for d in report["artifacts"][0]["differences"]]
        self.assertIn("$.items[0]", selectors)

    def test_numeric_and_string_are_not_coerced(self):
        a = write_json(self.path("a.json"), {"n": "1"})
        b = write_json(self.path("b.json"), {"n": 1})
        report, code = self.compare(a, b)
        self.assertEqual(code, harness.EXIT_UNEXPECTED_DIFFERENCE)
        difference = report["artifacts"][0]["differences"][0]
        self.assertEqual(difference["reason"], "type_mismatch")
        self.assertEqual(difference["selector"], "$.n")

    def test_boolean_is_not_conflated_with_one(self):
        a = write_json(self.path("a.json"), {"flag": True})
        b = write_json(self.path("b.json"), {"flag": 1})
        report, code = self.compare(a, b)
        self.assertEqual(code, harness.EXIT_UNEXPECTED_DIFFERENCE)

    def test_absent_key_is_reported_at_its_exact_selector(self):
        a = write_json(self.path("a.json"), {"kept": 1, "dropped": 2})
        b = write_json(self.path("b.json"), {"kept": 1})
        report, code = self.compare(a, b)
        self.assertEqual(code, harness.EXIT_UNEXPECTED_DIFFERENCE)
        difference = report["artifacts"][0]["differences"][0]
        self.assertEqual(difference["selector"], "$.dropped")
        self.assertEqual(difference["reason"], "absent_on_one_side")
        self.assertEqual(difference["candidate_value"], "<ABSENT>")

    def test_nested_selector_is_precise(self):
        a = write_json(self.path("a.json"), {"a": {"b": [{"c": 1}]}})
        b = write_json(self.path("b.json"), {"a": {"b": [{"c": 2}]}})
        report, code = self.compare(a, b)
        self.assertEqual(report["artifacts"][0]["differences"][0]["selector"],
                         "$.a.b[0].c")


class TestAllowlistBehaviour(HarnessTestCase):
    """Exact artifact identity + identity-addressed selectors."""

    ARTIFACT = "risk-p2-cyp2c19-poor.json"
    LEGACY_SNAPSHOT = {
        "drug_results": [
            {"drug": "clopidogrel", "overall_risk_level": "high"},
            {"drug": "voriconazole", "overall_risk_level": "high"},
            {"drug": "codeine", "overall_risk_level": "none"},
            {"drug": "warfarin", "overall_risk_level": "none"},
        ]
    }

    def _dirs(self, mutate=None, name=None, legacy_doc=None):
        legacy_dir = os.path.join(self.tmp, "legacy")
        candidate_dir = os.path.join(self.tmp, "candidate")
        for path in (legacy_dir, candidate_dir):
            if not os.path.isdir(path):
                os.makedirs(path)
        name = name or self.ARTIFACT
        base = legacy_doc if legacy_doc is not None else self.LEGACY_SNAPSHOT
        write_json(os.path.join(legacy_dir, name), base)
        modified = json.loads(json.dumps(base))
        if mutate:
            mutate(modified)
        write_json(os.path.join(candidate_dir, name), modified)
        return legacy_dir, candidate_dir

    def _drug(self, document, name):
        for entry in document["drug_results"]:
            if entry["drug"] == name:
                return entry
        raise KeyError(name)

    # -- exact identity ------------------------------------------------

    def test_correct_exact_artifact_id_matches(self):
        legacy_dir, candidate_dir = self._dirs(
            lambda d: self._drug(d, "codeine").__setitem__(
                "overall_risk_level", "NOT_ASSESSED"))
        report, code = self.compare(legacy_dir, candidate_dir)
        self.assertEqual(report["outcome"], harness.STATUS_EXPECTED)
        self.assertEqual(code, harness.EXIT_OK)
        self.assertIn("XDIFF-LEGACY-BUG-002-CODEINE", report["applied_rule_ids"])

    def test_same_basename_in_a_different_directory_does_not_match(self):
        """An unrelated file sharing a basename must never borrow a rule."""
        legacy_dir = os.path.join(self.tmp, "legacy")
        candidate_dir = os.path.join(self.tmp, "candidate")
        for base in (legacy_dir, candidate_dir):
            os.makedirs(os.path.join(base, "unrelated"))
        rel = os.path.join("unrelated", self.ARTIFACT)
        write_json(os.path.join(legacy_dir, rel), self.LEGACY_SNAPSHOT)
        modified = json.loads(json.dumps(self.LEGACY_SNAPSHOT))
        self._drug(modified, "codeine")["overall_risk_level"] = "NOT_ASSESSED"
        write_json(os.path.join(candidate_dir, rel), modified)

        report, code = self.compare(legacy_dir, candidate_dir)
        self.assertEqual(report["outcome"], harness.STATUS_UNEXPECTED)
        self.assertEqual(code, harness.EXIT_UNEXPECTED_DIFFERENCE)
        self.assertEqual(report["applied_rule_ids"], [])
        self.assertEqual(report["artifacts"][0]["artifact"],
                         "unrelated/" + self.ARTIFACT)

    def test_file_mode_without_artifact_id_cannot_apply_a_rule(self):
        legacy = write_json(self.path("a.json"), self.LEGACY_SNAPSHOT)
        modified = json.loads(json.dumps(self.LEGACY_SNAPSHOT))
        self._drug(modified, "codeine")["overall_risk_level"] = "NOT_ASSESSED"
        candidate = write_json(self.path("b.json"), modified)
        report, code = self.compare(legacy, candidate)
        self.assertEqual(code, harness.EXIT_UNEXPECTED_DIFFERENCE)
        self.assertEqual(report["applied_rule_ids"], [])
        self.assertIn(harness.UNIDENTIFIED_ARTIFACT,
                      report["artifact_identity"]["unidentified_artifacts"])

    def test_file_mode_with_explicit_artifact_id_matches(self):
        legacy = write_json(self.path("a.json"), self.LEGACY_SNAPSHOT)
        modified = json.loads(json.dumps(self.LEGACY_SNAPSHOT))
        self._drug(modified, "codeine")["overall_risk_level"] = "NOT_ASSESSED"
        candidate = write_json(self.path("b.json"), modified)
        report, code = self.compare(legacy, candidate, artifact_id=self.ARTIFACT)
        self.assertEqual(report["outcome"], harness.STATUS_EXPECTED)
        self.assertEqual(code, harness.EXIT_OK)
        self.assertIn("XDIFF-LEGACY-BUG-002-CODEINE", report["applied_rule_ids"])

    def test_artifact_id_path_traversal_is_rejected(self):
        legacy = write_json(self.path("a.json"), {"x": 1})
        candidate = write_json(self.path("b.json"), {"x": 2})
        for bad in ("../escape.json", "/etc/passwd", "a/../../b.json",
                    "snap*.json", "./a.json", ""):
            with self.assertRaises(ConfigurationError, msg=bad):
                self.compare(legacy, candidate, artifact_id=bad)

    def test_artifact_id_is_rejected_for_directory_comparison(self):
        legacy_dir, candidate_dir = self._dirs()
        with self.assertRaises(ConfigurationError):
            self.compare(legacy_dir, candidate_dir, artifact_id=self.ARTIFACT)

    # -- identity-addressed selectors ----------------------------------

    def test_codeine_rule_is_not_applied_to_warfarin(self):
        """The core safety property: a rule may not migrate to another entity."""
        legacy_dir, candidate_dir = self._dirs(
            lambda d: self._drug(d, "warfarin").__setitem__(
                "overall_risk_level", "NOT_ASSESSED"))
        report, code = self.compare(legacy_dir, candidate_dir)
        difference = report["artifacts"][0]["differences"][0]
        self.assertEqual(difference["selector"],
                         "$.drug_results[drug=warfarin].overall_risk_level")
        self.assertEqual(difference["matched_rule_id"],
                         "XDIFF-LEGACY-BUG-002-WARFARIN")
        self.assertNotIn("XDIFF-LEGACY-BUG-002-CODEINE", report["applied_rule_ids"])
        self.assertEqual(code, harness.EXIT_OK)

    def test_reordering_does_not_move_a_rule_onto_another_drug(self):
        def mutate(document):
            document["drug_results"].reverse()
        legacy_dir, candidate_dir = self._dirs(mutate)
        report, code = self.compare(legacy_dir, candidate_dir)
        selectors = {d["selector"]: d for d in report["artifacts"][0]["differences"]}
        # The only difference is the order itself; no field difference appears.
        self.assertIn("$.drug_results[order]", selectors)
        self.assertEqual(selectors["$.drug_results[order]"]["reason"],
                         "list_order_mismatch")
        self.assertEqual(len(selectors), 1, selectors)
        # Order is not allowlisted, so it is an unexpected difference.
        self.assertEqual(code, harness.EXIT_UNEXPECTED_DIFFERENCE)

    def test_reorder_plus_field_change_reports_the_right_entity(self):
        def mutate(document):
            document["drug_results"].reverse()
            self._drug(document, "codeine")["overall_risk_level"] = "NOT_ASSESSED"
        legacy_dir, candidate_dir = self._dirs(mutate)
        report, _ = self.compare(legacy_dir, candidate_dir)
        by_selector = {d["selector"]: d for d in report["artifacts"][0]["differences"]}
        self.assertIn("$.drug_results[order]", by_selector)
        field = by_selector["$.drug_results[drug=codeine].overall_risk_level"]
        self.assertEqual(field["matched_rule_id"], "XDIFF-LEGACY-BUG-002-CODEINE")
        self.assertEqual(field["legacy_value"], '"none"')
        self.assertEqual(field["candidate_value"], '"NOT_ASSESSED"')

    def test_duplicate_identity_is_a_failure_not_a_silent_first_match(self):
        duplicated = {"drug_results": [
            {"drug": "codeine", "overall_risk_level": "none"},
            {"drug": "codeine", "overall_risk_level": "high"},
        ]}
        legacy_dir, candidate_dir = self._dirs(
            lambda d: d["drug_results"][0].__setitem__("overall_risk_level", "x"),
            legacy_doc=duplicated)
        report, code = self.compare(legacy_dir, candidate_dir)
        self.assertEqual(report["outcome"], harness.STATUS_AMBIGUOUS_IDENTITY)
        self.assertEqual(code, harness.EXIT_CONFIGURATION_FAILURE)
        self.assertIn("duplicate identity", report["artifacts"][0]["detail"])

    def test_removed_list_item_is_reported_by_identity(self):
        def mutate(document):
            document["drug_results"] = [
                e for e in document["drug_results"] if e["drug"] != "warfarin"]
        legacy_dir, candidate_dir = self._dirs(mutate)
        report, _ = self.compare(legacy_dir, candidate_dir)
        selectors = {d["selector"]: d for d in report["artifacts"][0]["differences"]}
        removed = selectors["$.drug_results[drug=warfarin]"]
        self.assertEqual(removed["reason"], "list_item_removed")
        self.assertEqual(removed["candidate_value"], "<ABSENT>")

    def test_added_list_item_is_reported_by_identity(self):
        def mutate(document):
            document["drug_results"].append(
                {"drug": "omeprazole", "overall_risk_level": "medium"})
        legacy_dir, candidate_dir = self._dirs(mutate)
        report, _ = self.compare(legacy_dir, candidate_dir)
        selectors = {d["selector"]: d for d in report["artifacts"][0]["differences"]}
        added = selectors["$.drug_results[drug=omeprazole]"]
        self.assertEqual(added["reason"], "list_item_added")
        self.assertEqual(added["legacy_value"], "<ABSENT>")

    def test_prasugrel_and_ticagrelor_match_their_own_rules(self):
        legacy = {"candidate_results": [
            {"candidate_drug": "prasugrel", "legacy_score_unprotected": 59},
            {"candidate_drug": "ticagrelor", "legacy_score_unprotected": 59},
        ]}
        legacy_dir = os.path.join(self.tmp, "legacy")
        candidate_dir = os.path.join(self.tmp, "candidate")
        os.makedirs(legacy_dir)
        os.makedirs(candidate_dir)
        name = "alternative-beta-clopidogrel.json"
        write_json(os.path.join(legacy_dir, name), legacy)
        removed = {"candidate_results": [
            {"candidate_drug": "prasugrel"},
            {"candidate_drug": "ticagrelor"},
        ]}
        write_json(os.path.join(candidate_dir, name), removed)
        report, code = self.compare(legacy_dir, candidate_dir)
        self.assertEqual(report["outcome"], harness.STATUS_EXPECTED)
        self.assertEqual(code, harness.EXIT_OK)
        self.assertEqual(sorted(report["applied_rule_ids"]),
                         ["XDIFF-LEGACY-BUG-009-PRASUGREL-SCORE-REMOVAL",
                          "XDIFF-LEGACY-BUG-009-TICAGRELOR-SCORE-REMOVAL"])
        # Each difference must be matched by the rule for its OWN candidate.
        for difference in report["artifacts"][0]["differences"]:
            selector = difference["selector"]
            rule_id = difference["matched_rule_id"]
            drug = selector.split("candidate_drug=")[1].split("]")[0]
            self.assertIn(drug.upper(), rule_id,
                          "%s must be matched by its own rule, got %s"
                          % (selector, rule_id))

    def test_legacy_bug_007_covers_both_counts(self):
        legacy_dir = os.path.join(self.tmp, "legacy")
        candidate_dir = os.path.join(self.tmp, "candidate")
        os.makedirs(legacy_dir)
        os.makedirs(candidate_dir)
        name = "mvp_seed_summary.json"
        write_json(os.path.join(legacy_dir, name),
                   {"counts": {"supported_drugs": 11, "guideline_rows": 30}})
        write_json(os.path.join(candidate_dir, name),
                   {"counts": {"supported_drugs": 15, "guideline_rows": 36}})
        report, code = self.compare(legacy_dir, candidate_dir)
        self.assertEqual(report["outcome"], harness.STATUS_EXPECTED)
        self.assertEqual(code, harness.EXIT_OK)
        self.assertEqual(sorted(report["applied_rule_ids"]),
                         ["XDIFF-LEGACY-BUG-007-GUIDELINE-ROWS",
                          "XDIFF-LEGACY-BUG-007-SUPPORTED-DRUGS"])

    # -- allowlist hygiene ---------------------------------------------

    def test_a_difference_outside_the_allowlist_is_unexpected(self):
        legacy_dir, candidate_dir = self._dirs(
            lambda d: self._drug(d, "clopidogrel").__setitem__(
                "overall_risk_level", "low"))
        report, code = self.compare(legacy_dir, candidate_dir)
        self.assertEqual(report["outcome"], harness.STATUS_UNEXPECTED)
        self.assertEqual(code, harness.EXIT_UNEXPECTED_DIFFERENCE)

    def test_unused_allowlist_entries_are_reported_not_silently_passed(self):
        legacy_dir, candidate_dir = self._dirs(
            lambda d: self._drug(d, "codeine").__setitem__(
                "overall_risk_level", "NOT_ASSESSED"))
        report, _ = self.compare(legacy_dir, candidate_dir)
        self.assertTrue(report["unused_allowlist_entries"])
        self.assertNotIn("XDIFF-LEGACY-BUG-002-CODEINE",
                         report["unused_allowlist_entries"])

    def test_registered_but_inactive_entries_suppress_nothing(self):
        allowlist = Allowlist(ALLOWLIST_PATH)
        self.assertTrue(allowlist.inactive_entries)
        for entry in allowlist.entries:
            if not entry["active"]:
                self.assertIsNone(entry["comparison_selector"], entry["rule_id"])
                self.assertIsNone(entry["artifact_id"], entry["rule_id"])

    def test_unknown_bug_id_is_a_configuration_failure(self):
        document = read_json_file(ALLOWLIST_PATH)
        document["entries"][0]["bug_id"] = "LEGACY-BUG-099"
        bad = write_json(self.path("bad.json"), document)
        with self.assertRaises(ConfigurationError) as ctx:
            Allowlist(bad)
        self.assertIn("LEGACY-BUG-099", str(ctx.exception))

    def test_unknown_bug_id_exits_two_through_the_cli(self):
        document = read_json_file(ALLOWLIST_PATH)
        document["entries"][0]["bug_id"] = "NOT-A-BUG"
        bad = write_json(self.path("bad.json"), document)
        a = write_json(self.path("a.json"), {"x": 1})
        b = write_json(self.path("b.json"), {"x": 1})
        code = harness.main(["compare", "--legacy", a, "--candidate", b,
                             "--allowlist", bad, "--quiet"])
        self.assertEqual(code, harness.EXIT_CONFIGURATION_FAILURE)

    def test_wildcard_selector_is_rejected(self):
        for broad in ("*", "$.*", "$..drug_results", "$", ""):
            document = read_json_file(ALLOWLIST_PATH)
            for entry in document["entries"]:
                if entry["active"]:
                    entry["comparison_selector"] = broad
            bad = write_json(self.path("broad.json"), document)
            with self.assertRaises(ConfigurationError, msg=broad):
                Allowlist(bad)

    def test_wildcard_artifact_id_is_rejected(self):
        document = read_json_file(ALLOWLIST_PATH)
        for entry in document["entries"]:
            if entry["active"]:
                entry["artifact_id"] = "*"
        bad = write_json(self.path("broad.json"), document)
        with self.assertRaises(ConfigurationError):
            Allowlist(bad)

    def test_active_entry_without_an_artifact_id_is_rejected(self):
        document = read_json_file(ALLOWLIST_PATH)
        for entry in document["entries"]:
            if entry["active"]:
                entry["artifact_id"] = None
        bad = write_json(self.path("noartifact.json"), document)
        with self.assertRaises(ConfigurationError) as ctx:
            Allowlist(bad)
        self.assertIn("artifact_id", str(ctx.exception))

    def test_traversing_artifact_id_in_the_allowlist_is_rejected(self):
        document = read_json_file(ALLOWLIST_PATH)
        for entry in document["entries"]:
            if entry["active"]:
                entry["artifact_id"] = "../outside.json"
        bad = write_json(self.path("traverse.json"), document)
        with self.assertRaises(ConfigurationError):
            Allowlist(bad)

    def test_active_entry_without_a_selector_is_rejected(self):
        document = read_json_file(ALLOWLIST_PATH)
        for entry in document["entries"]:
            if entry["active"]:
                entry["comparison_selector"] = None
        bad = write_json(self.path("noselector.json"), document)
        with self.assertRaises(ConfigurationError):
            Allowlist(bad)

    def test_duplicate_artifact_selector_pair_is_rejected(self):
        document = read_json_file(ALLOWLIST_PATH)
        active = [e for e in document["entries"] if e["active"]]
        clone = dict(active[0])
        clone["rule_id"] = clone["rule_id"] + "-DUPLICATE"
        document["entries"].append(clone)
        bad = write_json(self.path("dup.json"), document)
        with self.assertRaises(ConfigurationError) as ctx:
            Allowlist(bad)
        self.assertIn("same artifact_id", str(ctx.exception))

    def test_protected_as_correct_entry_is_rejected(self):
        document = read_json_file(ALLOWLIST_PATH)
        document["entries"][0]["protected_as_correct"] = True
        bad = write_json(self.path("protected.json"), document)
        with self.assertRaises(ConfigurationError) as ctx:
            Allowlist(bad)
        self.assertIn("protected_as_correct", str(ctx.exception))

    def test_the_shipped_allowlist_loads_cleanly(self):
        allowlist = Allowlist(ALLOWLIST_PATH)
        self.assertEqual(len(allowlist.entries), 15)
        self.assertEqual(len(allowlist.inactive_entries), 8)
        active = [e for e in allowlist.entries if e["active"]]
        self.assertEqual(len(active), 7)
        for entry in active:
            self.assertTrue(entry["artifact_id"])
            self.assertTrue(entry["comparison_selector"])


class TestCsvAndTextComparison(HarnessTestCase):

    def test_csv_cell_difference_names_the_row_and_column(self):
        a = write(self.path("a.csv"), "drug,risk\nclopidogrel,high\ncodeine,none\n")
        b = write(self.path("b.csv"), "drug,risk\nclopidogrel,high\ncodeine,NOT_ASSESSED\n")
        report, code = self.compare(a, b)
        self.assertEqual(code, harness.EXIT_UNEXPECTED_DIFFERENCE)
        difference = report["artifacts"][0]["differences"][0]
        self.assertEqual(difference["selector"], "csv:row[1].column[risk]")
        self.assertEqual(difference["reason"], "cell_mismatch")

    def test_csv_header_difference_is_reported(self):
        a = write(self.path("a.csv"), "drug,risk\nclopidogrel,high\n")
        b = write(self.path("b.csv"), "drug,attention\nclopidogrel,high\n")
        report, code = self.compare(a, b)
        self.assertEqual(code, harness.EXIT_UNEXPECTED_DIFFERENCE)
        selectors = [d["selector"] for d in report["artifacts"][0]["differences"]]
        self.assertIn("csv:header", selectors)

    def test_csv_row_order_is_significant(self):
        a = write(self.path("a.csv"), "drug,risk\nclopidogrel,high\ncodeine,none\n")
        b = write(self.path("b.csv"), "drug,risk\ncodeine,none\nclopidogrel,high\n")
        report, code = self.compare(a, b)
        self.assertEqual(code, harness.EXIT_UNEXPECTED_DIFFERENCE)

    def test_identical_csv_is_a_match(self):
        text = "drug,risk\nclopidogrel,high\n"
        report, code = self.compare(write(self.path("a.csv"), text),
                                    write(self.path("b.csv"), text))
        self.assertEqual(report["outcome"], harness.STATUS_MATCH)
        self.assertEqual(code, harness.EXIT_OK)

    def test_text_line_difference_names_the_line_number(self):
        a = write(self.path("a.md"), "# Rapor\nsatir bir\nsatir iki\n")
        b = write(self.path("b.md"), "# Rapor\nsatir BIR\nsatir iki\n")
        report, code = self.compare(a, b)
        self.assertEqual(code, harness.EXIT_UNEXPECTED_DIFFERENCE)
        difference = report["artifacts"][0]["differences"][0]
        self.assertEqual(difference["selector"], "text:line[2]")

    def test_identical_text_is_a_match(self):
        text = "# Rapor\nayni icerik\n"
        report, code = self.compare(write(self.path("a.md"), text),
                                    write(self.path("b.md"), text))
        self.assertEqual(report["outcome"], harness.STATUS_MATCH)


class TestFailureModes(HarnessTestCase):

    def test_missing_input_exits_two(self):
        a = write_json(self.path("a.json"), {"x": 1})
        code = harness.main(["compare", "--legacy", a, "--candidate",
                             self.path("missing.json"), "--allowlist", ALLOWLIST_PATH,
                             "--quiet"])
        self.assertEqual(code, harness.EXIT_CONFIGURATION_FAILURE)

    def test_missing_file_inside_a_directory_pair_is_missing_input(self):
        legacy_dir = os.path.join(self.tmp, "legacy")
        candidate_dir = os.path.join(self.tmp, "candidate")
        os.makedirs(legacy_dir)
        os.makedirs(candidate_dir)
        write_json(os.path.join(legacy_dir, "only-legacy.json"), {"x": 1})
        report, code = self.compare(legacy_dir, candidate_dir)
        self.assertEqual(code, harness.EXIT_CONFIGURATION_FAILURE)
        self.assertEqual(report["outcome"], harness.STATUS_MISSING_INPUT)

    def test_unsupported_format_exits_two(self):
        a = write(self.path("a.xml"), "<a/>")
        b = write(self.path("b.xml"), "<a/>")
        report, code = harness.run_compare(a, b, ALLOWLIST_PATH, None)
        self.assertEqual(report["outcome"], harness.STATUS_UNSUPPORTED_FORMAT)
        self.assertEqual(code, harness.EXIT_CONFIGURATION_FAILURE)

    def test_malformed_json_is_reported_as_unsupported_format(self):
        a = write(self.path("a.json"), '{"x": 1}')
        b = write(self.path("b.json"), '{"x": ')
        report, code = self.compare(a, b)
        self.assertEqual(report["artifacts"][0]["status"],
                         harness.STATUS_UNSUPPORTED_FORMAT)
        self.assertEqual(code, harness.EXIT_CONFIGURATION_FAILURE)

    def test_mixing_a_file_and_a_directory_is_a_configuration_failure(self):
        a = write_json(self.path("a.json"), {"x": 1})
        directory = os.path.join(self.tmp, "dir")
        os.makedirs(directory)
        with self.assertRaises(ConfigurationError):
            harness.run_compare(a, directory, ALLOWLIST_PATH, None)

    def test_missing_allowlist_is_a_configuration_failure(self):
        a = write_json(self.path("a.json"), {"x": 1})
        b = write_json(self.path("b.json"), {"x": 1})
        with self.assertRaises(ConfigurationError):
            harness.run_compare(a, b, self.path("no-such-allowlist.json"), None)


class TestDeterminism(HarnessTestCase):

    def test_output_is_byte_deterministic_for_the_same_inputs(self):
        a = write_json(self.path("a.json"), {"z": 1, "a": [3, 2, 1], "m": {"k": "v"}})
        b = write_json(self.path("b.json"), {"a": [3, 2, 9], "m": {"k": "w"}, "z": 1})
        first = self.path("first.json")
        second = self.path("second.json")
        harness.run_compare(a, b, ALLOWLIST_PATH, first)
        harness.run_compare(a, b, ALLOWLIST_PATH, second)
        self.assertEqual(harness.sha256_file(first), harness.sha256_file(second))

    def test_result_contains_every_required_report_field(self):
        a = write_json(self.path("a.json"), {"x": 1})
        b = write_json(self.path("b.json"), {"x": 2})
        report, _ = self.compare(a, b)
        for key in ("schema_version", "legacy_input", "candidate_input", "allowlist",
                    "counts_by_status", "artifacts", "applied_rule_ids",
                    "unused_allowlist_entries", "outcome"):
            self.assertIn(key, report)
        self.assertIsNotNone(report["legacy_input"]["sha256"])
        self.assertIsNotNone(report["candidate_input"]["sha256"])
        self.assertIsNotNone(report["allowlist"]["sha256"])

    def test_counts_by_status_covers_every_status(self):
        a = write_json(self.path("a.json"), {"x": 1})
        b = write_json(self.path("b.json"), {"x": 1})
        report, _ = self.compare(a, b)
        self.assertEqual(sorted(report["counts_by_status"]), sorted(harness.ALL_STATUSES))

    def test_differences_are_sorted_deterministically(self):
        a = write_json(self.path("a.json"), {"z": 1, "a": 1, "m": 1})
        b = write_json(self.path("b.json"), {"z": 2, "a": 2, "m": 2})
        report, _ = self.compare(a, b)
        selectors = [d["selector"] for d in report["artifacts"][0]["differences"]]
        self.assertEqual(selectors, sorted(selectors))


class TestHarnessIsImportSafe(BaselineRequiredMixin, unittest.TestCase):

    def test_importing_the_harness_has_no_side_effects(self):
        import importlib
        module = importlib.import_module("compare_legacy_v2")
        self.assertTrue(hasattr(module, "main"))
        self.assertTrue(hasattr(module, "run_compare"))
        self.assertTrue(hasattr(module, "verify_manifest"))

    def test_exit_code_contract_is_explicit(self):
        self.assertEqual(harness.EXIT_OK, 0)
        self.assertEqual(harness.EXIT_UNEXPECTED_DIFFERENCE, 1)
        self.assertEqual(harness.EXIT_CONFIGURATION_FAILURE, 2)

    def test_harness_uses_only_the_standard_library(self):
        with io.open(os.path.join(REPO_ROOT, "scripts", "compare_legacy_v2.py"),
                     encoding="utf-8") as handle:
            source = handle.read()
        for banned in ("import requests", "import pydantic", "import fastapi",
                       "import sqlalchemy", "import pytest", "import numpy",
                       "import pandas"):
            self.assertNotIn(banned, source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
