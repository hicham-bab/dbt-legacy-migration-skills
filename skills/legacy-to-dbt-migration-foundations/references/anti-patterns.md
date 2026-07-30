# Migration anti-patterns: why lift-and-shift creates tech debt

A migration that "gives the same results" is not done. Reproducing the legacy tool's shape one-for-one
(the lift-and-shift) usually produces dbt that technically runs but throws away the reasons dbt works:
lineage, testability, incrementality, and reviewability. This catalog names the common anti-patterns,
the idiomatic alternative, and why. It is both migration guidance and enablement content for the
mindset shift, and it backs the automated quality bar (`scripts/lint_idiomatic.py`, see below).

| Anti-pattern | Why it is a problem | Idiomatic dbt instead |
|---|---|---|
| **Pre/post-hook overuse** (every `preSQL`/`postSQL`, `INSERT`/`DELETE`/`MERGE` side-effect ported to a hook) | Hooks are invisible to lineage, hard to test, and run imperative SQL outside the model DAG, the same opacity you are migrating away from | Put transformation logic in the model (a CTE), assertions in a **test**, reusable SQL in a **macro**, history in a **snapshot**. Reserve hooks for true side-effects with no model form (grants, cache warmups) |
| **Monolithic model** (one giant model reproducing a whole job/proc) | Nothing is independently testable or reusable; a change re-runs everything; review is impossible | Decompose into staging -> (intermediate) -> mart; each step named for what it does and testable |
| **Hardcoded relations** (`from db.schema.table`) | Breaks lineage, environment portability, and `dbt run` ordering | `{{ ref('model') }}` and `{{ source('src','table') }}` only; no `database.schema.table`, no DDL in models |
| **Kept control-flow** (cursors, loops, `EXECUTE IMMEDIATE`, `CALL`, row-by-row logic) | The warehouse cannot express it well and it defeats set-based performance | Set-based SQL; a full-population rebuild or an incremental model, not procedural iteration |
| **1:1 thin intermediates** (one `int_` per legacy step, chained) | Produces long chains of trivial models where the logic belonged together | Consolidate related logic into purposeful intermediate models; layering depth is per-workload, not a fixed template (see [layer-classification.md](layer-classification.md)) |
| **Same-results-only mindset** (parity is the only goal) | Passes parity while carrying forward every legacy quirk as permanent debt | Parity is the floor, not the finish. Also choose the model shape deliberately (see [target-modeling.md](target-modeling.md)), add tests/docs/contracts, and prove it against the evaluator |
| **No tests or docs** | The migration is unverifiable and unmaintainable | Tests on the grain (unique/not_null) + accepted_values/relationships; descriptions on models and key columns |

## The quality bar (enforce it, don't just advise it)

Idiomatic quality is a **required gate**, not a suggestion. After building the migrated project, run
both and resolve findings (or record a justified exception):

```bash
python3 scripts/lint_idiomatic.py <project-dir>        # deterministic anti-pattern gate (this catalog)
dbt build --select package:dbt_project_evaluator       # dbt-labs best-practice gate
```

`lint_idiomatic.py` flags hooks, hardcoded relations, kept control-flow, monoliths, and missing
layering/tests, and exits non-zero on any error-severity finding. A migration is "done" only when it
passes the quality bar (or its exceptions are documented and justified), not merely at >=95% coverage
with matching results. See [coverage-report.md](coverage-report.md).
