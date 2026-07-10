#!/usr/bin/env bash
#
# Install (or update) the dbt legacy-migration skills into your agent's skills directory.
#
# Usage:
#   ./install.sh                      # install into the dbt Wizard skills dir (~/.dbt/wizard/skills)
#   ./install.sh --claude             # install into Claude Code's dir (~/.agents/skills)
#   ./install.sh --dest /path/to/dir  # install into a specific skills directory
#
# Safe to re-run: it cleanly replaces just these five skill folders and touches nothing else.
set -euo pipefail

SKILLS=(
  legacy-to-dbt-migration-foundations
  migrating-informatica-to-dbt
  migrating-talend-to-dbt
  migrating-stored-procedures-to-dbt
  migrating-matillion-to-dbt
)

# --- pick the destination ---------------------------------------------------
DEST="$HOME/.dbt/wizard/skills"
while [ $# -gt 0 ]; do
  case "$1" in
    --claude) DEST="$HOME/.agents/skills"; shift ;;
    --dest)   DEST="${2:?--dest needs a path}"; shift 2 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

# --- find the skill folders (this clone, or clone fresh) --------------------
SRC="$(cd "$(dirname "$0")" && pwd)"
CLEANUP=""
if [ ! -d "$SRC/legacy-to-dbt-migration-foundations" ]; then
  echo "Fetching the skills from GitHub..."
  SRC="$(mktemp -d)"; CLEANUP="$SRC"
  git clone --depth 1 -q https://github.com/hicham-bab/dbt-legacy-migration-skills.git "$SRC"
fi

# --- install ----------------------------------------------------------------
mkdir -p "$DEST"
echo "Installing ${#SKILLS[@]} dbt migration skills into: $DEST"
for s in "${SKILLS[@]}"; do
  [ -d "$SRC/$s" ] || { echo "  ! missing in source: $s (aborting)"; exit 1; }
  rm -rf "${DEST:?}/$s"          # replace only our own folders; leaves other skills untouched
  cp -R "$SRC/$s" "$DEST/$s"
  echo "  - $s"
done
[ -n "$CLEANUP" ] && rm -rf "$CLEANUP"

echo
echo "Done. Installed into $DEST."
echo "Restart your agent (e.g. quit and reopen dbt Wizard) so it picks up the skills."
