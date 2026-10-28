# SnapLogic Snap → dbt answer key (Step 3)

The translation table for SnapLogic Snaps. Unlike Matillion — where every transformation component
is push-down SQL — SnapLogic has **three execution regimes**, and only the two that already run in
the warehouse translate cleanly. Grounded in SnapLogic Snap documentation and real `.slp` exports.

## Contents

- [Translate target-table-first, not Snap-first](#translate-target-table-first-not-snap-first)
- [The MERGE/UPDATE chain — the headline pattern](#the-mergeupdate-chain--the-headline-pattern)
- [One snap → several models](#one-snap--several-models)
- [ELT Snap Pack → dbt](#elt-snap-pack--dbt)
- [`<DB> Execute` Snaps → dbt](#db-execute-snaps--dbt)
- [Standard Snaps → dbt](#standard-snaps--dbt)
- [Flow & control Snaps](#flow--control-snaps)
- [SCD2 → dbt snapshots](#scd2--dbt-snapshots)
- [Expressions, parameters & variables](#expressions-parameters--variables)
- [Structural rules](#structural-rules)
- [Worked example](#worked-example)

## Translate target-table-first, not Snap-first

A Matillion transformation pipeline is one dataflow ending in one write, so component → CTE is
1:1. **A SnapLogic pipeline is not.** It is usually a *script* of independent warehouse statements
sequenced by the canvas, several of which hit the same table.

So: group the inventory by **write target**, and translate one target at a time. For each target,
the ordered list of Snaps writing it is the model's CTE chain. Snaps that only `SELECT` (row-count
checks, freshness gates) are usually tests or `dbt source freshness`, not models.

## The MERGE/UPDATE chain — the headline pattern

The dominant real-world SnapLogic shape: a sequence of `MERGE INTO <same target>` Snaps each
enrich a few columns of one table.

```
Load Cust Sum temp     CTAS  -> core.us_customer_summary_tmp   (a staging input)
Load Cust Summary      MERGE -> core.us_customer_summary       [inserts_rows]
Upd Order Type         MERGE -> core.us_customer_summary       [self_referencing]
Upd Customer Type      MERGE -> core.us_customer_summary       [self_referencing]
Updt item count        MERGE -> core.us_customer_summary
… a dozen-plus live snaps, more write statements than snaps, one target
```

**This is ONE dbt model, not fourteen.** But before collapsing, read three things off the
inventory, because they decide what kind of model it is:

**1. Is the target rebuilt, or does it accumulate?** Look for `WHEN NOT MATCHED THEN INSERT`
(the script flags it as `inserts_rows`). If any statement in the chain has it, the table
**accumulates rows across runs** — it is an **incremental** model, not a `table`. Only if every
statement is `WHEN MATCHED THEN UPDATE` *and* some upstream step fully rebuilds the table can you
materialize it as `table`.

**2. Does any statement read its own target?** When the `USING` subquery selects from the target
table (flagged `self_referencing`), it is a **read-modify-write over existing history**. You
cannot express that as a CTE over freshly-built data — that silently rebases the calculation onto
the current increment and changes results. It needs `{{ this }}`:

```sql
{{ config(materialized='incremental', unique_key=['customer_id','event_date'],
          incremental_strategy='merge') }}

with existing as (
    {% if is_incremental() %}
    select * from {{ this }}          -- the "USING (select … from <target>)" subquery
    {% else %}
    select * from {{ ref('int_customer_summary_tmp') }} where false
    {% endif %}
),
…
```

**3. What is the grain, and does the chain change it?** A `NOT MATCHED … INSERT` adds rows; model
that as a `union`/`full outer join`, not a `left join`, or the row count will not match.

**4. Is each merge key at-or-finer-than the target grain?** The `left join` recipe below is only
safe for equality merges at target grain. Real chains are not uniform — within one chain you will
see a MERGE joining on a bare id, another on a normalised expression such as `UPPER(trim(col))`,
and another on a **range** predicate (`a.event_date >= b.min_date`). A join on a coarser key or a
range predicate **fans out
rows**. Dedupe the subquery to the target grain (`qualify row_number() = 1` over the *target's*
key, not the subquery's) before joining, and check the row count after. Likewise, a
`WHEN MATCHED AND <predicate on the target>` clause (e.g. `AND ps.account_type is null`, or
`AND event_date >= date_sub(...)`) is **not** the same as `coalesce()` — translate a null-guard
to `coalesce()`, but a target-predicate to `case when <predicate> then new else old end`.

Once those are settled, each MERGE's `USING (...)` subquery becomes a CTE and its
`WHEN MATCHED THEN UPDATE SET col = s.col` becomes a column sourced by a `left join` on the merge
keys, wrapped in `coalesce()` to preserve "only overwrite when matched":

```sql
with base as (
    select * from {{ ref('int_customer_summary_tmp') }}
),
sale_type as (                              -- "Upd Order Type" USING (...) subquery
    select tx_id, order_type_flag, product_sku
    from {{ ref('stg_product_sales') }}
),
final as (
    select
        base.*,
        coalesce(sale_type.order_type_flag, 'UNKNOWN') as order_type_flag
    from base
    left join sale_type on base.tx_id = sale_type.tx_id
)
select * from final
```

**Rules for collapsing a chain:**
1. **Drop disabled snaps from the chain first.** A chain member with `execution_mode: "Disabled"`
   never ran in production. Folding it into the collapsed model applies an enrichment the legacy
   job never applied — the build succeeds, the tests pass, and the output quietly diverges.
2. **Order matters, and the order lives in two edge sets.** Follow the DAG, not `snap_map` order
   (JSON maps are unordered) — and use **both** the data edges *and* the `isGoto` edges, which
   carry part of the chain sequence. A later MERGE may overwrite a column an earlier one set:
   last write wins, so it goes last in the `coalesce()`/`case` precedence. **If several statements
   write the same column** — audit and metadata columns are the usual offenders, set to a
   different value by each snap in the chain — the order is not cosmetic: resolve it explicitly or
   the column's value is undefined.
3. **Keep a seeding/staging CTAS as its own `int_` model** when several MERGE subqueries read it —
   inlining it as an ephemeral CTE would duplicate that scan once per use.
4. **One snap may contribute more than one statement.** A snap holding two MERGEs contributes two
   enrichments, not one. Count statements, not snaps.
5. **Split only for a real reason** (reuse by another model, or a genuinely different grain).
   "It was a separate Snap" is not a reason.
6. **Parity (Step 5) is mandatory here.** Collapsing is the highest-risk transformation in the
   whole migration; the diff against the legacy table is the only proof it held.

## One snap → several models

The inverse case. A single Execute snap can hold several `;`-separated statements writing
different tables — a single snap holding **6 write statements across 2 targets** is not unusual
(a `_tmp` build, then MERGEs and UPDATEs into the final table). Split it by write target: each
target becomes its own model, and statements writing the same target collapse per the rules above.
Never let the snap boundary decide the model boundary.

## ELT Snap Pack → dbt

ELT Snaps (`com-snaplogic-snaps-elt-*`) build one optimized SQL query and process no data
themselves — the direct analogue of Matillion's push-down components, and the cleanest mapping.

| Snap | dbt / SQL translation |
|---|---|
| **ELT Select** | the `select` / source CTE — `{{ source() }}` or `{{ ref() }}` |
| **ELT Transform** | scalar expressions in a `select` |
| **ELT Filter** | `where` |
| **ELT Aggregate** | `group by` + aggregate functions |
| **ELT Join** | `join` (type per config) |
| **ELT Union** / **ELT Intersect** / **ELT Minus** | `union [all]` / `intersect` / `except` |
| **ELT Sort** | `order by` (usually droppable — order is a presentation concern) |
| **ELT Limit** / **ELT Sample** | `limit` / `tablesample` — often a dev-only guard; confirm |
| **ELT Pivot** | `pivot` / conditional aggregation |
| **ELT Router** | one model per branch, or a `case`; see the Router note below |
| **ELT Case Expression** / **Conditional Function** | `case when …` |
| **ELT Cast Function** | `cast(col as <type>)` |
| **ELT Coalesce** | `coalesce(...)` |
| **ELT Math / String Function** | the equivalent SQL function |
| **ELT Create View** | a `view`-materialized model |
| **ELT Insert-Select** | `incremental` model (append) |
| **ELT Merge Into** | `incremental` model, `incremental_strategy: merge`, `unique_key` = merge keys |
| **ELT SCD2** | **snapshot** — see below |
| **ELT Load** | EL ingestion (stage/cloud storage → table) → **out of scope**, map to `sources` |
| **ELT Execute** | arbitrary SQL — treat as a `<DB> Execute` Snap (next section) |
| **ELT Copy** | fan-out — vanishes; both downstream models `ref()` the same upstream |

## `<DB> Execute` Snaps → dbt

BigQuery Execute, Snowflake Execute, Redshift Execute, MySQL Execute, JDBC Execute, … all hold raw
warehouse SQL (`settings.Query` or `settings.sqlStatement`). Translate by the statement's **verb**:

| SQL verb | What it means | dbt translation |
|---|---|---|
| `CREATE OR REPLACE TABLE x AS SELECT …` | full rebuild (CTAS) | a `table` model named for `x` |
| `CREATE OR REPLACE VIEW x AS …` | view | a `view` model |
| `CREATE … TABLE x_tmp AS …` (`_tmp`, `_stg`, `_temp`) | scratch staging | an `int_` model, or an ephemeral CTE — **not** a mart |
| `MERGE INTO x USING (…)` | upsert **or** enrichment | if it is one of several writing `x` → collapse (above). If it stands alone → `incremental` with `incremental_strategy: merge` |
| `INSERT INTO x SELECT …` | append | `incremental` model (append) |
| `UPDATE x SET …` | in-place enrichment | a CTE/join inside `x`'s model — never its own model |
| `DELETE FROM x WHERE …` / `TRUNCATE` | housekeeping | dbt owns the rebuild — usually drop; if it is a real business rule (purging), make it a `where` |
| `DROP` / `ALTER` / `GRANT` | DDL | dbt owns DDL — drop, or move grants to `config(grants=…)` |
| `CALL some_proc(…)` | logic hidden in the warehouse | **fetch the procedure body**; hand off to `migrating-stored-procedures-to-dbt`. Do not guess |
| bare `SELECT count(*) …` | a check/gate feeding a Router or notification | a dbt **test** (or `dbt source freshness`), not a model |
| *any verb, but* `execution_mode: "Disabled"` | dead code — never runs | **nothing.** Do not migrate, do not count |
| `CREATE … TABLE x_bkp AS SELECT * FROM x` | pre-run backup | operational safety net — dbt's rebuild semantics replace it; document and drop |

**Always unwrap `expression: true` SQL first** (see the parsing reference) and strip
`#standardSQL` hints and comments. Then translate the dialect. "Fusion-conformant" is not
"no platform syntax" — it means portable ANSI where a portable form exists, and
`config()`/`{{ target }}` for genuine platform tuning. Concretely, for the BigQuery SQL these
exports are full of:

| Source form | Do this |
|---|---|
| `` `proj.dataset.table` `` backticks | drop them; use `source()`/`ref()` |
| `IFNULL(a, b)`, `NVL(a, b)` | `coalesce(a, b)` |
| `IF(cond, a, b)` | `case when cond then a else b end` |
| `a :: int` | `cast(a as int)` |
| `CURRENT_DATE('America/Los_Angeles')` | keep the timezone, but make it explicit and consistent — a bare `current_date` silently changes the business day |
| `DATE_ADD(x, INTERVAL -1 MONTH)`, `DATE_SUB`, `DATE_TRUNC(x, MONTH)` | `dbt_utils.dateadd` / `dateadd()` / `date_trunc('month', x)` per target |
| `QUALIFY row_number() over (...) = 1` | **keep it** on Snowflake/BigQuery/Databricks; rewrite as a subquery + `where rn = 1` only if the target lacks `QUALIFY` (Redshift) |
| `SAFE_CAST`, `SAFE_DIVIDE` | `try_cast` / `nullif`-guarded division per target |

When in doubt, compile it: Fusion tells you immediately whether the target accepts the form.

## Standard Snaps → dbt

These run **row-by-row in the Snaplex**, not in the warehouse. Translate them **only when the
surrounding flow is warehouse-to-warehouse** — i.e. the data came out of a warehouse Snap and goes
back into one. Then they are just set-based SQL that was being done the slow way, and migrating
them is a genuine win. If the flow touches files, APIs, queues or email, the Snap is integration
work: it stays in SnapLogic (or moves to a loader) and is **out of scope**.

| Snap (`class_id` tail) | What it does | dbt translation (warehouse-to-warehouse flows only) |
|---|---|---|
| **Mapper** (`transform-datatransform`) | maps/derives fields via expression language | scalar expressions in a `select`; `passThrough: false` means *only* the mapped fields survive — mirror that by selecting explicitly |
| **Join** (`transform-join`) | joins two streams | `join` per `joinType` |
| **Multijoin** (`transform-multijoin`) | joins N streams | chained `join`s — **unless it joins on a literal**, which is a wait barrier (drop it) |
| **Aggregate** (`transform-aggregate`) | aggregate + group by | `group by` |
| **Group By Fields / Group By N** | nests documents into arrays | usually a reshaping artifact for a downstream writer — re-model set-based or drop |
| **Sort** (`transform-sort`) | orders the stream | `order by`, usually droppable |
| **Unique** (`transform-unique`) | dedupe | `select distinct` or `qualify row_number() = 1` |
| **Pivot** (`transform-pivot`) | rows → columns | `pivot` / conditional aggregation |
| **In-Memory Lookup** | lookup table join | `left join` to a `ref()`/seed |
| **Diff** (`transform-diff`) | compares two streams | a `full outer join` comparison — and if it feeds an SCD2 write, a **snapshot** |
| **Sequence** / **Constant** | generates values | a literal column, or `dbt_utils.generate_surrogate_key` for keys |
| **Union** (`flow-union`) | merges streams | `union all` |
| **Filter** (`flow-filter`) | keeps matching documents | `where` — *if* it filters data, not job status |
| **Router** (`flow-router`) | routes to N outputs by expression | one model per branch, or a `case` column. `firstMatch: true` means the branches are ordered and mutually exclusive — reproduce with `case when … then … else`, not independent `where`s |
| **Data Validator** | constraint checks | dbt **tests**, not a model |
| **JSON/XML/CSV Parser & Formatter** | serialisation | EL concern — out of scope |

**The `nullSafeAccess` / `passThrough` settings change semantics.** `passThrough: true` means
unmapped input fields flow through — your `select` must be `source.*` plus the mapped columns.
`passThrough: false` means the output is *only* the mapped fields.

## Flow & control Snaps

Out of dbt scope — document, don't model:

| Snap | Kind | Where it goes |
|---|---|---|
| `flow-copy` (**Copy**) | fan-out | vanishes — both downstream models `ref()` the same upstream |
| `flow-tail` / `flow-gate` (as "Wait") | synchronization barrier | dbt's DAG handles ordering — drop |
| Join/Multijoin **on a literal** | synchronization barrier | drop |
| `flow-pipeexec` (**Pipeline Execute**) | invokes a child pipeline | the dbt DAG. Recurse into project-local children; shared `gbl_Start_Job_*` / `gbl_End_Job_*` / `gbl_Error_Handling` are a job-logging framework → document once, drop |
| `flow-foreach` (**ForEach**) | one child run per document | runtime looping with no dbt equivalent — re-model set-based, or residual. **Do not unroll into N copies** |
| `flow-taskexecute` (**Task Execute**) | invokes a triggered Task | a platform job dependency — notes |
| `flow-exit` (**Exit**) | fails the pipeline past a threshold | a dbt test with `severity: error` |
| `flow-head` (**Head**) | first N documents | usually a dev guard — confirm, then drop |
| `email-emailsender` | notification | platform job notification config |
| `script-script` (**Script**) | arbitrary JavaScript/Python | a dbt Python model **only** if it is a genuine set-based transform; otherwise residual. In practice these are usually "Null Output" stubs feeding a barrier — drop |
| MySQL/JDBC Execute against a **job-history table** | run logging | the platform's own run metadata replaces it — drop |

## SCD2 → dbt snapshots

Two forms, one destination:

1. **ELT SCD2 Snap** — configured with natural keys, tracked columns, and start/end-date columns.
2. **A hand-built SCD2 MERGE** in a `<DB> Execute` Snap — expires the current row
   (`WHEN MATCHED … SET end_date = …, current_flag = 'N'`) and inserts a new version.

Both become a dbt **snapshot**, not a hand-written model:

```yaml
snapshots:
  - name: dim_customer_snapshot
    relation: ref('stg_customer')
    config:
      unique_key: customer_id
      strategy: check
      check_cols: [full_name, email, segment]
```

The snapshot manages `dbt_valid_from`/`dbt_valid_to`/current-row. Map the Snap's natural key →
`unique_key` and its tracked columns → `check_cols` (or use `strategy: timestamp` with
`updated_at` if the source carries a reliable modification timestamp). An SCD1 (overwrite)
dimension is just a `table` model.

## Expressions, parameters & variables

| SnapLogic | dbt |
|---|---|
| Pipeline parameter `_env`, `_org_name` (`param_table`) | `{{ var('env') }}` or `{{ env_var('…') }}` |
| Document field `$field` in a Mapper | a column reference / expression |
| `lib.BigQuery.ProdEnv1.ProjectID` (from an `.expr` import) | the resolved database/project name — **ask the migrator for the `.expr` file**; do not guess |
| `eval('lib.BigQuery.' + _env + '.SaAccount')` | environment indirection → dbt targets/profiles |
| `Date.now().toLocaleDateString({...})` | `current_date` / `current_timestamp` |
| `Date.parse($x).toLocaleDateString({format:'yyyy-MM-dd'})` | `cast(x as date)` / `to_date(x, 'YYYY-MM-DD')` |
| `$a == null ? b : $a` | `coalesce(a, b)` |
| `.toUpperCase()`, `.trim()`, `.replace()` | `upper()`, `trim()`, `replace()` |
| `snap.in.totalCount`, `$original`, `$error` | runtime/plumbing — no equivalent, drop |
| a `$field` **spliced into SQL as a literal**, e.g. `"… >= CAST(SUBSTR('" + $min_updated_at + "',1,10) AS DATE)"` | a **run watermark**, not a column. It is neither a `_param` nor a column reference: it is computed upstream (a Mapper) and injected per run. This is usually the whole reason a CTAS is incremental — translate it to `{% if is_incremental() %} where updated_at > (select max(updated_at) from {{ this }}) {% endif %}`, or to a `var()` if the migrator wants to keep passing it in |

Environment indirection (`_bigq_env` selecting between `ProdEnv1` / `ProdEnv2`) is
SnapLogic doing what dbt **targets** do. Map it to profile targets rather than to `var()` branching
inside model SQL.

## Structural rules

1. Wrap logic in CTEs; name the final CTE `final`; last line `select * from final`.
2. Use `{{ ref('model') }}` for tables another pipeline produced, `{{ source('schema','table') }}`
   for raw loaded tables.
3. One CTE per meaningful Snap or per merged-in enrichment, in DAG order — not `snap_map` order.
4. Derive the model name from the **write target table**, not the Snap label — Snap labels like
   `"BQExec - stg curr"` are canvas notes, not object names. Then **apply the layer prefix your
   architecture requires** (`stg_` / `int_` / `dim_` / `fct_`): `bi_staging.sales_temp_curr` →
   `int_daily_sales_current`. Step 7 runs `dbt_project_evaluator`, which enforces those
   prefixes, so a bare target-table name will fail the gate the skill mandates.
5. Fusion-conformant: `cast()` not `::`, `coalesce()` not `nvl`/`ifnull`; no `#standardSQL` hints;
   no DDL in models.
6. **Resolve every table reference, and know which kind you have.** The same SQL mixes two forms:
   - **Fully-qualified** (`` `g5-prod-1.ebs_did.SOME_TABLE` ``) — becomes a `source()` entry with a
     known database/project. Never hard-code the project/dataset in model SQL.
   - **Bare two-part** (`core.us_order_headers`, `dimensions.d_product`) — the project/database
     is **implicit**, resolved at runtime from the Snap account and the external `.expr` library
     (`eval('lib.BigQuery.' + _env + '.ProjectID')`). **You cannot determine it from the export.**
     Do not assume the default project. Create the `source()` **provisionally**, leave the
     `database:` unresolved with a comment, list it under "Unresolved dependencies", and ask the
     migrator for the `.expr` file or the account config. Getting this wrong points a model at the
     wrong environment while still compiling cleanly.

## Worked example

A pipeline: `BQExec - stg curr` (CTAS into `bi_staging.sales_temp_curr`, reading a fully-qualified
prod table with a 3-month window) → `BQExec - stg hist` (CTAS, history) → `BQ SP - Load Sales`
(`CALL`) → `BQExec - rowcount` (`SELECT count(*)`) → `BQExec - snapshot bkp` (CTAS `_bkp`).

Translation:

```sql
-- models/intermediate/int_daily_sales_current.sql
-- Why a table: rebuilt in full each run from a rolling 3-month window; small enough to recompute.
{{ config(materialized='table') }}

with source as (
    select * from {{ source('erp_ext', 'erp_sales_order_detail_v') }}
),
windowed as (
    select
        order_type,
        booked_date,
        sales_order,
        -- … the explicit column list from the CTAS …
        current_date as loaded_at
    from source
    where gl_date >= date_trunc(date_add(current_date, interval -3 month), month)
),
final as (select * from windowed)
select * from final
```

- The `_tmp`/`_curr` CTAS becomes an **`int_` model** — it is scratch, not a mart.
- `CALL load_sales()` → **fetch the procedure body**; it holds the real load logic. Hand off to
  `migrating-stored-procedures-to-dbt`, don't guess at it.
- `SELECT count(*)` row-count check → a `dbt_utils.expression_is_true` or row-count test, not a
  model.
- The `_bkp` CTAS → operational backup; dbt's rebuild replaces it. Document and drop.

Prove parity for the resulting mart against the table SnapLogic produced (foundations →
data-validation.md).
