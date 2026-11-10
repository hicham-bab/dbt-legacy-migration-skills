#!/usr/bin/env python3
"""Regression tests for lint_idiomatic.py (stdlib unittest, projects built in a temp dir).

Run:  python3 test_lint_idiomatic.py

Covers the `nondeterministic_order` rule: a window ordered only by a constant
(`order by 0`, `order by 1`, `order by null`) numbers rows arbitrarily, so a key built from it
changes between runs. Seen in a real METL export as `row_number() over (order by 0)`.
"""
from __future__ import annotations
import tempfile
import unittest
from pathlib import Path

import lint_idiomatic as lint


class NondeterministicOrder(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "models").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def flagged(self, sql: str) -> bool:
        (self.root / "models" / "m.sql").write_text(sql)
        report = lint.lint(self.root)
        return any(f["check"] == "nondeterministic_order" for f in report["findings"])

    def test_constant_orders_are_flagged(self):
        for sql in (
            "select row_number() over (order by 0) as k from {{ ref('x') }}",
            "select row_number() over (order by 1) as k from {{ ref('x') }}",
            "select row_number() over (order by null) as k from {{ ref('x') }}",
            "select row_number() over (partition by h order by null) as k from {{ ref('x') }}",
            "select rank() over (order by 10 desc) as k from {{ ref('x') }}",
            "select ROW_NUMBER() OVER (ORDER BY 0) as k from {{ ref('x') }}",
        ):
            with self.subTest(sql=sql):
                self.assertTrue(self.flagged(sql))

    def test_real_sort_keys_are_not_flagged(self):
        for sql in (
            "select row_number() over (partition by h order by h) as k from {{ ref('x') }}",
            "select row_number() over (order by loaded_at, id) as k from {{ ref('x') }}",
            "select row_number() over (order by col_1) as k from {{ ref('x') }}",
            "select * from {{ ref('x') }} order by 1",   # a query sort, not a window
        ):
            with self.subTest(sql=sql):
                self.assertFalse(self.flagged(sql))

    def test_commented_out_legacy_code_is_ignored(self):
        self.assertFalse(self.flagged(
            "-- legacy: row_number() over (order by 0)\n"
            "select row_number() over (partition by h order by h) as k from {{ ref('x') }}"))

    def test_rule_is_a_warning_not_an_error(self):
        (self.root / "models" / "m.sql").write_text(
            "select row_number() over (order by 0) as k from {{ ref('x') }}")
        report = lint.lint(self.root)
        self.assertEqual(report["summary"]["errors"], 0)
        self.assertEqual(report["summary"]["warnings"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
