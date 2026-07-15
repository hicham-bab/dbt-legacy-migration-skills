# Task: migrate a legacy stored procedure to dbt

You are migrating a legacy SQL stored procedure to dbt, targeting **DuckDB** (a local warehouse, so
no cloud credentials are needed). Use the **`migrating-stored-procedures-to-dbt`** skill (available
in your skills directory) and its shared `legacy-to-dbt-migration-foundations` references.

## What's provided (under `/app`)

- `legacy/sp_customer_ltv.sql` — the legacy stored procedure to migrate (its logic is in comments).
- `data/raw_orders.csv`, `data/raw_customers.csv` — the raw source data.
- `expected/legacy_customer_ltv.csv` — the legacy procedure's **production output** (the source of
  truth to match). Do not read it into your models; it exists only so parity can be proven.

## What to do

1. Follow the skill's workflow. A `migration_decisions.yml` is already provided at `/app` recording
   the decisions for this run (architecture: layered; warehouse: duckdb; packages: external_hub) so
   you can proceed non-interactively — read it and honor it.
2. Build the dbt project **in `/app/project`** (a dbt-duckdb project). Load the two raw CSVs as dbt
   **seeds**, add a staging model, and produce a mart **`mart_customer_ltv`** that reproduces the
   procedure's logic (grain: one row per customer; completed orders only; `lifetime_value`,
   `order_count`, `ltv_segment` with the `>= 150 -> 'high'` threshold).
3. Add the parity check and tests per the skill. The project's dbt profile must be named
   `stored_proc` and use the DuckDB adapter with `path: dev.duckdb` (a `profiles.yml` is provided in
   `/app/project`).
4. Make it build: from `/app/project`, `dbt deps` (if any) then `dbt build` must succeed.

## Success = the verifier can build your project and `mart_customer_ltv` matches the expected output
row-for-row (customer_id, lifetime_value, order_count, ltv_segment).
