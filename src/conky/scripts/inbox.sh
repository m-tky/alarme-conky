#!/usr/bin/env bash
# Inbox — self-headering with Nerd Font inbox glyph. Hides on zero so
# the panel shrinks when the inbox is empty.
set -eu
total=$("$JQ" -r '.data.inbox_count // 0' "$STATE_FILE" 2>/dev/null || echo 0)
if [ "$total" -eq 0 ]; then exit 0; fi
printf '${voffset 4}${color #%s}${font %s}%s${font %s} Inbox${color}\n' \
  "$COLOR_SECTION" "$NF_FONT" "$GLYPH_INBOX" "$MAIN_FONT"
"$JQ" -r '.data.inbox_tasks[]? | "• " + .title' "$STATE_FILE"
shown=$("$JQ" -r '.data.inbox_tasks | length' "$STATE_FILE" 2>/dev/null || echo 0)
remainder=$(( total - shown ))
if [ "$remainder" -gt 0 ]; then
  printf '+ %d more\n' "$remainder"
fi
