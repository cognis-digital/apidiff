"""Behavior tests for the additive reporters and CLI surface added in the
deep-expansion series: Markdown output, JUnit XML output, ``--ignore-code``
suppression, ``--output`` file writing, and the shared severity ordering.

Everything runs offline against in-memory fixtures or the bundled demos — no
network access and no active scanning.
"""
import io
import json
import os
import sys
import tempfile
import unittest
import xml.dom.minidom as minidom
from contextlib import redirect_stdout, redirect_stderr

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apidiff.core import (  # noqa: E402
    SEVERITY_ICON,
    SEVERITY_ORDER,
    DiffResult,
    Severity,
    diff_files,
    diff_openapi,
)
from apidiff.cli import build_parser, main  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMOS = os.path.join(ROOT, "demos")
DEMO1 = os.path.join(DEMOS, "01-basic")


def oa(paths):
    return json.dumps({"openapi": "3.0.0", "info": {"title": "t", "version": "1"},
                       "paths": paths})


def breaking_result():
    """A result with BREAKING + INFO changes (from demo 01)."""
    with open(os.path.join(DEMO1, "openapi.old.json"), encoding="utf-8") as f:
        old = f.read()
    with open(os.path.join(DEMO1, "openapi.new.json"), encoding="utf-8") as f:
        new = f.read()
    return diff_files(old, new)


def clean_result():
    doc = oa({"/a": {"get": {"responses": {}}}})
    return diff_openapi(doc, doc)


# ===========================================================================
# Shared severity ordering
# ===========================================================================
class TestSeverityOrder(unittest.TestCase):
    def test_order_is_breaking_first(self):
        self.assertLess(SEVERITY_ORDER[Severity.BREAKING],
                        SEVERITY_ORDER[Severity.WARNING])
        self.assertLess(SEVERITY_ORDER[Severity.WARNING],
                        SEVERITY_ORDER[Severity.INFO])

    def test_every_severity_has_order_and_icon(self):
        for sev in Severity:
            self.assertIn(sev, SEVERITY_ORDER)
            self.assertIn(sev, SEVERITY_ICON)

    def test_sorted_changes_orders_by_severity(self):
        r = breaking_result()
        seq = [SEVERITY_ORDER[c.severity] for c in r.sorted_changes()]
        self.assertEqual(seq, sorted(seq))
        # first entry must be the most severe present
        self.assertEqual(r.sorted_changes()[0].severity, Severity.BREAKING)

    def test_sorted_changes_stable_within_severity(self):
        # two BREAKING changes should keep insertion order
        r = DiffResult(api_format="openapi")
        r.add(Severity.INFO, "c.info", "loc", "info first inserted")
        r.add(Severity.BREAKING, "c.b1", "loc", "b1")
        r.add(Severity.BREAKING, "c.b2", "loc", "b2")
        ordered = r.sorted_changes()
        self.assertEqual([c.code for c in ordered], ["c.b1", "c.b2", "c.info"])


# ===========================================================================
# filtered() — ignore-code core
# ===========================================================================
class TestFiltered(unittest.TestCase):
    def test_filtered_removes_named_codes(self):
        r = breaking_result()
        present = {c.code for c in r.changes}
        self.assertIn("operation.removed", present)
        f = r.filtered(["operation.removed"])
        self.assertNotIn("operation.removed", {c.code for c in f.changes})
        # other codes survive
        self.assertIn("param.added.required", {c.code for c in f.changes})

    def test_filtered_does_not_mutate_original(self):
        r = breaking_result()
        n_before = len(r.changes)
        r.filtered(["operation.removed"])
        self.assertEqual(len(r.changes), n_before)

    def test_filtered_empty_iterable_is_copy(self):
        r = breaking_result()
        for arg in ([], None):
            f = r.filtered(arg)
            self.assertEqual(len(f.changes), len(r.changes))
            self.assertIsNot(f, r)

    def test_filtered_can_clear_all_breaking(self):
        r = breaking_result()
        codes = {c.code for c in r.breaking}
        f = r.filtered(codes)
        self.assertFalse(f.has_breaking())

    def test_filtered_preserves_format(self):
        r = breaking_result()
        self.assertEqual(r.filtered([]).api_format, r.api_format)


