"""Comprehensive behavior tests for the apidiff engine (stdlib unittest).

These tests are exhaustive over the change taxonomy and severity model, the
SARIF renderer, format detection, the GraphQL subset parser, the convenience
API (scan/to_json/diff_paths), and the CLI. Everything runs offline against
in-memory fixtures or the bundled demos — no network, no active scanning.
"""
import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout, redirect_stderr

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apidiff import TOOL_NAME, TOOL_VERSION  # noqa: E402
from apidiff.core import (  # noqa: E402
    Change,
    DiffResult,
    Severity,
    detect_format,
    diff_files,
    diff_graphql,
    diff_openapi,
    diff_paths,
    scan,
    to_json,
)
from apidiff.cli import build_parser, main  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMOS = os.path.join(ROOT, "demos")


def oa(paths):
    """Build a minimal OpenAPI doc string from a paths dict."""
    return json.dumps({"openapi": "3.0.0", "info": {"title": "t", "version": "1"},
                       "paths": paths})


def codes(result):
    return {c.code for c in result.changes}


def sev_of(result, code):
    for c in result.changes:
        if c.code == code:
            return c.severity
    return None


# ===========================================================================
# Identity & VERSION
# ===========================================================================
class TestIdentity(unittest.TestCase):
    def test_tool_name(self):
        self.assertEqual(TOOL_NAME, "apidiff")

    def test_version_nonempty(self):
        self.assertTrue(TOOL_VERSION)

    def test_version_matches_version_file(self):
        with open(os.path.join(ROOT, "VERSION"), encoding="utf-8") as fh:
            self.assertEqual(TOOL_VERSION, fh.read().strip())

    def test_version_is_semverish(self):
        parts = TOOL_VERSION.split(".")
        self.assertGreaterEqual(len(parts), 2)
        self.assertTrue(parts[0].isdigit())


# ===========================================================================
# Format detection
# ===========================================================================
class TestDetect(unittest.TestCase):
    def test_openapi_3(self):
        self.assertEqual(detect_format('{"openapi":"3.0.0","paths":{}}'), "openapi")

    def test_swagger_2(self):
        self.assertEqual(detect_format('{"swagger":"2.0","paths":{}}'), "openapi")

    def test_graphql_type(self):
        self.assertEqual(detect_format("type Query { hello: String }"), "graphql")

    def test_graphql_input(self):
        self.assertEqual(detect_format("input Filter { q: String }"), "graphql")

    def test_graphql_enum(self):
        self.assertEqual(detect_format("enum Color { RED }"), "graphql")

    def test_graphql_interface(self):
        self.assertEqual(detect_format("interface Node { id: ID! }"), "graphql")

    def test_graphql_union(self):
        self.assertEqual(detect_format("union Pet = Cat | Dog"), "graphql")

    def test_leading_whitespace_openapi(self):
        self.assertEqual(detect_format('   \n  {"openapi":"3.0.0"}'), "openapi")

    def test_non_json_non_keyword_defaults_graphql(self):
        self.assertEqual(detect_format("scalar DateTime"), "graphql")

    def test_invalid_json_object_falls_back(self):
        # starts with { but not valid JSON and no gql keyword -> openapi fallback
        self.assertEqual(detect_format("{ this is not json"), "openapi")


