# Coverage report — proving ≥95% (Step 7)

The migration target is **≥95% of the legacy workload migrated and validated**. This step turns
that into a concrete, auditable number and lists exactly what the remaining <5% is, so nothing is
silently dropped.

## Contents

- [How to compute coverage](#how-to-compute-coverage)
- [What counts as the residual](#what-counts-as-the-residual)
- [Quality gate: dbt_project_evaluator](#quality-gate-dbt_project_evaluator)
- [Report template](#report-template)

## Quality bar: warehouse conformance + anti-pattern lint + dbt_project_evaluator

Coverage and parity are the floor, not the finish. A migration that reproduces the legacy tool's
shape can pass both while carrying forward technical debt (the lift-and-shift trap), or while using
SQL/types that are wrong for the target warehouse. So the migration is **not "done"** until it also
clears the **quality bar**, three automated gates run on the migrated project:

```bash
dbt parse && dbt compile                             # against the CONNECTED target adapter: dialect + contract types
python3 <skills-dir>/legacy-to-dbt-migration-foundations/scripts/lint_idiomatic.py <project-dir>     # deterministic anti-pattern gate
dbt build --select package:dbt_project_evaluator     # dbt-labs best-practice gate
```

- **Compile on the connected adapter** must be clean, with contracts enforced. This is what makes the
  output correct for the customer's actual warehouse (dialect functions, contract `data_type`
  validity, macro portability, package/adapter support), for any target, without a per-warehouse
  rulebook. See [warehouse-conformance.md](warehouse-conformance.md).
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

The 95% bar is not arbitrary: it forces the hard long tail (ambiguous logic, missing infrastructure)
to be **explicitly triaged** as an accepted difference or a blocker, rather than silently dropped.

### Score two metrics: recall and precision (not one)

"Parity-validated" means **both** metrics from the PK-coverage pass (see
[data-validation.md](data-validation.md)) are >= 95%:

| Metric | Formula | Detects |
|---|---|---|
| `recall` | `matched / (matched + only_in_legacy)` | missing rows in dbt (under-coverage) |
| `precision` | `matched / (matched + only_in_dbt)` | extra rows in dbt (fan-out / filter gap) |

A model passes **only when both >= 95%**. Recall alone is a trap: a model at recall 100% / precision
1.4% has a catastrophic fan-out (e.g. the wrong join producing every row instead of the matched
subset) that recall-only scoring would call PASS. Sort the report by `least(recall, precision)` so the
worst models surface first.

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

## BLOCKED - infrastructure dependency (not a code issue)

Some models cannot reach parity until an **infrastructure** dependency is resolved (a datashare not
provisioned, a source system not yet available in the target). Calling these FAIL misrepresents the
migration to stakeholders. Record them **separately**, exclude them from the denominator, and surface
the specific ask:

| Model | Legacy coverage | Blocker | Ask |
|---|---|---|---|
| `rpt_risk_in_force` | 3% | source datashare absent | provision it in the target environment |
| `rpt_claims_tsi` | 1% | only snapshot data available | provision the production datashare |

```
coverage % = PASS / (total - BLOCKED) × 100
```

BLOCKED is distinct from residual: residual is in-scope work still being explained or fixed; BLOCKED
is out of your hands until the infrastructure lands. Never fold BLOCKED into FAIL, and never hide it in
the coverage number.

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
