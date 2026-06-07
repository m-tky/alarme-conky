#!/usr/bin/env bash
# Pomodoro block — self-headering, conditional. Only renders while a
# session is active; the rest of the time the user has one less line
# of decoration on the panel.
set -eu
has_active=$("$JQ" -r 'if .data.pomodoro then "yes" else "no" end' "$STATE_FILE" 2>/dev/null || echo no)
if [ "$has_active" != "yes" ]; then exit 0; fi
"$JQ" -r --arg c8 "$COLOR_ACCENT" --arg c3 "$COLOR_HIGHLIGHT" '
  "${color #" + $c8 + "}── Pomodoro ──────────${color}\n" +
  .data.pomodoro.task_title + "\n" +
  "${color #" + $c3 + "}" + .data.pomodoro.remaining + "${color}"
' "$STATE_FILE"
