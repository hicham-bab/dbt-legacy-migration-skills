#!/usr/bin/env python3
"""Run every harbor task's ORACLE solution through the scorecard and aggregate the results.

This is the solvability + scorecard smoke test (no agent, no Docker): for each task it lays out the
app dir, runs solution/solve.sh (the oracle), scores the built project with the shared scorer, and
writes an aggregate harbor/SCORECARD.md + harbor/scorecard.json. A correct oracle should score high
and reward 1 on every task; if it doesn't, a task or the scorer has regressed.

Needs `dbt` (dbt-duckdb) + duckdb + pyyaml on PATH; the judge dimension also runs if ANTHROPIC_API_KEY
(and the anthropic SDK) are present, else it is skipped. Full agent evals are a manual `harbor run`.

Usage: python3 harbor/_scorer/run_all.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
HARBOR = HERE.parent
ROOT = HARBOR.parent
sys.path.insert(0, str(HERE))
import scorer  # noqa: E402

os.environ.setdefault("HARBOR_SKILLS_DIR", str(ROOT / "skills"))


def _resolve_spec(task: Path, app: Path) -> dict:
    spec = json.loads((task / "tests" / "spec.json").read_text())
    spec["project"] = str(app / "project")
    if spec.get("legacy_file"):
        spec["legacy_file"] = str(app / spec["legacy_file"])
    if spec.get("inventory"):
        spec["inventory"] = {**spec["inventory"], "input": str(app / spec["inventory"]["input"])}
    spec["marts"] = [{**m, "expected_csv": str(task / "tests" / m["expected"])} for m in spec["marts"]]
    return spec


def run_task(task: Path) -> scorer.Scorecard:
    work = Path(tempfile.mkdtemp(prefix=f"{task.name}-"))
    app = work / "app"
    shutil.copytree(task / "environment" / "app", app)
    # oracle solve.sh hardcodes /app -> rewrite to this run's app dir
    solve = (task / "solution" / "solve.sh").read_text().replace("/app", str(app))
    (work / "solve.sh").write_text(solve)
    env = {**os.environ, "DBT_PROFILES_DIR": str(app / "project")}
    r = subprocess.run(["bash", str(work / "solve.sh")], capture_output=True, text=True, env=env)
    if r.returncode != 0:
        print(f"  ! oracle build failed:\n{r.stdout[-1500:]}\n{r.stderr[-500:]}")
    return scorer.score_task(_resolve_spec(task, app))


def main() -> int:
    tasks = sorted(list(HARBOR.glob("migrate-*")) + list(HARBOR.glob("remediate-*")))
    cards = []
    for task in tasks:
        if not (task / "tests" / "spec.json").exists():
            continue
        print(f"### {task.name}")
        card = run_task(task)
        require_lint = json.loads((task / "tests" / "spec.json").read_text()).get("require_lint", False)
        r = scorer.reward(card, require_lint=require_lint)
        cards.append((card, r))
        print(card.to_markdown())
        print(f"reward: {r}\n")

    # aggregate
    lines = ["# Harbor aggregate scorecard", "",
             "> Oracle-solution smoke test across all migration tasks "
             "(`python3 harbor/_scorer/run_all.py`). Full agent evals run via `harbor run`.", "",
             "| Task | Weighted | Parity | Coverage | Structural | Judge | Reward |",
             "|---|---|---|---|---|---|---|"]

    def cell(card, name):
        d = card.get(name)
        return "-" if not d else ("skip" if not d.ran else f"{d.score*100:.0f}%")

    all_reward = 1
    for card, r in cards:
        all_reward &= r
        lines.append(f"| {card.task} | {card.total*100:.0f}% | {cell(card,'parity')} | "
                     f"{cell(card,'coverage')} | {cell(card,'structural')} | {cell(card,'judge')} | {r} |")
    lines.append("")
    (HARBOR / "SCORECARD.md").write_text("\n".join(lines))
    (HARBOR / "scorecard.json").write_text(json.dumps(
        {"tasks": [{**c.as_dict(), "reward": r} for c, r in cards],
         "all_reward": bool(all_reward)}, indent=2) + "\n")
    print(f"Wrote harbor/SCORECARD.md and harbor/scorecard.json ({len(cards)} tasks, "
          f"all_reward={bool(all_reward)}).")
    return 0 if all_reward else 1


if __name__ == "__main__":
    sys.exit(main())
