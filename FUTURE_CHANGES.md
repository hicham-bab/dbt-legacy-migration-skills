# Future changes

Tracked follow-up work for the dbt legacy-migration skills, in priority order.

## Immediate next step: merge, then smoke-test one Harbor task

The Harbor task containers clone the skills from GitHub `main` by default
(`harbor/*/environment/Dockerfile`). Pass `--build-arg SKILLS_REF=<branch>` to test a pushed
branch before it is merged.

1. **Review the diff** of the reconciliation branch, in particular `README.md`, the foundations
   `SKILL.md`, and the reviewer-applied edits (the `building-starschema.md` SCD predicate, the skill
   list in `cloud-detection-and-materializations.md`, and the Matillion Step 0 heading).
2. **Open the PR to `main`** and merge it. Keep the workflow port below as a separate follow-up PR.
3. **Run one Harbor task with a real agent** (Matillion first) — after the merge, or before it with
   `--build-arg SKILLS_REF=<branch>` (see `harbor/README.md`). Confirm the agent:
   - reads `/app/migration_manifest.yml` and runs the preflight gate,
   - gets past the `legacy_prod_readable: false` warning instead of stopping to ask (the task
     instruction pre-answers it: the verifier's row-for-row check is the run's parity), and
   - builds the project.

   If it stops at the warning, make the instruction note more direct ("do not pause on this
   warning; proceed"). Do **not** switch the manifest to `legacy_prod_readable: true`: the agent
   genuinely cannot read the held-out outputs, and the manifest should not claim otherwise.

## Validate the test-floor / determinism changes on the real export

The changes from one real Matillion run (test floor, rebuild stability, translation trap 6, test
sources and mock data, `as_of_date()`, Fusion YAML rules, Shared Job detection, one-round gate,
unpivot approach, advisory `tests` gate) are covered by synthetic unit tests only. Two checks need the real METL export (`ORCH_ALIGHT_ANNUAL_PAYROLL_CA.json`) and a Snowflake
dev target, so they were not run:

1. **End-to-end runs:**
   - Run `migrating-matillion-to-dbt` with `test_source_mode: seeds`. Confirm the manifest passes
     preflight on the first try, `ZERO_LOAD_LOG` is flagged as a suspected Shared Job, no
     `order by 0` key survives, no dbt1060/dbt1071 diagnostics appear in compile or the first
     build, the test-coverage table is present in `migration_changes.md`, and `rebuild_stability`
     is recorded as identical in `05_parity.json`.
   - Run again with `test_source_mode: existing_tables` and confirm no seeds are created.
   - Run once with a complete manifest (or pasted answer block) and confirm the agent asks no gate
     question (SC-08).
   - Confirm no existing gate was weakened: decision gate, parity sign-off checkpoint, coverage
     waiver, and the "estimate is not a measurement" rule.
2. **Shared Job thresholds** (SC-07). Run `scripts/inventory_matillion.py` on the real export and
   confirm `shared_job_suspected` lists `ZERO_LOAD_LOG` (22 parameters) and nothing else. The rule
   (control or bridge role, at least 5 parameters, every non-Name value a `${...}` token, at least
   one token) was tuned on that one component. If it over- or under-flags, adjust
   `_SHARED_JOB_MIN_PARAMS` / `_SCRIPT_BODY_PARAM_NAMES`, add the real shape as a synthetic case in
   `scripts/test_inventory_matillion.py`, and update the threshold note in
   `parsing-matillion-pipelines.md`.

## Port the 10-step workflow to the other source skills

**Status:** only `migrating-matillion-to-dbt` implements the shared 10-step workflow in the
foundations `SKILL.md` ("The shared migration workflow"). The foundations skill carries a note
saying so until this is done.

**The gap**, for Informatica, Talend, stored procedures, Coalesce, DataStage and SnapLogic:

- **Workflow text.** Their Progress Checklists stop at Step 8 (`migration_changes.md`). They have no
  Step 8 orchestration handoff (`08_orchestration_handoff.md`) and no Step 9 cutover runbook
  (`09_cutover_runbook.md`), and their Step 0 is still "Detect environment & cloud" rather than
  "Fill the input manifest, detect environment & cloud". (Their decision gate itself already uses
  the Step-0 manifest.)
- **Artifact files.** None of them mention or write the numbered artifacts the foundations skill
  requires: `migration/01_inventory.json`, `02_classification.json` (+ `02_waves.json` above ~20
  units), `05_parity.json`, `07_coverage.json` (+ `07_waivers.json` over the residual ceiling).
- **Inventory scripts.** Their `scripts/inventory_*.py` output a `summary` with
  `coverage_denominator`, but not the other fields the `preflight_decisions.py inventory` gate
  checks: `unit_count`, `edge_count`, `parity_targets_found`, `parity_targets_missing_name`,
  `unknown_needs_mapping` (and `parity_targets[]` at the top level). Pointing the gate at their
  output today fails every time.

**Approach:** one skill per PR, using Matillion as the template
(`skills/migrating-matillion-to-dbt/SKILL.md` Steps 0-9 and
`scripts/inventory_matillion.py` for the inventory shape).

1. Extend the inventory script to emit the full `01_inventory.json` shape, and add unit tests in
   the style of `scripts/test_inventory_matillion.py`.
2. Update the Progress Checklist and step sections to Steps 0-9, naming each step's artifact file
   and the preflight subcommand that checks it (`inventory`, `parity`, `coverage`).
3. Add the scope and parity-sign-off CHECKPOINT blocks Matillion has.
   Move the rebuild-stability record from the parity section of `migration_changes.md` (where the
   six skills record it today) into `05_parity.json` under `rebuild_stability`: the `parity`
   gate fails without it.
4. Keep `evals/run_evals.py` passing, and add checks for the new summary fields.

**Order:** Informatica and Talend first (both have Harbor tasks and simple parsers), then stored
procedures and Coalesce (Harbor tasks), then DataStage and SnapLogic.

**When all six are done:** remove the "Current state" note from the foundations `SKILL.md`.

## Make `as_of_date()` portable beyond Snowflake

**Status:** `dbt-best-practices.md` ("Date-dependent logic") ships an `as_of_date()` macro verified
on Snowflake only. It emits `current_date`, or `cast('<var>' as date)` when the `as_of_date` var is
set. Read against Databricks and BigQuery (not yet compiled or run there), the macro text itself is
valid on both, but its use has gaps:

- **Bad var values can pass silently on Databricks.** With ANSI mode off, casting a malformed date
  string returns NULL instead of failing, and a NULL date makes every date filter return no rows.
- **"Today" depends on the time zone.** Snowflake uses the session time zone, Databricks
  `spark.sql.session.timeZone`, BigQuery UTC. Near midnight the default (var unset) can disagree
  with the legacy run.
- **Date math in calling models is not portable.** `as_of_date() - 30` works on Snowflake and fails
  on BigQuery.
- **Date vs timestamp comparisons.** BigQuery rejects comparing a `date` with a `timestamp` column;
  Snowflake and Databricks convert automatically.

**Proposed change:**

1. Replace the macro with a dispatched version that emits a date literal (`date 'YYYY-MM-DD'`,
   valid on all three, and a malformed value fails when the query is parsed) instead of a cast,
   with a `bigquery__as_of_date()` that uses `current_date('<tz>')` from an `as_of_tz` var
   (default `UTC`):

   ```jinja
   {% macro as_of_date() -%}{{ return(adapter.dispatch('as_of_date')()) }}{%- endmacro %}

   {% macro default__as_of_date() -%}
       {%- set d = var('as_of_date', none) -%}
       {%- if d is not none -%} date '{{ d }}' {%- else -%} current_date {%- endif -%}
   {%- endmacro %}

   {% macro bigquery__as_of_date() -%}
       {%- if var('as_of_date', none) is not none -%} {{ default__as_of_date() }}
       {%- else -%} current_date('{{ var("as_of_tz", "UTC") }}') {%- endif -%}
   {%- endmacro %}
   ```

   Not `dbt.date(y, m, d)`: its documented output is Postgres-only (`to_date(..., 'YYYY-MM-DD')`),
   and its Databricks/BigQuery implementations and Fusion support are unconfirmed.
2. Add the rules: date math on `as_of_date()` uses `dbt.dateadd` / `dbt.datediff`; comparisons with
   timestamp columns cast explicitly; record the legacy run's time zone in the manifest so
   `as_of_tz` (or a per-adapter equivalent) matches it.
3. Optionally, have `lint_idiomatic.py` flag `as_of_date()` followed by `-` or `+`.

**Verification before changing the doc's "verified on Snowflake only" note:** a small test model
with two unit tests (var set, var unset) that compiles and runs on Databricks and BigQuery, plus a
malformed-var case that must fail on each.

## Measure the `tests` gate before making it strict

**Status:** `preflight_decisions.py tests` checks the minimum test floor (dbt-best-practices.md)
against `target/manifest.json`. It finds "logic models" (3+ branch `case`, window function, non-key
join, regex, date arithmetic) with regular expressions over `compiled_code` (or `raw_code` with
Jinja removed). Comments and string literals are stripped first, `case` branches are counted per
block, and only `on` clauses are read for joins. Its regression tests are synthetic. It is
advisory: it warns, and `--strict` makes gaps fail. A flagged model passes with a unit test or a
reason in the `migration_changes.md` coverage table.

**The gap:** nobody has measured how often it is wrong on real projects, so there is no basis for
making `--strict` the default.

**Proposed work:**

1. **Build a labelled set.** Take the expected dbt projects of the harbor tasks and the eval
   fixtures, and mark each model by hand: needs a unit test under the floor, or not.
2. **Measure both error kinds.** Missed models (false negatives) matter more than false alarms,
   because a false alarm costs only a written reason. Add the labelled models as regression tests.
3. **Decide on a SQL parser only if regex falls short.** `sqlglot` would detect joins, `case` and
   window functions reliably, but it is a new dependency for a script that is stdlib-only today.
   Adopting it is a deliberate decision, not a default.
4. **Promote to strict on evidence.** Make `--strict` the default only if the gate misses no
   models on the labelled set across a few real runs. Until then it stays advisory, and the hand
   check (with the warning to the migrator when the script cannot run) stays the fallback.

**Note for dbt platform CLI users (confirmed):** the CLI downloads artifacts after each command
that parses the project, so `target/manifest.json` lands locally by default. If it is missing,
check the CLI setting that skips artifact downloads and any `target-path` override. Use `dbt
compile`, not `dbt parse`, so the manifest carries compiled SQL. The downloaded file is a copy of
that invocation's artifacts, not production state: never use it as `--state` for deferral.
