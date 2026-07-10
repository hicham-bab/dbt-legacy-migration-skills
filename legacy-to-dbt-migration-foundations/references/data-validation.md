# Data validation against the warehouse (Step 5)

Compilation success is not correctness. This step proves the migrated dbt models produce the
**same data** the legacy job produced. Two levels: the free compile gate, then data parity.
Patterns sourced from `~/dbt-gcp-retail-copilot/analyses/validate_ltv_migration.sql` (row-for-row
diff) and `~/dbt-oracle-to-databricks/validation/parity_checks.sql` (aggregate baseline).

## Contents

- [The compile gate (free)](#the-compile-gate-free)
- [Pattern A: row-for-row parity](#pattern-a-row-for-row-parity)
- [Pattern B: aggregate + row-count baseline](#pattern-b-aggregate--row-count-baseline)
- [Running the checks](#running-the-checks)

## The compile gate (free)

Iterate here first — it costs no warehouse compute:

```bash
rm -rf target/    # clear stale schema cache when the target platform changed
dbt compile       # or dbtf compile
```

Fix every error **and warning** until compile is clean, then run models once
(`dbt build` / `dbt run`) to materialize them before parity checks. Only parity checks and
`dbt test` incur warehouse cost — run them after compile is clean.

## Pattern A: row-for-row parity

Best when the legacy output table is still queryable. Full-outer-join the migrated model to the
legacy table on the grain; return **only mismatches**. Zero rows = perfect parity.

```sql
-- analyses/validate_<entity>_migration.sql
with dbt_model as (
    select * from {{ ref('fct_sales') }}
),
legacy as (
    select * from {{ source('legacy', 'fct_sales_legacy') }}
),
compare as (
    select
        coalesce(d.sales_key, l.sales_key) as sales_key,
        d.net_amount as dbt_net_amount,
        l.net_amount as legacy_net_amount,
        case
            when d.sales_key is null then 'missing_in_dbt'
            when l.sales_key is null then 'missing_in_legacy'
            when d.net_amount <> l.net_amount then 'value_mismatch'
        end as diff_type
    from dbt_model d
    full outer join legacy l on d.sales_key = l.sales_key
)
select * from compare
where diff_type is not null
```

Use `round()` on decimals to absorb legitimate cross-platform floating-point differences. Any
rows returned are the residual to investigate (and count against coverage in Step 7).

## Pattern B: aggregate + row-count baseline

Best when a full row-level compare is too large or the legacy table is gone but metrics were
captured. Compute a baseline of row counts + key aggregates from the legacy run, store it (e.g.
`baseline_metrics.csv`), then diff the dbt model's equivalents:

```sql
select
    count(*)                          as row_count,
    count(distinct customer_key)      as distinct_customers,
    round(sum(net_amount), 2)         as total_net_amount,
    round(avg(net_amount), 2)         as avg_net_amount
from {{ ref('fct_sales') }}
```

Compare each metric to the baseline; anything outside tolerance is a mismatch to investigate.

## Running the checks

- Preview with `dbt show --select <model> --limit 5` on the dev target.
- Run the parity `analysis` via `dbt compile` then execute the compiled SQL, or run it directly
  through the dbt MCP `execute_sql` tool.
- Use the dbt MCP `get_model_health` / `get_model_performance` tools to confirm tests pass and to
  read run stats (also feeds Step 6 cost).
- Record parity result per model (pass / N mismatches) — this is the evidence the migration is
  correct, and drives the coverage number.
