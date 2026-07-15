# dbt features that make a migration great

Beyond building models, dbt has features that make a migration **more trustworthy** — pinning the
migrated logic, preserving downstream lineage, and catching stale inputs. All grounded in the dbt
docs (linked). Use these alongside the parity validation and coverage steps.

## Contents

- [Unit tests — pin the migrated logic](#unit-tests--pin-the-migrated-logic)
- [Exposures — preserve downstream lineage](#exposures--preserve-downstream-lineage)
- [Source freshness — rule out stale inputs](#source-freshness--rule-out-stale-inputs)

## Unit tests — pin the migrated logic

Data parity (Step 5) checks the **data**; **unit tests** check the **logic** on fixed inputs,
without touching prod. dbt docs: *"Unit tests allow you to validate your SQL modeling logic on a
small set of static inputs before you materialize your full model in production."* For a migration
this is gold — encode "this CASE / join / aggregation reproduces the legacy rule" as a fast,
warehouse-light assertion that can't silently drift. (dbt **v1.8+**; the `test_type:unit` selector
works on Core and Fusion.)

Author them at **Step 4** for the models carrying real transformation logic (a mart's segmentation
`case`, a fan-out-prone join, the SCD change-detection). Mock each upstream `ref()`/`source()`;
capture 2-3 representative rows — including a legacy edge case — as expected output:

```yaml
unit_tests:
  - name: test_ltv_segment_thresholds
    model: mart_customer_ltv
    given:
      - input: ref('int_customer_order_summary')
        format: dict
        rows:
          - {customer_id: 1, lifetime_value: 150}
          - {customer_id: 2, lifetime_value: 20}
    expect:
      format: dict
      rows:
        - {customer_id: 1, ltv_segment: 'high'}
        - {customer_id: 2, ltv_segment: 'low'}
```

Formats: `dict` (default), `csv`, `sql` (ephemeral inputs must use `sql`); fixtures live in a
`fixtures/` subdir of a test path. Run: `dbt test --select "test_type:unit"`, or per model
`dbt test --select "mart_customer_ltv,test_type:unit"`; `dbt build` runs unit tests → model → data
tests in lineage order. Use `--empty` to build empty parents cheaply. dbt Labs recommends running
unit tests **in dev/CI only** (static inputs — no prod compute). For authoring detail, hand off to
the `adding-dbt-unit-test` skill. Docs: <https://docs.getdbt.com/docs/build/unit-tests>.

## Exposures — preserve downstream lineage

The legacy job fed something — a dashboard, a report, an ML pipeline. Capture those as **exposures**
so the migrated project knows **what it must not break** and the lineage-to-consumers survives the
migration. dbt docs: *"Exposures make it possible to define and describe a downstream use of your
dbt project, such as in a dashboard, application, or data science pipeline."*

Identify consumers at **Step 1** (inventory — the legacy workflow's final targets/reports) and
declare them at **Step 4**, under an `exposures:` key in a `.yml` under `models/`:

```yaml
exposures:
  - name: weekly_sales_dashboard
    type: dashboard                # dashboard | notebook | analysis | ml | application
    maturity: high                 # high | medium | low
    url: https://bi.tool/dashboards/42
    description: "The exec sales dashboard the legacy nightly job fed."
    depends_on:
      - ref('fct_sales')
      - ref('dim_customer')
    owner:
      name: Data Team
      email: data@company.com
```

`name`, `type`, and `owner` (name or email) are required; `depends_on` lists refable nodes. Select
the exposure and everything feeding it: `dbt build -s +exposure:weekly_sales_dashboard` (or
`run`/`test`). In v1.10+, `tags`/`meta`/`enabled` nest under a `config:` block. Docs:
<https://docs.getdbt.com/docs/build/exposures>.

## Source freshness — rule out stale inputs

In Step 5 a "difference" is often just **stale input**, not a logic bug. Declaring source
**freshness** lets you rule that out and gives the migrated pipeline an SLA signal. dbt docs: *"dbt
can optionally capture the 'freshness' of the data in your source tables… a critical component of
defining SLAs."*

Add it to the `sources` you declared at Step 1. **As of dbt v1.9 `freshness` nests under `config:`,
and v1.10 moves `loaded_at_field` under `config:` too** — these skills target Fusion, so use the
nested form (drop the `config:` wrapper only for dbt Core < 1.9):

```yaml
sources:
  - name: raw
    database: raw
    config:
      freshness:                     # changed to config in v1.9
        warn_after: {count: 12, period: hour}
        error_after: {count: 24, period: hour}
      loaded_at_field: _etl_loaded_at   # changed to config in v1.10
    tables:
      - name: orders
        config:
          freshness:                 # per-table override
            warn_after: {count: 6, period: hour}
      - name: product_skus
        config:
          freshness: null            # exclude this table from freshness checks
```

`warn_after`/`error_after` each take `count` (positive int) + `period` (`minute`/`hour`/`day`); give
one or both or dbt skips the check. Run `dbt source freshness`; then build only what's downstream of
refreshed sources with `dbt build --select source_status:fresher+`. Some adapters (Snowflake,
Redshift, BigQuery, Databricks/Fusion) can use warehouse metadata instead of a `loaded_at_field`.
Docs: <https://docs.getdbt.com/docs/build/sources> ·
<https://docs.getdbt.com/reference/resource-properties/freshness>.
