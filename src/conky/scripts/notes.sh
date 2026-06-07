#!/usr/bin/env bash
# Notes block — self-headering, conditional. Backend currently has no
# global recent-notes endpoint so this stays silent until a future
# revision populates ``.data.notes_recent``.
set -eu
shown=$("$JQ" -r '.data.notes_recent | length' "$STATE_FILE" 2>/dev/null || echo 0)
if [ "$shown" -eq 0 ]; then exit 0; fi
printf '${color #%s}── Notes ──────────────${color}\n' "$COLOR_SECTION"
"$JQ" -r '.data.notes_recent[]? | "• \(.title)"' "$STATE_FILE" | head -n 3
