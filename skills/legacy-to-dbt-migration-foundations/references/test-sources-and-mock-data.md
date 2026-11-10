# Test sources and mock data (Step 0, Steps 4-5)

A migration builds its dbt models against **source tables** and proves them against **legacy
outputs**. These are separate questions. A sandbox often has the first and not the second: the
source tables exist in dev, or can be stood in for, but the legacy production outputs are not
readable. The manifest records which case applies in `inputs.test_source_mode`:

| `test_source_mode` | What dbt builds against | What it proves |
|---|---|---|
| `existing_tables` | real inputs the migrator supplied: tables already in dev, or files provided with the work (`inputs.test_source_schemas` says where each lives) | the SQL runs and the tests hold on real inputs; parity still needs `legacy_prod_readable` |
| `seeds` | mock source rows the **agent invents**, loaded as dbt seeds | the SQL runs and the tests hold on **fabricated** rows only |
| `none` | nothing | compile only |

**The line between the two is who wrote the rows, not the dbt mechanism.** Files the migrator
supplied (an extract, a sample CSV) are `existing_tables` even when they are loaded with
`dbt seed`; record them as `supplied_seeds: <database>.<schema>` in `test_source_schemas`. Only
rows the agent made up are `seeds`.

Recommend `existing_tables` whenever dev can read the sources or the migrator can supply files;
`seeds` only when neither is possible and the migrator still wants the logic exercised; `none`
only to check that the project compiles. Ask it in the Step-0 gate round with every other manifest
question; the gate fails until it is answered. The rest of this reference applies only to `seeds`.

## Contents

- [When to use seeds](#when-to-use-seeds)
- [Where to put them](#where-to-put-them)
- [Column types](#column-types)
- [Edge cases to include on purpose](#edge-cases-to-include-on-purpose)
- [Metadata views](#metadata-views)
- [Fabricated data rule](#fabricated-data-rule)
- [Dev schema safety](#dev-schema-safety)
- [Reporting](#reporting)
- [Removal before production](#removal-before-production)

## When to use seeds

Only when `access.legacy_prod_readable` is false or the sources are missing in dev, **and** the
migrator chose `seeds`. Never when real sources exist: with `existing_tables`, create no seeds.

## Where to put them

`seeds/mock_<domain>/<schema_role>/`, one CSV per source table. Give each original schema its own
seed schema, so every source block keeps one database/schema (Fusion rejects `database:`/`schema:`
on a source table; see [dbt-best-practices.md](dbt-best-practices.md#fusion-yaml-gotchas)):

```yaml
# dbt_project.yml
seeds:
  my_project:
    mock_payroll:
      lnd:
        +schema: mock_payroll_lnd
      temp:
        +schema: mock_payroll_temp
```

Point each source at the seed schema through a var, so switching back to the real location is one
change:

```yaml
sources:
  - name: legacy_prod_lnd
    database: "{{ target.database }}"
    schema: "{{ var('legacy_prod_lnd_schema', 'LND') }}"
```

## Column types

Pin `+column_types` in `dbt_project.yml` to the types the staging models and contracts expect, so
numbers and dates are not inferred from CSV text:

```yaml
      lnd:
        +column_types:
          emp_id: varchar
          pay_amount: number(18, 2)
          pay_date: date
```

Use the connected adapter's type names (see [warehouse-conformance.md](warehouse-conformance.md)).
A column a validation rule checks for non-numeric text must stay `varchar` in the seed, or the
seed load rejects the very rows the rule exists to catch.

## Edge cases to include on purpose

A mock set that only holds happy-path rows proves nothing about the rules. Include:

- null and non-numeric values in every validated column;
- a row present on one side of each outer join only;
- an excluded category for every `where` filter;
- superseded history rows (an older version of a record that a newer one replaces);
- a boundary-date row for every date window (pin the date with `as_of_date`, see
  [dbt-best-practices.md](dbt-best-practices.md#date-dependent-logic));
- a byte-identical duplicate row (it exercises translation trap 6 keys and dedup logic).

## Metadata views

Warehouse metadata the legacy SQL reads (for example Snowflake `INFORMATION_SCHEMA.LOAD_HISTORY`)
cannot be seeded. Add a seed with the same columns in the mock schema, and a var
(`load_history_schema` style) that the model reads the relation from, defaulting to the real
location. List the substitution in `migration_changes.md`.

## Fabricated data rule

Values are invented, never copied from real data. Do not echo the values of columns listed in
`compliance.pii_columns` (or columns that hold PII under a misleading name,
`compliance.misleading_names`) into docs, fixtures, or messages, even mock ones.

## Dev schema safety

Before `dbt seed`, confirm with a read-only query (for example against `information_schema.schemata`)
that the target seed schemas do not already exist, and tell the migrator which database and schemas
dbt will write to. Seeds only ever go into **new** schemas in the dev target.

## Reporting

Everything built on mock data is labelled **"mock data only"** in `migration_changes.md`. It never
sets `parity: pass` in `05_parity.json` and never counts toward coverage "validated" in Step 7. The
rebuild-stability check ([data-validation.md](data-validation.md#the-compile-gate-free)) still runs
and is still recorded: determinism does not depend on where the rows came from.

## Removal before production

The seeds, their `dbt_project.yml` config, and the substitution vars are removed before production.
List each in the cutover runbook ([cutover-runbook.md](cutover-runbook.md)) so the removal is a
checked step, not a memory.
