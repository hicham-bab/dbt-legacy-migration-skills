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
- [Structural rules](#structural-rules)
- [Worked example](#worked-example)

## Resolving METL implementationID

DPC YAML names the component `type` directly (kebab-case). **Matillion ETL (METL) JSON does not** —
each component carries a numeric `implementationID` instead, and the human name is the first
parameter (`parameters["1"].elements["1"].values["1"].value`). To map a METL component, use the
name parameter as the primary signal (it matches the DPC component names in the table below), and
the `implementationID` as a secondary key. Values verified from real exports:

| implementationID | Component | Kind |
|---|---|---|
| 444132438 | Start | control |
| 1611478312 | Create Table | control (DDL) |
| 655623811 | Create File Format | control |
| 1214167305 / 1043089869 | API Query / API Extract | EL ingestion |
| -798585337 | SQL Script | script |
| -1773186829 | Python Script | script |
| 1354890871 | Table Input | transform |
| -359894709 | Detect Changes | transform |
| 1139103188 | Pivot | transform |

The full `implementationID` → component table is proprietary and not exhaustive here; **trust the
`"Name"` parameter** to identify the component, then apply the mapping below. If a component's name
and id are both unfamiliar, inventory it and route to the residual.

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
| **Fixed Flow** (`fixed-flow`) | Inline literal table (hard-coded / from variables) | a dbt **seed**, or `select ... union all` of literal rows |
| **Extract Nested Data** (`extract-nested-data`) | Unpack JSON/semi-structured | platform flatten: `lateral flatten` (Snowflake) / `unnest` (BigQuery) / `explode` (Databricks) |
| **Split Field** (`split-field`) | Split one column into several | `split_part` / string functions |
| **Map Values** (`map-values`) | Replace values via lookup | `case when ...` |
| **Detect Changes** (`detect-changes`) | Compare two datasets, flag differences | **snapshot** (SCD2) — see below |
| **Table Output** (`table-output`) | Insert/append into a target table | `incremental` model (`append`, or `merge` with `unique_key`) |
| **Rewrite Table** (`rewrite-table`) | Drop & recreate target with the flow output (CTAS) | `table` materialization (the mart) |

Materialization choice follows the target cloud — see foundations →
cloud-detection-and-materializations.md. `Rewrite Table` (full CTAS rebuild) → `table`;
`Table Output` (insert/append/upsert) → `incremental`.

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

## Structural rules

1. Wrap logic in CTEs; name the final CTE `final`; last line `select * from final`.
2. Use `{{ ref('model') }}` for tables another pipeline produced, `{{ source('schema','table') }}`
   for raw loaded tables.
3. One CTE per meaningful component (`table_input` → `source`, `filter` → `filtered`, `join` →
   `joined`, `aggregate` → `aggregated`), in the `sources:` DAG order.
4. Fusion-conformant: `cast()` not `::`, `coalesce()` not `nvl`/`ifnull`; no DDL in models.

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
