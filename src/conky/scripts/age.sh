#!/usr/bin/env bash
# Print the freshness badge: green < 60s, yellow < 5m, red ≥ 5m.
# Reads ageEnv injected via systemd / parent script (STATE_FILE, JQ, COLOR_OK,
# COLOR_HIGHLIGHT, COLOR_ALERT). These come from the home.nix wrapper which
# substitutes Nix values into a tiny env-prelude.
set -eu
file="${STATE_FILE:?STATE_FILE not set}"
jq_bin="${JQ:?JQ not set}"
if [ ! -f "$file" ]; then echo "no data"; exit 0; fi
now=$(date +%s)
then_=$("$jq_bin" -r '.meta.fetched_at_epoch // 0' "$file")
diff=$(( now - then_ ))
if   [ "$diff" -lt 60 ];  then col="$COLOR_OK";        label="${diff}s ago"
elif [ "$diff" -lt 300 ]; then col="$COLOR_HIGHLIGHT"; label="$((diff/60))m ago"
else                           col="$COLOR_ALERT";    label="$((diff/60))m ago"
fi
printf '${color #%s}⟳ %s' "$col" "$label"
