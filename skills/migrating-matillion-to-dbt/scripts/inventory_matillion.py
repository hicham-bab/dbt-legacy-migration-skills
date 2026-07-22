#!/usr/bin/env python3
"""Deterministic inventory of Matillion exports (stdlib for METL JSON; DPC YAML needs pyyaml).

Handles every Matillion form:
  - Data Productivity Cloud YAML  (.tran.yaml / .orch.yaml)   -> needs `pyyaml`
  - Matillion ETL JSON export     (jobsTree / orchestrationJobs+transformationJobs arrays)
  - Matillion ETL JSON export     (older `objects[]` of {jobObject, info})
  - Matillion ETL git per-job     (<Name>.ORCHESTRATION / .TRANSFORMATION, {job, info})

Emits a normalized inventory splitting **transformation** components (migratable -> dbt models;
the coverage denominator) from **orchestration / EL** components (out of dbt scope). If a DPC YAML
file is given and pyyaml isn't installed, it says so and exits 3 (install pyyaml or inventory by hand).

Usage: python3 inventory_matillion.py <file-or-dir> [...] [--json]
METL JSON verified against real exports; DPC YAML against example pipelines.
"""
from __future__ import annotations
import json
import sys
import glob
import os
from pathlib import Path

EL_TYPES = {"s3-load", "database-query", "api-query", "salesforce-query", "excel-query",
            "google-sheets-query", "hubspot-query"}
CONTROL_TYPES = {"start", "end-success", "end-failure", "create-table", "truncate-table",
                 "alter-table", "if", "and", "retry", "sql", "python-script", "bash-script",
                 "grid-iterator", "table-iterator", "loop-iterator", "fixed-iterator"}
BRIDGE_TYPES = {"run-transformation", "run-orchestration"}
# METL numeric implementationID -> component (from verified real exports; extend as needed)
METL_IMPL = {1354890871: "table-input", -359894709: "detect-changes", 1139103188: "pivot",
             444132438: "start", 1611478312: "create-table", 655623811: "create-file-format",
             1214167305: "api-query", 1043089869: "api-extract", -798585337: "sql",
             -1773186829: "python-script", 773867971: "s3-load", 235671163: "and",
             1058406652: "file-iterator", 1896325668: "table-output"}


def _metl_comp_name(c):
    try:
        return c["parameters"]["1"]["elements"]["1"]["values"]["1"]["value"]
    except Exception:
        return None


def _classify(ctype: str) -> str:
    if ctype in EL_TYPES:
        return "el_ingestion"
    if ctype in BRIDGE_TYPES:
        return "bridge"
    if ctype in CONTROL_TYPES:
        return "control"
    return "transformation"


def parse_dpc_yaml(path: Path):
    try:
        import yaml
    except ImportError:
        return None  # signal: pyyaml missing
    doc = yaml.safe_load(path.read_text())
    ptype = doc.get("type", "")
    comps = (doc.get("pipeline", {}) or {}).get("components", {}) or {}
    out = []
    for name, body in comps.items():
        ctype = body.get("type", "")
        out.append({"name": name, "type": ctype,
                    "role": "transformation" if ptype == "transformation" else _classify(ctype),
                    "target": (body.get("parameters", {}) or {}).get("targetTable")})
    return [{"unit": path.name, "pipeline_type": ptype, "components": out}]


def _metl_jobs(doc):
    """Yield (job_name, job_type, body) across the METL JSON variants."""
    def jtype(body, info=None):
        raw = ((info or {}).get("type") or body.get("JobType") or "")
        if "tran" in raw.lower():
            return "transformation"
        if "orch" in raw.lower():
            return "orchestration"
        return "transformation" if ("connectors" in body and "successConnectors" not in body) else "orchestration"
    if "job" in doc and "info" in doc:                       # git per-job
        yield (doc["info"].get("name", "<job>"), jtype(doc["job"], doc["info"]), doc["job"])
    elif "objects" in doc:                                   # older export
        for o in doc["objects"]:
            body = o.get("jobObject") or o.get("job") or {}
            yield (o.get("info", {}).get("name", "<obj>"), jtype(body, o.get("info")), body)
    elif "jobsTree" in doc:                                  # newer export
        for j in doc.get("orchestrationJobs", []):
            yield ("<orch>", "orchestration", j)
        for j in doc.get("transformationJobs", []):
            yield ("<tran>", "transformation", j)


