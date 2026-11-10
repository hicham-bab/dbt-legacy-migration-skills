#!/usr/bin/env python3
"""Regression tests for preflight_decisions.py (stdlib unittest, fixtures built in a temp dir).

Run:  python3 test_preflight_decisions.py

Covers the checks added after a real METL run surfaced them:
  * inputs.test_source_mode: enum, test_source_schemas required for existing_tables,
    and seeds passing with a "fabricated data only" warning.
  * inventory gate: a suspected Shared Job requires shared_job_bundles_path to be
    answered (null only together with a residual_disposition).
  * parity gate: a rebuild_stability record with two identical runs is required.
  * tests gate: advisory test-floor check over target/manifest.json.
"""
from __future__ import annotations
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import preflight_decisions as pf

MANIFEST = """\
schema_version: 1
provenance:
  answered_by: migrator@example.com
  answered_at: 2026-11-10T00:00:00Z
  method: interactive
decisions:
  target_modeling: layered
  data_warehouse: snowflake
  packages_mode: external_hub
  landing_spot: /tmp/project
  landing_mode: new_standalone
  dbt_runtime: fusion
  parity_scope: all_marts
  contract_boundary: all_marts
  residual_disposition: {residual}
inputs:
  legacy_export_path: /tmp/export.json
{inputs}
access:
  legacy_prod_readable: false
  metering_views_readable: false
  warehouse_catalog_readable: true
"""


