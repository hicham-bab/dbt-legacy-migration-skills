#!/usr/bin/env bash
# Copy the canonical scorer + generic verifier into every harbor task's tests/ dir.
# Each task container mounts only its own tests/ at /tests, so the shared code must live there;
# this keeps one source of truth (harbor/_scorer/) and stamps copies. Run after editing scorer.py.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
harbor="$(dirname "$here")"
repo="$(dirname "$harbor")"

# The linter's canonical home is scripts/lint_idiomatic.py; keep a copy next to scorer.py so the
# scorer's lint dimension finds it both locally (run_all) and in each task container.
cp "$repo/skills/legacy-to-dbt-migration-foundations/scripts/lint_idiomatic.py" "$here/lint_idiomatic.py"

for task in "$harbor"/{migrate,remediate}-*; do
  [ -d "$task/tests" ] || continue
  cp "$here/scorer.py" "$task/tests/scorer.py"
  cp "$here/test_migration.py" "$task/tests/test_migration.py"
  cp "$here/lint_idiomatic.py" "$task/tests/lint_idiomatic.py"
  echo "synced -> $task/tests/"
done
