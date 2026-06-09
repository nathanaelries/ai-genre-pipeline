#!/usr/bin/env bash
# Batch-generate a series of verse videos that all share ONE character.
#
# Each non-blank, non-# line of the verses file is:   <run-name> | <theme/verse>
# Re-runnable: finished stages are cached, so a re-run only does what's missing.
#
# Usage:   sudo bash scripts/batch-generate.sh [verses.txt] [character-run]
#   verses.txt    list of verses (default: ./verses.txt; see verses.example.txt)
#   character-run prior run whose character to reuse (default: scripture-meditations)
#
# After this finishes: render each Suno brief
#   (outputs/<run>/03_music/track_01_suno_prompt.txt), drop the rendered mp3 at
#   outputs/<run>/03_music/track_01.mp3, then run scripts/batch-finish.sh.
set -uo pipefail

VERSES="${1:-verses.txt}"
CHARACTER="${2:-scripture-meditations}"

[ -f "$VERSES" ] || { echo "No verses file: $VERSES (copy verses.example.txt)"; exit 1; }

while IFS='|' read -r run theme; do
  run="$(echo "${run:-}" | xargs)"      # trim
  theme="$(echo "${theme:-}" | xargs)"
  [ -z "$run" ] && continue             # blank line
  case "$run" in \#*) continue ;; esac  # comment

  echo "=================================================================="
  echo ">> Generating '$run'"
  echo "   theme: $theme"
  echo "=================================================================="
  docker compose run --rm orchestrator run \
      --character "$CHARACTER" --run "$run" --theme "$theme" \
    || { echo "!! FAILED: $run (continuing to next)"; continue; }
done < "$VERSES"

echo
echo "All generated. Next: render each Suno brief, drop the mp3 into"
echo "outputs/<run>/03_music/track_01.mp3, then: sudo bash scripts/batch-finish.sh $VERSES"
