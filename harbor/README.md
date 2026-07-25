# Harbor evals for the migration skills

[Harbor](https://github.com/harbor-framework/harbor) is an agent-evaluation framework: it runs a
whole agent (Claude Code, etc.) against a task in a Docker container and scores the outcome. These
tasks are the **end-to-end eval** - "does an agent *following the skills* actually produce a correct,
idiomatic migration?" - complementary to `evals/run_evals.py` (which unit-tests the deterministic
parsers).

## The scorecard

Each task no longer scores a single pass/fail. The shared scorer (`_scorer/scorer.py`) grades the
migrated project on five dimensions and writes a weighted `SCORECARD.md` + `scorecard.json`:

| Dimension | Weight | What it measures | How |
|---|---|---|---|
| **build** | gate | `dbt deps` + `dbt build` succeed | runs dbt |
| **parity** | 3.0 | every mart matches the held-out expected output **row-for-row** | queries the built warehouse, compares cells (numeric tolerance) |
| **coverage** | 1.5 | the required models are all present | `expected_models` from `spec.json` (falls back to the skill's inventory `coverage_denominator`) |
| **structural** | 1.0 | idiomatic dbt: test coverage, docs, staging→marts layering | reads `target/manifest.json` |
| **judge** | 1.0 | SCD correctness, decomposition, docs & test *meaningfulness* | LLM-as-judge - default via the dbt **Wizard** (dbt-managed inference, no raw key), or `ANTHROPIC_API_KEY`; skipped if neither |

The **reward** (Harbor's 1/0) is the correctness gate: **build passed AND every mart matches
row-for-row**. Coverage/structural/judge are quality signals in the weighted score, not the binary
gate - an ETL component often collapses into fewer dbt models, so a models/units ratio is directional,
not pass/fail.

## Tasks

All tasks target **DuckDB** (free, no cloud creds), preload the skills at `/skills`, and hold the
expected outputs beside the verifier (**hidden from the agent**). Expected outputs are computed
independently (reference logic / small deterministic seeds), so parity is real **without** installing
the legacy tool.

| Task | What it evaluates | Marts |
|------|-------------------|-------|
| [`migrate-stored-proc-to-dbt`](migrate-stored-proc-to-dbt) | Legacy **stored procedure** (temp table + `CREATE OR REPLACE`) | `mart_customer_ltv` |
| [`migrate-talend-to-dbt`](migrate-talend-to-dbt) | **Talend** job (`.item`: filter → tMap join → tAggregateRow) | `mart_customer_revenue` |
| [`migrate-informatica-to-dbt`](migrate-informatica-to-dbt) | **Informatica** PowerCenter mapping (Filter → Aggregator → Expression band) | `mart_fct_customer_orders` |
| [`migrate-matillion-to-dbt`](migrate-matillion-to-dbt) | **Matillion** DPC pipeline (calculator, filter, join, **rank**, aggregate) | `mart_fct_orders`, `mart_agg_customer_sales` |
| [`migrate-coalesce-to-dbt`](migrate-coalesce-to-dbt) | **Coalesce** node graph (Source→Stage→Dim→Fact) incl. a **Type 2 SCD** dimension → dbt snapshot | `mart_dim_customer`, `mart_fct_orders` |

## Run it

### Aggregate scorecard smoke test (no Docker, no agent)

Runs every task's **oracle** solution through the scorer and writes `harbor/SCORECARD.md`. Needs
`dbt-duckdb` + `duckdb` + `pyyaml`; the judge dimension also runs if `ANTHROPIC_API_KEY` is set.

```bash
pip install dbt-duckdb duckdb pyyaml anthropic
python3 harbor/_scorer/run_all.py          # -> harbor/SCORECARD.md + scorecard.json
```

This is also what the **`harbor-scorecard`** GitHub workflow runs (manual `workflow_dispatch`).

### Full agent eval - the dbt Wizard via dbt-managed inference (needs Docker)

The target agent is the **dbt Wizard**, which runs non-interactively as `dbt-wizard exec` and calls
models through **dbt-managed inference** - so no raw Anthropic key is needed. Instead, stage the
Wizard's OAuth credentials into the task images:

```bash
# 1) Authenticate on the host (writes OAuth files under ~/.dbt):
export WIZARD_INTERNAL=1
dbt login

# 2) Stage those credentials into each task's build context (gitignored, never committed):
bash harbor/_scorer/stage_wizard_auth.sh

# 3) Solvability with the oracle (no Wizard needed):
harbor run -p harbor/migrate-coalesce-to-dbt -a oracle

# 4) Evaluate the Wizard following the skills - build with the Wizard installed.
#    Uses the adapter in harbor/agents/dbt_wizard_agent.py (copy it into your Harbor checkout at
#    src/harbor/agents/installed/dbt_wizard.py first - see that file's header):
harbor run -p harbor/migrate-matillion-to-dbt \
  --agent harbor.agents.installed.dbt_wizard:DbtWizardAgent \
  --build-arg INSTALL_WIZARD=true

# 5) When done, remove the staged credentials:
bash harbor/_scorer/stage_wizard_auth.sh --clean
```

The images set `DO_NOT_TRACK=1` + `DBT_SEND_ANONYMOUS_USAGE_STATS=False` so eval runs don't inflate
telemetry, and `WIZARD_INTERNAL=1`. Skills are preloaded at both `/skills` and `~/.dbt/wizard/skills`.

> **Security:** the staged files are live OAuth credentials. They are gitignored, but once copied
> into an image they live in that image's layers - treat such images as secret and never push them
> to a public registry. Confirm `WIZARD_INSTALL_URL` in the Dockerfiles matches your Wizard release
> channel before building with `INSTALL_WIZARD=true`.

Pass = reward `1` (written by the verifier to `/logs/verifier/reward.txt`); the full scorecard is at
`/logs/verifier/SCORECARD.md`. View results with `harbor view ./jobs`.

## How each task is built

- **`task.toml`** - Harbor config; `environment.skills_dir = "/skills"` preloads the migration skills.
- **`instruction.md`** - the prompt (migrate the artifact; build in `/app/project`; targets DuckDB; a
  `migration_decisions.yml` is provided so the decision gate passes non-interactively).
- **`environment/`** - `Dockerfile` (python + dbt-duckdb + skills) and `app/` (raw CSVs, the legacy
  artifact, the decisions file, an empty dbt project + profile).
- **`solution/solve.sh`** - the oracle reference migration (exemplary: staging + marts + tests + docs).
- **`tests/`** - `test.sh` (verifier entrypoint → reward file), `spec.json` (marts, keys, expected
  models, judge rubric), the held-out expected CSVs, and synced copies of `scorer.py` +
  `test_migration.py`.

## Shared scorer (single source of truth)

`_scorer/` holds the canonical `scorer.py` + generic `test_migration.py`. Each task container mounts
only its own `tests/`, so the code is **copied** into every `tests/` by `_scorer/sync.sh`. Drift is
caught by `_scorer/check_sync.py` (run by the parser-tier CI). After editing `scorer.py`, re-run
`bash harbor/_scorer/sync.sh`.

Calibrate the judge against the human-labeled set before trusting its scores. The judge backend is
chosen by `HARBOR_JUDGE_BACKEND` (`auto` | `wizard` | `anthropic` | `off`); `auto` prefers the dbt
Wizard (`dbt-wizard` on PATH, dbt-managed inference) and falls back to `ANTHROPIC_API_KEY`:

```bash
export WIZARD_INTERNAL=1 && dbt login     # or: export ANTHROPIC_API_KEY=<key>
python3 harbor/_scorer/calibrate_judge.py   # reports agreement %; target >= 80%
```

## Verification status (honest)

- **Verified locally on DuckDB (without Harbor/Docker)** for **all five** tasks: every oracle builds
  and scores **reward 1** with 100% weighted score; a deliberately broken migration (e.g. dropping a
  threshold) drops parity to 0% and **reward 0**. So each task is solvable and its scorecard discriminates.
- **Not run here:** the full Harbor container run (no Docker daemon in this environment) and the
  LLM-as-judge dimension (no `dbt-wizard` / key wired here - it skips gracefully). Run the commands
  above on a machine with Docker + a logged-in Wizard to execute those.
- **Wizard agent adapter:** `harbor/agents/dbt_wizard_agent.py` is a `BaseInstalledAgent` adapter
  that runs `dbt-wizard exec "<instruction>"` in the container against the staged
  dbt-managed-inference credentials. Copy it into your Harbor checkout (see its header) to register
  it. Verified: `dbt-wizard exec` is invoked correctly and reaches the dbt-managed-inference gateway;
  a live run needs a valid `dbt login` (an expired/invalid platform token returns 401). Confirm the
  `WIZARD_INSTALL_URL` for your release channel, and whether your Wizard build applies changes on
  `exec` or needs a follow-up `apply` (see APPLY_AFTER_EXEC in the adapter).
