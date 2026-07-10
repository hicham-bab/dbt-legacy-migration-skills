# Use the dbt package ecosystem (the best-way toolkit)

A migration must **lean on established dbt packages**, not hand-roll what a maintained package already
does well. This reference maps each migration step to the package(s) to use, with the exact macros.
All packages below carry the **Fusion-compatible** badge on the dbt package hub (verified) — but read
[Fusion compatibility](#fusion-compatibility) before pinning.

## Contents

- [Install pattern](#install-pattern)
- [Step-by-step package map](#step-by-step-package-map)
- [audit_helper — the validation centerpiece](#audit_helper--the-validation-centerpiece)
- [codegen — scaffolding](#codegen--scaffolding)
- [Fusion compatibility](#fusion-compatibility)

## Install pattern

Add to `packages.yml`, then `dbt deps`. **Do not hardcode versions from this doc** — they move; pin to
the **latest version that shows the Fusion-compatible badge on [hub.getdbt.com](https://hub.getdbt.com)**.

```yaml
packages:
  - package: dbt-labs/dbt_utils          # surrogate keys, star, date_spine, generic tests
  - package: dbt-labs/codegen            # scaffold sources / staging / YAML docs
  - package: dbt-labs/audit_helper       # legacy-vs-dbt data parity  ← the validation centerpiece
  - package: metaplane/dbt_expectations  # Great-Expectations-style tests (moved from calogica)
  - package: dbt-labs/dbt_project_evaluator  # best-practice quality gate
  - package: godatadriven/dbt_date       # Kimball date dimension (dimensional migrations only)
```
Install only what a given migration needs (e.g. `dbt_date` only for a Kimball/star target;
`datavault4dbt` only for a Data Vault target).

## Step-by-step package map

| Step | Task | Package · macro |
|------|------|-----------------|
| 1 | Scaffold `sources.yml` from the legacy tables | **codegen** · `generate_source` |
| 1/3 | Scaffold staging models (import CTEs, base model) | **codegen** · `generate_base_model`, `generate_model_import_ctes` |
| 3 | Surrogate keys, `SELECT * minus`, union many tables, date spine | **dbt_utils** · `generate_surrogate_key`, `star`, `union_relations`, `date_spine` |
| 3 | Data Vault entities | **datavault4dbt** (via the `using-datavault4dbt` skill) |
| 3 | Kimball date dimension | **dbt_date** · `get_date_dimension` |
| 4 | Scaffold model YAML (docs + tests) | **codegen** · `generate_model_yaml` |
| 4 | Generic tests beyond built-ins | **dbt_utils** (`unique_combination_of_columns`, `accepted_range`, `equality`, `recency`) + **dbt_expectations** (`expect_column_values_to_be_between`, `_to_match_regex`, `_to_be_in_set`, `expect_table_row_count_to_equal_other_table`) |
| 5 | **Prove legacy-prod = dbt-dev** | **audit_helper** (see below) — the best-way parity tool |
| 7 | Post-migration quality gate | **dbt_project_evaluator** — flags missing tests/docs, bad structure, fanout |
| — | Make the project Fusion-clean | **dbt-autofix** CLI (remediates deprecations, moves test args under `arguments:`) + `dbt compile` under Fusion |

Always emit tests with the Fusion **`arguments:`** nested spec (required for package generic tests
under Fusion) — see [dbt-best-practices.md](dbt-best-practices.md).

## audit_helper — the validation centerpiece

For Step 5, **use audit_helper instead of a hand-written full-outer-join** — it's dbt Labs' official
migration-validation package. Use the current **"classify"** macros (the older `compare_relations` /
`compare_queries` are labelled *legacy* — avoid for new work):

- `compare_and_classify_query_results` — row-by-row comparison of two **queries** (legacy prod vs the
  dbt model) with summary stats: identical / added / removed / modified. **The primary "does my
  migrated model match legacy?" macro.**
- `compare_and_classify_relation_rows` — same, taking two **relations**.
- `quick_are_relations_identical` / `quick_are_queries_identical` — fast hash-based yes/no.
- `compare_which_relation_columns_differ` / `compare_which_query_columns_differ` — which columns hold
  value differences (to target the investigation).
- `compare_column_values` — detailed value diff of a single column.
- `compare_relation_columns` — **schema** diff (column order + data types).
- `compare_row_counts` — quick row-count delta.

Typical flow: `quick_are_relations_identical` first; if not identical,
`compare_and_classify_relation_rows` for the summary, then `compare_which_relation_columns_differ` +
`compare_column_values` to find and explain the differing columns (feeding the "explain every
difference" taxonomy in [data-validation.md](data-validation.md)). Run through `dbt compile` + the
dbt MCP `execute_sql`, comparing the dbt-dev model to the legacy prod table.

## codegen — scaffolding

Accelerate the boilerplate so the agent spends its effort on logic, not typing YAML:
- `dbt run-operation generate_source --args '{schema_name: ..., database_name: ...}'` → paste into
  `_sources.yml` (wraps the legacy raw tables).
- `dbt run-operation generate_base_model --args '{source_name: ..., table_name: ...}'` → a `stg_` model.
- `dbt run-operation generate_model_yaml --args '{model_names: [...]}'` → the model property/doc file
  to then enrich with descriptions and `arguments:`-spec tests.

Treat generated output as a **starting point** — review and correct it; don't ship it blind.

## Fusion compatibility

- **The hub badge is the source of truth.** Each package version on hub.getdbt.com shows a
  "Fusion compatible" badge + the Fusion preview build it was parse-tested against. Pin to a
  badged version.
- **dbt1065 warning is not a blocker.** Fusion may warn `Package 'X' requires dbt version [...] but
  current version is 2.0.0-preview...` when a package's `require-dbt-version` upper bound predates
  2.0. If the hub badge says compatible, it is — upgrade to a version whose `require-dbt-version`
  admits 2.0 (e.g. `<3.0.0`) to silence it.
- **`arguments:` is mandatory** for passing args to package generic tests under Fusion.
- Verify the badge at pin time; these are preview builds and versions move.
