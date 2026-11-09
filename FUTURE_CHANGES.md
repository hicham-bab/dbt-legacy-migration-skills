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

## Port the 10-step workflow to the other source skills

**Status:** only `migrating-matillion-to-dbt` implements the shared 10-step workflow in the
foundations `SKILL.md` ("The shared 10-step workflow"). The foundations skill carries a note
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
4. Keep `evals/run_evals.py` passing, and add checks for the new summary fields.

**Order:** Informatica and Talend first (both have Harbor tasks and simple parsers), then stored
procedures and Coalesce (Harbor tasks), then DataStage and SnapLogic.

**When all six are done:** remove the "Current state" note from the foundations `SKILL.md`.
