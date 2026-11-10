# dbt best practices: SQL, tests, docs, contracts, snapshots (Step 4)

Every migrated model must ship Fusion-conformant SQL, tests, docs, and (for the marts inside
the manifest's `contract_boundary`) contracts. Grounded in the [dbt documentation](https://docs.getdbt.com/best-practices) and in
patterns from prior legacy-to-dbt migrations; the governance assets referred to below
(`_marts.yml`, `groups.yml`, `exposures.yml`) are described here in full and do not ship as
fixtures with this skill.

**Use packages, don't hand-type** (see [dbt-packages.md](dbt-packages.md)): scaffold the YAML with
**codegen** (`generate_model_yaml`, `generate_source`), then enrich it; add generic tests from
**dbt_utils** and Great-Expectations-style tests from **dbt_expectations** (`metaplane/dbt_expectations`)
on top of the built-ins; and run **dbt_project_evaluator** as the post-migration quality gate (it
flags undocumented/untested models, bad structure, and fanout).

## Contents

- [Fusion-conformant SQL rules](#fusion-conformant-sql-rules)
- [Fusion YAML gotchas](#fusion-yaml-gotchas)
- [Date-dependent logic](#date-dependent-logic)
- [Tests](#tests) (incl. the [minimum test floor](#minimum-test-floor-for-a-migration))
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

## Fusion YAML gotchas

Each of these was observed on dbt Fusion 2.0.11 and cost a failed compile or a build warning:

1. **Column-level `meta` goes under `config:`.** `meta:` directly on a column is rejected
   (`UnusedConfigKey`, dbt1060, reported as a compile error). Write
   `config: {meta: {pii: true}}`.
2. **Source tables take no `database:` or `schema:` key.** Those are set on the source. For tables
   in different databases or schemas, declare one source per location (for example `legacy_prod`,
   `legacy_prod_lnd`, `legacy_prod_temp`).
3. **Give every numeric cast an explicit precision.** `cast(x as number)` triggers a dbt1071 warning
   ("numeric type and unspecified precision/scale") at build time, not compile time. Use
   `number(38, 0)` for integers, and match the contract `data_type`. Compile alone will not show it,
   so the zero-warnings bar is checked on the first `dbt build` output too.

## Date-dependent logic

Replace every `current_date` / `current_timestamp` used in a business rule with a project macro
`as_of_date()` that returns `current_date` unless the `as_of_date` var (YYYY-MM-DD) is set. Unit
tests then pin the date with `overrides: vars: {as_of_date: "YYYY-MM-DD"}`. Repeated predicates (for
example a fiscal-year window) become one macro that calls `as_of_date()`. Default behaviour must
not change when the var is unset. Audit timestamps that record when a run happened stay as they are.

```jinja
{% macro as_of_date() -%}
    {%- if var('as_of_date', none) is not none -%}
        cast('{{ var("as_of_date") }}' as date)
    {%- else -%}
        current_date
    {%- endif -%}
{%- endmacro %}
```

This macro was verified on Snowflake only; compile it against the connected adapter before relying
on it elsewhere (see [warehouse-conformance.md](warehouse-conformance.md)). The check: no bare
`current_date` remains in model SQL outside audit columns, and every unit test on a date-windowed
model sets `as_of_date`.

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

### Minimum test floor for a migration

Every migrated project ships at least:

1. **Grain and keys.** `unique` + `not_null` (or `dbt_utils.unique_combination_of_columns`) on the
   grain of every mart and every staging lookup. If no grain exists, state that in the model
   description and add a `warn`-level grain test.
2. **Closed code sets.** `accepted_values` on every column whose legacy logic enumerates its values
   (for example a list of validated columns or categories).
3. **Unit tests.** At least one `unit_tests:` entry for every model that contains any of: a `case`
   with 3 or more branches, a join that is not a plain key equality, a window function, regex,
   or date arithmetic. Each unit test includes at least one edge case taken from the legacy export
   (null input, excluded category, boundary date, duplicate row).
4. **Joins without a condition or on a non-key.** Every cross join, `on 1 = 1`, or non-key join
   gets a `warn`-level singular test asserting the expected grain, and is listed under Residual.
5. **Cross-model invariants.** One singular test per invariant the legacy logic implies, for
   example "every record rejected by validation appears in the error log" and "no rejected record
   reaches the valid output".
6. **Contracts** on the marts inside the manifest's `contract_boundary`: every column typed, numeric
   columns with explicit precision and scale.

Record a table in `migration_changes.md` under a `## Test coverage` heading, one row per model:
model, generic tests, unit tests, singular tests, and a reason for any model with none. A model
that matches item 3 but needs no unit test (for example a `row_number()` already pinned by a grain
test) is covered by a reason in this table; never write a placeholder unit test to satisfy the
check.

**Checking the floor.** Where Python runs, use the advisory gate:

```bash
python3 <skills-dir>/legacy-to-dbt-migration-foundations/scripts/preflight_decisions.py tests \
        --manifest target/manifest.json --changes migration_changes.md --file migration_manifest.yml
```

It needs a current `target/manifest.json` (run `dbt parse` or, better, `dbt compile` first, so
SQL generated by macros is checked too; a parse-only manifest has no compiled SQL). With the dbt
platform CLI, the manifest is downloaded to `target/` after each command that parses the project.
If it is missing, check the CLI setting that skips artifact downloads and any `target-path`
override. That downloaded manifest is a copy of one invocation, not production state, so never use
it as `--state` for deferral. It reports marts without a grain test, marts inside
`contract_boundary` without an enforced contract, models missing from the coverage table, and
models whose SQL looks like item 3 (found by pattern matching, so it can be wrong both ways) with
neither a unit test nor a reason. It warns only; `--strict` makes gaps fail.

**When the script cannot be run** — on the dbt platform, with no shell, or with `python3` not
found (see foundations SKILL.md, "Choosing the path"; a non-zero exit or a missing
`target/manifest.json` is a gate result to fix, not a reason to skip) — still check items 1-6
against each model yourself, then **give the migrator this warning**, in the message and in
`migration_changes.md`:

> **The automated test-floor check did not run.**
>
> - **Why:** `preflight_decisions.py tests` needs Python, which is not available here.
> - **Risk:** a model with business logic and no unit test, a mart with no grain test, or a mart
>   missing its contract can go unnoticed. A changed rule, duplicated rows, or a broken column
>   for downstream consumers would then surface only after deployment.
> - **Please check by hand,** in the Test coverage table in `migration_changes.md`:
>   - every model has a row;
>   - every mart has a `unique` (or `unique_combination_of_columns`) test;
>   - every mart inside `contract_boundary` has an enforced contract;
>   - every model with a 3+ branch `case`, a window function, a non-key join, regex, or date
>     arithmetic has a unit test or a stated reason.
> - **Automatic on the CLI:** when the migration runs from the CLI on a machine with Python, the
>   skill runs this check automatically at Step 4. Running `preflight_decisions.py tests` there
>   once before cutover confirms the hand check.

## Docs

- Model-level `description:` — 1-2 sentences: what the entity is and its grain.
- A `description:` for **every** column — infer meaning from the SQL and the legacy mapping.
- Prefer describing the grain explicitly ("one row per …") — it makes the unique test self-evident.

## Contracts

Enforce a contract on every mart inside the manifest's `contract_boundary`, so column names/types
are a stable API and parity is pre-wired.

**Choosing `contract_boundary` (Step 0, the migrator decides).** Recommend from who reads the marts:

| Answer | Contracts on | Recommend when |
|---|---|---|
| `all_marts` | every mart | the legacy output tables are read outside dbt (BI, extracts, other teams). This is the usual case when replacing a legacy tool, so it is the default recommendation. |
| `public_marts` | only marts with `access: public` | a dbt Mesh split, or a few marts clearly shared while the rest are internal to the project |
| `none` | no mart | throwaway or prototype work only. Say that consumers then get no build-time protection against a changed column or type. |

The types come from `inputs.legacy_target_ddl_path` when supplied (the legacy table is the shape
consumers already depend on), otherwise from the warehouse catalog. With neither, say the contract
types are inferred and list them for the migrator to confirm.

```yaml
models:
  - name: fct_sales
    access: public
    config:
      contract: {enforced: true}
    columns:
      - name: sales_key
        data_type: string       # ILLUSTRATIVE ONLY - use the connected adapter's type name
      - name: net_amount
        data_type: decimal(18,2) # e.g. number(18,2) on Snowflake, numeric on BigQuery/Redshift
```

> **The `data_type` values above are illustrative (Databricks/BigQuery-flavored), not portable.**
> `string` vs `varchar` vs `number` vs `int64` differ by warehouse, and an enforced contract's
> preflight **fails** on a type the target does not accept. Use the customer's **connected adapter's**
> type names and let `dbt compile` confirm them - the connected-adapter compile is the source of
> truth, not this example. See [warehouse-conformance.md](warehouse-conformance.md) for the per-adapter
> orientation table and why compiling on the real adapter is the conformance gate.

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
dates + current flag, insert-new-expire-old) needs a history-capture pattern. A **dbt snapshot** is
the default shown below, but snapshot vs incremental-merge model vs the hybrid (snapshot capture +
model on top) is a real tradeoff on compute, lineage, and debugging that applies across every
modeling approach. Decide with [scd-history-strategies.md](scd-history-strategies.md); the default
for most migrations is the **hybrid** (thin snapshot, then a dimension model on `ref()` of it).

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

When you use a snapshot, let it manage `dbt_valid_from` / `dbt_valid_to` / current-row logic
(v1.9+ adds `hard_deletes` and `dbt_valid_to_current`) rather than hand-building those columns.
Hand-build history in an incremental model only when [scd-history-strategies.md](scd-history-strategies.md)
calls for it (large tables with a CDC predicate, Type-4 / custom effective-dating, unit-tested logic).