def run(fn, *args):
    """Call a gate; return (exit_code, output). fail() exits via SystemExit."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            code = fn(*args)
        except SystemExit as e:
            code = e.code
    return code, buf.getvalue()


class PreflightRegression(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def manifest(self, inputs="", residual="null") -> Path:
        p = self.d / "migration_manifest.yml"
        p.write_text(MANIFEST.format(inputs=inputs, residual=residual))
        return p

    def write_json(self, name, obj) -> Path:
        p = self.d / name
        p.write_text(json.dumps(obj))
        return p

    # --- decisions: test_source_mode ------------------------------------------
    def test_seeds_passes_with_mock_warning(self):
        code, out = run(pf.gate_decisions,
                        self.manifest("  test_source_mode: seeds"), self.d / "none.yml")
        self.assertEqual(code, 0)
        self.assertIn("FABRICATED", out)

    def test_missing_test_source_mode_fails(self):
        code, out = run(pf.gate_decisions, self.manifest(), self.d / "none.yml")
        self.assertEqual(code, 1)
        self.assertIn("[test_source_mode]", out)

    def test_existing_tables_requires_schemas(self):
        code, out = run(pf.gate_decisions,
                        self.manifest("  test_source_mode: existing_tables\n"
                                      "  test_source_schemas: {}"), self.d / "none.yml")
        self.assertEqual(code, 1)
        self.assertIn("test_source_schemas", out)

    def test_existing_tables_with_schemas_passes(self):
        code, _ = run(pf.gate_decisions,
                      self.manifest("  test_source_mode: existing_tables\n"
                                    "  test_source_schemas:\n"
                                    "    legacy_prod_lnd: RAW.LND"), self.d / "none.yml")
        self.assertEqual(code, 0)

    def test_invalid_test_source_mode_fails(self):
        code, out = run(pf.gate_decisions,
                        self.manifest("  test_source_mode: fixtures"), self.d / "none.yml")
        self.assertEqual(code, 1)
        self.assertIn("test_source_mode", out)

    # --- inventory: suspected Shared Jobs -------------------------------------
    def inventory(self, suspected=True) -> Path:
        return self.write_json("01_inventory.json", {
            "summary": {"unit_count": 1, "coverage_denominator": 3, "edge_count": 2,
                        "parity_targets_found": 1, "parity_targets_missing_name": 0},
            "shared_job_suspected": [{"unit": "x.json:ORCH", "name": "ZERO_LOAD_LOG"}]
            if suspected else [],
        })

    def test_shared_job_needs_bundle_answer(self):
        code, out = run(pf.gate_inventory, self.inventory(), self.manifest())
        self.assertEqual(code, 1)
        self.assertIn("ZERO_LOAD_LOG", out)

    def test_shared_job_null_bundle_needs_residual_disposition(self):
        code, _ = run(pf.gate_inventory, self.inventory(),
                      self.manifest("  shared_job_bundles_path: null"))
        self.assertEqual(code, 1)
        code, out = run(pf.gate_inventory, self.inventory(),
                        self.manifest("  shared_job_bundles_path: null",
                                      residual="human_backlog"))
        self.assertEqual(code, 0)
        self.assertIn("ZERO_LOAD_LOG", out)

    def test_shared_job_with_bundle_path_passes(self):
        code, _ = run(pf.gate_inventory, self.inventory(),
                      self.manifest("  shared_job_bundles_path: /tmp/bundles"))
        self.assertEqual(code, 0)

    def test_no_suspects_no_bundle_requirement(self):
        code, _ = run(pf.gate_inventory, self.inventory(suspected=False), self.manifest())
        self.assertEqual(code, 0)

    # --- parity: rebuild stability --------------------------------------------
    def parity(self, rs) -> Path:
        body = {"models": [{"model": "fct_x", "columns_compared": 3, "columns_total": 3,
                            "parity": "pass"}]}
        if rs is not None:
            body["rebuild_stability"] = rs
        return self.write_json("05_parity.json", body)

    def test_parity_requires_rebuild_stability(self):
        code, out = run(pf.gate_parity, self.parity(None), None)
        self.assertEqual(code, 1)
        self.assertIn("rebuild_stability", out)

    def test_parity_rejects_unstable_rebuild(self):
        code, out = run(pf.gate_parity, self.parity(
            {"runs": 2, "identical": False,
             "models": [{"model": "fct_x", "key_columns": ["k"]}]}), None)
        self.assertEqual(code, 1)
        self.assertIn("non-determinism", out)

    def test_parity_passes_with_stable_rebuild(self):
        code, _ = run(pf.gate_parity, self.parity(
            {"runs": 2, "identical": True,
             "models": [{"model": "fct_x", "key_columns": ["k"],
                         "row_counts": [10, 10]}]}), None)
        self.assertEqual(code, 0)

    # --- tests: advisory test floor -------------------------------------------
    def dbt_manifest(self, with_tests: bool) -> Path:
        nodes = {
            "model.p.fct_pay": {
                "resource_type": "model", "name": "fct_pay",
                "original_file_path": "models/marts/fct_pay.sql",
                "config": {"contract": {"enforced": True}},
                "raw_code": "select row_number() over (partition by a order by b) as k "
                            "from {{ ref('stg_pay') }}"},
            "model.p.stg_pay": {
                "resource_type": "model", "name": "stg_pay",
                "original_file_path": "models/staging/stg_pay.sql",
                "config": {}, "raw_code": "select * from {{ source('s', 't') }}"},
        }
        unit_tests = {}
        if with_tests:
            nodes["test.p.unique_fct_pay_k"] = {
                "resource_type": "test", "test_metadata": {"name": "unique"},
                "depends_on": {"nodes": ["model.p.fct_pay"]}}
            unit_tests["unit_test.p.fct_pay.t1"] = {
                "model": "fct_pay", "depends_on": {"nodes": ["model.p.fct_pay"]}}
        return self.write_json("manifest.json", {"nodes": nodes, "unit_tests": unit_tests})

    def changes(self, rows) -> Path:
        p = self.d / "migration_changes.md"
        body = "\n".join(f"| {m} | {r} |" for m, r in rows)
        p.write_text("# Changes\n\n## Test coverage (minimum test floor)\n"
                     "| Model | Generic tests | Unit tests | Singular tests | Reason if none |\n"
                     "|---|---|---|---|---|\n" + body + "\n\n## Residual\n")
        return p

    def test_tests_gate_flags_gaps_advisory(self):
        cp = self.changes([("fct_pay", "1 | 0 | 0 |"), ("stg_pay", "0 | 0 | 0 | view only")])
        code, out = run(pf.gate_tests, self.dbt_manifest(False), False, None, cp)
        self.assertEqual(code, 0)                     # advisory by default
        self.assertIn("fct_pay: mart with no grain test", out)
        self.assertIn("window function", out)
        self.assertNotIn("stg_pay", out)
        code, _ = run(pf.gate_tests, self.dbt_manifest(False), True, None, cp)
        self.assertEqual(code, 1)                     # --strict makes gaps fail

    def test_tests_gate_passes_when_floor_met(self):
        cp = self.changes([("fct_pay", "1 | 1 | 0 |"), ("stg_pay", "0 | 0 | 0 | view only")])
        code, out = run(pf.gate_tests, self.dbt_manifest(True), True, None, cp)
        self.assertEqual(code, 0, out)
        self.assertNotIn("WARN", out)

    def test_reason_in_coverage_table_accepts_flagged_model(self):
        cp = self.changes([("fct_pay", "1 | 0 | 0 | row_number only numbers lines; "
                                       "covered by grain test"),
                           ("stg_pay", "0 | 0 | 0 | view only")])
        code, out = run(pf.gate_tests, self.dbt_manifest(False), False, None, cp)
        self.assertNotIn("no unit test", out)

    def test_missing_coverage_table_and_rows_are_reported(self):
        code, out = run(pf.gate_tests, self.dbt_manifest(True), False, None,
                        self.d / "absent.md")
        self.assertIn("no 'Test coverage' table", out)
        cp = self.changes([("fct_pay", "1 | 1 | 0 |")])
        code, out = run(pf.gate_tests, self.dbt_manifest(True), False, None, cp)
        self.assertIn("stg_pay: no row", out)

    def test_contract_check_follows_contract_boundary(self):
        man = self.dbt_manifest(True)
        data = json.loads(man.read_text())
        data["nodes"]["model.p.fct_pay"]["config"] = {}
        man.write_text(json.dumps(data))
        cp = self.changes([("fct_pay", "1 | 1 | 0 |"), ("stg_pay", "0 | 0 | 0 | view only")])
        _, out = run(pf.gate_tests, man, False, self.manifest(), cp)          # all_marts
        self.assertIn("no enforced contract", out)
        mf = self.d / "migration_manifest.yml"
        mf.write_text(mf.read_text().replace("contract_boundary: all_marts",
                                             "contract_boundary: none"))
        _, out = run(pf.gate_tests, man, False, mf, cp)
        self.assertNotIn("no enforced contract", out)


class LogicDetection(unittest.TestCase):
    """The regex cases that were wrong before the detection was rewritten."""

    def hits(self, sql):
        return pf._logic_hits(pf._sql_for_scan({"raw_code": sql}))

    def test_where_comparison_after_key_join_is_not_non_key(self):
        self.assertNotIn("non-key join",
                         self.hits("select * from a join b on a.id = b.id where a.amt > 0"))

    def test_comparison_in_comment_is_ignored(self):
        self.assertNotIn("non-key join",
                         self.hits("select * from a join b on a.id = b.id\n-- note: x > y"))

    def test_range_and_or_joins_are_non_key(self):
        self.assertIn("non-key join",
                      self.hits("select * from a join b on a.d between b.s and b.e"))
        self.assertIn("non-key join",
                      self.hits("select * from a join b on a.id = b.id or a.alt = b.id"))
        self.assertIn("non-key join", self.hits("select * from a join b on 1 = 1"))

    def test_when_counted_per_case_block(self):
        two = "-- when the job runs\nselect case when a then 1 when b then 2 end"
        self.assertNotIn("case with 3+ branches", self.hits(two))
        split = ("select case when a then 1 when b then 2 end, "
                 "case when c then 1 when d then 2 end")
        self.assertNotIn("case with 3+ branches", self.hits(split))
        three = "select case when a then 1 when b then 2 when c then 3 else 0 end"
        self.assertIn("case with 3+ branches", self.hits(three))

    def test_date_arithmetic_on_current_date(self):
        self.assertIn("date arithmetic", self.hits("select * from t where d > current_date - 7"))
        self.assertNotIn("date arithmetic", self.hits("select 'interval' as label from t"))

    def test_compiled_code_preferred(self):
        node = {"raw_code": "select * from {{ dbt_utils.unpivot(ref('x')) }}",
                "compiled_code": "select row_number() over (order by k) from x"}
        self.assertIn("window function", pf._logic_hits(pf._sql_for_scan(node)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
