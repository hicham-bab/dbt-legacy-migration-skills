#!/usr/bin/env python3
"""Migration gates for a legacy->dbt migration (stdlib only, pyyaml optional).

OPTIONAL FAST PATH. These gates are a convenience for local checkouts. Every gate
has a documented no-Python equivalent in ../SKILL.md, because the skill's declared
target (the dbt platform) cannot install or run Python. The ARTIFACT and the PASS
CRITERIA are the contract; this script is one way to check them.

Gates:
  decisions   Step 0 -> Step 1. Validate migration_manifest.yml (or the older flat
              migration_decisions.yml). Blocks model building.
  inventory   Step 1 -> Step 2. Validate 01_inventory.json: non-empty, no unmapped
              components, parity targets present when parity_scope demands them.
  parity      Step 5 -> Step 6. Verify every in-scope model has a parity record AND
              that the record compared EVERY column. A single-column diff is a false
              pass, so columns_compared < columns_total is a FAIL.
  coverage    Step 7 -> Step 8. RECOMPUTE gross/in-scope/residual coverage from the
              artifacts rather than accepting a typed number. Applies the >=95% gate
              and the <=5% residual ceiling to the GROSS figure, honouring waivers.

Usage:
    python3 preflight_decisions.py decisions [--file migration_manifest.yml]
                                             [--profiles ~/.dbt/profiles.yml]
    python3 preflight_decisions.py inventory  --inventory migration/01_inventory.json
                                             [--file migration_manifest.yml]
    python3 preflight_decisions.py parity     --parity migration/05_parity.json
                                              --inventory migration/01_inventory.json
    python3 preflight_decisions.py coverage   --inventory migration/01_inventory.json
                                              --parity  migration/05_parity.json
                                             [--waivers migration/07_waivers.json]

Called with no subcommand it runs `decisions`, preserving the original behaviour.

Exit codes: 0 pass | 1 gate not satisfied | 2 usage error
"""
from __future__ import annotations
import json
import os
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Step-0 decision vocabulary. `landing_spot` is REQUIRED, not optional: SKILL.md
# forbids building in a temp dir, so "where" must be answered before Step 3.
# ---------------------------------------------------------------------------
REQUIRED_ENUMS = {
    "target_modeling": {"kimball", "datavault", "star", "layered"},
    # duckdb is included for local dev / eval runs (dbt-duckdb); the rest are the cloud targets
    "data_warehouse": {"snowflake", "databricks", "bigquery", "redshift", "duckdb"},
    "packages_mode": {"external_hub", "self_contained_macros"},
    "dbt_runtime": {"fusion", "core"},
    "landing_mode": {"new_standalone", "fold_into_existing"},
    "parity_scope": {"all_marts", "tiered", "sampled"},
}
REQUIRED_FREE = ("landing_spot",)
# Feasibility answers. `null` is NOT acceptable here -- "unknown" is the state this
# gate exists to eliminate. `false` is acceptable and re-scopes later steps.
REQUIRED_ACCESS = ("legacy_prod_readable", "metering_views_readable",
                   "warehouse_catalog_readable")

