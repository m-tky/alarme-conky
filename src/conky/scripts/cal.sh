#!/usr/bin/env bash
# Print the month grid (pre-rendered by the fetcher with conky color
# escapes already baked in) followed by 1-2 highlight lines so a glance
# answers both "where am I in the month?" and "what's next?".
set -eu
"$JQ" -r '.data.calendar_grid // ""' "$STATE_FILE" 2>/dev/null
"$JQ" -r '.data.calendar_highlights[]?' "$STATE_FILE" 2>/dev/null
