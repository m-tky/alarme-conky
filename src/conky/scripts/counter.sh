#!/usr/bin/env bash
# Print one counter from the state JSON. $1 = field name under .data.counters.
set -eu
field="${1:?field required}"
"$JQ" -r ".data.counters.$field // 0" "$STATE_FILE" 2>/dev/null || echo 0
