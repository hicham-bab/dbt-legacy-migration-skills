# Task: migrate a legacy Matillion transformation pipeline to dbt

You are migrating a legacy **Matillion** transformation pipeline to dbt, targeting **DuckDB** (a
local warehouse, so no cloud credentials are needed). Use the **`migrating-matillion-to-dbt`** skill
(available in your skills directory) and its shared `legacy-to-dbt-migration-foundations` references.

## What's provided (under `/app`)

- `legacy/build_sales_marts.tran.yaml` - the legacy Matillion Data Productivity Cloud transformation
  pipeline to migrate (a `.tran.yaml` export).
- `data/raw_orders.csv`, `data/raw_customers.csv` - the raw source data the pipeline reads.

The pipeline's **production outputs** are the source of truth your marts must match, but they are
**held out with the verifier** - they are not in `/app`. Reproduce them from the pipeline's logic;
the verifier compares your marts against them row-for-row.

## The pipeline's logic (as encoded in the `.tran.yaml`)

1. Read `orders` and `customers` (table-input).
2. `calculator` - `net_amount = total_amount - discount_amount`.
3. `filter` - keep only `status = 'completed'`.
4. `join` - LEFT JOIN completed orders to customers on `customer_id`.
5. `rank` - `row_number()` partitioned by `customer_id`, ordered by `order_date` **descending**,
   as `order_recency_rank`.
6. `aggregate` - GROUP BY `customer_id`, producing `total_net = SUM(net_amount)` and
   `order_count = COUNT(order_id)`.
7. Two outputs: **`fct_orders`** (from the rank branch, one row per completed order) and
   **`agg_customer_sales`** (from the aggregate branch, one row per customer).

## What to do

1. Follow the skill's workflow. A `migration_decisions.yml` is already provided at `/app` (modeling:
   layered; warehouse: duckdb; packages: external_hub) so you can proceed non-interactively.
2. Build the dbt project **in `/app/project`** (a dbt-duckdb project). Load the two raw CSVs as dbt
   **seeds**, add staging models, and produce two marts:
   - **`mart_fct_orders`** - one row per completed order, with columns `order_id`, `customer_id`,
     `order_date`, `net_amount`, `customer_name`, `region`, `segment`, `order_recency_rank`.
   - **`mart_agg_customer_sales`** - one row per customer, with `customer_id`, `total_net`,
     `order_count`.
3. Add tests per the skill (grain uniqueness/not-null on the keys). The dbt profile must be named
   `matillion_demo` and use the DuckDB adapter with `path: dev.duckdb` (a `profiles.yml` is provided).
4. Make it build: from `/app/project`, `dbt deps` (if any) then `dbt build` must succeed.

## Success = the verifier can build your project and both marts match the expected outputs row-for-row.
