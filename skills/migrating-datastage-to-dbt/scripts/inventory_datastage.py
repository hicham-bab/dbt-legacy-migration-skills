#!/usr/bin/env python3
"""Deterministic inventory of IBM DataStage exports (.dsx, stdlib only).

Parses the DataStage Interchange (DSX) text format: `BEGIN/END HEADER`, `BEGIN/END DSJOB`
(one export file can hold many jobs - a whole-project export concatenates them), `BEGIN/END
DSRECORD` (the job's stages, link pins, and a `CContainerView` record listing every stage), and
nested `BEGIN/END DSSUBRECORD` (stage properties and column metadata, grouped under whichever of
`Properties`/`Columns` preceded them).

Emits a normalized inventory with **one entry per job** as the coverage denominator (like the
Informatica skill - a job's stage graph is one modeling unit, not each stage), splitting ETL
**transformation** stages (Join, Filter, Transformer, Aggregator, Sort, Lookup, Funnel, Remove
Duplicates, Modify, Surrogate Key Generator, Change Capture/Apply, SCD...) from **I/O** stages
(Sequential File / Dataset / Lookup File Set / DB connectors - become dbt `sources`/the mart
table) and flagging CDC/SCD stages (-> snapshot candidates) and custom-code stages
(Java/Wrapper/Build/BASIC routines) as residual for human review. A job whose stage graph has no
recognized stage types at all (likely a Job Sequence / job-control job, not a parallel ETL job) is
routed to `needs_review_jobs` and excluded from the coverage denominator - see
parsing-datastage-jobs.md for why sequence-job detection is heuristic here.

Usage: python3 inventory_datastage.py <file-or-dir> [...] [--json]
The container/record grammar (HEADER/DSJOB/DSRECORD/DSSUBRECORD, CContainerView's pipe-delimited
StageList/StageTypeIDs/StageNames, per-stage InputPins/OutputPins, per-pin Partner links) is
verified against a genuine IBM InfoSphere DataStage 8.7 export (Java Integration Stage samples:
custom/debug/I-O stages, multi-output links) plus a broader public job set exercising Join, Filter,
Transformer, Aggregator, Sort, Remove Duplicates, Lookup, Merge, Funnel, Pivot, Surrogate Key, and
Change Capture/CDC stages (provenance of that second set as a captured production export is
unconfirmed - see ATTRIBUTION.md). The stage-type -> kind table also carries IBM-doc-sourced
entries not seen in either sample set - treat those as a starting answer key and verify against the
migrator's actual export (see parsing-datastage-jobs.md).
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

BEGIN_RE = re.compile(r'^BEGIN (\S+)$')
END_RE = re.compile(r'^END (\S+)$')
BLOCK_RE = re.compile(r'^(\S+)\s*=\+=\+=\+=$')
SCALAR_RE = re.compile(r'^(\S+)\s+"(.*)"$')
BLOCK_DELIM = '=+=+=+='

# Stage `StageType` (DPC-equivalent kebab `type`) -> kind.
# "verified" = seen in a real exported .dsx; "doc" = IBM DataStage documentation, not yet
# file-verified here - confirm against the migrator's real export before trusting blindly.
IO_TYPES_VERIFIED = {"PxSequentialFile"}
IO_TYPES_DOC = {
    "PxDataSet", "PxFileSet", "PxLookupFileSet", "PxExternalSource", "PxExternalTarget",
    "PxExternalFilter", "CODBCConnectorPX", "PxODBCConnectorPX", "PxDB2", "PxOracleConnectorPX",
    "PxTeradataConnectorPX", "PxNetezza", "PxInformixCDC", "CWebServicesClient", "CFTPStage",
    "PxComplexFlatFile", "PxXMLStage",
}
TRANSFORM_TYPES_VERIFIED = {"PxJoin", "PxFilter", "CTransformerStage"}
TRANSFORM_TYPES_DOC = {
    "PxAggregator", "PxSort", "PxRemoveDups", "PxRemDup", "PxRemoveDuplicates", "PxLookup", "PxFunnel", "PxModify",
    "PxChangeCapture", "PxChangeApply", "PxSCD", "PxSurrogateKeyGenerator", "PxMerge",
    "PxPivotEnterprise", "PxUnpivot", "PxEncode", "PxDecode",
}
DEBUG_TYPES_VERIFIED = {"PxPeek", "PxRowGenerator"}
DEBUG_TYPES_DOC = {"PxHead", "PxTail", "PxSample", "PxWaveGenerator", "PxColumnGenerator"}
PASSTHROUGH_TYPES_DOC = {"PxCopy"}
CUSTOM_TYPES_VERIFIED = {"JavaStagePX"}
CUSTOM_TYPES_DOC = {"CBuildStage", "CWrapperStage", "CParallelRoutineStage", "CBasicTransformerStage"}
SCD_TYPES = {"PxChangeCapture", "PxChangeApply", "PxSCD"}

KIND_OF = {}
for t in IO_TYPES_VERIFIED | IO_TYPES_DOC:
    KIND_OF[t] = "io"
for t in TRANSFORM_TYPES_VERIFIED | TRANSFORM_TYPES_DOC:
    KIND_OF[t] = "transform"
for t in DEBUG_TYPES_VERIFIED | DEBUG_TYPES_DOC:
    KIND_OF[t] = "debug"
for t in PASSTHROUGH_TYPES_DOC:
    KIND_OF[t] = "passthrough"
for t in CUSTOM_TYPES_VERIFIED | CUSTOM_TYPES_DOC:
    KIND_OF[t] = "custom"


def _classify(stage_type: str) -> str:
    return KIND_OF.get(stage_type, "unknown")


def _role(kind: str, has_in: bool, has_out: bool) -> str:
    if kind == "io":
        if has_out and not has_in:
            return "source"
        if has_in and not has_out:
            return "target"
        return "io_passthrough"
    if kind == "debug":
        return "debug"
    if kind == "passthrough":
        return "passthrough"
    if kind == "custom":
        return "custom_code"
    if kind == "transform":
        return "transform"
    return "unknown"


def _parse_scope(lines: list[str], i: int, end_tag: str | None):
    """Parse sibling prop/record entries until `END <end_tag>` (or EOF if end_tag is None).

    Returns (props: dict of last-scalar-wins values, order: list of entries in encounter order,
    next_index). `order` entries are ('prop', key, value) or ('record', tag, props, order).
    """
    props: dict[str, str] = {}
    order: list[tuple] = []
    n = len(lines)
    while i < n:
        s = lines[i].strip()
        if not s:
            i += 1
            continue
        m = END_RE.match(s)
        if m:
            i += 1
            if end_tag is None or m.group(1) == end_tag:
                return props, order, i
            # mismatched END at top level while scanning for BEGIN blocks - keep going
            continue
        m = BEGIN_RE.match(s)
        if m:
            tag = m.group(1)
            sub_props, sub_order, i = _parse_scope(lines, i + 1, tag)
            order.append(("record", tag, sub_props, sub_order))
            continue
        m = BLOCK_RE.match(s)
        if m:
            key = m.group(1)
            i += 1
            buf = []
            while i < n and lines[i].strip() != BLOCK_DELIM:
                buf.append(lines[i])
                i += 1
            i += 1  # skip the closing delimiter line
            val = "\n".join(buf)
            props[key] = val
            order.append(("prop", key, val))
            continue
        m = SCALAR_RE.match(s)
        if m:
            key, val = m.group(1), m.group(2)
            props[key] = val
            order.append(("prop", key, val))
            i += 1
            continue
        i += 1  # unrecognized line (stray text) - skip
        if end_tag is None:
            continue
    return props, order, i


def _bucket_subrecords(order: list[tuple]) -> dict[str, list[dict]]:
    """Group DSSUBRECORD children by the Properties/Columns marker that preceded them."""
    buckets: dict[str, list[dict]] = {"properties": [], "columns": [], "other": []}
    current = "other"
    for entry in order:
        if entry[0] == "prop":
            _, key, _val = entry
            if key == "Properties":
                current = "properties"
            elif key == "Columns":
                current = "columns"
        elif entry[0] == "record" and entry[1] == "DSSUBRECORD":
            buckets[current].append(entry[2])
    return buckets


def _pipe_list(props: dict, key: str) -> list[str]:
    raw = props.get(key, "")
    return raw.split("|") if raw else []


def parse_dsx(path: Path) -> list[dict]:
    text = path.read_text(errors="replace")
    lines = text.splitlines()
    _top_props, top_order, _ = _parse_scope(lines, 0, None)
    jobs = []
    for entry in top_order:
        if entry[0] == "record" and entry[1] == "DSJOB":
            jobs.append(_parse_job(entry[2], entry[3], path))
    return jobs


def _parse_job(job_props: dict, job_order: list[tuple], path: Path) -> dict:
    records = [(e[2], e[3]) for e in job_order if e[0] == "record" and e[1] == "DSRECORD"]
    by_id = {p.get("Identifier"): (p, o) for p, o in records}

    root = next((p for p, _ in records if p.get("OLEType") == "CJobDefn"), {})
    containers = [p for p, _ in records if p.get("OLEType") == "CContainerView"]

    stages = {}
    edges = []
    for cv in containers:
        ids = _pipe_list(cv, "StageList")
        types = _pipe_list(cv, "StageTypeIDs")
        names = _pipe_list(cv, "StageNames")
        for sid, stype, sname in zip(ids, types, names):
            srec, _ = by_id.get(sid, ({}, []))
            if not stype.strip():
                # Blank StageTypeIDs entry: a canvas annotation (CAnnotation), not an ETL stage.
                continue
            stype = stype.strip()
            in_pins = _pipe_list(srec, "InputPins")
            out_pins = _pipe_list(srec, "OutputPins")
            kind = _classify(stype)
            stages[sid] = {
                "id": sid, "name": sname, "type": stype, "kind": kind,
                "role": _role(kind, bool(in_pins), bool(out_pins)),
                "input_pins": in_pins, "output_pins": out_pins,
            }
            for pin_id in out_pins:
                pin_props, pin_order = by_id.get(pin_id, ({}, []))
                partner = pin_props.get("Partner", "")
                if "|" in partner:
                    to_stage_id, _to_pin = partner.split("|", 1)
                    to_rec, _ = by_id.get(to_stage_id, ({}, []))
                    edges.append({
                        "from": sname, "to": to_rec.get("Name", to_stage_id),
                        "link": pin_props.get("Name", pin_id),
                    })

    stage_list = list(stages.values())
    is_etl_job = any(s["kind"] != "unknown" for s in stage_list)
    scd_stages = [s["name"] for s in stage_list if s["type"] in SCD_TYPES]
    residual = sorted({s["type"] for s in stage_list if s["kind"] in ("custom", "unknown")})
    modeling = [s for s in stage_list if s["role"] in ("transform", "custom_code")]
    glue = [s for s in stage_list if s["role"] in ("source", "target", "io_passthrough",
                                                    "debug", "passthrough")]

    return {
        "file": path.name,
        "name": job_props.get("Identifier") or root.get("Name"),
        "category": root.get("Category"),
        "job_type": root.get("JobType"),
        "is_etl_job": is_etl_job,
        "stages": stage_list,
        "edges": edges,
        "stage_count": len(stage_list),
        "modeling_stage_count": len(modeling),
        "glue_stage_count": len(glue),
        "scd_stages": scd_stages,
        "residual_stage_types": residual,
    }


def build_inventory(paths: list[Path]) -> dict:
    files = []
    for p in paths:
        if p.is_dir():
            files.extend(sorted(p.glob("*.dsx")) + sorted(p.glob("*.DSX")))
        else:
            files.append(p)

    jobs = [j for f in files for j in parse_dsx(f)]
    etl_jobs = [j for j in jobs if j["is_etl_job"]]
    needs_review = [j for j in jobs if not j["is_etl_job"]]
    scd_jobs = [j["name"] for j in etl_jobs if j["scd_stages"]]
    residual_types = sorted({t for j in etl_jobs for t in j["residual_stage_types"]})

    return {
        "jobs": jobs,
        "summary": {
            "job_count": len(jobs),
            "etl_job_count": len(etl_jobs),
            "coverage_denominator": len(etl_jobs),   # one dbt model (family) per ETL job
            "needs_review_job_count": len(needs_review),
            "needs_review_jobs": [j["name"] for j in needs_review],
            "total_stages": sum(j["stage_count"] for j in etl_jobs),
            "modeling_stages": sum(j["modeling_stage_count"] for j in etl_jobs),
            "glue_stages": sum(j["glue_stage_count"] for j in etl_jobs),
            "scd_jobs": scd_jobs,
            "residual_stage_types": residual_types,
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
    print(f"DataStage inventory: {s['job_count']} job(s), {s['etl_job_count']} ETL (parallel) job(s)")
    print(f"  coverage denominator (ETL jobs): {s['coverage_denominator']}")
    if s["needs_review_job_count"]:
        print(f"  needs review (no recognized stage graph - likely a Sequence/control job): "
              f"{s['needs_review_jobs']}")
    print(f"  stages: {s['total_stages']} total, {s['modeling_stages']} modeling, "
          f"{s['glue_stages']} I/O or glue")
    if s["scd_jobs"]:
        print(f"  CDC/SCD stages detected -> snapshot candidates: {s['scd_jobs']}")
    if s["residual_stage_types"]:
        print(f"  residual stage types (custom code / unrecognized): {s['residual_stage_types']}")
    for j in inv["jobs"]:
        tag = "" if j["is_etl_job"] else "  <needs review>"
        print(f"\n[{j['file']}] {j['name']}{tag}  ({j['stage_count']} stages)")
        for st in j["stages"]:
            rtag = "" if st["role"] == "transform" else f"  <{st['role']}>"
            print(f"    {st['name']:28s} {st['type']:20s}{rtag}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
