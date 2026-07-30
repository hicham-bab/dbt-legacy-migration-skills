# Planning a migration at estate scale (Step 0.5)

A single migration is one workload. A real customer estate is **hundreds or thousands of jobs** across
one or more tools, often with a multi-year deprecation deadline. Migrating them one-at-a-time with no
plan is how estates stall. Before Step 1, when the input is a whole export directory rather than a
single artifact, **plan the estate**: inventory everything, sequence it into waves, and track progress.

## Inventory the whole estate

Run the batch inventory over the export directory. It discovers and classifies every artifact
(Talend / Informatica / Matillion / Coalesce / stored procedures), runs the matching per-source parser,
and aggregates one normalized backlog:

```
python3 <skills-dir>/legacy-to-dbt-migration-foundations/scripts/inventory_estate.py <estate-dir>
```

Outputs (in the estate dir, or `--out <dir>`):

- **`estate_backlog.md`** - every job with its tool, kind, **complexity**, **risk** (high if SCD2,
  dynamic SQL, or large), **SCD2** flag, dependencies, and assigned **wave**.
- **`estate_inventory.json`** - the machine-readable backlog (per-job records + summary + waves).
- **`estate_ledger.json`** - a seeded progress ledger (every job `pending`), written only if absent
  so it is never clobbered.

## Sequence into waves

Waves are **dependency-ordered**: a job whose upstream (within a tool, e.g. a Coalesce stage feeding a
dimension, or a Talend `tRunJob` chain) is in the estate lands in a later wave than its dependency.
Within a wave, jobs are ordered simplest-first, so early waves are quick wins that build momentum and
prove the pattern before the hard ones.

Use the backlog to pick a **first wave** deliberately: low-risk, low-complexity, high-value jobs that
exercise the full path (migrate -> parity -> quality bar) end to end. Tackle high-risk jobs (SCD2,
dynamic SQL, dense dependencies) in later waves once the team and the patterns are proven.

> Cross-tool dependencies (a job in one tool feeding a table another tool reads) are not inferred
> automatically; note them by hand and adjust wave order where they matter.

## Track progress across waves

Each job still goes through the normal per-workload workflow (Steps 1-8) and must clear the **quality
bar** (see [coverage-report.md](coverage-report.md) and [anti-patterns.md](anti-patterns.md)), so the
estate does not accumulate lift-and-shift debt at scale. Record each job's state in the ledger:

```
python3 <skills-dir>/legacy-to-dbt-migration-foundations/scripts/estate_ledger.py <ledger.json> set <job-id> parity_passed
python3 <skills-dir>/legacy-to-dbt-migration-foundations/scripts/estate_ledger.py <ledger.json> report
```

`report` shows overall parity-passed percent and per-wave progress (done / in flight / needs review),
the number that answers "how far through the estate are we, and what is outstanding".
