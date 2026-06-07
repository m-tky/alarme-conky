#!/usr/bin/env bash
# Inbox block — fully conditional. When the user has nothing
# unscheduled, the whole block (header + body) is omitted so the panel
# shrinks vertically instead of leaving a "── Inbox ──" stub on screen.
set -eu
total=$("$JQ" -r '.data.inbox_count // 0' "$STATE_FILE" 2>/dev/null || echo 0)
if [ "$total" -eq 0 ]; then exit 0; fi
printf '${color #%s}── Inbox ──────────────${color}\n' "$COLOR_SECTION"
"$JQ" -r '.data.inbox_tasks[]? | "• " + .title' "$STATE_FILE"
shown=$("$JQ" -r '.data.inbox_tasks | length' "$STATE_FILE" 2>/dev/null || echo 0)
remainder=$(( total - shown ))
if [ "$remainder" -gt 0 ]; then
  printf '+ %d more\n' "$remainder"
fi
