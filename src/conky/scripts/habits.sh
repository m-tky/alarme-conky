#!/usr/bin/env bash
set -eu
"$JQ" -r '
  if .data.habits_today then
    (.data.habits_today | map(if .done then "✓" else "○" end + " " + .name) | join("  "))
  else "" end' "$STATE_FILE" 2>/dev/null