# ===========================================================================
# to_markdown()
# ===========================================================================
class TestMarkdown(unittest.TestCase):
    def test_has_verdict_and_counts_table(self):
        md = breaking_result().to_markdown()
        self.assertIn("## API diff", md)
        self.assertIn("Breaking changes detected", md)
        self.assertIn("| Severity | Count |", md)
        self.assertIn("| **Total** | **4** |", md)

    def test_custom_title(self):
        md = breaking_result().to_markdown(title="Contract check")
        self.assertIn("## Contract check", md)

    def test_lists_every_change_row(self):
        r = breaking_result()
        md = r.to_markdown()
        for c in r.changes:
            self.assertIn(f"`{c.code}`", md)

    def test_rows_sorted_breaking_first(self):
        md = breaking_result().to_markdown()
        body = md.split("| Message |", 1)[1]
        first_break = body.find("BREAKING")
        first_info = body.find("INFO")
        self.assertNotEqual(first_break, -1)
        self.assertNotEqual(first_info, -1)
        self.assertLess(first_break, first_info)

    def test_clean_diff_says_no_changes(self):
        md = clean_result().to_markdown()
        self.assertIn("No breaking changes", md)
        self.assertIn("_No changes detected._", md)

    def test_warning_only_verdict(self):
        r = DiffResult(api_format="graphql")
        r.add(Severity.WARNING, "enum.value.added", "Color", "added value")
        md = r.to_markdown()
        self.assertIn("Non-breaking changes (warnings)", md)

    def test_pipe_in_message_is_escaped(self):
        r = DiffResult(api_format="openapi")
        r.add(Severity.INFO, "x.y", "GET /a|b", "message with a | pipe")
        md = r.to_markdown()
        # raw unescaped pipe (surrounded by spaces) must not appear in the row
        self.assertIn("\\|", md)
        self.assertNotIn("a|b", md)

    def test_ends_with_newline(self):
        self.assertTrue(breaking_result().to_markdown().endswith("\n"))


# ===========================================================================
# to_junit()
# ===========================================================================
class TestJUnit(unittest.TestCase):
    def _dom(self, xml):
        return minidom.parseString(xml)

    def test_is_well_formed_xml(self):
        xml = breaking_result().to_junit()
        dom = self._dom(xml)  # raises on malformed XML
        self.assertEqual(dom.documentElement.tagName, "testsuites")

    def test_failures_equal_breaking_count(self):
        r = breaking_result()
        xml = r.to_junit()
        dom = self._dom(xml)
        suites = dom.getElementsByTagName("testsuites")[0]
        self.assertEqual(int(suites.getAttribute("failures")), len(r.breaking))
        self.assertEqual(int(suites.getAttribute("tests")), len(r.changes))

    def test_one_testcase_per_change(self):
        r = breaking_result()
        dom = self._dom(r.to_junit())
        self.assertEqual(len(dom.getElementsByTagName("testcase")), len(r.changes))

    def test_breaking_changes_are_failures(self):
        r = breaking_result()
        dom = self._dom(r.to_junit())
        failures = dom.getElementsByTagName("failure")
        self.assertEqual(len(failures), len(r.breaking))
        for f in failures:
            self.assertEqual(f.getAttribute("type"), "BREAKING")

    def test_non_breaking_recorded_as_system_out(self):
        r = DiffResult(api_format="openapi")
        r.add(Severity.INFO, "path.added", "/x", "added")
        dom = self._dom(r.to_junit())
        self.assertEqual(len(dom.getElementsByTagName("failure")), 0)
        self.assertEqual(len(dom.getElementsByTagName("system-out")), 1)

    def test_empty_diff_single_passing_case(self):
        xml = clean_result().to_junit()
        dom = self._dom(xml)
        cases = dom.getElementsByTagName("testcase")
        self.assertEqual(len(cases), 1)
        self.assertEqual(len(dom.getElementsByTagName("failure")), 0)
        suites = dom.getElementsByTagName("testsuites")[0]
        self.assertEqual(int(suites.getAttribute("failures")), 0)

    def test_special_chars_escaped(self):
        r = DiffResult(api_format="openapi")
        r.add(Severity.BREAKING, "op.removed", "GET /a<b>&c", 'msg "x" < y & z')
        xml = r.to_junit()
        # must still parse cleanly despite <, >, &, quotes
        dom = self._dom(xml)
        self.assertEqual(len(dom.getElementsByTagName("failure")), 1)

    def test_suite_name_used(self):
        xml = breaking_result().to_junit("custom-suite")
        self.assertIn('name="custom-suite"', xml)


