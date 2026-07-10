# Building a Kimball dimensional model (Step 3, architecture = Kimball)

Generate conformed **dimensions** + **fact** tables laid out as star schemas, dbt-native
(`dbt_utils.generate_surrogate_key` + snapshots; add `godatadriven/dbt_date` for a calendar dim —
see [dbt-packages.md](dbt-packages.md)). The legacy→dim/fact mapping is in
[target-architecture.md](target-architecture.md#kimball-dimensional); this reference is the *how*.

## Contents

- [Non-negotiables](#non-negotiables)
- [Dimensions, SCD & surrogate keys](#dimensions-scd--surrogate-keys)
- [Facts](#facts)
- [Layout, materializations & performance](#layout-materializations--performance)
- [Tests, docs & contracts](#tests-docs--contracts)
- [End-to-end example](#end-to-end-example)

## Non-negotiables

1. **Declare the fact grain first** — "one row per _____". It fixes the primary key, the dimensions,
   and which measures are valid. Never mix grains in one fact.
2. **Build dimensions once, conform them.** One `dim_customer`/`dim_date`/`dim_product`, referenced
   by every fact (the bus matrix). In a Mesh, conformed dims live in the producer with
   `contract: enforced` + `access: public`.
3. **Surrogate keys everywhere.** Dimensions get `<entity>_key` via
   `{{ dbt_utils.generate_surrogate_key([...]) }}`; facts carry the dimension **surrogate** key as
   the FK, never the natural key. Keep the natural key on the dim for lineage. Add an unknown/ghost
   member so fact FKs are never null.
4. **History via snapshots** — Type-2 dims come from a dbt snapshot, not hand-rolled valid-from/to.
5. Build bottom-up: sources → `stg_` (view) → `int_` (view/ephemeral) → `dim_`/`fct_` (dim=table,
   fact=incremental). Snapshots in `snapshots/`.

## Dimensions, SCD & surrogate keys

| SCD type | Behavior | Implementation |
|---|---|---|
| Type 1 | overwrite, no history | `table` model; surrogate key from natural key |
| Type 2 | new row per change (valid_from/valid_to/is_current) | dbt **snapshot** → dimension model |
| Type 3 | previous value in an extra column | `previous_<attr>` via `lag()` / self-join |

Type-2 pattern:
```yaml
# snapshots/customer_snapshot.yml
snapshots:
  - name: customer_snapshot
    relation: ref('stg_customers')
    # dbt recommends strategy: timestamp when a reliable updated_at exists; use check otherwise
    config: {unique_key: customer_id, strategy: check, check_cols: [customer_name, segment, region]}
```
```sql
-- models/marts/dim_customer.sql (table)
select
    {{ dbt_utils.generate_surrogate_key(['customer_id', 'dbt_valid_from']) }} as customer_key,
    customer_id, customer_name, segment, region,
    dbt_valid_from as valid_from,
    coalesce(dbt_valid_to, cast('9999-12-31' as timestamp)) as valid_to,
    dbt_valid_to is null as is_current
from {{ ref('customer_snapshot') }}
```
Facts join the correct version with a point-in-time predicate:
`on f.customer_id = d.customer_id and f.event_date >= d.valid_from and f.event_date < d.valid_to`.

**Date dimension:** build one `dim_date` (role-playing, conformed) — prefer
`{{ dbt_date.get_date_dimension('2015-01-01','2035-12-31') }}`, else `dbt_utils.date_spine` / a seed.

## Facts

| Fact type | Grain | Materialization |
|---|---|---|
| Transaction | one row per event | `incremental` (append/merge) |
| Periodic snapshot | one row per entity per period | `incremental` on the period |
| Accumulating snapshot | one row per pipeline instance, updated across milestones | `incremental` merge on the instance key |
| Factless | event/coverage, no measures | `incremental` |

Build a fact: read the event source at the grain → look up each dimension's surrogate key (join on
the natural key + PIT predicate for Type-2 dims) → carry surrogate keys as FKs → keep degenerate
dims (order number) as plain columns → cast measures explicitly. Classify measures additive /
semi-additive (don't sum over time) / non-additive (store numerator+denominator, ratio in BI).

## Layout, materializations & performance

```
models/staging/ stg_*   → view
models/intermediate/ int_* → view/ephemeral
models/marts/ dim_*/fct_* → dim=table, fact=incremental
snapshots/               → source snapshots feeding Type-2 dims
```
Performance: **incremental facts** (never full-rebuild) partitioned+clustered by date + main FK;
dims as clustered tables; keep facts **narrow** (keys + measures + degenerate dims); Type-2 via
snapshots (cheap capture). Per-platform tuning:
[cloud-detection-and-materializations.md](cloud-detection-and-materializations.md).

## Tests, docs & contracts

Via the `arguments:` spec ([dbt-best-practices.md](dbt-best-practices.md)): `unique`+`not_null` on
the dim surrogate key and the fact grain key; `relationships` from **every** fact FK to its dim;
`accepted_values` on low-cardinality columns. Docs state the fact **grain** and each dim's **SCD
type**. `contract: enforced` on published dims/facts; version them.

## End-to-end example

Put it together: the Type-2 `dim_customer` (from a snapshot) shown above, plus an `fct_orders` at
grain "one order line" that generates its own surrogate grain key, looks up `customer_key` with the
point-in-time predicate, keeps the order id as a degenerate dimension, and casts its measures —
materialized `incremental`. See the [facts](#facts) section for the fact build steps.
