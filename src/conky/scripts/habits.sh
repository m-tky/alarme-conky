#!/usr/bin/env bash
# Habits — self-headering with Nerd Font fire glyph, conditional.
# Hides on zero habits so the panel doesn't carry a lonely "Habits"
# label when none are configured.
#
# Each habit renders as either ✓/○ (target_count == 1) or a
# ▰▰▰▱▱ progress bar (target_count > 1), so multi-count goals like
# "drink water 3 times" show real progress instead of a binary tick.
set -eu
n=$("$JQ" -r '(.data.habits_today // []) | length' "$STATE_FILE" 2>/dev/null || echo 0)
if [ "$n" -eq 0 ]; then exit 0; fi
printf '${voffset 4}${color #%s}${font %s}%s${font %s} Habits${color}\n' \
  "$COLOR_SECTION" "$NF_FONT" "$GLYPH_FIRE" "$MAIN_FONT"
"$JQ" -r --arg ok "$COLOR_OK" --arg muted "$COLOR_MUTED" '
  .data.habits_today
  | map(
      if .target_count and .target_count > 1 then
        (.count // 0) as $c
        | (.target_count) as $t
        | (
            "${color #" + $ok + "}"
            + ((["▰"] * $c + ["▱"] * ($t - $c)) | join(""))
            + "${color}  " + .name
          )
      else
        (if (.done // false) then "${color #" + $ok + "}✓${color}" else "${color #" + $muted + "}○${color}" end)
        + " " + .name
      end
    )
  | join("   ")
' "$STATE_FILE" 2>/dev/null
