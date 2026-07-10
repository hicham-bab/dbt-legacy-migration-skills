# Facts, materializations, project layout & performance

Building fact tables in dbt and making them cheap to run and query.

## Contents

- [Fact types & measures](#fact-types--measures)
- [Building a fact](#building-a-fact)
- [Project layout & materializations](#project-layout--materializations)
- [Performance](#performance)

## Fact types & measures

| Fact type | Grain | Materialization |
|-----------|-------|-----------------|
| Transaction | one row per event (order line, payment) | `incremental` (append/merge) |
| Periodic snapshot | one row per entity per period (daily balance) | `incremental` on the period |
| Accumulating snapshot | one row per pipeline instance, updated across milestones | `incremental` with `merge` on the instance key |
| Factless | one row per event/coverage, no measures | `incremental` |

**Measures** — classify each:
- **Additive** — sum across all dimensions (amount, quantity). The default.
- **Semi-additive** — sum across some dimensions but not time (account balance: sum across accounts,
  not across days — average or take period-end over time).
- **Non-additive** — ratios/percentages; don't sum. Store the numerator and denominator as additive
  measures and compute the ratio in the BI layer / a metric.

## Building a fact

1. Start from the event source at the declared grain (`stg_`/`int_`).
2. Look up each dimension's **surrogate key** by joining on the natural key (and, for Type-2 dims, a
   point-in-time predicate on the event date). Carry the surrogate key as the FK.
3. Keep degenerate dimensions (order number) as plain columns.
4. Keep only keys + measures + degenerate dims — narrow.
5. Cast measures to explicit types (`cast(amount as decimal(18,2))`), Fusion-conformant.
6. Point unmatched FKs at the dimension's **unknown member** so no FK is null.

```sql
{{ config(materialized='incremental', unique_key='order_line_key') }}
-- ... CTEs: source event -> surrogate-key lookups -> final (see SKILL.md end-to-end example)
{% if is_incremental() %}
where order_date > (select coalesce(max(order_date), '1900-01-01') from {{ this }})
{% endif %}
```

## Project layout & materializations

```
models/
├── staging/      stg_*    → view      (rename/cast/clean, 1:1 with source)
├── intermediate/ int_*    → view/ephemeral (joins, derivations, surrogate-key prep)
└── marts/        dim_*/fct_* → dim=table, fact=incremental
snapshots/                  → the source snapshots feeding Type-2 dims
```

```yaml
# dbt_project.yml
models:
  my_project:
    staging:      {+materialized: view}
    intermediate: {+materialized: view}
    marts:        {+materialized: table}      # override facts to incremental in the model config()
```

Build order: `dbt snapshot` → `dbt run -s staging` → `intermediate` → `marts` (or `dbt build` for
run+test end to end). Snapshots must run before the dims that read them.

## Performance

- **Incremental facts, never full rebuild.** Filter on the load/date column in `is_incremental()`.
- **Partition + cluster the fact** by its date and highest-cardinality FK (per platform — see the
  foundations `cloud-detection-and-materializations.md`: BigQuery `partition_by`+`cluster_by`,
  Snowflake `cluster_by`, Databricks liquid clustering / Z-order, Redshift dist/sort keys).
- **Dimensions as tables**, clustered by surrogate key; they're small and joined constantly.
- **Narrow facts** — descriptive attributes belong in dimensions so scans stay cheap.
- Type-2 dims come from **snapshots** (cheap incremental capture), not recomputed history each run.
- Prove parity at the mart layer (foundations `data-validation.md`); the fact grain matches the
  legacy output's grain.