QUESTIONS = {
    "target_modeling":
        "Which target modeling approach? kimball | datavault | star | layered "
        "(datavault = auditable hubs/links/sats; kimball = conformed dims+facts; "
        "star = one lightweight star; layered = faithful port, lowest risk).",
    "data_warehouse":
        "Which data warehouse are we targeting? snowflake | databricks | bigquery | "
        "redshift | duckdb (this sets the SQL dialect the generated models use; "
        "duckdb = local dev/eval).",
    "packages_mode":
        "External dbt packages (hub.getdbt.com only) or self-contained hand-made "
        "macros? external_hub | self_contained_macros.",
    "dbt_runtime":
        "dbt Fusion or dbt Core? fusion | core (Fusion's real-time compile is the "
        "free iteration gate; it also changes which SQL forms are allowed).",
    "landing_mode":
        "A new standalone dbt project, or fold into an existing one? "
        "new_standalone | fold_into_existing.",
    "landing_spot":
        "Which directory should the dbt project be built in? Give a real path -- "
        "models are never built in a temp dir and copied over.",
    "parity_scope":
        "Which outputs get data-parity proof? all_marts | tiered | sampled. "
        "If tiered or sampled, also set parity_tier_rule.",
    "legacy_prod_readable":
        "Can we still query the LEGACY PRODUCTION output tables? true | false. "
        "If false, Step-5 data parity -- the definition of done -- is unachievable "
        "and the engagement must be re-scoped explicitly.",
    "metering_views_readable":
        "Do we have read access to warehouse metering (account_usage / "
        "JOBS_BY_PROJECT / system.billing)? true | false. If false, Step 6 produces "
        "the labelled TCO estimate only.",
    "warehouse_catalog_readable":
        "Can we read the warehouse catalog (information_schema)? true | false. "
        "Needed for codegen generate_source and Multi-Table Input enumeration.",
}


# ---------------------------------------------------------------------------
# YAML loading. Prefer pyyaml; fall back to a minimal nested-mapping reader so the
# gate still works on a stdlib-only box. The fallback handles nested maps, scalars,
# and simple inline lists -- enough for the manifest template.
# ---------------------------------------------------------------------------
def _coerce(v: str):
    s = v.strip().strip("'\"")
    if s in ("", "null", "~", "None"):
        return None
    if s in ("true", "True", "yes"):
        return True
    if s in ("false", "False", "no"):
        return False
    if s in ("{}", "[]"):
        return {} if s == "{}" else []
    return s


def _mini_yaml(text: str) -> dict:
    """Indentation-based reader for the manifest subset. Not a general YAML parser."""
    root: dict = {}
    stack = [(-1, root)]
    for raw in text.splitlines():
        line = raw.split(" #", 1)[0].rstrip() if " #" in raw else raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        body = line.strip()
        if body.startswith("- "):
            continue  # list items are not needed by any gate check below
        m = re.match(r"^([A-Za-z0-9_]+)\s*:\s*(.*)$", body)
        if not m:
            continue
        key, val = m.group(1), m.group(2)
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1] if stack else root
        if val == "":
            child: dict = {}
            parent[key] = child
            stack.append((indent, child))
        else:
            parent[key] = _coerce(val)
    return root


def load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    text = path.read_text()
    try:
        import yaml
    except ImportError:
        return _mini_yaml(text)
    try:
        data = yaml.safe_load(text)
    except Exception as e:                      # malformed YAML is a gate failure,
        fail(f"{path} is not valid YAML: {e}",  # not a traceback
             ["Fix the syntax and re-run. Indentation and unquoted colons are the "
              "usual causes."])
    return data if isinstance(data, dict) else {}


def load_json(path: Path, label: str) -> dict:
    if not path or not path.exists():
        fail(f"missing artifact: {label} at {path}",
             ["Run the Step that produces it, or produce it by hand via the "
              "no-Python procedure in ../SKILL.md."])
    return json.loads(path.read_text())


# ---------------------------------------------------------------------------
def banner(title: str) -> None:
    print("=" * 72)
    print(title)
    print("=" * 72)


def fail(msg: str, hints=()) -> None:
    banner(f"GATE NOT SATISFIED -- {msg}")
    for h in hints:
        print(f"  {h}")
    sys.exit(1)


def detect_warehouse(profiles: Path):
    if not profiles.exists():
        return None
    for line in profiles.read_text().splitlines():
        m = re.match(r"\s*type:\s*([A-Za-z0-9_]+)", line)
        if m and m.group(1).lower() in REQUIRED_ENUMS["data_warehouse"]:
            return m.group(1).lower()
    return None


# deprecated key names accepted for backward compatibility
ALIASES = {"target_architecture": "target_modeling"}


def _flat_legacy(d: dict) -> dict:
    """Accept the older flat migration_decisions.yml shape."""
    return {"decisions": d, "access": {}, "provenance": {}, "inputs": {}}


