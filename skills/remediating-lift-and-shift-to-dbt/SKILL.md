---
name: remediating-lift-and-shift-to-dbt
description: >
  Refactor an existing, poorly-migrated ("lift-and-shift") dbt project into idiomatic dbt without
  changing results. Use when a project already runs and returns correct numbers but is not
  maintainable: pre/post-hook overuse, monolithic models, hardcoded relations, retained control-flow,
  or missing staging/tests/docs. Preserves parity while clearing the idiomatic quality bar.
license: Apache-2.0
allowed-tools: "Bash(dbt:*), Bash(git:*), Bash(python3:*), Read, Write, Edit, Glob, Grep, WebFetch(domain:docs.getdbt.com)"
metadata:
  author: hicham-babahmed
  compatibility: dbt Fusion
---

# Remediating a lift-and-shift dbt project

A migration that "gives the same results" is not finished. A lift-and-shift often produces dbt that
runs but carries the legacy tool's shape as technical debt. This skill takes an **existing dbt
project** and refactors it to idiomatic dbt **without changing its output**. It is the counterpart to
the legacy-to-dbt migration skills: same destination (idiomatic dbt), different starting point
(already-migrated-badly, not the legacy tool).

Shares the common references in
[legacy-to-dbt-migration-foundations](../legacy-to-dbt-migration-foundations/SKILL.md). Read the
anti-pattern catalog first:
[anti-patterns.md](../legacy-to-dbt-migration-foundations/references/anti-patterns.md).

## Core principle

**Parity is invariant; only the shape changes.** Every refactor step must leave results identical.
Capture a baseline before touching anything, and re-check parity after each change. "Done" means the
project is idiomatic (clears the quality bar) **and** returns exactly what it returned before.

## Workflow

- **Step 0 - Detect the project and warehouse.** Locate the dbt project, profile, and target platform
  (see [cloud-detection-and-materializations.md](../legacy-to-dbt-migration-foundations/references/cloud-detection-and-materializations.md)).
  A `migration_decisions.yml` may record the run's decisions.
- **Step 1 - Inventory the anti-patterns.** Run the linter to enumerate what to fix:
  `python3 <skills-dir>/legacy-to-dbt-migration-foundations/scripts/lint_idiomatic.py <project-dir>`
  and `dbt build --select package:dbt_project_evaluator`. Map each finding to its fix using
  [anti-patterns.md](../legacy-to-dbt-migration-foundations/references/anti-patterns.md).
- **Step 2 - Capture a parity baseline.** Materialize or record the current output of every model you
  will touch, so the refactor can be proven results-preserving. Use the patterns in
  [data-validation.md](../legacy-to-dbt-migration-foundations/references/data-validation.md)
  (audit_helper, or a full-outer-join / row-count baseline).
- **Step 3 - Refactor one model family at a time**, re-checking parity after each:
  - **Hooks:** move `pre_hook`/`post_hook` logic into the model (a CTE), a **test**, a **macro**, or a
    **snapshot**; keep a hook only for a true side-effect (grants, cache warmups).
  - **Monolith:** decompose into staging -> (intermediate) -> mart via `ref()`
    ([layer-classification.md](../legacy-to-dbt-migration-foundations/references/layer-classification.md),
    depth per-workload, not a fixed template).
  - **Hardcoded relations:** replace `db.schema.table` with `ref()` / `source()`.
  - **Control-flow:** turn cursors/loops/`EXECUTE IMMEDIATE`/`CALL` into set-based SQL.
- **Step 4 - Add tests, docs, contracts** per
  [dbt-best-practices.md](../legacy-to-dbt-migration-foundations/references/dbt-best-practices.md)
  (grain unique/not_null, accepted_values/relationships, descriptions; a data-quality DELETE that was
  in a hook usually becomes a test).
- **Step 5 - Prove parity vs the Step 2 baseline.** Every model's output must be unchanged; explain
  any diff (accept only environment/platform differences, never a logic change).
- **Step 6 - Clear the quality bar.** Re-run the linter and `dbt_project_evaluator`; both must pass
  (or exceptions justified in `remediation_changes.md`). See
  [coverage-report.md](../legacy-to-dbt-migration-foundations/references/coverage-report.md).
- **Step 7 - Document** the before/after in `remediation_changes.md` (anti-pattern -> fix, and the
  parity evidence).

## Success criteria

- `dbt build` succeeds; every model builds and its tests pass.
- **Parity preserved:** outputs identical to the pre-refactor baseline.
- **Quality bar cleared:** the anti-pattern linter reports zero findings and `dbt_project_evaluator`
  passes (or documented exceptions).
- Compilation is not correctness, and correctness is not idiomatic. Remediation requires all three.
