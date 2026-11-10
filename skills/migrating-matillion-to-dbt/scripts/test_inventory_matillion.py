#!/usr/bin/env python3
"""Regression tests for inventory_matillion.py (stdlib unittest, no fixtures on disk).

Run:  python3 test_inventory_matillion.py

The fixture below is SYNTHETIC. It reproduces the structural shape of a real METL
`jobsTree` export -- one orchestration job plus transformation jobs, the six common
transformation component ids, run-transformation bridges, and the five separate
orchestration connector collections -- without carrying any customer data.

These tests lock in the four defects that made the coverage denominator untrustworthy:

  1. Unmapped ids must NOT default to `transformation`. The old default silently
     counted every unrecognized component as migratable. Measured on a real export:
     40 reported against 19 true.
  2. Job type must NOT override component type. The old code forced
     role="transformation" for every component in a transformation job, which masked
     the fact that the id map covered none of the six common transformation types.
  3. `run-transformation` must classify as a bridge. Id 1896325668 was previously
     mis-mapped to `table-output`, so `bridges` was structurally always 0.
  4. Orchestration jobs must yield edges. The old code read only `connectors`, which
     transformation jobs use; orchestration control flow lives in five other
     collections and was invisible.
"""
from __future__ import annotations
import json
import tempfile
import unittest
from pathlib import Path

import inventory_matillion as inv


def _c(cid: int, impl: int, name: str, extra_params=None) -> dict:
    params = {"1": {"name": "Name",
                    "elements": {"1": {"values": {"1": {"value": name}}}}}}
    for slot, (pname, pval) in (extra_params or {}).items():
        params[slot] = {"name": pname,
                        "elements": {"1": {"values": {"1": {"value": pval}}}}}
    return {"id": cid, "implementationID": impl, "parameters": params}


def _conn(cid: int, s: int, t: int) -> dict:
    return {"id": cid, "sourceID": s, "targetID": t}


def build_fixture() -> dict:
    """1 orchestration job (9 components) + 2 transformation jobs (8 + 2)."""
    orch = {
        "id": 900,
        "components": {
            "1": _c(11, 444132438, "ST_EXAMPLE"),                    # start   -> control
            "2": _c(12, -1357378929, "IF_EXAMPLE"),                   # if      -> control
            "3": _c(13, 1897708461, "EXL_QUERY_EXAMPLE",              # excel   -> EL
                    {"2": ("Target Table", "RAW_EXAMPLE_IN")}),
            "4": _c(14, 1896325668, "TRANS_EXAMPLE_MAIN"),            # bridge
            "5": _c(15, 1896325668, "TRANS_EXAMPLE_AUX"),             # bridge
            "6": _c(16, 438858066, "MSG_EXAMPLE"),                    # sns     -> control
            "7": _c(17, 999999999, "MYSTERY_COMPONENT"),              # UNMAPPED -> unknown
            # only ${...} pass-throughs: a suspected Shared Job, logic not in export
            "8": _c(18, 2014087685, "LOG_SHARED_JOB_EXAMPLE",
                    {str(i): (f"Param {i}", f"${{JV_PARAM_{i}}}") for i in range(2, 8)}),
            # same shape but with a real SQL body: an inline script, not a Shared Job
            "9": _c(19, -798585337, "SQL_SCRIPT_INLINE_EXAMPLE",
                    {"2": ("SQL Script", "insert into LOG_EXAMPLE select 1"),
                     **{str(i): (f"Param {i}", f"${{JV_PARAM_{i}}}")
                        for i in range(3, 8)}}),
        },
        # control flow lives across five collections, not in `connectors`
        "successConnectors": {"a": _conn(51, 11, 12)},
        "trueConnectors": {"b": _conn(52, 12, 13)},
        "falseConnectors": {"c": _conn(53, 12, 16)},
        "failureConnectors": {"d": _conn(54, 13, 16)},
        "unconditionalConnectors": {"e": _conn(55, 14, 15)},
        "iterationConnectors": {},
    }
    tran_main = {
        "id": 901,
        "components": {
            "1": _c(21, -1266674941, "SQ_SOURCE"),        # sql
            "2": _c(22, 1716658327, "CALC_DERIVE"),       # calculator
            "3": _c(23, -629958239, "JOIN_INNER_MISNAMED"),  # join
            "4": _c(24, -1760161015, "FLTR_VALID"),       # filter
            "5": _c(25, 128170095, "RN_EXAMPLE"),            # rename
            "6": _c(26, -627810085, "TRNSP_EXAMPLE"),        # unpivot
            "7": _c(27, 211954775, "TBL_OUT_MART",        # table-output, truncate
                    {"2": ("Target Table", "MART_EXAMPLE"),
                     "5": ("Truncate", "Truncate"),
                     "200": ("Schema", "ANALYTICS")}),
            # an EL component sitting INSIDE a transformation job: must stay EL
            "8": _c(28, 773867971, "S3_LOAD_INSIDE_TRAN"),
        },
        "connectors": {"x": _conn(61, 21, 22), "y": _conn(62, 22, 27)},
    }
    tran_aux = {
        "id": 902,
        "components": {
            "1": _c(31, -1266674941, "SQ_LOG"),
            "2": _c(32, 211954775, "TBL_OUT_LOG",         # table-output, APPEND
                    {"2": ("Target Table", "LOG_EXAMPLE"),
                     "5": ("Truncate", "Append")}),
        },
        "connectors": {"z": _conn(71, 31, 32)},
    }
    return {
        "dbEnvironment": "snowflake",
        "jobsTree": [
            {"id": 900, "name": "ORCH_EXAMPLE"},
            {"id": 901, "name": "TRANS_EXAMPLE_MAIN"},
            {"id": 902, "name": "TRANS_EXAMPLE_AUX"},
        ],
        "orchestrationJobs": [orch],
        "transformationJobs": [tran_main, tran_aux],
        "variables": [],
        "environments": [],
    }


class InventoryRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        p = Path(cls.tmp.name) / "ORCH_EXAMPLE.json"
        p.write_text(json.dumps(build_fixture()))
        cls.inv = inv.build_inventory([p])
        cls.s = cls.inv["summary"]

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    # --- defect 1: unmapped must not inflate the denominator -------------------
    def test_unmapped_is_unknown_not_transformation(self):
        roles = {c["name"]: c["role"]
                 for u in self.inv["units"] for c in u["components"]}
        self.assertEqual(roles["MYSTERY_COMPONENT"], "unknown")
        self.assertEqual(self.s["unknown_needs_mapping"], 1)

    def test_unknown_excluded_from_denominator(self):
        # 8 in tran_main + 2 in tran_aux = 10 components in transformation jobs,
        # but S3_LOAD_INSIDE_TRAN is EL, so 9 are migratable. The unknown in the
        # orchestration job must not be added.
        self.assertEqual(self.s["coverage_denominator"], 9)
        self.assertNotIn("MYSTERY", str(self.inv["parity_targets"]))

    def test_unknown_components_are_listed_for_mapping(self):
        names = [u["name"] for u in self.inv["unknown_components"]]
        self.assertEqual(names, ["MYSTERY_COMPONENT"])
        self.assertEqual(self.inv["unknown_components"][0]["implementation_id"],
                         999999999)

    # --- defect 2: component type beats job type ------------------------------
    def test_el_inside_transformation_job_stays_el(self):
        roles = {c["name"]: c["role"]
                 for u in self.inv["units"] for c in u["components"]}
        self.assertEqual(roles["S3_LOAD_INSIDE_TRAN"], "el_ingestion")

    def test_six_common_transformation_ids_resolve(self):
        types = {c["name"]: c["type"]
                 for u in self.inv["units"] for c in u["components"]}
        self.assertEqual(types["SQ_SOURCE"], "sql")
        self.assertEqual(types["CALC_DERIVE"], "calculator")
        self.assertEqual(types["JOIN_INNER_MISNAMED"], "join")
        self.assertEqual(types["FLTR_VALID"], "filter")
        self.assertEqual(types["RN_EXAMPLE"], "rename")
        self.assertEqual(types["TRNSP_EXAMPLE"], "unpivot")

    # --- defect 3: bridges must be reachable ----------------------------------
    def test_run_transformation_is_a_bridge(self):
        self.assertEqual(self.s["bridges"], 2)
        types = {c["name"]: c["type"]
                 for u in self.inv["units"] for c in u["components"]}
        self.assertEqual(types["TRANS_EXAMPLE_MAIN"], "run-transformation")

    def test_table_output_id_is_not_run_transformation(self):
        types = {c["name"]: c["type"]
                 for u in self.inv["units"] for c in u["components"]}
        self.assertEqual(types["TBL_OUT_MART"], "table-output")

    # --- defect 4: orchestration edges ----------------------------------------
    def test_every_job_emits_edges(self):
        for u in self.inv["units"]:
            self.assertTrue(u["edges"], f"{u['unit']} emitted no edges")

    def test_control_flow_edges_are_typed(self):
        kinds = {e["kind"] for e in self.inv["control_flow_edges"]}
        self.assertEqual(kinds, {"on_true", "on_false", "on_failure"})
        self.assertEqual(self.s["control_flow_edge_count"], 3)

    def test_orchestration_edges_counted(self):
        orch = next(u for u in self.inv["units"]
                    if u["pipeline_type"] == "orchestration")
        self.assertEqual(len(orch["edges"]), 5)

    # --- parity targets and write mode ----------------------------------------
    def test_parity_targets_captured_for_metl(self):
        by_comp = {t["component"]: t for t in self.inv["parity_targets"]}
        self.assertEqual(by_comp["TBL_OUT_MART"]["target"], "MART_EXAMPLE")
        self.assertEqual(by_comp["TBL_OUT_MART"]["schema"], "ANALYTICS")
        self.assertEqual(self.s["parity_targets_missing_name"], 0)

    def test_append_vs_truncate_detected(self):
        by_comp = {t["component"]: t for t in self.inv["parity_targets"]}
        self.assertEqual(by_comp["TBL_OUT_MART"]["write_mode"], "truncate_reload")
        self.assertEqual(by_comp["TBL_OUT_LOG"]["write_mode"], "append")
        self.assertEqual(self.s["append_mode_targets"], 1)

    # --- suspected Shared Jobs ------------------------------------------------
    def test_pass_through_control_is_suspected_shared_job(self):
        names = [c["name"] for c in self.inv["shared_job_suspected"]]
        self.assertEqual(names, ["LOG_SHARED_JOB_EXAMPLE"])
        self.assertEqual(self.s["shared_job_suspected_count"], 1)
        self.assertEqual(self.inv["shared_job_suspected"][0]["parameter_count"], 7)

    def test_sql_script_with_body_is_not_suspected(self):
        flags = {c["name"]: c["shared_job_suspected"]
                 for u in self.inv["units"] for c in u["components"]}
        self.assertFalse(flags["SQL_SCRIPT_INLINE_EXAMPLE"])
        # components with only a Name parameter are below the threshold
        self.assertFalse(flags["ST_EXAMPLE"])
        self.assertFalse(flags["TRANS_EXAMPLE_MAIN"])

    def test_shared_job_rule_unit(self):
        tok = [("Name", ["X"])] + [(f"P{i}", [f"${{V{i}}}"]) for i in range(5)]
        self.assertTrue(inv._shared_job_suspected("control", tok))
        self.assertTrue(inv._shared_job_suspected("bridge", tok))
        # transformation components are never flagged
        self.assertFalse(inv._shared_job_suspected("transformation", tok))
        # a literal value means the component carries its own configuration
        self.assertFalse(inv._shared_job_suspected("control", tok + [("P9", ["literal"])]))
        # fewer than the minimum number of parameters
        self.assertFalse(inv._shared_job_suspected("control", tok[:3]))
        # all empty: no token, nothing to suspect
        self.assertFalse(inv._shared_job_suspected(
            "control", [(f"P{i}", [""]) for i in range(6)]))

    # --- naming ----------------------------------------------------------------
    def test_job_names_recovered_from_jobs_tree(self):
        units = [u["unit"].split(":", 1)[1] for u in self.inv["units"]]
        self.assertIn("ORCH_EXAMPLE", units)
        self.assertIn("TRANS_EXAMPLE_MAIN", units)

    def test_no_component_name_falls_back_to_raw_id(self):
        raw = [c["name"] for u in self.inv["units"] for c in u["components"]
               if str(c["name"]).isdigit()]
        self.assertEqual(raw, [], f"names fell back to raw ids: {raw}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
