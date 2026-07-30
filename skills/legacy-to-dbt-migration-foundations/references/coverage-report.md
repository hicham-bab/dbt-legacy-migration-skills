# Coverage report — proving ≥95% (Step 7)

The migration target is **≥95% of the legacy workload migrated and validated**. This step turns
that into a concrete, auditable number and lists exactly what the remaining <5% is, so nothing is
silently dropped.

## Contents

- [How to compute coverage](#how-to-compute-coverage)
- [What counts as the residual](#what-counts-as-the-residual)
- [Quality gate: dbt_project_evaluator](#quality-gate-dbt_project_evaluator)
- [Report template](#report-template)

## Quality bar: anti-pattern lint + dbt_project_evaluator

Coverage and parity are the floor, not the finish. A migration that reproduces the legacy tool's
shape can pass both while carrying forward technical debt (the lift-and-shift trap). So the migration
is **not "done"** until it also clears an idiomatic **quality bar**, two automated gates run on the
migrated project:

```bash
python3 <skills-dir>/legacy-to-dbt-migration-foundations/scripts/lint_idiomatic.py <project-dir>     # deterministic anti-pattern gate
dbt build --select package:dbt_project_evaluator    # dbt-labs best-practice gate
```

- **`lint_idiomatic.py`** flags the lift-and-shift anti-patterns directly (pre/post-hook overuse,
  hardcoded `db.schema.table` relations, kept control-flow, monolithic models, missing staging/tests)
  and exits non-zero on any error-severity finding. See
  [anti-patterns.md](anti-patterns.md) for what each means and the idiomatic fix.
- **`dbt_project_evaluator`** (dbt-labs) flags undocumented/untested models, direct source references,
  model fanout, staging<->source 1:1 violations, and naming/structure issues. See [dbt-packages.md](dbt-packages.md).

Resolve findings, or record a justified exception (evaluator seed / a note in `migration_changes.md`).
A migration is "done" only when it passes the quality bar, not merely at >=95% coverage with matching
results.

## How to compute coverage

Coverage is measured against the **inventory built in Step 1** — not a guess. Use the total count
of legacy units of work recorded there (mappings/transformations, components, or procedural
blocks, depending on the source).

```
coverage % = (units migrated AND parity-validated) / (total units inventoried) × 100
```

A unit counts as covered only when both are true:
1. It was translated into a dbt object (model / snapshot / macro / source), and
2. It passed validation in Step 5 (parity pass, or its tests pass with no unexplained mismatch).

A unit translated but with unresolved data mismatches is **not** covered — it is residual until
the mismatch is explained (legitimate platform difference) or fixed.

## What counts as the residual

The <5% you are allowed to leave for human review — always list it explicitly with a reason:

- Dynamic SQL / runtime-generated statements that can't be resolved statically.
- Proprietary source-tool components with no SQL/warehouse equivalent (e.g. non-SQL Informatica/
  Talend runtime transforms, external calls, file/FTP side effects).
- Non-deterministic or order-dependent procedural logic.
- Low-confidence classifications (< 0.65 from Step 2) awaiting a human confirm.
- Units with genuine data mismatches still under investigation.

If the residual exceeds 5%, do not claim success — report the actual number and the blocking
categories, and recommend next steps.

## Report template

Append to `migration_changes.md` (or write `coverage_report.md`):

```markdown
## Coverage

- Total legacy units inventoried: N
- Migrated & validated: M
- **Coverage: M/N = XX.X%**

### Migrated (M)
- <unit> → <dbt object> — parity: pass

### Residual — needs human review (N - M)
| Legacy unit | Why not auto-migrated | Recommended action |
|-------------|-----------------------|--------------------|
| <unit>      | dynamic SQL           | manual rewrite     |
```
