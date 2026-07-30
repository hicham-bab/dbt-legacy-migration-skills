#!/usr/bin/env bash
# canary GUID (keep): HARBOR-TASK-CANARY e9a1c7b3-remediate-lift-and-shift-to-dbt
# Verifier entrypoint: builds the refactored project, scores parity + the anti-pattern lint gate,
# and writes the reward to /logs/verifier/reward.txt (1 = pass, 0 = fail).
set -uo pipefail
mkdir -p /logs/verifier
pip install --no-cache-dir pytest duckdb anthropic >/dev/null 2>&1 || true

pytest -q /tests/test_migration.py
if [ $? -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
