# Data validation: legacy prod vs dbt dev (Step 5)

Compilation success is not correctness. This step proves the migrated dbt models produce the
**same data** the legacy job produced, by comparing the **legacy production output** (the table the
old tool populates in prod) against the **dbt dev output** (what the migrated models build in your
dev target) — and, for every difference, explaining *why* it exists and deciding whether it's an
accepted difference or a bug to fix. Two parity patterns are shown below: a row-for-row
full-outer-join diff and an aggregate + row-count baseline.

## Contents

- [The compile gate (free)](#the-compile-gate-free)
- [Set up the comparison: legacy prod vs dbt dev](#set-up-the-comparison-legacy-prod-vs-dbt-dev)
- [Preferred tool: audit_helper](#preferred-tool-audit_helper)
- [Two-stage parity at scale: PK coverage, then column values](#two-stage-parity-at-scale-pk-coverage-then-column-values)
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
and `dbt test` incur warehouse cost — run them after compile is clean. Some diagnostics appear only
at build time (for example Fusion's dbt1071 unspecified-numeric-precision warning), so the
zero-warnings bar applies to the first `dbt build` output as well as to compile.

**Rebuild stability (required, runs before parity).** After the first clean `dbt build`, record the
key columns and row counts of every mart. Run `dbt build --full-refresh` a second time. The two runs
must both have 0 failures, identical row counts, and identical key values. Any difference is a
non-determinism bug (for example `row_number() over (order by 0)` copied into a key; see
"Non-deterministic ordering" under [Explaining the differences](#explaining-the-differences)) to fix
before comparing with legacy data. Record the result and the columns compared in `05_parity.json`
under `rebuild_stability`:

```json
"rebuild_stability": {
  "runs": 2,
  "identical": true,
  "models": [
    {"model": "fct_sales", "key_columns": ["sales_key"], "row_counts": [1200, 1200]}
  ]
}
```

This check needs only the dev target, so it runs even when `legacy_prod_readable` is false. The
`preflight_decisions.py parity` gate fails without it.

**Snowflake shortcut: `hash_agg` as a pass/fail screen.** Instead of comparing key values row by
row, compute one hash per run over an **explicit, identically ordered column list** (never `*`:
column order changes the hash), paired with `count(*)`:

```sql
select count(*) as row_count, hash_agg(sales_key, order_status, net_amount) as table_hash
from {{ ref('fct_sales') }}
```

A mismatch is conclusive: the rebuild differs. A match is probabilistic only, so treat it as a
screen, not a full diff. The docs do not say how duplicate rows are combined, which is why
`count(*)` goes with it. Hash values are not guaranteed stable across Snowflake releases: compare
two runs taken close together, and never store a hash as a long-lived baseline
([Snowflake docs](https://docs.snowflake.com/en/sql-reference/functions/hash_agg)). Record the
columns hashed under `key_columns` and note `method: hash_agg` in the `rebuild_stability` entry.

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
   Declaring **source freshness** on the raw tables makes this explicit — see
   [dbt-features-for-migration.md](dbt-features-for-migration.md#source-freshness--rule-out-stale-inputs).

Beyond data parity, **unit tests** prove the migrated *logic* on fixed inputs (warehouse-light) —
run them here too; see
[dbt-features-for-migration.md](dbt-features-for-migration.md#unit-tests--pin-the-migrated-logic).

**You do not have to guess the legacy prod table name.** Where the source tool's Step-1 inventory
script emits it, the inventory artifact (`01_inventory.json`) carries a `parity_targets` list — one
entry per output component, with fields `unit`, `component`, `target`, `schema`, `database` and
`write_mode`. That list *is* the set of Step-5 comparison targets; work through it rather than
rediscovering targets by reading pipelines again. Entries with a null `target` are a visible gap to
resolve, not an absent one.

- **`write_mode: append` changes the comparison.** An append target **accumulates across runs**, so
  the legacy prod table holds the union of every historical run while the dbt model holds one
  rebuild. A whole-table diff will not match, and the mismatch is an artifact of the write mode, not
  a logic bug. Scope both sides to the **run window** (a load date, batch id, or run timestamp
  column) before comparing.
- **`write_mode: truncate_reload`** targets hold one run's output, so a whole-table diff is valid.

**The `legacy_prod` source must exist.** Every `source('legacy_prod', ...)` reference in this file
resolves only if a matching source block is declared in the dbt project, pointed at the legacy
production database/schema. **Nothing else in the workflow creates it** — no step generates it as a
side effect. Add it before the first parity run, using the `database`/`schema` values from
`parity_targets`:

```yaml
sources:
  - name: legacy_prod
    database: PROD          # from parity_targets.database
    schema: MARTS           # from parity_targets.schema
    tables:
      - name: fct_sales     # from parity_targets.target
```

Keep it read-only: declare it as a source and never build into it.

Only after inputs are aligned does a remaining difference point to the *transformation logic*.

## Preferred tool: audit_helper

**If the migrator allowed external packages** (Step 0 — see [dbt-packages.md](dbt-packages.md)), use
the `audit_helper` package rather than a hand-written diff — it's dbt Labs' official
migration-validation tooling and does row- and column-level classification for you. Add
`dbt-labs/audit_helper` from hub.getdbt.com (`dbt deps`). Use the current **classify** macros (not
the legacy `compare_relations`/`compare_queries`). *If they chose self-contained macros,* skip this
and use Pattern A/B below.

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
        primary_key_columns=['sales_key']) }}
   ```
   (Or `compare_and_classify_query_results(a_query, b_query, primary_key_columns=[...])` to compare
   two queries — e.g. to restrict both sides to the overlapping time window.)
3. **Find the differing columns**, then drill in:
   ```sql
   {{ audit_helper.compare_which_relation_columns_differ(
        a_relation=ref('fct_sales'), b_relation=source('legacy_prod','fct_sales'),
        primary_key_columns=['sales_key']) }}
   -- then compare_column_values(a_query, b_query, primary_key, column_to_compare) on each flagged column
   ```
4. **Schema diff** (column order + types): `audit_helper.compare_relation_columns(...)`.

Put these in an `analyses/validate_<entity>.sql`, `dbt compile`, and run the compiled SQL (or via the
dbt MCP `execute_sql`). Every non-identical row is a difference to **explain** (see below) — not
automatically a bug. Use the classify output (added/removed/modified counts + differing columns) to
drive the explanation.

## Two-stage parity at scale: PK coverage, then column values

On a large or CDC-sourced migration, do **not** jump straight to a full column diff. When the two
sides have different row populations, the missing rows dominate every column's mismatch count and you
waste compute. Split Step 5 into two gates, and score **two** metrics, not one.

**Stage 1 - PK coverage (cheap, no column hashing).** Compare primary keys only:

```sql
{{ audit_helper.compare_and_classify_query_results(
    a_query = "select pk_col from <ref to dbt model>  where <date_filter>",
    b_query = "select pk_col from <source to legacy>   where <date_filter>",
    primary_key_columns = ['pk_col'],
    columns             = ['pk_col']    -- PK only; no content comparison
) }}
```

From the matched / added / removed counts, compute **both**:

- **recall** = `matched / (matched + only_in_legacy)` - are we missing legacy rows (under-coverage)?
- **precision** = `matched / (matched + only_in_dbt)` - are we producing extra rows (fan-out)?

Proceed to the column diff only when **recall >= 95%**. A model with 100% recall but low precision has
a fan-out bug that a recall-only check would wrongly call PASS, so both must pass (see the dual-metric
scoring in [coverage-report.md](coverage-report.md)).

### Find the comparison window programmatically (static snapshots)

Legacy prod is materialized at time T1; dbt dev rebuilds at T2 (maybe months later). A rolling window
then shows phantom diffs. Establish the real overlap first:

```sql
select 'dbt'    as src, max(loss_date) from {{ ref('fct_my_model') }}
union all
select 'legacy' as src, max(loss_date) from {{ source('legacy_prod', 'fct_my_model') }}
```

Use `min(dbt_max, legacy_max)` as `date_to`, go back a fixed N days for `date_from`, and **pin these as
static dates** in the analysis (not `current_date()`, since both sides are static snapshots). A model
with a dynamic filter like `closed_date >= date_add(current_date(), -7)` will always look regressed
against a static snapshot; classify that as **Category 1 (timing/environment)**, not a bug.

### Run the column diff via view models (not analyses)

`compare_all_columns` needs real Relations it can introspect (**ephemeral models fail** -
`get_filtered_columns_in_relation` needs a warehouse relation), and it has no date-filter argument. So
apply the window in small **view** models and point the macro at them:

```sql
-- models/comparison/col_diff_a__my_model.sql   {{ config(materialized='view') }}
select * from {{ ref('my_model') }}
where date_col >= cast('2026-05-24' as date) and date_col < cast('2026-07-23' as date)

-- models/comparison/col_diff_b__my_model.sql   {{ config(materialized='view') }}
select * from {{ source('legacy_prod', 'my_model') }}
where date_col >= cast('2026-05-24' as date) and date_col < cast('2026-07-23' as date)

-- models/comparison/col_diff__my_model.sql     {{ config(materialized='view') }}
{{ audit_helper.compare_all_columns(
     a_relation = ref('col_diff_a__my_model'),
     b_relation = ref('col_diff_b__my_model'),
     primary_key = 'claim_id', summarize = true) }}
```

`dbt run --select path:models/comparison/` builds them all; `dbt show --select col_diff__my_model`
reads the result. The installed macro signature varies by version; expect
`compare_all_columns(a_relation, b_relation, primary_key, exclude_columns=[], summarize=true)` where
**`primary_key` is a SQL expression string, not a list**. Composite PK:
`primary_key = "cast(claim_id as string) || '|||' || cast(month_end_date as string)"`.

> **Enforce grain before comparing.** If a model has known 1:many joins that the legacy system hid
> with `SELECT DISTINCT`, dedup to the true grain with `qualify row_number() over (...) = 1` before the
> diff (see [cdc-deduplication.md](cdc-deduplication.md)). `SELECT DISTINCT` does **not** collapse rows
> that differ in any column.

### Exclude CDC-internal and audit columns from the diff

Some columns exist on only one side and will always show ~0% match: CDC-internal columns
(`commit_timestamp`, `max_commit_timestamp`, `_fivetran_synced`, `dms_*`) and dbt audit columns
(`dbt_updated_at`, `dbt_valid_from`/`dbt_valid_to`). These are expected, not regressions. Pass them to
`exclude_columns=[...]` so they do not dominate the mismatch counts.

An exclusion is legitimate only when it is **named in the parity record** with its reason (CDC-internal,
dbt audit, one-sided). Unnamed or unexplained exclusions are not allowed: they are how a 3-of-40-column
diff gets reported as a pass. See the completeness assertion below.

### What a failing metric points at

Diagnose by **which** of the two metrics failed - it maps straight to a class of bug:

| Failed metric | Meaning | Common root causes | Fix |
|---|---|---|---|
| **precision** low (extra rows in dbt) | fan-out | a raw CDC join without dedup; a `left join` where the model is event-scoped and needs `inner`; a 1:many join the legacy collapsed with `SELECT DISTINCT` | QUALIFY-dedup the CDC source ([cdc-deduplication.md](cdc-deduplication.md)); fix the join type; enforce grain |
| **recall** low (missing rows in dbt) | under-coverage | a value dropped from a `where ... in (...)` list (e.g. a missing brand); an over-restrictive dynamic-date filter vs a static snapshot; a source/datashare not provisioned | complete the filter; treat dynamic-date as Category 1 timing; if the source is absent mark **BLOCKED**, not FAIL |

## Pattern A: row-for-row parity (fallback)

Use only when audit_helper can't be installed.

> **⚠ A single-column diff is not parity — it is a false pass.** Comparing one column (or a
> hand-picked handful), getting zero rows back, and reporting "parity: pass" asserts nothing about
> every other column in the model. Those columns can be entirely wrong and the query still returns
> zero rows. Parity is the gate the whole methodology rests on, so Pattern A must compare **all**
> columns of the model, every time.

Two queries, run together: a **row-hash check** to find *which rows* differ, then a **per-column
comparison** to find *which columns* differ in those rows. Both full-outer-join on the grain and
return only mismatches; zero rows from **both** is parity.

**A1 — row-hash fast check (which rows differ):**

```sql
-- analyses/validate_<entity>_rows.sql
{% set cols = adapter.get_columns_in_relation(ref('fct_sales'))
              | map(attribute='name') | map('lower') | sort | list %}

with dbt_dev as (
    select
        {{ cols | join(', ') }},
        md5(concat_ws('|',
            {% for c in cols %}coalesce(cast({{ c }} as varchar), '<NULL>')
            {%- if not loop.last %}, {% endif %}{% endfor %}
        )) as row_hash
    from {{ ref('fct_sales') }}
),
legacy_prod as (
    select
        {{ cols | join(', ') }},
        md5(concat_ws('|',
            {% for c in cols %}coalesce(cast({{ c }} as varchar), '<NULL>')
            {%- if not loop.last %}, {% endif %}{% endfor %}
        )) as row_hash
    from {{ source('legacy_prod', 'fct_sales') }}
)
select
    coalesce(d.sales_key, l.sales_key) as sales_key,
    case
        when d.sales_key is null then 'missing_in_dbt'
        when l.sales_key is null then 'missing_in_legacy'
        else 'row_mismatch'
    end as diff_type
from dbt_dev d
full outer join legacy_prod l on d.sales_key = l.sales_key
where d.sales_key is null
   or l.sales_key is null
   or d.row_hash <> l.row_hash
```

The hash is a *finder*, not proof — it tells you a row differs somewhere, not where. Three things
make it spuriously mismatch:

- **NULL handling must be identical on both sides.** `concat_ws` skips NULLs, so `(a, NULL, c)` and
  `(a, c, NULL)` hash alike unless every value is `coalesce`d to a sentinel first. Use the same
  sentinel (`'<NULL>'` above) on both sides.
- **Column order must match.** Both sides are built from the same sorted `cols` list for exactly
  this reason — never enumerate the two sides independently.
- **Types must match.** `cast(... as varchar)` renders `1.50` and `1.5`, or two timestamp
  precisions, as different strings. Normalise first (round decimals to a fixed scale, cast
  timestamps to a common precision) or the hash reports differences that do not exist.

Both sides are built from the **model's** column list, so a column the legacy table doesn't have
makes the query fail to compile/run. That is a finding — a schema difference — not an obstacle:
record it and reconcile the schemas before claiming parity.

**A2 — per-column comparison (which columns differ):**

```sql
-- analyses/validate_<entity>_columns.sql
{% set cols = adapter.get_columns_in_relation(ref('fct_sales'))
              | map(attribute='name') | map('lower') | sort | list %}
{% set key  = ['sales_key'] %}

with joined as (
    select
        coalesce(d.sales_key, l.sales_key) as sales_key,
        d.sales_key is null                as missing_in_dbt,
        l.sales_key is null                as missing_in_legacy,
        {% for c in cols %}
        d.{{ c }} as dbt_{{ c }}, l.{{ c }} as legacy_{{ c }}
        {%- if not loop.last %},{% endif %}
        {% endfor %}
    from {{ ref('fct_sales') }} d
    full outer join {{ source('legacy_prod', 'fct_sales') }} l
        on d.sales_key = l.sales_key
),
flagged as (
    select
        sales_key, missing_in_dbt, missing_in_legacy,
        {% for c in cols if c not in key %}
        -- NULL-safe: both NULL = match; one NULL = mismatch
        case when (dbt_{{ c }} is null) <> (legacy_{{ c }} is null) then 1
             when dbt_{{ c }} is null and legacy_{{ c }} is null    then 0
             when dbt_{{ c }} <> legacy_{{ c }}                     then 1
             else 0 end as mm_{{ c }}
        {%- if not loop.last %},{% endif %}
        {% endfor %}
    from joined
)
select * from flagged
where missing_in_dbt or missing_in_legacy
   or ({% for c in cols if c not in key %}mm_{{ c }} = 1
       {%- if not loop.last %} or {% endif %}{% endfor %})
```

Aggregate `sum(mm_<col>)` across `flagged` to get a mismatch count per column — that ranks which
columns to investigate first.

**The column list must be enumerated from the model's actual schema**, not hand-picked.
`adapter.get_columns_in_relation()` above does that at compile time; without it you are asserting
parity over whatever columns you happened to remember. **A parity claim that covers fewer columns
than the model has is not a parity claim** — it is a claim about those columns only, and must be
described that way.

**Required completeness assertion.** Record per model:

```
columns_compared / columns_total
```

`columns_compared + len(excluded_columns) < columns_total` is a **FAIL**, not a pass — regardless of
how few rows the diff returned. `excluded_columns` counts only columns listed by name, each with a
reason (see "Exclude CDC-internal and audit columns" above). A model whose diff came back empty over
3 of 40 columns, with nothing named as excluded, has not been validated. All three numbers go into the
parity record alongside the result (see the last section); a result recorded without them is
incomplete.

Use `round()` on decimals (in both the hash and the per-column compare) to absorb legitimate
cross-platform floating-point noise. Every returned row is a difference to **explain** (next
section), not automatically a bug.

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
- **Type/format representation**: a column stored as `timestamp` on one side but `varchar` on the
  other reads as 0% match even when the values agree; cast **both** sides to a common type before
  comparing.
- **Floating-point** noise (compare with `round()` / a tolerance).
- **NULL handling & ordering**, **collation / case sensitivity**, **timestamp / timezone** defaults,
  **date parsing / formatting** differences between the legacy engine and the target warehouse.
- **Non-deterministic ordering** — `row_number()` over tied keys can rank differently; add a
  deterministic tiebreaker to the `order by`. A **constant** `order by` (`order by 0`, `order by 1`,
  `order by null`) has no ordering at all, so a tiebreaker does not fix it: replace the column with a
  deterministic content-based key (Matillion → matillion-component-mapping.md, translation trap 6).
  This is a bug to fix, not an accepted difference, when the column is a key.

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
  bucketed as *accepted* (with reasons) vs *fixed* (with the bug) — **plus `columns_compared` /
  `columns_total` and `excluded_columns` (each named, with its reason)**. A pass recorded without the
  column counts is incomplete, and `columns_compared + len(excluded_columns) < columns_total` is a
  fail (see Pattern A). Only accepted differences may
  remain; unexplained differences block the model and count against coverage in Step 7. Write this
  into the `migration_changes.md` parity section.
- **Mock data is not parity.** A build on agent-created seed sources (`inputs.test_source_mode:
  seeds`) proves the SQL runs and the tests hold on fabricated rows only. Label it "mock data only";
  it never sets `parity: pass` and never counts toward coverage. See
  [test-sources-and-mock-data.md](test-sources-and-mock-data.md).
