#!/usr/bin/env python3
"""Deterministic inventory of a Coalesce (coalesce.io) Git project (needs pyyaml).

Coalesce commits its project as YAML: one file per node under ./nodes/*.yml, node type
templates under ./nodeTypes/, plus macros/jobs/subgraphs/locations/data.yml. This walks
the node files and emits a normalized inventory — each node's inferred kind (source /
stage / dimension / dimension_scd2 / fact / view), materialization, business/surrogate
keys, upstream refs (column-level lineage), and per-node transforms — plus a computed
coverage denominator (transformable, non-source nodes) and the SCD2 dimensions
(-> snapshots). Lets Step 1 be reproducible instead of hand-reading YAML.

Usage: python3 inventory_coalesce.py <project-dir | nodes-dir | node.yml ...> [--json]
Structure grounded in the coalesceio Git format; verify against a real export early.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path


def _load(path: Path):
    import yaml
    return yaml.safe_load(path.read_text())


def _upstream_ids(col: dict) -> list[str]:
    out = []
    for scr in col.get("sourceColumnReferences") or []:
        for cr in scr.get("columnReferences") or []:
            cc = cr.get("columnCounter")
            if cc:
                out.append(cc)
    return out


def classify(node: dict) -> str:
    op = node.get("operation", {}) or {}
    if op.get("type") == "sourceInput" or op.get("sqlType") == "Source":
        return "source"
    cfg = op.get("config", {}) or {}
    cols = op.get("metadata", {}).get("columns", []) or []
    has_bk = any(c.get("isBusinessKey") for c in cols)
    name = (node.get("name") or "").upper()
    if cfg.get("type2Dimension"):
        return "dimension_scd2"
    if name.startswith("DIM") or (has_bk and "FCT" not in name and "FACT" not in name and op.get("materializationType") != "view"):
        return "dimension" if has_bk else "stage"
    if name.startswith(("FCT", "FACT")):
        return "fact"
    if op.get("materializationType") == "view":
        return "view"
    return "stage"


def parse_node(path: Path) -> dict:
    n = _load(path)
    if not isinstance(n, dict) or n.get("type") != "Node":
        return {}
    op = n.get("operation", {}) or {}
    cols = op.get("metadata", {}).get("columns", []) or []
    kind = classify(n)
    return {
        "file": path.name,
        "id": n.get("id"),
        "name": n.get("name"),
        "location": op.get("locationName"),
        "kind": kind,
        "materialization": op.get("materializationType"),
        "type2_scd": bool((op.get("config") or {}).get("type2Dimension")),
        "business_keys": [c["name"] for c in cols if c.get("isBusinessKey")],
        "surrogate_keys": [c["name"] for c in cols if c.get("isSurrogateKey")],
        "column_count": len(cols),
        "upstream_node_ids": sorted({u for c in cols for u in _upstream_ids(c)}),
        "transforms": [{"column": c["name"], "transform": c["transform"]}
                       for c in cols if c.get("transform")],
    }


def collect_node_files(paths: list[Path]) -> list[Path]:
    files = []
    for p in paths:
        if p.is_file() and p.suffix in (".yml", ".yaml"):
            files.append(p)
        elif p.is_dir():
            nodes_dir = p / "nodes" if (p / "nodes").is_dir() else p
            files.extend(sorted(nodes_dir.glob("*.yml")) + sorted(nodes_dir.glob("*.yaml")))
    return files


def build_inventory(paths: list[Path]) -> dict:
    nodes = [n for f in collect_node_files(paths) if (n := parse_node(f))]
    by_id = {n["id"]: n["name"] for n in nodes if n.get("id")}
    for n in nodes:  # resolve upstream ids -> node names (ref lineage)
        n["upstream_nodes"] = [by_id.get(i, i) for i in n["upstream_node_ids"]]
        del n["upstream_node_ids"]
    kinds = {}
    for n in nodes:
        kinds[n["kind"]] = kinds.get(n["kind"], 0) + 1
    transformable = [n for n in nodes if n["kind"] != "source"]
    return {
        "nodes": nodes,
        "summary": {
            "node_count": len(nodes),
            "by_kind": kinds,
            "sources": kinds.get("source", 0),
            "transformable_nodes": len(transformable),
            "coverage_denominator": len(transformable),   # non-source nodes
            "scd2_dimensions": [n["name"] for n in nodes if n["type2_scd"]],
        },
    }


def main(argv):
    args = [a for a in argv if a != "--json"]
    if not args:
        print(__doc__); return 2
    try:
        import yaml  # noqa: F401
    except ImportError:
        print("ERROR: this parser needs pyyaml. Run `pip install pyyaml` and retry.", file=sys.stderr)
        return 3
    inv = build_inventory([Path(a) for a in args])
    if "--json" in argv:
        print(json.dumps(inv, indent=2)); return 0
    s = inv["summary"]
    print(f"Coalesce inventory: {s['node_count']} node(s)  {s['by_kind']}")
    print(f"  transformable (non-source): {s['transformable_nodes']}  <- coverage denominator")
    if s["scd2_dimensions"]:
        print(f"  SCD2 dimensions -> dbt snapshots: {s['scd2_dimensions']}")
    for n in inv["nodes"]:
        bk = f" bk={n['business_keys']}" if n["business_keys"] else ""
        up = f" <- {n['upstream_nodes']}" if n["upstream_nodes"] else ""
        print(f"    {n['name']:22s} [{n['kind']}/{n['materialization'] or '-'}]{bk}{up}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
