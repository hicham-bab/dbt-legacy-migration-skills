#!/usr/bin/env bash
# Stage the dbt Wizard's dbt-managed-inference OAuth credentials into each harbor task's build
# context, so the task image can COPY them to /root/.dbt and the Wizard can run non-interactively
# (`dbt-wizard exec`) inside the container without a raw API key.
#
# Run this AFTER authenticating on the host:
#     export WIZARD_INTERNAL=1
#     dbt login                      # writes the OAuth files under ~/.dbt
#     bash harbor/_scorer/stage_wizard_auth.sh
#     # then build with:  --build-arg INSTALL_WIZARD=true
#
# SECURITY: these are LIVE credentials. They are gitignored (never committed) and, once copied into
# an image, live in that image's layers - treat such images as secret and don't push them to a
# public registry. Run `stage_wizard_auth.sh --clean` to remove the staged copies when done.
set -euo pipefail

SRC="${DBT_DIR:-$HOME/.dbt}"
FILES=(oauth_sessions.json state_auth.json dbt_cloud.yml)
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
harbor="$(dirname "$here")"

if [ "${1:-}" = "--clean" ]; then
  for task in "$harbor"/migrate-*; do
    dest="$task/environment/wizard-auth"
    find "$dest" -type f ! -name .gitkeep -delete 2>/dev/null || true
    echo "cleaned $dest"
  done
  echo "Removed staged credentials."
  exit 0
fi

copied=0
for task in "$harbor"/migrate-*; do
  dest="$task/environment/wizard-auth"
  mkdir -p "$dest"
  for f in "${FILES[@]}"; do
    if [ -f "$SRC/$f" ]; then cp "$SRC/$f" "$dest/$f"; copied=1; fi
  done
  echo "staged auth -> $dest"
done

if [ "$copied" != 1 ]; then
  echo "WARNING: no auth files (${FILES[*]}) found in $SRC." >&2
  echo "         Run 'export WIZARD_INTERNAL=1 && dbt login' first, then re-run this script." >&2
  exit 1
fi
echo "Done. Build the wizard-agent image with --build-arg INSTALL_WIZARD=true."
echo "Reminder: staged files are live credentials (gitignored). Run with --clean to remove them."
