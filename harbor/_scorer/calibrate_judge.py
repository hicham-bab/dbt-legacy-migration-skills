#!/usr/bin/env python3
"""Validate the LLM-as-judge against a small human-labeled set before trusting its scores.

For each case in labeled_set/*.json, reconstruct the mini dbt project, run the judge, and check
each dimension's score lands in the human-labeled band (high => score >= 0.6, low => score < 0.6).
Reports agreement %. The judge is only trustworthy when agreement is high (target >= ~80%); if it
is low, tighten the rubric wording before relying on the judge dimension.

Requires ANTHROPIC_API_KEY (real API calls). Usage: python3 harbor/_scorer/calibrate_judge.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import scorer  # noqa: E402

BAND = 0.6  # score >= BAND counts as "high", else "low"


def _agree(score: float, label: str) -> bool:
    return (score >= BAND) if label == "high" else (score < BAND)


def main() -> int:
    backend = scorer._judge_backend()
    if backend == "off":
        print("ERROR: no judge backend. Install dbt-wizard (dbt-managed inference) or set "
              "ANTHROPIC_API_KEY.", file=sys.stderr)
        return 2
    print(f"(judge backend: {backend})")
    cases = sorted((HERE / "labeled_set").glob("*.json"))
    if not cases:
        print("No labeled cases found in harbor/_scorer/labeled_set/.", file=sys.stderr)
        return 2
    total, agreed = 0, 0
    for cf in cases:
        case = json.loads(cf.read_text())
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td)
            for rel, content in case["files"].items():
                p = proj / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content)
            try:
                scores = scorer.judge_raw(proj, case.get("legacy_text", ""), case["rubric"])
            except Exception as e:
                print(f"[{case['name']}] judge error: {e!r}")
                continue
        print(f"\n=== {case['name']} ===")
        for dim, label in case["labels"].items():
            got = float(scores.get(dim, {}).get("score", -1))
            ok = _agree(got, label)
            total += 1
            agreed += int(ok)
            mark = "✓" if ok else "✗"
            print(f"  {mark} {dim}: judge={got:.2f} label={label}")
    pct = 100 * agreed / total if total else 0
    print(f"\nJudge agreement: {agreed}/{total} = {pct:.0f}%  (target >= 80%)")
    return 0 if pct >= 80 else 1


if __name__ == "__main__":
    sys.exit(main())
