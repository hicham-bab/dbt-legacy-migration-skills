# History capture and SCD: snapshot vs incremental vs hybrid

Preserving history is a **cross-cutting** concern, not a Kimball detail. It shows up as Type-2
dimensions (Kimball / star), satellites (Data Vault), and any "keep prior versions" requirement in a
layered build. This note is the shared decision framework; the modeling references (building-kimball,
building-starschema, building-datavault) link here instead of each restating it.

The question is always: **where does history physically live, and how is it loaded?** There are four
shapes. Pick by scoring compute, lineage, and debugging, not by habit.

## The options

1. **dbt snapshot** (managed SCD2). dbt owns `dbt_valid_from` / `dbt_valid_to` / current-row logic.
   `timestamp` strategy when a reliable `updated_at` exists (cheap, incremental by that column);
   `check` strategy otherwise (compares tracked columns).
2. **Incremental SCD2 model** (`incremental_strategy='merge'`). You hand-write the "close the changed
   version, insert the new one" logic, reading current state via `{{ this }}`.
3. **Hybrid** (recommended default): a thin snapshot does the cheap, stateful history *capture*, and a
   normal model built on `ref(snapshot)` does the *presentation* (surrogate key, `is_current`,
   valid-from/to shaping, joins).
4. **Data Vault satellite** (DV only): insert-only append, a new row per detected change via hashdiff
   + `load_dts`, loaded incrementally by `datavault4dbt`. Not a dbt snapshot; the package owns it.

## Scored on the three axes

**Compute**
- Snapshot `check`: full compare of source vs snapshot every run, cost scales with source size
  (`O(source)`) even when little changed. Fine small/medium, expensive at scale.
- Snapshot `timestamp`: only newer `updated_at` rows, much cheaper, needs a trustworthy timestamp.
- Incremental `merge`: scans only changed rows via the `is_incremental()` predicate, usually the
  cheapest at scale; the merge rewrites matched partitions/microfiles (notable on BigQuery /
  Databricks), so cluster/partition by the business key to bound it.
- DV satellite: insert-only, no rewrite of existing rows, cheap writes; reads add the "current row per
  key" resolution cost downstream (PITs mitigate).

**Lineage**
- Incremental model / DV satellite: first-class DAG nodes, uniform `ref()`, column-level lineage,
  exposures, and tests. Cleanest.
- Snapshot: a distinct resource type; it can `ref()` upstream models (v1.9+), but some column-level
  lineage / test tooling treats it as a leaf, and it breaks "everything is a model."
- Caveat for incremental SCD2: the `{{ this }}` self-reference is an implicit self-dependency that
  can muddy full-refresh reasoning. A snapshot hides that inside the resource.

**Debugging**
- Incremental model: `dbt compile` / `dbt show`, add audit columns, and it is **unit-testable**
  (dbt unit tests do not support snapshots). Reason about it like any model.
- Snapshot: stateful and append-only, no clean preview, a bad deploy pollutes history,
  `--full-refresh` destroys it, no unit tests, recovery means warehouse time-travel or a rebuild.
- History-fragility applies to any single-copy history store: if the source is current-state only, a
  standalone snapshot **or** a standalone incremental model both lose history on full refresh. The
  hybrid protects the model layer because history lives in the (never-full-refreshed) snapshot.

## Pick this when

- **Hybrid (snapshot capture + model on top)** - default for most migrations. Best balance: the only
  stateful piece is a tiny snapshot; lineage and debugging live in the model, which is safe to
  full-refresh. Use for typical Type-2 dims.
- **Plain dbt snapshot consumed directly** - smallest dims, quick wins, when a separate presentation
  model adds no value.
- **Incremental SCD2 model** - large dimensions where the snapshot compare hurts and you have a
  reliable CDC / `updated_at` predicate; or you need Type-4 / mini-dimensions, custom effective-dating,
  delete handling, or unit-tested SCD logic. Own the merge, cluster by key, guard `--full-refresh`.
- **DV satellite** - always, for history in a Data Vault build; let `datavault4dbt` load it. A snapshot
  can still feed a satellite's source if the system only exposes current state.

## Per-paradigm pointers

- **Kimball / star:** Type-2 dim = hybrid by default (snapshot then `dim_` model). See building-kimball.md.
- **Data Vault:** history = satellite (insert-only, `datavault4dbt`). See building-datavault.md.
- **Layered:** apply the same decision to any history-preserving model; default hybrid.

Whatever you choose, the eval judges history on **outcome** (is prior state preserved and queryable),
not on the mechanism, so a correct incremental SCD2 model passes parity just like a snapshot.
