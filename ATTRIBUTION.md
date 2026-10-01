# Attribution - third-party content

## datavault4dbt (Scalefree)

The Data Vault generation reference
(`skills/legacy-to-dbt-migration-foundations/references/building-datavault.md`) is **distilled from**
Scalefree's **datavault4dbt agent skills** - the staging-driven hub/link/satellite pattern, entity
choice, project layout/materializations, and technical tests.

- Source: https://github.com/ScalefreeCOM/datavault4dbt-agent-skills
- Author: Scalefree International GmbH
- License: Apache License 2.0

The reference is a condensed, rewritten summary (not a verbatim copy) that credits Scalefree and
points to their full skill set and the `datavault4dbt` package docs for deeper coverage (all
satellite variants, PIT cleanup, rehashing, per-adapter config, troubleshooting). The
`datavault4dbt` dbt **package** it describes is Apache-2.0 and installed on demand into the target
project's `packages.yml` at migration time - it is not redistributed here.

## Coalesce harbor fixture format (0nmus/coalesce-demo)

The Coalesce end-to-end eval fixture
(`harbor/migrate-coalesce-to-dbt/environment/app/legacy/nodes/*.yml`) is **authored, not copied**.
Its file/field structure (top-level `type: Node`, `operation.sqlType`, `metadata.columns[]` with
`isBusinessKey`/`isSurrogateKey`/`isChangeTracking` and `sourceColumnReferences[].columnReferences[].stepCounter`)
was verified against the public reference project below to ensure the parser exercises a realistic
Coalesce Git export. The referenced repo carries no license file, so **none of its files are
redistributed** - the fixture is an independently-written TPC-H slice.

- Reference: https://github.com/0nmus/coalesce-demo (public; no license file - used only to verify format)

## Matillion harbor fixture (build_sales_marts pipeline)

The Matillion end-to-end eval fixture
(`harbor/migrate-matillion-to-dbt/environment/app/legacy/build_sales_marts.tran.yaml`) is authored
by the repo owner, grounded in the Matillion Data Productivity Cloud `.tran.yaml` export format.

## DataStage parser + eval fixture (.dsx format)

The `migrating-datastage-to-dbt` parser (`inventory_datastage.py`) and the eval fixture
(`evals/fixtures/datastage/orders_enrich.dsx`) are **authored, not copied**. The DSX text format
(`BEGIN/END HEADER`, `DSJOB`, `DSRECORD`, `DSSUBRECORD`; `CContainerView`'s pipe-delimited
`StageList`/`StageTypeIDs`/`StageNames`; per-stage `InputPins`/`OutputPins`; per-pin `Partner`
links) was verified against real exported `.dsx` files found in two public repos, neither of which
carries a license file, so **none of their files are redistributed** here:

- https://github.com/fernandokarnagi/ibm-datastage-javaintegration-sample (public; no license file -
  a genuine IBM InfoSphere DataStage 8.7 export, used to confirm the base grammar and the
  custom/debug/I-O stage shapes)
- https://github.com/isobina/DataStageJobs (public; no license file - a broader set of jobs used to
  exercise additional stage-type coverage: Join, Filter, Aggregate, Sort, Remove Duplicates,
  Lookup, Merge, Funnel, Pivot, Surrogate Key, Change Capture/CDC. This set's own provenance as a
  captured production export is unconfirmed - treat its exact stage-type spellings as a second,
  lower-confidence source alongside IBM's documentation, not as verified-production ground truth)

This repository is licensed Apache-2.0 (see [LICENSE](LICENSE)).
