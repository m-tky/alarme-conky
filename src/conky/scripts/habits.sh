#!/usr/bin/env bash
# Habits row — render each habit as "<glyph> <name>  ▰▰▰▱▱" so multi-
# count goals (target_count > 1) read at a glance. For target_count=1
# the bar collapses to a single ✓/○.
set -eu
"$JQ" -r --arg ok "$COLOR_OK" --arg muted "$COLOR_MUTED" '
  if .data.habits_today and (.data.habits_today | length) > 0 then
    .data.habits_today
    | map(
        if .target_count and .target_count > 1 then
          (.count // 0) as $c
          | (.target_count) as $t
          | (["▰"] * $c + ["▱"] * ($t - $c)) | join("")
            | (
                "${color #" + $ok + "}" + . + "${color}  " + .name
              )
        else
          (if (.done // false) then "${color #" + $ok + "}✓${color}" else "${color #" + $muted + "}○${color}" end)
          + " " + .name
        end
      )
    | join("   ")
  else "" end
' "$STATE_FILE" 2>/dev/null
