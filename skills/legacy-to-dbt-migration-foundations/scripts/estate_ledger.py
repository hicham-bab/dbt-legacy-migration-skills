#!/usr/bin/env python3
"""Track migration progress across a large estate.

Reads/updates the estate_ledger.json seeded by inventory_estate.py. Each job has a status:
pending -> in_progress -> migrated -> parity_passed  (or needs_review / residual). Use `set` to
update a job as it moves through a wave, and `report` for a scannable progress view (overall and
per-wave), so a team migrating thousands of jobs can see what's done, in flight, and outstanding.

Usage:
  python3 estate_ledger.py <ledger.json> report
  python3 estate_ledger.py <ledger.json> set <job-id> <status> [--note "..."]
Statuses: pending in_progress migrated parity_passed needs_review residual
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

STATUSES = ["pending", "in_progress", "migrated", "parity_passed", "needs_review", "residual"]
DONE = {"parity_passed"}


def report(ledger: dict) -> str:
    jobs = ledger.get("jobs", {})
    total = len(jobs)
    by_status = {s: sum(1 for j in jobs.values() if j.get("status") == s) for s in STATUSES}
    done = sum(1 for j in jobs.values() if j.get("status") in DONE)
    waves = sorted({j.get("wave", 1) for j in jobs.values()})
    lines = [f"Estate progress: {done}/{total} parity-passed ({(done/total*100 if total else 0):.0f}%)", ""]
    lines.append("By status: " + ", ".join(f"{s}={by_status[s]}" for s in STATUSES if by_status[s]))
    lines.append("")
    lines.append("| Wave | jobs | parity_passed | in flight | needs_review |")
    lines.append("|---|---|---|---|---|")
    for w in waves:
        wj = [j for j in jobs.values() if j.get("wave", 1) == w]
        pp = sum(1 for j in wj if j.get("status") in DONE)
        infl = sum(1 for j in wj if j.get("status") in ("in_progress", "migrated"))
        nr = sum(1 for j in wj if j.get("status") == "needs_review")
        lines.append(f"| {w} | {len(wj)} | {pp} | {infl} | {nr} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__); return 2
    path = Path(argv[0])
    cmd = argv[1]
    ledger = json.loads(path.read_text())
    if cmd == "report":
        print(report(ledger)); return 0
    if cmd == "set":
        if len(argv) < 4:
            print("set needs <job-id> <status>", file=sys.stderr); return 2
        jid, status = argv[2], argv[3]
        if status not in STATUSES:
            print(f"unknown status '{status}'; use one of {STATUSES}", file=sys.stderr); return 2
        if jid not in ledger.get("jobs", {}):
            print(f"unknown job id '{jid}'", file=sys.stderr); return 2
        ledger["jobs"][jid]["status"] = status
        if "--note" in argv:
            ledger["jobs"][jid]["notes"] = argv[argv.index("--note") + 1]
        path.write_text(json.dumps(ledger, indent=2) + "\n")
        print(f"{jid} -> {status}")
        return 0
    print(f"unknown command '{cmd}'", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
