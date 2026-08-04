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

## Macros: prefer adapter-dispatched packages when the target is not fixed

Because the target is the customer's connected adapter, prefer **packages** (`dbt_utils` etc., which
`adapter.dispatch` per platform) over hand-rolled macros. If you must write a self-contained macro
(packages_mode = self_contained_macros), keep it adapter-portable and compile it against the target.
See [dbt-packages.md](dbt-packages.md).

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

## Note on the eval

The harbor eval proves the migration's **logic** on DuckDB (free, reproducible). **Warehouse
conformance** is proven at migration time by this compile-against-the-connected-adapter gate, not by
the DuckDB eval. The two are complementary: DuckDB for logic/parity in CI, the connected adapter for
dialect/contract/type conformance on the real target.
