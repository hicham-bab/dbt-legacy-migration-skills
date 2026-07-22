# Harbor evals for the migration skills

[Harbor](https://github.com/harbor-framework/harbor) is an agent-evaluation framework: it runs a
whole agent (Claude Code, etc.) against a task in a Docker container and scores the outcome. These
tasks are the **end-to-end eval** — "does an agent *following the skills* actually produce a correct
migration?" — complementary to `evals/run_evals.py` (which unit-tests the deterministic parsers).

## Tasks

| Task | What it evaluates |
|------|-------------------|
| [`migrate-stored-proc-to-dbt`](migrate-stored-proc-to-dbt) | Agent migrates a legacy stored procedure to a dbt project on **DuckDB** (free, no cloud creds) and must reproduce the legacy output. Verifier builds the project and checks `mart_customer_ltv` matches the captured legacy output **row-for-row**. |

## Run it (needs Docker + an Anthropic key — not runnable in a restricted sandbox)

```bash
uv tool install harbor            # or: pip install harbor
export ANTHROPIC_API_KEY=<your-key>

# 1) Solvability check with the oracle reference solution (no model/key needed):
harbor run -p harbor/migrate-stored-proc-to-dbt -a oracle

# 2) Evaluate an agent following the skills (use a current model id):
harbor run -p harbor/migrate-stored-proc-to-dbt -a claude-code -m anthropic/claude-opus-4-8
```

Pass = reward `1` (written by the verifier to `/logs/verifier/reward.txt`); view results with
`harbor view ./jobs`.

## How the task is built

- **`task.toml`** — Harbor config; `environment.skills_dir = "/skills"` preloads the migration skills
  for the agent (the Dockerfile bakes them into `/skills`).
- **`instruction.md`** — the prompt (migrate the proc; build in `/app/project`; targets DuckDB; a
  `migration_decisions.yml` is provided so the decision gate passes non-interactively).
- **`environment/Dockerfile`** — python + dbt-duckdb + the skills + the agent's working files under `/app`.
- **`solution/solve.sh`** — the oracle reference migration (proves solvability).
- **`tests/`** — `test.sh` (verifier entrypoint → reward file) + `test_migration.py` (builds the
  agent's project, compares `mart_customer_ltv` to `legacy_customer_ltv.csv`). The expected output
  lives here, hidden from the agent.

## Verification status (honest)

- **Verified locally on DuckDB (without Harbor/Docker):** the oracle solution builds and the verifier
  scores **reward 1**; a deliberately broken migration (dropping the completed-only filter) scores
  **reward 0**. So the task is solvable and the verifier is correct.
- **Not run here:** the full Harbor container run (no Docker daemon / agent / API key in this
  environment). Run the commands above on a machine with Docker to execute the agent eval.
- Harbor drives agents like **claude-code**, not the dbt **Wizard** specifically — it evaluates the
  skills as loaded into a supported agent (a close proxy for Wizard behavior, not Wizard itself).
- The DuckDB proc task is self-contained by design. Equivalent tasks for the other sources
  (Talend/Informatica/Matillion/Coalesce) would need bundled fixtures + captured expected output —
  a natural follow-on.