# ===========================================================================
# OpenAPI — paths & operations
# ===========================================================================
class TestOpenAPIPaths(unittest.TestCase):
    def test_removed_path_breaking(self):
        r = diff_openapi(oa({"/a": {"get": {"responses": {}}}}), oa({}))
        self.assertIn("path.removed", codes(r))
        self.assertEqual(sev_of(r, "path.removed"), Severity.BREAKING)

    def test_added_path_info(self):
        r = diff_openapi(oa({}), oa({"/a": {"get": {"responses": {}}}}))
        self.assertIn("path.added", codes(r))
        self.assertEqual(sev_of(r, "path.added"), Severity.INFO)
        self.assertFalse(r.has_breaking())

    def test_removed_operation_breaking(self):
        old = oa({"/a": {"get": {"responses": {}}, "post": {"responses": {}}}})
        new = oa({"/a": {"get": {"responses": {}}}})
        r = diff_openapi(old, new)
        self.assertIn("operation.removed", codes(r))
        self.assertEqual(sev_of(r, "operation.removed"), Severity.BREAKING)

    def test_added_operation_info(self):
        old = oa({"/a": {"get": {"responses": {}}}})
        new = oa({"/a": {"get": {"responses": {}}, "post": {"responses": {}}}})
        r = diff_openapi(old, new)
        self.assertIn("operation.added", codes(r))
        self.assertEqual(sev_of(r, "operation.added"), Severity.INFO)
        self.assertFalse(r.has_breaking())

    def test_identical_no_changes(self):
        doc = oa({"/a": {"get": {"responses": {}}}})
        self.assertEqual(len(diff_openapi(doc, doc).changes), 0)

    def test_empty_to_empty(self):
        self.assertEqual(len(diff_openapi(oa({}), oa({})).changes), 0)

    def test_all_methods_detected(self):
        for m in ("get", "put", "post", "delete", "patch", "head", "options"):
            old = oa({"/a": {m: {"responses": {}}}})
            new = oa({"/a": {}})
            r = diff_openapi(old, new)
            self.assertIn("operation.removed", codes(r), f"method {m}")


# ===========================================================================
# OpenAPI — parameters
# ===========================================================================
def op_with_params(params):
    return oa({"/a": {"get": {"parameters": params, "responses": {}}}})


class TestOpenAPIParams(unittest.TestCase):
    def test_new_required_param_breaking(self):
        r = diff_openapi(op_with_params([]),
                         op_with_params([{"name": "q", "in": "query", "required": True}]))
        self.assertEqual(sev_of(r, "param.added.required"), Severity.BREAKING)

    def test_new_optional_param_info(self):
        r = diff_openapi(op_with_params([]),
                         op_with_params([{"name": "q", "in": "query", "required": False}]))
        self.assertEqual(sev_of(r, "param.added"), Severity.INFO)
        self.assertFalse(r.has_breaking())

    def test_param_became_required_breaking(self):
        old = op_with_params([{"name": "q", "in": "query", "required": False}])
        new = op_with_params([{"name": "q", "in": "query", "required": True}])
        r = diff_openapi(old, new)
        self.assertEqual(sev_of(r, "param.required.added"), Severity.BREAKING)

    def test_param_became_optional_info(self):
        old = op_with_params([{"name": "q", "in": "query", "required": True}])
        new = op_with_params([{"name": "q", "in": "query", "required": False}])
        r = diff_openapi(old, new)
        self.assertEqual(sev_of(r, "param.required.removed"), Severity.INFO)
        self.assertFalse(r.has_breaking())

    def test_removed_param_warning(self):
        old = op_with_params([{"name": "q", "in": "query"}])
        new = op_with_params([])
        r = diff_openapi(old, new)
        self.assertEqual(sev_of(r, "param.removed"), Severity.WARNING)

    def test_same_name_different_location_is_distinct(self):
        old = op_with_params([{"name": "id", "in": "query"}])
        new = op_with_params([{"name": "id", "in": "path", "required": True}])
        r = diff_openapi(old, new)
        # query 'id' removed (warning) AND path 'id' added required (breaking)
        self.assertIn("param.removed", codes(r))
        self.assertIn("param.added.required", codes(r))

    def test_param_default_location_is_query(self):
        old = op_with_params([{"name": "q"}])  # no "in"
        new = op_with_params([])
        r = diff_openapi(old, new)
        msg = next(c.message for c in r.changes if c.code == "param.removed")
        self.assertIn("in: query", msg)


# ===========================================================================
# OpenAPI — request body
# ===========================================================================
def op_with_body(schema):
    return oa({"/a": {"post": {
        "requestBody": {"content": {"application/json": {"schema": schema}}},
        "responses": {}}}})


