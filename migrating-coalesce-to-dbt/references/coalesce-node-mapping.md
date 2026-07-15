# Coalesce node → dbt answer key (Step 3)

Coalesce is **push-down SQL** (like dbt): each node compiles to warehouse SQL, so nodes map onto dbt
models almost 1:1 — arguably the closest of any source tool to dbt. Grounded in Coalesce docs + the
real `coalesceio` node format.

## Contents

- [Node → dbt object](#node--dbt-object)
- [SCD2 dimensions → snapshots](#scd2-dimensions--snapshots)
- [Columns, transforms & keys](#columns-transforms--keys)
- [Node types, hooks, jobs](#node-types-hooks-jobs)
- [Worked example](#worked-example)

## Node → dbt object

| Coalesce node | dbt object / materialization |
|---|---|
| **Source** | `sources:` entry in `_sources.yml` (+ optional `stg_` model) |
| **Stage / Work** (`truncateBefore: true`) | staging model, `materialized='view'` (truncate+reload ≈ view/table rebuilt each run) |
| **Persistent Stage** (history, business key) | dbt **snapshot** if it preserves history; else `incremental` |
| **Dimension — SCD1** | `dim_` model, `materialized='table'` (or `incremental` merge on the business key) |
| **Dimension — SCD2** (`type2Dimension: true`) | dbt **snapshot** feeding a `dim_` (see below) |
| **Fact / Factless Fact** | `fct_` model, `materialized='incremental'` (merge on the business key) |
| **View** | model, `materialized='view'` |
| **Node type** (create/run `.j2` templates) | dbt **materialization** + **macros** (usually the built-in materializations cover it) |
| **Job** | a dbt job / `dbt build` selector |
| **Subgraph** | a model group / folder + selector |

Materialization follows the target warehouse chosen at the gate — see foundations →
cloud-detection-and-materializations.md. Coalesce runs on Snowflake/Databricks/BigQuery, all dbt
targets, so the dialect maps directly.

## SCD2 dimensions → snapshots

A Coalesce **Dimension with `config.type2Dimension: true`** keeps version history via a MERGE (or a
Dynamic-Table variant). Migrate it to a dbt **snapshot**, not a hand-built model:

```yaml
snapshots:
  - name: dim_customer_snapshot
    relation: ref('stg_customers')
    config:
      unique_key: customer_id            # the isBusinessKey column
      # lastModifiedComparison + lastModifiedColumn  -> strategy: timestamp
      strategy: timestamp
      updated_at: last_modified_ts
      # or, if change is tracked by comparing columns (changeTrackingColumns):
      # strategy: check
      # check_cols: [customer_name, segment]
```

Map the config: `lastModifiedComparison`/`lastModifiedColumn` → `strategy: timestamp` + `updated_at`;
`changeTrackingColumns` → `strategy: check` + `check_cols`; the `isBusinessKey` column →
`unique_key`. Coalesce's auto system columns (`<NODE>_KEY` surrogate, `SYSTEM_VERSION`,
record-start/end) are provided by the snapshot's `dbt_valid_from`/`dbt_valid_to` + a
`generate_surrogate_key` — don't hand-build them. **SCD1** dimension → a plain `table` model.

## Columns, transforms & keys

- Each target column = `<transform> AS <name>` in the SELECT; resolve its
  `sourceColumnReferences.columnReferences[].columnCounter` to the upstream node → a `ref()`/`source()`.
- `isBusinessKey` columns → the model grain: `unique` + `not_null` tests; `unique_key` for
  incremental/snapshot.
- `isSurrogateKey` columns → `{{ dbt_utils.generate_surrogate_key([<business keys>]) }}`.
- `acceptedValues` / `appliedColumnTests` on a column → dbt `accepted_values` / the matching tests.
- Emit Fusion-conformant SQL (`cast()` not `::`, `coalesce()` not `nvl`).

## Node types, hooks, jobs

- Most nodes use the **built-in** node types → the standard dbt materializations cover them; you
  rarely need a custom materialization. A genuinely **custom node type (UDN)** with bespoke
  create/run templates → reproduce its logic as a dbt macro or a custom materialization, or flag it.
- `operation.config.preSQL` / `postSQL` → dbt `pre_hook` / `post_hook`.
- **Jobs** → a dbt job / selection; **subgraphs** → model groups.

## Worked example

A Source → Stage → SCD2 Dimension chain:

```sql
-- models/staging/stg_customers.sql  (Stage node, view)
with source as ( select * from {{ source('source_data', 'customers') }} )
select
    customer_id,
    trim(customer_name)  as customer_name,   -- Coalesce column transform TRIM(...)
    upper(segment)       as segment          -- UPPER(...)
from source
```
```yaml
# snapshots/dim_customer_snapshot.yml  (Dimension node, type2Dimension: true)
snapshots:
  - name: dim_customer_snapshot
    relation: ref('stg_customers')
    config: {unique_key: customer_id, strategy: timestamp, updated_at: last_modified_ts}
```
The Fact node (`FCT_ORDERS`, business key `ORDER_ID`, FK `DIM_CUSTOMER_KEY`) becomes an
`incremental` `fct_orders` that joins `ref('dim_customer')` for the surrogate key — see foundations →
building-kimball.md for the fact pattern.
