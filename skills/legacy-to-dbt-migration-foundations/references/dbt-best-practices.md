# dbt best practices: SQL, tests, docs, contracts, snapshots (Step 4)

Every migrated model must ship Fusion-conformant SQL, tests, docs, and (for public marts)
contracts. Sourced from the `SCHEMA_WRITER_SYSTEM` prompt in `a proven Talend→dbt schema/test-generation prompt`
and the governance assets in `an Oracle→Databricks migration project` (`_marts.yml`, `groups.yml`, `exposures.yml`).

**Use packages, don't hand-type** (see [dbt-packages.md](dbt-packages.md)): scaffold the YAML with
**codegen** (`generate_model_yaml`, `generate_source`), then enrich it; add generic tests from
**dbt_utils** and Great-Expectations-style tests from **dbt_expectations** (`metaplane/dbt_expectations`)
on top of the built-ins; and run **dbt_project_evaluator** as the post-migration quality gate (it
flags undocumented/untested models, bad structure, and fanout).

## Contents

- [Fusion-conformant SQL rules](#fusion-conformant-sql-rules)
- [Tests](#tests)
- [Docs](#docs)
- [Contracts](#contracts)
- [Snapshots for SCD2](#snapshots-for-scd2)

## Fusion-conformant SQL rules

1. `cast(x as <type>)` only — **never** `x::type`.
2. `coalesce()` — never `nvl()`, `ifnull()`, `nvl2()`.
3. Standard SQL functions only; no platform-specific syntax in model bodies (platform tuning goes
   in `config()`, not the SQL).
4. Wrap logic in CTEs; name the final CTE `final`; last line `select * from final`.
5. Use `{{ ref('model') }}` for upstream models and `{{ source('schema','table') }}` for raw tables.
   No hard-coded database.schema.table references.
6. No DDL in models — no `CREATE TABLE`/`CREATE VIEW`/`INSERT INTO` (dbt owns materialization).
7. `require-dbt-version: [">=1.9.0"]` in `dbt_project.yml`; no `config-version:` key.

## Tests

Per the [dbt docs](https://docs.getdbt.com/docs/build/data-tests), there are two kinds — **generic**
(parameterized, referenced by name; "should make up the bulk of your testing suite") and **singular**
(a `.sql` query returning failing rows). dbt ships **four** built-in generic tests: `unique`,
`not_null`, `accepted_values`, `relationships`. Declare them under the **`data_tests:`** key (the
current name; `tests:` still works as an alias).

Generate a `_<group>_models.yml` (or per-model YAML) alongside each model with:
- `unique` + `not_null` on the grain (primary key).
- `not_null` on obviously required columns (status, email, amount, keys).
- `accepted_values` on low-cardinality columns (status, type, method, country).
- `relationships` from foreign keys to the referenced model.

**Test-argument syntax — mind the version.** The nested **`arguments:`** key is documented as
available in **dbt v1.10.5+ (and Fusion)**; older projects put the args (`values:`, `to:`, `field:`)
**directly** under the test with no `arguments:` layer. These skills target Fusion, so use
`arguments:` — but if a project is on an older dbt, drop the `arguments:` nesting.

```yaml
models:
  - name: fct_sales
    description: One row per completed sales order line, with margin and FX-adjusted amounts.
    columns:
      - name: sales_key
        description: Surrogate key for the sales fact grain.
        data_tests:
          - unique
          - not_null
      - name: order_status
        description: Order lifecycle status.
        data_tests:
          - accepted_values:
              arguments:
                values: ['completed', 'cancelled', 'returned']
      - name: customer_key
        description: FK to dim_customer.
        data_tests:
          - relationships:
              arguments:
                to: ref('dim_customer')
                field: customer_key
```

For **golden-dataset / logic-preservation** tests, generate dbt **unit tests** on the leaf/mart
models — capture 2-3 representative rows on the legacy output as expected values. See
[dbt-features-for-migration.md](dbt-features-for-migration.md#unit-tests--pin-the-migrated-logic)
for the docs-grounded syntax and the `adding-dbt-unit-test` skill for authoring detail; do not
duplicate its guidance here.

Also capture the legacy job's **downstream consumers** (dashboards, reports, ML pipelines) as
**exposures** so lineage-to-consumers survives the migration and you know what not to break —
see [dbt-features-for-migration.md](dbt-features-for-migration.md#exposures--preserve-downstream-lineage).

## Docs

- Model-level `description:` — 1-2 sentences: what the entity is and its grain.
- A `description:` for **every** column — infer meaning from the SQL and the legacy mapping.
- Prefer describing the grain explicitly ("one row per …") — it makes the unique test self-evident.

## Contracts

For public marts (especially in a Mesh producer), enforce a contract so column names/types are a
stable API and parity is pre-wired:

```yaml
models:
  - name: fct_sales
    access: public
    config:
      contract: {enforced: true}
    columns:
      - name: sales_key
        data_type: string
      - name: net_amount
        data_type: decimal(18,2)   # translate legacy NUMBER(18,2) / VARCHAR2 etc. to platform types
```

Per the [model-contracts docs](https://docs.getdbt.com/docs/mesh/govern/model-contracts): with
`contract: {enforced: true}` the contract **must list every column's `name` and `data_type`** (all
columns, not a subset). dbt runs a preflight check that the built columns match (names + types) and
bakes the names/types/constraints into the DDL. Column-level `constraints` (e.g. `not_null`) require
the model be materialized as `table` or `incremental` (not `view`/`ephemeral`), and most platforms
enforce only `not_null`. Contracts define the **shape** of the output — recommended for public
models others depend on.

Use `groups.yml` to assign ownership and `exposures.yml` to record downstream BI/consumers when
they exist in the legacy lineage. Version public marts (`versions:`) when the legacy contract may
change.

## Sources (dbt docs)

- [Materializations](https://docs.getdbt.com/docs/build/materializations) ·
  [Incremental models](https://docs.getdbt.com/docs/build/incremental-models) ·
  [Incremental strategies](https://docs.getdbt.com/docs/build/incremental-strategy)
- [Snapshots](https://docs.getdbt.com/docs/build/snapshots) ·
  [Data tests](https://docs.getdbt.com/docs/build/data-tests) ·
  [Model contracts](https://docs.getdbt.com/docs/mesh/govern/model-contracts)
- [How we structure our dbt projects](https://docs.getdbt.com/best-practices/how-we-structure/1-guide-overview)

## Snapshots for SCD2

Any legacy pattern that preserves history (Informatica Update Strategy SCD2, effective/expiry
dates + current flag, insert-new-expire-old) migrates to a **dbt snapshot**, not a model:

Per the [snapshots docs](https://docs.getdbt.com/docs/build/snapshots), configure snapshots in
**YAML** (the `{% snapshot %}` SQL block is legacy, v1.8 and earlier); files may live in the
`models/` or a `snapshots/` directory (a separate schema is recommended). dbt **recommends the
`timestamp` strategy** when the source has a reliable `updated_at` column (it handles column
add/drop more efficiently and tracks one column); use `check` (with an enumerated `check_cols`, not
`'all'`) only when there's no trustworthy timestamp.

```yaml
snapshots:
  - name: dim_customer_snapshot
    relation: ref('stg_customers')
    config:
      unique_key: customer_id
      strategy: timestamp          # preferred when a reliable updated_at exists
      updated_at: updated_at
      # strategy: check            # fall back to this when there's no reliable timestamp
      # check_cols: [customer_name, address, segment]
```

Do not hand-build effective/expiry columns in a model — the snapshot manages `dbt_valid_from` /
`dbt_valid_to` / current-row logic for you (v1.9+ adds `hard_deletes` and `dbt_valid_to_current`).
