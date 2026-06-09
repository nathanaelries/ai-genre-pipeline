#!/usr/bin/env bash
# Finish (mux audio + assemble) every verse that has a rendered song dropped in.
#
# Run AFTER you've placed each Suno render at outputs/<run>/03_music/track_01.<ext>.
# Verses without an audio file yet are skipped, so it's safe to run repeatedly as
# you finish rendering more songs.
#
# Usage:   sudo bash scripts/batch-finish.sh [verses.txt]
set -uo pipefail

VERSES="${1:-verses.txt}"
[ -f "$VERSES" ] || { echo "No verses file: $VERSES"; exit 1; }

while IFS='|' read -r run theme; do
  run="$(echo "${run:-}" | xargs)"
  [ -z "$run" ] && continue
  case "$run" in \#*) continue ;; esac

  audio=""
  for ext in mp3 wav m4a flac ogg opus aac; do
    if [ -f "outputs/$run/03_music/track_01.$ext" ]; then audio="track_01.$ext"; break; fi
  done

  if [ -n "$audio" ]; then
    echo "=== Finishing '$run'  (audio: $audio) ==="
    docker compose run --rm orchestrator run --redo final --run "$run" \
      || echo "!! FAILED: $run (continuing)"
  else
    echo "--- Skipping '$run' — no audio in outputs/$run/03_music/ yet ---"
  fi
done < "$VERSES"
