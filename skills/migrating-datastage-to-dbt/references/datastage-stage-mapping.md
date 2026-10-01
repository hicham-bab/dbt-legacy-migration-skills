# DataStage stage -> dbt answer key (Step 3)

The translation table for IBM DataStage parallel-job stages. DataStage is an **engine-executed ETL**
tool (the DataStage Parallel Engine runs the stage graph itself, usually reading/writing flat
files/datasets between stages) rather than push-down ELT like Matillion - so unlike Matillion's
near-1:1 component mapping, a DataStage stage graph is **re-expressed as warehouse SQL**, the same
re-authoring job as an Informatica PowerCenter mapping. Grounded in IBM DataStage documentation and
verified parsing of real `.dsx` exports (see ATTRIBUTION.md) - the exact per-stage *configuration*
(join keys, derivations, filter expressions) is read from each stage's `Properties`
(`DSSUBRECORD`s), not invented.

## Contents

- [Transformation stages -> SQL](#transformation-stages--sql)
- [I/O stages -> sources / target tables](#io-stages--sources--target-tables)
- [CDC/SCD -> dbt snapshots](#cdcscd--dbt-snapshots)
- [Debug, passthrough & custom-code stages](#debug-passthrough--custom-code-stages)
- [Job Sequences (orchestration)](#job-sequences-orchestration)
- [Structural rules](#structural-rules)
- [Worked example](#worked-example)

## Transformation stages -> SQL

| Stage (`StageType`) | What it does | dbt / SQL translation |
|---|---|---|
| **Transformer** (`CTransformerStage`) | Row-level derivations, multiple output links each with its own constraint expression | one `select` per output link: derivation expressions as computed columns, the link's constraint as `where` (a reject/second output link becomes a second model or a `qualify`/`case`-flagged split) |
| **Join** (`PxJoin`) | Inner/Left/Right/Full join on key columns, one "left"/primary input + one or more reference inputs | `join ... on` (type per the stage's join-type property) |
| **Lookup** (`PxLookup`) | Like Join but with configurable not-found behavior (fail/drop/reject/continue with default) | `left join` + `coalesce(...)` for the default, or `inner join` if not-found drops the row |
| **Merge** (`PxMerge`) | Combines a master input with one or more update inputs on a key, column-by-column precedence | `coalesce()` across the join of master + update(s) on the key, or `merge`/`update` if this is the final write step |
| **Filter** (`PxFilter`) | Routes rows to different output links by boolean expression(s) | `where` (one model per output-link expression, or a single model with a `case`-derived flag if the splits are later reunited) |
| **Aggregator** (`PxAggregator`) | Group + aggregate functions | `group by` + `sum/avg/count/min/max/...` |
| **Sort** (`PxSort`) | Sorts rows (often a required precursor to Merge/Aggregator/RemoveDuplicates in the engine) | drop - SQL has no row order without an `order by` on the final `select`; sorting-as-a-step is a parallel-engine requirement, not a modeling concern, unless the sort key feeds a window function (see Remove Duplicates) |
| **Remove Duplicates** (`PxRemoveDups`/`PxRemDup`/`PxRemoveDuplicates`) | Drops duplicate rows by key, keeping first/last per the preceding Sort | `qualify row_number() over (partition by <key> order by <tiebreak>) = 1` (Fusion-conformant: avoid a bare `select distinct` if there's a real tiebreak/"keep last" rule - encode it in the `order by`) |
| **Funnel** (`PxFunnel`) | Combines multiple same-schema inputs into one stream | `union all` (or `union` if the stage is configured to dedupe) |
| **Pivot Enterprise** (`PxPivotEnterprise`) | Pivot (columns -> rows) or un-pivot (rows -> columns) | `unpivot`/manual `union all` of `select 'col_name' as attr, col_value` per source column (pivot-to-rows); platform `pivot` or conditional aggregation (rows-to-columns) |
| **Surrogate Key Generator** (`PxSurrogateKeyGenerator`) | Assigns a generated integer key, optionally from a persistent key-state file | `row_number() over (...)` for a fresh load; `{{ dbt_utils.generate_surrogate_key([...]) }}` (hash key) is usually the better dbt-native replacement unless the migrator needs the exact same integer sequence (flag this distinction explicitly - it's a behavior change worth calling out) |
| **Modify** (`PxModify`) | Explicit type/null conversions and column drops, specified as a DSL string | `cast()` / `coalesce()` per the Modify spec's `column_name:type` / `handle_null` directives |
| **Copy** (`PxCopy`) | Pass-through, optionally fans out to multiple links unchanged | drop (just `ref()`/`select *` the upstream directly); multiple output links just mean multiple downstream consumers of the same CTE |

## I/O stages -> sources / target tables

| Stage | Kind | dbt mapping |
|---|---|---|
| **Sequential File** (`PxSequentialFile`), **Dataset** (`PxDataSet`), **File Set** (`PxFileSet`), **Complex Flat File** (`PxComplexFlatFile`) | flat-file I/O | a *source* read -> `{{ source(...) }}` (the landed table that loaded this file); a *target* write -> the mart output, becomes this job's model name |
| **DB connectors** (`CODBCConnectorPX`/`PxODBCConnectorPX`, `PxDB2`, `PxOracleConnectorPX`, `PxTeradataConnectorPX`, `PxNetezza`, ...) | database I/O | reading -> `{{ source(...) }}` or `{{ ref(...) }}` if another job produced the table; writing -> the mart/model this job builds |
| **External Source/Target/Filter** (`PxExternalSource`/`PxExternalTarget`/`PxExternalFilter`) | shells out to an OS command/script | not a warehouse read/write - residual, document as an external dependency |
| **Lookup File Set** (`PxLookupFileSet`) | a pre-built lookup structure, paired with a Lookup stage | the reference table/source the paired Lookup stage joins against |
| **Web Services Client** (`CWebServicesClient`), **FTP** (`CFTPStage`) | external API/file transfer | ingestion-adjacent, out of dbt scope - map the landed result to a `source` |

## CDC/SCD -> dbt snapshots

**Change Capture** (`PxChangeCapture`) compares a "before" and "after" dataset on key columns and
emits a change code column (insert/delete/edit/copy - the DataStage equivalent of Matillion's
Detect Changes Indicator); **Change Apply** (`PxChangeApply`) replays that change stream onto a
target. A native **SCD** stage (where present) bundles Change Capture + Apply + surrogate-key/
effective-dating logic into one configured stage. All three map to a **dbt snapshot**, not a
hand-built model - the snapshot's `check` strategy (or `timestamp` if the source carries a reliable
updated-at column) replaces the Change Capture/Apply pair:

```yaml
snapshots:
  - name: dim_customer_snapshot
    relation: ref('stg_customer')
    config:
      unique_key: customer_id
      strategy: check
      check_cols: [full_name, email, segment]
```

A Transformer-based "flag changes by comparing current vs previous" pattern (no native CDC stage,
just derivation expressions) is the **same SCD2 intent authored by hand** - still migrate it to a
snapshot rather than reproducing the comparison logic as a model; confirm the comparison columns
match what the Transformer's expressions actually compared.

## Debug, passthrough & custom-code stages

- **Peek** (`PxPeek`), **Head/Tail/Sample** (`PxHead`/`PxTail`/`PxSample`), **Row/Column Generator**
  (`PxRowGenerator`/`PxColumnGenerator`), **Wave Generator** (`PxWaveGenerator`) - development/testing
  aids (print sample rows, generate synthetic test data). **Drop these entirely** - they carry no
  production logic. Don't count them in the coverage denominator as migratable, but don't flag them
  as residual either; note their presence in `migration_changes.md` as "test/debug scaffolding,
  dropped."
- **Java Integration** (`JavaStagePX`), **Build Stage** (`CBuildStage`), **Wrapper Stage**
  (`CWrapperStage`), **Parallel Routine** (`CParallelRoutineStage`), **BASIC Transformer**
  (`CBasicTransformerStage`) - custom code (Java/C++/OS command/BASIC). Read the stage's `Properties`
  for what it actually computes: a genuine set-based transform -> re-author as SQL (or a Python
  model as a last resort); anything stateful, imperative, or calling an external system -> residual
  for human review, same treatment as Matillion's Python Script/Bash Script.

## Job Sequences (orchestration)

Mostly **out of dbt scope** - document, don't model:

| Sequence stage | Kind | Where it goes |
|---|---|---|
| **Job Activity** | invokes a parallel job | the dbt DAG/run (that job's stages -> models) |
| **Sequencer** | AND/OR join of upstream activities | dbt run ordering (ref graph already encodes this) |
| **Nested Condition** | if/else branching | a scheduler/job, captured as notes |
| **Exception Handler**, **Terminator** | error handling / abort | platform job retry/alerting config |
| **Notification**, **Email** | send an email on completion/failure | job notification config |
| **Wait For File**, **ExecCommand** | external trigger / OS command | an upstream EL/orchestration dependency, noted |

## Structural rules

1. Wrap logic in CTEs; name the final CTE `final`; last line `select * from final`.
2. Use `{{ ref('model') }}` for a table another job produced, `{{ source('schema','table') }}` for a
   raw loaded table.
3. One CTE per meaningful stage (`PxSequentialFile` source -> `source`, `PxFilter` -> `filtered`,
   `PxJoin` -> `joined`, `PxAggregator` -> `aggregated`), in the stage-graph's DAG order.
4. Fusion-conformant: `cast()` not DataStage's internal type-conversion functions, `coalesce()` for
   Modify/Lookup default handling; no OS-level/DataStage-engine-only operations in model SQL.
5. A Transformer with multiple output links (main + reject, or several filtered splits) usually
   becomes **multiple models** (or a shared upstream CTE referenced by several models) - don't force
   every output link into one model's `where` clauses if they represent genuinely different mart
   outputs.

## Worked example

A job: `Sequential File` (orders_raw) + `Sequential File` (customers_ref) -> `Transformer`
(derive `net_amount`, filter `status = 'active'` on the main link, route rejects to a second link)
-> `Sequential File` (orders_enriched_out) / `Sequential File` (rejected_out):

```sql
with orders as (
    select * from {{ source('raw', 'orders_raw') }}
),
customers as (
    select * from {{ source('raw', 'customers_ref') }}
),
joined as (
    select orders.*, customers.customer_name
    from orders
    left join customers on orders.customer_id = customers.customer_id
),
derived as (
    select *, cast(amount - discount as decimal(18,2)) as net_amount
    from joined
),
final as (
    select * from derived where status = 'active'
)
select * from final
```

The reject link (`status != 'active'`) becomes a second model (`rejected_orders`) built on the same
`derived` CTE with the inverse `where`, or a shared `int_orders_derived` model `ref()`'d by both if
the two outputs live in different marts. Prove parity against the `orders_enriched_out` /
`rejected_out` tables the DataStage job produced (foundations -> data-validation.md).
