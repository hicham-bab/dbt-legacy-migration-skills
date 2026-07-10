# Cloud detection & cost-aware materializations (Step 0 + Step 3)

Used by all three migration skills. This reference has two jobs: (1) the questions to ask before
writing any dbt code, and (2) how to pick materializations that are correct **and cheap** on the
target cloud.

## Contents

- [Questions to ask up front](#questions-to-ask-up-front)
- [Choosing a materialization](#choosing-a-materialization)
- [Per-platform cost-aware guidance](#per-platform-cost-aware-guidance)

## Questions to ask up front

Ask these at Step 0 and record the answers — every later step depends on them. **Present them as one
batch of choices, each with a recommended default and the alternatives** (the migrator picks — see
the "Suggest, don't decide" principle in the foundations skill). Detect what you can from the
environment to *inform your recommendation*, but still offer the choice — don't silently default.
Don't start parsing until at least the platform, architecture, and packages/macros calls are made.

1. **Landing spot?** A **new standalone dbt project** (clean, mirrors the legacy workload 1:1) or
   **fold into an existing project** (reuse its sources/config). Recommend new-standalone unless the
   legacy domain clearly overlaps an existing project's sources.
2. **Which data warehouse / cloud is the target?** Snowflake, Databricks, BigQuery, or Redshift.
   This drives dialect, materialization defaults, and the cost model. Inspect `profiles.yml`
   (`type:` field) / installed adapters to recommend, then confirm with the migrator.
3. **dbt Fusion or dbt Core?** Detect: check for `dbtf`; else run `dbt --version` and look for a
   `dbt-fusion` prefix. Fusion is preferred — its real-time compile is the free iteration gate.
4. **Packages or self-contained macros?** May the migration use **external dbt packages
   (from hub.getdbt.com only)** — reusing maintained macros — or should it stay **self-contained**
   and generate the needed macros itself? Drives every later step. See [dbt-packages.md](dbt-packages.md).
   *(The target-architecture choice is the other big one — Step 2, see target-architecture.md.)*
5. **What is the dev target?** A dev schema/database the migration can build into safely
   (`dbt build` in dev), separate from prod.
6. **Is the legacy output still queryable** for parity checks? (the existing warehouse table the
   old job populated, or the source system). Needed for Step 5 data validation.
7. **Do you have legacy run metrics** (runtime, license tier, infra, schedule frequency)? Needed
   for the Step 6 cost comparison; absent these, Step 6 produces the TCO estimate only.

## Choosing a materialization

Map the legacy write pattern to a dbt materialization, then apply the platform tuning below. New to
these terms (view / table / incremental / ephemeral)? Explain them from
[dbt-concepts-explained.md](dbt-concepts-explained.md#materializations-view-table-incremental-ephemeral)
as you go.

| Legacy pattern | dbt materialization | Notes |
|---|---|---|
| Full rebuild of a table each run (`CREATE OR REPLACE TABLE`, truncate+insert) | `table` | Default for marts. |
| Lightweight transform, no heavy compute, read often | `view` | Staging models. |
| Append / merge-on-key / upsert (`MERGE`, Update Strategy insert-else-update) | `incremental` | Use `unique_key` + an incremental strategy; see per-platform notes. |
| SCD Type 2 (history preserved: effective/expiry dates, current flag) | **snapshot** | Do NOT hand-roll SCD2 in a model — use a dbt snapshot. |
| Reusable subroutine reused by several jobs (mapplet, `tRunJob`, shared proc) | `ephemeral` model or macro | Inline where small; intermediate model where reused. |

Default to `view` for staging and `table` for marts unless the legacy job clearly upserts on a
key (then `incremental`) or preserves history (then snapshot). Prefer incremental for large,
frequently-run fact loads — it is the single biggest compute saving in most migrations.

## Per-platform cost-aware guidance

### BigQuery
- **Partition** fact/large tables on the date column; **cluster** on the common filter/join keys.
  Config: `partition_by={'field': 'order_date', 'data_type': 'date'}`, `cluster_by=['customer_id']`.
- Incremental with partition pruning: `incremental_strategy='insert_overwrite'` on the partition,
  or `merge` with `unique_key`. This limits bytes billed to touched partitions.
- Avoid `SELECT *` — BigQuery bills on bytes scanned per column. Project only needed columns.
- In dev, use `--full-refresh` sparingly; prefer incremental to keep dev bytes low.

### Snowflake
- Right-size the warehouse for the job: `+snowflake_warehouse: 'TRANSFORM_XS'` in dev, larger only
  for heavy marts. Idle auto-suspend keeps cost down.
- Incremental via `incremental_strategy='merge'` with `unique_key`. Use `delete+insert` only when
  merge keys aren't unique.
- Add a `cluster_by` (clustering key) only on very large tables that are filtered/joined on a
  consistent key — clustering is not free to maintain.
- Use `transient` tables in dev (no fail-safe storage cost): `+transient: true`.

### Databricks
- Materialize as Delta (default). Enable **liquid clustering** (`cluster_by`) or Z-ORDER on the
  frequent filter/join columns instead of static partitions for most tables.
- Incremental via `incremental_strategy='merge'` with `unique_key`; the Delta MERGE replaces the
  legacy Update Strategy / MERGE.
- Enable Photon on the SQL warehouse/cluster for cheaper vectorized execution; size the cluster to
  the job.

### Redshift
- Set `dist` (distribution) and `sort` keys on large tables: distribute facts on the join key to
  co-locate with dims; sort on the date/filter column.
- Incremental via `incremental_strategy='merge'` (or `append` for insert-only loads).
- Keep dev tables small; run `VACUUM`/`ANALYZE` considerations out of dbt (scheduled separately).

**Cross-platform rule (Fusion):** never emit platform-specific cast syntax (`::`) or functions
(`nvl`, `ifnull`, `decode`). Use `cast(... as ...)` and `coalesce()`; let the target platform
config keys (above) carry the platform specifics.
