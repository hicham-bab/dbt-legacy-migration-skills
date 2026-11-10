# dbt migration skills

[![evals](https://github.com/hicham-bab/dbt-legacy-migration-skills/actions/workflows/evals.yml/badge.svg?branch=main)](https://github.com/hicham-bab/dbt-legacy-migration-skills/actions/workflows/evals.yml)
[![eval checks](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/hicham-bab/dbt-legacy-migration-skills/main/evals/results.json)](evals/RESULTS.md)

Agent skills for migrating legacy ETL workloads to dbt. One shared foundation plus a
per-source skill that knows how to read that tool's export format.

| Skill | Covers |
|---|---|
| [`legacy-to-dbt-migration-foundations`](skills/legacy-to-dbt-migration-foundations) | The shared workflow — Step-0 input contract, layer classification, materializations, tests/docs, parity validation, coverage math, cost comparison, cutover. Not invoked directly. |
| [`migrating-matillion-to-dbt`](skills/migrating-matillion-to-dbt) | Matillion DPC YAML and METL JSON exports |
| [`migrating-snaplogic-to-dbt`](skills/migrating-snaplogic-to-dbt) | SnapLogic `.slp` pipeline exports |
| [`migrating-informatica-to-dbt`](skills/migrating-informatica-to-dbt) | Informatica PowerCenter repository XML |
| [`migrating-talend-to-dbt`](skills/migrating-talend-to-dbt) | Talend job `.item` exports |
| [`migrating-stored-procedures-to-dbt`](skills/migrating-stored-procedures-to-dbt) | Warehouse stored procedures |
| [`migrating-coalesce-to-dbt`](skills/migrating-coalesce-to-dbt) | Coalesce.io projects (Git-committed YAML nodes) |
| [`migrating-datastage-to-dbt`](skills/migrating-datastage-to-dbt) | IBM InfoSphere DataStage parallel jobs (`.dsx` export) |
| [`remediating-lift-and-shift-to-dbt`](skills/remediating-lift-and-shift-to-dbt) | An already-migrated but non-idiomatic dbt project (hook/monolith/hardcoded lift-and-shift) → refactored to idiomatic dbt with parity preserved |
| [`example-project-skill`](skills/example-project-skill) | Template for project-specific guidance |

Each source skill links to the foundations skill by name rather than duplicating it, so a
fix to the shared workflow reaches every source.

## The Step-0 gate

`templates/migration_manifest.yml` in the foundations skill is the single input contract.
It supersedes the older flat `migration_decisions.yml`, which covered three of the seven
Step-0 questions and none of the artifact, access, or compliance inputs — the ones that
actually halt migrations. Validate it with the preflight script:

```
python3 skills/legacy-to-dbt-migration-foundations/scripts/preflight_decisions.py \
    decisions --file migration_manifest.yml
```

The script (and each skill's inventory script) is the primary path. Each skill's gate also
describes a by-hand check, for use **only** on the dbt platform, where Python can't run.

## Install

> **Run these in your terminal, not inside the dbt Wizard prompt.** Installing skills is just file
> copying into `~/.dbt/wizard/skills/`; it needs no login and no model call. Pasting the commands into
> the Wizard chat only makes the Wizard spend a model call to run shell for you (and fails if your
> dbt Platform auth is not set up). After installing, **restart the Wizard** so it reloads the skills.

The skills live under `skills/<name>/`, the standard [Agent Skills](https://agentskills.io/specification)
layout, so any skills tool can install them straight from GitHub, from anywhere:

```bash
npx skills add hicham-bab/dbt-legacy-migration-skills   # vercel-labs/skills
# or:  gh skill install hicham-bab/dbt-legacy-migration-skills
```

**Or the bundled one-liner** (installs/updates all the skills):

```bash
git clone https://github.com/hicham-bab/dbt-legacy-migration-skills.git
cd dbt-legacy-migration-skills && ./install.sh          # dbt Wizard CLI (~/.dbt/wizard/skills)
#                                  ./install.sh --claude # Claude Code   (~/.claude/skills)
#                                  ./install.sh --codex  # Codex CLI     (~/.codex/skills)
```

`install.sh` copies just the skill folders (from `skills/`) into your skills directory and leaves
everything else untouched. If you run it outside a clone it fetches the skills from GitHub for you.
**It's safe to re-run to update**; it cleanly replaces only these folders. (Use `--dest <path>` for a
custom location.) After it finishes, **restart the agent** so it reloads the skill list.

<details><summary>Manual copy</summary>

```bash
cp -R skills/* ~/.dbt/wizard/skills/
```

</details>

Install **all the skills together** - every migration and remediation skill references
`legacy-to-dbt-migration-foundations` by relative path, so it must sit alongside them.

### Using dbt Wizard on the dbt platform (Studio)

Wizard **in the dbt platform** does not read `~/.dbt/wizard/skills`. It discovers **repo-level
skills** from an `.agents/skills/` directory at your **dbt project root**, scanned at the start of
each chat ([docs](https://docs.getdbt.com/docs/dbt-ai/wizard-platform-skills)). Studio is a browser
IDE with no general shell, so you do **not** run `install.sh` (or any of the commands above) inside
the platform. Instead, get the skill folders into your project repo's `.agents/skills/` one of
two ways.

**Via git (recommended)** - in a local checkout of *your dbt project* (on your machine, outside
Studio), add the skills and push:

```bash
# run in a local clone of YOUR dbt project, not in Studio
git clone https://github.com/hicham-bab/dbt-legacy-migration-skills.git /tmp/dbt-mig
mkdir -p .agents/skills && cp -R /tmp/dbt-mig/skills/* .agents/skills/
git add .agents/skills && git commit -m "Add dbt legacy-migration skills" && git push
```

Then in Studio, **pull the branch** using the built-in git controls (the git button / wayfinder bar
handles branch/commit/push/pull; there is no shell). (`/tmp/dbt-mig/install.sh --dest
"$(pwd)/.agents/skills"` does the same copy if you prefer it, but it still runs on your machine, not
in the platform.)

**Or in the Studio file explorer** - create `.agents/skills/<skill>/SKILL.md` (plus any `references/`
files) for each skill by hand, pasting the contents from this repo. Fine for one skill, tedious for
all of them.

Either way, then:

1. **Start a new dbt Wizard chat** - skills load at session start, so mid-session edits are not
   picked up until you open a new chat.
2. Reference one by name, e.g. `Use migrating-informatica-to-dbt to migrate models/legacy/wf_orders.XML`.
3. Keep `.agents/skills/` committed so the whole project team (and every Wizard session on the repo)
   gets them. A custom skill overrides a built-in one of the same name.

Keep all the skills together so `legacy-to-dbt-migration-foundations` sits alongside the migration skills.

### Using with Claude Code or Codex

The same skill folders work in other Agent-Skills-compatible CLIs; only the directory differs
(each agent scans its own location, not `.agents/skills`):

- **Claude Code** - `~/.claude/skills/` (all your projects) or `.claude/skills/` in a repo (that
  project only). Run `./install.sh --claude`. Claude Code watches the folder, so a newly added skill
  is picked up in the current session (restart only if `~/.claude/skills` did not exist when the
  session started). Then just ask, e.g. "use migrating-talend-to-dbt to migrate ...".
- **Codex CLI** - `~/.codex/skills/` (all your projects) or `.codex/skills/` in a repo. Run
  `./install.sh --codex`. Invoke with `$migrating-talend-to-dbt`, or let it auto-activate from the
  skill's description.

All the skills install together (foundations must sit alongside the migration skills), and re-running
`install.sh` is safe to update.

### Iterating on the skills (frequent edits / beta)

If you are actively changing the skills, **symlink instead of copy** so your working clone is the
live source and you never re-install on each edit:

```bash
./install.sh --link            # symlinks into ~/.dbt/wizard/skills; combine with --claude / --codex / --dest
```

Then edits in `skills/` are live: **dbt Wizard and Codex** pick them up when you **start a new
session**; **Claude Code** re-reads changed skills within the session (no restart). `--link` needs a
local clone (it points the symlinks at your checkout). Run a plain `./install.sh` again to switch
back to a real copy. For the **dbt platform (Studio)** there's no symlink, iterate by committing to
`.agents/skills/` and starting a new chat.

## Usage

**Set the approval posture up front.** A migration is a multi-step run (it writes models and runs
`dbt`), so decide once at the start instead of confirming every edit. To run **without a prompt at
each step**, use a workspace-scoped sandbox with approvals off:

```bash
dbt-wizard --sandbox workspace-write --ask-for-approval never
```

`workspace-write` confines writes to your project; `never` means the Wizard applies edits and runs
`dbt` without asking (a command that would need to leave the sandbox just fails instead of
prompting). The default policy, `on-request`, is what makes the Wizard ask "Would you like to make
the following edits?" at each step; if you stay in that mode, press `a` ("don't ask again for these
files") to stop the prompts for the current files. `--dangerously-bypass-approvals-and-sandbox`
removes the sandbox entirely and is for externally sandboxed / CI runs only.

## Project independence

These skills are source-tool-specific but **customer-agnostic**. Everything that varies per
engagement belongs in the migrator's own `migration_manifest.yml`, never in a skill file.

Worked examples use invented schemas, and where a reference cites evidence it can no longer
show — "developed against real exports covering X, but not Y" — it says so without pointing
at files that do not ship.

How thoroughly that was verified differs by skill, so treat the guarantee as uneven:

- **Matillion and SnapLogic — verified programmatically.** A real export was available for
  each. Every identifier in the export was extracted and matched against every skill file;
  each hit was either generalized or confirmed to be source-tool vocabulary
  (`transformationJob`, `execution_mode`, `implementationID`) rather than customer data.
  This found leaks that reading had missed twice — verbatim snap labels, a patient-data
  schema, environment names, and component names buried in code comments.
- **Informatica, Talend, stored procedures — inspected only.** No export was on disk to
  diff against. Their worked examples (`m_STG_CUSTOMER`, `RETAIL_SRC.CUSTOMERS`,
  `EXP_CLEANSE`) read as hand-authored retail demos rather than customer data, but that is
  a judgment, not a measurement. If you have a real export for one of these tools, run the
  same extract-and-match check before trusting the property.

If you add to these skills, keep that property: no customer names, table or column names,
job or component names, environment names, or counts taken from one engagement.

## Tests

```
python3 -m unittest discover -s skills/migrating-matillion-to-dbt/scripts -p 'test_*.py'
```

The Matillion skill carries a synthetic fixture that reproduces the structural shape of a
real METL export — `jobsTree`, the common transformation component ids, `run-transformation`
bridges, and the orchestration connector collections — without carrying customer data. Its
17 tests lock in role classification, the coverage denominator, and Shared Job detection.

Every push and PR also runs a deterministic eval harness over the skills' inventory **parsers** (the
step that reads a legacy export and produces the workload inventory). CI fails on any regression, so
the badges above reflect the live state of `main`.

- **Published breakdown:** [`evals/RESULTS.md`](evals/RESULTS.md) - per-check results by source,
  refreshed by CI on every push to `main`.
- **How it's checked:** [`evals/README.md`](evals/README.md) - fixtures, methodology, and the
  "verified against real vendor exports" discipline behind the numbers.
- **Reproduce locally:** `pip install pyyaml && python3 evals/run_evals.py` (add `--write` to
  regenerate the report + `results.json`).
- **Agent eval + scorecard** - [`harbor/`](harbor/) holds
  [Harbor](https://github.com/harbor-framework/harbor) tasks that run a whole agent *following the
  skills* against real migrations in a container (targeting DuckDB, no cloud creds) and grade the
  output on a weighted **scorecard**: build → **data parity** (row-for-row vs a held-out expected
  output) → **coverage** → **structural** (idiomatic-dbt signals) → **LLM-as-judge** (SCD
  correctness, decomposition, docs/test quality). **Six tasks** - **stored procedure**, **Talend**,
  **Informatica**, **Matillion**, **Coalesce** (incl. a Type 2 SCD → dbt snapshot), and a
  **lift-and-shift remediation** (refactor to idiomatic dbt, parity preserved, lint must pass) - each
  verified solvable: the oracle scores 100% / reward 1, a broken migration drops parity and scores
  reward 0. Run the aggregate smoke test with `python3 harbor/_scorer/run_all.py`.
