# Parsing Talend `.item` jobs (Step 1)

How to read a Talend job export and produce the workload inventory. The element/attribute names
below are **verified** against real `.item` fixtures at `real Talend `.item` exports`
and against the working parser at `a reference XML-walking parser`.
You read the XML directly with Read/Grep; no Python required.

## Contents

- [File layout](#file-layout)
- [XML structure](#xml-structure)
- [Where each component keeps its logic](#where-each-component-keeps-its-logic)
- [Building the inventory + data-flow graph](#building-the-inventory--data-flow-graph)

## File layout

A Talend export has one `.item` file per job (the component graph, XML). The root element is
`<talendfile:ProcessType name="...">`. Talend Studio projects also carry a sibling `.properties`
metadata file per job and may externalize context groups under `contexts/`; context can **also**
be inline as a `<context>` element inside the `.item` (as in the demo fixtures). Scan the tree for
all `.item` files first — each is one job to inventory.

## XML structure

Verified elements and attributes:

- **`<node componentName="tPostgresqlInput" uniqueName="tPostgresqlInput_1">`** — a component
  instance. Key attributes are `componentName` and `uniqueName` (connections reference nodes by
  `uniqueName`).
- **`<elementParameter name="..." value="..." field="...">`** — the component's config, one entry
  per property. The parser reads these keys (with common aliases):
  - table: `TABLENAME` (or `TABLE`); schema: `SCHEMA_DB` (or `SCHEMA`); connection: `CONNECTION`
    (or `DBNAME`)
  - custom SQL: `QUERY` (or `QUERYSTORE`)
  - filter condition (tFilterRow): `CONDITION` (or `CONDITIONS`)
  - tMap join model: `JOIN_MODEL` (e.g. `LEFT_OUTER`); lookup match model: `lookupMode` /
    `MATCHING_MODE`
  - aggregate (tAggregateRow): `GROUP_BY`, plus indexed `OPERATIONS.INPUT_COLUMN.n`,
    `OPERATIONS.FUNCTION.n`, `OPERATIONS.OUTPUT_COLUMN.n`
  - dedup keys (tUniqRow): `KEY_ATTRIBUTE`
  - called job (tRunJob): `PROCESS`
- **`<metadata name="..." connector="FLOW">`** with `<column name="..." type="id_Integer" ...>`
  children — the component's schema. Column attributes: `name`, `type` (Talend types:
  `id_Integer`, `id_String`, `id_Date`, `id_BigDecimal`, `id_Boolean`, …), `length`, `precision`,
  `nullable`, `key`. A `connector="REJECT"` metadata block is a reject flow (usually skip).
- **`<connection connectorName="FLOW" label="orders" source="tPostgresqlInput_1" target="tMap_1"/>`**
  — an edge. `connectorName` values:
  - `FLOW` (also `MAIN`) — the main data flow (a DAG edge to translate).
  - `LOOKUP` — a lookup input into a tMap (becomes a join, not a linear step).
  - `ON_SUBJOB_OK` / `ON_COMPONENT_OK` / `RUN_IF` — **trigger/orchestration** edges, not data
    flow. These express run order, not column lineage — map them to dbt DAG ordering / scheduling,
    not to a join.
- **`<context name="Default">`** with `<contextParameter name="db_host" type="id_String"
  value="localhost"/>` — job parameters. Map `context.X` references to dbt `var()` / `env_var()`;
  never inline secrets.

## Where each component keeps its logic

- **tMap** — logic is in a nested `<nodeData>`:
  - `<inputTables name="orders"/>` and `<inputTables name="items" lookupMode="LOAD_ONCE">` — the
    main input and the lookup input(s). Join keys are `<mapperTableEntries name="order_id"
    expression="orders.order_id"/>` inside a lookup `inputTables`.
  - `<outputTables name="enriched_orders">` with `<mapperTableEntries name="..." expression="..."
    type="id_..."/>` — the output columns and their expressions. Filter/var entries also appear
    here. Input tables themselves are inferred from the incoming FLOW/LOOKUP connections.
- **tAggregateRow** — `GROUP_BY` + the indexed `OPERATIONS.*` params (input col, function, output
  col) listed above.
- **tFilterRow** — the `CONDITION`/`CONDITIONS` elementParameter.
- **tUniqRow** — the `KEY_ATTRIBUTE` elementParameter (dedup keys).
- **tDBInput/Output** — `TABLENAME` + `SCHEMA_DB` (+ `QUERY` when a custom query is used).

## Building the inventory + data-flow graph

1. Count every `<node>` across all jobs → the **total unit count** (coverage denominator).
2. Build each job's DAG from `FLOW`/`MAIN` connections; attach `LOOKUP` inputs to their tMap as
   joins. Treat `ON_SUBJOB_OK`/`ON_COMPONENT_OK`/`RUN_IF` as ordering only. Collapse passthrough/
   logging components (tSortRow, tLogRow) into their parent.
3. Add cross-job edges from `tRunJob` (the `PROCESS` param names the called job).
4. Hand the inventory to Step 2 (classification) and each component's logic to Step 3
   ([talend-component-mapping.md](talend-component-mapping.md)).

> **Caveat:** the demo fixtures are simplified/hand-authored `.item` files. Real Talend Studio
> exports are more verbose (namespaced, many more `elementParameter` entries, richer connection
> attributes), but they use the same core elements — `node`/`elementParameter`/`metadata`/
> `connection`/`nodeData` — and the parser already handles the common param aliases noted above.
> If you hit an unfamiliar `componentName` or param, inventory it and, if it has no clear SQL
> mapping, route it to the residual for human review rather than guessing.
