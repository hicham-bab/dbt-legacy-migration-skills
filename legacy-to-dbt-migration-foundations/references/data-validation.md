# Data validation: legacy prod vs dbt dev (Step 5)

Compilation success is not correctness. This step proves the migrated dbt models produce the
**same data** the legacy job produced, by comparing the **legacy production output** (the table the
old tool populates in prod) against the **dbt dev output** (what the migrated models build in your
dev target) — and, for every difference, explaining *why* it exists and deciding whether it's an
accepted difference or a bug to fix. Patterns sourced from
`~/dbt-gcp-retail-copilot/analyses/validate_ltv_migration.sql` (row-for-row diff) and
`~/dbt-oracle-to-databricks/validation/parity_checks.sql` (aggregate baseline).

## Contents

- [The compile gate (free)](#the-compile-gate-free)
- [Set up the comparison: legacy prod vs dbt dev](#set-up-the-comparison-legacy-prod-vs-dbt-dev)
- [Preferred tool: audit_helper](#preferred-tool-audit_helper)
- [Pattern A: row-for-row parity (fallback)](#pattern-a-row-for-row-parity-fallback)
- [Pattern B: aggregate + row-count baseline (fallback)](#pattern-b-aggregate--row-count-baseline-fallback)
- [Explaining the differences](#explaining-the-differences)
- [Running the checks & recording the result](#running-the-checks--recording-the-result)

## The compile gate (free)

Iterate here first — it costs no warehouse compute:

```bash
rm -rf target/    # clear stale schema cache when the target platform changed
dbt compile       # or dbtf compile
```

Fix every error **and warning** until compile is clean, then run models once
(`dbt build` / `dbt run`) into **dev** to materialize them before parity checks. Only parity checks
and `dbt test` incur warehouse cost — run them after compile is clean.

## Set up the comparison: legacy prod vs dbt dev

You are comparing two tables produced in **different environments**, so control the inputs before
you compare — otherwise you'll misread an environment difference as a logic bug.

1. **Identify the legacy prod table** — the actual output the legacy tool writes in production
   (e.g. `PROD.MARTS.FCT_SALES`). This is the source of truth. Read-only; never write to it.
2. **Point dbt dev at the same source data the legacy prod run consumed.** Ideally build the dbt
   models in dev **from the same raw/source tables** (or a snapshot of them) that fed the legacy
   prod run. If dev reads a different/refreshed copy of the sources, differences are expected and
   not evidence of a logic error.
3. **Align the time window / grain.** If dev only holds a subset (fewer dates, sampled rows),
   restrict the comparison to the overlapping window (`where order_date between …`) so you compare
   like for like.
4. **Note the run timestamps.** Record when the legacy prod table was last built and when the dbt
   dev run happened — freshness gaps are the most common "difference" and must be ruled out first.

Only after inputs are aligned does a remaining difference point to the *transformation logic*.

## Preferred tool: audit_helper

**Use the `audit_helper` package rather than a hand-written diff** — it's dbt Labs' official
migration-validation tooling and does row- and column-level classification for you. Add
`dbt-labs/audit_helper` to `packages.yml` (`dbt deps`); see
[dbt-packages.md](dbt-packages.md#audit_helper--the-validation-centerpiece). Use the current
**classify** macros (not the legacy `compare_relations`/`compare_queries`).

1. **Fast yes/no** — is the dbt-dev model already identical to legacy prod?
   ```sql
   {{ audit_helper.quick_are_relations_identical(
        a_relation=ref('fct_sales'),
        b_relation=source('legacy_prod', 'fct_sales')) }}
   ```
2. **Classified row comparison** — summary of identical / added / removed / modified rows:
   ```sql
   {{ audit_helper.compare_and_classify_relation_rows(
        a_relation=ref('fct_sales'),
        b_relation=source('legacy_prod', 'fct_sales'),
        primary_key='sales_key') }}
   ```
   (Or `compare_and_classify_query_results` to compare two queries — e.g. to restrict both sides to
   the overlapping time window.)
3. **Find the differing columns**, then drill in:
   ```sql
   {{ audit_helper.compare_which_relation_columns_differ(
        a_relation=ref('fct_sales'), b_relation=source('legacy_prod','fct_sales'),
        primary_key='sales_key') }}
   -- then compare_column_values(...) on each flagged column
   ```
4. **Schema diff** (column order + types): `audit_helper.compare_relation_columns(...)`.

Put these in an `analyses/validate_<entity>.sql`, `dbt compile`, and run the compiled SQL (or via the
dbt MCP `execute_sql`). Every non-identical row is a difference to **explain** (see below) — not
automatically a bug. Use the classify output (added/removed/modified counts + differing columns) to
drive the explanation.

## Pattern A: row-for-row parity (fallback)

Use only when audit_helper can't be installed. Full-outer-join the dbt dev model to the legacy prod
table on the grain; return **only mismatches**. Zero rows = perfect parity.

```sql
-- analyses/validate_<entity>_migration.sql
with dbt_dev as (
    select * from {{ ref('fct_sales') }}                       -- built in dev
),
legacy_prod as (
    select * from {{ source('legacy_prod', 'fct_sales') }}     -- the prod table the old tool writes
),
compare as (
    select
        coalesce(d.sales_key, l.sales_key) as sales_key,
        d.net_amount as dbt_net_amount,
        l.net_amount as legacy_net_amount,
        case
            when d.sales_key is null then 'missing_in_dbt'      -- dbt dropped a row
            when l.sales_key is null then 'missing_in_legacy'   -- dbt produced an extra row
            when round(d.net_amount, 2) <> round(l.net_amount, 2) then 'value_mismatch'
        end as diff_type
    from dbt_dev d
    full outer join legacy_prod l on d.sales_key = l.sales_key
)
select * from compare
where diff_type is not null
```

Use `round()` on decimals to absorb legitimate cross-platform floating-point noise. Every returned
row is a difference to **explain** (next section), not automatically a bug.

## Pattern B: aggregate + row-count baseline (fallback)

Best when a full row-level compare is too large, or the legacy prod table can't be queried directly
but its metrics were captured. Take a baseline of row counts + key aggregates from the legacy prod
run (store it, e.g. `baseline_metrics.csv`), then diff the dbt dev model's equivalents:

```sql
select
    count(*)                          as row_count,
    count(distinct customer_key)      as distinct_customers,
    round(sum(net_amount), 2)         as total_net_amount,
    round(avg(net_amount), 2)         as avg_net_amount
from {{ ref('fct_sales') }}
```

Compare each metric to the baseline; anything outside tolerance is a difference to explain.

## Explaining the differences

For **every** difference, classify the cause and decide: **accept** (a legitimate
environment/platform difference — document it) or **fix** (a real migration bug — correct the
model and re-run). Never leave a difference unexplained.

**Category 1 — environment / freshness (usually accept, after confirming):**
- **Source data drift** — dev read a newer/older or refreshed copy of the sources than the legacy
  prod run; late-arriving or updated rows differ. *Explanation:* different inputs, not different
  logic. Re-align inputs and re-check.
- **Stale legacy prod table** — the legacy job hasn't run since the sources changed, so prod is
  behind. *Explanation:* prod is out of date, dbt dev is actually more current.
- **Subset / time-window** — dev holds fewer rows/dates than prod. *Explanation:* restrict to the
  overlapping window.
- **SCD/snapshot timing** — a snapshot captured state at a different moment than the legacy SCD run.

**Category 2 — platform / representation (usually accept, document):**
- Numeric **precision & rounding** (e.g. `SUM()` scale differs across platforms → cast to a fixed
  `decimal(p,s)`).
- **Floating-point** noise (compare with `round()` / a tolerance).
- **NULL handling & ordering**, **collation / case sensitivity**, **timestamp / timezone** defaults,
  **date parsing / formatting** differences between the legacy engine and the target warehouse.
- **Non-deterministic ordering** — `row_number()` over tied keys can rank differently; add a
  deterministic tiebreaker to the `order by`.

**Category 3 — real migration bugs (must fix):**
- **Join fan-out** — a one-to-many join multiplied rows (inflated counts/sums). Fix the grain.
- **Wrong join type** — `inner` where the legacy used an outer join (or vice-versa) adds/drops rows.
- **Filter/predicate mismatch** — a status/date/`where` condition translated wrong (rows included or
  excluded that shouldn't be).
- **Aggregation grain mismatch** — wrong `group by`, so totals don't tie.
- **Expression translation error** — a derived column computed differently (e.g. age as
  `datediff('year', …)` instead of `floor(datediff('day', …)/365.25)`; `decode`/`case` mis-mapped).
- **Missing dedup** — a UNIQUE MATCH / distinct step not reproduced, leaving duplicates.
- **Type cast changing values** — truncation/overflow from a narrower target type.

**How to attribute a difference:** quantify it (count and % of rows by `diff_type`), pull 3-5
representative mismatched rows, trace the columns that differ back through the model's CTEs to the
component/transformation that produced them, and name the cause. Category 1-2 → document as an
accepted difference with the justification; Category 3 → fix the model and re-run the parity check
until only accepted differences remain.

## Running the checks & recording the result

- Preview with `dbt show --select <model> --limit 5` on the dev target.
- Run the parity `analysis` via `dbt compile` then execute the compiled SQL, or run it directly
  through the dbt MCP `execute_sql` tool. Query the legacy prod table read-only through the same
  connection or a source pointed at prod.
- Use the dbt MCP `get_model_health` / `get_model_performance` tools to confirm tests pass and read
  run stats (also feeds Step 6 cost).
- **Record per model:** legacy prod vs dbt dev result — `parity: pass`, or the count of differences
  bucketed as *accepted* (with reasons) vs *fixed* (with the bug). Only accepted differences may
  remain; unexplained differences block the model and count against coverage in Step 7. Write this
  into the `migration_changes.md` parity section.