class TestOpenAPIRequestBody(unittest.TestCase):
    def test_new_required_field_breaking(self):
        old = op_with_body({"required": [], "properties": {"name": {"type": "string"}}})
        new = op_with_body({"required": ["name"], "properties": {"name": {"type": "string"}}})
        r = diff_openapi(old, new)
        self.assertEqual(sev_of(r, "requestBody.required.added"), Severity.BREAKING)

    def test_relaxed_required_field_info(self):
        old = op_with_body({"required": ["name"], "properties": {"name": {"type": "string"}}})
        new = op_with_body({"required": [], "properties": {"name": {"type": "string"}}})
        r = diff_openapi(old, new)
        self.assertEqual(sev_of(r, "requestBody.required.removed"), Severity.INFO)
        self.assertFalse(r.has_breaking())

    def test_removed_body_property_is_warning_not_breaking(self):
        # request body property removal does not break readers -> warning
        old = op_with_body({"properties": {"a": {"type": "string"}}})
        new = op_with_body({"properties": {}})
        r = diff_openapi(old, new)
        self.assertEqual(sev_of(r, "requestBody.property.removed"), Severity.WARNING)

    def test_body_property_type_change_breaking(self):
        old = op_with_body({"properties": {"a": {"type": "string"}}})
        new = op_with_body({"properties": {"a": {"type": "integer"}}})
        r = diff_openapi(old, new)
        self.assertEqual(sev_of(r, "requestBody.property.type.changed"), Severity.BREAKING)

    def test_added_body_property_info(self):
        old = op_with_body({"properties": {"a": {"type": "string"}}})
        new = op_with_body({"properties": {"a": {"type": "string"}, "b": {"type": "string"}}})
        r = diff_openapi(old, new)
        self.assertEqual(sev_of(r, "requestBody.property.added"), Severity.INFO)


# ===========================================================================
# OpenAPI — responses
# ===========================================================================
def op_with_response(code, schema=None, extra=None):
    resp = {}
    if schema is not None:
        resp = {"content": {"application/json": {"schema": schema}}}
    responses = {code: resp}
    if extra:
        responses.update(extra)
    return oa({"/a": {"get": {"responses": responses}}})


class TestOpenAPIResponses(unittest.TestCase):
    def test_removed_response_property_breaking(self):
        old = op_with_response("200", {"properties": {"x": {"type": "string"}}})
        new = op_with_response("200", {"properties": {}})
        r = diff_openapi(old, new)
        self.assertEqual(sev_of(r, "response.property.removed"), Severity.BREAKING)

    def test_response_property_type_change_breaking(self):
        old = op_with_response("200", {"properties": {"x": {"type": "string"}}})
        new = op_with_response("200", {"properties": {"x": {"type": "integer"}}})
        r = diff_openapi(old, new)
        self.assertEqual(sev_of(r, "response.property.type.changed"), Severity.BREAKING)

    def test_added_response_property_info(self):
        old = op_with_response("200", {"properties": {"x": {"type": "string"}}})
        new = op_with_response("200", {"properties": {"x": {"type": "string"}, "y": {"type": "string"}}})
        r = diff_openapi(old, new)
        self.assertEqual(sev_of(r, "response.property.added"), Severity.INFO)

    def test_dropped_2xx_status_breaking(self):
        old = oa({"/a": {"get": {"responses": {"200": {}, "206": {}}}}})
        new = oa({"/a": {"get": {"responses": {"200": {}}}}})
        r = diff_openapi(old, new)
        self.assertEqual(sev_of(r, "response.removed"), Severity.BREAKING)

    def test_dropped_4xx_not_breaking(self):
        old = oa({"/a": {"get": {"responses": {"200": {}, "404": {}}}}})
        new = oa({"/a": {"get": {"responses": {"200": {}}}}})
        r = diff_openapi(old, new)
        self.assertNotIn("response.removed", codes(r))
        self.assertFalse(r.has_breaking())


