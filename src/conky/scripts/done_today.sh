#!/usr/bin/env bash
# Done today — self-headering with Nerd Font check glyph. Stays silent
# on zero-completion days so the panel doesn't accuse the user of
# being unproductive when they just opened it.
set -eu
shown=$("$JQ" -r '.data.done_today_tasks | length' "$STATE_FILE" 2>/dev/null || echo 0)
if [ "$shown" -eq 0 ]; then exit 0; fi
printf '${voffset 4}${color #%s}${font %s}%s${font %s} Done today${color}\n' \
  "$COLOR_SECTION" "$NF_FONT" "$GLYPH_CHECK" "$MAIN_FONT"
"$JQ" -r --arg ok "$COLOR_OK" '
  .data.done_today_tasks[]? | "${color #" + $ok + "}✓${color}  " + .title
' "$STATE_FILE"
total=$("$JQ" -r '.data.done_today_count // 0' "$STATE_FILE" 2>/dev/null || echo 0)
remainder=$(( total - shown ))
if [ "$remainder" -gt 0 ]; then
  printf '+ %d more\n' "$remainder"
fi
