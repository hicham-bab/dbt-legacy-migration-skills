# SQL dialect notes for stored-procedure migration (Step 0 + Step 3)

Stored procedures come in several dialects. This reference covers the **procedural** constructs
per dialect (how to recognize and decompose them) and points to the right tool for **expression/
function** dialect translation. Function-level translation detail is sourced from
`an Oracle→Databricks translation answer key` (a full Oracle→Databricks answer key).

## Contents

- [Procedural constructs by dialect](#procedural-constructs-by-dialect)
- [Function translation](#function-translation)
- [Choosing target syntax](#choosing-target-syntax)

## Procedural constructs by dialect

| Dialect | Procedure wrapper | Temp table | Upsert | Branch / loop | Dynamic SQL |
|---|---|---|---|---|---|
| **Snowflake** | `CREATE PROCEDURE ... LANGUAGE SQL` / JS | `CREATE TEMP TABLE` | `MERGE` | `IF/FOR` in SQL scripting | `EXECUTE IMMEDIATE` |
| **BigQuery** | `CREATE PROCEDURE` (scripting) | `CREATE TEMP TABLE` | `MERGE` | `IF/WHILE/LOOP` | `EXECUTE IMMEDIATE` |
| **Databricks** | SQL UDF / notebook / `CREATE PROCEDURE` (recent) | temp view / CTE | Delta `MERGE` | `IF`/loops (limited) | dynamic via widgets/spark |
| **T-SQL (SQL Server)** | `CREATE PROC` | `#temp` / `@table` var | `MERGE` | `IF/WHILE`, cursors | `sp_executesql` / `EXEC()` |
| **Oracle PL/SQL** | `CREATE PROCEDURE ... BEGIN ... END` | GTT / collections | `MERGE` | `IF/LOOP/FOR`, `CURSOR` | `EXECUTE IMMEDIATE` |

For decomposing these into dbt, see `stored-proc-decomposition.md`. The recognition matters at
Step 1 (inventory) so you count every step and spot the residual (cursors carrying state, dynamic
SQL) early.

## Function translation

Translate source-dialect functions to Fusion-conformant, target-cloud SQL. Common Oracle/T-SQL →
standard SQL cases (from the Oracle answer key):

| Source | Fusion-conformant SQL |
|---|---|
| `NVL(x,y)` / `ISNULL(x,y)` | `coalesce(x, y)` |
| `DECODE(x,a,r,d)` | `case when x=a then r else d end` |
| `x::type` (cast shorthand) | `cast(x as type)` |
| `TO_DATE` / `CONVERT` | `cast(... as date)` (or platform date parse, kept conformant) |
| `TRUNC(date)` | `date_trunc('day', ...)` |
| `SYSDATE` / `GETDATE()` | `current_timestamp` |
| `LISTAGG(x, ',')` | `array_join(collect_list(x), ',')` (Databricks) / `listagg`/`string_agg` per platform |
| `ROWNUM <= n` | `limit n` (or `qualify row_number() ... <= n`) |
| optimizer hints (`/*+ ... */`) | drop |
| `CONNECT BY` (hierarchical) | `with recursive ...` — **structural rewrite, confirm with user** |

Mechanical function swaps are safe. Structural rewrites (recursive queries, `KEEP DENSE_RANK`,
`RATIO_TO_REPORT`, window-frame differences) need a human confirm — flag them.

## Choosing target syntax

- Emit SQL for the **target cloud** detected in Step 0, not the source dialect — the migrated dbt
  project runs on the target.
- When the source and target dialects differ substantially, **delegate the dialect translation to
  the `migrating-dbt-project-across-platforms` skill**: it uses dbt Fusion's real-time compiler to
  surface and fix every dialect incompatibility, rather than pre-documenting them. Do the
  procedural decomposition here, then let that skill clean up the dialect on compile.
- Keep model bodies Fusion-conformant (`cast()`, `coalesce()`, standard functions); push platform
  specifics into `config()` (partition/cluster/warehouse/dist keys — see foundations →
  cloud-detection-and-materializations.md).
