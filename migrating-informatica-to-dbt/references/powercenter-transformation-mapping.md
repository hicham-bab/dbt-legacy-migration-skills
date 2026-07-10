# PowerCenter transformation → dbt answer key (Step 3)

The translation table for each PowerCenter transformation type. Grounded in
`~/informatica-retail-legacy/snowflake/04_edw_load_simulation.sql`, where each mapping is
replicated in SQL (tagged with its `[m_...]` name) — treat that file as the worked answer key.

## Contents

- [Transformation mapping table](#transformation-mapping-table)
- [SCD2 → dbt snapshots](#scd2--dbt-snapshots)
- [Expression function translation](#expression-function-translation)
- [Worked example](#worked-example)

## Transformation mapping table

| PowerCenter transformation | dbt translation |
|---|---|
| **Source definition** (`TYPE="SOURCE"`) | dbt `source()` in `_sources.yml` |
| **Source Qualifier** (SQ_) | the `select ... from {{ source(...) }}` at the top of the staging CTE; its SQL override (if any) becomes the staging query |
| **Expression** (EXP_) | column expressions in a `select` — port `out_X = expr` becomes `expr as x` |
| **Filter** (FIL_) | a `where` clause |
| **Router** (RTR_) | either `case` output columns, or split into multiple models (one per output group) — split when groups feed different targets |
| **Joiner** (JNR_) | a `join` (map join type: Normal→`inner`, Master/Detail Outer→`left`/`right`, Full→`full outer`) |
| **Lookup — connected** (LKP_) | a `left join` to the looked-up model/source on the lookup condition |
| **Lookup — unconnected** (`:LKP` call) | a scalar subquery, or a join if called row-wise; inspect the call site |
| **Aggregator** (AGG_) | `group by` + aggregate functions; the group-by ports are the grain |
| **Sorter** (SRT_) | usually drop (ordering is not meaningful in a set); keep only if feeding a dedup |
| **Update Strategy** (UPD_) — insert/update by key | `incremental` model with `unique_key` + `merge`; **if it preserves history → snapshot** |
| **Update Strategy** — full reload | `table` materialization |
| **Sequence Generator** (SEQ_) | surrogate key: `{{ dbt_utils.generate_surrogate_key([...]) }}` or a hash; not a stateful counter |
| **Aggregator + Expression building a fact** | the `fct_` mart model |
| **Mapplet** (mplt_) | a macro or an intermediate (`int_`) model, referenced by each caller |
| **Worklet** (wklt_) | a folder/group of models in the DAG; orchestration handled by the dbt run + scheduler |
| **Target** (`TYPE="TARGET"`) | the materialized model (or snapshot) |

Materialization choice per target follows the target cloud — see foundations →
cloud-detection-and-materializations.md.

## SCD2 → dbt snapshots

The canonical PowerCenter SCD2 pattern — Lookup current row → Expression detects NEW/CHANGED/
UNCHANGED → Router → Update Strategy (insert new, expire old) → Sequence surrogate key — migrates
to a **dbt snapshot**, not a model. Do not reproduce effective/expiry columns by hand:

```yaml
snapshots:
  - name: dim_customer_snapshot
    relation: ref('stg_customer')
    config:
      unique_key: customer_id
      strategy: check
      check_cols: [full_name, email, loyalty_tier, address]
```

The snapshot manages `dbt_valid_from` / `dbt_valid_to` / current-row. SCD1 dims (overwrite) are
just a `table` model. Confirm the natural key and the tracked columns from the mapping's Lookup
condition and Expression change-detection ports.

## Expression function translation

PowerCenter expression language → Fusion-conformant SQL:

| PowerCenter | SQL |
|---|---|
| `DECODE(x, a, r1, b, r2, d)` | `case when x=a then r1 when x=b then r2 else d end` |
| `IIF(cond, t, f)` | `case when cond then t else f end` |
| `NVL(x, y)` / `ISNULL` | `coalesce(x, y)` |
| `LTRIM(x)` / `RTRIM(x)` / `LTRIM(RTRIM(x))` | `ltrim(x)` / `rtrim(x)` / `trim(x)` |
| `INITCAP(x)` | `initcap(x)` |
| `UPPER`/`LOWER`/`SUBSTR`/`LENGTH`/`INSTR` | same, standard SQL (`position()` for INSTR) |
| `TO_DATE(str, fmt)` | `cast(str as date)` (or platform date parse if fmt is non-ISO — keep conformant) |
| `TO_CHAR(date, fmt)` | `cast(... as string)` / platform format function |
| `TRUNC(date)` / `TRUNC(num)` | `date_trunc(...)` / `floor()`/`trunc()` |
| `DATE_DIFF(d1, d2, 'DD')` | `datediff('day', d2, d1)` (mind the argument order — PowerCenter is `(later, earlier, fmt)`) |
| `SYSDATE` | `current_date` |
| `SESSSTARTTIME` / `SYSTIMESTAMP` | `current_timestamp` |
| `ADD_TO_DATE` / date math | `dateadd`/interval math (standard SQL) |
| `\|\|` concat | `\|\|` or `concat()` |
| `IN (...)` / `NOT` | same |

**Preserve the exact expression** — do not simplify. e.g. an age derived as
`FLOOR(DATE_DIFF(SYSDATE, DATE_OF_BIRTH, 'DD') / 365.25)` must become
`floor(datediff('day', date_of_birth, current_date) / 365.25)`, **not** `datediff('year', ...)`
(which counts calendar-year boundaries and breaks parity).

Always emit `cast()` (never `::`) and `coalesce()` (never `nvl`).

## Worked example

`m_STG_CUSTOMER` in the fixture: Source Qualifier `SQ_CUSTOMERS` reads `RETAIL_SRC.CUSTOMERS`;
`EXP_CLEANSE` builds `out_FULL_NAME`, `out_EMAIL`, `out_LOYALTY_TIER`, `out_AGE_YEARS`, `out_LOAD_TS`.
The verified `TRANSFORMFIELD EXPRESSION` values are:
`INITCAP(LTRIM(RTRIM(FIRST_NAME))) || ' ' || INITCAP(LTRIM(RTRIM(LAST_NAME)))`,
`LOWER(LTRIM(RTRIM(in_EMAIL)))`, `UPPER(LTRIM(RTRIM(in_LOYALTY_TIER)))`,
`FLOOR(DATE_DIFF(SYSDATE, DATE_OF_BIRTH, 'DD') / 365.25)`, `SESSSTARTTIME`. Faithful translation:

```sql
with source as (
    select * from {{ source('retail_src', 'customers') }}
),
cleansed as (
    select
        customer_id,
        initcap(trim(first_name)) || ' ' || initcap(trim(last_name))  as full_name,
        lower(trim(email))                                            as email,
        upper(trim(loyalty_tier))                                     as loyalty_tier,
        floor(datediff('day', date_of_birth, current_date) / 365.25)  as age_years,
        current_timestamp                                             as load_ts
    from source
),
final as (select * from cleansed)
select * from final
```

This matches the `[m_STG_CUSTOMER]` block in `04_edw_load_simulation.sql` (which uses the same
`INITCAP(TRIM(...))`, `LOWER(TRIM(...))`, and `FLOOR(DATEDIFF('day', ...)/365.25)` logic).
**Cross-check every generated model against its corresponding `[m_...]` block** in that file — it
is the parity answer key.