def parse_metl_json(path: Path):
    doc = json.loads(path.read_text())
    units = []
    for name, jtype, body in _metl_jobs(doc):
        comps = []
        for cid, c in (body.get("components", {}) or {}).items():
            impl = c.get("implementationID")
            ctype = METL_IMPL.get(impl, f"impl:{impl}")
            comps.append({"name": _metl_comp_name(c) or cid, "type": ctype,
                          "role": "transformation" if jtype == "transformation" else _classify(ctype)})
        units.append({"unit": f"{path.name}:{name}", "pipeline_type": jtype, "components": comps})
    return units


def parse_file(path: Path):
    if path.name.endswith((".tran.yaml", ".orch.yaml")):
        return parse_dpc_yaml(path)  # may be None if pyyaml missing
    if path.suffix == ".json" or path.suffix in (".ORCHESTRATION", ".TRANSFORMATION"):
        return parse_metl_json(path)
    return []


def build_inventory(paths):
    files = []
    for p in paths:
        if p.is_dir():
            for pat in ("*.tran.yaml", "*.orch.yaml", "*.json", "*.ORCHESTRATION", "*.TRANSFORMATION"):
                files.extend(sorted(p.glob(pat)))
        else:
            files.append(p)
    units, yaml_missing = [], False
    for f in files:
        r = parse_file(f)
        if r is None:
            yaml_missing = True
        else:
            units.extend(r)
    roles = [c["role"] for u in units for c in u["components"]]
    transform = roles.count("transformation")
    return {
        "units": units,
        "yaml_pyyaml_missing": yaml_missing,
        "summary": {
            "unit_count": len(units),
            "total_components": len(roles),
            "transformation_components_migratable": transform,
            "coverage_denominator": transform,   # only transformation components
            "el_ingestion_out_of_scope": roles.count("el_ingestion"),
            "control_out_of_scope": roles.count("control"),
            "bridges": roles.count("bridge"),
        },
    }


def main(argv):
    args = [a for a in argv if a != "--json"]
    if not args:
        print(__doc__); return 2
    inv = build_inventory([Path(a) for a in args])
    if inv["yaml_pyyaml_missing"]:
        print("NOTE: a DPC .yaml pipeline was skipped because `pyyaml` is not installed.\n"
              "      Run `pip install pyyaml` and re-run, or inventory that pipeline by hand\n"
              "      using parsing-matillion-pipelines.md.", file=sys.stderr)
    if "--json" in argv:
        print(json.dumps({k: v for k, v in inv.items() if k != "yaml_pyyaml_missing"}, indent=2))
        return 3 if inv["yaml_pyyaml_missing"] and not inv["units"] else 0
    s = inv["summary"]
    print(f"Matillion inventory: {s['unit_count']} pipeline/job(s), {s['total_components']} components")
    print(f"  transformation (migratable): {s['transformation_components_migratable']}  <- coverage denominator")
    print(f"  EL ingestion (out of scope): {s['el_ingestion_out_of_scope']}  |  "
          f"control: {s['control_out_of_scope']}  |  run-* bridges: {s['bridges']}")
    for u in inv["units"]:
        print(f"\n[{u['pipeline_type']}] {u['unit']}  ({len(u['components'])} components)")
        for c in u["components"]:
            tag = "" if c["role"] == "transformation" else f"  <{c['role']}>"
            print(f"    {c['name']:28s} {c['type']}{tag}")
    return 3 if inv["yaml_pyyaml_missing"] and not inv["units"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
