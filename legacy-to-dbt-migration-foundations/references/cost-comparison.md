# Cost comparison: legacy run vs dbt dev run (Step 6)

Produce two views of cost: a **TCO summary** (annualized ownership) and a **measured dev-run**
comparison (actual compute of running the migrated models vs the legacy job). TCO model adapted
from `~/talend-to-dbt/src/talend_to_dbt/cost/comparator.py`; the measured-run capture uses each
platform's query history.

## Contents

- [A. TCO summary](#a-tco-summary)
- [B. Measured dev-run compute](#b-measured-dev-run-compute)
- [Report template](#report-template)

## A. TCO summary

Compare annual cost of the legacy stack vs the dbt-on-warehouse stack. Ask the user for the inputs
you don't know; label every assumption.

**Legacy annual cost** = license/subscription (Informatica/Talend tier, or the DB engine hosting
the procs) + infrastructure (ETL server / integration runtime) + maintenance FTE (the analyst/
engineer time spent babysitting jobs).

**dbt annual cost** = warehouse compute (the recurring transform cost) + storage + dbt platform
seats.

Then report: annual savings ($ and %), one-time migration effort (hours × blended rate), and
payback period (migration cost ÷ annual savings). The Oracle project's `MIGRATION_TIME_ESTIMATE.md`
gives a defensible effort framing (with-skill ≈ 1 week vs manual 4-8 weeks).

Per-platform recurring compute rates are estimates — state them explicitly and let the user
override with their contracted rates.

## B. Measured dev-run compute

This is the concrete "legacy run vs dbt dev run" number. After the models build cleanly in dev
(Step 5), capture the actual compute the dbt run consumed and compare it to the legacy job's
measured run.

Capture the dbt dev-run cost per platform:

- **BigQuery** — bytes billed per model. Query `INFORMATION_SCHEMA.JOBS_BY_PROJECT`:
  `select job_id, total_bytes_billed from region-us.INFORMATION_SCHEMA.JOBS_BY_PROJECT
   where creation_time > <run_start>` — convert bytes → $ at the on-demand rate.
- **Snowflake** — warehouse-seconds → credits. Query `SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY`
  (or `WAREHOUSE_METERING_HISTORY`) for the run window; credits × credit price.
- **Databricks** — DBUs consumed by the SQL warehouse/cluster over the run window (system billing
  tables / SQL warehouse monitoring); DBUs × DBU rate.
- **Redshift** — for serverless, RPU-hours from `SYS_SERVERLESS_USAGE`; for provisioned, prorate
  cluster cost over the run duration.

Run the capture via `dbt show` / the dbt MCP `execute_sql` tool. Compare against the legacy run
metrics the user supplied (runtime × server/warehouse rate, or the vendor job cost). If the user
has no legacy metrics, report the dbt dev-run cost alone and fall back to the TCO estimate for the
legacy side.

**Point out the structural savings**, not just the number: incremental materializations (vs the
legacy full rebuild), partition/cluster pruning, and dev warehouses that auto-suspend are usually
where the win comes from — tie the savings back to the materialization choices from Step 3.

## Report template

Write this to `cost_comparison.md`:

```markdown
# Cost Comparison — <source system> → dbt on <platform>

## TCO (annual)
| Line item        | Legacy    | dbt on <platform> |
|------------------|-----------|-------------------|
| License / seats  | $         | $                 |
| Infrastructure   | $         | —                 |
| Compute          | (bundled) | $                 |
| Storage          | —         | $                 |
| Maintenance FTE  | $         | $                 |
| **Total / yr**   | **$**     | **$**             |

- Annual savings: $X (Y%)
- Migration effort: N hours (~$Z)
- Payback period: P months

## Measured dev run (this migration)
| Metric                 | Legacy run | dbt dev run |
|------------------------|------------|-------------|
| Runtime                |            |             |
| Compute (credits/bytes/DBUs) |      |             |
| Estimated $ per run    | $          | $           |

Assumptions: <list every rate and estimate used>
```
