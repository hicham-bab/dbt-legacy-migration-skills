# Stored procedure → dbt decomposition (Step 1 + Step 3)

How to take an imperative stored procedure apart and rebuild it as declarative dbt models. Pattern
sourced from the worked example in `a worked stored-proc→dbt example`: `legacy/sp_customer_ltv.sql` (a
BigQuery proc that rebuilds a table with temp tables and procedural SQL) → the refactored
`models/marts/finance/mart_customer_ltv.sql` on `ref()` models, with
`analyses/validate_ltv_migration.sql` proving parity. The `WIZARD_PROMPTS.md` in that repo is a
ready-made 3-act prompt flow (Understand → Decompose/Generate → Prove parity).

## Contents

- [Step 1: read the procedure](#step-1-read-the-procedure)
- [Procedural → declarative mapping](#procedural--declarative-mapping)
- [Worked example](#worked-example)

## Step 1: read the procedure

Before writing any dbt, extract and record:

1. **Output grain** — what is one row of the final target? (e.g. one row per customer). Everything
   depends on this; confirm it explicitly.
2. **Source tables** — every table the proc reads. Map to existing dbt `source()`s / `stg_` models;
   prefer building on models that already exist over re-reading raw.
3. **Steps** — each temp-table build, each intermediate query, each branch, the final write. This
   list is the **total step count** (coverage denominator).
4. **Business rules** — segmentation thresholds, status/date filters, recency/tenure/lifecycle
   logic, magic numbers. Preserve these **exactly**; do not round or "improve" them.
5. **Write pattern** — full rebuild (`CREATE OR REPLACE TABLE` / truncate+insert) vs
   MERGE/upsert vs append. This picks the materialization.

## Procedural → declarative mapping

| Procedural construct | dbt translation |
|---|---|
| Temp table / CTE built mid-proc (`CREATE TEMP TABLE t AS ...`) | a CTE in the model, or an `int_` intermediate model if reused by several outputs |
| `CREATE OR REPLACE TABLE target AS ...` (full rebuild) | `table` materialization on the mart |
| `MERGE INTO target ...` / upsert on key | `incremental` model with `unique_key` + `merge` strategy |
| `INSERT INTO target` (append) | `incremental` with `append` strategy |
| `IF <cond> THEN ... ELSE ...` (row-level) | `case when ... then ... else ... end` |
| `IF <cond>` selecting a whole branch/target | separate models, selected/combined via `ref()` |
| Cursor / `FOR`/`WHILE` loop over rows | set-based single query (join/aggregate) — loops almost always express a set operation |
| Loop carrying state across iterations | **residual** — flag for human review |
| Dynamic SQL (`EXECUTE IMMEDIATE`, string-built) | **residual** — cannot resolve statically |
| Scalar variable assignment used downstream | a CTE computing that value, cross-joined in |
| Multiple target tables written by one proc | one dbt model per target |

**Layering:** raw reads → `stg_`; joins/lookups/reusable calc → `int_`; the final target → `fct_`/
`dim_` mart. Decompose long procs into intermediate models rather than one giant model — it makes
each step testable and matches the DAG the proc implied.

Materialization choice follows the target cloud — see foundations →
cloud-detection-and-materializations.md. Preserve the write pattern (rebuild vs merge) unless
switching to incremental is a safe, clearly-cheaper win (usually it is for large facts).

## Worked example

`sp_customer_ltv` (BigQuery) builds temp tables `_orders` and `_cust`, then rebuilds
`analytics.customer_ltv` with segmentation thresholds and recency/tenure math. Decomposition:

- `_orders` temp table → build on the existing `ref('int_customer_order_summary')` (don't re-read
  raw orders).
- `_cust` temp table → `ref('stg_customers')`.
- segmentation thresholds + lifecycle rules → `case` expressions in the mart, **thresholds copied
  verbatim**.
- `CREATE OR REPLACE TABLE` full rebuild → `table` materialization.

Result = `models/marts/finance/mart_customer_ltv.sql`: CTEs on the two `ref()` models, same output
columns, same thresholds, Fusion-conformant (`cast()`, lowercase, no `::`). Then prove parity with
a full-outer-join diff to `analytics.customer_ltv` (see foundations → data-validation.md and the
repo's `analyses/validate_ltv_migration.sql`).
