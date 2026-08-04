# Respecting the target warehouse: compile against the connected adapter

The target warehouse is **whatever the customer connected in the dbt platform** (their project's
active connection / profile), not a fixed choice. So conformance is not guaranteed by memorizing
per-warehouse rules; it is guaranteed by **compiling the generated dbt against that connected
adapter, with contracts enforced.** dbt Fusion's compile-time analysis is authoritative for that
specific target and catches what a static rulebook would miss.

## The gate

1. **Detect the connected target (Step 0).** Read the project's active connection / `profiles.yml`
   target. That adapter (Snowflake / Databricks / BigQuery / Redshift / ...) is the source of truth
   for dialect and types.
2. **Compile early and iterate.** Run `dbt parse` then `dbt compile` against the connected adapter
   (Fusion resolves functions, columns, and types in real time). Fix each error the compiler reports,
   then recompile. This is the fast loop; do it per model, not once at the end.
3. **Enforce contracts while compiling/building** so the preflight checks each `data_type` against the
   real adapter.

A migration is conformant only when it **parses and compiles clean against the connected target
adapter** (in addition to the idiomatic quality bar and data parity).

## What compiling on the real adapter catches (so you do not need a per-warehouse rulebook)

- **Dialect functions.** `qualify` is unsupported on some adapters (e.g. Redshift); `listagg` vs
  `array_join(collect_list(...))`, date add/diff, regex, and string functions differ. The compiler
  errors on an unsupported function against the connected adapter.
- **Contract `data_type` validity.** `string` vs `varchar` vs `number` vs `int64` vs `numeric` differ
  by adapter; an enforced contract's preflight fails on a type the adapter does not accept.
- **Self-contained macro portability.** A hand-rolled macro with `cast(... as string)` compiles on
  Databricks/BigQuery but fails on Redshift (`varchar`). Compiling against the target surfaces it.
- **Package / adapter compatibility.** `dbt deps` + compile surfaces a package or macro the adapter
  does not support.

## Contracts: do not assume a type vocabulary

The example `data_type: string` / `decimal(18,2)` in dbt-best-practices.md is **illustrative
(Databricks/BigQuery-flavored), not portable.** Use the connected adapter's own type names and let the
compile preflight confirm them. Quick orientation only (always confirm by compiling):

| | integer | decimal | string | timestamp |
|---|---|---|---|---|
| Snowflake | `number(38,0)` | `number(18,2)` | `varchar` | `timestamp_ntz` |
| BigQuery | `int64` | `numeric` | `string` | `timestamp` |
| Databricks | `bigint` | `decimal(18,2)` | `string` | `timestamp` |
| Redshift | `bigint` | `numeric(18,2)` | `varchar` | `timestamp` |

Or use dbt's portable type macros in the contract (`{{ dbt.type_int() }}`, `type_string()`,
`type_numeric()`, `type_timestamp()`) so the type resolves per adapter, see the cross-database macros
below.

### Constraints are enforced differently per adapter (use tests, not constraints, for uniqueness)