# ===========================================================================
# CLI wiring for the new options
# ===========================================================================
class TestCLINewFormats(unittest.TestCase):
    def _paths(self):
        return (os.path.join(DEMO1, "openapi.old.json"),
                os.path.join(DEMO1, "openapi.new.json"))

    def test_parser_accepts_new_formats(self):
        p = build_parser()
        for fmt in ("markdown", "junit"):
            args = p.parse_args(["diff", "a", "b", "--format", fmt])
            self.assertEqual(args.format, fmt)

    def test_parser_ignore_code_is_repeatable(self):
        p = build_parser()
        args = p.parse_args(
            ["diff", "a", "b", "--ignore-code", "x", "--ignore-code", "y"])
        self.assertEqual(args.ignore_code, ["x", "y"])

    def test_cli_markdown_output(self):
        old, new = self._paths()
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["diff", old, new, "--format", "markdown"])
        self.assertEqual(code, 1)
        out = buf.getvalue()
        self.assertIn("## API diff", out)
        self.assertIn("Breaking changes detected", out)

    def test_cli_junit_output(self):
        old, new = self._paths()
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["diff", old, new, "--format", "junit"])
        self.assertEqual(code, 1)
        dom = minidom.parseString(buf.getvalue())
        self.assertEqual(dom.documentElement.tagName, "testsuites")

    def test_cli_ignore_code_changes_exit(self):
        old, new = self._paths()
        # suppress every breaking code -> clean exit
        r = breaking_result()
        args = ["diff", old, new, "--format", "json"]
        for code in {c.code for c in r.breaking}:
            args += ["--ignore-code", code]
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(args)
        self.assertEqual(rc, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["summary"]["breaking"], 0)

    def test_cli_ignore_code_still_reports_survivors(self):
        old, new = self._paths()
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["diff", old, new, "--format", "json",
                       "--ignore-code", "operation.removed"])
        self.assertEqual(rc, 1)  # other breaking codes remain
        payload = json.loads(buf.getvalue())
        codes = {c["code"] for c in payload["changes"]}
        self.assertNotIn("operation.removed", codes)

    def test_cli_output_writes_file(self):
        old, new = self._paths()
        with tempfile.TemporaryDirectory() as td:
            out = os.path.join(td, "report.md")
            code = main(["diff", old, new, "--format", "markdown", "-o", out])
            self.assertEqual(code, 1)
            with open(out, encoding="utf-8") as fh:
                content = fh.read()
            self.assertIn("## API diff", content)
            self.assertTrue(content.endswith("\n"))

    def test_cli_output_junit_file_is_valid_xml(self):
        old, new = self._paths()
        with tempfile.TemporaryDirectory() as td:
            out = os.path.join(td, "report.xml")
            main(["diff", old, new, "--format", "junit", "--output", out])
            dom = minidom.parse(out)
            self.assertEqual(dom.documentElement.tagName, "testsuites")

    def test_cli_output_bad_path_errors(self):
        old, new = self._paths()
        bad = os.path.join(old, "nope", "cannot", "write.md")  # under a file
        buf = io.StringIO()
        with redirect_stderr(buf):
            code = main(["diff", old, new, "--format", "markdown", "-o", bad])
        self.assertEqual(code, 2)
        self.assertIn("error:", buf.getvalue())


# ===========================================================================
# Cross-format consistency across all demos
# ===========================================================================
class TestRenderersAcrossDemos(unittest.TestCase):
    def _pairs(self):
        for demo in sorted(os.listdir(DEMOS)):
            d = os.path.join(DEMOS, demo)
            if not os.path.isdir(d):
                continue
            olds = [f for f in os.listdir(d) if ".old." in f]
            news = [f for f in os.listdir(d) if ".new." in f]
            if not olds or not news:
                continue
            with open(os.path.join(d, olds[0]), encoding="utf-8") as f:
                old = f.read()
            with open(os.path.join(d, news[0]), encoding="utf-8") as f:
                new = f.read()
            yield demo, diff_files(old, new)

    def test_markdown_and_junit_render_for_every_demo(self):
        seen = 0
        for demo, res in self._pairs():
            seen += 1
            with self.subTest(demo=demo):
                md = res.to_markdown()
                self.assertIn("| Severity | Count |", md)
                # JUnit must always be well-formed XML
                dom = minidom.parseString(res.to_junit())
                failures = int(
                    dom.getElementsByTagName("testsuites")[0].getAttribute("failures"))
                self.assertEqual(failures, len(res.breaking))
        self.assertGreaterEqual(seen, 10)


if __name__ == "__main__":
    unittest.main()
