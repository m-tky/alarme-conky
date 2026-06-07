#!/usr/bin/env bash
set -eu
"$JQ" -r '.data.today_tasks[]? | "• \(.title)" + (if .scheduled_time then "  \(.scheduled_time)" else "" end)' \
  "$STATE_FILE" 2>/dev/null | head -n 5