# ===========================================================================
# GraphQL — types, fields, enums, args
# ===========================================================================
class TestGraphQLTypes(unittest.TestCase):
    def test_removed_type_breaking(self):
        r = diff_graphql("type A { x: Int } type B { y: Int }", "type A { x: Int }")
        self.assertEqual(sev_of(r, "type.removed"), Severity.BREAKING)

    def test_added_type_info(self):
        r = diff_graphql("type A { x: Int }", "type A { x: Int } type B { y: Int }")
        self.assertEqual(sev_of(r, "type.added"), Severity.INFO)
        self.assertFalse(r.has_breaking())

    def test_kind_change_breaking(self):
        r = diff_graphql("type A { x: Int }", "input A { x: Int }")
        self.assertEqual(sev_of(r, "type.kind.changed"), Severity.BREAKING)

    def test_removed_field_breaking(self):
        r = diff_graphql("type U { id: ID! name: String }", "type U { id: ID! }")
        self.assertEqual(sev_of(r, "field.removed"), Severity.BREAKING)

    def test_added_field_info(self):
        r = diff_graphql("type U { id: ID! }", "type U { id: ID! name: String }")
        self.assertEqual(sev_of(r, "field.added"), Severity.INFO)
        self.assertFalse(r.has_breaking())


class TestGraphQLNullability(unittest.TestCase):
    def test_output_required_to_optional_breaking(self):
        # readers expect non-null -> loosening breaks them
        r = diff_graphql("type U { name: String! }", "type U { name: String }")
        self.assertEqual(sev_of(r, "field.type.changed"), Severity.BREAKING)

    def test_output_optional_to_required_info(self):
        r = diff_graphql("type U { name: String }", "type U { name: String! }")
        self.assertEqual(sev_of(r, "field.type.changed"), Severity.INFO)
        self.assertFalse(r.has_breaking())

    def test_input_optional_to_required_breaking(self):
        r = diff_graphql("input F { name: String }", "input F { name: String! }")
        self.assertEqual(sev_of(r, "field.type.changed"), Severity.BREAKING)

    def test_base_type_change_breaking(self):
        r = diff_graphql("type U { x: Int }", "type U { x: String }")
        self.assertEqual(sev_of(r, "field.type.changed"), Severity.BREAKING)

    def test_new_required_input_field_breaking(self):
        r = diff_graphql("input F { name: String }",
                         "input F { name: String region: String! }")
        self.assertEqual(sev_of(r, "input.field.added.required"), Severity.BREAKING)

    def test_new_optional_input_field_info(self):
        r = diff_graphql("input F { name: String }",
                         "input F { name: String region: String }")
        self.assertEqual(sev_of(r, "field.added"), Severity.INFO)
        self.assertFalse(r.has_breaking())


class TestGraphQLEnums(unittest.TestCase):
    def test_removed_enum_value_breaking(self):
        r = diff_graphql("enum C { RED GREEN BLUE }", "enum C { RED GREEN }")
        self.assertEqual(sev_of(r, "enum.value.removed"), Severity.BREAKING)

    def test_added_enum_value_warning(self):
        r = diff_graphql("enum C { RED GREEN }", "enum C { RED GREEN BLUE }")
        self.assertEqual(sev_of(r, "enum.value.added"), Severity.WARNING)
        self.assertFalse(r.has_breaking())

    def test_enum_unchanged_no_changes(self):
        r = diff_graphql("enum C { RED GREEN }", "enum C { RED GREEN }")
        self.assertEqual(len(r.changes), 0)


class TestGraphQLArgs(unittest.TestCase):
    def test_removed_arg_breaking(self):
        r = diff_graphql("type Q { pets(first: Int): [String] }",
                         "type Q { pets: [String] }")
        self.assertEqual(sev_of(r, "arg.removed"), Severity.BREAKING)

    def test_new_required_arg_breaking(self):
        r = diff_graphql("type Q { pets: [String] }",
                         "type Q { pets(first: Int!): [String] }")
        self.assertEqual(sev_of(r, "arg.added.required"), Severity.BREAKING)

    def test_new_optional_arg_info(self):
        r = diff_graphql("type Q { pets: [String] }",
                         "type Q { pets(first: Int): [String] }")
        self.assertEqual(sev_of(r, "arg.added"), Severity.INFO)
        self.assertFalse(r.has_breaking())

    def test_arg_became_required_breaking(self):
        r = diff_graphql("type Q { pets(first: Int): [String] }",
                         "type Q { pets(first: Int!): [String] }")
        self.assertEqual(sev_of(r, "arg.required.added"), Severity.BREAKING)

    def test_arg_type_change_warning(self):
        r = diff_graphql("type Q { pets(first: Int): [String] }",
                         "type Q { pets(first: String): [String] }")
        self.assertEqual(sev_of(r, "arg.type.changed"), Severity.WARNING)


