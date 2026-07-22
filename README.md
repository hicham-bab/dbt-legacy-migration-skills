# dbt legacy migration skills

[![evals](https://github.com/hicham-bab/dbt-legacy-migration-skills/actions/workflows/evals.yml/badge.svg?branch=main)](https://github.com/hicham-bab/dbt-legacy-migration-skills/actions/workflows/evals.yml)
[![eval checks](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/hicham-bab/dbt-legacy-migration-skills/main/evals/results.json)](evals/RESULTS.md)

A set of agent skills that migrate legacy ETL/ELT workloads to dbt — mapping the original
workload, translating it into dbt with best practices (tests, docs, contracts), validating the
result against real warehouse data, choosing cost-aware materializations for the target cloud, and
reporting a legacy-vs-dbt cost comparison. Each targets **≥95% coverage** of the migratable
workload, with the residual explicitly flagged for human review.

Built for the [dbt Wizard](https://docs.getdbt.com/docs/dbt-ai/about-dbt-wizard-cli) CLI; the
skills are plain `SKILL.md` folders and work in any agent that supports the skill format
(e.g. Claude Code).

## Skills

| Skill | Migrates |
|-------|----------|
| [`migrating-informatica-to-dbt`](migrating-informatica-to-dbt) | Informatica PowerCenter workflows/mappings (XML repository export) |
| [`migrating-talend-to-dbt`](migrating-talend-to-dbt) | Talend ETL jobs (`.item` XML exports) |
| [`migrating-stored-procedures-to-dbt`](migrating-stored-procedures-to-dbt) | SQL stored procedures (Snowflake, BigQuery, Databricks, T-SQL, PL/SQL) |
| [`migrating-matillion-to-dbt`](migrating-matillion-to-dbt) | Matillion pipelines/jobs — DPC YAML (`.tran.yaml`/`.orch.yaml`), Matillion ETL JSON (export + git per-job forms), CDC/streaming, shared jobs |
| [`migrating-coalesce-to-dbt`](migrating-coalesce-to-dbt) | Coalesce.io projects (Git-committed YAML nodes) — Source/Stage/Dimension(SCD1/2)/Fact/View nodes → models, snapshots, sources |
| [`legacy-to-dbt-migration-foundations`](legacy-to-dbt-migration-foundations) | *Shared reference library* — not invoked directly; the four migration skills link to it |

## How they fit together

The four migration skills share the same 8-step workflow and defer the common steps to
`legacy-to-dbt-migration-foundations`:

- **Step 0** — Detect environment & cloud (Snowflake / Databricks / BigQuery / Redshift; Fusion vs Core)
- **Step 1** — Inventory & map the legacy workload *(source-specific)*
- **Step 2** — **Choose the target modeling approach** (see below), then classify the workload into it + detect Mesh
- **Step 3** — Translate to dbt SQL for the chosen modeling approach, with cost-aware materializations *(source-specific answer key)*
- **Step 4** — Apply best practices: tests (`arguments:` spec), docs, contracts, snapshots
- **Step 5** — Validate: `dbt compile` gate (free), then **legacy-prod vs dbt-dev** data parity (explain every difference)
- **Step 6** — Cost comparison: **measured** warehouse consumption (legacy vs dbt), auditable
- **Step 7** — Coverage report (confirm ≥95%, flag residual)
- **Step 8** — Document changes in `migration_changes.md`

Each migration skill carries a `references/` folder with two source-specific docs: how to parse
the source artifact, and the component/transformation → dbt answer key. All generated SQL is dbt
Fusion-conformant (`cast()` not `::`, `coalesce()` not `nvl`/`ifnull`, tests via the `arguments:`
nested spec).

**Uses the dbt package ecosystem** (all Fusion-checked): **codegen** to scaffold sources/models/YAML,
**audit_helper** to prove legacy-vs-dbt parity, **dbt_utils** + **dbt_expectations** for tests,
**dbt_project_evaluator** as the quality gate, **datavault4dbt**/**dbt_date** per modeling approach — see
`legacy-to-dbt-migration-foundations/references/dbt-packages.md`.

## Target modeling approach (Step 2)

After mapping the legacy workload, the skill **asks which target modeling approach to build**,
then generates the dbt models accordingly:

- **Layered (default)** — faithful source-aligned staging → intermediate → mart. Lowest risk.
- **Data Vault 2.0** — hubs / links / satellites via the [datavault4dbt](https://github.com/ScalefreeCOM/datavault4dbt)
  package, with dimensional info marts on top.
- **Kimball dimensional** — conformed dimensions + fact tables, SCD2 via snapshots, surrogate keys.
- **Star schema (pragmatic)** — facts + dimensions for a focused subject area.

The generation for each paradigm lives in the **shared foundations skill's references** — not as
separate skills — so the install is just the four migration skills + foundations:
`legacy-to-dbt-migration-foundations/references/target-modeling.md` (legacy→paradigm mapping +
performance), `building-datavault.md`, `building-kimball.md`, `building-starschema.md`.

> **Data Vault path:** `building-datavault.md` is **distilled** from Scalefree's
> [datavault4dbt agent skills](https://github.com/ScalefreeCOM/datavault4dbt-agent-skills)
> (Apache-2.0) — see [ATTRIBUTION.md](ATTRIBUTION.md). The `datavault4dbt` **package** itself is
> installed on demand when Data Vault is chosen (see `dbt-packages.md`). For deeper Data Vault
> coverage, install Scalefree's full skill set separately. Kimball and star need nothing extra.

## Install

**One command** — installs (or updates) all five skills, then restart your agent:

```bash
git clone https://github.com/hicham-bab/dbt-legacy-migration-skills.git
cd dbt-legacy-migration-skills && ./install.sh          # dbt Wizard (~/.dbt/wizard/skills)
#                                  ./install.sh --claude # Claude Code (~/.agents/skills)
```

`install.sh` copies just the five skill folders into your skills directory and leaves everything
else untouched. **It's safe to re-run to update** — it cleanly replaces only these folders. (Use
`--dest <path>` for a custom location.) After it finishes, **restart the agent** so it reloads the
skill list.

<details><summary>Alternatives (no script)</summary>

- **From inside dbt Wizard**, ask it to install with the built-in installer:
  `install-skill-from-github.py --repo hicham-bab/dbt-legacy-migration-skills --path legacy-to-dbt-migration-foundations migrating-informatica-to-dbt migrating-talend-to-dbt migrating-stored-procedures-to-dbt migrating-matillion-to-dbt`
  (clean download; note it aborts if a skill folder already exists, so remove the old ones first when updating).
- **Manual copy:** `cp -R {legacy-to-dbt-migration-foundations,migrating-*} ~/.dbt/wizard/skills/`.

</details>

Install **all five together** — the four migration skills reference
`legacy-to-dbt-migration-foundations` by relative path, so it must sit alongside them.

## Usage

Once installed, ask the agent to migrate a project and point it at the source artifacts, e.g.:

- "Migrate this Informatica workflow export to dbt" (point at the `.XML`)
- "Migrate these Talend jobs to dbt" (point at the `.item` folder)
- "Migrate this stored procedure to a dbt model and prove parity"
- "Migrate this Matillion pipeline to dbt" (point at the `.tran.yaml`/`.orch.yaml` or METL JSON)
- "Migrate this Coalesce project to dbt" (point at the cloned Coalesce Git repo)

The skill runs the 8-step workflow, asks which cloud you're targeting, and produces the dbt
models, tests, docs, a parity check, a cost comparison, and a coverage report.

## Scope & caveats

- **Only transformation logic migrates to dbt.** Ingestion/extract-load (Informatica sessions
  loading files, Talend `tFileInput`/`tFTP`, Matillion S3 Load / connector queries / CDC capture)
  and control-flow/scheduling have no model equivalent — the skills map those to `sources` and a
  scheduler, and exclude them from the coverage denominator rather than force-fitting them.
- **Compilation is not correctness.** Every skill treats `dbt compile` as the fast iteration gate
  and **data parity against the warehouse** as the proof a migration preserved business logic.
- Dynamic SQL, non-deterministic procedural logic, and proprietary runtime components are routed
  to the flagged residual, not guessed at.

## Eval results

Every push and PR runs a deterministic eval harness over the skills' inventory **parsers** (the step
that reads a legacy export and produces the workload inventory). CI fails on any regression, so the
badges above reflect the live state of `main`.

- **Published breakdown:** [`evals/RESULTS.md`](evals/RESULTS.md) — per-check results by source,
  refreshed by CI on every push to `main`.
- **How it's checked:** [`evals/README.md`](evals/README.md) — fixtures, methodology, and the
  "verified against real vendor exports" discipline behind the numbers.
- **Reproduce locally:** `pip install pyyaml && python3 evals/run_evals.py` (add `--write` to
  regenerate the report + `results.json`).

Two layers of evals:

- **Parser evals** (above) — deterministic unit checks over the inventory parsers, gated in CI.
- **Agent eval** — [`harbor/`](harbor/) holds a [Harbor](https://github.com/harbor-framework/harbor)
  task that runs a whole agent *following the skills* against a real stored-procedure migration in a
  container (targeting DuckDB, no cloud creds) and scores whether the output matches the legacy
  result **row-for-row**. Verified solvable: the oracle solution scores reward 1, a broken migration
  scores reward 0.

## License

Apache-2.0. See [LICENSE](LICENSE).
