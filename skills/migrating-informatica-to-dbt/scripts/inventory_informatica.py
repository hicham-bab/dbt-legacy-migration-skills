#!/usr/bin/env python3
"""Deterministic inventory of an Informatica PowerCenter XML export (stdlib only).

Walks POWERMART > REPOSITORY > FOLDER and emits a normalized JSON inventory of mappings,
their transformations, sources, targets, mapplets, and the workflow — plus a computed
coverage denominator (total transformations across mappings). Lets Step 1 be reproducible
instead of the agent re-reading the XML by hand.

Usage: python3 inventory_informatica.py <file.xml> [more.xml ...] [--json]
Verified against a real PowerCenter 10.5 export.
"""
from __future__ import annotations
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

# transformation TYPEs that are structural glue, not a modeling unit
GLUE_TYPES = {"Source Qualifier", "Input Transformation", "Output Transformation"}


def parse_export(path: Path) -> dict:
    root = ET.parse(path).getroot()
    folders = []
    for folder in root.iter("FOLDER"):
        mappings = []
        for mp in folder.iter("MAPPING"):
            transforms = [
                {"name": t.get("NAME"), "type": t.get("TYPE"),
                 "reusable": t.get("REUSABLE"),
                 "is_glue": t.get("TYPE") in GLUE_TYPES}
                for t in mp.iter("TRANSFORMATION")
            ]
            targets = sorted({i.get("NAME") for i in mp.iter("INSTANCE")
                              if i.get("TYPE") == "TARGET"})
            mappings.append({
                "name": mp.get("NAME"),
                "description": mp.get("DESCRIPTION") or None,
                "transformations": transforms,
                "transformation_types": sorted({t["type"] for t in transforms}),
                "targets": targets,
            })
        folders.append({
            "name": folder.get("NAME"),
            "mappings": mappings,
            "sources": sorted({s.get("NAME") for s in folder.iter("SOURCE")}),
            "targets": sorted({t.get("NAME") for t in folder.iter("TARGET")}),
            "mapplets": sorted({m.get("NAME") for m in folder.iter("MAPPLET")}),
            "worklets": sorted({w.get("NAME") for w in folder.iter("WORKLET")}),
            "sessions": [s.get("NAME") for s in folder.iter("SESSION")],
        })
    return {"file": path.name, "folders": folders}


def build_inventory(paths: list[Path]) -> dict:
    exports = [parse_export(p) for p in paths]
    all_mappings = [m for e in exports for f in e["folders"] for m in f["mappings"]]
    total_transforms = sum(len(m["transformations"]) for m in all_mappings)
    modeling_transforms = sum(
        1 for m in all_mappings for t in m["transformations"] if not t["is_glue"])
    scd2_mappings = [m["name"] for m in all_mappings
                     if any(t["type"] == "Update Strategy" for t in m["transformations"])]
    return {
        "exports": exports,
        "summary": {
            "mapping_count": len(all_mappings),
            "total_transformations": total_transforms,
            "modeling_transformations": modeling_transforms,
            "coverage_denominator": len(all_mappings),   # one dbt model (family) per mapping
            "mappings_with_update_strategy_scd2": scd2_mappings,
        },
    }


def main(argv):
    args = [a for a in argv if a != "--json"]
    if not args:
        print(__doc__); return 2
    inv = build_inventory([Path(a) for a in args])
    if "--json" in argv:
        print(json.dumps(inv, indent=2)); return 0
    s = inv["summary"]
    print(f"Informatica inventory: {s['mapping_count']} mapping(s), "
          f"{s['total_transformations']} transformations "
          f"({s['modeling_transformations']} non-glue)")
    print(f"  coverage denominator (mappings): {s['coverage_denominator']}")
    if s["mappings_with_update_strategy_scd2"]:
        print(f"  SCD2 (Update Strategy) -> snapshots: {s['mappings_with_update_strategy_scd2']}")
    for e in inv["exports"]:
        for f in e["folders"]:
            print(f"\n[folder {f['name']}]  sources={len(f['sources'])} "
                  f"targets={len(f['targets'])} mapplets={len(f['mapplets'])}")
            for m in f["mappings"]:
                print(f"    {m['name']:22s} -> {','.join(m['targets']) or '?'}  "
                      f"[{', '.join(m['transformation_types'])}]")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
