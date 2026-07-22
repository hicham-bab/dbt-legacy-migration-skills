# Parsing a Coalesce (coalesce.io) project (Step 1)

> **Disambiguation:** this is **Coalesce.io** — the column-aware transformation platform for
> Snowflake/Databricks/BigQuery (Coalesce Automation Inc.) — **not** the former dbt Labs "Coalesce"
> conference (now dbt Summit).

How to read a Coalesce project export and produce the workload inventory. Coalesce commits the
project to **Git as YAML**; clone the repo and parse it. Structure below is grounded in Coalesce
docs and the real `coalesceio` Git format. You read the YAML directly — the deterministic script
does the walking.

## Contents

- [Project layout](#project-layout)
- [The node file](#the-node-file)
- [Node kinds](#node-kinds)
- [Column-level lineage](#column-level-lineage)
- [Building the inventory](#building-the-inventory)

## Project layout

A Coalesce Git repo (one repo per Project) commits:

```
./data.yml                 # global project settings
./locations.yml            # storage locations (db/schema mappings)
./environments/*.yml       # deployment environments (dev/QA/prod)
./nodes/*.yml              # ONE FILE PER NODE — the instances (the workload)
./nodeTypes/<Name-id>/     # node type templates
    definition.yml         #   UI/metadata spec (nodeMetadataSpec)
    create.sql.j2          #   DDL template (Deploy)  ~ dbt materialization
    run.sql.j2             #   DML template (Run)     ~ SCD2 MERGE / INSERT logic
./macros/*.yml             # macros
./jobs/*.yml               # job definitions (schedules)
./subgraphs/*.yml          # reusable sub-DAGs
```

Node files are named `<LOCATION>-<NODE_NAME>.yml` (e.g. `SOURCE_DATA-CUSTOMERS.yml`,
`TARGET_DB-DIM_CUSTOMER_SCD2.yml`). **The nodes are the migration units.**

## The node file

Verified key paths in `./nodes/*.yml`:

```yaml
fileVersion: 1
id: <uuid>                          # node id (referenced by downstream stepCounter)
name: DIM_CUSTOMER_SCD2
operation:
  locationName: TARGET_DB           # the schema/location
  materializationType: table        # table | view
  sqlType: Source                   # present on SOURCE nodes
  type: sourceInput                 # present on SOURCE nodes
  config:
    type2Dimension: true            # <- SCD2 switch (dimension nodes)
    lastModifiedComparison: true    # CDC by last-modified column
    lastModifiedColumn: {...}
    truncateBefore: false           # Stage/Work = true (truncate+reload)
    preSQL: "" / postSQL: ""        # -> dbt pre_hook / post_hook
  metadata:
    columns:
      - name: DIM_CUSTOMER_KEY
        dataType: NUMBER
        isSurrogateKey: true        # surrogate key flag
      - name: CUSTOMER_ID
        dataType: NUMBER(38,0)
        isBusinessKey: true         # business/natural key flag
        transform: "<sql expr>"     # the column's transform (-> SELECT expression)
        sourceColumnReferences:
          - columnReferences:
              - {stepCounter: <upstream-node-id>, columnCounter: <upstream-col-id>}   # lineage (stepCounter = node)
            transform: ""
type: Node
```

> **Caveat (flag):** the *node type name* isn't always a single clean key on a target node file —
> infer the kind from `sqlType`/`type` (sources), `config.type2Dimension`, `isBusinessKey`,
> `materializationType`, and the name prefix. Confirm on a real export; unfamiliar custom node
> types (UDNs) → inventory and route to review.

## Node kinds

| Coalesce node | What it is | Recognize by |
|---|---|---|
| **Source** | existing raw table/view, not transformed | `operation.type: sourceInput` / `sqlType: Source` |
| **Stage / Work** | business logic, truncated+reloaded each run | `truncateBefore: true`, no business key, view/table |
| **Persistent Stage** | like Stage but persists across runs; history w/ a business key | persists; business key present |
| **Dimension** | Kimball dimension (SCD1 or SCD2) | business key; `type2Dimension` true/false |
| **Fact / Factless Fact** | Kimball fact | name `FCT_`/`FACT_`; measures + FK columns |
| **View** | generic SQL view | `materializationType: view` |

## Column-level lineage

Coalesce lineage is **column-level**: each target column's
`sourceColumnReferences[].columnReferences[]` holds `{columnCounter, stepCounter}` where
**`stepCounter` is the upstream _node_ id and `columnCounter` is the upstream _column_ id** (verified
against real exports). Resolve **`stepCounter`** to a node's `id` to get the upstream node
(→ a dbt `ref()`) — *not* `columnCounter` — and combine each column's `transform` with its source
column to produce the SELECT expression. A `stepCounter` of `"0"` is Coalesce's constant/no-source
marker (ignore it). A column with empty `sourceColumnReferences` on a Source node is a raw column; a
surrogate-key column (`isSurrogateKey`) is generated, not sourced.

> The `inventory_coalesce.py` script does this resolution for you (verified against real Coalesce Git
> exports — a 21-node demo and a 482-node project).

## Building the inventory

1. Run the deterministic script:
   `python3 <skills-dir>/migrating-coalesce-to-dbt/scripts/inventory_coalesce.py <project-dir> --json`
   (needs `pyyaml`). It emits each node's inferred kind, materialization, business/surrogate keys,
   resolved upstream nodes (lineage), per-column transforms, the **coverage denominator**
   (non-source nodes), and the **SCD2 dimensions**.
2. Sources → dbt `sources`; every non-source node → a dbt model (the coverage denominator).
3. Hand the inventory to Step 2 (modeling approach) and the node bodies to Step 3
   ([coalesce-node-mapping.md](coalesce-node-mapping.md)).

> **Verification:** the parser is checked in `evals/` against a committed fixture and was validated
> against **real Coalesce Git exports** (a 21-node demo and a 482-node project) — sources, dims,
> facts, stages, business keys, and column-level lineage all resolve. Still confirm the customer's
> export early, since a project may use **custom node types (UDNs)** or the **Dynamic-Tables**
> dimension variant, which the kind-inference may not recognize.