# ---------------------------------------------------------------------------
def gate_decisions(fpath: Path, ppath: Path) -> int:
    raw = load_yaml(fpath)
    man = raw if ("decisions" in raw or "access" in raw) else _flat_legacy(raw)
    dec = {ALIASES.get(k, k): v for k, v in (man.get("decisions") or {}).items()}
    acc = man.get("access") or {}
    prov = man.get("provenance") or {}

    missing, invalid, warn = [], [], []

    for key, allowed in REQUIRED_ENUMS.items():
        val = dec.get(key)
        if val in (None, ""):
            missing.append(key)
        elif str(val).lower() not in allowed:
            invalid.append((key, val, sorted(allowed)))
    for key in REQUIRED_FREE:
        if dec.get(key) in (None, ""):
            missing.append(key)
    for key in REQUIRED_ACCESS:
        if acc.get(key) is None:
            missing.append(key)

    # conditional requirements
    if str(dec.get("landing_mode", "")).lower() == "fold_into_existing" \
            and not dec.get("existing_project_path"):
        missing.append("existing_project_path")
    if str(dec.get("parity_scope", "")).lower() in ("tiered", "sampled") \
            and not dec.get("parity_tier_rule"):
        missing.append("parity_tier_rule")

    if not prov.get("answered_by") or not prov.get("answered_at"):
        warn.append("provenance.answered_by / answered_at are empty -- these values "
                    "carry no human attestation and a reviewer cannot tell them from "
                    "agent guesses.")
    if acc.get("legacy_prod_readable") is False:
        warn.append("legacy_prod_readable is false -- Step-5 data parity is "
                    "UNACHIEVABLE. Re-scope the engagement explicitly and record the "
                    "revised definition of done before building models.")
    if acc.get("metering_views_readable") is False:
        warn.append("metering_views_readable is false -- Step 6 must produce the "
                    "labelled TCO estimate only. Do not present an estimate as a "
                    "measurement.")

    if missing or invalid:
        rec = detect_warehouse(ppath)
        banner("STOP -- migration decisions required before building any models.")
        print(f"Manifest: {fpath}  (create/complete it, then re-run)\n")
        print("Ask the migrator these questions and record their answers "
              "(recommend a default with a one-line why, but they decide):\n")
        for key in list(REQUIRED_ENUMS) + list(REQUIRED_FREE) + list(REQUIRED_ACCESS):
            if key in missing or any(k == key for k, _, _ in invalid):
                print(f"  [{key}] {QUESTIONS.get(key, 'required')}")
                if key == "data_warehouse" and rec:
                    print(f"        (detected in profiles.yml: '{rec}' -- "
                          f"recommend, but confirm)")
                print()
        for key in missing:
            if key in ("existing_project_path", "parity_tier_rule"):
                print(f"  [{key}] required because of an earlier answer.\n")
        for key, val, allowed in invalid:
            print(f"  ! '{key}' = '{val}' is not one of {allowed}")
        print("\nWrite answers into the manifest, then re-run. "
              "Do NOT create models until this exits 0.")
        return 1

    banner("Step-0 gate PASSED -- decisions recorded")
    for key in list(REQUIRED_ENUMS) + list(REQUIRED_FREE):
        print(f"  decisions.{key}: {dec.get(key)}")
    for key in REQUIRED_ACCESS:
        print(f"  access.{key}: {acc.get(key)}")
    if prov.get("answered_by"):
        print(f"  provenance: {prov.get('answered_by')} at {prov.get('answered_at')}")
    for w in warn:
        print(f"\n  WARNING: {w}")
    return 0


