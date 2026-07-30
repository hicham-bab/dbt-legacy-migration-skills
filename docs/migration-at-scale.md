# Legacy migration at scale: accelerator or check-the-box?

This doc answers a fair, direct question from the field: is the migration-skills work a genuine
migration accelerator that teams with thousands of jobs can depend on, or a check-the-box "we have
something" that risks creating more technical debt? It sets an honest stance, shows what already
exists, names the gaps, and lays out how we earn the "at scale" claim rather than assert it. Audience:
customer-facing SAs, RAs, and the enablement/training team.

## Honest stance

Today this is a **strong, guardrailed, single-workload migration accelerator.** It migrates a given
Informatica / Talend / Matillion / Coalesce / stored-procedure workload to idiomatic dbt with tests,
docs, data-parity proof, and a coverage report. **At-scale dependability across a large estate is a
roadmap we are earning through a pressure-test, not a claim we make yet.** Saying that plainly is the
point: we would rather prove it on a real estate than overclaim.

## What it already does (answers two common worries)

- **It is project-level, not file-by-file.** The skills inventory the whole workload and build a
  dependency graph (column-level lineage, cross-job edges), classify layers by topology, detect a
  producer/consumer (Mesh) split, and present the full scope before building. dbt Wizard adds its
  project context on top of that.
- **It is designed to not lift-and-shift.** Anti-monolith and "don't 1:1 echo the source" guidance,
  set-based-not-control-flow translation, `ref()`/`source()`/no-DDL rules, and a deliberate choice of
  target model shape are all built in. Quality is proven on multiple axes: coverage >=95%, row-for-row
  data parity (audit_helper), measured cost comparison, and a five-dimension evaluation harness
  (build, parity, coverage, structural, LLM-judge).

## The tech-debt guardrail (Phase A, shipping now)

The real risk the field raised is a migration that "gives the same results" but carries forward
technical debt (hook-laden, monolithic, hardcoded, legacy control-flow copied over). We are hardening
the guardrails from advice into an **enforced quality bar**:

- A deterministic anti-pattern linter (`scripts/lint_idiomatic.py`) that fails the migration on
  pre/post-hook overuse, hardcoded `db.schema.table` relations, kept control-flow, monolithic models,
  and missing layering/tests.
- Paired with `dbt_project_evaluator`, run as a required gate. A migration is "done" only when it
  clears the bar, not merely when results match. See `references/anti-patterns.md`.

This directly targets the failure mode we have seen in prior lift-and-shifts.

## The gaps we are closing to earn "at scale"

- **Estate management (biggest gap).** Batch inventory across thousands of jobs, prioritization into
  waves, a global dependency DAG, and a progress ledger. Today the flow is one workload at a time.
- **Remediation.** A path that ingests an already-badly-migrated dbt project and refactors it to
  idiomatic dbt while preserving parity, not just greenfield legacy-to-dbt.
- **Proof at volume.** A pressure-test on a real estate with honest accelerator metrics.

## Waste Management: the beachhead

Waste Management is the right place to pressure-test, two tracks:

1. **Accelerate** the outstanding Matillion estate ahead of the 2-3 year deprecation, in prioritized
   waves, with the quality bar enforced so we do not repeat the earlier lift-and-shift.
2. **Remediate** the projects already migrated badly (pre/post-hook misuse, no dbt idioms) into
   maintainable dbt.

This gives the two RAs already pushing Wizard a concrete, measurable proof point instead of a claim.

## The metrics we will report (so the answer is evidence, not opinion)

On the pressure-test we will measure and publish:

- **% auto-migrated to parity** (no human intervention),
- **% needing human fix** and the nature of the fixes,
- **coverage** and **quality-bar pass rate** (idiomatic, not just correct),
- **throughput per wave** (jobs migrated per unit effort).

If these numbers hold on a real estate, "dependable accelerator" is earned. If they do not, we learn
exactly where the nuance breaks before overpromising.

### Running the pressure-test (the instrument is built; the estate is the input)

The measurement apparatus exists and is validated; the pressure-test is now a matter of pointing it
at a real estate. The procedure:

1. **Plan the estate** - `scripts/inventory_estate.py <estate-dir>` produces the waved backlog + ledger
   (see [estate-planning.md](../skills/legacy-to-dbt-migration-foundations/references/estate-planning.md)).
2. **Run the agent per job**, wave by wave. Each job is migrated by the **dbt Wizard** (not the oracle)
   and scored by the harbor scorer, which writes a per-job scorecard.
3. **Aggregate the dependability metrics** - `harbor/_scorer/estate_report.py --runs <scorecards-dir>`
   (or `--scorecard <run_all output>`) computes auto-to-parity %, human-fix %, quality-bar pass %, and
   the per-wave breakdown into `estate_dependability.md`.

The report carries an explicit caveat: **the numbers only mean "accelerator" when the jobs were solved
by the agent, not by the oracle reference solutions** (which pass by construction). Validation runs on
a synthetic estate and on the built oracle tasks confirm the instrument; they are not accelerator claims.

**Status:** the instrument (`inventory_estate.py`, the harbor scorer, `estate_report.py`) is complete
and validated. The Waste Management pressure-test is blocked only on a **sanitized slice of the WM
Matillion estate** to use as the input; once that lands, this same pipeline produces the real numbers.

## Not autopilot: enablement pairing

The tool is an accelerator with guardrails and a human in the loop, not a replacement for judgment.
It pairs with the training team's mindset-shift enablement (why dbt does things the way it does);
`references/anti-patterns.md` is written to double as that content. Coordinate with the training team
(and Mariano) so the tool and the enablement land together.

## Status and next steps

- **Now:** Phase A quality bar (anti-pattern linter + enforced gate + guidance fixes) is implemented.
- **Next:** remediation capability, then estate-scale batching/prioritization, then the Waste
  Management pressure-test with the metrics above.
- **Ask:** a sanitized slice of the Waste Management Matillion estate to use as the pressure-test
  fixture, and a working session with the training team / Mariano on the enablement pairing.
