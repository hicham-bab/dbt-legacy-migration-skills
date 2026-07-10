# Provisioning dbt packages during the migration

Packages are **not** bundled with this skill or assumed to be pre-installed. Instead the skill is
**smart about packages at migration time**: as each step needs one, it detects whether the target
project already has it, and if not **adds only that package** to the target project's `packages.yml`
(pinned to a Fusion-compatible version), runs `dbt deps`, and uses it. Add just what *this* migration
needs — never bloat `packages.yml` with unused packages.

## Contents

- [The just-in-time procedure](#the-just-in-time-procedure)
- [Which need pulls in which package](#which-need-pulls-in-which-package)
- [audit_helper — the validation centerpiece](#audit_helper--the-validation-centerpiece)
- [codegen — scaffolding](#codegen--scaffolding)
- [Fusion compatibility & pinning](#fusion-compatibility--pinning)

## The just-in-time procedure

1. **Read the target project's `packages.yml`** (create it if absent). Note what's already installed
   — never remove or downgrade a package the project already depends on.
2. **When a step needs a package** (see the table below), and it isn't already present, **append it**
   to `packages.yml` pinned to the **latest Fusion-badged version on
   [hub.getdbt.com](https://hub.getdbt.com)** (don't hardcode a version from this doc — they move).
3. **`dbt deps`**, then confirm with **`dbt parse`** that the project still parses cleanly.
4. **Add only what this migration uses.** The set is driven by the choices made:
   - always useful: `dbt-labs/codegen` (scaffolding), `dbt-labs/dbt_utils` (keys/tests/helpers)
   - data-parity validation (Step 5): `dbt-labs/audit_helper`
   - richer data tests (Step 4): `metaplane/dbt_expectations`
   - quality gate (Step 7): `dbt-labs/dbt_project_evaluator`
   - **only if** the chosen architecture is Data Vault: `datavault4dbt` (Scalefree)
   - **only if** Kimball/Star and you need a calendar dimension: `godatadriven/dbt_date`
5. **Record it** — the edited `packages.yml` is part of the migration output; note in
   `migration_changes.md` which packages were added and why.

Because the needed set depends on Step 2's architecture choice and whether Step 5 does data parity,
provision **incrementally as you reach each step** (or compute the set right after Step 2 and install
once). Don't pre-install packages a given migration won't touch.

## Which need pulls in which package

| The migration needs to… | Add package · use |
|---|---|
| Scaffold `sources.yml` from the legacy tables | **dbt-labs/codegen** · `generate_source` |
| Scaffold staging models / import CTEs | **dbt-labs/codegen** · `generate_base_model`, `generate_model_import_ctes` |
| Scaffold model YAML (docs + test stubs) | **dbt-labs/codegen** · `generate_model_yaml` |
| Surrogate keys, `SELECT * minus`, union many tables, date spine | **dbt-labs/dbt_utils** · `generate_surrogate_key`, `star`, `union_relations`, `date_spine` |
| Generic tests beyond the built-ins | **dbt-labs/dbt_utils** (`unique_combination_of_columns`, `accepted_range`) + **metaplane/dbt_expectations** (`expect_column_values_to_be_between`, `_to_match_regex`, `_to_be_in_set`) |
| Prove legacy-prod = dbt-dev (data parity) | **dbt-labs/audit_helper** (see below) |
| Post-migration quality gate | **dbt-labs/dbt_project_evaluator** — flags missing tests/docs, structure, fanout |
| Build a Data Vault (architecture = Data Vault) | **datavault4dbt** (via the `using-datavault4dbt` skill, which configures it) |
| Build a Kimball/Star calendar dimension | **godatadriven/dbt_date** · `get_date_dimension` |

Emit package generic tests with the Fusion **`arguments:`** nested spec — required under Fusion.

## audit_helper — the validation centerpiece

For Step 5, add `dbt-labs/audit_helper` and use it instead of a hand-written full-outer-join — it's
dbt Labs' official migration-validation package. Signatures verified against audit_helper 0.14.0
(the row/query classify macros take `primary_key_columns=[...]`, a **list**):

- `compare_and_classify_relation_rows(a_relation, b_relation, primary_key_columns=[...])` — the
  primary "does my migrated model match legacy?" macro; classifies rows identical / added / removed /
  modified. (`compare_and_classify_query_results(a_query, b_query, primary_key_columns=[...])` to
  compare two queries — e.g. restricting both to the overlapping window.)
- `quick_are_relations_identical(a_relation, b_relation)` — fast hash yes/no (no key arg).
- `compare_which_relation_columns_differ(a_relation, b_relation, primary_key_columns=[...])` — which
  columns hold value differences.
- `compare_column_values(a_query, b_query, primary_key, column_to_compare)` — value diff of one
  column (note: singular `primary_key` string here).
- `compare_relation_columns(a_relation, b_relation)` — schema diff (column order + types).
- `compare_row_counts(a_relation, b_relation)` — row-count delta.

Avoid the legacy `compare_relations`/`compare_queries`. Put the call in `analyses/validate_<entity>.sql`,
`dbt compile`, and run the compiled SQL (or via the dbt MCP `execute_sql`).

## codegen — scaffolding

Add `dbt-labs/codegen`, then run via `dbt run-operation`:
- `generate_source --args '{schema_name: ..., database_name: ...}'` → paste into `_sources.yml`.
- `generate_base_model --args '{source_name: ..., table_name: ...}'` → a `stg_` model.
- `generate_model_yaml --args '{model_names: [...]}'` → the property/doc file to enrich.

Treat generated output as a **starting point** — review and correct it; don't ship it blind.

## Fusion compatibility & pinning

- **The hub badge is the source of truth.** Each package version on hub.getdbt.com shows a
  "Fusion compatible" badge + the preview build it was parse-tested against. Pin to a badged version.
- **`dbt1065` is not a blocker.** Fusion may warn a package's `require-dbt-version` upper bound
  predates 2.0; if the hub badge says compatible, upgrade to a version whose bound admits 2.0
  (e.g. `<3.0.0`) to silence it.
- **`arguments:` is mandatory** for package generic tests under Fusion.
- Re-verify the badge at install time — these are preview builds and versions move.
