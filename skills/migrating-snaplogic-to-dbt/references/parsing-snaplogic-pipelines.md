# Parsing SnapLogic pipelines (Step 1)

SnapLogic exports one artifact type — the **`.slp` file, which is JSON**. There is no
transformation/orchestration file split, so the whole job of this step is deciding, **per Snap**,
which execution regime it belongs to. Structure below is grounded in SnapLogic documentation and
**real exported `.slp` files**.

## Contents

- [Acquiring the artifact](#acquiring-the-artifact)
- [The `.slp` envelope](#the-slp-envelope)
- [`snap_map` — the Snaps](#snap_map--the-snaps)
- [`link_map` — the DAG](#link_map--the-dag)
- [Pipeline-level `property_map`](#pipeline-level-property_map)
- [The expression language](#the-expression-language)
- [The three execution regimes](#the-three-execution-regimes)
- [What is *not* in the export](#what-is-not-in-the-export)
- [Building the inventory + data-flow graph](#building-the-inventory--data-flow-graph)

## Acquiring the artifact

Prefer a Git-backed project — it gives you every pipeline at once, with history:

- **Git integration** (best): SnapLogic projects can be checked out to a Git repo; pipelines are
  committed as `.slp` files. Clone the repo.
- **Manager UI export**: SnapLogic Manager → select the project or asset → Export. Downloads
  `.slp` (single pipeline) or a `.zip` (project).
- **Public API**: there is a project/asset export endpoint under the SnapLogic Public APIs
  (`/project/export/...`), returning the same JSON. Endpoint paths, auth scheme and parameters vary
  by control plane and release — **check the current docs for your environment** rather than
  assuming a signature.

Exports **exclude accounts and credentials** by design. What survives is an `account_ref`
expression naming the account (often `eval('lib.BigQuery.' + … + '.SaAccount')`) — record the name
if useful, never treat it as a secret to resolve.

## The `.slp` envelope

Top-level keys of a pipeline export:

| Key | What it is | Use it? |
|---|---|---|
| `snap_map` | map of **snap UUID → snap**; the components | **yes** — the inventory |
| `link_map` | map of link id → `{src_id, dst_id, src_view_id, dst_view_id, isGoto}` | **yes** — the DAG |
| `property_map` | pipeline-level info, params, imports, error behaviour | **yes** |
| `class_fqid` | e.g. `com-snaplogic-pipeline_9` | identifies the file as a pipeline |
| `path_id` | the SnapLogic project path, e.g. `/ExampleProd/projects/Direct_Sales` | domain/Mesh signal |
| `render_map` | canvas positions, zoom, notes | **no** — cosmetic, like Matillion's `design` |
| `snode_id`, `instance_id`, `instance_version`, `link_serial`, `path_snode` | internal ids | no |

## `snap_map` — the Snaps

Keyed by snap UUID. Each snap:

```json
"a0e08b1a-c716-4357-b684-7c2ca25ddce9": {
  "class_id":   "com-snaplogic-snaps-google-bigquery-execute",
  "class_fqid": "com-snaplogic-snaps-google-bigquery-execute_1-427patches13615",
  "class_version": 1,
  "property_map": {
    "info":     { "label": { "value": "BQExec - stg curr" }, "notes": {} },
    "account":  { "account_ref": { "expression": true, "value": "eval('lib.BigQuery.' + …)" } },
    "settings": { "Query": { "expression": false, "value": "CREATE OR REPLACE TABLE …" }, … },
    "input":    { "input101": { "view_type": {"value": "document"}, … } },
    "output":   { "output0":  { … } },
    "error":    { "error_behavior": { "value": "fail" }, … }
  }
}
```

**Critical field rules:**

- **`class_id` is the stable type key.** `class_fqid` appends a build tag
  (`_1-427patches13615`) that changes between releases — never match on it.
- The naming convention is `com-snaplogic-snaps-<pack>-<snap>`, e.g.
  `…-google-bigquery-execute`, `…-transform-datatransform` (the Mapper), `…-flow-pipeexec`,
  `…-elt-scd2`. Strip the `com-snaplogic-snaps-` prefix to get `<pack>-<snap>`.
- **The human label** is `property_map.info.label.value`. It is free text and frequently the only
  clue to intent (`"Wait For Upstream"`, `"Upd Order Type"`, `"Notify Missing Data"`) — read it, but never
  trust it *over* the settings.
- **Every setting is a `{value, expression}` pair.** See
  [the expression language](#the-expression-language).
- **`settings.execution_mode` decides whether the snap runs at all.** Values are
  `"Validate & Execute"`, `"Execute only"`, `"Validate only"` and **`"Disabled"`**. A disabled
  snap is dead code — it stays on the canvas and in the export but never executes. **Check this
  first, on every snap** — before regime classification, before SQL extraction. Disabled snaps are
  common in mature pipelines, and they are not confined to the edges of the graph: expect them
  *inside* live chains, which is where they do damage. Migrating one means migrating logic nobody
  runs.
- **One snap can hold many SQL statements.** The SQL setting is a single string, but it commonly
  contains several `;`-separated statements — and they may write **different tables** — for
  example a `_tmp` build followed by MERGEs and UPDATEs into a final table. Extract every
  statement; never assume the first verb characterises the snap.
- `input` / `output` / `error` declare the Snap's **views** (ports). `input101`, `output0` etc. are
  the ids that `link_map` joins on. An `error` view wired to something is error-handling flow.

**Where the SQL lives, per Snap Pack** (check these keys in order):

| Snap | SQL setting key |
|---|---|
| BigQuery Execute | `settings.Query.value` |
| Snowflake / Redshift / SQL Server / MySQL / JDBC Execute | `settings.sqlStatement.value` |
| Generic / others | `settings.sql_statement`, `settings.statement`, `settings.sqlQuery`, `settings.query` |

## `link_map` — the DAG

```json
"link104": { "src_id": "a0e08b1a-…", "dst_id": "4e411bc7-…",
             "src_view_id": "output0", "dst_view_id": "input101", "isGoto": false }
```

- `src_id` → `dst_id` are **snap UUIDs**; this is the lineage edge.
- **`isGoto: true` is a control jump, not data flow** — exclude it from the data DAG (but note it,
  it usually marks error routing or a loop-back).
- `src_view_id`/`dst_view_id` matter when a Snap has multiple outputs: a Router's route names
  (`"Source Refreshed"`, `"Source Not Refreshed"`) tell you which branch an edge carries.

## Pipeline-level `property_map`

```json
"property_map": {
  "info":     { "label": {"value": "Master_Load_BQ_Daily_Sales_Details"},
                "author": {"value": "someone@example.com"}, "purpose": {…} },
  "settings": {
     "param_table": { "value": [ { "key": {"value":"bigq_env"},
                                   "value": {"value":"ProdEnv1"},
                                   "data_type": {"value":"string"} }, … ] },
     "imports":     { "value": [ { "path": {"value": "'file:///mnt/BI/ETL/…/' + _org_name + …",
                                            "expression": true},
                                   "as": {"value":"BigQuery"} } ] }
  }
}
```

- **`param_table`** = pipeline parameters. Referenced in expressions as `_name` (leading
  underscore). → dbt `var()` / `env_var()`.
- **`imports`** = external **expression libraries** (`.expr` files) loaded from a mounted
  filesystem and referenced as `lib.<as>.<member>`. **They are not in the export.** Flag every
  import as an unresolved dependency and ask the migrator for the files — without them you cannot
  resolve `eval('lib.BigQuery.' + … + '.ProjectID')` into a real project/dataset name.
- `info.label` is the pipeline name; `path_id` (top level) is its project folder.

## The expression language

SnapLogic settings are either literals or **expressions** in a JavaScript-like language:

| Form | Meaning |
|---|---|
| `{"expression": false, "value": "CREATE OR REPLACE TABLE …"}` | literal SQL — use as-is |
| `{"expression": true,  "value": "\"SELECT … \" + $today + \" …\""}` | **expression** — the value is code that *builds* a string |
| `$field` | a field on the current document |
| `_param` | a pipeline parameter |
| `lib.X.Y` | a member of an imported `.expr` library |
| `eval('lib.BigQuery.' + _env + '.ProjectID')` | dynamic library lookup — environment indirection |

**Always unwrap before translating.** When `expression` is true, strip the outer `"`, resolve the
`+ var +` concatenation, and drop BigQuery `#standardSQL` hints and leading `--` comments, or you
will misread the statement's verb. Dynamic SQL (`expression: true` on a SQL setting) is also a
flag for the residual: if the statement's shape depends on runtime values, a human must confirm the
translation.

Translate `_param` → `{{ var('param') }}` / `{{ env_var('…') }}`; translate `$field` inside a
Mapper into a column expression.

## The three execution regimes

This is the classification that drives everything downstream.

| Regime | `class_id` signature | Runs where | dbt? |
|---|---|---|---|
| **pushdown_elt** | `com-snaplogic-snaps-elt-*` | warehouse (Snaps build one SQL query, process no data) | **yes, near 1:1** |
| **warehouse_sql** | `<warehouse-pack>-execute` / `-select` / `-insert` / `-merge` / `-bulkload` | warehouse | **yes** |
| **standard_stream** | `transform-*`, `flow-union`, `flow-router`, `flow-filter` | Snaplex, row-by-row documents | **only if the flow is warehouse→warehouse** |
| *sync_barrier* | `transform-multijoin`/`-join` **joining on a literal**, `flow-tail`/`flow-gate` used as a wait | Snaplex | no — ordering only |
| *fan_out* | `flow-copy` | Snaplex | no — vanishes (two models `ref()` the same upstream) |
| *bridge* | `flow-pipeexec`, `flow-foreach`, `flow-taskexecute` | control plane | no — recurse into the child |
| *el_ingestion* | `*-parser`, `*-formatter`, `*-reader`, `*-writer`, `s3-*`, `rest-*`, `file-*`, … | Snaplex | no — map outputs to `sources` |
| *control* | `flow-exit`, `script-script`, `email-emailsender` | Snaplex | no — notes |

**The sync-barrier trap.** A Join/Multijoin whose `joinPaths` all have `leftPath`/`rightPath` of a
literal (`"1"`) is **not a join** — it is a synchronization barrier making the pipeline wait for
two branches. Labels like `"Wait For Upstream"` / `"Join - Gate"` confirm it. So is a `Tail` Snap placed
after a `Copy`. Counting these as transformations silently inflates the coverage denominator.

**The Router/Filter judgement call.** `flow-router` and `flow-filter` are data operations in a
document stream (`where` / `case`), but in practice they very often branch on *job status* or
*row counts* — that is control flow. Read the route expressions: `$SOURCE_COUNT > $TARGET_COUNT` gating a
notification is orchestration, not a model.

## What is *not* in the export

Flag each of these to the migrator; none of it is modelable from the `.slp` alone:

- **Accounts / credentials** — excluded by design.
- **External `.expr` expression libraries** — referenced by `imports`, stored on a filesystem.
- **Tasks** (Scheduled / Triggered / Ultra) — schedules, retries and triggers live in Manager.
  → a platform job; capture as notes.
- **Stored procedure bodies** — a `CALL proc(...)` in an Execute Snap hides its logic in the
  warehouse. Fetch the body; hand off to `migrating-stored-procedures-to-dbt`.
- **Snaplex/node topology** and any runtime governance settings.

## Building the inventory + data-flow graph

1. Glob `**/*.slp` and parse each as JSON (stdlib; no YAML anywhere).
2. For each Snap, take `class_id` → regime (table above). Count the migratable regimes → the
   coverage denominator. Report the rest separately.
3. **Skip disabled snaps** (`execution_mode == "Disabled"`) — record them, never count them.
4. For every live `warehouse_sql` / ELT-Execute Snap, unwrap the SQL, split it into statements,
   and record **each** statement's **verb** (`CTAS` / `MERGE` / `INSERT` / `UPDATE` / `DELETE` /
   `DDL` / `CALL` / `SELECT`) and **write target**. Note two semantics that change the dbt
   materialization: a `WHEN NOT MATCHED THEN INSERT` clause (the target **accumulates rows** →
   incremental, not a rebuilt table) and a `USING` subquery that reads the **target itself**
   (read-modify-write over history → needs `{{ this }}` semantics).
5. **Group Snaps by write target.** More than one Snap writing the same table = a sequential
   enrichment chain = **one** dbt model. This is the single most important output of Step 1.
6. Build the DAG from `link_map`, skipping `isGoto` edges; drop `flow-copy` nodes (fan-out) and
   sync barriers, splicing their edges through.
7. Cross-pipeline lineage: each `flow-pipeexec` names a child in `settings.pipeline.value`.
   Recurse into project-local children. Relative paths into a `shared/` folder
   (`gbl_Start_Job_*`, `gbl_End_Job_*`, `gbl_Error_Handling`) are a job-logging/error framework —
   document once, drop, do not model.
8. A table read by one pipeline and written by another = `ref()`; a table only ever read =
   `source()`. **If the writing pipeline is not in the export**, you cannot tell which it is —
   default to `source()`, mark it provisional, and list the missing pipeline as an unresolved
   dependency. Say explicitly that the denominator is unstable until it is supplied.
9. Map `param_table` entries → `var()`/`env_var()`; list unresolved `imports`.
10. Hand the inventory to Step 2 (classification) and each Snap's settings to Step 3
   ([snaplogic-snap-mapping.md](snaplogic-snap-mapping.md)).

> **How this reference was built:** it and `scripts/inventory_snaplogic.py` were developed against
> real `.slp` exports covering BigQuery Execute CTAS and MERGE chains, MySQL Execute,
> Mapper/Router/Multijoin, Copy/Tail plumbing, Pipeline Execute into both local and shared
> pipelines, `isGoto` edges, dynamic SQL, disabled snaps, multi-statement snaps, self-referencing
> MERGEs, and unresolved `.expr` imports.
>
> **That coverage has gaps.** No ELT Snap Pack snap, no Snowflake / Databricks / Redshift Execute
> snap, no ELT SCD2, and no file or API ingestion snap were exercised — that part of the mapping is
> documentation-grounded only. Verify against the migrator's
> *actual* export early: if a `class_id` is unfamiliar the script reports it as `unknown` —
> classify it by hand before computing coverage.

## Known limitations of `inventory_snaplogic.py`

The script is a deterministic first pass, not an oracle. Where it is weak, check by hand:

- **Statement splitting is regex-based.** It finds write verbs; it does not parse SQL. A `--` or
  `/* */` sequence inside a string literal is stripped as a comment.
- **Write targets are matched as raw strings.** `device.tbl` and `proj.device.tbl` form two
  separate chains even when they are the same table. Normalise before trusting a chain count.
- **`kind` is per snap, not per statement.** A multi-statement snap whose first target ends in
  `_bkp` is labelled `backup`, which understates its other writes.
- **`inserts_rows` is a regex over `WHEN NOT MATCHED … THEN INSERT`** and can fire on a
  `WHEN NOT MATCHED BY SOURCE THEN DELETE` followed later by an unrelated `insert`.
- **Config-driven snaps** (ELT Snaps, `<DB> Select/Insert/Merge/Bulk Load`) carry no SQL string,
  so their write target is read from a settings key that varies by Snap Pack; the script tries
  `table` and `targetTable` and will otherwise leave `writes` empty.
- **The `pushdown_elt` path is documentation-grounded only** — no ELT Snap was exercised when this
  script was developed. Check it against a real ELT pipeline before relying on the count.
