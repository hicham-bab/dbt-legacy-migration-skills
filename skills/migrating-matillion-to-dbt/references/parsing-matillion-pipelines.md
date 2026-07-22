# Parsing Matillion pipelines/jobs (Step 1)

Matillion workflows come in several forms across two product generations and multiple export
mechanisms. This reference covers **all** of them. Structure below is grounded in Matillion docs
and **real exported files** (DPC YAML and METL JSON verified from public repos; sample METL files
live in `real Matillion ETL JSON exports`).

## Contents

- [Step 0: identify the form](#step-0-identify-the-form)
- [Acquiring the artifact](#acquiring-the-artifact)
- [DPC — Data Productivity Cloud YAML](#dpc--data-productivity-cloud-yaml)
- [METL — Matillion ETL JSON](#metl--matillion-etl-json)
- [CDC / Streaming pipelines](#cdc--streaming-pipelines)
- [Shared Jobs, sub-pipelines & custom connectors](#shared-jobs-sub-pipelines--custom-connectors)
- [Transformation vs orchestration (both products)](#transformation-vs-orchestration-both-products)
- [Building the inventory + data-flow graph](#building-the-inventory--data-flow-graph)

## Step 0: identify the form

Before parsing, determine which of these you have — the structure differs sharply:

| Form | How to recognize | Section |
|---|---|---|
| **DPC pipeline (YAML)** | files `*.tran.yaml` / `*.orch.yaml`; top-level `type`/`version`/`pipeline`/`design` | [DPC YAML](#dpc--data-productivity-cloud-yaml) |
| **METL export (JSON)** | `.json` with top-level keys `jobsTree`, `orchestrationJobs`, `transformationJobs`, `variables`, `environments` | [METL JSON](#metl--matillion-etl-json) |
| **METL Git per-job** | files `<Name>.ORCHESTRATION` / `<Name>.TRANSFORMATION`; top-level `{ "job": {...}, "info": {...} }` | [METL JSON](#metl--matillion-etl-json) |
| **CDC / Streaming** | no design-time file — a managed configuration in the DPC UI | [CDC / Streaming](#cdc--streaming-pipelines) |
| **Shared Job (METL)** | `.melt` bundle; appears as a single palette component with a numeric id | [Shared Jobs](#shared-jobs-sub-pipelines--custom-connectors) |

Glob for `*.tran.yaml`, `*.orch.yaml`, `*.json`, `*.ORCHESTRATION`, `*.TRANSFORMATION`, `*.melt`.

## Acquiring the artifact

If the user hasn't handed you a file, these are the ways to get one (prefer Git — most reliable):
- **Git integration** (best): DPC Designer commits `.orch.yaml`/`.tran.yaml`; METL commits per-job
  `.ORCHESTRATION`/`.TRANSFORMATION`. Clone the repo.
- **UI export**: METL → Project → Export → one JSON file (multiple jobs). DPC → export YAML.
- **REST API v1** (METL): `GET /rest/v1/group/name/<g>/project/name/<p>/job/name/<j>/export` (one job)
  or `.../project/name/<p>/export` (whole project incl. variables/environments/schedules). Returns
  JSON; passwords are excluded.
- Not recommended: METL's internal metadata Postgres DB (no supported schema for extraction).

Never read/echo credentials; note that v1 exports and DPC exports already exclude
secrets/OAuths, and METL variable exports carry names only.

## DPC — Data Productivity Cloud YAML

Top-level keys: `type` (`"orchestration"` | `"transformation"`), `version`, `pipeline`, `design`.
`pipeline.components` is a **map keyed by the human component name**; each has a kebab-case `type`
(e.g. `table-input`, `calculator`, `join`, `rewrite-table`, `s3-load`, `create-table`), a
`parameters` block, and links:
- **Transformation**: `sources:` — array of **upstream** component names (data-flow DAG → dbt `ref()`).
- **Orchestration**: `transitions:` with `success:` / `failure:` / `unconditional:` arrays of
  **downstream** names (control flow).

```yaml
type: "transformation"
pipeline:
  components:
    Enrich:
      type: "calculator"
      sources: ["Read raw orders"]          # data-flow edge
      parameters: { calculations: [...] }
    Write fct_orders:
      type: "rewrite-table"
      sources: ["Enrich"]
      parameters: { targetTable: "fct_orders", warehouse/database/schema: ... }
design:
  components: { <name>: { position: {x,y}, tempMetlId: N } }
```

`design` is canvas-only (positions, `tempMetlId`, `notes`) — ignore for logic. Scripts (SQL /
Python) are stored inline as string parameter values.

## METL — Matillion ETL JSON

**Three artifact shapes, one common job body** — detect by top-level keys (the export format varies
by METL version):
- **Export, newer (~v1.75.x)** — top-level `jobsTree`, `orchestrationJobs` (list),
  `transformationJobs` (list), `variables`, `environments`. Job type = which array it's in (the
  `jobsTree` registry also carries `type` `ORCHESTRATION`/`TRANSFORMATION` per job, nested via `children`).
- **Export, older (~v1.67.x)** — top-level `objects` (list), `version`, `environment`. Each entry
  is `{ "jobObject": {<job body>}, "info": {...}, "path": [...] }`.
- **Git per-job file** (`<Name>.ORCHESTRATION` / `.TRANSFORMATION`) — top-level
  `{ "job": {<job body>}, "info": {...} }`.

**Determining a job's type** (works across all three): read `info.type`
(`"ORCHESTRATION"`/`"TRANSFORMATION"`) or the job body's `JobType`
(`".OrchestrationJob"`/`".TransformationJob"`) — normalize by matching `tran`/`orch`. As a fallback,
a body with a single `connectors` map and no `successConnectors` is a transformation job.

**Job body:**
- `components` — a **map keyed by numeric component id** (as a string).
- **Orchestration** connectors: job-level maps `successConnectors`, `failureConnectors`,
  `unconditionalConnectors`, `trueConnectors`, `falseConnectors`, `iterationConnectors`, each keyed
  by connector id with shape `{ "id":N, "sourceID":N, "targetID":N }`. Components reference them via
  `outputSuccessConnectorIDs`, `outputFailureConnectorIDs`, `outputUnconditionalConnectorIDs`,
  `outputTrueConnectorIDs`, `outputFalseConnectorIDs`, `outputIterationConnectorIDs` /
  `inputIterationConnectorIDs`, plus generic `inputConnectorIDs`.
- **Transformation** connectors: a **single** job-level `connectors` map (same `{id,sourceID,targetID}`
  shape), components using generic `inputConnectorIDs` / `outputConnectorIDs`. No success/failure
  split — this is the data-flow DAG (the METL equivalent of DPC `sources:`).
- `variables` (map keyed by name: `{definition:{name,type,scope,visibility}, value}`),
  `grids` (map keyed by name: `{definition:{definitions:[{name,type}...], scope, visibility}, values:[rows]}`).

**Critical difference from DPC:** METL has **no kebab-case `type` string**. A component's type is
the numeric **`implementationID`** (can be negative). The human name is not a key — it's the first
parameter: `parameters["1"].elements["1"].values["1"].value`. Parameter values live at
`parameters[slot].elements[elem].values[val].value` (multi-`elements` = grid rows; multi-`values`
= columns). See [matillion-component-mapping.md](matillion-component-mapping.md#resolving-metl-implementationid)
for resolving `implementationID` → component.

```json
"components": {
  "8118": {
    "id": 8118, "implementationID": -359894709,          // -359894709 = Detect Changes
    "inputConnectorIDs": [8137, 8125], "outputConnectorIDs": [],
    "parameters": { "1": { "elements": { "1": { "values": { "1": { "value": "Detect Changes" }}}}} }
  }
}
"connectors": { "8137": { "id":8137, "sourceID":8061, "targetID":8118 } }   // data-flow edge
```

## CDC / Streaming pipelines

CDC (surfaced as **Streaming pipelines** in current DPC) is a **managed configuration, not an
exportable design file** — there is no `.cdc.yaml`. A capture agent reads the source DB's log and
lands change events (partitioned batches) in cloud storage (S3 / Blob).

**dbt mapping:** the capture itself is **ingestion → out of dbt scope** (like S3 Load). The
*migratable* part is the **downstream consumer** that turns landed change files/tables into
current-state — that maps to a dbt **snapshot** (SCD) or **incremental model** (merge on
primary key / op-type). If you only have the CDC config and no downstream transformation, there is
nothing to migrate into dbt; document it as an ingestion dependency feeding your `sources`.

## Shared Jobs, sub-pipelines & custom connectors

- **Shared Job (METL)** — a bundled reusable workflow that appears as one palette component with
  its own numeric `implementationID` (in migration mappings this is the `metlImplementationId`).
  Exported as a `.melt` bundle. → migrate the underlying job once as a **macro or a set of
  intermediate/`int_` models**, and `ref()` it from callers. (`.melt` internal structure is
  doc-sourced, not file-verified — inspect the actual bundle before trusting field names.)
- **Sub-pipelines (DPC)** — an orchestration/transformation invoked by a parent via Run
  Transformation / Run Orchestration. Recurse into it; it becomes part of the same dbt DAG.
- **Custom Connectors (DPC)** — user-defined API extract connectors. These are **ingestion →
  out of dbt scope**; map their output tables to `sources`.

## Transformation vs orchestration (both products)

Regardless of form, the same split governs what maps to dbt:
- **Transformation** (DPC `.tran.yaml` / METL transformation job) → dbt models. Every component is
  push-down SQL; the data-flow edges are the lineage. **These are the migratable units and the
  coverage denominator.**
- **Orchestration** (DPC `.orch.yaml` / METL orchestration job) → mostly out of dbt scope:
  data-load / connector / API / CDC components = EL ingestion → map to `sources`; `run-transformation`
  / Run Transformation → the dbt DAG/run; DDL / `if` / `and` / `retry` / iterators / scripts →
  run ordering + a scheduler/job (captured as notes, not modeled).

## Building the inventory + data-flow graph

1. Identify the form (Step 0) and, for a METL export, walk `jobsTree` to list every job with its
   type; for DPC, glob the YAML files.
2. Count every **transformation** component (across all transformation jobs/pipelines) → the
   coverage denominator. List orchestration EL/control-flow components separately (out of scope).
3. Build each transformation DAG:
   - DPC: from `sources:` edges.
   - METL: from the `connectors` map (`sourceID` → `targetID`), joined to components by id.
   Leaf `rewrite-table`/`table-output` (DPC) or the terminal write component (METL) = mart outputs.
4. Resolve component types: DPC `type` string directly; METL via `implementationID` +
   the `"Name"` parameter (see the mapping reference).
5. Cross-pipeline edges: a Table Input reading a table another pipeline's write produced = `ref()`;
   `run-transformation` / Run Transformation gives run order; Shared Job / sub-pipeline invocations
   = recurse.
6. Map variables (`${var}` in DPC; `variables`/`grids` maps in METL) → dbt `var()`/`env_var()`;
   grid variables + iterators → flag for deliberate re-modeling.
7. Hand the inventory to Step 2 (classification) and each component's parameters to Step 3
   ([matillion-component-mapping.md](matillion-component-mapping.md)).

> **Reference fixtures:** `example Matillion exports` holds hand-authored DPC YAML plus
> **real** METL JSON samples under `metl_samples/` (export form and a `.ORCHESTRATION` git-form
> file), and `test_parse.py` walks both DPC YAML and METL JSON using this reference's algorithm.
> Verify against the user's *actual* export early: if a component `type`/`implementationID` or
> parameter key is unfamiliar, inventory it and route anything without a clear SQL mapping to the
> residual for human review.
