#!/usr/bin/env bash
# Notes — self-headering with Nerd Font sticky-note glyph. The backend
# currently has no global recent-notes endpoint so this stays silent.
set -eu
shown=$("$JQ" -r '.data.notes_recent | length' "$STATE_FILE" 2>/dev/null || echo 0)
if [ "$shown" -eq 0 ]; then exit 0; fi
printf '${voffset 4}${color #%s}${font %s}%s${font %s} Notes${color}\n' \
  "$COLOR_SECTION" "$NF_FONT" "$GLYPH_NOTE" "$MAIN_FONT"
"$JQ" -r '.data.notes_recent[]? | "• \(.title)"' "$STATE_FILE" | head -n 3
