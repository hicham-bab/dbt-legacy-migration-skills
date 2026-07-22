#!/usr/bin/env python3
"""Deterministic inventory of Talend .item job exports (stdlib only).

Emits a normalized JSON inventory the migration skill reasons over — instead of the
agent re-parsing XML by hand each run. This makes Step 1 reproducible and makes the
coverage denominator a computed number.

Usage:
    python3 inventory_talend.py <path-to-.item | dir> [more...] [--json]

Default output is a human-readable summary; --json emits the full structure.
Verified against real Talend .item exports.
"""
from __future__ import annotations
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

# component types with no in-warehouse (SQL) equivalent -> out of scope / residual
NON_SQL = {
    "tFileInputDelimited", "tFileInputExcel", "tFileOutputDelimited", "tFileOutputExcel",
    "tFTPGet", "tFTPPut", "tSendMail", "tJava", "tJavaRow", "tJavaFlex",
    "tLogCatcher", "tDie", "tWarn", "tFlowMeter", "tSystem",
}
# connector names that are orchestration/trigger edges, not data flow
TRIGGER_CONNECTORS = {"ON_SUBJOB_OK", "ON_SUBJOB_ERROR", "ON_COMPONENT_OK",
                      "ON_COMPONENT_ERROR", "RUN_IF"}
DATAFLOW_CONNECTORS = {"FLOW", "MAIN", "LOOKUP", "REJECT"}


def _param(node, name):
    """Return the value of an <elementParameter name=...> under a node."""
    for ep in node.iter("elementParameter"):
        if ep.get("name") == name:
            return ep.get("value")
    return None


def parse_item(path: Path) -> dict:
    root = ET.parse(path).getroot()
    job = {"file": path.name, "job_name": root.get("name") or path.stem,
           "components": [], "connections": [], "context": []}

    for node in root.iter("node"):
        comp_name = node.get("componentName", "")
        comp = {
            "name": node.get("uniqueName", ""),
            "component": comp_name,
            "schema_db": _param(node, "SCHEMA_DB") or _param(node, "SCHEMA"),
            "table": _param(node, "TABLENAME") or _param(node, "TABLE"),
            "query": _param(node, "QUERY") or _param(node, "QUERYSTORE"),
            "condition": _param(node, "CONDITION") or _param(node, "CONDITIONS"),
            "group_by": _param(node, "GROUP_BY"),
            "unique_keys": _param(node, "KEY_ATTRIBUTE"),
            "join_model": _param(node, "JOIN_MODEL"),
            "runs_job": _param(node, "PROCESS"),
            "columns": [
                {"name": c.get("name"), "type": c.get("type"),
                 "nullable": c.get("nullable"), "key": c.get("key")}
                for md in node.iter("metadata") if md.get("connector") != "REJECT"
                for c in md.iter("column")
            ],
            "is_sql": comp_name not in NON_SQL,
        }
        comp = {k: v for k, v in comp.items() if v not in (None, [], "")}
        comp["is_sql"] = comp_name not in NON_SQL  # keep even if False
        job["components"].append(comp)

    for conn in root.iter("connection"):
        cname = conn.get("connectorName", "FLOW")
        job["connections"].append({
            "type": cname,
            "kind": "trigger" if cname in TRIGGER_CONNECTORS else "dataflow",
            "source": conn.get("source"),
            "target": conn.get("target"),
            "label": conn.get("label"),
        })

    for cp in root.iter("contextParameter"):
        job["context"].append({"name": cp.get("name"), "type": cp.get("type")})

    return job


def build_inventory(paths: list[Path]) -> dict:
    items = []
    for p in paths:
        if p.is_dir():
            items.extend(sorted(p.glob("*.item")))
        elif p.suffix == ".item":
            items.append(p)
    jobs = [parse_item(p) for p in items]

    total_components = sum(len(j["components"]) for j in jobs)
    sql_components = sum(1 for j in jobs for c in j["components"] if c.get("is_sql"))
    non_sql = [(j["job_name"], c["name"], c["component"])
               for j in jobs for c in j["components"] if not c.get("is_sql")]
    cross_job = [(j["job_name"], c["name"], c.get("runs_job"))
                 for j in jobs for c in j["components"] if c["component"] == "tRunJob"]

    return {
        "jobs": jobs,
        "summary": {
            "job_count": len(jobs),
            "total_components": total_components,
            "sql_components_migratable": sql_components,
            "non_sql_components_out_of_scope": len(non_sql),
            "coverage_denominator": sql_components,  # only SQL components count
            "cross_job_edges": cross_job,
            "out_of_scope": non_sql,
        },
    }


def main(argv):
    args = [a for a in argv if a != "--json"]
    as_json = "--json" in argv
    if not args:
        print(__doc__); return 2
    inv = build_inventory([Path(a) for a in args])
    if as_json:
        print(json.dumps(inv, indent=2)); return 0

    s = inv["summary"]
    print(f"Talend inventory: {s['job_count']} job(s), {s['total_components']} components")
    print(f"  migratable (SQL) components  : {s['sql_components_migratable']}  <- coverage denominator")
    print(f"  out-of-scope (non-SQL)       : {s['non_sql_components_out_of_scope']}")
    for j in inv["jobs"]:
        print(f"\n[{j['job_name']}]  ({len(j['components'])} components)")
        for c in j["components"]:
            tag = "" if c.get("is_sql") else "  <out-of-scope>"
            tgt = f" -> {c['table']}" if c.get("table") else ""
            print(f"    {c['name']:26s} {c['component']}{tgt}{tag}")
        for cn in j["connections"]:
            arrow = "==>" if cn["kind"] == "dataflow" else "..>(trigger)"
            print(f"      {cn['source']} {arrow} {cn['target']}  [{cn['type']}]")
    if s["out_of_scope"]:
        print("\nOut of scope (map to sources / scheduler, not models):")
        for job, name, comp in s["out_of_scope"]:
            print(f"  - {job}.{name} ({comp})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
