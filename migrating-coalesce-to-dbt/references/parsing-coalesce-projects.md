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
./data.yml                 # project config: default storage mapping, fileVersion (auto-generated
                           #   by Coalesce on an empty repo — holds connections, storage-location
                           #   mappings, node-type/macro registration; see Coalesce Git docs)
./environments/*.yml       # deployment environments (dev/QA/prod)
./nodes/*.yml              # ONE FILE PER NODE — the instances (the workload)
./nodeTypes/<Name-id>/     # node type templates (one dir per type; standard + user-defined)
    definition.yml         #   Node Definition — UI/metadata spec (name, tagColor, config items)
    create.sql.j2          #   Create Template — DDL, run at Deploy  ~ dbt materialization
    run.sql.j2             #   Run Template — DML, run at Refresh   ~ SCD2 MERGE / INSERT logic
./packages/                # installed marketplace / package node types (when present)
./macros/*.yml             # macros            (present only if the project defines them)
./jobs/*.yml               # job definitions   (schedules; present only if defined)
./subgraphs/*.yml          # reusable sub-DAGs (present only if defined)
```

Only `data.yml`, `nodes/`, `nodeTypes/` and `environments/` are always present; `macros/`, `jobs/`,
`subgraphs/`, `packages/` appear only when the project uses them. Confirmed against real exports
(`0nmus/coalesce-demo`) and the [Coalesce Git integration docs](https://docs.coalesce.io/docs/git-integration).

Node files are named `<LOCATION>-<NODE_NAME>.yml` (e.g. `SAMPLE-CUSTOMER.yml`,
`WORK-DIM_CUSTOMER.yml`) where `<LOCATION>` is the storage location. **The nodes are the migration
units.**

## The node file

Verified key paths in `./nodes/*.yml`:

```yaml
fileVersion: 1
id: <uuid>                          # node id (referenced by downstream stepCounter)
name: DIM_CUSTOMER
operation:
  locationName: WORK                # the storage location (schema)
  materializationType: table        # table | view
  sqlType: Dimension                # THE node-type discriminator: Source | Stage |
                                     #   Dimension | Fact | View | Persistent Stage
  type: sql                         # sql (transform) | sourceInput (source node)
  isMultisource: false
  config:
    preSQL: "" / postSQL: ""        # -> dbt pre_hook / post_hook
    truncateBefore: true            # Stage default = truncate+reload
    testsEnabled: true
  metadata:
    columns:
      - name: DIM_CUSTOMER_KEY
        dataType: NUMBER(38,0)
        isSurrogateKey: true        # surrogate key flag (generated, not sourced)
      - name: C_CUSTKEY
        dataType: NUMBER(38,0)
        isBusinessKey: true         # business/natural key flag
        transform: "<sql expr>"     # the column's transform (-> SELECT expression)
        sourceColumnReferences:
          - columnReferences:
              - {stepCounter: <upstream-node-id>, columnCounter: <upstream-col-id>}   # lineage (stepCounter = node)
            transform: ""
      - name: EFFECTIVE_FROM
        isChangeTracking: true      # <- SCD2 marker: a change-tracking column on a
                                     #    Dimension node = Type 2 (else Type 1)
type: Node
```

> **Node-type detection (grounded):** classify from **`operation.sqlType`** — Coalesce writes the
> node type there (`Source` / `Stage` / `Dimension` / `Fact` / `View` / `Persistent Stage`). This is
> the reliable discriminator; the name prefix is only a hint. **SCD Type 2** is a Dimension node with
> a **change-tracking column** (`isChangeTracking: true`) — matching the docs ("Type 2: with change
> tracking column selected"); a Dimension with no change-tracking column is **Type 1**. Only fall
> back to name/column heuristics for **user-defined (custom) node types** that carry no standard
> `sqlType`; route the ambiguous to review.

## Node kinds

Per the [Coalesce docs, "Nodes and Node Types"](https://docs.coalesce.io/docs/get-started/coalesce-fundamentals/nodes):

| Coalesce node (`sqlType`) | What it is | Behavior / recognize by | dbt target |
|---|---|---|---|
| **Source** | existing raw table/view, not transformed | `type: sourceInput` / `sqlType: Source` | dbt `source()` |
| **Stage** | business logic; **truncate + reload** each run by default | `sqlType: Stage`, `truncateBefore: true` | `stg_`/`int_` model |
| **Persistent Stage** | like Stage but **persists across runs**; tracks change history by business key | `sqlType: Persistent Stage`; business key | incremental model / snapshot |
| **Dimension** | Kimball dimension; **requires a business key**. Type 1 (current) or Type 2 (history) | `sqlType: Dimension`; Type 2 = `isChangeTracking` column present | `dim_` (Type 2 via **snapshot**) |
| **Fact** | Kimball fact; **MERGE** when a business key is set, else **INSERT** | `sqlType: Fact` | `fct_` model |
| **View** | generic SQL view (DAG readability) | `sqlType: View` / `materializationType: view` | `view`-materialized model |

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
   (needs `pyyaml`). It emits each node's `sqlType` + inferred kind, materialization,
   business/surrogate/change-tracking keys, resolved upstream nodes (lineage), per-column transforms,
   the **coverage denominator** (non-source nodes), and the **SCD2 dimensions**
   (Dimension nodes with a change-tracking column → dbt snapshots).
2. Sources → dbt `sources`; every non-source node → a dbt model (the coverage denominator).
3. Hand the inventory to Step 2 (modeling approach) and the node bodies to Step 3
   ([coalesce-node-mapping.md](coalesce-node-mapping.md)).

> **Verification:** the parser is checked in `evals/` against a committed fixture and was validated
> against **real Coalesce Git exports** (a 21-node demo and a 482-node project) — sources, dims,
> facts, stages, business keys, and column-level lineage all resolve. Still confirm the customer's
> export early, since a project may use **custom node types (UDNs)** or the **Dynamic-Tables**
> dimension variant, which the kind-inference may not recognize.
