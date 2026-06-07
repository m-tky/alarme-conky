#!/usr/bin/env bash
# Pomodoro — top-of-panel block when a session is active, silent
# otherwise. The cairo ring (drawn by pomo-ring.lua at top-right)
# carries the remaining time; we emit just the section header and
# the focused task title on the left so the ring has a textual
# anchor. Title is hard-truncated to ~22 chars because the right
# half of the row is reserved for the ring.
set -eu
has_active=$("$JQ" -r 'if .data.pomodoro then "yes" else "no" end' "$STATE_FILE" 2>/dev/null || echo no)
if [ "$has_active" != "yes" ]; then exit 0; fi
"$JQ" -r \
  --arg c8 "$COLOR_ACCENT" \
  --arg nf_font "$NF_FONT" \
  --arg main_font "$MAIN_FONT" \
  --arg glyph "$GLYPH_STOPWATCH" '
  .data.pomodoro as $p
  | ($p.task_title | .[0:22]) as $title
  | "${color #" + $c8 + "}${font " + $nf_font + "}" + $glyph + "${font " + $main_font + "} Pomodoro${color}\n" +
    $title
' "$STATE_FILE" 2>/dev/null
