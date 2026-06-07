#!/usr/bin/env bash
# Pomodoro — self-headering with Nerd Font stopwatch glyph (user
# preference over the tomato emoji, which renders as full red colour
# on most systems). Body shows task title + remaining MM:SS + a
# Unicode block progress bar driven by .data.pomodoro.elapsed_ratio.
set -eu
has_active=$("$JQ" -r 'if .data.pomodoro then "yes" else "no" end' "$STATE_FILE" 2>/dev/null || echo no)
if [ "$has_active" != "yes" ]; then exit 0; fi
"$JQ" -r \
  --arg c8 "$COLOR_ACCENT" \
  --arg c3 "$COLOR_HIGHLIGHT" \
  --arg muted "$COLOR_MUTED" \
  --arg nf_font "$NF_FONT" \
  --arg main_font "$MAIN_FONT" \
  --arg glyph "$GLYPH_STOPWATCH" '
  .data.pomodoro as $p
  | ($p.elapsed_ratio // 0) as $r
  | (12 * $r | floor) as $filled
  | (["▰"] * $filled + ["▱"] * (12 - $filled) | join("")) as $bar
  | "${voffset 4}${color #" + $c8 + "}${font " + $nf_font + "}" + $glyph + "${font " + $main_font + "} Pomodoro${color}\n" +
    $p.task_title + "\n" +
    "${color #" + $c3 + "}" + $p.remaining + "${color}  " +
    "${color #" + $muted + "}" + $bar + "${color}"
' "$STATE_FILE" 2>/dev/null
