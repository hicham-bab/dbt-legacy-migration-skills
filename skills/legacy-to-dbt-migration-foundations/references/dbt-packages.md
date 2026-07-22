# Packages vs. macros — provisioning during the migration

The skill does **not** bundle or assume packages. Two things govern package use:

1. **Ask the migrator a choice up front** (Step 0): may the migration use **external dbt packages**
   (so it reuses maintained macros instead of hand-writing them), or should it stay
   **self-contained** and generate the needed macros itself?
2. **Only ever install from [hub.getdbt.com](https://hub.getdbt.com)** — never git/tarball/private
   sources — and only versions that show the **Fusion-compatible** badge.

Then, as each step **detects a need** (surrogate keys, SCD, dedup, unions, a date dimension, data
comparison, richer tests, scaffolding), the skill either installs the hub package (Path A) or
generates the equivalent macro (Path B) — it never silently hand-rolls boilerplate that a hub
package solves when the migrator asked for packages.

## Contents

- [The choice: packages or macros](#the-choice-packages-or-macros)
- [Rule: hub.getdbt.com only](#rule-hubgetdbtcom-only)
- [Detecting a package need](#detecting-a-package-need)
- [Path A — external hub packages (just-in-time)](#path-a--external-hub-packages-just-in-time)
- [Path B — self-contained macros](#path-b--self-contained-macros)
- [Need → package (Path A) / macro (Path B)](#need--package-path-a--macro-path-b)
- [audit_helper & codegen](#audit_helper--codegen)
- [Fusion compatibility & pinning](#fusion-compatibility--pinning)

## The choice: packages or macros

Ask at Step 0 and record it — it governs how every later step is built:

- **Use external packages (recommended)** — maintained, versioned, Fusion-tested code from
  hub.getdbt.com; far less code for you to own. The skill installs only what each step needs.
- **Self-contained (macros only)** — no external dependencies; the skill writes the equivalent
  macros into the project's `macros/`. You own and maintain them (no upstream fixes).

**Interaction with the modeling approach choice (Step 2):** the **Data Vault** path effectively *requires*
the `datavault4dbt` hub package (hand-rolling its hashing/loading is impractical). If the migrator
picks *macros only* **and** Data Vault, flag the conflict and offer to either allow that one hub
package or pick a dimensional modeling approach instead. Kimball/Star and layered work fine either way
(dbt snapshots and simple macros cover them).

## Rule: hub.getdbt.com only

When packages are used, add them **only** via the hub `package:` syntax, pinned:

```yaml
packages:
  - package: dbt-labs/dbt_utils        # namespace/name resolves from hub.getdbt.com
    version: [">=1.0.0", "<2.0.0"]
```

**Never** use `git:`, `tarball:`, `local:`, or any private/unverified source — those bypass the hub's
trust, versioning, and Fusion badge. Every package added must have the **Fusion-compatible badge**
on its hub page; pin to a badged version. If a needed capability has no hub package, fall back to a
Path B macro rather than reaching for an off-hub source.

## Detecting a package need

Whenever a step is about to emit **repeated/boilerplate SQL or a custom macro**, first check the
[need → package](#need--package-path-a--macro-path-b) table. If a hub package covers it:
- migrator chose **packages** → install & use it (Path A);
- migrator chose **macros** → generate the equivalent (Path B).

Don't hand-roll a surrogate-key hash, an SCD differ, a date spine, a union-of-many-tables, or a
data-comparison query from scratch when a hub package does it and packages are allowed.

## Path A — external hub packages (just-in-time)

1. **Read the target project's `packages.yml`** (create if absent); never remove/downgrade existing deps.
2. **When a step needs a package**, and it's absent, **append it** pinned to the latest Fusion-badged
   hub version (don't hardcode versions from this doc — they move).
3. **`dbt deps`**, then confirm **`dbt parse`** is clean.
4. **Add only what this migration uses** — driven by the choices (e.g. `datavault4dbt` only for Data
   Vault; `godatadriven/dbt_date` only for a Kimball calendar dim; `dbt-labs/audit_helper` only when
   doing data parity). Don't bloat `packages.yml`.
5. **Record** the added packages (and why) in `migration_changes.md`; the edited `packages.yml` is
   part of the output.

## Path B — self-contained macros

If external packages were declined, generate the equivalents into `macros/` (and singular/custom
generic tests into `tests/` or `macros/`). Keep them small and Fusion-conformant (`cast()`,
`coalesce()`, no `::`). Reasonable substitutes:

- **Surrogate key** → a macro hashing coalesced, cast key columns, e.g.
  `md5(coalesce(cast(a as string),'') || '-' || coalesce(cast(b as string),''))` — deterministic,
  stable column order.
- **SCD Type 2** → use dbt **snapshots** (a core dbt feature, *not* a package) feeding a versioned
  dim; no macro needed.
- **Date dimension** → a date-spine macro (recursive CTE / `union all` generator) or a generated seed.
- **Data parity (Step 5)** → the hand-written full-outer-join / aggregate-baseline in
  [data-validation.md](data-validation.md).
- **Richer tests** → singular tests in `tests/` or a small custom generic test macro.
- **Scaffolding** → just write `_sources.yml` / staging models directly (scaffolding packages are a
  convenience, never required).

Trade-off to state to the user: self-contained = no external trust surface and no version drift, but
you maintain the macros and forgo upstream fixes/coverage.

## Need → package (Path A) / macro (Path B)

| The migration needs to… | Path A: hub package · macro | Path B: self-contained |
|---|---|---|
| Surrogate keys | `dbt-labs/dbt_utils` · `generate_surrogate_key` | md5-of-coalesced-casts macro |
| `SELECT * minus`, unions, date spine | `dbt-labs/dbt_utils` · `star`, `union_relations`, `date_spine` | small helper macros |
| Scaffold sources / staging / model YAML | `dbt-labs/codegen` | write the YAML/models directly |
| Generic tests beyond built-ins | `dbt-labs/dbt_utils` + `metaplane/dbt_expectations` | singular/custom generic tests |
| Prove legacy-prod = dbt-dev (parity) | `dbt-labs/audit_helper` (classify macros) | full-outer-join diff (data-validation.md) |
| Post-migration quality gate | `dbt-labs/dbt_project_evaluator` | manual review checklist |
| SCD2 history | dbt **snapshots** (core, not a package) | dbt **snapshots** (same) |
| Build a Data Vault | `datavault4dbt` (**required** — see building-datavault.md) | not practical without the package |
| Kimball/Star calendar dimension | `godatadriven/dbt_date` · `get_date_dimension` | date-spine macro / seed |

Emit package generic tests with the Fusion **`arguments:`** nested spec.

## audit_helper & codegen

(Path A only — under Path B use the substitutes above.)

**audit_helper** — the Step 5 parity centerpiece. Signatures verified against 0.14.0 (row/query
classify macros take `primary_key_columns=[...]`, a **list**):
`compare_and_classify_relation_rows(a_relation, b_relation, primary_key_columns=[...])` (primary
"does it match?" macro), `compare_and_classify_query_results(a_query, b_query, primary_key_columns=[...])`,
`quick_are_relations_identical(a_relation, b_relation)`,
`compare_which_relation_columns_differ(a_relation, b_relation, primary_key_columns=[...])`,
`compare_column_values(a_query, b_query, primary_key, column_to_compare)` (singular `primary_key`),
`compare_relation_columns` (schema), `compare_row_counts`. Avoid the legacy `compare_relations`/`compare_queries`.

**codegen** — scaffolding via `dbt run-operation`: `generate_source`, `generate_base_model`,
`generate_model_import_ctes`, `generate_model_yaml`. Treat output as a starting point; review it.

## Fusion compatibility & pinning

- **The hub badge is the source of truth** — pin to a version showing the Fusion-compatible badge.
- **`dbt1065` is not a blocker** — if the badge says compatible, widen the `require-dbt-version`
  bound (e.g. `<3.0.0`) to silence it.
- **`arguments:` is mandatory** for package generic tests under Fusion.
- Re-verify the badge at install time — preview builds and versions move.