def gate_inventory(ipath: Path, fpath: Path) -> int:
    inv = load_json(ipath, "01_inventory.json")
    s = inv.get("summary") or {}
    dec = (load_yaml(fpath).get("decisions") or {}) if fpath else {}
    problems = []

    if not s.get("unit_count"):
        problems.append("unit_count is 0 -- nothing was parsed. A denominator of 0 "
                        "makes every later coverage figure meaningless.")
    if not s.get("coverage_denominator"):
        problems.append("coverage_denominator is 0 -- no migratable component found.")
    if s.get("unknown_needs_mapping"):
        problems.append(
            f"{s['unknown_needs_mapping']} component(s) are role `unknown`. Map them "
            f"in the inventory script's id table, or record each as documented "
            f"residual. Unknowns are excluded from the denominator, so leaving them "
            f"here understates the workload.")
    if not s.get("edge_count"):
        problems.append("edge_count is 0 -- no DAG edges. Without lineage, ref() vs "
                        "source() is a guess, and a wrong guess compiles cleanly.")
    if str(dec.get("parity_scope", "")).lower() == "all_marts":
        if not s.get("parity_targets_found"):
            problems.append("parity_scope is all_marts but no parity targets were "
                            "found. Step 5 has nothing to compare against.")
        if s.get("parity_targets_missing_name"):
            problems.append(
                f"{s['parity_targets_missing_name']} parity target(s) have no target "
                f"table name. Supply them in the manifest under "
                f"access.legacy_prod_tables.")

    if problems:
        fail("Step-1 inventory is not usable", [f"* {p}" for p in problems])
    banner("Step-1 gate PASSED -- inventory usable")
    for k in ("unit_count", "total_components", "coverage_denominator",
              "el_ingestion_out_of_scope", "control_out_of_scope", "bridges",
              "unknown_needs_mapping", "edge_count", "parity_targets_found",
              "append_mode_targets"):
        if k in s:
            print(f"  {k}: {s[k]}")
    if s.get("append_mode_targets"):
        print(f"\n  NOTE: {s['append_mode_targets']} append-mode target(s). Each needs "
              f"an incremental model with an explicit unique_key, and a "
              f"run-window-scoped parity comparison.")
    return 0


def gate_parity(ppath: Path, ipath: Path) -> int:
    """The false-pass gate. A parity record that compared one column is not parity."""
    par = load_json(ppath, "05_parity.json")
    records = par.get("models") if isinstance(par, dict) else par
    if not records:
        fail("05_parity.json contains no model records",
             ["Every model in parity_scope needs a record with columns_compared, "
              "columns_total, and a disposition for each difference."])
    problems = []
    for r in records:
        name = r.get("model", "<unnamed>")
        cc, ct = r.get("columns_compared"), r.get("columns_total")
        if cc is None or ct is None:
            problems.append(f"{name}: missing columns_compared / columns_total. "
                            f"Completeness cannot be verified.")
        elif ct and cc < ct:
            problems.append(f"{name}: compared {cc} of {ct} columns. A partial diff "
                            f"is a FALSE PASS, not a pass.")
        diffs = r.get("differences") or []
        undisposed = [d for d in diffs
                      if not d.get("category") or not d.get("disposition")]
        if undisposed:
            problems.append(f"{name}: {len(undisposed)} difference(s) with no "
                            f"category/disposition. Every difference must be "
                            f"explained and marked accept or fix.")
    if ipath and ipath.exists():
        inv = json.loads(ipath.read_text())
        want = {t["target"] for t in (inv.get("parity_targets") or []) if t.get("target")}
        have = {r.get("legacy_table") or r.get("model") for r in records}
        gap = {w for w in want if w and w not in have and
               not any(str(w).lower() in str(h).lower() for h in have if h)}
        if gap:
            problems.append(f"no parity record for: {sorted(gap)}")
    if problems:
        fail("Step-5 parity is incomplete", [f"* {p}" for p in problems])
    banner("Step-5 gate PASSED -- parity complete and fully attributed")
    print(f"  models with parity records: {len(records)}")
    print(f"  all columns compared on every model: yes")
    return 0


