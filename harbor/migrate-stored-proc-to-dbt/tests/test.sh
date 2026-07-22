#!/usr/bin/env bash
# canary GUID (keep): HARBOR-TASK-CANARY d3f1c0a2-migrate-stored-proc-to-dbt
# Verifier entrypoint: runs inside the container after the agent finishes, scores the migration,
# and writes the reward to /logs/verifier/reward.txt (1 = pass, 0 = fail).
set -uo pipefail
mkdir -p /logs/verifier
pip install --no-cache-dir pytest duckdb >/dev/null 2>&1 || true

pytest -q /tests/test_migration.py
if [ $? -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