class TestGraphQLParser(unittest.TestCase):
    def test_comments_stripped(self):
        old = "# a comment\ntype U { id: ID! }"
        new = "type U { id: ID! }"
        self.assertEqual(len(diff_graphql(old, new).changes), 0)

    def test_union_parsed_as_type(self):
        r = diff_graphql("union P = A | B\ntype A{x:Int}\ntype B{y:Int}",
                         "type A{x:Int}\ntype B{y:Int}")
        self.assertEqual(sev_of(r, "type.removed"), Severity.BREAKING)

    def test_list_types_preserved(self):
        # changing [String] -> [Int] is a base-type change (breaking)
        r = diff_graphql("type U { tags: [String] }", "type U { tags: [Int] }")
        self.assertEqual(sev_of(r, "field.type.changed"), Severity.BREAKING)


# ===========================================================================
# DiffResult / SARIF / JSON
# ===========================================================================
class TestDiffResultModel(unittest.TestCase):
    def _mixed(self):
        r = DiffResult(api_format="openapi")
        r.add(Severity.BREAKING, "x.removed", "GET /a", "removed")
        r.add(Severity.WARNING, "x.warn", "GET /a", "warn")
        r.add(Severity.INFO, "x.info", "GET /a", "info")
        return r

    def test_breaking_property(self):
        self.assertEqual(len(self._mixed().breaking), 1)

    def test_warnings_property(self):
        self.assertEqual(len(self._mixed().warnings), 1)

    def test_has_breaking(self):
        self.assertTrue(self._mixed().has_breaking())

    def test_summary_counts(self):
        d = self._mixed().to_dict()
        self.assertEqual(d["summary"]["total"], 3)
        self.assertEqual(d["summary"]["breaking"], 1)
        self.assertEqual(d["summary"]["warning"], 1)
        self.assertEqual(d["summary"]["info"], 1)

    def test_to_dict_changes_serializable(self):
        d = self._mixed().to_dict()
        json.dumps(d)  # must not raise
        self.assertEqual(d["changes"][0]["severity"], "BREAKING")

    def test_change_to_dict(self):
        c = Change(Severity.INFO, "c", "loc", "msg").to_dict()
        self.assertEqual(c["severity"], "INFO")
        self.assertEqual(c["code"], "c")


