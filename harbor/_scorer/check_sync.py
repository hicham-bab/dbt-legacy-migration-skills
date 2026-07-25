#!/usr/bin/env python3
"""Fail if any task's tests/scorer.py or test_migration.py has drifted from harbor/_scorer/.

Run by the parser-tier CI so a scorer edit that wasn't re-synced (via harbor/_scorer/sync.sh)
is caught before it silently diverges across tasks. Exits non-zero on drift.
"""
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
HARBOR = HERE.parent
drift = []
for task in sorted(HARBOR.glob("migrate-*")):
    tests = task / "tests"
    if not tests.is_dir():
        continue
    for fn in ("scorer.py", "test_migration.py"):
        canonical, copy = HERE / fn, tests / fn
        if not copy.exists():
            drift.append(f"missing: {copy.relative_to(HARBOR)}")
        elif copy.read_text() != canonical.read_text():
            drift.append(f"drifted: {copy.relative_to(HARBOR)} (run harbor/_scorer/sync.sh)")

if drift:
    print("Scorer sync check FAILED:")
    for d in drift:
        print("  -", d)
    sys.exit(1)
print("Scorer sync check: all task copies match harbor/_scorer/.")
