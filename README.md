# dbt legacy migration skills

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
| [`legacy-to-dbt-migration-foundations`](legacy-to-dbt-migration-foundations) | *Shared reference library* — not invoked directly; the four migration skills link to it |

## How they fit together

The four migration skills share the same 8-step workflow and defer the common steps to
`legacy-to-dbt-migration-foundations`:

- **Step 0** — Detect environment & cloud (Snowflake / Databricks / BigQuery / Redshift; Fusion vs Core)
- **Step 1** — Inventory & map the legacy workload *(source-specific)*
- **Step 2** — Classify into dbt layers (source → staging → intermediate → mart) + detect Mesh
- **Step 3** — Translate to dbt SQL with cost-aware materializations *(source-specific answer key)*
- **Step 4** — Apply best practices: tests (`arguments:` spec), docs, contracts, snapshots
- **Step 5** — Validate: `dbt compile` gate (free), then data parity against the warehouse
- **Step 6** — Cost comparison: TCO + measured dev run
- **Step 7** — Coverage report (confirm ≥95%, flag residual)
- **Step 8** — Document changes in `migration_changes.md`

Each migration skill carries a `references/` folder with two source-specific docs: how to parse
the source artifact, and the component/transformation → dbt answer key. All generated SQL is dbt
Fusion-conformant (`cast()` not `::`, `coalesce()` not `nvl`/`ifnull`, tests via the `arguments:`
nested spec).

## Install

Clone, then copy the skill folders into your agent's skills directory.

dbt Wizard CLI:

```bash
git clone https://github.com/hicham-bab/dbt-legacy-migration-skills.git
cp -R dbt-legacy-migration-skills/{legacy-to-dbt-migration-foundations,migrating-*} ~/.dbt/wizard/skills/
```

Claude Code (user-level skills):

```bash
cp -R dbt-legacy-migration-skills/{legacy-to-dbt-migration-foundations,migrating-*} ~/.agents/skills/
```

Install all five together — the four migration skills reference
`legacy-to-dbt-migration-foundations` by relative path, so it must sit alongside them.

## Usage

Once installed, ask the agent to migrate a project and point it at the source artifacts, e.g.:

- "Migrate this Informatica workflow export to dbt" (point at the `.XML`)
- "Migrate these Talend jobs to dbt" (point at the `.item` folder)
- "Migrate this stored procedure to a dbt model and prove parity"
- "Migrate this Matillion pipeline to dbt" (point at the `.tran.yaml`/`.orch.yaml` or METL JSON)

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

## License

Apache-2.0. See [LICENSE](LICENSE).
