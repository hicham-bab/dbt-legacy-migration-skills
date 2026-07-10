# dbt best practices: SQL, tests, docs, contracts, snapshots (Step 4)

Every migrated model must ship Fusion-conformant SQL, tests, docs, and (for public marts)
contracts. Sourced from the `SCHEMA_WRITER_SYSTEM` prompt in `~/talend-to-dbt/.../generation/prompts.py`
and the governance assets in `~/dbt-oracle-to-databricks/` (`_marts.yml`, `groups.yml`, `exposures.yml`).

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

Generate a `_<group>_models.yml` (or per-model YAML) alongside each model. Use the **Fusion
`arguments:` nested spec** for parameterized tests.

- `unique` + `not_null` on the grain (primary key).
- `not_null` on obviously required columns (status, email, amount, keys).
- `accepted_values` on low-cardinality columns (status, type, method, country).
- `relationships` from foreign keys to the referenced model.

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
models — capture 2-3 representative rows on the legacy output as expected values. Follow the
`adding-dbt-unit-test` skill for authoring detail; do not duplicate its guidance here.

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

Use `groups.yml` to assign ownership and `exposures.yml` to record downstream BI/consumers when
they exist in the legacy lineage. Version public marts (`versions:`) when the legacy contract may
change.

## Snapshots for SCD2

Any legacy pattern that preserves history (Informatica Update Strategy SCD2, effective/expiry
dates + current flag, insert-new-expire-old) migrates to a **dbt snapshot**, not a model:

```yaml
snapshots:
  - name: dim_customer_snapshot
    relation: ref('stg_customers')
    config:
      unique_key: customer_id
      strategy: check
      check_cols: [customer_name, address, segment]
```

Do not hand-build effective/expiry columns in a model — the snapshot manages `dbt_valid_from` /
`dbt_valid_to` / current-row logic for you.
