# canary GUID (keep): HARBOR-TASK-CANARY generic-scorecard-verifier
"""Generic verifier - identical across tasks (synced from harbor/_scorer/).

Reads the task's `spec.json` (sibling file), builds the agent's dbt project, scores it on the
five scorecard dimensions, writes SCORECARD.md + scorecard.json to /logs/verifier, and asserts
the reward gate (build + perfect parity + coverage). Path bases:
  APP   = $HARBOR_APP   (default /app)      - legacy artifact, project, raw data
  TESTS = this file's dir (mounted at /tests) - held-out expected CSVs
Local runs override HARBOR_APP / HARBOR_LOGS to point at a scratch layout.
"""
import json
import os
from pathlib import Path

import scorer  # synced sibling; single source of truth in harbor/_scorer/scorer.py

TESTS = Path(__file__).resolve().parent
APP = Path(os.environ.get("HARBOR_APP", "/app"))
LOGS = Path(os.environ.get("HARBOR_LOGS", "/logs/verifier"))
SPEC = json.loads((TESTS / "spec.json").read_text())


def _resolved_spec() -> dict:
    s = dict(SPEC)
    s["project"] = str(APP / "project")
    if s.get("legacy_file"):
        s["legacy_file"] = str(APP / s["legacy_file"])
    if s.get("inventory"):
        s["inventory"] = {**s["inventory"], "input": str(APP / s["inventory"]["input"])}
    s["marts"] = [{**m, "expected_csv": str(TESTS / m["expected"])} for m in s["marts"]]
    return s


def test_scorecard():
    card = scorer.score_task(_resolved_spec())
    card.write(LOGS)
    print("\n" + card.to_markdown())
    r = scorer.reward(card, SPEC.get("coverage_threshold", 0.95))
    (LOGS).mkdir(parents=True, exist_ok=True)
    (LOGS / "reward.txt").write_text(str(r) + "\n")
    b, p = card.get("build"), card.get("parity")
    assert b and b.score == 1.0, f"build gate failed: {b.detail if b else 'n/a'}"
    assert p and p.score == 1.0, f"parity gate failed: {p.detail if p else 'n/a'}"
    assert r == 1, "reward gate not met (see scorecard)"
