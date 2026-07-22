# Harbor evals for the migration skills

[Harbor](https://github.com/harbor-framework/harbor) is an agent-evaluation framework: it runs a
whole agent (Claude Code, etc.) against a task in a Docker container and scores the outcome. These
tasks are the **end-to-end eval** — "does an agent *following the skills* actually produce a correct
migration?" — complementary to `evals/run_evals.py` (which unit-tests the deterministic parsers).

## Tasks

All tasks target **DuckDB** (free, no cloud creds), preload the skills at `/skills`, and score parity
by building the agent's project and comparing its mart to a **held-out** captured legacy output
**row-for-row**.

| Task | What it evaluates |
|------|-------------------|
| [`migrate-stored-proc-to-dbt`](migrate-stored-proc-to-dbt) | Agent migrates a legacy **stored procedure** (temp table + `CREATE OR REPLACE`) → checks `mart_customer_ltv`. |
| [`migrate-talend-to-dbt`](migrate-talend-to-dbt) | Agent migrates a legacy **Talend** job (`.item`: filter → tMap join → tAggregateRow) → checks `mart_customer_revenue`. |
| [`migrate-informatica-to-dbt`](migrate-informatica-to-dbt) | Agent migrates a legacy **Informatica** mapping (PowerCenter XML: Filter → Aggregator → Expression) → checks `mart_fct_customer_orders`. |

## Run it (needs Docker + an Anthropic key — not runnable in a restricted sandbox)

```bash
uv tool install harbor            # or: pip install harbor
export ANTHROPIC_API_KEY=<your-key>

# 1) Solvability check with the oracle reference solution (no model/key needed):
harbor run -p harbor/migrate-stored-proc-to-dbt -a oracle
harbor run -p harbor/migrate-talend-to-dbt      -a oracle
harbor run -p harbor/migrate-informatica-to-dbt -a oracle

# 2) Evaluate an agent following the skills (use a current model id):
harbor run -p harbor/migrate-talend-to-dbt -a claude-code -m anthropic/claude-opus-4-8
```

Pass = reward `1` (written by the verifier to `/logs/verifier/reward.txt`); view results with
`harbor view ./jobs`.

## How each task is built

- **`task.toml`** — Harbor config; `environment.skills_dir = "/skills"` preloads the migration skills
  for the agent (the Dockerfile bakes them into `/skills`).
- **`instruction.md`** — the prompt (migrate the artifact; build in `/app/project`; targets DuckDB; a
  `migration_decisions.yml` is provided so the decision gate passes non-interactively).
- **`environment/`** — `Dockerfile` (python + dbt-duckdb + skills) and `app/` (raw CSVs, the legacy
  artifact, the decisions file, an empty dbt project + profile).
- **`solution/solve.sh`** — the oracle reference migration (proves solvability).
- **`tests/`** — `test.sh` (verifier entrypoint → reward file) + `test_migration.py` (builds the
  agent's project and compares its mart to the expected CSV). The expected output lives here,
  **hidden from the agent**.

## Verification status (honest)

- **Verified locally on DuckDB (without Harbor/Docker)** — for **all three** tasks: the oracle
  solution builds and the verifier scores **reward 1**; a deliberately broken migration (dropping the
  completed-only filter) scores **reward 0**. So each task is solvable and its verifier discriminates.
- **Not run here:** the full Harbor container run (no Docker daemon / agent / API key in this
  environment). Run the commands above on a machine with Docker to execute the agent eval.
- Harbor drives agents like **claude-code**, not the dbt **Wizard** specifically — it evaluates the
  skills as loaded into a supported agent (a close proxy for Wizard behavior, not Wizard itself).
- The remaining sources (**Matillion**, **Coalesce**) would each get a task the same way — a bundled
  fixture + captured expected output — a natural follow-on.
