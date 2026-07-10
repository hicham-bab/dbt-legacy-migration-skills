# dbt layer classification & Mesh detection (Step 2)

Distilled from the confidence-scored classifier in `~/talend-to-dbt/src/talend_to_dbt/graph/classifier.py`.
After the workload is inventoried (Step 1), assign each unit of work to a dbt layer so the
generated project follows the standard source → staging → intermediate → mart structure.

## Contents

- [The four layers](#the-four-layers)
- [Confidence-scored classification](#confidence-scored-classification)
- [Naming conventions](#naming-conventions)
- [Mesh domain detection](#mesh-domain-detection)

## The four layers

| Layer | Purpose | Materialization default | dbt object |
|---|---|---|---|
| **source** | Raw tables the legacy job reads from | (declared, not materialized) | `sources:` in a `_sources.yml` |
| **staging** (`stg_`) | 1:1 with a source: rename, cast, light clean, no joins | `view` | model |
| **intermediate** (`int_`) | Joins, lookups, reusable business logic, fan-in | `view` or `ephemeral` | model |
| **mart** (`fct_`/`dim_`) | Final business entities, aggregations, the tables consumers query | `table`/`incremental`/snapshot | model |

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