def gate_coverage(ipath: Path, ppath: Path, wpath: Path | None) -> int:
    """Recompute, never accept. The agent must not both produce and grade the number."""
    inv = load_json(ipath, "01_inventory.json")
    par = load_json(ppath, "05_parity.json")
    records = par.get("models") if isinstance(par, dict) else par
    if not isinstance(records, list) or not records:
        fail("05_parity.json has no `models` list",
             ['Expected {"models": [...]} or a top-level list of parity records.'])
    denom = (inv.get("summary") or {}).get("coverage_denominator") or 0
    if not denom:
        fail("coverage_denominator is 0 -- cannot compute coverage")

    validated_names = {r.get("model") or r.get("legacy_table") for r in records
                       if isinstance(r, dict) and str(r.get("parity", "")).lower()
                       in ("pass", "passed", "identical", "true")}
    validated_names.discard(None)
    validated = len(validated_names)
    scope = par.get("engagement_scope") if isinstance(par, dict) else None
    scope = scope if isinstance(scope, int) and scope > 0 else denom
    residual_raw = (par.get("documented_residual") if isinstance(par, dict) else None)
    residual_names = set(residual_raw) if isinstance(residual_raw, list) else set()
    residual = len(residual_names) if isinstance(residual_raw, list) \
        else (residual_raw or 0)

    gross = 100.0 * validated / denom
    in_scope = 100.0 * validated / scope if scope else 0.0
    residual_pct = 100.0 * residual / denom

    waivers = []
    if wpath and wpath.exists():
        w = json.loads(wpath.read_text())
        waivers = w.get("waivers") if isinstance(w, dict) else w
        waivers = waivers if isinstance(waivers, list) else []
    complete_waivers = [wv for wv in waivers if isinstance(wv, dict) and all(
        wv.get(k) for k in ("component", "reason", "accepted_by", "date"))]
    incomplete = [wv for wv in waivers if wv not in complete_waivers]

    # A granted waiver removes a component from the GATE's reachable maximum. It does
    # NOT remove it from the reported denominator. This is the crucial difference from
    # simply dividing by (migratable - residual): the reported gross figure still says
    # 92%, the exception stays visible and attributable, but a migration blocked by
    # something genuinely outside dbt is not permanently failed by arithmetic.
    #
    # Three abuses this must resist, each of which turns a failing number into a pass:
    #   1. a waiver naming a component that appears nowhere in the workload
    #   2. the same component waived N times to inflate the count
    #   3. a waiver for a component that was in fact migrated and validated
    # So: dedupe by component name, and count only waivers that resolve to a real,
    # unvalidated component of the inventoried workload.
    inventory_names = {c.get("name") for u in (inv.get("units") or [])
                       for c in (u.get("components") or [])}
    inventory_names |= {t.get("target") for t in (inv.get("parity_targets") or [])}
    inventory_names.discard(None)

    waived_names = {wv["component"] for wv in complete_waivers}
    unknown_waivers = sorted(n for n in waived_names
                             if n not in inventory_names and n not in residual_names)
    vacuous_waivers = sorted(n for n in waived_names if n in validated_names)
    effective_waived = waived_names - set(unknown_waivers) - set(vacuous_waivers)
    waived = len(effective_waived)

    gate_denom = denom - waived
    effective = (100.0 * validated / gate_denom) if gate_denom > 0 else 0.0

    banner("Step-7 coverage -- RECOMPUTED from artifacts")
    print(f"  migratable inventoried (denominator) : {denom}")
    print(f"  engagement scope                     : {scope}")
    print(f"  migrated AND parity-validated        : {validated}")
    print(f"  documented residual                  : {residual}")
    print(f"  waived (complete waivers on record)  : {waived}")
    print()
    print(f"  gross_coverage    = {validated}/{denom} = {gross:.1f}%   "
          f"<- always report this")
    print(f"  in_scope_coverage = {validated}/{scope} = {in_scope:.1f}%   "
          f"(context only, never 'the' number)")
    print(f"  residual_pct      = {residual}/{denom} = {residual_pct:.1f}%")
    if waived:
        print(f"  effective (gated)  = {validated}/{gate_denom} = {effective:.1f}%   "
              f"<- the >=95% gate, waived components excluded from the maximum")

    problems = []
    if unknown_waivers:
        problems.append(
            f"waiver(s) name component(s) that appear nowhere in the inventory or the "
            f"residual list: {unknown_waivers}. A waiver for a component that does not "
            f"exist is the same metric-gaming this gate exists to prevent.")
    if vacuous_waivers:
        problems.append(
            f"waiver(s) name component(s) that were migrated AND validated: "
            f"{vacuous_waivers}. Nothing to waive; remove them.")
    if validated > gate_denom:
        problems.append(
            f"validated ({validated}) exceeds the waived-adjusted denominator "
            f"({gate_denom}). The parity records and the inventory disagree -- "
            f"reconcile them rather than reporting coverage above 100%.")
    if effective < 95.0:
        problems.append(
            f"coverage {effective:.1f}% is below the 95% gate"
            + (f" (waived-adjusted: {validated}/{gate_denom})" if waived else "")
            + ". Migrate more, or record a waiver for each component that genuinely "
              "cannot be migrated.")
    if residual_pct > 5.0:
        if complete_waivers:
            print(f"\n  residual {residual_pct:.1f}% exceeds the 5% ceiling; "
                  f"{len(complete_waivers)} waiver(s) on record:")
            for wv in complete_waivers:
                print(f"    - {wv.get('component')}: {wv.get('reason')} "
                      f"(accepted by {wv.get('accepted_by')} on {wv.get('date')})")
        else:
            problems.append(
                f"residual {residual_pct:.1f}% exceeds the 5% ceiling and there is no "
                f"complete waiver on record. Do NOT remove residual from the reported "
                f"denominator to make this pass -- that voids the ceiling. Record a "
                f"waiver naming each residual component, its blocker, who accepted "
                f"it, and when.")
    if incomplete:
        problems.append(f"{len(incomplete)} waiver(s) missing component, reason, "
                        f"accepted_by or date. An unattributed waiver is not a waiver.")
    unwaived_residual = residual - waived
    if unwaived_residual > 0 and residual_pct > 5.0:
        problems.append(f"{unwaived_residual} residual component(s) have no waiver.")
    if problems:
        fail("Step-7 coverage gate", [f"* {p}" for p in problems])
    print("\n  PASSED"
          + (" (on waiver -- the exception is recorded, not erased)" if waived else ""))
    return 0


