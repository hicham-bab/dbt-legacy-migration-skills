#!/usr/bin/env python3
"""Estate dependability report: turn a batch of migration eval results into the accelerator metrics.

This is the measurement instrument behind the "accelerator or check-the-box?" question. Given the
per-job scorecards from an estate pressure-test (each job run through the agent, then scored by the
harbor scorer), it computes and publishes the numbers that decide whether the tool is dependable at
scale, rather than asserting it:

  - auto-to-parity %     jobs the agent migrated to a correct, matching result with NO human fix
                         (reward == build AND parity); the core accelerator metric.
  - human-fix %          the complement: jobs that needed a person.
  - quality-bar pass %   jobs that were also idiomatic (lint dimension clean); correct AND not
                         lift-and-shift debt.
  - avg parity/coverage/structural/judge, and a per-tool / per-wave breakdown.

Inputs (either):
  --scorecard <file>   the aggregate written by run_all.py (has tasks[] with dimensions + reward)
  --runs <dir>         a directory of per-job scorecard.json files (as the verifier writes)
Optional: --ledger <estate_ledger.json> to attribute jobs to waves; --out <dir>.

IMPORTANT: the numbers only mean "accelerator" when the jobs were solved by the AGENT (e.g. dbt
Wizard), not by the oracle reference solutions (which pass by construction). Label runs accordingly.

Usage: python3 estate_report.py (--scorecard f | --runs d) [--ledger l] [--out dir] [--label "..."]
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path


def _load_cards(argv: list[str]) -> list[dict]:
    if "--scorecard" in argv:
        agg = json.loads(Path(argv[argv.index("--scorecard") + 1]).read_text())
        return agg.get("tasks", [])
    if "--runs" in argv:
        d = Path(argv[argv.index("--runs") + 1])
        return [json.loads(p.read_text()) for p in sorted(d.glob("**/scorecard.json"))]
    print("need --scorecard <file> or --runs <dir>", file=sys.stderr)
    sys.exit(2)


def _dim(card: dict, name: str):
    return next((d for d in card.get("dimensions", []) if d["name"] == name), None)


def _reward(card: dict) -> int:
    if "reward" in card:
        return int(card["reward"])
    b, p = _dim(card, "build"), _dim(card, "parity")  # fall back to build AND parity
    return int(bool(b and b["score"] == 1.0 and p and p["score"] == 1.0))


def _avg(cards, name):
    vals = [d["score"] for c in cards if (d := _dim(c, name)) and d.get("ran", True)]
    return statistics.mean(vals) if vals else None


def build_report(cards: list[dict], ledger: dict | None, label: str) -> dict:
    n = len(cards)
    auto = sum(_reward(c) for c in cards)
    qbar = sum(1 for c in cards if (d := _dim(c, "lint")) and d.get("ran", True) and d["score"] == 1.0)
    wave_of = {}
    if ledger:
        # match a scorecard task name to a ledger job by suffix
        for c in cards:
            t = c.get("task", "")
            j = next((v for k, v in ledger.get("jobs", {}).items() if k.endswith(t) or t.endswith(v.get("name", "\0"))), None)
            wave_of[t] = j.get("wave") if j else None
    per_wave = {}
    for c in cards:
        w = wave_of.get(c.get("task", ""))
        if w is not None:
            per_wave.setdefault(w, []).append(c)
    return {
        "label": label,
        "total_jobs": n,
        "auto_to_parity_pct": round(100 * auto / n, 1) if n else 0.0,
        "human_fix_pct": round(100 * (n - auto) / n, 1) if n else 0.0,
        "quality_bar_pass_pct": round(100 * qbar / n, 1) if n else 0.0,
        "avg": {k: (round(v, 3) if v is not None else None)
                for k in ("parity", "coverage", "structural", "judge") for v in [_avg(cards, k)]},
        "by_wave": {str(w): {"jobs": len(cs), "auto_to_parity": sum(_reward(c) for c in cs)}
                    for w, cs in sorted(per_wave.items())},
    }


def report_md(r: dict) -> str:
    a = r["avg"]
    def pct(x): return "n/a" if x is None else f"{x*100:.0f}%"
    lines = [f"# Estate dependability report{' - ' + r['label'] if r['label'] else ''}", "",
             f"**{r['total_jobs']} jobs**", "",
             f"- **Auto-to-parity: {r['auto_to_parity_pct']}%** (migrated correctly, no human fix)",
             f"- Human-fix needed: {r['human_fix_pct']}%",
             f"- **Quality-bar pass: {r['quality_bar_pass_pct']}%** (correct AND idiomatic)",
             f"- Avg parity {pct(a['parity'])} · coverage {pct(a['coverage'])} · "
             f"structural {pct(a['structural'])} · judge {pct(a['judge'])}", ""]
    if r["by_wave"]:
        lines += ["| Wave | jobs | auto-to-parity |", "|---|---|---|"]
        for w, v in r["by_wave"].items():
            lines.append(f"| {w} | {v['jobs']} | {v['auto_to_parity']}/{v['jobs']} |")
        lines.append("")
    lines += ["> Accelerator numbers require AGENT (not oracle) runs. "
              "The Waste Management pressure-test replaces this input with the sanitized WM estate.", ""]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    cards = _load_cards(argv)
    ledger = json.loads(Path(argv[argv.index("--ledger") + 1]).read_text()) if "--ledger" in argv else None
    label = argv[argv.index("--label") + 1] if "--label" in argv else ""
    r = build_report(cards, ledger, label)
    out = Path(argv[argv.index("--out") + 1]) if "--out" in argv else Path(".")
    out.mkdir(parents=True, exist_ok=True)
    (out / "estate_dependability.json").write_text(json.dumps(r, indent=2) + "\n")
    (out / "estate_dependability.md").write_text(report_md(r))
    print(report_md(r))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