Contracts also carry column `constraints`, but **enforcement is adapter-specific and mostly weak**
([docs](https://docs.getdbt.com/reference/resource-properties/constraints)):

| Constraint | Snowflake | BigQuery | Databricks | Redshift |
|---|---|---|---|---|
| `not_null` | enforced | enforced | enforced (post-build) | enforced |
| `check` | not definable | not definable | enforced (post-build) | not definable |
| `primary_key` / `foreign_key` | not enforced | not enforced | not enforced | not enforced |
| `unique` | not enforced | not definable | not enforced | not enforced |

- **Do not rely on `primary_key` / `unique` / `foreign_key` constraints for data quality** - they are
  metadata only on every warehouse (Snowflake can use them for query rewrite if you add `rely`).
  Enforce grain and relationships with **dbt tests** (`unique`, `not_null`, `relationships`) instead.
- `check` is enforced only on Databricks; elsewhere express the rule as a dbt test.
- `not_null` / `check` are enforced only **after** the build, so they are not part of the contract
  preflight (which checks names + types). On Databricks a failing-data table still persists (no
  transactional create-or-replace), so pair constraints with tests and a failure alert.

## Macros: prefer adapter-dispatched packages and cross-database macros

Because the target is the customer's connected adapter, prefer **packages** (`dbt_utils` etc., which
`adapter.dispatch` per platform) over hand-rolled macros. If you must write a self-contained macro
(packages_mode = self_contained_macros), keep it adapter-portable and compile it against the target.
See [dbt-packages.md](dbt-packages.md).

In model SQL, prefer dbt's **cross-database macros** (`dbt.*`) over raw warehouse functions - they
dispatch to the right dialect per adapter so the same model compiles everywhere
([docs](https://docs.getdbt.com/reference/dbt-jinja-functions/cross-database-macros)):

- dates/times: `dbt.dateadd`, `dbt.datediff`, `dbt.date_trunc`, `dbt.last_day`, `dbt.current_timestamp`
- strings: `dbt.split_part`, `dbt.concat`, `dbt.replace`, `dbt.position`, `dbt.right`, `dbt.length`, `dbt.hash`, `dbt.listagg`
- types/casts: `dbt.cast`, `dbt.safe_cast`, `dbt.type_string`, `dbt.type_int`, `dbt.type_numeric`, `dbt.type_timestamp`

e.g. `{{ dbt.datediff("start_date", "end_date", "day") }}` instead of a warehouse-specific `datediff`.
These moved from dbt_utils into dbt-core: call `dbt.datediff(...)`, not `dbt_utils.datediff(...)`.

## Per-adapter callouts (from real migrations)

Things the compile gate will catch, but that are worth knowing up front:

**Databricks**
- **Alias the `{{ this }}` subquery in incremental watermark filters.** Without an alias, Databricks
  can incorrectly correlate the subquery with the outer table alias and fail with
  `INVALID_WHERE_CONDITION: aggregate functions in WHERE clause`. Always alias it and default the max:
  ```sql
  {% if is_incremental() %}
  where source_table.commit_timestamp > (
      select coalesce(max(watermark.commit_timestamp), timestamp('1900-01-01'))
      from {{ this }} as watermark
  )
  {% endif %}
  ```
  This should be the standard incremental watermark pattern in any Databricks dbt project.
- `QUALIFY` is available (Spark 3+); `dateadd` / `add_months` work; **`TIMESTAMP` literals need
  `timestamp('...')`** (or `cast(... as timestamp)`), not a bare `'2020-01-01'::timestamp`.
- **`row_number()` tiebreaking is non-deterministic** - always add a deterministic secondary sort key
  in the `order by` (matters for CDC dedup and SCD surrogate keys, see
  [cdc-deduplication.md](cdc-deduplication.md)).

**Redshift**
- `QUALIFY` is historically unsupported - the compile will flag it; rewrite as a subquery with
  `row_number()` filtered in an outer `where`.

**All adapters - incremental strategy** ([docs](https://docs.getdbt.com/docs/build/incremental-strategy))
- `merge` **without a `unique_key` silently behaves like `append`** - it inserts and never updates, so
  a re-run duplicates rows. Always set `unique_key` for merge (it may be composite).
- Use `delete+insert` when `merge` is unsupported or the key is not truly unique; `insert_overwrite`
  only on partitioned tables (replaces whole partitions); `microbatch` needs an `event_time` column
  (Snowflake / Databricks; not BigQuery / Spark).
- Per-warehouse strategy + partition/cluster/dist-key choice:
  [cloud-detection-and-materializations.md](cloud-detection-and-materializations.md).

## Note on the eval

The harbor eval proves the migration's **logic** on DuckDB (free, reproducible). **Warehouse
conformance** is proven at migration time by this compile-against-the-connected-adapter gate, not by
the DuckDB eval. The two are complementary: DuckDB for logic/parity in CI, the connected adapter for
dialect/contract/type conformance on the real target.
