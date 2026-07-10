# Talend component → dbt answer key (Step 3)

The translation table for each Talend component. Lifted from the `REWRITER_SYSTEM` prompt in
`~/talend-to-dbt/src/talend_to_dbt/generation/prompts.py`, which encodes the proven mappings.

## Contents

- [Component mapping table](#component-mapping-table)
- [tMap join types](#tmap-join-types)
- [Talend expression translation](#talend-expression-translation)
- [Structural rules](#structural-rules)

## Component mapping table

| Talend component | dbt translation |
|---|---|
| **tDBInput / tOracleInput / tSnowflakeInput** | `source()` + a `stg_` model; the component `QUERY` seeds the staging select |
| **tMap** (single input, expressions only) | a `select` with the output-column expressions → staging/intermediate |
| **tMap** (input + lookups) | `join`(s) to the lookup models on the join keys, then the output expressions → intermediate |
| **tFilterRow** | a `where` clause |
| **tAggregateRow** | `group by` + aggregate functions (the group-by cols are the grain) |
| **tJoin** | a `join` (map the join type) |
| **tUniqRow** | dedup: `qualify row_number() over (partition by <keys> order by ...) = 1` (or a distinct) |
| **tSortRow** | usually drop (ordering isn't meaningful in a set); keep only if feeding tUniqRow |
| **tReplace / tConvertType** | inline expressions (`replace()`, `cast()`) in the select |
| **tDBOutput** (insert) | `table` (or `incremental` for large) mart model |
| **tDBOutput** (update/upsert on key) | `incremental` model with `unique_key` + `merge` |
| **tRunJob** | a cross-model dependency (`ref()` ordering) — or a Mesh boundary if cross-domain |
| **tContextLoad / context.X** | dbt `var()` / `env_var()` |
| **tFileInput/tFileOutput/tFTP/tSendMail/tJava/tJavaRow** | no warehouse equivalent → residual for human review |

Materialization choice follows the target cloud — see foundations →
cloud-detection-and-materializations.md.

## tMap join types

Two separate settings govern a tMap lookup and both affect row counts — translate them exactly.
The **join model** is the `JOIN_MODEL` elementParameter; the **match model** is `lookupMode` /
`MATCHING_MODE` on the lookup input table.

| Talend setting | value | SQL |
|---|---|---|
| `JOIN_MODEL` | `INNER` / `INNER_JOIN` | `inner join` |
| `JOIN_MODEL` | `LEFT_OUTER` | `left join` |
| match model | `UNIQUE_MATCH` | join + dedup the lookup to one row (`qualify row_number() = 1`) |
| match model | `FIRST_MATCH` | join + keep first per key (deterministic `row_number() = 1` with an order) |
| match model | `ALL_MATCHES` | plain join (may fan out — expected, but note it for parity) |

## Talend expression translation

Talend expression syntax → Fusion-conformant SQL:

| Talend | SQL |
|---|---|
| `row1.column_name` | reference the upstream CTE column `column_name` |
| `StringHandling.CHANGE(s, old, new)` | `replace(s, old, new)` |
| `StringHandling.TRIM(s)` | `trim(s)` |
| `StringHandling.UPCASE(s)` / `DOWNCASE(s)` | `upper(s)` / `lower(s)` |
| `StringHandling.LEFT(s, n)` / `RIGHT(s, n)` | `left(s, n)` / `right(s, n)` |
| `StringHandling.INDEX(s, sub)` | `position(sub in s)` |
| `TalendDate.parseDate("yyyy-MM-dd", s)` | `cast(s as date)` |
| `TalendDate.formatDate("yyyy-MM-dd", d)` | `cast(d as string)` (or platform date-format, kept conformant) |
| `TalendDate.getDate()` / `getCurrentDate()` | `current_date` / `current_timestamp` |
| `TalendDate.diffDate(d1, d2, "dd")` | `datediff(day, d2, d1)` |
| `Numeric.sequence("s1", 1, 1)` | `row_number() over (order by 1)` (or surrogate-key macro) |
| `Relational.NOT(cond)` | `not cond` |
| `row1.col != null` / `== null` | `col is not null` / `col is null` |
| `ISNULL` / null-default | `coalesce(...)` |

Always emit `cast()` (never `::`) and `coalesce()` (never `nvl`/`ifnull`).

## Structural rules

1. Wrap logic in CTEs; name the final CTE `final`; last line `select * from final`.
2. Use `{{ ref('model') }}` for upstream models, `{{ source('schema','table') }}` for raw tables.
3. Strip schema prefixes from column aliases; use snake_case.
4. No `CREATE TABLE`/`VIEW`/`INSERT` — dbt owns materialization.
5. Give CTEs meaningful names (one per logical component: `source`, `filtered`, `joined`,
   `aggregated`, `final`).
