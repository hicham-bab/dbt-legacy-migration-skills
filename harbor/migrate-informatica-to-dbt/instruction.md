# Task: migrate a legacy Informatica mapping to dbt

You are migrating a legacy **Informatica PowerCenter** mapping to dbt, targeting **DuckDB** (a local
warehouse, so no cloud credentials are needed). Use the **`migrating-informatica-to-dbt`** skill
(available in your skills directory) and its shared `legacy-to-dbt-migration-foundations` references.

## What's provided (under `/app`)

- `legacy/wf_customer_orders.XML` — the legacy PowerCenter export to migrate. Its logic is in the
  transformation fields (and summarized in the file header).
- `data/raw_orders.csv` — the raw source data the mapping reads.

The mapping's **production output** is the source of truth your mart must match, but it is
**held out with the verifier** — it is not in `/app`. Reproduce it from the mapping's logic; the
verifier will compare your `mart_fct_customer_orders` against it row-for-row.

## The mapping's logic (`m_FCT_CUSTOMER_ORDERS`, as encoded in the XML)

1. `SQ_ORDERS` (Source Qualifier) reads `ORDERS`.
2. `FIL_COMPLETED` (Filter) — keep only `status = 'completed'`.
3. `AGG_CUSTOMER` (Aggregator) — GROUP BY `customer_id`, producing
   `lifetime_amount = SUM(amount)` (decimal) and `order_count = COUNT(order_id)`.
4. `EXP_BAND` (Expression) — `value_band = IIF(lifetime_amount >= 200, 'A', 'B')`.
5. Load target `FCT_CUSTOMER_ORDERS` (grain: one row per customer).

## What to do

1. Follow the skill's workflow. A `migration_decisions.yml` is already provided at `/app` recording
   the decisions for this run (modeling approach: layered; warehouse: duckdb; packages: external_hub)
   so you can proceed non-interactively — read it and honor it.
2. Build the dbt project **in `/app/project`** (a dbt-duckdb project). Load the raw CSV as a dbt
   **seed**, add a staging model, and produce a mart **`mart_fct_customer_orders`** at the grain
   one row per customer, with columns `customer_id`, `lifetime_amount`, `order_count`, `value_band`.
3. Add tests per the skill (the grain is unique/not-null on `customer_id`). The project's dbt profile
   must be named `informatica_demo` and use the DuckDB adapter with `path: dev.duckdb` (a
   `profiles.yml` is provided in `/app/project`).
4. Make it build: from `/app/project`, `dbt deps` (if any) then `dbt build` must succeed.

## Success = the verifier can build your project and `mart_fct_customer_orders` matches the expected output row-for-row (customer_id, lifetime_amount, order_count, value_band).
