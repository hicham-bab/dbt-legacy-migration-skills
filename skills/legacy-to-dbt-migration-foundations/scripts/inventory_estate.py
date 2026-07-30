#!/usr/bin/env python3
"""Estate-scale inventory: turn a whole directory of mixed legacy artifacts into a migration backlog.

The per-source parsers (inventory_talend/informatica/matillion/coalesce/stored_proc) each handle one
workload. This orchestrates them across an entire estate (thousands of jobs, multiple tools): it
discovers and classifies every artifact, runs the right parser, and aggregates into one normalized
backlog with complexity, risk, within-tool dependencies, and a dependency-ordered **wave** plan. It
also seeds a progress **ledger** (see estate_ledger.py) so a migration can be tracked across waves.

Usage: python3 inventory_estate.py <estate-dir> [--out <dir>] [--json]
Outputs (to --out, default the estate dir): estate_inventory.json, estate_backlog.md, and
estate_ledger.json (seeded only if absent, so progress is never clobbered).
Stdlib only, except the Matillion DPC-YAML and Coalesce cases which need pyyaml (their parsers say so).
"""
from __future__ import annotations

import datetime
import json
import re
import subprocess
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]
PARSERS = {
    "talend": SKILLS / "migrating-talend-to-dbt/scripts/inventory_talend.py",
    "informatica": SKILLS / "migrating-informatica-to-dbt/scripts/inventory_informatica.py",
    "matillion": SKILLS / "migrating-matillion-to-dbt/scripts/inventory_matillion.py",
    "coalesce": SKILLS / "migrating-coalesce-to-dbt/scripts/inventory_coalesce.py",
    "stored_proc": SKILLS / "migrating-stored-procedures-to-dbt/scripts/inventory_stored_proc.py",
}


def classify(p: Path) -> str | None:
    n = p.name.lower()
    if n.endswith(".item"):
        return "talend"
    if n.endswith((".tran.yaml", ".orch.yaml")):
        return "matillion"
    try:
        head = p.read_text(errors="ignore")[:4000]
    except Exception:
        return None
    if p.suffix.lower() == ".xml":
        return "informatica" if "POWERMART" in head else None
    if p.suffix.lower() in (".yml", ".yaml"):
        return "coalesce" if ("sqlType" in head and "operation" in head) else None
    if p.suffix.lower() == ".json":
        return "matillion" if any(k in head for k in ("implementationID", "jobsTree", "jobObject")) else None
    if p.suffix.lower() == ".sql":
        return "stored_proc" if re.search(r"create\s+(or\s+replace\s+)?procedure", head, re.I) else None
    return None


def run_parser(tool: str, files: list[Path]) -> dict:
    if tool == "stored_proc":  # merge per-file (parser reads one proc file at a time)
        merged = {"procedures": []}
        for f in files:
            out = subprocess.run([sys.executable, str(PARSERS[tool]), str(f), "--json"],
                                 capture_output=True, text=True)
            try:
                merged["procedures"] += json.loads(out.stdout).get("procedures", [])
            except Exception:
                pass
        return merged
    out = subprocess.run([sys.executable, str(PARSERS[tool]), *map(str, files), "--json"],
                         capture_output=True, text=True)
    try:
        return json.loads(out.stdout)
    except Exception as e:
        return {"_error": f"{e!r}: {out.stderr[:200]}"}


# --- per-tool adapters: parser JSON -> normalized job records ------------

def _risk(complexity: int, scd2: bool, dyn: bool, oos: bool) -> str:
    if scd2 or dyn or complexity >= 8:
        return "high"
    if complexity >= 4 or oos:
        return "med"
    return "low"


def adapt(tool: str, d: dict) -> list[dict]:
    jobs = []
    if tool == "talend":
        oos_jobs = {e[0] for e in d.get("summary", {}).get("out_of_scope", [])}
        edges = d.get("summary", {}).get("cross_job_edges", [])
        for j in d.get("jobs", []):
            name = j.get("job_name") or j.get("file")
            comps = j.get("components", [])
            scd2 = any("scd" in (c.get("component", "").lower()) for c in comps)
            deps = [e[0] for e in edges if isinstance(e, (list, tuple)) and len(e) >= 2 and e[1] == name]
            jobs.append(_job(tool, name, "job", len(comps), scd2, name in oos_jobs, False, deps))
    elif tool == "informatica":
        scd2_set = set(d.get("summary", {}).get("mappings_with_update_strategy_scd2", []))
        for ex in d.get("exports", []):
            for fld in ex.get("folders", []):
                for m in fld.get("mappings", []):
                    name = m.get("name", "<mapping>")
                    jobs.append(_job(tool, name, "mapping", len(m.get("transformations", [])),
                                     name in scd2_set, False, False, []))
    elif tool == "matillion":
        for u in d.get("units", []):
            comps = u.get("components", [])
            trans = [c for c in comps if c.get("role") == "transformation"] or comps
            scd2 = any(c.get("type") == "detect-changes" for c in comps)
            oos = any(c.get("role") in ("el_ingestion", "control") for c in comps)
            jobs.append(_job(tool, u.get("unit", "<unit>"), u.get("pipeline_type", "unit"),
                             len(trans), scd2, oos, False, []))
    elif tool == "coalesce":
        for n in d.get("nodes", []):
            if n.get("kind") == "source":
                continue
            jobs.append(_job(tool, n["name"], n.get("kind", "node"), n.get("column_count", 0),
                             bool(n.get("type2_scd")), False, False, list(n.get("upstream_nodes", []))))
    elif tool == "stored_proc":
        for pr in d.get("procedures", []):
            constructs = pr.get("constructs", {})
            name = Path(pr.get("file", "proc")).stem
            dyn = "dynamic_sql" in constructs
            jobs.append(_job(tool, name, "procedure", len(constructs), False,
                             "cursor_loop" in constructs, dyn, []))
    return jobs