class TestSarif(unittest.TestCase):
    def _result(self):
        return diff_paths(os.path.join(DEMOS, "01-basic", "openapi.old.json"),
                          os.path.join(DEMOS, "01-basic", "openapi.new.json"))

    def test_version(self):
        self.assertEqual(self._result().to_sarif()["version"], "2.1.0")

    def test_schema_present(self):
        self.assertIn("schema", str(self._result().to_sarif()["$schema"]).lower() or "")

    def test_driver_name_and_version(self):
        d = self._result().to_sarif("apidiff", "9.9.9")["runs"][0]["tool"]["driver"]
        self.assertEqual(d["name"], "apidiff")
        self.assertEqual(d["version"], "9.9.9")

    def test_results_reference_existing_rules(self):
        run = self._result().to_sarif()["runs"][0]
        rule_ids = {r["id"] for r in run["tool"]["driver"]["rules"]}
        for res in run["results"]:
            self.assertIn(res["ruleId"], rule_ids)
            self.assertEqual(
                run["tool"]["driver"]["rules"][res["ruleIndex"]]["id"], res["ruleId"])

    def test_levels_subset(self):
        run = self._result().to_sarif()["runs"][0]
        levels = {r["level"] for r in run["results"]}
        self.assertTrue(levels <= {"error", "warning", "note"})
        self.assertIn("error", levels)  # demo 01 has breaking changes

    def test_empty_diff_no_results(self):
        r = diff_files(oa({}), oa({}))
        s = r.to_sarif()
        self.assertEqual(s["runs"][0]["results"], [])
        self.assertEqual(s["runs"][0]["tool"]["driver"]["rules"], [])

    def test_breaking_maps_to_error(self):
        r = DiffResult(api_format="openapi")
        r.add(Severity.BREAKING, "x", "loc", "m")
        self.assertEqual(r.to_sarif()["runs"][0]["results"][0]["level"], "error")

    def test_warning_maps_to_warning(self):
        r = DiffResult(api_format="openapi")
        r.add(Severity.WARNING, "x", "loc", "m")
        self.assertEqual(r.to_sarif()["runs"][0]["results"][0]["level"], "warning")

    def test_info_maps_to_note(self):
        r = DiffResult(api_format="openapi")
        r.add(Severity.INFO, "x", "loc", "m")
        self.assertEqual(r.to_sarif()["runs"][0]["results"][0]["level"], "note")


# ===========================================================================
# Convenience API: scan / to_json / diff_paths / diff_files
# ===========================================================================
class TestConvenienceAPI(unittest.TestCase):
    def test_diff_files_autodetect_graphql(self):
        r = diff_files("type A { x: Int }", "type A { }")
        self.assertEqual(r.api_format, "graphql")
        self.assertTrue(r.has_breaking())

    def test_diff_files_autodetect_openapi(self):
        r = diff_files(oa({"/a": {"get": {"responses": {}}}}), oa({}))
        self.assertEqual(r.api_format, "openapi")

    def test_diff_files_explicit_format(self):
        r = diff_files("type A { x: Int }", "type A { }", fmt="graphql")
        self.assertEqual(r.api_format, "graphql")

    def test_diff_files_unknown_format_raises(self):
        with self.assertRaises(ValueError):
            diff_files("x", "y", fmt="protobuf")

    def test_scan_returns_dict(self):
        out = scan(os.path.join(DEMOS, "01-basic", "openapi.old.json"),
                   os.path.join(DEMOS, "01-basic", "openapi.new.json"))
        self.assertIn("summary", out)
        self.assertGreater(out["summary"]["breaking"], 0)

    def test_scan_clean_pair(self):
        p = os.path.join(DEMOS, "01-basic", "openapi.old.json")
        out = scan(p, p)
        self.assertEqual(out["summary"]["breaking"], 0)

    def test_to_json_roundtrip(self):
        out = scan(os.path.join(DEMOS, "01-basic", "openapi.old.json"),
                   os.path.join(DEMOS, "01-basic", "openapi.new.json"))
        s = to_json(out)
        self.assertEqual(json.loads(s)["summary"], out["summary"])

    def test_diff_paths_reads_files(self):
        r = diff_paths(os.path.join(DEMOS, "02-graphql-schema", "schema.old.graphql"),
                       os.path.join(DEMOS, "02-graphql-schema", "schema.new.graphql"))
        self.assertEqual(r.api_format, "graphql")


