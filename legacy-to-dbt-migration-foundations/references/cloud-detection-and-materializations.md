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

dbt has five built-in materializations (`view`, `table`, `incremental`, `ephemeral`,
`materialized view`); the default is `view`. Per the [dbt docs](https://docs.getdbt.com/docs/build/materializations),
the rule is **progressive — start as a view, promote only when needed:**

| Legacy pattern / need | dbt materialization | Notes (dbt docs) |
|---|---|---|
| Light rename/cast, read often (staging) | `view` | The default; "start with views… only change when you notice performance problems." |
| A mart/output that's **slow to query** (BI-facing, many downstream models) | `table` | Promote view → table when querying is slow. |
| A large/event-style table whose **table build** is slow | `incremental` | Only after table is slow — "**don't start with incremental models.**" Needs `unique_key` (a **list**) + `is_incremental()` filter. |
| SCD Type 2 (history preserved) | **snapshot** | Do NOT hand-roll SCD2 in a model — use a dbt snapshot. |
| Light reusable logic used by 1–2 downstream models | `ephemeral` | Inlined as a CTE; can't be queried directly and doesn't support contracts. |

**Incremental strategies** (`incremental_strategy`, per the
[docs](https://docs.getdbt.com/docs/build/incremental-strategy)): `append`, `merge` (upsert on
`unique_key`; mirrors SCD1), `delete+insert`, `insert_overwrite` (partition-based, ignores
`unique_key`), and `microbatch` (large time-series via a configured `event_time`). Map legacy
MERGE/upsert → `merge`; truncate+insert of a partition → `insert_overwrite`; append-only → `append`.
`on_schema_change` handles new/changed columns (`ignore`/`append_new_columns`/`sync_all_columns`).

So: recommend `view` first; go to `table` when it's slow to query and to `incremental` when it's
slow to build. Incremental is still the biggest compute saving for large, frequently-run facts — but
per the docs it's an optimization you reach for, not the starting point.

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
