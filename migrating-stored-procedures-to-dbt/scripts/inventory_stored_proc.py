#!/usr/bin/env python3
"""Heuristic construct scanner for a SQL stored procedure (stdlib only).

A stored proc is raw SQL text, not a structured export — so this is a **regex-based
construct scanner, not a real SQL parser**. It flags the constructs the migration must
handle and computes a step-count denominator, so Step 1 is reproducible and the residual
(dynamic SQL, stateful loops) is caught deterministically rather than by eye. Always
review its output against the actual SQL — it can miss/over-match on unusual formatting.

Usage: python3 inventory_stored_proc.py <proc.sql> [...] [--json]
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

# (label, regex, how it maps / whether it's residual)
PATTERNS = [
    ("target_rebuild",   r"\bCREATE\s+OR\s+REPLACE\s+TABLE\s+([A-Za-z0-9_.]+)", "-> table model (full rebuild)"),
    ("temp_table",       r"\bCREATE\s+(?:OR\s+REPLACE\s+)?(?:TEMP|TEMPORARY|GLOBAL TEMPORARY|VOLATILE)\s+TABLE\s+([A-Za-z0-9_.#]+)", "-> CTE or int_ model"),
    ("merge",            r"\bMERGE\s+INTO\s+([A-Za-z0-9_.]+)", "-> incremental (plain) / model explicitly (conditional)"),
    ("insert",           r"\bINSERT\s+(?:INTO\s+)?([A-Za-z0-9_.]+)", "-> incremental append / part of a model"),
    ("update",           r"\bUPDATE\s+([A-Za-z0-9_.]+)\s+SET", "-> set-based column / merge"),
    ("cursor_loop",      r"\b(FOR\s+\w+\s+IN|WHILE\s+|LOOP\b|OPEN\s+\w+\s+CURSOR|CURSOR\s+FOR)", "-> set-based query (or residual if stateful)"),
    ("if_branch",        r"\bIF\s+.+?\bTHEN\b", "-> case when / separate models"),
    ("dynamic_sql",      r"\b(EXECUTE\s+IMMEDIATE|sp_executesql|EXEC\s*\()", "RESIDUAL (transform) or DROP (DDL/maintenance)"),
    ("scalar_var",       r"^\s*(?:DECLARE\s+\w+|SET\s+\w+\s*:?=|\w+\s*:=)", "-> CTE computing the value"),
]
# dynamic-SQL bodies that are DDL/maintenance -> DROP (not residual)
MAINT_RE = re.compile(r"(ANALYZE|GRANT|CREATE\s+INDEX|VACUUM|GATHER_TABLE_STATS)", re.I)


def scan(path: Path) -> dict:
    text = path.read_text()
    # strip line + block comments so we don't match commented-out SQL
    body = re.sub(r"--[^\n]*", "", text)
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
    hits = {}
    for label, rx, note in PATTERNS:
        found = re.findall(rx, body, flags=re.I | re.M)
        if found:
            hits[label] = {"count": len(found), "note": note,
                           "targets": sorted({f if isinstance(f, str) else f[0]
                                              for f in found if (f if isinstance(f, str) else f[0])})[:10]}
    residual = []
    if "dynamic_sql" in hits:
        # classify each EXECUTE IMMEDIATE as maintenance (drop) vs transform (residual)
        for m in re.finditer(r"(EXECUTE\s+IMMEDIATE|sp_executesql|EXEC\s*\()(.{0,120})", body, re.I | re.S):
            residual.append("dynamic_sql:maintenance(drop)" if MAINT_RE.search(m.group(2))
                            else "dynamic_sql:transform(RESIDUAL - review)")
    # step-count denominator ~ statements that produce/modify a target
    denom = sum(hits.get(k, {}).get("count", 0)
                for k in ("target_rebuild", "temp_table", "merge", "insert", "update"))
    return {"file": path.name, "constructs": hits, "dynamic_sql_detail": residual,
            "step_count_denominator": denom}


def main(argv):
    args = [a for a in argv if a != "--json"]
    if not args:
        print(__doc__); return 2
    scans = [scan(Path(a)) for a in args]
    out = {"procedures": scans,
           "note": "Heuristic regex scan — review against the actual SQL; confirm grain and business rules by hand."}
    if "--json" in argv:
        print(json.dumps(out, indent=2)); return 0
    for sc in scans:
        print(f"\n{sc['file']}  (step-count denominator ~ {sc['step_count_denominator']})")
        for label, d in sc["constructs"].items():
            tgt = f"  {d['targets']}" if d["targets"] else ""
            print(f"    {label:14s} x{d['count']:<2}  {d['note']}{tgt}")
        for r in sc["dynamic_sql_detail"]:
            print(f"    -> {r}")
    print("\n(Heuristic — verify against the SQL; confirm grain + business rules manually.)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
