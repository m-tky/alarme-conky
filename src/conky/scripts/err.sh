#!/usr/bin/env bash
# Error — alert-coloured one-liner with the Nerd Font warning glyph.
set -eu
err=$("$JQ" -r '.meta.last_error // ""' "$STATE_FILE" 2>/dev/null)
if [ -n "$err" ]; then
  printf '${color #%s}${font %s}%s${font %s} %s${color}\n' \
    "$COLOR_ALERT" "$NF_FONT" "$GLYPH_WARN" "$MAIN_FONT" "$err"
fi