# ===========================================================================
# Demos — every bundled scenario behaves as documented
# ===========================================================================
class TestAllDemos(unittest.TestCase):
    EXPECT = {
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
        d = os.path.join(DEMOS, demo)
        old = next(f for f in os.listdir(d) if ".old." in f)
        new = next(f for f in os.listdir(d) if ".new." in f)
        with open(os.path.join(d, old), encoding="utf-8") as f:
            o = f.read()
        with open(os.path.join(d, new), encoding="utf-8") as f:
            n = f.read()
        return o, n

    def test_every_demo(self):
        for demo, (should_break, min_total) in self.EXPECT.items():
            with self.subTest(demo=demo):
                o, n = self._pair(demo)
                r = diff_files(o, n)
                self.assertEqual(r.has_breaking(), should_break)
                self.assertGreaterEqual(len(r.changes), min_total)

    def test_every_demo_has_scenario(self):
        for demo in self.EXPECT:
            with self.subTest(demo=demo):
                self.assertTrue(os.path.exists(os.path.join(DEMOS, demo, "SCENARIO.md")))

    def test_demo_count(self):
        dirs = [d for d in os.listdir(DEMOS)
                if os.path.isdir(os.path.join(DEMOS, d))]
        self.assertEqual(len(dirs), len(self.EXPECT))


# ===========================================================================
# CLI
# ===========================================================================
class TestCLI(unittest.TestCase):
    OLD = os.path.join(DEMOS, "01-basic", "openapi.old.json")
    NEW = os.path.join(DEMOS, "01-basic", "openapi.new.json")

    def _run(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_parser_builds(self):
        self.assertIsNotNone(build_parser())

    def test_json_exit_one_on_breaking(self):
        code, out, _ = self._run(["diff", self.OLD, self.NEW, "--format", "json"])
        self.assertEqual(code, 1)
        self.assertGreater(json.loads(out)["summary"]["breaking"], 0)

    def test_no_changes_exit_zero(self):
        code, _, _ = self._run(["diff", self.OLD, self.OLD, "--format", "json"])
        self.assertEqual(code, 0)

    def test_fail_on_never(self):
        code, _, _ = self._run(["diff", self.OLD, self.NEW, "--fail-on", "never"])
        self.assertEqual(code, 0)

    def test_fail_on_warning_with_warning_only(self):
        # craft a warning-only diff via temp files
        import tempfile
        old = op_with_params([{"name": "q", "in": "query"}])
        new = op_with_params([])  # removed param -> WARNING only
        with tempfile.TemporaryDirectory() as td:
            op, npth = os.path.join(td, "o.json"), os.path.join(td, "n.json")
            with open(op, "w") as f:
                f.write(old)
            with open(npth, "w") as f:
                f.write(new)
            code, _, _ = self._run(["diff", op, npth, "--fail-on", "warning"])
            self.assertEqual(code, 1)
            code2, _, _ = self._run(["diff", op, npth, "--fail-on", "breaking"])
            self.assertEqual(code2, 0)

    def test_table_output(self):
        code, out, _ = self._run(["diff", self.OLD, self.NEW])
        self.assertEqual(code, 1)
        self.assertIn("BREAKING", out)
        self.assertIn("format: openapi", out)

    def test_table_no_changes_message(self):
        code, out, _ = self._run(["diff", self.OLD, self.OLD])
        self.assertIn("No changes detected.", out)

    def test_sarif_output(self):
        code, out, _ = self._run(["diff", self.OLD, self.NEW, "--format", "sarif"])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out)["version"], "2.1.0")

    def test_missing_command_usage_error(self):
        code, _, _ = self._run([])
        self.assertEqual(code, 2)

    def test_io_error_returns_two(self):
        code, _, err = self._run(["diff", "does-not-exist.json", self.NEW])
        self.assertEqual(code, 2)
        self.assertIn("error", err)

    def test_bad_json_returns_two(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            bad = os.path.join(td, "bad.json")
            with open(bad, "w") as f:
                f.write("{ not json")
            code, _, err = self._run(["diff", bad, bad, "--fmt", "openapi"])
            self.assertEqual(code, 2)

    def test_explicit_graphql_fmt(self):
        gold = os.path.join(DEMOS, "02-graphql-schema", "schema.old.graphql")
        gnew = os.path.join(DEMOS, "02-graphql-schema", "schema.new.graphql")
        code, out, _ = self._run(["diff", gold, gnew, "--fmt", "graphql", "--format", "json"])
        self.assertEqual(json.loads(out)["format"], "graphql")

    def test_mcp_subcommand_registered(self):
        # The 'mcp' subcommand parses; without the extra installed it returns 1.
        parser = build_parser()
        args = parser.parse_args(["mcp"])
        self.assertEqual(args.command, "mcp")


if __name__ == "__main__":
    unittest.main()
