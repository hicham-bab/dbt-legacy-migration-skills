# Parsing a PowerCenter XML export (Step 1)

How to walk an Informatica PowerCenter repository export and produce the workload inventory that
Step 1 requires. The element/attribute names below are **verified** against
`a real PowerCenter 10.5 XML export`. You read the XML directly with
Read/Grep; no Python is required. (The element-walking parser at
`a reference XML-walking parser` is a useful structural template for
the traversal.)

## Contents

- [XML structure](#xml-structure)
- [What to extract](#what-to-extract)
- [Building the inventory + data-flow graph](#building-the-inventory--data-flow-graph)

## XML structure

A PowerCenter export is `<POWERMART CREATION_DATE= REPOSITORY_VERSION=>` →
`<REPOSITORY NAME= VERSION= DATABASETYPE=>` → `<FOLDER NAME=>`. Inside a folder you find, in rough
order: `SOURCE`/`TARGET` definitions, reusable `TRANSFORMATION`s, `MAPPLET`s, `MAPPING`s (each a
graph of `INSTANCE` nodes joined by `CONNECTOR` edges), `WORKLET`s, and a `WORKFLOW` with `SESSION`
tasks and control tasks.

Source/target definitions:
- **`<SOURCE DBDNAME= DATABASETYPE= ...>`** — a source table/file (`DBDNAME` names its database;
  `DATABASETYPE` may be `Oracle`, `Flat File`, etc.) with `<SOURCEFIELD>` columns.
- **`<TARGET DATABASETYPE= DESCRIPTION= ...>`** — a target table with `<TARGETFIELD>` columns. The
  `DESCRIPTION` often flags intent (e.g. "SCD Type 2 customer dimension").

The two elements that carry the mapping data flow:
- **`<INSTANCE NAME= TRANSFORMATION_TYPE= TYPE= DBDNAME=>`** — a node in a mapping.
  `TRANSFORMATION_TYPE` is e.g. `Source Qualifier`, `Expression`, `Lookup Procedure`, `Filter`,
  `Router`, `Joiner`, `Aggregator`, `Update Strategy`, `Sequence`. `TYPE` is `SOURCE`, `TARGET`, or
  `TRANSFORMATION`.
- **`<CONNECTOR FROMINSTANCE= FROMFIELD= TOINSTANCE= TOFIELD= FROMINSTANCETYPE= TOINSTANCETYPE=>`**
  — an edge wiring one instance's port to the next; the `CONNECTOR` list is the mapping DAG and its
  column-level lineage.

The transformation **definitions** (referenced by instances) carry the logic:
- **`<TRANSFORMATION NAME= TYPE= REUSABLE= ...>`** holds the ports and properties.
- **`<TRANSFORMFIELD NAME= PORTTYPE= DATATYPE= PRECISION= SCALE= EXPRESSION=>`** — one per port.
  `PORTTYPE` is `INPUT`/`OUTPUT`/`INPUT/OUTPUT`. For **Expression** and **Aggregator** ports the
  derivation is in the `EXPRESSION` attribute (an output port `out_X` with
  `EXPRESSION="expr"`); ports with no expression are passthrough.
- **`<TABLEATTRIBUTE NAME="..." VALUE="...">`** — the transformation's **properties**, and where
  most non-Expression logic lives. Verified names in the fixture: `Filter Condition` (Filter),
  `Lookup condition` and `Sql Query` (Lookup/Source Qualifier), `Group By` (Aggregator),
  `Update Strategy Expression` (e.g. `DD_INSERT`/`DD_UPDATE`), and Sequence props `Start Value` /
  `Increment By` / `Current Value`. Read TABLEATTRIBUTE first for Filter/Router/Lookup/Update
  Strategy/Sequence; read TRANSFORMFIELD `EXPRESSION` for Expression/Aggregator derivations.

Other elements: `<TARGETLOADORDER ORDER= TARGETINSTANCE=>` (target write order), `<MAPPLET>`
(reusable sub-flow with `Input Transformation`/`Output Transformation` ports),
`<WORKFLOW>`/`<SESSION>`/`<WORKLET>` and control tasks (Decision, Timer, Command, Event Wait,
Assignment, Email).

## What to extract

For each **mapping**, record:
1. **Sources** — `INSTANCE TYPE="SOURCE"` + the matching `<SOURCE>` definition (name, DB, columns,
   types). These become dbt `sources`.
2. **Transformations** — every `INSTANCE TYPE="TRANSFORMATION"`, its `TRANSFORMATION_TYPE`, and its
   logic (the `TRANSFORMFIELD` expressions, filter conditions, join/lookup conditions, group-by).
3. **Targets** — `INSTANCE TYPE="TARGET"` + `<TARGET>` definition. These become dbt models
   (or snapshots for SCD2 targets).
4. **Edges** — the `CONNECTOR` list → the column-level lineage and the transform order.

For **mapplets**: capture the sub-flow between `Input Transformation` and `Output Transformation`
— migrate once as a macro or intermediate model, reference from each caller.

For the **workflow**: capture session order, `TARGETLOADORDER`, and control-task conditions. dbt
models the data DAG; note control-flow (decisions, timers, email-on-failure) for the scheduler.

Read parameter files (`parameters/*.par`) for values referenced as `$$PARAM` — but **never** read
or echo connection credentials from them.

## Building the inventory + data-flow graph

1. List every mapping and, within it, every transformation instance → this is the **total unit
   count** (the coverage denominator; record it).
2. From the `CONNECTOR` edges, build the intra-mapping DAG (source → … → target). Collapse
   pure-passthrough instances (a Source Qualifier that only selects, a Sequence feeding one port).
3. Add cross-mapping edges: shared staging targets read by later mappings, and mapplet reuse.
4. Hand the inventory to Step 2 (classification) and the per-transformation logic to Step 3
   (translation via [powercenter-transformation-mapping.md](powercenter-transformation-mapping.md)).

**Reference fixture:** `a real PowerCenter 10.5 XML export` is a
complete, realistic example (10 sources, staging/dim/fact targets, a `mplt_LOOKUP_DIM_KEYS`
mapplet, a `wklt_LOAD_DIMENSIONS` worklet, SCD2 dims, and a full workflow). Its companion
`docs/WORKFLOW_DESIGN.md` walks each mapping, and `snowflake/04_edw_load_simulation.sql` shows the
intended SQL output per `[m_...]` mapping — use it to check your translations.