# ---------------------------------------------------------------------------
def main(argv):
    sub = argv[0] if argv and not argv[0].startswith("-") else "decisions"
    rest = argv[1:] if sub == (argv[0] if argv else None) else argv

    opts = {}
    i = 0
    while i < len(rest):
        if rest[i].startswith("--") and i + 1 < len(rest):
            opts[rest[i][2:]] = rest[i + 1]; i += 2
        else:
            i += 1

    fpath = Path(opts.get("file", "migration_manifest.yml"))
    if not fpath.exists() and Path("migration_decisions.yml").exists():
        fpath = Path("migration_decisions.yml")   # backward compatible
    ppro = Path(os.path.expanduser(opts.get("profiles", "~/.dbt/profiles.yml")))
    ipath = Path(opts["inventory"]) if "inventory" in opts else None
    parpath = Path(opts["parity"]) if "parity" in opts else None
    wpath = Path(opts["waivers"]) if "waivers" in opts else None

    if sub == "decisions":
        return gate_decisions(fpath, ppro)
    if sub == "inventory":
        if not ipath:
            print("usage: inventory --inventory migration/01_inventory.json"); return 2
        return gate_inventory(ipath, fpath)
    if sub == "parity":
        if not parpath:
            print("usage: parity --parity migration/05_parity.json "
                  "[--inventory migration/01_inventory.json]"); return 2
        return gate_parity(parpath, ipath)
    if sub == "coverage":
        if not (ipath and parpath):
            print("usage: coverage --inventory ... --parity ... [--waivers ...]")
            return 2
        return gate_coverage(ipath, parpath, wpath)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
