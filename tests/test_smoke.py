"""Smoke + behavior tests for APIDIFF (stdlib unittest, no network)."""
import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apidiff import (  # noqa: E402
    TOOL_NAME,
    TOOL_VERSION,
    Severity,
    detect_format,
    diff_files,
    diff_graphql,
    diff_openapi,
)
from apidiff.cli import main  # noqa: E402

DEMO = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "demos", "01-basic",
)


class TestMeta(unittest.TestCase):
    def test_tool_identity(self):
        self.assertEqual(TOOL_NAME, "apidiff")
        self.assertTrue(TOOL_VERSION)


class TestDetect(unittest.TestCase):
    def test_detect_openapi(self):
        self.assertEqual(detect_format('{"openapi": "3.0.0", "paths": {}}'), "openapi")

    def test_detect_graphql(self):
        self.assertEqual(detect_format("type Query { hello: String }"), "graphql")


class TestOpenAPI(unittest.TestCase):
    def test_removed_path_is_breaking(self):
        old = '{"openapi":"3.0.0","paths":{"/a":{"get":{"responses":{}}}}}'
        new = '{"openapi":"3.0.0","paths":{}}'
        res = diff_openapi(old, new)
        self.assertTrue(res.has_breaking())
        codes = {c.code for c in res.breaking}
        self.assertIn("path.removed", codes)

    def test_new_required_param_is_breaking(self):
        old = ('{"openapi":"3.0.0","paths":{"/a":{"get":'
               '{"parameters":[],"responses":{}}}}}')
        new = ('{"openapi":"3.0.0","paths":{"/a":{"get":'
               '{"parameters":[{"name":"q","in":"query","required":true}],'
               '"responses":{}}}}}')
        res = diff_openapi(old, new)
        self.assertTrue(any(c.code == "param.added.required" for c in res.breaking))

    def test_added_optional_param_not_breaking(self):
        old = ('{"openapi":"3.0.0","paths":{"/a":{"get":'
               '{"parameters":[],"responses":{}}}}}')
        new = ('{"openapi":"3.0.0","paths":{"/a":{"get":'
               '{"parameters":[{"name":"q","in":"query","required":false}],'
               '"responses":{}}}}}')
        res = diff_openapi(old, new)
        self.assertFalse(res.has_breaking())

    def test_response_property_removal_is_breaking(self):
        def _spec(props):
            return json.dumps({"openapi": "3.0.0", "paths": {"/a": {"get": {"responses":
                {"200": {"content": {"application/json": {"schema":
                    {"properties": props}}}}}}}}})
        old = _spec({"x": {"type": "string"}})
        new = _spec({})
        res = diff_openapi(old, new)
        self.assertTrue(any(c.code == "response.property.removed" for c in res.breaking))

    def test_identical_no_changes(self):
        doc = '{"openapi":"3.0.0","paths":{"/a":{"get":{"responses":{}}}}}'
        res = diff_openapi(doc, doc)
        self.assertEqual(len(res.changes), 0)


class TestGraphQL(unittest.TestCase):
    def test_removed_field_is_breaking(self):
        old = "type User { id: ID! name: String }"
        new = "type User { id: ID! }"
        res = diff_graphql(old, new)
        self.assertTrue(any(c.code == "field.removed" for c in res.breaking))

    def test_new_required_input_field_is_breaking(self):
        old = "input Filter { name: String }"
        new = "input Filter { name: String region: String! }"
        res = diff_graphql(old, new)
        self.assertTrue(
            any(c.code == "input.field.added.required" for c in res.breaking))

    def test_enum_value_removed_is_breaking(self):
        old = "enum Color { RED GREEN BLUE }"
        new = "enum Color { RED GREEN }"
        res = diff_graphql(old, new)
        self.assertTrue(any(c.code == "enum.value.removed" for c in res.breaking))

    def test_new_required_arg_is_breaking(self):
        old = "type Query { pets: [String] }"
        new = "type Query { pets(first: Int!): [String] }"
        res = diff_graphql(old, new)
        self.assertTrue(any(c.code == "arg.added.required" for c in res.breaking))

    def test_added_type_is_info_only(self):
        old = "type A { x: Int }"
        new = "type A { x: Int } type B { y: Int }"
        res = diff_graphql(old, new)
        self.assertFalse(res.has_breaking())
        self.assertTrue(any(c.code == "type.added" for c in res.changes))


class TestDispatchAndDemo(unittest.TestCase):
    def test_diff_files_autodetect(self):
        res = diff_files("type A { x: Int }", "type A { }")
        self.assertEqual(res.api_format, "graphql")
        self.assertTrue(res.has_breaking())

    def test_demo_files_exist_and_break(self):
        with open(os.path.join(DEMO, "openapi.old.json")) as f:
            old = f.read()
        with open(os.path.join(DEMO, "openapi.new.json")) as f:
            new = f.read()
        res = diff_files(old, new)
        self.assertTrue(res.has_breaking())
        codes = {c.code for c in res.breaking}
        self.assertIn("operation.removed", codes)
        self.assertIn("param.added.required", codes)
        self.assertIn("response.property.removed", codes)


