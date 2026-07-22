#!/usr/bin/env python3
"""Eval harness for the deterministic inventory parsers.

Runs each parser against a committed fixture and asserts on its JSON output — so a change
to a parser or answer key that breaks inventory/coverage is caught automatically. Fixtures
under evals/fixtures/ are small and self-authored (no user/third-party data). Stdlib only,
except the Matillion DPC-YAML case which is skipped with a note if `pyyaml` is absent
(the Matillion METL-JSON case always runs on stdlib).

Usage: python3 evals/run_evals.py          # exits 0 if all pass, 1 otherwise
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "evals" / "fixtures"
results = []


def run_json(script: str, *args) -> dict:
    out = subprocess.run([sys.executable, str(ROOT / script), *map(str, args), "--json"],
                         capture_output=True, text=True)
    if out.returncode not in (0, 3):
        raise RuntimeError(f"{script} exited {out.returncode}: {out.stderr[:400]}")
    return json.loads(out.stdout)


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))


# --- Talend --------------------------------------------------------------
try:
    inv = run_json("migrating-talend-to-dbt/scripts/inventory_talend.py", FIX / "talend")
    s = inv["summary"]
    check("talend: 1 job", s["job_count"] == 1, s["job_count"])
    check("talend: 5 components", s["total_components"] == 5, s["total_components"])
    check("talend: coverage denom = 4 SQL (tSendMail excluded)",
          s["coverage_denominator"] == 4, s["coverage_denominator"])
    check("talend: 1 out-of-scope (tSendMail)",
          s["non_sql_components_out_of_scope"] == 1, s["out_of_scope"])
    conns = [c for j in inv["jobs"] for c in j["connections"]]
    check("talend: ON_SUBJOB_OK classified as trigger",
          any(c["type"] == "ON_SUBJOB_OK" and c["kind"] == "trigger" for c in conns))
    check("talend: LOOKUP/FLOW classified as dataflow",
          all(c["kind"] == "dataflow" for c in conns if c["type"] in ("FLOW", "LOOKUP")))
except Exception as e:
    check("talend: parser ran", False, repr(e))

# --- Informatica ---------------------------------------------------------
try:
    inv = run_json("migrating-informatica-to-dbt/scripts/inventory_informatica.py", FIX / "informatica" / "mini_edw.XML")
    s = inv["summary"]
    check("informatica: 2 mappings", s["mapping_count"] == 2, s["mapping_count"])
    check("informatica: coverage denom = 2", s["coverage_denominator"] == 2, s["coverage_denominator"])
    check("informatica: SCD2 mapping detected (Update Strategy)",
          "m_DIM_CUSTOMER_SCD2" in s["mappings_with_update_strategy_scd2"],
          s["mappings_with_update_strategy_scd2"])
    check("informatica: non-glue transforms counted",
          s["modeling_transformations"] >= 4, s["modeling_transformations"])
except Exception as e:
    check("informatica: parser ran", False, repr(e))

# --- Matillion METL JSON (stdlib, always) --------------------------------
try:
    inv = run_json("migrating-matillion-to-dbt/scripts/inventory_matillion.py", FIX / "matillion" / "load.orch.export.json")
    s = inv["summary"]
    check("matillion(METL): 2 units (orch+tran)", s["unit_count"] == 2, s["unit_count"])
    check("matillion(METL): coverage denom = 2 transformation comps",
          s["coverage_denominator"] == 2, s["coverage_denominator"])
    check("matillion(METL): EL ingestion (S3 Load) flagged out of scope",
          s["el_ingestion_out_of_scope"] >= 1, s["el_ingestion_out_of_scope"])
except Exception as e:
    check("matillion(METL): parser ran", False, repr(e))

# --- Matillion DPC YAML (needs pyyaml; skip-with-note otherwise) ---------
try:
    import yaml  # noqa: F401
    inv = run_json("migrating-matillion-to-dbt/scripts/inventory_matillion.py", FIX / "matillion" / "build_marts.tran.yaml")
    s = inv["summary"]
    check("matillion(DPC): coverage denom = 4 transformation comps",
          s["coverage_denominator"] == 4, s["coverage_denominator"])
except ImportError:
    results.append(("matillion(DPC): SKIPPED (pyyaml not installed)", True, "install pyyaml to cover"))
except Exception as e:
    check("matillion(DPC): parser ran", False, repr(e))

# --- Coalesce (needs pyyaml; skip-with-note otherwise) -------------------
try:
    import yaml  # noqa: F401
    inv = run_json("migrating-coalesce-to-dbt/scripts/inventory_coalesce.py", FIX / "coalesce")
    s = inv["summary"]
    check("coalesce: 4 nodes", s["node_count"] == 4, s["node_count"])
    check("coalesce: coverage denom = 3 (non-source)", s["coverage_denominator"] == 3, s["coverage_denominator"])
    check("coalesce: SCD2 dimension detected", "DIM_CUSTOMER_SCD2" in s["scd2_dimensions"], s["scd2_dimensions"])
    check("coalesce: source classified", s["by_kind"].get("source") == 1, s["by_kind"])
    # classification is driven by operation.sqlType (the node-type discriminator)
    check("coalesce: kinds keyed off sqlType (source/stage/dimension_scd2/fact)",
          s["by_kind"] == {"source": 1, "stage": 1, "dimension_scd2": 1, "fact": 1}, s["by_kind"])
    dim = next((n for n in inv["nodes"] if n["name"] == "DIM_CUSTOMER_SCD2"), {})
    check("coalesce: column lineage resolved (DIM <- STG_CUSTOMERS)",
          "STG_CUSTOMERS" in dim.get("upstream_nodes", []), dim.get("upstream_nodes"))
    check("coalesce: business key extracted", dim.get("business_keys") == ["CUSTOMER_ID"], dim.get("business_keys"))
    # SCD Type 2 is detected from a change-tracking column (docs: "Type 2 = change tracking column")
    check("coalesce: SCD2 via isChangeTracking column", dim.get("change_tracking_keys") == ["SEGMENT_EFFECTIVE_FROM"],
          dim.get("change_tracking_keys"))
    check("coalesce: dimension sqlType surfaced", dim.get("sql_type") == "Dimension", dim.get("sql_type"))
except ImportError:
    results.append(("coalesce: SKIPPED (pyyaml not installed)", True, "install pyyaml to cover"))
except Exception as e:
    check("coalesce: parser ran", False, repr(e))

# --- Stored proc (heuristic scan) ----------------------------------------
try:
    inv = run_json("migrating-stored-procedures-to-dbt/scripts/inventory_stored_proc.py", FIX / "stored_proc" / "refresh_metrics.sql")
    sc = inv["procedures"][0]
    c = sc["constructs"]
    check("proc: temp_table flagged", "temp_table" in c, list(c))
    check("proc: merge flagged", "merge" in c, list(c))
    check("proc: cursor_loop flagged", "cursor_loop" in c, list(c))
    check("proc: dynamic_sql flagged", "dynamic_sql" in c, list(c))
    check("proc: dynamic ANALYZE classified as maintenance(drop)",
          any("maintenance(drop)" in d for d in sc["dynamic_sql_detail"]), sc["dynamic_sql_detail"])
    # regression (from real-proc verification): UPDATE/MERGE `SET col = ...` must NOT be counted as
    # scalar variables — only DECLARE / SET @var / `:=` assignments are. The fixture's only real
    # scalar bits are `DECLARE cutoff` + `cutoff :=` (2); the MERGE's `SET ltv_90d=` must not leak.
    sv = c.get("scalar_var", {}).get("count", 0)
    check("proc: scalar_var doesn't over-match UPDATE/MERGE SET clauses (== 2)", sv == 2, sv)
except Exception as e:
    check("proc: scanner ran", False, repr(e))


# --- report --------------------------------------------------------------
passed = sum(1 for _, ok, _ in results if ok)
print(f"Eval harness: {passed}/{len(results)} checks passed\n")
for name, ok, detail in results:
    mark = "PASS" if ok else "FAIL"
    extra = "" if ok else f"   (got: {detail})"
    print(f"  [{mark}] {name}{extra}")
sys.exit(0 if passed == len(results) else 1)
