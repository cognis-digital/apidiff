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
        old = ('{"openapi":"3.0.0","paths":{"/a":{"get":{"responses":{"200":'
               '{"content":{"application/json":{"schema":{"properties":'
               '{"x":{"type":"string"}}}}}}}}}}}')
        new = ('{"openapi":"3.0.0","paths":{"/a":{"get":{"responses":{"200":'
               '{"content":{"application/json":{"schema":{"properties":{}}}}}}}}}}')
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

    def test_cli_missing_command_usage_error(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main([])
        self.assertEqual(code, 2)

    def test_cli_missing_file_exit_2(self):
        """Non-existent input files must produce exit code 2 and a stderr message."""
        err_buf = io.StringIO()
        old_stderr = sys.stderr
        sys.stderr = err_buf
        try:
            code = main(["diff", "/no/such/old.json", "/no/such/new.json"])
        finally:
            sys.stderr = old_stderr
        self.assertEqual(code, 2)
        self.assertIn("error:", err_buf.getvalue())

    def test_cli_malformed_json_exit_2(self):
        """Malformed JSON input must produce exit code 2 and a clear stderr message."""
        import tempfile
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f_old:
            f_old.write('{"openapi": "3.0.0", "paths": {"/a": {"get": {}}}}')
            old_path = f_old.name
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f_new:
            f_new.write("not valid json }{")
            new_path = f_new.name
        try:
            err_buf = io.StringIO()
            old_stderr = sys.stderr
            sys.stderr = err_buf
            try:
                code = main(["diff", old_path, new_path, "--fmt", "openapi"])
            finally:
                sys.stderr = old_stderr
            self.assertEqual(code, 2)
            self.assertIn("error:", err_buf.getvalue())
        finally:
            os.unlink(old_path)
            os.unlink(new_path)


class TestHardeningEdgeCases(unittest.TestCase):
    """Verify hardened error paths in core.py."""

    def test_diff_files_empty_old_raises(self):
        """Empty old_text must raise ValueError, not a cryptic JSONDecodeError."""
        with self.assertRaises(ValueError) as ctx:
            diff_files("", '{"openapi":"3.0.0","paths":{}}', fmt="openapi")
        self.assertIn("empty", str(ctx.exception).lower())

    def test_diff_files_empty_new_raises(self):
        """Empty new_text must raise ValueError."""
        with self.assertRaises(ValueError) as ctx:
            diff_files('{"openapi":"3.0.0","paths":{}}', "   ", fmt="openapi")
        self.assertIn("empty", str(ctx.exception).lower())

    def test_diff_files_non_string_raises(self):
        """Non-string inputs must raise ValueError with a type hint."""
        with self.assertRaises(ValueError) as ctx:
            diff_files(None, '{"openapi":"3.0.0"}', fmt="openapi")
        self.assertIn("str", str(ctx.exception))

    def test_diff_files_unknown_fmt_raises(self):
        """Unknown fmt value must raise ValueError naming the bad value."""
        with self.assertRaises(ValueError) as ctx:
            diff_files(
                '{"openapi":"3.0.0","paths":{}}',
                '{"openapi":"3.0.0","paths":{}}',
                fmt="yaml",
            )
        self.assertIn("yaml", str(ctx.exception))

    def test_mcp_server_importable(self):
        """mcp_server must import without errors (no missing-name ImportError)."""
        import importlib
        mod = importlib.import_module("apidiff.mcp_server")
        self.assertTrue(callable(getattr(mod, "serve", None)))


if __name__ == "__main__":
    unittest.main()
