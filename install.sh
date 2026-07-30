#!/usr/bin/env bash
#
# Install (or update) the dbt legacy-migration skills into your agent's skills directory.
#
# Usage:
#   ./install.sh                      # dbt Wizard CLI skills dir (~/.dbt/wizard/skills)
#   ./install.sh --claude             # Claude Code skills dir (~/.claude/skills)
#   ./install.sh --codex              # Codex CLI skills dir (~/.codex/skills)
#   ./install.sh --dest /path/to/dir  # a specific dir (e.g. <dbt project>/.agents/skills for dbt platform Studio)
#   ./install.sh --link               # symlink instead of copy (dev loop: repo edits reflect live)
#
# --link combines with the target flags (e.g. ./install.sh --link --claude) and requires a local
# clone (symlinks must point at a real checkout, not a temp fetch).
#
# Safe to re-run: it cleanly replaces just these seven skill folders and touches nothing else.
#
# Note: the skills live under skills/ (the standard Agent Skills layout), so you can also install
# them with any skills tool, e.g.:  npx skills add hicham-bab/dbt-legacy-migration-skills
set -euo pipefail

# Skills live under skills/<name>/ (Agent Skills convention).
SKILLS_DIR="skills"
SKILLS=(
  legacy-to-dbt-migration-foundations
  migrating-informatica-to-dbt
  migrating-talend-to-dbt
  migrating-stored-procedures-to-dbt
  migrating-matillion-to-dbt
  migrating-coalesce-to-dbt
  remediating-lift-and-shift-to-dbt
)

# --- pick the destination ---------------------------------------------------
DEST="$HOME/.dbt/wizard/skills"
LINK=0
while [ $# -gt 0 ]; do
  case "$1" in
    --claude) DEST="$HOME/.claude/skills"; shift ;;
    --codex)  DEST="$HOME/.codex/skills"; shift ;;
    --dest)   DEST="${2:?--dest needs a path}"; shift 2 ;;
    --link)   LINK=1; shift ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

# --- find the skill folders (this clone, or clone fresh) --------------------
SRC="$(cd "$(dirname "$0")" && pwd)"
CLEANUP=""
if [ ! -d "$SRC/$SKILLS_DIR/legacy-to-dbt-migration-foundations" ]; then
  echo "Fetching the skills from GitHub..."
  SRC="$(mktemp -d)"; CLEANUP="$SRC"
  git clone --depth 1 -q https://github.com/hicham-bab/dbt-legacy-migration-skills.git "$SRC"
fi

if [ "$LINK" = 1 ] && [ -n "$CLEANUP" ]; then
  echo "  ! --link needs a local clone; symlinks would point into a temp fetch that gets removed." >&2
  echo "    Clone the repo and run ./install.sh --link from inside it." >&2
  rm -rf "$CLEANUP"; exit 2
fi

# --- install ----------------------------------------------------------------
mkdir -p "$DEST"
echo "$([ "$LINK" = 1 ] && echo Symlinking || echo Installing) ${#SKILLS[@]} dbt migration skills into: $DEST"
for s in "${SKILLS[@]}"; do
  [ -d "$SRC/$SKILLS_DIR/$s" ] || { echo "  ! missing in source: $s (aborting)"; exit 1; }
  rm -rf "${DEST:?}/$s"          # replace only our own folders; leaves other skills untouched
  if [ "$LINK" = 1 ]; then
    ln -s "$SRC/$SKILLS_DIR/$s" "$DEST/$s"
  else
    cp -R "$SRC/$SKILLS_DIR/$s" "$DEST/$s"
  fi
  echo "  - $s"
done
[ -n "$CLEANUP" ] && rm -rf "$CLEANUP"

echo
if [ "$LINK" = 1 ]; then
  echo "Done. Symlinked $DEST -> $SRC/$SKILLS_DIR (repo edits now reflect live)."
  echo "Start a new agent session to reload; Claude Code picks up edits within the session."
else
  echo "Done. Installed into $DEST."
  echo "Restart your agent (e.g. quit and reopen dbt Wizard) so it picks up the skills."
fi
