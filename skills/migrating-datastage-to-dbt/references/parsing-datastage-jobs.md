# Parsing IBM DataStage jobs (Step 1)

IBM InfoSphere DataStage (now part of IBM Cloud Pak for Data / DataStage as a Service) exports jobs
as **DSX** (DataStage Interchange) files - a line-oriented text format, not XML or JSON. This
reference covers the grammar and how to build the inventory + data-flow graph from it. Grounded in
the DSX grammar verified against real exported files (see ATTRIBUTION.md) - the
`inventory_datastage.py` script implements this algorithm; reason over its `--json` output rather
than re-parsing by hand.

## Contents

- [Step 0: acquiring the artifact](#step-0-acquiring-the-artifact)
- [The DSX grammar](#the-dsx-grammar)
- [Jobs, stages, links](#jobs-stages-links)
- [Resolving a stage's type](#resolving-a-stages-type)
- [Job Sequences vs parallel ETL jobs](#job-sequences-vs-parallel-etl-jobs)
- [Shared containers](#shared-containers)
- [Building the inventory + data-flow graph](#building-the-inventory--data-flow-graph)

## Step 0: acquiring the artifact

If the migrator hasn't handed you a file, these are the ways to get one:
- **DataStage Designer**: right-click a job (or a whole folder/project) -> Export -> DataStage
  Components -> DSX format. A whole-project export concatenates every job into one `.dsx` file.
- **`dsexport` command-line** (Windows client): `dsexport.exe /H=host /U=user /P=pass /EXEC project
  output.dsx` to export the whole project, or name specific jobs.
- **`istool export`** (newer Information Server CLI): exports to `.isx` (a binary/archived form of
  the same content) - prefer DSX for a readable artifact; if only `.isx` is available, the migrator
  needs to re-export via Designer/`dsexport` as DSX, or you'll need `istool` to unpack it.

Glob for `*.dsx`/`*.DSX`. Never read/echo credentials; DSX exports do not carry connection
passwords (they're excluded or replaced by `/Connection/Reserved` placeholders).

## The DSX grammar

Everything is a nested `BEGIN <TAG> ... END <TAG>` block, indentation is cosmetic only:

```
BEGIN HEADER
   CharacterSet "UTF-8"
   ...
END HEADER
BEGIN DSJOB
   Identifier "Orders_Enrich"
   BEGIN DSRECORD
      Identifier "ROOT"
      OLEType "CJobDefn"
      ...
   END DSRECORD
   BEGIN DSRECORD
      ...
      BEGIN DSSUBRECORD
         Name "SomeProperty"
         Value "..."
      END DSSUBRECORD
   END DSRECORD
END DSJOB
```

- **`HEADER`**: export metadata (tool version, server, date) - informational only.
- **`DSJOB`**: one job. **A single `.dsx` file can contain many `DSJOB` blocks** (a whole-project
  export) - always iterate all of them, don't assume one job per file.
- **`DSRECORD`**: an object inside the job - the root job definition (`OLEType "CJobDefn"`), the
  canvas/stage-list record (`OLEType "CContainerView"`), each stage, and each stage's input/output
  link pins. Identified by a job-scoped `Identifier` (e.g. `V0`, `V0S0`, `V0S0P1`).
- **`DSSUBRECORD`**: nested metadata under a `DSRECORD` - stage properties (grouped under a
  `Properties "CCustomProperty"` marker) or column metadata (grouped under `Columns`).
- Scalar fields are `Key "value"` on one line. A few fields are multi-line blocks delimited by a
  trailing `=+=+=+=` marker on the key line and a lone `=+=+=+=` line closing it (used for things
  like embedded SQL or long XML property blobs) - treat the whole block as one opaque string value.

## Jobs, stages, links

Each job has exactly one `CContainerView` record (job-scoped `Identifier`, e.g. `V0`) that lists
**every stage on the canvas** via parallel pipe-delimited arrays, indexed by position:

```
StageList     "V0S0|V0S1|V0S2"
StageTypeIDs  "PxSequentialFile|CTransformerStage|PxSequentialFile"
StageNames    "ORDERS_RAW|FILTER_ENRICH|ORDERS_OUT"
```

`StageList[i]` is the stage's `Identifier` - look it up as its own `DSRECORD` to read its
`InputPins`/`OutputPins` (also pipe-delimited lists of pin identifiers). Each pin is **its own**
`DSRECORD` (`OLEType "CCustomInput"`/`"CCustomOutput"`) carrying a `Partner` field:

```
Partner "V0S3|V0S3P1"     # "<target stage id>|<target pin id>"
```

Resolve the target stage's `Identifier` to its `Name` to build a `(from stage, to stage, link name)`
edge - this is the job's data-flow DAG, directly analogous to Matillion's `sources:` or Informatica's
connector list. A stage with no `InputPins` and some `OutputPins` is a **source**; no `OutputPins`
and some `InputPins` is a **target**; both is pass-through/transform. A blank `StageTypeIDs` entry
(empty string between the pipes) is a **canvas annotation** (`ID_PALETTEANNOTATION`), not a stage -
skip it, it carries no ETL meaning.

A stage's own `Properties` (`DSSUBRECORD`s grouped under the `Properties "CCustomProperty"` marker)
carry its configuration - join keys, filter expressions, transformer derivations, column mappings.
Read these when translating (Step 3), not just for inventory.

## Resolving a stage's type

A stage `DSRECORD` carries a `StageType` field (matches the `CContainerView`'s `StageTypeIDs` entry
for it) - this is the authoritative type string, e.g. `PxJoin`, `PxFilter`, `CTransformerStage`,
`PxSequentialFile`, `JavaStagePX`. Unlike Matillion METL (numeric `implementationID`) or Informatica
(transformation `TYPE` attribute), DataStage's parallel-stage types are already a stable-ish
human-readable string with a `Px` (parallel) or `C` (server/common) prefix - map it directly via
[datastage-stage-mapping.md](datastage-stage-mapping.md). If a `StageType` is unfamiliar, inventory
it under `residual_stage_types` and route it to human review rather than guessing a mapping.

## Job Sequences vs parallel ETL jobs

DataStage has two job kinds that can appear in the same project export:
- **Parallel jobs** (`JobType "3"` or `"1"` depending on version) - the actual ETL/ELT workload;
  their `CContainerView` lists real `Px*`/`C*Stage` stages. **These are the migratable units.**
- **Job Sequences** (`JobType "2"`) - orchestration/control-flow (run this job, then that one, retry
  on failure, email on error) built from `Sequencer`/`Nested Condition`/`Job Activity` stages. These
  have **no recognized ETL stage types** in their `CContainerView`, so the parser's `is_etl_job`
  check (any stage classified as something other than `unknown`) naturally routes them to
  `needs_review_jobs`, excluded from the coverage denominator - same treatment as Matillion
  orchestration pipelines. Document the run order; don't try to model it.

`JobType` alone is not fully reliable across DataStage versions - the **stage-graph check is the
dependable signal**; treat `JobType` as a secondary hint.

## Shared containers

A **Shared Container** (reusable sub-graph, like a Matillion Shared Job or a Talend sub-job) appears
inlined into the parent job's `CContainerView` behind a `CSharedContainer`/`CLocalContainer`
`OLEType`, or is exported as its own small `.dsx` with a `BEGIN DSJOB` of its own depending on
export options. If you see a container-type stage whose own stage graph is empty in this file,
it's a shared container reference - locate and inventory its definition separately, then migrate it
**once** as a macro or a set of `int_` models and `ref()` it from every caller (same rule as
Matillion Shared Jobs / Talend joblets).

## Building the inventory + data-flow graph

1. Glob for `.dsx` files; each may hold multiple `DSJOB` blocks - inventory every one.
2. For each job, classify every `StageList` entry via the mapping reference; split into
   **transformation** stages (modeling, the coverage denominator) vs **I/O** stages (sources/targets)
   vs debug/passthrough (`PxPeek`, `PxHead`, `PxCopy` - drop, they exist for development/testing
   only) vs custom code (residual for human review).
3. Build the job's DAG from pin `Partner` links (stage id + pin id -> target stage + pin); resolve
   ids to names for a readable edge list.
4. Flag CDC/SCD stages (`PxChangeCapture`, `PxChangeApply`, a native SCD stage) -> snapshot
   candidates (see [datastage-stage-mapping.md](datastage-stage-mapping.md#cdcscd--dbt-snapshots)).
5. A job with no recognized stage type at all -> `needs_review_jobs` (likely a Job Sequence), excluded
   from the denominator.
6. Hand the inventory to Step 2 (classification into the chosen modeling approach) and each job's
   stage properties to Step 3 ([datastage-stage-mapping.md](datastage-stage-mapping.md)).

> **Reference fixture:** `evals/fixtures/datastage/orders_enrich.dsx` is a small hand-authored DSX
> job (two sources, a two-output Transformer, two targets) exercising the full grammar above; see
> ATTRIBUTION.md for the real exports it was verified against. Validate against the migrator's
> *actual* export early - a stage type or property shape you haven't seen should go to residual for
> human review, not a guessed mapping.
