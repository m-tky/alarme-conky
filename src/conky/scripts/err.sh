#!/usr/bin/env bash
# Error line — already silent on success. No header glyph, just the
# alert-colored message, because the toast (notify-send) already gave
# the user the loud version.
set -eu
err=$("$JQ" -r '.meta.last_error // ""' "$STATE_FILE" 2>/dev/null)
if [ -n "$err" ]; then
  printf '${color #%s}⚠ %s${color}\n' "$COLOR_ALERT" "$err"
fi
