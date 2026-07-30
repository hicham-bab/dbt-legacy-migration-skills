# Task: remediate a lift-and-shift dbt project into idiomatic dbt

You are given an existing dbt project in `/app/project` that was produced by a **lift-and-shift**
migration from Matillion. It builds and returns the correct numbers, but it is **not idiomatic dbt**:

- a single **monolithic** model (`models/marts/customer_ltv.sql`) that reads the raw seed directly,
  with **no staging layer**,
- a data-quality `DELETE` crammed into a **post_hook** (that logic belongs in a test),
- **no tests and no docs**.

This is the kind of technical debt that makes a "migrated" project hard to trust and maintain.

## What to do

Refactor the project **in place in `/app/project`** into idiomatic dbt **without changing the
output**:

1. Add a **staging** model over the raw seed (`stg_orders`), typed and named per convention.
2. Rebuild `customer_ltv` as a mart that reads the staging model via `ref()` (keep its name and grain:
   one row per customer, completed orders only, `lifetime_value` = SUM(amount), `order_count`,
   `ltv_segment` with the `>= 150 -> 'high'` threshold).
3. **Remove the post_hook**; if the DELETE encoded a data-quality rule, express it as a **test**.
4. Add tests (unique/not_null on the grain, accepted_values on `ltv_segment`) and short descriptions.
5. Keep results identical: `customer_ltv` must still return exactly the rows it returns today.

A `migration_decisions.yml` at `/app` records the run decisions (layered; duckdb). The profile is
`remediate_demo` (DuckDB, `path: dev.duckdb`). From `/app/project`, `dbt build` must succeed.

## Success

The verifier will:

1. build your refactored project,
2. check `customer_ltv` still matches the **held-out** current output row-for-row (parity), and
3. run the idiomatic anti-pattern linter (`scripts/lint_idiomatic.py`) and require **zero findings**.

So a "do nothing" answer that leaves the lift-and-shift in place will pass parity but **fail the lint
gate**. Remediation means idiomatic **and** identical results.
