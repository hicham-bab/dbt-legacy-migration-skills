# Matillion component → dbt answer key (Step 3)

The translation table for Matillion components. Because Matillion is **push-down ELT**, every
transformation component already corresponds to a SQL operation executed in the warehouse — the
mapping to dbt is direct. Grounded in Matillion component documentation.

## Contents

- [Resolving METL implementationID](#resolving-metl-implementationid)
- [Transformation components → SQL](#transformation-components--sql)
- [Detect Changes → dbt snapshots](#detect-changes--dbt-snapshots)
- [Orchestration components](#orchestration-components)
- [Script components, Shared Jobs & CDC](#script-components-shared-jobs--cdc)
- [Variables](#variables)
- [Translation traps](#translation-traps)
- [Structural rules](#structural-rules)
- [Worked example](#worked-example)

## Resolving METL implementationID

DPC YAML names the component `type` directly (kebab-case). **Matillion ETL (METL) JSON does not** —
each component carries a numeric `implementationID` instead, and the human name is the first
parameter (`parameters["1"].elements["1"].values["1"].value`). To map a METL component, use the
name parameter as the primary signal (it matches the DPC component names in the table below), and
the `implementationID` as a secondary key. Values verified from real exports:

This is the map implemented in [`scripts/inventory_matillion.py`](../scripts/inventory_matillion.py)
(`METL_IMPL`). Keep the two in sync — the script is the executable copy.

> **⚠ Correction: `1896325668` is Run Transformation, not Table Output.** It was previously
> mis-identified as Table Output. It is a **bridge** (it invokes a child transformation job), so
> translating it as a write target produces a model that writes nothing and a missing job in the DAG.
> The genuine Table Output id is **`211954775`**.

**Provenance tags** — so a maintainer can judge confidence per row:

- `[EXPORT]` — identified from a real METL export by component naming convention
  (`SQ_`/`CALC_`/`JOIN_`/`FLTR_`/`RN_`/`TRNSP_`/`TBL_OUT_` and similar); high confidence,
  corroborated where marked.
- `[XREF]` — corroborated by an independently authored id map (a Matillion→dbt/Glue transpiler
  component-type config).
- `[PRIOR]` — inherited from the original 14-id map.

**Transformation components:**

| implementationID | Component (`type`) | Role | Provenance |
|---|---|---|---|
| -1266674941 | `sql` (SQL component) | transformation | `[EXPORT]` |
| 1716658327 | `calculator` | transformation | `[EXPORT]` |
| -629958239 | `join` | transformation | `[EXPORT]` |
| -1760161015 | `filter` | transformation | `[EXPORT]` |
| 128170095 | `rename` | transformation | `[EXPORT]` |
| -627810085 | `unpivot` (Transpose / melt) | transformation | `[EXPORT]` |
| 211954775 | `table-output` | transformation | `[EXPORT+XREF]` |
| 335239555 | `rewrite-table` (Table Rewrite Output) | transformation | `[XREF]` |
| 1354890871 | `table-input` | transformation | `[PRIOR]` |
| -359894709 | `detect-changes` | transformation | `[PRIOR]` |
| 1139103188 | `pivot` | transformation | `[PRIOR]` |

**Bridges** (invoke another job — not modelled, but they define the DAG between jobs):

| implementationID | Component (`type`) | Role | Provenance |
|---|---|---|---|
| 1896325668 | `run-transformation` | bridge | `[EXPORT]` — **not** Table Output |
| 1785813072 | `run-orchestration` (Run Orchestration Job) | bridge | `[XREF]` |

**EL ingestion** (out of dbt scope → map the loaded tables to `sources`):

| implementationID | Component (`type`) | Role | Provenance |
|---|---|---|---|
| 1897708461 | `excel-query` | el_ingestion | `[EXPORT]` |
| 374945314 | `s3-unload` | el_ingestion | `[EXPORT]` |
| 773867971 | `s3-load` | el_ingestion | `[PRIOR]` |
| 1214167305 | `api-query` | el_ingestion | `[PRIOR]` |
| 1043089869 | `api-extract` | el_ingestion | `[PRIOR]` |

**Control flow / DDL / glue** (document, don't model):

| implementationID | Component (`type`) | Role | Provenance |
|---|---|---|---|
| 444132438 | `start` | control | `[PRIOR+EXPORT+XREF]` |
| -1946388514 | `end-success` | control | `[EXPORT+XREF]` |
| 515156205 | `end-failure` | control | `[EXPORT]` |
| -1357378929 | `if` | control | `[EXPORT]` |
| -1343684451 | `or` | control | `[EXPORT]` |
| 235671163 | `and` | control | `[PRIOR]` |
| 237373210 | `truncate-table` | control | `[EXPORT]` |
| 1611478312 | `create-table` | control (DDL) | `[PRIOR]` |
| 655623811 | `create-file-format` | control | `[PRIOR]` |
| -798585337 | `sql-script` (orchestration SQL Script) | control | `[PRIOR+XREF]` |
| 2014087685 | `sql-script` (logging SQL) | control | `[EXPORT]` |
| -1773186829 | `python-script` | control | `[PRIOR]` |
| -1032749985 | `query-result-to-scalar` | control | `[EXPORT]` |
| 438858066 | `sns-message` | control | `[EXPORT+XREF]` |
| -379661045 | `sns-message` | control | `[EXPORT]` |
| 1199871910 | `file-transfer` | el_ingestion* | `[EXPORT]` |
| 1058406652 | `file-iterator` | control | `[PRIOR]` |

\* `file-transfer` sits in the glue group by origin but its **type** classifies it as EL ingestion
(it moves files, it is not warehouse logic). Role is always whatever the type maps to — the group
heading is organisational only, and the job a component lives in never overrides its type.

Note two ids can map to the same type (`sql-script`, `sns-message`); that is expected, since
Matillion ships variants of the same component.

The full `implementationID` → component table is proprietary and not exhaustive here; **trust the
`"Name"` parameter** to identify the component, then apply the mapping below. If a component's name
and id are both unfamiliar, inventory it and route to the residual.

**Unrecognized ids resolve to role `unknown`.** They are *not* defaulted to `transformation` — the
old default silently counted every unmapped component as migratable and inflated the coverage
denominator. Unknowns are **excluded from the coverage denominator**, reported in their own bucket,
and listed with their id so they can be mapped. Running the inventory with `--strict` turns any
remaining unknown into a **non-zero exit** (4), so an unmapped estate fails loudly instead of
producing a confident-looking but wrong coverage number.

## Transformation components → SQL

| Component (`type`) | What it does | dbt / SQL translation |
|---|---|---|
| **Table Input** (`table-input`) | Reads columns from a warehouse table/view | `{{ source(...) }}` (raw) or `{{ ref('...') }}` (a table another pipeline built) |
| **Multi-Table Input** (`multi-table-input`) | Reads many tables matching a pattern | `union all` across the enumerated tables |
| **SQL** (`sql`) | Arbitrary user SQL | inline as a CTE (translate dialect, keep Fusion-conformant) |
| **Calculator** (`calculator`) | Adds/overwrites columns via expressions (1 row → 1 row) | scalar expressions in a `select` |
| **Filter** (`filter`) | Keeps rows matching AND/OR criteria | `where` |
| **Aggregate** (`aggregate`) | Group + aggregate | `group by` + `sum/avg/count/...` |
| **Join** (`join`) | Combine inputs (one main + joins) | `join` (inner/left/right/full per config) |
| **Rank** (`rank`) | Partition + order + ranking function | `rank()/row_number()/dense_rank() over (partition by ... order by ...)` |
| **Unite** (`unite`) | Combine datasets (all or common columns) | `union` / `union all` |
| **Distinct** / Remove Duplicates | Deduplicate | `select distinct` (or `qualify row_number() = 1`) |
| **Convert Type** (`convert-type`) | Cast types | `cast(col as <type>)` |
| **Rename** (`rename`) | Rename columns | `col as new_name` |
| **Unpivot / Transpose** (`unpivot`) | Melt columns into rows (one row per field per record) | `dbt_utils.unpivot` (keeps null values) or explicit `union all` branches — pick one, match the legacy null handling, and record it (translation trap 4) |
| **Fixed Flow** (`fixed-flow`) | Inline literal table (hard-coded / from variables) | a dbt **seed**, or `select ... union all` of literal rows |
| **Extract Nested Data** (`extract-nested-data`) | Unpack JSON/semi-structured | platform flatten: `lateral flatten` (Snowflake) / `unnest` (BigQuery) / `explode` (Databricks) |
| **Split Field** (`split-field`) | Split one column into several | `split_part` / string functions |
| **Map Values** (`map-values`) | Replace values via lookup | `case when ...` |
| **Detect Changes** (`detect-changes`) | Compare two datasets, flag differences | **snapshot** (SCD2) — see below |
| **Table Output** (`table-output`) | Insert/append into a target table | depends on the write mode — see below |
| **Rewrite Table** (`rewrite-table`) | Drop & recreate target with the flow output (CTAS) | `table` materialization (the mart) |

Materialization choice follows the target cloud — see foundations →
cloud-detection-and-materializations.md. `Rewrite Table` (full CTAS rebuild) → `table`.

**Table Output: append vs truncate-and-reload.** These are different materializations, and the
component name does not tell you which — read the write-mode parameter (`Truncate` / `Load Option` /
`Write Mode`):

- **Append mode** (truncate off) → dbt **`incremental`** with an explicit **`unique_key`**. Matillion
  accumulated rows across runs; dbt must add only new/changed rows.
  **TRAP:** translating an append-mode Table Output as a plain `table` or `view` **double-writes on
  every rebuild** — Matillion appended once per run, dbt rebuilds the whole result each run, so row
  counts and every `sum()` inflate. This compiles cleanly and only shows up as a parity failure.
- **Truncate-and-reload mode** (truncate on) → plain **`table`**. The target held exactly one run's
  output, so a full rebuild is the faithful translation. Making this one `incremental` is the mirror
  error: it retains rows the legacy job would have discarded.

The inventory script detects this rather than leaving it to inference: each parity target carries
`write_mode` of `append` or `truncate_reload`, and the summary reports an `append_mode_targets`
count. Read it off the artifact. A `write_mode` of null means the parameter was not found — that is
a gap to resolve by reading the component, not a default to assume.

## Detect Changes → dbt snapshots

The **Detect Changes** component compares a new/staged dataset against an existing one on key
columns and emits an **Indicator** column: `N` (new), `C` (changed), `I` (identical), `D`
(deleted) — i.e. a `full outer join` on the keys plus column comparison. The documented Matillion
SCD2 pattern (Detect Changes → filter on indicator → insert new versions with effective-from/to +
current flag, expire old) migrates to a **dbt snapshot**, not a hand-built model:

```yaml
snapshots:
  - name: dim_customer_snapshot
    relation: ref('stg_customer')
    config:
      unique_key: customer_id
      strategy: check
      check_cols: [full_name, email, segment]
```

The snapshot manages `dbt_valid_from`/`dbt_valid_to`/current-row. An SCD1 (overwrite) dimension is
just a `table` model.

## Orchestration components

Orchestration is mostly **out of dbt scope** — document, don't model:

| Component | Kind | Where it goes |
|---|---|---|
| `s3-load`, `database-query`, API/connector Query | EL ingestion | keep in a loader/EL tool; map loaded tables to dbt `sources` |
| `run-transformation` | invokes a transformation | the dbt DAG/run (its transformation → models) |
| `run-orchestration` | invokes a child orchestration | recurse into that pipeline |
| `create-table`/`truncate-table`, Alter | DDL | dbt owns table creation — drop these |
| `if` / `and` / `retry`, success/failure branches | control flow | dbt run ordering + a scheduler/job (notes) |
| iterators (`grid-iterator`, `table-iterator`, `loop-iterator`, ...) | runtime looping | re-model set-based, or parameterized model, or residual |
| `sql` script, `python-script`, `bash-script` | scripting | SQL → CTE if it's a transform; Python/Bash → residual |
| `start`, `end-success`, `end-failure` | flow markers | drop |

## Script components, Shared Jobs & CDC

- **SQL Script / SQL component** — the SQL is stored inline (a string parameter, e.g. METL param
  name `"SQL Script"`). If it's a transform (a `SELECT`/CTAS building a table) → inline as a CTE in
  a model, translating dialect and keeping Fusion-conformant. If it's DDL/grants/masking/session
  setup → not a model; move to a dbt `on-run-start`/operation or drop (dbt owns DDL). 
- **Python Script / Python Pushdown** — inline Python string (METL param `"Script"`; uses
  `context.updateVariable(...)`, `context.getGridVariable(...)`). → a dbt **Python model** only if
  it's a genuine set-based transform; otherwise it's orchestration glue → residual / out of scope.
- **Bash Script** — orchestration hook → out of scope.
- **Shared Job (METL) / sub-pipeline (DPC)** — a reusable bundled workflow invoked as one
  component. Migrate the underlying job **once** as a macro or a set of `int_` models, and `ref()`
  it from every caller — do not inline it repeatedly. In METL migration mappings this component is
  keyed by `metlImplementationId`.
- **CDC / Streaming** — the capture is ingestion (out of scope → `sources`). Only the downstream
  consumer that turns landed change data into current-state maps to dbt: a **snapshot** (SCD) or an
  **incremental model** merging on primary key / op-type.

## Variables

- **Project / environment variables** (METL: environment variables) → dbt `var()` or `env_var()`.
- **Pipeline / job variables** → dbt `var()` scoped via the model, or hard-coded if constant.
- **Grid variables** + Grid/Table Iterators → no direct dbt equivalent; re-model as set-based SQL
  or a parameterized model, or flag as residual. Do not unroll into N copied models blindly.
- Referencing syntax in Matillion is `${variable_name}`; translate those tokens to `{{ var('...') }}`
  / `{{ env_var('...') }}`.

## Translation traps

Six Matillion-general translation errors that **compile cleanly and silently corrupt parity**. Each
is worth an explicit check per pipeline, because none of them produces an error message.

1. **Translate joins by the CONFIGURED join type, never the component name.** Matillion join
   components are routinely misnamed — a component called `JOIN_INNER_*` is frequently configured as
   RIGHT or FULL. Read the join-type parameter and the main/joined input roles, not the label.
   *Why it silently corrupts parity:* emitting `inner` for a configured outer join drops every
   unmatched row, so counts and sums come out low with no error.
2. **`DECODE(x, NULL, ...)` MATCHES NULL in Snowflake** — unlike `=`. Translate it to an explicit
   `case when x is null then ...`, never `case when x = NULL`.
   *Why it silently corrupts parity:* `x = NULL` never evaluates true, so the branch never fires and
   the column falls through to the default value for every NULL input.
3. **Calculator "Include Input Columns = Yes" plus a downstream Rename passthrough governs the final
   column set.** Trace both to know which columns the flow actually emits. Watch for
   double-underscore rename artifacts (`CALC__COL` → `COL`) and for two competing lineages that
   produce the same output column name.
   *Why it silently corrupts parity:* you emit the wrong column list — extra columns, missing
   columns, or the wrong lineage's version of a same-named column, all of which pass a key-only diff.
4. **Preserve the Unpivot/Transpose melt grain:** one row per unpivoted field per source record.
   *Why it silently corrupts parity:* collapsing or duplicating the melt grain multiplies or divides
   the row count downstream, so every row-count and aggregate check breaks at a point far from the
   component that caused it.
   Choose and record one approach: `dbt_utils.unpivot` (preferred when installed: fewer lines, same
   grain) or explicit `union all` branches (use when per-branch conditions or null handling differ).
   Match the legacy null handling deliberately. `dbt_utils.unpivot` **keeps** rows whose value is
   null ([dbt-utils docs](https://github.com/dbt-labs/dbt-utils#unpivot-source)), while Snowflake's
   native `UNPIVOT` **drops** them unless `INCLUDE NULLS` is set
   ([Snowflake docs](https://docs.snowflake.com/en/sql-reference/constructs/unpivot)). Do not
   assume the two agree: read the component's configuration (and, where possible, the SQL Matillion
   generated) to see whether the legacy flow kept nulls, and add `where <value> is not null`
   downstream if it dropped them. Add a singular test asserting one
   row per invalid field per record. If the approach differs from the plan shown to the migrator,
   say so in the closing message, not only in a notes file.
5. **Near-identical table names one token apart are common** — e.g. a `_IN` raw load table versus a
   `_PRE_..._IN` intermediate that another pipeline produces. One is a `source()`, the other is a
   `ref()`. Resolve which by asking whether a pipeline in the estate writes it.
   *Why it silently corrupts parity:* referencing the wrong one compiles and runs, but reads a
   different table at a different stage of processing, producing a silently wrong DAG and plausible
   but incorrect numbers.
6. **`row_number() over (order by 0)` (or any constant `order by`) is not a key.** It numbers rows in
   arbitrary order, so the value changes between runs and between queries. Never copy it into an
   output column unchanged. Replace it with a deterministic key and record it as a contract change
   the migrator must approve: `md5` of the record's content hash plus its occurrence number among
   byte-identical rows (`row_number() over (partition by content_hash order by content_hash)`).
   Keep the plain content hash as a separate column if the legacy output had one. Identical rows
   then share the content hash but have distinct keys, and the key is stable across rebuilds.
   *Why it silently corrupts parity:* row-for-row comparison on this column can never pass, and any
   test that joins on it flakes. The Step-5 rebuild-stability check (foundations →
   data-validation.md) catches a survivor; `lint_idiomatic.py` flags the pattern as
   `nondeterministic_order`.

## Structural rules

1. Wrap logic in CTEs; name the final CTE `final`; last line `select * from final`.
2. Use `{{ ref('model') }}` for tables another pipeline produced, `{{ source('schema','table') }}`
   for raw loaded tables.
3. One CTE per meaningful component (`table_input` → `source`, `filter` → `filtered`, `join` →
   `joined`, `aggregate` → `aggregated`), in the `sources:` DAG order.
4. Fusion-conformant: `cast()` not `::`, `coalesce()` not `nvl`/`ifnull`; no DDL in models.
5. **Conformant first; platform-specific only where the result would otherwise change.** Where a
   platform-specific function has no conformant equivalent that preserves the **exact** result, keep
   the platform function and comment why. Where a conformant equivalent does preserve the result,
   use it — prefer `try_cast(...)` over platform-specific try-conversion functions, for example.
   "Keeping the semantics" is not a licence to re-emit platform SQL by default; it is a narrow
   exception that has to be justified per expression.

## Worked example

A transformation pipeline: `Table Input` (raw_orders) → `Calculator` (net = amount - discount) →
`Filter` (status = 'completed') → `Aggregate` (by customer_id) → `Rewrite Table` (fct_customer_sales):

```sql
with source as (
    select * from {{ source('raw', 'raw_orders') }}
),
calculated as (
    select *, cast(amount - discount as decimal(18,2)) as net_amount
    from source
),
filtered as (
    select * from calculated where status = 'completed'
),
aggregated as (
    select
        customer_id,
        cast(sum(net_amount) as decimal(18,2)) as total_net,
        count(*)                               as order_count
    from filtered
    group by customer_id
),
final as (select * from aggregated)
select * from final
```

The `Rewrite Table` target (`fct_customer_sales`) becomes this model's name + a `table`
materialization; prove parity against the table Matillion produced (foundations →
data-validation.md).
