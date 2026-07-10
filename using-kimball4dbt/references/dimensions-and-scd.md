# Dimensions, SCD, surrogate keys & conformed dimensions

How to build dimensions in dbt: surrogate keys, the three SCD types, snapshots for history,
conformed dimensions / bus matrix, and the date dimension.

## Contents

- [Surrogate keys](#surrogate-keys)
- [SCD types](#scd-types)
- [SCD Type 2 via dbt snapshots](#scd-type-2-via-dbt-snapshots)
- [Conformed dimensions & the bus matrix](#conformed-dimensions--the-bus-matrix)
- [The date dimension](#the-date-dimension)

## Surrogate keys

Every dimension gets a **surrogate key** — a single synthetic key independent of the source's
natural key. Use `dbt_utils`:

```sql
{{ dbt_utils.generate_surrogate_key(['customer_id']) }} as customer_key            -- Type 1
{{ dbt_utils.generate_surrogate_key(['customer_id', 'valid_from']) }} as customer_key  -- Type 2 (one key per version)
```

Rules:
- The dimension keeps **both** the surrogate key (`<entity>_key`) and the natural/business key
  (`<entity>_id`) — the natural key for lineage/joins-to-source, the surrogate for the fact FK.
- Facts carry the **surrogate** key as the FK, never the natural key.
- Add an **unknown/ghost member** (surrogate key for a sentinel row) so fact FKs are never null —
  late-arriving or unmatched facts point at the unknown member.
- `generate_surrogate_key` hashes consistently across platforms — keep the column order stable, or
  the key changes.

## SCD types

| Type | Behavior | dbt implementation |
|------|----------|--------------------|
| **Type 1** | Overwrite — no history | `table` model; surrogate key from the natural key |
| **Type 2** | New row per change — full history with valid-from/to + current flag | dbt **snapshot** → dimension model (below) |
| **Type 3** | Keep previous value in an extra column (limited history) | a `previous_<attr>` column via `lag()` or a self-join |

Pick per attribute/dimension based on whether the business needs history. Legacy SCD2 (Informatica
Update Strategy, Matillion Detect Changes, a proc's merge-with-history) → Type 2 here.

## SCD Type 2 via dbt snapshots

Do **not** hand-roll valid-from/valid-to with window functions. Snapshot the source, then build the
dimension from the snapshot:

```yaml
# snapshots/customer_snapshot.yml
snapshots:
  - name: customer_snapshot
    relation: ref('stg_customers')
    config:
      unique_key: customer_id
      strategy: check            # or timestamp, if the source has a reliable updated_at
      check_cols: [customer_name, segment, region]
```

```sql
-- models/marts/dim_customer.sql (table)
select
    {{ dbt_utils.generate_surrogate_key(['customer_id', 'dbt_valid_from']) }} as customer_key,
    customer_id,
    customer_name, segment, region,
    dbt_valid_from as valid_from,
    coalesce(dbt_valid_to, cast('9999-12-31' as timestamp)) as valid_to,
    dbt_valid_to is null as is_current
from {{ ref('customer_snapshot') }}
```

Facts join to the correct version with a **point-in-time** predicate:
`on f.customer_id = d.customer_id and f.event_date >= d.valid_from and f.event_date < d.valid_to`.
`strategy: check` compares `check_cols`; `strategy: timestamp` uses an `updated_at` column (cheaper,
needs a trustworthy timestamp).

## Conformed dimensions & the bus matrix

A **conformed dimension** is one dimension used consistently by many facts/business processes. Build
it **once** and `ref()` it everywhere — this is the Kimball **bus matrix** (rows = business
processes/facts, columns = shared dimensions).

- Inventory the mapped facts and the dimensions each needs; where the same entity recurs (customer,
  product, date), build a single shared `dim_`.
- In a dbt **Mesh**, put conformed dimensions in the **producer** project with `access: public` and
  `contract: enforced`; consumer domains reference them cross-project. This guarantees every process
  slices by the same customer/product/date definitions.
- Never fork a conformed dimension per mart — that reintroduces the inconsistent-reporting problem
  dimensional modeling exists to solve.

## The date dimension

Build one `dim_date` (a role-playing, conformed dimension) with a stable integer/`YYYYMMDD`
surrogate key and the calendar attributes the business filters by (year, quarter, month, week,
day-of-week, fiscal periods, holiday flags). Generate it with a date spine
(`dbt_utils.date_spine`) or a seed. Every date FK on every fact references it
(`order_date_key`, `ship_date_key`, …).
