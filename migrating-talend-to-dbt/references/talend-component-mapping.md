# Talend component → dbt answer key (Step 3)

The translation table for each Talend component. Lifted from the `REWRITER_SYSTEM` prompt in
`a proven Talend→dbt translation/prompt set`, which encodes the proven mappings.

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

### Java operators & literals — the common failure point

Talend expressions are **Java**, not SQL. Translating the function names (above) but leaving Java
operators produces **invalid SQL**. The same token can mean different things by context — read it
carefully:

| Talend / Java | SQL | Note |
|---|---|---|
| `a + b` where a/b are **strings** | `a \|\| b` | Java `+` is **string concatenation** → SQL `\|\|` (or `concat`) |
| `a + b` where a/b are **numbers** | `a + b` | numeric `+` stays `+` |
| `"text"` (double quotes) | `'text'` (single quotes) | Java string literal → SQL string literal |
| `cond1 \|\| cond2` (booleans) | `cond1 or cond2` | Java `\|\|` is **logical OR**, *not* concat, in a boolean context |
| `cond1 && cond2` | `cond1 and cond2` | logical AND |
| `!cond` | `not cond` | |
| `row1.status.equals("premium")` | `status = 'premium'` | Java `.equals()` → `=` |
| `!row1.status.equals("x")` | `status <> 'x'` | negated equals |
| `a == b` / `a != b` | `a = b` / `a <> b` | Java equality (for non-strings) |
| `cond ? x : y` (ternary) | `case when cond then x else y end` | |
| `row1.a.compareTo(row1.b) > 0` | `a > b` | |

Worked example (a real `tMap` output): Talend
`StringHandling.TRIM(row1.first_name) + " " + StringHandling.TRIM(row1.last_name)` →
`trim(first_name) || ' ' || trim(last_name)`; Talend `row1.status.equals("premium")` →
`status = 'premium'`; filter `row1.status.equals("active") || row1.status.equals("premium")` →
`where status in ('active', 'premium')`.

## Structural rules

1. Wrap logic in CTEs; name the final CTE `final`; last line `select * from final`.
2. Use `{{ ref('model') }}` for upstream models, `{{ source('schema','table') }}` for raw tables.
3. Strip schema prefixes from column aliases; use snake_case.
4. No `CREATE TABLE`/`VIEW`/`INSERT` — dbt owns materialization.
5. Give CTEs meaningful names (one per logical component: `source`, `filtered`, `joined`,
   `aggregated`, `final`).
6. **Reuse, don't recompute.** If one component's FLOW output feeds **multiple** downstream
   components, build it **once** as an intermediate (`int_`) model and `ref()` it from each — don't
   duplicate the logic. Example: a `tMap` whose output goes to both a `tDBOutput` (a fact) *and* a
   `tAggregateRow` (a summary) → make `int_<entity>` for the tMap result, then `fct_<entity>` and the
   aggregate both `ref('int_<entity>')`.
7. **Trigger edges are not data flow.** A `tDBOutput → tAggregateRow` link with `connectorName`
   `ON_SUBJOB_OK`/`ON_COMPONENT_OK` only means "run after"; the aggregate's *data* comes from its
   `FLOW`/`LOOKUP` input (often the same tMap), not from the fact table. Don't `ref()` the fact as
   the aggregate's source because of a trigger edge.
