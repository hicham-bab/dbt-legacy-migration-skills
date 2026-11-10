# Cutover runbook — parallel run, switchover, decommission (Step 9)

The shared workflow ends at Step 8, "document in `migration_changes.md`". That leaves the migration
built, validated, and still not in use — nothing in the skill set says how the legacy job stops
being the system of record and the dbt project starts. Produce this as `09_cutover_runbook.md`,
after the Step 7 coverage gate and alongside the Step 8
[orchestration handoff](orchestration-handoff.md): the scheduler must exist before you cut over
to it.

## Contents

- [Why cutover is its own phase](#why-cutover-is-its-own-phase)
- [Required input: the downstream consumer inventory](#required-input-the-downstream-consumer-inventory)
- [Parallel run](#parallel-run)
- [Switchover criteria](#switchover-criteria)
- [Rollback](#rollback)
- [Decommission checklist](#decommission-checklist)
- [Output template](#output-template)
- [Don't do these things](#dont-do-these-things)

## Why cutover is its own phase

Step 5 proves parity **once, in dev, against one snapshot of the inputs**. Necessary, not
sufficient. Parity *holding in production over time* is a different claim, and what breaks it only
appears on the clock:

- **Data the dev sample never held** — a late correction, a first null, a new code value, a negative
  amount, a duplicate key.
- **Period-boundary logic** — month-end, quarter-end, fiscal-calendar paths absent from the dev window.
- **Volume** — a query correct at 1% of rows that times out or spills at 100%.
- **Incremental state** — the first run after a full refresh differs from the tenth; late-arriving
  rows outside the lookback window are the classic silent loss.
- **Concurrency and timing** — the run now competes for the warehouse and may read sources mid-load.

So: prove parity in dev, then prove it **repeatedly in production against live inputs** before
anything downstream is repointed.

## Required input: the downstream consumer inventory

You cannot derive this from the legacy export: the export knows what the job *wrote*, not who
*reads* it. It has to be collected from people, and it is the input most often skipped.

| Consumer type | How to find it | Why it matters at cutover |
|---|---|---|
| BI dashboards / reports | Warehouse query history filtered to the legacy target relations; BI tool lineage | Repointing them is the actual switchover |
| Reverse-ETL / activation syncs | The reverse-ETL tool's own source config | Writes to external systems — a wrong cutover is visible to customers |
| Scheduled extracts / file drops | Scheduler inventory; the Step 8 handoff's residual side effects | Often the only consumer nobody remembers |
| Downstream jobs and other pipelines | Query history; the legacy tool's cross-pipeline invocations | May depend on the legacy schema shape, not just its data |
| Humans with saved queries and notebooks | Ask. There is no other way | They break quietly and complain late |

Query history is a strong first pass that misses anything not run recently — a list to confirm, not
the answer. Record the confirmed set as dbt **`exposures`** in the project YAML: an exposure names
the consumer, its owner, and the models it depends on, making the list versioned, visible in the
DAG, and selectable (`dbt build --select +exposure:<name>`) rather than a spreadsheet.

## Parallel run

Both systems run on the same schedule against the same sources, **writing to separate targets**.
Legacy stays the system of record for the whole parallel period.

- **Separate targets, never shared.** Sharing a relation gives you no comparison and a race.
- **Same trigger cadence**, on the same inputs. Daily legacy job → daily dbt job.
- **Compare every cycle, automatically.** Reuse the classification approach from
  [data-validation.md](data-validation.md) — `audit_helper.compare_and_classify_relation_rows`
  (legacy prod as one relation, the dbt output as the other, keyed on the grain), or Pattern A/B if
  packages were declined. A manual eyeball does not accumulate into evidence.
- **Each cycle, record:** row counts both sides, added/removed/modified counts, differing columns,
  runtime, and the disposition of every difference (accepted with a reason, or fixed).

**How many cycles?** Enough consecutive clean cycles to cover **one full business cycle** of the
job, plus margin — not a fixed number of days.

| Job schedule | Suggested minimum parallel window |
|---|---|
| Hourly / intra-day | 2 weeks, and must include a month-end |
| Daily | 1 full month, spanning a month-end close |
| Weekly | 4–6 cycles, spanning a month-end |
| Monthly | 2–3 cycles, and at least one must be a quarter-end if the logic is period-sensitive |

Annual behaviour (fiscal-year roll, annual true-up) will not get a clean cycle. Say so explicitly
and build a targeted historical replay for that path, rather than implying the run covered it.

## Switchover criteria

A checklist tied to artifacts, not to confidence. Every line needs a name and a date.

- [ ] **N consecutive parity-clean cycles** recorded, N per the table above; clean = zero
      *unexplained* differences. Record them in the Step 5 parity artifact — the
      `migration_changes.md` parity section per [data-validation.md](data-validation.md), or a
      structured per-cycle parity file if the project keeps one. Not from memory.
- [ ] **Coverage gate passed** — ≥95% per [coverage-report.md](coverage-report.md), residual
      itemised, each item accepted or assigned.
- [ ] **Orchestration handoff signed off** — scheduler exists, runs, has an owner; every
      `on_failure` edge has a disposition ([orchestration-handoff.md](orchestration-handoff.md)).
- [ ] **Every consumer repointed or dual-reading**, each with a named owner who has *confirmed* —
      not merely been notified.
- [ ] **Rollback tested**, not merely written down (next section).
- [ ] **Owner and window agreed** — named person on point, slack for a rollback decision, low-risk
      slot in the business calendar. Not the day before close.
- [ ] **Freshness and volume monitoring live** on the new targets *before* switchover.
- [ ] **Test floor confirmed** — `preflight_decisions.py tests` run on a machine with Python reports
      no gaps, or every gap has a reason in the `migration_changes.md` coverage table (see
      [dbt-best-practices.md](dbt-best-practices.md#minimum-test-floor-for-a-migration)). If the
      migration was built on the dbt platform, run it locally once before switchover. Do not
      require `--strict` or write placeholder tests to silence a flag: the logic detection is
      pattern-based, and a stated reason is the correct answer to a false alarm.
- [ ] **Mock sources removed** (only if `inputs.test_source_mode` was `seeds`) — every mock seed,
      its `dbt_project.yml` config, and each substitution var, listed by name. See
      [test-sources-and-mock-data.md](test-sources-and-mock-data.md#removal-before-production).

## Rollback

**Trigger conditions** — agree in advance, in writing, with thresholds; deciding mid-incident
whether it is bad enough is how a two-hour problem becomes a two-day one. Typical: parity break
above tolerance on a production run; a consumer-visible correctness error; the run missing the
business window; a downstream system rejecting the output.

**Procedure** — re-enable the legacy schedule, repoint consumers back, confirm the legacy run
reproduces the current period end to end. If the dbt project wrote into relations the legacy job
also uses, restoring those is part of the procedure, written out step by step.

**Test it during parallel run, while legacy is still live.** Rehearse the full sequence — disable,
repoint, verify — in a controlled window, and time it. After decommission there is no rollback,
only a rebuild on an unknown timeline under pressure. An untested plan is a paragraph, not a
capability.

## Decommission checklist

Deliberately slow and deliberately reversible, in this order. Do this in a **separate change
window** from switchover, days or weeks later.

1. **Disable the legacy schedule — do not delete it.** Pause the trigger; the definition stays
   intact and runnable. This is the step that keeps rollback possible.
2. **Retain the legacy job read-only** for an agreed period (30–90 days is common — agree the
   number). Revoke write/edit rights so it cannot be resumed or altered by accident.
3. **Retain the legacy target tables** for the same period, then drop. Snapshot or export first if
   any retention or audit obligation applies. Never drop on the day you disable.
4. **Reclaim credentials and licences last** — after the retention window closes. Revoking early is
   an untested rollback dependency.
5. **Write a dated record of what was removed** — object names, dates, who authorised each step,
   where any export lives. Six months on, "why is this table gone" needs an answer.

## Output template

Write `09_cutover_runbook.md`:

```markdown
# Cutover runbook

## Scope
- Legacy job(s) retired: … | dbt selector replacing them: `dbt build --select …`
- Cutover owner / rollback decision-maker:

## Downstream consumers
| Consumer | Type | Owner | Repoint action | Confirmed (date) | Exposure recorded |
|---|---|---|---|---|---|

## Parallel run
- Legacy target: … | dbt target: … (separate) | Cadence: … | Required clean cycles: N (rationale)
- Comparison method: [audit_helper classify / Pattern A / Pattern B]

| Cycle | Date | Rows legacy | Rows dbt | Added | Removed | Modified | Unexplained | Verdict |
|---|---|---|---|---|---|---|---|---|

- Paths the parallel run could not cover (annual/rare) + how they were tested instead:

## Switchover
- Criteria checklist: [all boxes, with names and dates]
- Window: … | Comms to: … | Monitoring in place: … | Steps, in order:

## Rollback
- Trigger conditions + thresholds: … | Procedure, step by step: …
- **Rehearsed on: [date] — by: [name] — elapsed: [duration]**

## Decommission (separate window, date: …)
| Step | Object / asset | Date | Authorised by | Retention until | Export location |
|---|---|---|---|---|---|

## Open risks
```

## Don't do these things

- **Don't cut over on a single clean parity run.** One clean cycle proves the code ran once. The
  criterion is N consecutive clean cycles covering a full business cycle including a month-end.
- **Don't decommission in the same change window as switchover.** Collapsing them removes your only
  fallback at the exact moment you are most likely to need it.
- **Don't skip the consumer inventory.** It is not in the legacy export, so if you did not ask
  people, you do not have it — and the consumer you missed is the one that breaks.
- **Don't test rollback after the legacy system is gone.** Rehearse it during parallel run while
  legacy is still live and warm.
- **Don't treat "the dashboard still loads" as verification.** A dashboard reading a stale or
  half-populated relation loads fine. Verify row counts and one known figure per consumer.
