# Cost comparison: measured, apples-to-apples (Step 6)

The credible cost number is **measured, not estimated**. The legacy job and the migrated dbt models
both push work into the warehouse, and the warehouse already records what each consumed. So we
**measure the legacy run's actual consumption and the dbt run's actual consumption on the same
data, isolate each run, convert to dollars with a cited rate, and compare** — and we make the whole
analysis reproducible by emitting the exact measurement queries and raw numbers. A TCO estimate
(license/infra/FTE) is a clearly-labeled secondary context, never the headline.

## Contents

- [Principle: measure, don't estimate](#principle-measure-dont-estimate)
- [What a credible comparison requires](#what-a-credible-comparison-requires)
- [Method](#method)
- [Per-platform measurement queries](#per-platform-measurement-queries)
- [The visible, reproducible cost artifact](#the-visible-reproducible-cost-artifact)
- [Honest limits](#honest-limits)
- [TCO context (secondary, labeled estimate)](#tco-context-secondary-labeled-estimate)

## Principle: measure, don't estimate

- **Per-query dollar attribution is only clean on Snowflake** (`QUERY_ATTRIBUTION_HISTORY` gives
  credits per query) **and BigQuery on-demand** (`total_bytes_billed` per job).
- **Databricks, Redshift, and BigQuery-under-reservations meter compute per resource over time,
  not per statement.** For those, isolate the run on a **dedicated warehouse/workgroup over a clean
  time window** and attribute the whole window. Do **not** claim statement-level dollar precision
  there — say how you attributed it.

## What a credible comparison requires

1. **Same inputs / same size.** Run legacy and dbt against the **same source data** (same tables,
   same row counts, same time window). Report the row counts. Normalize to **cost per 1M rows** so
   "same size" is explicit and the comparison survives volume differences.
2. **Isolate each run** so you sum only its queries — via a query tag (Snowflake), job label
   (BigQuery), or a marker comment / dedicated warehouse (Databricks, Redshift).
3. **Disable result caching** during measurement, or you measure a cache hit, not compute. Verify
   with the platform's cache-hit flag.
4. **Run each side N times (≥3), take the median** — warehouse timings are noisy.
5. **Cite the dollar rate** with its source, region, and date. Rates are region/edition/contract-
   specific; never publish a number without the rate it came from.
6. **Where does the legacy actually run?**
   - Legacy that **pushes down to the warehouse** (stored procedures, Matillion transformation,
     ELT Informatica/Talend) — its real queries are already in query history. Measure a real prod
     run (filter by the tool's user/warehouse/time window), or re-run the captured legacy SQL under
     a tag.
   - Legacy that runs **off-warehouse** (engine-based Informatica/Talend) — it consumed no
     warehouse compute for transforms, so an in-warehouse legacy number doesn't exist. Be explicit:
     either (a) run the legacy's equivalent pushed-down SQL in the warehouse under a tag and label
     it "reconstructed baseline," or (b) compare dbt's measured warehouse cost against the legacy
     tool's own run cost (engine runtime × instance/license rate) and state plainly that the two
     are **different cost bases**. Never silently compare a warehouse number to an engine number.

## Method

1. Freeze the input data (or snapshot it) so both runs read identical sources.
2. Disable result cache; set the isolation tag/label/marker for the **legacy** run; run it ≥3×.
3. Same for the **dbt** run (`dbt build` the equivalent models) with its own tag/label.
4. Pull actual consumption for each run from the platform's metering views (queries below).
5. Convert to dollars with a cited rate; compute per-run and per-1M-row figures; take medians.
6. Emit the [visible artifact](#the-visible-reproducible-cost-artifact) — queries + raw numbers +
   comparison — so anyone can re-run and audit it.

## Per-platform measurement queries

> Column/object names verified against vendor docs (July 2026). Confirm the **dollar rate** for
> your region/contract before publishing. `<...>` = fill in.

### Snowflake — per-query credits (most precise)
Tag the run: `alter session set use_cached_result = false; alter session set query_tag = '<run_tag>';`
For dbt use the `query_tag` model config (it issues `alter session set query_tag`), **not**
`query-comment` (comments aren't visible to the attribution view).
```sql
with attributed as (
  select sum(credits_attributed_compute)
       + sum(coalesce(credits_used_query_acceleration, 0)) as total_credits,
         count(*) as query_count
  from snowflake.account_usage.query_attribution_history
  where query_tag = '<run_tag>'
    and start_time >= '<start>' and start_time < '<end>'
),
rate as (   -- derive effective $/credit from org usage (or use your contract rate)
  select sum(usage_in_currency) / nullif(sum(usage), 0) as usd_per_credit
  from snowflake.organization_usage.usage_in_currency_daily
  where service_type = 'WAREHOUSE_METERING' and rating_type = 'compute'
    and usage_date >= '<start>'::date and usage_date < '<end>'::date
)
select a.query_count, a.total_credits, r.usd_per_credit,
       a.total_credits * r.usd_per_credit as estimated_cost_usd
from attributed a cross join rate r;
```
Notes: `QUERY_ATTRIBUTION_HISTORY` excludes ≤~100ms queries and Adaptive Warehouses; up to 8h
latency. Reconcile totals against `WAREHOUSE_METERING_HISTORY` (`credits_used_compute`).

### BigQuery — bytes billed (on-demand)
Isolate with a label: `set @@query_label = "run:baseline";` (or `bq --label run:baseline`); for dbt
set `query-comment: job-label: true`. Disable cache: `--nouse_cache` / `useQueryCache=false`.
```sql
select count(*) as job_count,
       sum(total_bytes_billed) as bytes_billed,
       sum(total_bytes_billed)/power(1024,4) as tib_billed,
       (sum(total_bytes_billed)/power(1024,4)) * <usd_per_tib>  as est_cost_usd,  -- e.g. 6.25 US, VARIES
       sum(total_slot_ms)/1000/3600 as slot_hours   -- illustrative only under reservations
from `region-<region>`.INFORMATION_SCHEMA.JOBS_BY_PROJECT as j, unnest(j.labels) as label
where j.job_type='QUERY' and j.state='DONE' and j.error_result is null and j.cache_hit = false
  and label.key='run' and label.value='baseline'
  and j.creation_time between timestamp('<start>') and timestamp('<end>');
```
`total_bytes_billed` is 0 for cache hits/failures. Under Editions/reservations, per-query dollars
are not invoice-accurate — attribute by reservation/window instead and say so.

### Databricks — DBUs over an isolated window
No per-statement dollars. Run the workload on a **dedicated SQL warehouse** (or tag via
`custom_tags`), disable cache (`set use_cached_result = false;`), attribute the window:
```sql
select u.usage_metadata.warehouse_id as warehouse_id,
       sum(u.usage_quantity) as total_dbus,
       sum(u.usage_quantity * lp.pricing.effective_list.default) as total_cost
from system.billing.usage u
join system.billing.list_prices lp
  on lp.sku_name = u.sku_name
 and u.usage_end_time >= lp.price_start_time
 and (u.usage_end_time <  lp.price_end_time or lp.price_end_time is null)
where u.usage_unit = 'DBU'
  and u.usage_metadata.warehouse_id = '<warehouse_id>'      -- or: u.custom_tags['run'] = 'baseline'
  and u.usage_date >= date'<start>' and u.usage_date < date'<end>'
group by 1;
```
Per-statement duration/bytes (not dollars) come from `system.query.history` (filter
`compute.warehouse_id`; Public Preview; SQL-warehouse/serverless only, not classic clusters).

### Redshift — RPU-seconds (serverless) / node-hours (provisioned)
Isolate with a **marker comment** in the SQL (`query_group`→SYS linkage is unconfirmed); disable
cache: `set enable_result_cache_for_session to off;`.
```sql
-- serverless: charged RPU-seconds over an isolated window -> $
select sum(charged_seconds)          as charged_rpu_seconds,
       sum(charged_seconds)/3600.0   as charged_rpu_hours,
       (sum(charged_seconds)/3600.0) * <usd_per_rpu_hour> as est_cost_usd  -- region-specific
from sys_serverless_usage
where start_time >= '<start>' and end_time <= '<end>';

-- per-query effort (relative, not dollars) for the same run:
select count(*) as query_count, sum(execution_time)/1e6 as execution_sec
from sys_query_history
where query_text like '%<marker>%' and query_text not like '%sys_query_history%'
  and start_time between '<start>' and '<end>';
```
Provisioned Redshift is node-hour billed — no per-query dollar metric; use node-count × node-hour
rate over the isolated window. Serverless view retains only 7 days.

## The visible, reproducible cost artifact

Make the analysis auditable — emit a `cost_analysis/` folder, not just a number:

- `measurement_queries.sql` — the **exact** metering queries you ran (from above, filled in), so
  anyone can re-run them.
- `raw_metrics.csv` — per-run, per-model rows: `run(legacy|dbt), model/statement, runs, median
  credits/bytes/DBUs/RPU-sec, elapsed_sec, row_count`.
- `rates.md` — every dollar rate used, with **source URL, region, and date**.
- `cost_comparison.md` — the report (template below), including the methodology and caveats so a
  reader sees *how* the number was produced.
- Optional `cost_chart` — a side-by-side bar chart (legacy vs dbt, total and per-model). Use the
  `dataviz` skill for the chart.

Report template (`cost_comparison.md`):
```markdown
# Cost Comparison — <source> → dbt on <platform> (measured)

## How this was measured
- Platform: <...>; metering source: <QUERY_ATTRIBUTION_HISTORY / JOBS / system.billing.usage / SYS_*>
- Legacy run: <where it ran; tag/label/window used>; dbt run: <tag/label used>
- Same inputs: <source tables, row counts, time window>
- Result cache: disabled (<how>); runs: <N>, median reported
- Dollar rate: <$X per credit/TiB/DBU/RPU-hour> — source <url>, region <...>, date <...>

## Measured result
| Workload | Runs | Median compute (credits/TiB/DBU/RPU-s) | $ / run | Rows | $ / 1M rows |
|----------|------|----------------------------------------|---------|------|-------------|
| Legacy   |      |                                        |         |      |             |
| dbt      |      |                                        |         |      |             |
| **Δ**    |      |                                        | **-X%** |      | **-Y%**     |

## Caveats
- <e.g. Databricks/Redshift: attributed by isolated window, not per statement>
- <legacy cost basis: in-warehouse measured / reconstructed / off-warehouse engine cost>

See measurement_queries.sql and raw_metrics.csv for the underlying data.
```

## Honest limits

- Per-query dollars are real only on Snowflake and BigQuery-on-demand; elsewhere say "attributed by
  isolated window."
- Prices are region/edition/contract-specific — always cite the rate and source; if you can't get
  the real rate, report the raw consumption (credits/bytes/DBUs/RPU-sec) and mark dollars as TBD.
- If the legacy ran off-warehouse, don't fabricate an in-warehouse legacy number — use a labeled
  reconstructed baseline or compare different cost bases explicitly.

## TCO context (secondary, labeled estimate)

Optionally add annual TCO context — legacy license/infra/maintenance-FTE vs dbt seats + the
measured recurring compute above. **Label every input as an estimate and cite its source.** This is
supporting context for a business case, not the headline; the measured warehouse comparison is the
credible core.
