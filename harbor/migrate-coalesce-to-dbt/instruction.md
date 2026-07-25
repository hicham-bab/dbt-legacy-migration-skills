# Task: migrate a legacy Coalesce project to dbt

You are migrating a legacy **Coalesce** (coalesce.io - the Snowflake transformation platform, **not**
the dbt conference) project to dbt, targeting **DuckDB** (a local warehouse, so no cloud credentials
are needed). Use the **`migrating-coalesce-to-dbt`** skill (available in your skills directory) and
its shared `legacy-to-dbt-migration-foundations` references.

## What's provided (under `/app`)

- `legacy/nodes/*.yml` - the Coalesce Git-export node files (a TPC-H slice: `CUSTOMER`, `NATION`,
  `ORDERS` sources → `STG_*` stages → `DIM_CUSTOMER` (a **Type 2 SCD** dimension, change-tracking on
  `C_NAME`) + `FCT_ORDERS`).
- `data/raw_customer.csv`, `data/raw_nation.csv`, `data/raw_orders.csv` - the raw source data.

The project's **production outputs** are the source of truth your marts must match, but they are
**held out with the verifier** - reproduce them from the node graph. Column names normalize to
lowercase in dbt/DuckDB.

## The node graph's logic

1. Stages (`STG_CUSTOMER`, `STG_NATION`, `STG_ORDERS`) - clean passthrough of each source.
2. `DIM_CUSTOMER` (Dimension, **Type 2** - `C_NAME` is the change-tracking column) - customer
   dimension with a surrogate key `dim_customer_key = ROW_NUMBER() OVER (ORDER BY c_custkey)`,
   business key `c_custkey`, `c_name`, `nation_name` (joined from `STG_NATION` on nationkey), and
   `c_mktsegment`.
3. `FCT_ORDERS` (Fact, one row per order) - `o_orderkey`, the `dim_customer_key` looked up from
   `DIM_CUSTOMER` on customer key, `o_orderstatus`, `o_totalprice`.

## What to do

1. Follow the skill's workflow. A `migration_decisions.yml` is provided at `/app` (modeling: star;
   warehouse: duckdb; packages: external_hub) so you can proceed non-interactively.
2. Build the dbt project **in `/app/project`** (a dbt-duckdb project). Load the three raw CSVs as
   **seeds**, add staging models (`stg_customer`, `stg_nation`, `stg_orders`), model the **Type 2
   dimension as a dbt snapshot** (change-tracking on `c_name`), and produce two marts:
   - **`mart_dim_customer`** - one row per customer: `dim_customer_key`, `c_custkey`, `c_name`,
     `nation_name`, `c_mktsegment`.
   - **`mart_fct_orders`** - one row per order: `o_orderkey`, `dim_customer_key`, `o_orderstatus`,
     `o_totalprice`.
3. Add tests per the skill (grain uniqueness/not-null on `c_custkey` and `o_orderkey`). The dbt
   profile must be named `coalesce_demo` and use the DuckDB adapter with `path: dev.duckdb` (a
   `profiles.yml` is provided).
4. Make it build: from `/app/project`, `dbt deps` (if any) then `dbt build` must succeed.

## Success = the verifier can build your project and both marts match the expected outputs row-for-row.
