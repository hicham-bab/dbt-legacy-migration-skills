#!/usr/bin/env python3
"""Deterministic inventory of SnapLogic pipeline exports (.slp). Stdlib only — .slp is JSON.

Classifies every snap into one of SnapLogic's execution regimes, because — unlike Matillion —
a .slp file has no transformation/orchestration split. The regime is a property of the *snap*:

  pushdown_elt    ELT Snap Pack (com-snaplogic-snaps-elt-*)  -> builds SQL, runs in the warehouse
  warehouse_sql   <DB> Execute / Select / Insert / Merge     -> raw SQL sent to the warehouse
  standard_stream Transform/Flow snaps carrying data logic   -> row-by-row in the Snaplex
  sync_barrier    joins on a constant, Tail/Gate "wait"      -> ordering, not data
  fan_out         Copy                                       -> vanishes in dbt
  bridge          Pipeline Execute / ForEach / Task Execute  -> recurse into the child pipeline
  el_ingestion    readers / writers / parsers / formatters / API / file / queue snaps
  control         Exit, Script, Email, Router-as-branch, job-logging, error handling

The coverage denominator is pushdown_elt + warehouse_sql + migratable standard_stream. The
standard_stream count is reported separately so you can discount snaps whose flow is not
warehouse-to-warehouse (those are genuinely not dbt work).

Also reports **write-target chains**: several warehouse_sql snaps whose SQL writes the same table
is SnapLogic's sequential MERGE/UPDATE enrichment pattern — that is ONE dbt model, not N.

Usage: python3 inventory_snaplogic.py <file-or-dir> [...] [--json]
Verified against real .slp exports.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# --- snap class_id -> regime -------------------------------------------------------------
# class_id is the stable type key (class_fqid carries a build tag and must not be matched on).

ELT_PREFIX = "com-snaplogic-snaps-elt-"

# Suffixes on a database Snap Pack that mean "send this SQL to the warehouse".
WAREHOUSE_SQL_SUFFIXES = ("-execute", "-select", "-insert", "-update", "-delete",
                          "-merge", "-bulkload", "-bulk-load", "-multiexecute", "-scd2")
WAREHOUSE_PACKS = ("bigquery", "snowflake", "redshift", "databricks", "synapse", "azuresql",
                   "sqlserver", "oracle", "mysql", "postgres", "postgresql", "teradata",
                   "vertica", "netezza", "db2", "hana", "jdbc", "genericjdbc")

STANDARD_STREAM = {
    "transform-datatransform",     # Mapper
    "transform-join", "transform-multijoin", "transform-aggregate", "transform-sort",
    "transform-unique", "transform-pivot", "transform-groupbyfields", "transform-groupbyn",
    "transform-inmemorylookup", "transform-diff", "transform-conditional", "transform-structure",
    "transform-sequence", "transform-constant",
    "flow-union", "flow-router", "flow-filter", "flow-binaryrouter",
    "flow-datavalidator",
}   # note: flow-head lives in SYNC_BARRIER below (it truncates a stream, it doesn't transform)
SYNC_BARRIER = {"flow-tail", "flow-gate", "flow-head"}
FAN_OUT = {"flow-copy"}
BRIDGE = {"flow-pipeexec", "flow-foreach", "flow-taskexecute"}
CONTROL = {"flow-exit", "script-script", "email-emailsender", "email-emailreader",
           "transform-recordreplay"}

EL_HINTS = ("-parser", "-formatter", "-reader", "-writer", "-read", "-write", "-poll",
            "-browse", "-upload", "-download", "-get", "-post", "-put", "-patch")
EL_PACKS = ("s3", "file", "binary", "rest", "soap", "http", "api", "kafka", "jms", "ftp", "sftp",
            "salesforce", "workday", "netsuite", "sap", "servicenow", "marketo", "hubspot",
            "googlesheets", "googledrive", "excel", "azurestorage", "gcs", "email")

# SQL verbs -> what the snap is really doing.
SQL_VERB = [
    (re.compile(r"\bcreate\s+(or\s+replace\s+)?(temp(orary)?\s+)?(table|view)\b", re.I), "ctas"),
    (re.compile(r"\bmerge\s+into\b", re.I), "merge"),
    (re.compile(r"\binsert\s+(into|overwrite)\b", re.I), "insert"),
    (re.compile(r"\bupdate\b", re.I), "update"),
    (re.compile(r"\bdelete\s+from\b|\btruncate\b", re.I), "delete"),
    (re.compile(r"\b(drop|alter|grant|revoke)\b", re.I), "ddl"),
    (re.compile(r"\bcall\b", re.I), "procedure"),
    (re.compile(r"\bselect\b", re.I), "select"),
]
# A single Execute snap routinely holds SEVERAL statements (";"-separated). Find every write.
WRITE_RE = re.compile(
    r"\b(?P<verb>merge\s+into"
    r"|create\s+(?:or\s+replace\s+)?(?:temp(?:orary)?\s+)?(?:table|view)(?:\s+if\s+not\s+exists)?"
    r"|insert\s+(?:into|overwrite)(?:\s+table)?"
    r"|truncate\s+table|delete\s+from)\s+`?(?P<target>[\w.\-]+)`?", re.I)
# A bare UPDATE that is NOT the "when matched then update set" clause of a MERGE.
BARE_UPDATE_RE = re.compile(r"(?<!then\s)\bupdate\s+`?([\w.\-]+)`?\s+set\b", re.I)
NOT_MATCHED_INSERT_RE = re.compile(r"when\s+not\s+matched.*?then\s+insert", re.I | re.S)
# Where each Snap Pack keeps its SQL text.
SQL_KEYS = ("Query", "sqlStatement", "sql_statement", "statement", "sqlQuery", "query")


def _short(class_id: str) -> str:
    """com-snaplogic-snaps-transform-datatransform -> transform-datatransform"""
    return class_id.replace("com-snaplogic-snaps-", "") if class_id else ""


def _prop(node, *path, default=None):
    """Walk a SnapLogic {value: ...} property tree."""
    cur = node
    for key in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
    return cur if cur is not None else default


def _setting(settings: dict, key: str):
    """Return (value, is_expression) for settings[key]."""
    node = (settings or {}).get(key)
    if not isinstance(node, dict):
        return None, False
    return node.get("value"), bool(node.get("expression"))


def unwrap_sql(raw, is_expression: bool) -> str:
    """Strip SnapLogic expression quoting so the SQL verb is visible.

    When `expression` is true the value is an expression-language string: SQL wrapped in double
    quotes and concatenated with `+ $var +`. Leading `#standardSQL` hints and `--` comments also
    hide the verb.
    """
    if not isinstance(raw, str):
        return ""
    s = raw.strip()
    if is_expression and s.startswith('"'):
        s = s[1:]
    s = re.sub(r"^\s*#\w+", "", s)                      # #standardSQL / #StandardSQL
    # Strip ALL comments, not just leading ones. Commented-out table names are common in these
    # exports ("--`schema.tbl` alias --historical") and otherwise produce false write targets and
    # false self_referencing flags. Heuristic: a "--" inside a string literal would also go.
    s = re.sub(r"/\*.*?\*/", " ", s, flags=re.S)
    s = re.sub(r"--[^\n]*", " ", s)
    return s.strip()


def snap_sql(settings: dict):
    """Return (sql_text, is_expression) for whichever key this Snap Pack uses."""
    for key in SQL_KEYS:
        value, is_expr = _setting(settings, key)
        if isinstance(value, str) and value.strip():
            return unwrap_sql(value, is_expr), is_expr
    return "", False


def sql_verb(sql: str) -> str:
    for pattern, verb in SQL_VERB:
        if pattern.search(sql):
            return verb
    return "unknown"


def sql_writes(sql: str):
    """Every table this snap writes, in statement order. One snap can write several tables."""
    seen, out = set(), []
    for m in WRITE_RE.finditer(sql):
        target = m.group("target")
        if target.lower() not in seen:
            seen.add(target.lower())
            out.append(target)
    for m in BARE_UPDATE_RE.finditer(sql):
        target = m.group(1)
        if target.lower() not in seen:
            seen.add(target.lower())
            out.append(target)
    return out


def sql_statement_count(sql: str) -> int:
    """Number of write statements — >1 means this snap maps to more than one dbt object."""
    return len(WRITE_RE.findall(sql))


def writes_per_target(sql: str):
    """How many write statements hit each target, within this one snap."""
    counts = {}
    for m in WRITE_RE.finditer(sql):
        counts[m.group("target")] = counts.get(m.group("target"), 0) + 1
    for m in BARE_UPDATE_RE.finditer(sql):
        counts[m.group(1)] = counts.get(m.group(1), 0) + 1
    return counts


def merge_flags(sql: str, writes):
    """Semantics that change the dbt materialization choice."""
    flags = []
    if NOT_MATCHED_INSERT_RE.search(sql):
        flags.append("inserts_rows")          # accumulating table -> incremental, not table
    # Self-reference: the target table is also read inside the statement (the USING subquery).
    # Detect by removing the "MERGE INTO <target>" / "UPDATE <target>" header, then looking for
    # the table name again in the body.
    body = WRITE_RE.sub(" ", sql)                       # drop every "<verb> <target>" header
    body = BARE_UPDATE_RE.sub(" set ", body)
    if any(re.search(r"\b" + re.escape(w.split(".")[-1]) + r"\b", body, re.I) for w in writes):
        flags.append("self_referencing")      # reads its own target -> needs {{ this }} semantics
    return flags


# ELT Snaps that don't build data (their output is a check, a load, or plumbing).
ELT_NON_MODEL = {"elt-load": "el_ingestion", "elt-copy": "fan_out", "elt-execute": "model",
                 "elt-sample": "check", "elt-limit": "check"}


def elt_kind(short: str) -> str:
    """An ELT Snap Pack snap holds configuration, not SQL text — classify it by type."""
    return ELT_NON_MODEL.get(short, "model")


def sql_kind(verb: str, writes) -> str:
    """Sub-classify a warehouse SQL snap: does it build data, check data, or neither?

    Only `model` snaps are dbt models. `check` snaps become dbt tests; `procedure` is blocked on
    another skill; `backup`/`ddl` are operational and disappear.
    """
    if verb == "procedure":
        return "procedure"
    if verb in ("ddl",):
        return "ddl"
    if not writes:
        return "check" if verb == "select" else "ddl"
    if any(re.search(r"(_bkp|_backup|_bak)$", w, re.I) for w in writes):
        return "backup"
    return "model"


def classify(class_id: str, settings: dict, label: str) -> str:
    short = _short(class_id)
    if class_id.startswith(ELT_PREFIX):
        return "pushdown_elt"
    if any(short.endswith(sfx) for sfx in WAREHOUSE_SQL_SUFFIXES) and \
            any(pack in short for pack in WAREHOUSE_PACKS):
        return "warehouse_sql"
    if short in BRIDGE:
        return "bridge"
    if short in FAN_OUT:
        return "fan_out"
    if short in CONTROL:
        return "control"
    if short in STANDARD_STREAM:
        # A join whose every joinPath is a literal is a synchronisation barrier, not a join.
        paths = _prop(settings, "joinPaths", "value", default=None)
        if isinstance(paths, list) and paths:
            keys = [str(_prop(p, "leftPath", "value", default="")).strip() for p in paths]
            if all(re.fullmatch(r"['\"]?\d+['\"]?", k or "") for k in keys):
                return "sync_barrier"
        return "standard_stream"
    if short in SYNC_BARRIER:
        return "sync_barrier"
    if any(h in short for h in EL_HINTS) or any(short.startswith(p + "-") for p in EL_PACKS):
        return "el_ingestion"
    return "unknown"


MIGRATABLE = ("pushdown_elt", "warehouse_sql", "standard_stream")


def parse_slp(path: Path):
    doc = json.loads(path.read_text())
    if "snap_map" not in doc:
        return []
    pipeline = _prop(doc, "property_map", "info", "label", "value", default=path.stem)
    params = [_prop(p, "key", "value") for p in
              _prop(doc, "property_map", "settings", "param_table", "value", default=[]) or []]
    imports = [_prop(i, "path", "value") for i in
               _prop(doc, "property_map", "settings", "imports", "value", default=[]) or []]

    snaps = []
    for sid, snap in (doc.get("snap_map") or {}).items():
        class_id = snap.get("class_id") or ""
        pm = snap.get("property_map") or {}
        settings = pm.get("settings") or {}
        label = _prop(pm, "info", "label", "value", default=sid)
        regime = classify(class_id, settings, label)
        # A snap set to "Disabled" does not run. It is dead code: never migrate it, never count it.
        disabled = _prop(settings, "execution_mode", "value") == "Disabled"
        entry = {"id": sid, "label": label, "type": _short(class_id) or "<unknown>",
                 "regime": regime, "disabled": disabled}
        if regime in ("warehouse_sql", "pushdown_elt", "control"):
            sql, is_expr = snap_sql(settings)
            if not sql and regime == "warehouse_sql":
                # <DB> Select/Insert/Merge/Bulk Load snaps are configured, not SQL-bearing.
                # Without this they would silently fall out of the denominator.
                short = _short(class_id)
                entry["kind"] = ("check" if short.endswith("-select")
                                 else "ddl" if short.endswith(("-delete", "-truncate"))
                                 else "model")
                entry["writes"] = [w for w in [_prop(settings, "table", "value"),
                                               _prop(settings, "targetTable", "value")] if w]
            if not sql and regime == "pushdown_elt":
                # ELT Snaps build their SQL from configuration and hold no SQL string. They are
                # the most migratable regime, so they must not fall out of the denominator.
                entry["kind"] = elt_kind(_short(class_id))
                entry["writes"] = [w for w in [_prop(settings, "targetTable", "value")] if w]
            if sql:
                entry["sql_verb"] = sql_verb(sql)
                entry["writes"] = sql_writes(sql)
                entry["write_statements"] = sql_statement_count(sql)
                entry["writes_per_target"] = writes_per_target(sql)
                entry["dynamic_sql"] = is_expr
                entry["flags"] = merge_flags(sql, entry["writes"])
                entry["kind"] = sql_kind(entry["sql_verb"], entry["writes"])
        if regime == "bridge":
            entry["calls"] = _prop(settings, "pipeline", "value")
        snaps.append(entry)

    # link_map is the DAG. isGoto edges are control jumps, not data flow.
    # isGoto edges are NOT data lineage — but they ARE sequencing, and in these exports they
    # carry part of the MERGE-chain order. Keep them in a separate list; never silently drop them.
    edges, goto_edges = [], []
    for link in (doc.get("link_map") or {}).values():
        edge = {"src": link.get("src_id"), "dst": link.get("dst_id")}
        (goto_edges if link.get("isGoto") else edges).append(edge)

    return [{"unit": str(path), "pipeline": pipeline, "snaps": snaps, "edges": edges,
             "goto_edges": goto_edges, "pipeline_params": [p for p in params if p],
             "imports": [i for i in imports if i]}]


def write_chains(units):
    """Targets written by more than one STATEMENT -> sequential enrichment = ONE dbt model.

    Counted per statement, not per snap: a single snap can write the same target five times
    (CTAS then four MERGEs), which is the same collapse problem as five separate snaps.
    """
    chains = {}
    for unit in units:
        for snap in unit["snaps"]:
            if snap.get("disabled") or snap.get("kind") not in ("model", None):
                continue
            for target, n in (snap.get("writes_per_target") or {}).items():
                who = f"{unit['pipeline']}.{snap['label']}"
                chains.setdefault(target, []).extend(
                    [who + (f" (stmt {i + 1} of {n} in this snap)" if n > 1 else "")
                     for i in range(n)])
    return {t: s for t, s in chains.items() if len(s) > 1}


def all_model_targets(units):
    """Distinct tables that live data-building snaps write = the dbt models to build."""
    targets = set()
    for unit in units:
        for snap in unit["snaps"]:
            if snap.get("disabled") or snap.get("kind") != "model":
                continue
            targets.update(snap.get("writes") or [])
    return sorted(targets)


def build_inventory(paths):
    files = []
    for p in paths:
        files.extend(sorted(p.rglob("*.slp")) if p.is_dir() else [p])
    units = []
    for f in files:
        units.extend(parse_slp(f))

    all_snaps = [s for u in units for s in u["snaps"]]
    regimes = [s["regime"] for s in all_snaps]
    counts = {r: regimes.count(r) for r in sorted(set(regimes))}
    disabled = [s for s in all_snaps if s["disabled"]]
    live = [s for s in all_snaps if not s["disabled"]]

    kinds = {}
    for s in live:
        if s["regime"] in ("warehouse_sql", "pushdown_elt") and s.get("kind"):
            kinds[s["kind"]] = kinds.get(s["kind"], 0) + 1

    # Denominator = live snaps that become dbt MODELS. Excluded by rule, not by judgement:
    #   disabled (dead code) | check (-> tests) | backup/ddl (operational) | procedure (blocked)
    #   | standard_stream (reported separately: count only warehouse-to-warehouse flows)
    denominator = kinds.get("model", 0)
    stream_candidates = sum(1 for s in live if s["regime"] == "standard_stream")
    model_targets = all_model_targets(units)
    return {
        "units": units,
        "write_chains": write_chains(units),
        "model_targets": model_targets,
        "summary": {
            "pipeline_count": len(units),
            "total_snaps": len(all_snaps),
            "disabled_snaps": len(disabled),
            "coverage_denominator": denominator,
            "distinct_model_targets": len(model_targets),
            "denominator_note": ("live warehouse SQL/ELT snaps that build data (kind=model); "
                                 "add any standard_stream snaps you confirm are "
                                 "warehouse-to-warehouse"),
            "standard_stream_candidates": stream_candidates,
            "warehouse_sql_by_kind": kinds,
            "by_regime": counts,
            "multi_statement_snaps": sum(1 for s in live
                                         if (s.get("write_statements") or 0) > 1),
        },
    }


def main(argv):
    args = [a for a in argv if a != "--json"]
    if not args:
        print(__doc__)
        return 2
    inv = build_inventory([Path(a) for a in args])
    if "--json" in argv:
        print(json.dumps(inv, indent=2))
        return 0

    s = inv["summary"]
    print(f"SnapLogic inventory: {s['pipeline_count']} pipeline(s), {s['total_snaps']} snaps "
          f"({s['disabled_snaps']} disabled)")
    print(f"\n  COVERAGE DENOMINATOR = {s['coverage_denominator']} snaps   "
          f"({s['denominator_note']})")
    print(f"  distinct model targets to build = {s['distinct_model_targets']}   "
          "(snaps and models are NOT 1:1 — count coverage in snaps, build by target)")
    if s["warehouse_sql_by_kind"]:
        print("  live warehouse SQL/ELT snaps by kind:")
        for kind, n in sorted(s["warehouse_sql_by_kind"].items(), key=lambda kv: -kv[1]):
            note = {"model": "-> dbt models  [COUNTED]", "check": "-> dbt tests",
                    "backup": "-> operational, drop", "ddl": "-> dbt owns DDL, drop",
                    "procedure": "-> migrating-stored-procedures-to-dbt (blocked)"}.get(kind, "")
            print(f"      {kind:10s} {n:3d}  {note}")
    print(f"  standard_stream candidates: {s['standard_stream_candidates']}  "
          "(count ONLY those whose flow is warehouse-to-warehouse; job-logging/notification "
          "mappers and status routers are not)")
    print("  by regime: " + ", ".join(f"{r}={n}" for r, n in
                                      sorted(s["by_regime"].items(), key=lambda kv: -kv[1])))
    if s["multi_statement_snaps"]:
        print(f"  !! {s['multi_statement_snaps']} snap(s) hold MORE THAN ONE write statement — "
              "one snap can map to several dbt models")

    for u in inv["units"]:
        print(f"\n[{u['pipeline']}]  {len(u['snaps'])} snaps, {len(u['edges'])} data edges"
              + (f", {len(u['goto_edges'])} goto (ordering) edges" if u["goto_edges"] else ""))
        if u["goto_edges"]:
            names = {sn["id"]: sn["label"] for sn in u["snaps"]}
            print("    goto edges carry SEQUENCE, not lineage — use them to order a collapsed "
                  "chain:")
            for e in u["goto_edges"]:
                print(f"        {names.get(e['src'], '?')[:30]:32s} => "
                      f"{names.get(e['dst'], '?')}")
        if u["imports"]:
            print(f"    ! external expression libraries (not in the export): {u['imports']}")
        for snap in u["snaps"]:
            extra = ""
            if snap.get("sql_verb"):
                bits = [snap["sql_verb"], snap.get("kind", "")]
                if (snap.get("write_statements") or 0) > 1:
                    bits.append(f"{snap['write_statements']} stmts")
                if snap.get("dynamic_sql"):
                    bits.append("dynamic")
                bits.extend(snap.get("flags") or [])
                extra = "  [" + ", ".join(b for b in bits if b) + "]"
                if snap.get("writes"):
                    extra += " -> " + ", ".join(snap["writes"])
            elif snap.get("calls"):
                extra = f"  -> {snap['calls']}"
            flag = "x" if snap["disabled"] else " "
            print(f"  {flag} {snap['label'][:32]:32s} {snap['type']:32s} "
                  f"{snap['regime']}{extra}")
        if any(sn["disabled"] for sn in u["snaps"]):
            print("    ('x' = execution_mode Disabled: dead code, not migrated, not counted)")

    if inv["write_chains"]:
        print("\n!! Write-target chains (live, data-building snaps only) — each is ONE dbt "
              "model, not N:")
        for target, snaps in inv["write_chains"].items():
            print(f"   {target}  <- {len(snaps)} write statements")
            for name in snaps:
                print(f"       {name}")
    if inv["summary"]["by_regime"].get("unknown"):
        print("\nNOTE: 'unknown' snaps were not recognised — inventory them by hand using "
              "parsing-snaplogic-pipelines.md before computing coverage.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
