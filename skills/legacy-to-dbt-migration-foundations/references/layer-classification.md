# dbt layer classification & Mesh detection (Step 2)

After the workload is inventoried (Step 1), assign each unit of work to a dbt layer so the
generated project follows the standard source → staging → intermediate → mart structure. The
confidence scores below are the classifier: apply the rules in priority order and record the score
you assigned, because Step 7 counts anything under 0.65 against coverage.

## Contents

- [The four layers](#the-four-layers)
- [Confidence-scored classification](#confidence-scored-classification)
- [Don't over-split the intermediate layer](#dont-over-split-the-intermediate-layer)
- [Naming conventions](#naming-conventions)
- [Mesh domain detection](#mesh-domain-detection)
- [Wave planning for large workloads](#wave-planning-for-large-workloads)

## The four layers

Per dbt's [How we structure our dbt projects](https://docs.getdbt.com/best-practices/how-we-structure/1-guide-overview)
guide, a project moves data from *source-conformed* to *business-conformed* across these layers:

| Layer | Purpose | Materialization | Naming (dbt docs) |
|---|---|---|---|
| **source** | Raw tables the legacy job reads from | (declared, not materialized) | `sources:` in a `_sources.yml` |
| **staging** (`stg_`) | **1:1 with a source table**: rename, cast, light compute — **no joins, no aggregations**; the only place using `source()` | **view** | `stg_[source]__[entity]s` (double underscore; plural entity) |
| **intermediate** (`int_`) | Joins, lookups, reusable business logic, fan-in; not exposed in the main prod schema | **ephemeral** (simplest) or **view** in a custom schema | `int_[entity]s_[verb]s` |
| **mart** | Final business entities the consumers query; wide/denormalized | **start as a `view`; promote to `table` when it's slow to *query*; to `incremental` only when the table is slow to *build*** | *layered default:* plain-English entity (`customers`, `orders`). *Dimensional modeling (Kimball/Star):* `fct_`/`dim_` (a deliberate departure — see [target-modeling.md](target-modeling.md)) |

> **Naming note (grounded in the docs):** dbt's structure guide names marts by **plain-English
> entity** (`customers.sql`, `orders.sql`), *not* `fct_`/`dim_`, and it explicitly contrasts with a
> Kimball star schema. So for a **faithful layered port**, use plain-English mart names. The
> `fct_`/`dim_` prefixes are correct only when the migrator picks a **dimensional** target
> (Kimball/Star), where they're the intended convention.
>
> **Materialization (grounded):** the docs say *start every model as a view*, promote to `table`
> when querying is slow, and to `incremental` only when the table build is slow — "don't start with
> incremental models." Recommend on that basis rather than defaulting marts to `table`.

## Confidence-scored classification

Classify each unit, attach a confidence score, and **flag anything below 0.65 for human review**
(it counts against coverage in Step 7). Priority order: name override → structural role →
topology fallback.

1. **Name-prefix override (highest confidence).** If the legacy object/target name already carries
   an intent: `raw_`/`src_` → source (0.95); `stg_` → staging (0.95); `int_`/`wrk_`/`tmp_` →
   intermediate (0.90); `fct_`/`fact_`/`dim_`/`agg_`/`rpt_` → mart (0.92).
2. **Structural role of the unit** (from the source parser):
   - Reads a raw DB table with no upstream transform → source + a `stg_` model (0.95).
   - Single-input rename/cast/filter → staging (0.83).
   - Join or lookup against another flow → intermediate (0.85).
   - Aggregation / GROUP BY / final write to a reporting table → mart (0.82).
   - Dedup (distinct / ROW_NUMBER=1) → staging or intermediate depending on inputs (0.80).
   - Write to the warehouse target table → mart (0.88).
3. **Topology fallback** (when name and role are ambiguous): in-degree 0 (only reads sources) →
   staging; high in-degree, feeds other transforms → intermediate; out-degree 0 (nothing reads it,
   it is a terminal write) → mart. Confidence 0.60–0.70 — usually worth a human confirm.

Record `(unit, layer, confidence, reason)` for every unit; this table feeds both the generated
folder structure and the coverage report.

## Don't over-split the intermediate layer

A legacy job has many sequential steps, but **one `int_` model per legacy step is wrong** — it
produces chains of thin intermediate models (`int_a` → `int_b` → mart) where the logic belonged in a
single model. Consolidate:

- **Default: one intermediate model per logical transformation, using CTEs for its sequential
  steps.** Several legacy steps that flow linearly into one output (filter → derive → join →
  aggregate) become **one** `int_` model with a CTE per step, then the mart reads that one `int_`.
  Don't materialize each step as its own model.
- **Split into a separate `int_` model only when** one of these is true:
  1. the intermediate result is **reused by 2+ downstream models** (build once, `ref()` it), or
  2. it **crosses a grain change** (e.g. row-level detail → an aggregate) that a later model needs
     at the pre-aggregated grain, or
  3. the single model would be **too large to read/test** and a named split genuinely clarifies it.
- **Rule of thumb:** if `int_b`'s only consumer is one mart and it doesn't change grain, fold it into
  that mart (or into `int_a`) as a CTE instead of a standalone model. Prefer the fewest models that
  each have a distinct, nameable purpose.

This matches dbt's guidance that intermediate models are purposeful "molecules," not a 1:1 echo of
every source step (see [How we structure our dbt projects](https://docs.getdbt.com/best-practices/how-we-structure/3-intermediate)).

## Naming conventions

- snake_case everywhere; layer prefix + a meaningful entity name: `stg_orders`,
  `int_orders_joined_customers`, `fct_sales`, `dim_customer`.
- Strip source schema prefixes from column aliases.
- One staging model per source table; one mart per business entity.
- Folder layout: `models/staging/`, `models/intermediate/`, `models/marts/` (optionally
  `models/marts/<domain>/`).

## Mesh domain detection

If the legacy artifacts show clear domain boundaries — separate folders, schemas, or naming stems
(e.g. `finance_*`, `marketing_*`, `mktg.`, `fin.`) — propose a dbt Mesh split: a producer project
for shared/core entities and one consumer project per domain. Signals:

- Distinct schema namespaces per subject area.
- Groups of jobs that only read one domain's tables plus shared dims.
- A shared dimension set (customer, product, date) read by every domain → belongs in the producer.

When Mesh applies, put shared marts in the producer with `access: public` + enforced contracts,
and have consumers reference them across projects. Confirm the split with the user before
scaffolding multiple projects — do not impose Mesh on a small single-domain job.

## Wave planning for large workloads

The shared workflow is implicitly **single-batch**: one inventory, one classification pass, one
coverage number, one document. That works for a handful of pipelines and has no story above roughly
20. Waves are the extension: the same steps, executed repeatedly over slices of one fixed inventory.

**When to use waves**

- More than roughly 20 legacy units, **or**
- any workload that will not fit one working session's context — whichever comes first. Below that,
  do not add the machinery; a single batch is simpler and the coverage number is easier to defend.

**Derive the waves from the DAG, not from a directory listing**

`01_inventory.json` carries the pipeline DAG edges. Each edge is `{unit, source, target, kind}`; use
the **data-flow** kind (`flow` in the Matillion inventory) for lineage and ignore the control-flow
kinds — a failure branch or a conditional path is not a data dependency and must not constrain wave
order.

1. Topologically order the units over the data-flow edges.
2. Group by **dependency depth**: depth 0 is everything with no upstream unit in the estate, depth 1
   is everything depending only on depth 0, and so on.
3. Wave *n* = depth band *n*. The invariant: **a wave never depends on a later wave.** If it does,
   the ordering is wrong — fix it before building, not by patching `ref()`s later.
4. A cycle in the edges means the estate has a genuine cyclic dependency (or the edges are
   mis-parsed). Resolve it explicitly and record which it was; do not silently break the cycle.

**Sub-group within a depth band by domain**

A depth band can be wider than one session. Split it using the **same schema/folder/naming-stem
signals** this file already uses for Mesh detection, so a wave is one domain at one depth. That
keeps the models built together the ones that share sources and conventions, and it makes a later
Mesh split cheaper if it happens.

**Emit `02_waves.json`**

Persist the plan with per-wave unit lists — wave number, depth band, domain, and the units in it.
The plan is an artifact, not a decision held in the session.

**Steps 3 through 7 become wave-scoped**

Translate, test, validate and report per wave. Coverage **accumulates** across waves against the
**single fixed denominator from Step 1**:

- **The denominator must NOT be recomputed per wave.** A per-wave denominator makes every wave look
  ~100% complete and the estate-level number disappears. Wave 3 of 5 reporting "100% coverage" is
  meaningless; "wave 3 complete, 61% of the estate migrated and validated" is the number that
  matters. See [coverage-report.md](coverage-report.md) — `gross_coverage` is always over the whole
  inventory.
- Report the running estate total alongside the per-wave result, every wave.

**Pattern deduplication**

Identical component subgraphs recur across units in most large estates. Translate such a subgraph
**once** and reuse it — a macro for a repeated expression pattern, an intermediate model for a
repeated data pattern — rather than regenerating it per unit.

Honestly: the value of this depends **entirely** on how repetitive the actual estate is, and that is
unknown before you look. Measure it on the first two waves (how many units shared a translated
pattern, and did the macro survive contact with the second wave) before planning any later wave
around the saving. A macro parameterised to fit three barely-similar pipelines is worse than three
plain models.

**Waves must be resumable from artifacts alone**

Context does not carry across sessions. Assume the next wave starts with no memory of this one:
everything it needs — the inventory, the classification table, the wave plan, the accumulated
coverage, the accepted parity differences — must be readable from the persisted artifacts. If a wave
can only be continued by someone who was present for the previous one, the artifacts are incomplete.