class TestSarif(unittest.TestCase):
    def _result(self):
        with open(os.path.join(DEMO, "openapi.old.json")) as f:
            old = f.read()
        with open(os.path.join(DEMO, "openapi.new.json")) as f:
            new = f.read()
        return diff_files(old, new)

    def test_sarif_structure(self):
        sarif = self._result().to_sarif("apidiff", "9.9.9")
        self.assertEqual(sarif["version"], "2.1.0")
        run = sarif["runs"][0]
        driver = run["tool"]["driver"]
        self.assertEqual(driver["name"], "apidiff")
        self.assertEqual(driver["version"], "9.9.9")
        # every result references a rule that exists in the catalogue
        rule_ids = {r["id"] for r in driver["rules"]}
        self.assertTrue(rule_ids)
        for res in run["results"]:
            self.assertIn(res["ruleId"], rule_ids)
            self.assertEqual(
                driver["rules"][res["ruleIndex"]]["id"], res["ruleId"])

    def test_sarif_levels_map_from_severity(self):
        sarif = self._result().to_sarif()
        levels = {r["level"] for r in sarif["runs"][0]["results"]}
        # demo 01 has breaking changes -> at least one 'error'
        self.assertIn("error", levels)
        self.assertTrue(levels <= {"error", "warning", "note"})

    def test_sarif_empty_diff(self):
        res = diff_files(
            '{"openapi":"3.0.0","paths":{}}',
            '{"openapi":"3.0.0","paths":{}}')
        sarif = res.to_sarif()
        self.assertEqual(sarif["runs"][0]["results"], [])
        self.assertEqual(sarif["runs"][0]["tool"]["driver"]["rules"], [])


DEMOS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "demos")


class TestAllDemos(unittest.TestCase):
    # demo dir -> expected (has_breaking, min total changes)
    EXPECTATIONS = {
        "01-basic": (True, 4),
        "02-graphql-schema": (True, 3),
        "03-safe-evolution": (False, 3),
        "04-graphql-required-input": (True, 2),
        "05-response-shape-change": (True, 2),
        "06-status-code-dropped": (True, 2),
        "07-sarif-codescanning": (True, 3),
        "08-graphql-enum-and-args": (True, 3),
        "09-request-body-tightening": (True, 1),
        "10-multitenant-rollout": (True, 4),
    }

    def _pair(self, demo):
        d = os.path.join(DEMOS_DIR, demo)
        olds = [f for f in os.listdir(d) if ".old." in f]
        news = [f for f in os.listdir(d) if ".new." in f]
        self.assertEqual(len(olds), 1, f"{demo}: one .old.* file expected")
        self.assertEqual(len(news), 1, f"{demo}: one .new.* file expected")
        with open(os.path.join(d, olds[0]), encoding="utf-8") as f:
            old = f.read()
        with open(os.path.join(d, news[0]), encoding="utf-8") as f:
            new = f.read()
        return old, new

    def test_every_demo_fires_as_documented(self):
        for demo, (should_break, min_total) in self.EXPECTATIONS.items():
            with self.subTest(demo=demo):
                old, new = self._pair(demo)
                res = diff_files(old, new)
                self.assertEqual(
                    res.has_breaking(), should_break,
                    f"{demo}: breaking expectation mismatch")
                self.assertGreaterEqual(
                    len(res.changes), min_total,
                    f"{demo}: expected >= {min_total} changes")
                # SCENARIO.md must exist for every demo
                self.assertTrue(os.path.exists(
                    os.path.join(DEMOS_DIR, demo, "SCENARIO.md")))


class TestCLI(unittest.TestCase):
    def test_cli_json_and_exit_code(self):
        old = os.path.join(DEMO, "openapi.old.json")
        new = os.path.join(DEMO, "openapi.new.json")
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["diff", old, new, "--format", "json"])
        self.assertEqual(code, 1)  # breaking -> non-zero
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["format"], "openapi")
        self.assertGreater(payload["summary"]["breaking"], 0)

    def test_cli_no_changes_exit_zero(self):
        path = os.path.join(DEMO, "openapi.old.json")
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["diff", path, path, "--format", "json"])
        self.assertEqual(code, 0)

    def test_cli_fail_on_never(self):
        old = os.path.join(DEMO, "openapi.old.json")
        new = os.path.join(DEMO, "openapi.new.json")
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["diff", old, new, "--fail-on", "never"])
        self.assertEqual(code, 0)

    def test_cli_sarif_output(self):
        old = os.path.join(DEMO, "openapi.old.json")
        new = os.path.join(DEMO, "openapi.new.json")
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["diff", old, new, "--format", "sarif"])
        self.assertEqual(code, 1)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["version"], "2.1.0")
        self.assertTrue(payload["runs"][0]["results"])

    def test_cli_missing_command_usage_error(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main([])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
