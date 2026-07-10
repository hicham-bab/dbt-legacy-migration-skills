# dbt concepts, explained (for people new to dbt)

Use this to **explain concepts to the migrator in plain language** as they come up. Assume the
person may know their legacy tool (Informatica/Talend/Matillion/SQL procs) well but be new to dbt.
When a step introduces a term below, give the one-line "what/why" and point here for more.

## Contents

- [What dbt is](#what-dbt-is)
- [Model, ref(), source()](#model-ref-source)
- [The DAG and the layers](#the-dag-and-the-layers)
- [Materializations: view, table, incremental, ephemeral](#materializations-view-table-incremental-ephemeral)
- [Snapshots and SCD (tracking history)](#snapshots-and-scd-tracking-history)
- [Tests](#tests)
- [Docs](#docs)
- [Contracts](#contracts)
- [Seeds, macros, packages](#seeds-macros-packages)
- [Fusion vs Core](#fusion-vs-core)

## What dbt is

dbt is a **transformation** tool: you write `SELECT` statements, and dbt handles the rest — creating
the tables/views, running them in the right order, testing them, and documenting them. You do **not**
write `CREATE TABLE`/`INSERT`/`MERGE`; you describe *what the data should be* with a query, and dbt
materializes it in your warehouse. This is the big shift from a legacy ETL tool: the warehouse does
the compute, and your logic lives as version-controlled SQL, not in a drag-and-drop canvas.

## Model, ref(), source()

- A **model** is one `.sql` file = one `SELECT` = one table or view in the warehouse.
- `{{ source('raw', 'orders') }}` points at a **raw table** the data was loaded into (declared once
  in a `sources` YAML). `{{ ref('stg_orders') }}` points at **another model**. Using these instead
  of hard-coded `db.schema.table` names is what lets dbt build a dependency graph and swap
  environments (dev/prod) automatically.
- *Why it matters in a migration:* every legacy "read a table" becomes a `source()` or `ref()`, and
  every legacy "write a table" becomes a model.

## The DAG and the layers

dbt reads your `ref()`s to build a **DAG** (dependency graph) and runs models in order. The common
layering:
- **staging (`stg_`)** — one model per source table: rename, cast, light clean. Usually a **view**.
- **intermediate (`int_`)** — joins and reusable business logic.
- **mart (`fct_`/`dim_`)** — the final tables people query.
*Why:* small, testable steps; you can trace any number back to its source; you reuse instead of
copy-pasting logic across a hundred legacy jobs.

## Materializations: view, table, incremental, ephemeral

A **materialization** is *how* dbt persists a model's `SELECT`:
- **view** — dbt creates a database view; the query re-runs every time someone reads it. Cheap to
  build, no storage; good for light staging. (Nothing is stored; compute happens at query time.)
- **table** — dbt runs the query and stores the full result as a table, rebuilt each run. Fast to
  query; costs compute to rebuild every time. Good for marts that aren't huge.
- **incremental** — dbt builds the table once, then on later runs **only processes new/changed
  rows** and adds them, instead of rebuilding everything. *Why it matters:* for a large, frequently
  updated table (a big fact table, an event log), rebuilding from scratch every run is slow and
  expensive; incremental is the single biggest compute saving. It needs a `unique_key` (so dbt knows
  what to update) and a filter (`is_incremental()`) selecting only the new rows. Legacy
  "MERGE/upsert" or "append" patterns become incremental models.
- **ephemeral** — not built in the warehouse at all; dbt inlines the SQL into whatever model
  `ref()`s it (like a reusable CTE). Good for small helper logic.

Rule of thumb (the dbt docs' progression): **start every model as a view**; promote it to a **table**
once it's slow to *query*; switch to **incremental** only once that table is slow to *build* — "don't
start with incremental models." So in practice staging stays views, marts become tables, and only big
event/fact tables become incremental.

## Snapshots and SCD (tracking history)

A **Slowly Changing Dimension (SCD)** is a dimension whose attributes change over time and you want
to keep the **history** — e.g. a customer moves city, and you want to know which city they were in
when each past order was placed. **SCD Type 2** keeps a new row per version, with `valid_from` /
`valid_to` dates and an `is_current` flag.

A dbt **snapshot** is dbt's built-in way to do SCD Type 2: point it at a table, tell it the key and
which columns to watch, and on each run it records any changes as new versioned rows (adding
`dbt_valid_from` / `dbt_valid_to`). *Why it matters:* legacy tools do this with complex
"insert-new-expire-old" logic (Informatica Update Strategy, Matillion Detect Changes, a MERGE in a
proc). In dbt you don't hand-build that — you use a snapshot. If a legacy job "keeps history of
changes," it becomes a snapshot.

## Tests

**Data tests** are assertions dbt runs against your data:
- `unique` / `not_null` on a key — the grain is what you think it is.
- `accepted_values` — a column only holds an allowed set (e.g. status in active/inactive).
- `relationships` — every foreign key matches a row in the referenced table (no orphans).
*Why:* they catch a broken migration automatically, and they document the intended shape of the data.

## Docs

Every model and column gets a plain-English **description** in YAML. *Why:* the people consuming the
migrated data (analysts) often didn't build the legacy job; the docs are how they understand what a
column means and at what grain — and dbt renders them into a browsable catalog.

## Contracts

A **contract** (`contract: enforced`) pins a model's column names and data types, so the model is a
stable "API" other teams can depend on — dbt fails the build if the shape drifts. *Why in a
migration:* it guarantees the migrated table matches the shape the legacy consumers expect, and (in
a multi-project "Mesh") lets other domains safely build on your tables.

## Seeds, macros, packages

- **Seed** — a small CSV checked into the project, loaded as a table (lookup/reference data).
- **Macro** — a reusable snippet of SQL logic (like a function), written in Jinja.
- **Package** — a shared library of macros/models installed from the dbt package hub
  (hub.getdbt.com), so you reuse maintained code instead of writing your own (see
  [dbt-packages.md](dbt-packages.md)).

## Fusion vs Core

**dbt Core** is the original open-source engine. **dbt Fusion** is the newer engine that compiles
and type-checks your SQL in real time (catching errors before you touch the warehouse). This
migration prefers Fusion because that fast, free feedback loop makes the work quicker and safer.
"Fusion-conformant SQL" just means standard SQL that Fusion accepts (`cast(...)` not `::`,
`coalesce()` not `nvl()`).

## Learn more (official dbt docs)

Everything above is grounded in the dbt documentation — send newcomers to the source:
[materializations](https://docs.getdbt.com/docs/build/materializations),
[incremental models](https://docs.getdbt.com/docs/build/incremental-models),
[snapshots](https://docs.getdbt.com/docs/build/snapshots),
[data tests](https://docs.getdbt.com/docs/build/data-tests),
[model contracts](https://docs.getdbt.com/docs/mesh/govern/model-contracts), and
[How we structure our dbt projects](https://docs.getdbt.com/best-practices/how-we-structure/1-guide-overview).
