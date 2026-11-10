#!/usr/bin/env python3
"""Inventory a Matillion workload for a dbt migration (stdlib only, except pyyaml for DPC).

PRIMARY PATH. Run this script to produce the Step-1 inventory wherever Python is available.
The skill's Step 1 also documents a reasoning-based procedure that produces the same artifact
by hand, for the dbt platform only, where Python cannot be installed.
See migrating-matillion-to-dbt/SKILL.md Step 1 and references/parsing-matillion-pipelines.md.

Handles:
  * DPC pipelines      .tran.yaml / .orch.yaml            (needs pyyaml)
  * METL git per-job   .ORCHESTRATION / .TRANSFORMATION    (stdlib)
  * METL JSON exports  {"job","info"} | {"objects"} | {"jobsTree"}  (stdlib)

Emits, per component: name, type, role, target table, write mode, a shared_job_suspected flag,
and the pipeline DAG edges.

Usage:
    python3 inventory_matillion.py <file-or-dir> [...] [--json] [--out PATH] [--strict]

    --json      print the machine-readable inventory to stdout
    --out PATH  write the machine-readable inventory to PATH (recommended:
                migration/01_inventory.json, so Step 7 coverage can be recomputed
                rather than retyped)
    --strict    exit 4 if any component landed in the `unknown` bucket

Exit codes: 0 ok | 2 no args | 3 pyyaml missing and nothing else parsed | 4 --strict unknowns
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Role classification sets. A component's TYPE decides its role. The job it
# lives in is a hint for reporting only and must never override the type --
# an s3-load inside a .tran.yaml is still EL, and a run-transformation inside
# an orchestration job is still a bridge.
# ---------------------------------------------------------------------------
EL_TYPES = {
    "s3-load", "database-query", "api-query", "api-extract", "excel-query",
    "salesforce-query", "google-sheets-query", "hubspot-query", "s3-unload",
    "table-unload", "file-transfer",
}
CONTROL_TYPES = {
    "start", "end-success", "end-failure", "create-table", "truncate-table",
    "alter-table", "create-file-format", "if", "and", "or", "retry", "sql-script",
    "python-script", "bash-script", "sns-message", "sqs-message", "query-result-to-scalar",
    "query-result-to-grid", "archive", "grid-iterator", "table-iterator",
    "loop-iterator", "fixed-iterator", "file-iterator",
}
BRIDGE_TYPES = {"run-transformation", "run-orchestration"}

# METL numeric implementationID -> component type (kebab-case, matching the DPC
# vocabulary used in references/matillion-component-mapping.md).
#
# Provenance of each id is recorded so a future maintainer can judge confidence:
#   [EXPORT]  identified from a real METL export by component naming
#             convention (SQ_/CALC_/JOIN_/FLTR_/RN_/TRNSP_/TBL_OUT_) -- high confidence,
#             corroborated where marked
#   [XREF]    corroborated by an independently authored id map (Matillion->dbt/Glue
#             transpiler config, component_type_map.yaml by_id)
#   [PRIOR]   inherited from the original 14-id map in this file
#
# The full implementationID space is proprietary and NOT exhaustive here. Unrecognized
# ids fall through to role `unknown` and are excluded from the coverage denominator --
# see _classify(). Trust the component's "Name" parameter as the primary signal.
METL_IMPL = {
    # --- transformation components (the six highest-frequency types) ------------
    -1266674941: "sql",                    # [EXPORT] 5x SQ_*  (SQL component)
    1716658327: "calculator",              # [EXPORT] 4x CALC_*
    -629958239: "join",                    # [EXPORT] 2x JOIN_*
    -1760161015: "filter",                 # [EXPORT] 2x FLTR_*
    128170095: "rename",                   # [EXPORT] RN_*
    -627810085: "unpivot",                 # [EXPORT] transpose/melt component
    211954775: "table-output",             # [EXPORT+XREF] 4x TBL_OUT_*/TEMP_*_OUT
    335239555: "rewrite-table",            # [XREF] "Table Rewrite Output"
    1354890871: "table-input",             # [PRIOR]
    -359894709: "detect-changes",          # [PRIOR]
    1139103188: "pivot",                   # [PRIOR]
    # --- bridges ---------------------------------------------------------------
    1896325668: "run-transformation",      # [EXPORT] 3x TRANS_* in the orchestration job,
                                           #   matching the 3 transformation jobs 1:1.
                                           #   Previously mis-mapped to "table-output".
    1785813072: "run-orchestration",       # [XREF] "Run Orchestration Job"
    # --- EL ingestion ----------------------------------------------------------
    1897708461: "excel-query",             # [EXPORT] EXL_QUERY_*
    374945314: "s3-unload",                # [EXPORT] S3_UNLOAD_*
    773867971: "s3-load",                  # [PRIOR]
    1214167305: "api-query",               # [PRIOR]
    1043089869: "api-extract",             # [PRIOR]
    # --- control flow / DDL / glue --------------------------------------------
    444132438: "start",                    # [PRIOR+EXPORT+XREF] ST_*
    -1946388514: "end-success",            # [EXPORT+XREF] END_SUC_*
    515156205: "end-failure",              # [EXPORT] END_FAIL_*
    -1357378929: "if",                     # [EXPORT] 2x IF_*
    -1343684451: "or",                     # [EXPORT] 3x OR_*
    235671163: "and",                      # [PRIOR]
    237373210: "truncate-table",           # [EXPORT] TRUNC_*
    1611478312: "create-table",            # [PRIOR]
    655623811: "create-file-format",       # [PRIOR]
    -798585337: "sql-script",              # [PRIOR+XREF] orchestration SQL Script
    -1773186829: "python-script",          # [PRIOR]
    -1032749985: "query-result-to-scalar",  # [EXPORT] 3x QUERY_RES_SCLR_*, SQ_GEN_*
    438858066: "sns-message",              # [EXPORT+XREF] 2x MSG_*
    -379661045: "sns-message",             # [EXPORT] SNS_MSG_*
    2014087685: "sql-script",              # [EXPORT] logging SQL component
    1199871910: "file-transfer",           # [EXPORT] post-load archival file transfer
    1058406652: "file-iterator",           # [PRIOR]
}

# Parameter names that carry the write target / write mode on a Table Output.
_TARGET_PARAM_NAMES = ("Target Table", "Table", "Target")
_MODE_PARAM_NAMES = ("Truncate", "Load Option", "Write Mode")
_SCHEMA_PARAM_NAMES = ("Schema", "Target Schema")
_DATABASE_PARAM_NAMES = ("Database", "Target Database")

# Shared-Job suspicion. A control/bridge component whose parameters are nothing but
# ${...} pass-throughs carries no logic of its own: the body lives in a .melt bundle
# that is not in the export. The thresholds are a starting point, tuned on one real
# export (a 22-parameter logging component); adjust them on the user's export.
_SHARED_JOB_MIN_PARAMS = 5
_SCRIPT_BODY_PARAM_NAMES = {"sql script", "script", "sql query"}
_NAME_PARAM_NAMES = {"name", "component name"}
_TOKEN = re.compile(r"^\$\{[^}]+\}$")


# ---------------------------------------------------------------------------
# classification
# ---------------------------------------------------------------------------
def _classify(ctype: str) -> str:
    """Map a component TYPE to a role. Type is authoritative; job type is not.

    An unrecognized type returns "unknown", NOT "transformation". The old default
    silently counted every unmapped component as migratable and inflated the
    coverage denominator (measured: 40 reported vs 19 true on a real export).
    Unknowns are reported in their own bucket and excluded from the denominator.
    """
    if ctype in EL_TYPES:
        return "el_ingestion"
    if ctype in BRIDGE_TYPES:
        return "bridge"
    if ctype in CONTROL_TYPES:
        return "control"
    if ctype.startswith("impl:") or ctype in ("", None):
        return "unknown"
    return "transformation"


def _write_mode(raw) -> str | None:
    """Append-mode Table Output needs an incremental model with a unique_key;
    truncate-and-reload needs a plain table. Getting this wrong double-writes on
    rebuild. See references/matillion-component-mapping.md (Table Output)."""
    if raw is None:
        return None
    v = str(raw).strip().lower()
    if v in ("truncate", "true", "yes"):
        return "truncate_reload"
    if v in ("append", "false", "no", "insert"):
        return "append"
    return v or None


def _shared_job_suspected(role: str, params) -> bool:
    """True when a control/bridge component looks like a Shared Job call.

    `params` is a list of (parameter_name, [values]). The component is suspected when
    it has at least _SHARED_JOB_MIN_PARAMS parameters, no SQL/script body parameter
    has a value, and every non-Name value is a ${...} token or empty (with at least
    one token). Such a component must be reported as "logic not in export, bundle
    required", never described as an inline script.
    """
    if role not in ("control", "bridge") or len(params) < _SHARED_JOB_MIN_PARAMS:
        return False
    tokens = 0
    for pname, values in params:
        key = str(pname or "").strip().lower()
        if key in _NAME_PARAM_NAMES:
            continue
        for v in values:
            s = "" if v is None else str(v).strip()
            if not s:
                continue
            if key in _SCRIPT_BODY_PARAM_NAMES or not _TOKEN.match(s):
                return False
            tokens += 1
    return tokens > 0


# ---------------------------------------------------------------------------
# DPC (.tran.yaml / .orch.yaml)
# ---------------------------------------------------------------------------
def parse_dpc_yaml(path: Path):
    try:
        import yaml
    except ImportError:
        return None  # signal: pyyaml missing
    doc = yaml.safe_load(path.read_text()) or {}
    ptype = doc.get("type", "")
    comps = (doc.get("pipeline", {}) or {}).get("components", {}) or {}
    out, edges = [], []
    for name, body in comps.items():
        body = body or {}
        params = body.get("parameters", {}) or {}
        ctype = body.get("type", "")
        role = _classify(ctype)
        out.append({
            "name": name,
            "type": ctype,
            # type-driven, never overridden by the pipeline type
            "role": role,
            "in_pipeline_type": ptype,
            "target": params.get("targetTable") or params.get("table"),
            "schema": params.get("schema"),
            "database": params.get("database"),
            "write_mode": _write_mode(params.get("loadOption") or params.get("truncate")),
            "shared_job_suspected": _shared_job_suspected(role, [
                (k, v if isinstance(v, list) else [v]) for k, v in params.items()
                if not isinstance(v, dict)]),
        })
        # DAG edges: DPC records each component's upstreams under `sources:`
        for src in (body.get("sources") or []):
            edges.append({"source": src, "target": name})
        for trans in (body.get("transitions") or {}).values() if isinstance(
                body.get("transitions"), dict) else []:
            for tgt in (trans if isinstance(trans, list) else [trans]):
                if isinstance(tgt, str):
                    edges.append({"source": name, "target": tgt})
    return [{"unit": path.name, "pipeline_type": ptype, "components": out, "edges": edges}]


# ---------------------------------------------------------------------------
# METL (.json / .ORCHESTRATION / .TRANSFORMATION)
# ---------------------------------------------------------------------------
def _slot_value(pv):
    try:
        return pv["elements"]["1"]["values"]["1"]["value"]
    except Exception:
        return None


def _metl_param(c, names) -> str | None:
    """Look a METL parameter up by its `name` field rather than its numeric slot.

    METL parameter slots are not stable across component types, but the `name`
    field is usually human-meaningful ("Name", "Target Table", "Schema", "Truncate").
    """
    for pv in (c.get("parameters") or {}).values():
        if isinstance(pv, dict) and pv.get("name") in names:
            return _slot_value(pv)
    return None


def _metl_comp_name(c):
    """The component's display name.

    Slot 1 always holds the name, but its `name` label is NOT always "Name" --
    e.g. a Start component labels slot 1 `"Start"`. Try the label first, then
    fall back to slot 1 positionally, which is the stable location.
    """
    return _metl_param(c, ("Name", "Component Name")) or \
        _slot_value((c.get("parameters") or {}).get("1") or {})


def _metl_all_params(c):
    """Every METL parameter as (name, [values]), across all grid rows and columns."""
    out = []
    for pv in (c.get("parameters") or {}).values():
        if not isinstance(pv, dict):
            continue
        values = [v.get("value")
                  for el in (pv.get("elements") or {}).values() if isinstance(el, dict)
                  for v in (el.get("values") or {}).values() if isinstance(v, dict)]
        out.append((pv.get("name"), values))
    return out


# METL connector collections -> edge kind. Transformation jobs use `connectors`
# for data flow; orchestration jobs carry the control-flow semantics across five
# separate collections. Emitting the kind is what makes the Step-8 orchestration
# handoff spec generatable instead of hand-written.
_CONNECTOR_KINDS = {
    "connectors": "flow",
    "successConnectors": "on_success",
    "failureConnectors": "on_failure",
    "unconditionalConnectors": "unconditional",
    "trueConnectors": "on_true",
    "falseConnectors": "on_false",
    "iterationConnectors": "iteration",
}


def _metl_jobs(doc):
    """Yield (job_name, job_type, body) across the METL JSON variants."""
    def jtype(body, info=None):
        raw = ((info or {}).get("type") or body.get("JobType") or "")
        if "tran" in raw.lower():
            return "transformation"
        if "orch" in raw.lower():
            return "orchestration"
        return "transformation" if (
            "connectors" in body and "successConnectors" not in body) else "orchestration"

    if "job" in doc and "info" in doc:                       # git per-job
        yield (doc["info"].get("name", "<job>"), jtype(doc["job"], doc["info"]), doc["job"])
    elif "objects" in doc:                                   # older export
        for o in doc["objects"]:
            body = o.get("jobObject") or o.get("job") or {}
            yield (o.get("info", {}).get("name", "<obj>"), jtype(body, o.get("info")), body)
    elif "jobsTree" in doc:                                  # newer export
        # Recover real job names from jobsTree rather than emitting "<orch>"/"<tran>".
        names = _jobs_tree_names(doc.get("jobsTree"))
        for j in doc.get("orchestrationJobs", []):
            yield (names.get(str(j.get("id")), f"orchestration:{j.get('id')}"),
                   "orchestration", j)
        for j in doc.get("transformationJobs", []):
            yield (names.get(str(j.get("id")), f"transformation:{j.get('id')}"),
                   "transformation", j)


def _jobs_tree_names(tree, acc=None):
    """Flatten jobsTree into {job_id: name}. Shape varies; walk defensively."""
    acc = {} if acc is None else acc
    if isinstance(tree, dict):
        jid = tree.get("id") or tree.get("jobID") or tree.get("jobId")
        nm = tree.get("name") or tree.get("text")
        if jid is not None and nm:
            acc[str(jid)] = nm
        for v in tree.values():
            _jobs_tree_names(v, acc)
    elif isinstance(tree, list):
        for v in tree:
            _jobs_tree_names(v, acc)
    return acc


def parse_metl_json(path: Path):
    doc = json.loads(path.read_text())
    units = []
    for name, jtype, body in _metl_jobs(doc):
        comps, by_id = [], {}
        for cid, c in (body.get("components", {}) or {}).items():
            impl = c.get("implementationID")
            ctype = METL_IMPL.get(impl, f"impl:{impl}")
            cname = _metl_comp_name(c) or cid
            by_id[str(c.get("id", cid))] = cname
            role = _classify(ctype)
            all_params = _metl_all_params(c)
            comps.append({
                "name": cname,
                "type": ctype,
                "implementation_id": impl,
                # type-driven, never overridden by the job type
                "role": role,
                "in_pipeline_type": jtype,
                "target": _metl_param(c, _TARGET_PARAM_NAMES),
                "schema": _metl_param(c, _SCHEMA_PARAM_NAMES),
                "database": _metl_param(c, _DATABASE_PARAM_NAMES),
                "write_mode": _write_mode(_metl_param(c, _MODE_PARAM_NAMES)),
                "parameter_count": len(all_params),
                "shared_job_suspected": _shared_job_suspected(role, all_params),
            })
        # DAG edges across every connector collection: {cid: {sourceID, targetID}}
        edges = []
        for coll, kind in _CONNECTOR_KINDS.items():
            for conn in (body.get(coll, {}) or {}).values():
                if not isinstance(conn, dict):
                    continue
                s, t = conn.get("sourceID"), conn.get("targetID")
                if s is None or t is None:
                    continue
                edges.append({
                    "source": by_id.get(str(s), f"id:{s}"),
                    "target": by_id.get(str(t), f"id:{t}"),
                    "kind": kind,
                })
        units.append({"unit": f"{path.name}:{name}", "pipeline_type": jtype,
                      "components": comps, "edges": edges})
    return units


# ---------------------------------------------------------------------------
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
            for pat in ("*.tran.yaml", "*.orch.yaml", "*.json",
                        "*.ORCHESTRATION", "*.TRANSFORMATION", "*.melt"):
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
    unknown = roles.count("unknown")
    unknown_detail = [
        {"unit": u["unit"], "name": c["name"], "type": c["type"],
         "implementation_id": c.get("implementation_id")}
        for u in units for c in u["components"] if c["role"] == "unknown"
    ]
    # Parity targets: every transformation component that writes a table is a
    # Step-5 comparison target. Missing targets are reported so the gap is visible
    # rather than silently absent.
    parity_targets = [
        {"unit": u["unit"], "component": c["name"], "target": c["target"],
         "schema": c.get("schema"), "database": c.get("database"),
         "write_mode": c.get("write_mode")}
        for u in units for c in u["components"]
        if c["role"] == "transformation" and c["type"] in ("table-output", "rewrite-table")
    ]
    # Control-flow edges are the input to the Step-8 orchestration handoff spec
    # (foundations -> orchestration-handoff.md). Surfacing them by kind means the
    # failure branches and conditional paths do not have to be rediscovered by hand.
    control_flow = [
        {"unit": u["unit"], **e}
        for u in units for e in (u.get("edges") or [])
        if e.get("kind") in ("on_failure", "on_true", "on_false", "iteration")
    ]
    # Suspected Shared Jobs: their logic is not in the export. They go on the Step-1
    # checkpoint list and the Step-8 handoff, and the inventory gate requires an
    # answer for inputs.shared_job_bundles_path.
    shared_jobs = [
        {"unit": u["unit"], "name": c["name"], "type": c["type"],
         "implementation_id": c.get("implementation_id"),
         "parameter_count": c.get("parameter_count")}
        for u in units for c in u["components"] if c.get("shared_job_suspected")
    ]
    return {
        "schema_version": 1,
        "units": units,
        "parity_targets": parity_targets,
        "control_flow_edges": control_flow,
        "unknown_components": unknown_detail,
        "shared_job_suspected": shared_jobs,
        "yaml_pyyaml_missing": yaml_missing,
        "summary": {
            "unit_count": len(units),
            "total_components": len(roles),
            "transformation_components_migratable": transform,
            # Denominator excludes unknown, EL, control and bridge components.
            "coverage_denominator": transform,
            "el_ingestion_out_of_scope": roles.count("el_ingestion"),
            "control_out_of_scope": roles.count("control"),
            "bridges": roles.count("bridge"),
            "unknown_needs_mapping": unknown,
            "shared_job_suspected_count": len(shared_jobs),
            "edge_count": sum(len(u.get("edges") or []) for u in units),
            "control_flow_edge_count": len(control_flow),
            "parity_targets_found": len(parity_targets),
            "parity_targets_missing_name": sum(
                1 for t in parity_targets if not t["target"]),
            "append_mode_targets": sum(
                1 for t in parity_targets if t.get("write_mode") == "append"),
        },
    }


def main(argv):
    args, out_path, want_json, strict = [], None, "--json" in argv, "--strict" in argv
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--out":
            out_path = Path(argv[i + 1]); i += 2; continue
        if a in ("--help", "-h"):
            print(__doc__); return 0
        if a in ("--json", "--strict"):
            i += 1; continue
        args.append(a); i += 1

    if not args:
        print(__doc__)
        return 2

    inv = build_inventory([Path(a) for a in args])
    s = inv["summary"]

    if inv["yaml_pyyaml_missing"]:
        print("NOTE: a DPC .yaml pipeline was skipped because `pyyaml` is not installed.\n"
              "      Run `pip install pyyaml` and re-run. (Inventory by hand with\n"
              "      parsing-matillion-pipelines.md only on the dbt platform.)", file=sys.stderr)

    payload = {k: v for k, v in inv.items() if k != "yaml_pyyaml_missing"}
    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2))
        print(f"wrote {out_path}", file=sys.stderr)
    if want_json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Matillion inventory: {s['unit_count']} pipeline/job(s), "
              f"{s['total_components']} components, {s['edge_count']} DAG edges")
        print(f"  transformation (migratable): {s['transformation_components_migratable']}"
              f"  <- coverage denominator")
        print(f"  EL ingestion: {s['el_ingestion_out_of_scope']}  |  "
              f"control: {s['control_out_of_scope']}  |  "
              f"run-* bridges: {s['bridges']}")
        print(f"  parity targets: {s['parity_targets_found']}"
              f" ({s['parity_targets_missing_name']} missing a target name,"
              f" {s['append_mode_targets']} append-mode -> incremental + unique_key)")
        print(f"  control-flow edges (for the orchestration handoff): "
              f"{s['control_flow_edge_count']}")
        if s["unknown_needs_mapping"]:
            print(f"  ** unknown (NOT counted in the denominator): "
                  f"{s['unknown_needs_mapping']} -- map these before trusting coverage:")
            for u in inv["unknown_components"]:
                print(f"       {u['name']:38s} impl={u['implementation_id']}")
        if s["shared_job_suspected_count"]:
            print(f"  ** suspected Shared Job(s): {s['shared_job_suspected_count']} -- "
                  f"logic not in export, .melt bundle required:")
            for u in inv["shared_job_suspected"]:
                print(f"       {u['name']:38s} ({u['parameter_count']} parameters, "
                      f"all ${{...}} pass-throughs)")
        for u in inv["units"]:
            print(f"\n[{u['pipeline_type']}] {u['unit']}  "
                  f"({len(u['components'])} components, {len(u.get('edges') or [])} edges)")
            for c in u["components"]:
                tag = "" if c["role"] == "transformation" else f"  <{c['role']}>"
                tgt = f"  -> {c['target']}" if c.get("target") else ""
                print(f"    {c['name']:30s} {c['type']}{tag}{tgt}")

    if strict and s["unknown_needs_mapping"]:
        print(f"\nSTRICT: {s['unknown_needs_mapping']} component(s) unmapped. "
              f"Map them in METL_IMPL or record them as residual.", file=sys.stderr)
        return 4
    if inv["yaml_pyyaml_missing"] and not inv["units"]:
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
