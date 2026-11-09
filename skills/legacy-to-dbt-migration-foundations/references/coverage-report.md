# Coverage report — proving ≥95% (Step 7)

The migration target is **≥95% of the legacy workload migrated and validated**. This step turns
that into a concrete, auditable number and lists exactly what the remaining <5% is, so nothing is
silently dropped.

## Contents

- [Quality bar: warehouse conformance + anti-pattern lint + dbt_project_evaluator](#quality-bar-warehouse-conformance--anti-pattern-lint--dbt_project_evaluator)
- [How to compute coverage](#how-to-compute-coverage)
- [What counts as the residual](#what-counts-as-the-residual)
- [Waivers: residual above the ceiling](#waivers-residual-above-the-ceiling)
- [Worked example](#worked-example)
- [BLOCKED - infrastructure dependency (not a code issue)](#blocked---infrastructure-dependency-not-a-code-issue)
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

**Report three figures — always all three.** A single ratio can be made to say almost anything by
moving units between the numerator and the denominator; three figures reported together cannot.

```
gross_coverage    = migrated_and_validated / migratable_inventoried
in_scope_coverage = migrated_and_validated / engagement_scope
residual_pct      = documented_residual / migratable_inventoried
```

- `migratable_inventoried` — every migratable unit Step 1 counted. This is the **fixed** denominator
  for the whole engagement.
- `engagement_scope` — the subset agreed for this pass (`engagement_scope ≤ migratable_inventoried`).
- `migrated_and_validated` — units both translated and parity-validated (the two conditions below).
- `documented_residual` — units inside `migratable_inventoried` that were **not** migrated and
  validated, each with a recorded reason.

Rules, non-negotiable:

- The **≥95% gate and the ≤5% residual ceiling apply to `gross_coverage` and `residual_pct`** —
  **never** to `in_scope_coverage`.
- `in_scope_coverage` is reported **for context only**. It must never be presented as "the" coverage
  number, in a report, a summary line, or a conversation.
- **Documented residual does not leave the denominator.** It is reported separately *and* counted
  against `gross_coverage`.
- Out-of-scope **EL, control-flow and bridge components were never in the denominator at all**. That
  is a different thing from "in the denominator and not migrated". Conflating the two is the error
  this section exists to prevent.
- If `residual_pct > 5%`, the migration **does not pass on arithmetic**. It can pass only on an
  explicit, recorded **waiver** — see below.

**Rejected formula.** Do **not** compute coverage as
`migrated / (migratable − documented_residual)`. Subtracting the residual from the denominator makes
the metric incapable of failing: anything unfinished gets relabelled "documented residual", leaves
the denominator, and the ratio reports itself as 100%. It also voids the ≤5% residual ceiling, which
only constrains anything while the residual is still measured against the full denominator.

**Recompute, never retype.** The Step-1 inventory script writes a machine-readable
`01_inventory.json` whose `summary.coverage_denominator` holds the migratable count. Recompute all
three figures at report time from that artifact plus the Step-5 parity results — do not carry
numbers forward from memory or from an earlier draft. The denominator printed in the report **must
equal** `summary.coverage_denominator`; if it does not, the report is wrong, not the artifact.

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
categories, and recommend next steps. The only route to a pass above the ceiling is a recorded
waiver.

## Waivers: residual above the ceiling

A waiver is the one legitimate way a migration passes with `residual_pct > 5%`. It does not change
the arithmetic — `gross_coverage` and `residual_pct` are still reported as computed. It records that
a named human accepted a named exception.

A waiver must name, for **each** residual unit:

- the unit (as it appears in the Step-1 inventory),
- the blocking reason (specific — a category name alone is not a reason),
- who accepted it (a person, not a team),
- the date accepted.

```markdown
### Coverage waiver

Residual: 2/25 = 8% (exceeds the 5% ceiling)

| Residual unit | Blocking reason | Accepted by | Date |
|---------------|-----------------|-------------|------|
| <unit>        | depends on a warehouse artifact dbt does not populate | <name> | YYYY-MM-DD |
| <unit>        | dynamic SQL, target resolved at runtime | <name> | YYYY-MM-DD |
```

A waiver makes the exception **visible and attributable**. Redefining the denominator makes the same
exception arithmetically erased and nobody's responsibility. Prefer the visible version — including
when it is the less comfortable number to present.

## Worked example

Generic numbers, to show how the three figures diverge:

- 25 migratable units inventoried (`summary.coverage_denominator = 25`).
- 23 of those 25 in the engagement scope for this pass.
- 23 migrated **and** parity-validated.
- 2 documented residual — both blocked on a warehouse artifact dbt does not populate.
- 15 orchestration / EL components that were **never in the denominator** (they are not migratable
  units; they are documented for the orchestration handoff instead).

```
gross_coverage    = 23 / 25 = 92%
in_scope_coverage = 23 / 23 = 100%
residual_pct      =  2 / 25 = 8%
```

Verdict: `residual_pct` of 8% **exceeds the 5% ceiling**, so this migration does not pass on
arithmetic. It passes on a **waiver**, granted with the blocker named: the 2 residual units depend on
a warehouse artifact dbt does not populate, so they cannot be built in dbt without an upstream
change. Reported honestly: *92% gross coverage, 100% of the agreed scope, 8% residual under
waiver.*

Note what the rejected single formula would have produced here:
`23 / (25 − 2) = 100%` — a silent pass, with the two blocked units and the fact that a human never
accepted anything both invisible. Nothing about the migration would have been different; only the
reporting.

The 15 orchestration/EL components appear in **neither** figure. They are out of scope by
classification, not unmigrated work, and must never be added to the denominator to make a percentage
look better or worse.

## BLOCKED - infrastructure dependency (not a code issue)

Some models cannot reach parity until an **infrastructure** dependency is resolved (a datashare not
provisioned, a source system not yet available in the target). Calling these FAIL misrepresents the
migration to stakeholders. Record them **separately** with the specific ask, but they **stay in the
denominator**: BLOCKED is a labelled kind of documented residual, not a way out of the count.

| Model | Legacy coverage | Blocker | Ask |
|---|---|---|---|
| `rpt_risk_in_force` | 3% | source datashare absent | provision it in the target environment |
| `rpt_claims_tsi` | 1% | only snapshot data available | provision the production datashare |

BLOCKED units count toward `documented_residual` and therefore toward `residual_pct`. If they push
`residual_pct` above 5%, the migration passes only on a [waiver](#waivers-residual-above-the-ceiling)
that names each blocker and its ask. Do **not** compute `PASS / (total - BLOCKED)`: it is the same
rejected subtract-from-the-denominator formula, and it would let any unfinished unit pass by being
relabelled BLOCKED.

What the label adds is the reason. Ordinary residual is in-scope work still being explained or fixed;
BLOCKED is out of your hands until the infrastructure lands. Never fold BLOCKED into FAIL, and list it
in its own table under the residual section of the report so the ask is visible.

## Report template

Append to `migration_changes.md` (or write `coverage_report.md`):

```markdown
## Coverage

- Migratable units inventoried (denominator, from `01_inventory.json`
  `summary.coverage_denominator`): N
- Units in engagement scope this pass: S
- Migrated & validated: M
- Documented residual: R

- **gross_coverage: M/N = XX.X%**   ← the gate figure (≥95%)
- **residual_pct: R/N = XX.X%**     ← the ceiling figure (≤5%)
- in_scope_coverage: M/S = XX.X%    ← context only, not "the" coverage number

- Out of denominator (never migratable units): E EL/ingestion, C control-flow, B bridges

### Migrated (M)
- <unit> → <dbt object> — parity: pass

### Residual — needs human review (R)
| Legacy unit | Why not auto-migrated | Recommended action |
|-------------|-----------------------|--------------------|
| <unit>      | dynamic SQL           | manual rewrite     |

### Coverage waiver
<!-- Required only when residual_pct > 5%. Omit the section entirely if within the ceiling. -->
| Residual unit | Blocking reason | Accepted by | Date |
|---------------|-----------------|-------------|------|
| <unit>        | <specific blocker> | <name> | YYYY-MM-DD |
```

All three figures are emitted every time, even when `residual_pct` is 0 and `in_scope_coverage`
equals `gross_coverage`. Dropping a figure because it is uninteresting this run is how the
single-number habit comes back.
