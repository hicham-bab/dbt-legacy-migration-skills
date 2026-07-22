# Task: migrate a legacy Talend job to dbt

You are migrating a legacy **Talend** job to dbt, targeting **DuckDB** (a local warehouse, so no
cloud credentials are needed). Use the **`migrating-talend-to-dbt`** skill (available in your skills
directory) and its shared `legacy-to-dbt-migration-foundations` references.

## What's provided (under `/app`)

- `legacy/customer_revenue_job.item` — the legacy Talend job to migrate (a `.item` XML export). Its
  logic is also summarized in the file header.
- `data/raw_orders.csv`, `data/raw_customers.csv` — the raw source data the job reads.

The legacy job's **production output** is the source of truth your mart must match, but it is
**held out with the verifier** — it is not in `/app`. Reproduce it from the job's logic; the verifier
will compare your `mart_customer_revenue` against it row-for-row.

## The job's logic (as encoded in the `.item`)

1. Read `raw_orders` and `raw_customers`.
2. `tFilterRow` — keep only rows where `status = 'completed'`.
3. `tMap` — INNER JOIN orders to customers on `customer_id` (brings in `customer_name`).
4. `tAggregateRow` — GROUP BY `customer_id, customer_name`, producing
   `total_revenue = SUM(amount)` (decimal) and `order_count = COUNT(order_id)`.
5. Write `analytics.customer_revenue`. (`tSendMail` is a notify step — out of scope for dbt.)

## What to do

1. Follow the skill's workflow. A `migration_decisions.yml` is already provided at `/app` recording
   the decisions for this run (modeling approach: layered; warehouse: duckdb; packages: external_hub)
   so you can proceed non-interactively — read it and honor it.
2. Build the dbt project **in `/app/project`** (a dbt-duckdb project). Load the two raw CSVs as dbt
   **seeds**, add staging models, and produce a mart **`mart_customer_revenue`** at the grain
   one row per customer, with columns `customer_id`, `customer_name`, `total_revenue`, `order_count`.
3. Add tests per the skill (the grain is unique/not-null on `customer_id`). The project's dbt profile
   must be named `talend_demo` and use the DuckDB adapter with `path: dev.duckdb` (a `profiles.yml`
   is provided in `/app/project`).
4. Make it build: from `/app/project`, `dbt deps` (if any) then `dbt build` must succeed.

## Success = the verifier can build your project and `mart_customer_revenue` matches the expected output row-for-row (customer_id, customer_name, total_revenue, order_count).
