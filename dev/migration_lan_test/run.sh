#!/usr/bin/env bash
# Depictio instances on a LAN: A (source) pushes a project to B (target),
# B's admin approves it, B serves it published read-only. Issue #1303.
# C is a target with the Helm chart's defaults (inbound on, no pairing key):
# its admin issues an invite code, A publishes to C with the URL + code.
#
#   One machine, two instances (both reached through the LAN address):
#     dev/migration_lan_test/run.sh demo [LAN_IP]
#
#   Two machines:
#     on B:  dev/migration_lan_test/run.sh target B_IP
#     on A:  dev/migration_lan_test/run.sh source A_IP http://B_IP:18059
#     then:  uv run --extra dev python dev/migration_lan_test/check.py \
#              --source http://A_IP:18058 --target http://B_IP:18059
#
#   Stop:    dev/migration_lan_test/run.sh down
#
# `depictio local up` (single-user mode, its own MongoDB/Redis/SeaweedFS) binds
# 127.0.0.1 only, so forward.py exposes each API on the LAN address. Both sides
# share one pairing key: PAIRING_KEY, or a generated one kept in $WORK/pairing.key.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
WORK="${WORK:-${TMPDIR:-/tmp}/depictio-migration-lan}"
A_PORT="${A_PORT:-18058}"
B_PORT="${B_PORT:-18059}"
C_PORT="${C_PORT:-18060}"
mkdir -p "$WORK"

lan_ip() { hostname -I 2>/dev/null | awk '{print $1}'; }

pairing_key() {
  if [[ -n "${PAIRING_KEY:-}" ]]; then echo "$PAIRING_KEY"; return; fi
  [[ -s "$WORK/pairing.key" ]] || python3 -c 'import secrets; print(secrets.token_hex(32))' >"$WORK/pairing.key"
  cat "$WORK/pairing.key"
}

depictio_local() { # home, args...
  local home="$1"; shift
  (cd "$REPO" && DEPICTIO_LOCAL_HOME="$home" uv run --extra local depictio local "$@")
}

forward() { # ip, port
  local log="$WORK/forward-$2.log"
  nohup python3 "$HERE/forward.py" "$1" "$2" >"$log" 2>&1 &
  echo $! >"$WORK/forward-$2.pid"
}

up_target() { # ip
  local ip="$1" key; key="$(pairing_key)"
  DEPICTIO_MIGRATION_UI_ENABLED=true \
  DEPICTIO_MIGRATION_INSTANCE_LABEL="lan-b" \
  DEPICTIO_MIGRATION_INBOUND_ENABLED=true \
  DEPICTIO_MIGRATION_INBOUND_SOURCES="$(python3 -c 'import json, sys; b = sys.argv[2]; print(json.dumps([{"name": "lan-a", "pairing_key": sys.argv[1], "allowed_source_buckets": [b] if b else []}]))' "$key" "${SHARED_SOURCE_BUCKET:-}")" \
  NO_PROXY="${NO_PROXY:-},$ip" no_proxy="${no_proxy:-},$ip" \
    depictio_local "$WORK/b" up --port "$B_PORT" --no-open --examples none
  forward "$ip" "$B_PORT"
  echo "target: http://$ip:$B_PORT"
}

# Chart-like defaults (helm-charts/depictio/values.yaml): inbound and UI on,
# no INBOUND_SOURCES. Nothing is accepted until C's admin issues an invite.
up_invite_target() { # ip
  local ip="$1"
  DEPICTIO_MIGRATION_UI_ENABLED=true \
  DEPICTIO_MIGRATION_INBOUND_ENABLED=true \
  DEPICTIO_MIGRATION_INSTANCE_LABEL="lan-c" \
  NO_PROXY="${NO_PROXY:-},$ip" no_proxy="${no_proxy:-},$ip" \
    depictio_local "$WORK/c" up --port "$C_PORT" --no-open --examples none
  forward "$ip" "$C_PORT"
  echo "invite target: http://$ip:$C_PORT"
}

up_source() { # ip, target url
  local ip="$1" target="$2" key thost; key="$(pairing_key)"
  thost="$(python3 -c 'import sys, urllib.parse as u; print(u.urlsplit(sys.argv[1]).hostname)' "$target")"
  # A LAN destination is plain http on a private address: the host must be both
  # an allowed destination domain and on the UI host allowlist.
  DEPICTIO_MIGRATION_DESTINATION_DOMAINS="[\"$thost\"]" \
  DEPICTIO_MIGRATION_UI_TARGET_HOST_ALLOWLIST="[\"$thost\"]" \
  DEPICTIO_MIGRATION_UI_ENABLED=true \
  DEPICTIO_MIGRATION_INSTANCE_LABEL="lan-a" \
  DEPICTIO_MIGRATION_TARGETS="[{\"name\": \"lan-b\", \"url\": \"$target\", \"pairing_key\": \"$key\"}]" \
  NO_PROXY="${NO_PROXY:-},$thost" no_proxy="${no_proxy:-},$thost" \
    depictio_local "$WORK/a" up --port "$A_PORT" --no-open --examples iris
  forward "$ip" "$A_PORT"
  echo "source: http://$ip:$A_PORT"
}

down() {
  for pid in "$WORK"/forward-*.pid; do
    [[ -e "$pid" ]] && { kill "$(cat "$pid")" 2>/dev/null || true; rm -f "$pid"; }
  done
  for side in a b c; do
    if [[ -d "$WORK/$side" ]]; then depictio_local "$WORK/$side" down || true; fi
  done
}

case "${1:-}" in
  demo)
    ip="${2:-$(lan_ip)}"
    up_target "$ip"
    up_invite_target "$ip"
    up_source "$ip" "http://$ip:$B_PORT"
    (cd "$REPO" && NO_PROXY="${NO_PROXY:-},$ip" no_proxy="${no_proxy:-},$ip" \
      uv run --extra dev python "$HERE/check.py" \
        --source "http://$ip:$A_PORT" --target "http://$ip:$B_PORT" \
        --pairing-key "$(pairing_key)" \
        --source-home "$WORK/a" --target-home "$WORK/b" \
        --invite-target "http://$ip:$C_PORT" --invite-target-home "$WORK/c" \
        --report "$WORK/report.md")
    ;;
  target) up_target "${2:?target LAN ip}" ;;
  invite-target) up_invite_target "${2:?target LAN ip}" ;;
  source) up_source "${2:?source LAN ip}" "${3:?target url, e.g. http://B_IP:$B_PORT}" ;;
  down) down ;;
  *) sed -n '2,20p' "$0"; exit 2 ;;
esac
