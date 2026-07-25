#!/usr/bin/env bash
# Copy the canonical scorer + generic verifier into every harbor task's tests/ dir.
# Each task container mounts only its own tests/ at /tests, so the shared code must live there;
# this keeps one source of truth (harbor/_scorer/) and stamps copies. Run after editing scorer.py.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
harbor="$(dirname "$here")"
for task in "$harbor"/migrate-*; do
  [ -d "$task/tests" ] || continue
  cp "$here/scorer.py" "$task/tests/scorer.py"
  cp "$here/test_migration.py" "$task/tests/test_migration.py"
  echo "synced -> $task/tests/"
done