def _job(tool, name, kind, complexity, scd2, oos, dyn, deps):
    return {"id": f"{tool}:{name}", "tool": tool, "name": name, "kind": kind,
            "complexity": complexity, "scd2": scd2, "out_of_scope": oos,
            "risk": _risk(complexity, scd2, dyn, oos),
            "deps": [f"{tool}:{d}" for d in deps]}


# --- waves: dependency-ordered levels ------------------------------------

def assign_waves(jobs: list[dict]) -> None:
    ids = {j["id"] for j in jobs}
    by_id = {j["id"]: j for j in jobs}
    level: dict[str, int] = {}

    def lvl(jid, seen):
        if jid in level:
            return level[jid]
        if jid in seen:
            return 0  # cycle guard
        deps = [d for d in by_id[jid]["deps"] if d in ids]
        level[jid] = 0 if not deps else 1 + max(lvl(d, seen | {jid}) for d in deps)
        return level[jid]

    for j in jobs:
        j["wave"] = lvl(j["id"], set()) + 1


def build(estate: Path) -> dict:
    groups: dict[str, list[Path]] = {}
    for p in sorted(estate.rglob("*")):
        if p.is_file() and (tool := classify(p)):
            groups.setdefault(tool, []).append(p)
    jobs: list[dict] = []
    errors = {}
    for tool, files in groups.items():
        d = run_parser(tool, files)
        if d.get("_error"):
            errors[tool] = d["_error"]
            continue
        jobs += adapt(tool, d)
    ids = {j["id"] for j in jobs}  # keep only deps that resolve to a job in this estate
    for j in jobs:
        j["deps"] = [d for d in j["deps"] if d in ids]
    assign_waves(jobs)
    jobs.sort(key=lambda j: (j["wave"], j["complexity"], j["id"]))
    by_tool = {t: sum(1 for j in jobs if j["tool"] == t) for t in sorted({j["tool"] for j in jobs})}
    waves = {}
    for j in jobs:
        waves.setdefault(j["wave"], []).append(j["id"])
    return {"generated_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "estate": str(estate), "summary": {"total_jobs": len(jobs), "by_tool": by_tool,
            "waves": {w: len(v) for w, v in sorted(waves.items())},
            "high_risk": sum(1 for j in jobs if j["risk"] == "high")},
            "parse_errors": errors, "jobs": jobs}


def backlog_md(inv: dict) -> str:
    s = inv["summary"]
    lines = ["# Migration estate backlog", "",
             f"> Generated by `inventory_estate.py` on {inv['generated_at']}. "
             "Waves are dependency-ordered; within a wave, simplest first (quick wins).", "",
             f"**{s['total_jobs']} jobs** across {len(s['by_tool'])} tool(s) "
             f"({', '.join(f'{t}: {n}' for t, n in s['by_tool'].items())}); "
             f"{s['high_risk']} high-risk; {len(s['waves'])} wave(s).", "",
             "| Wave | Job | Tool | Kind | Complexity | Risk | SCD2 | Depends on |",
             "|---|---|---|---|---|---|---|---|"]
    for j in inv["jobs"]:
        deps = ", ".join(d.split(":", 1)[1] for d in j["deps"]) or "-"
        lines.append(f"| {j['wave']} | {j['name']} | {j['tool']} | {j['kind']} | {j['complexity']} | "
                     f"{j['risk']} | {'yes' if j['scd2'] else '-'} | {deps} |")
    if inv["parse_errors"]:
        lines += ["", "## Parse errors", ""] + [f"- {t}: {e}" for t, e in inv["parse_errors"].items()]
    lines.append("")
    return "\n".join(lines)


def seed_ledger(inv: dict) -> dict:
    return {"generated_at": inv["generated_at"],
            "jobs": {j["id"]: {"tool": j["tool"], "name": j["name"], "wave": j["wave"],
                               "risk": j["risk"], "status": "pending", "notes": ""}
                     for j in inv["jobs"]}}


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    if not args:
        print(__doc__); return 2
    estate = Path(args[0])
    out = Path(argv[argv.index("--out") + 1]) if "--out" in argv else estate
    inv = build(estate)
    if "--json" in argv:
        print(json.dumps(inv, indent=2))
    out.mkdir(parents=True, exist_ok=True)
    (out / "estate_inventory.json").write_text(json.dumps(inv, indent=2) + "\n")
    (out / "estate_backlog.md").write_text(backlog_md(inv))
    ledger = out / "estate_ledger.json"
    if not ledger.exists():
        ledger.write_text(json.dumps(seed_ledger(inv), indent=2) + "\n")
    s = inv["summary"]
    print(f"Estate inventory: {s['total_jobs']} jobs, {len(s['waves'])} waves, "
          f"{s['high_risk']} high-risk -> {out}/estate_backlog.md")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
