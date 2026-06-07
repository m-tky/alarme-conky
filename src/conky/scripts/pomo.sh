#!/usr/bin/env bash
# Pomodoro — self-headering, conditional. Renders only while a session
# is active. The progress visual is a cairo ring drawn by
# ``pomo-ring.lua``; we emit just the title and remaining time here so
# the ring has a textual companion that says *what* you're focusing on
# and *how much longer*. The ring + this text appear in different parts
# of the panel (ring top-right, text inside the Pomodoro section) — by
# design, since the text needs to flow with the other sections while
# the ring wants a stable corner spot to read at a glance.
set -eu
has_active=$("$JQ" -r 'if .data.pomodoro then "yes" else "no" end' "$STATE_FILE" 2>/dev/null || echo no)
if [ "$has_active" != "yes" ]; then exit 0; fi
"$JQ" -r \
  --arg c8 "$COLOR_ACCENT" \
  --arg c3 "$COLOR_HIGHLIGHT" \
  --arg nf_font "$NF_FONT" \
  --arg main_font "$MAIN_FONT" \
  --arg glyph "$GLYPH_STOPWATCH" '
  .data.pomodoro as $p
  | "${voffset 4}${color #" + $c8 + "}${font " + $nf_font + "}" + $glyph + "${font " + $main_font + "} Pomodoro${color}\n" +
    $p.task_title + "\n" +
    "${color #" + $c3 + "}" + $p.remaining + "${color}"
' "$STATE_FILE" 2>/dev/null
