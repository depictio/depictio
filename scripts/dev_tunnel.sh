#!/usr/bin/env bash
# Reach the Depictio running in a sandbox whose only way out is an HTTPS proxy
# (Claude Code on the web). The sandbox dials out to Tailscale and keeps that connection
# open; Funnel (or `serve`) hands incoming requests down it, so no port is opened here.
#
#   scripts/dev_tunnel.sh up       start tailscaled, join the tailnet, publish the port
#   scripts/dev_tunnel.sh status   print the URL and what is running
#   scripts/dev_tunnel.sh down     unpublish and stop tailscaled
#
# Safe to re-run: `up` after a container restart reuses the saved login.
#
# Env:
#   TS_AUTHKEY            reusable + ephemeral auth key. Without it, the first `up` prints a
#                         login link to open once.
#   DEV_TUNNEL_PORT       port to publish (8058, the Depictio API + viewer)
#   DEV_TUNNEL_HOSTNAME   node name in the tailnet (depictio-dev)
#   DEV_TUNNEL_PUBLIC     1 (default) = Funnel, a public https URL; 0 = tailnet devices only.
#                         `depictio local up` has no login, so a public URL is open to anyone
#                         who finds it: use it for throwaway dev stacks only.
set -euo pipefail

PORT="${DEV_TUNNEL_PORT:-8058}"
NAME="${DEV_TUNNEL_HOSTNAME:-depictio-dev}"
PUBLIC="${DEV_TUNNEL_PUBLIC:-1}"
ROOT="${DEV_TUNNEL_HOME:-${TMPDIR:-/tmp}/depictio-tunnel}"
BIN="$ROOT/bin"
STATE="$ROOT/state"
SOCK="$STATE/ts.sock"
PIDFILE="$ROOT/tailscaled.pid"

say() { printf '%s\n' "$*" >&2; }
ts() { "$BIN/tailscale" --socket="$SOCK" "$@"; }

install_tailscale() {
  [ -x "$BIN/tailscaled" ] && return 0
  local arch
  case "$(uname -m)" in
    x86_64) arch=amd64 ;;
    aarch64 | arm64) arch=arm64 ;;
    *) say "Unsupported architecture: $(uname -m)"; exit 1 ;;
  esac
  say "Downloading Tailscale ($arch)"
  mkdir -p "$BIN"
  curl -fsSL "https://pkgs.tailscale.com/stable/tailscale_latest_${arch}.tgz" |
    tar xz -C "$BIN" --strip-components=1 --wildcards '*/tailscale' '*/tailscaled'
}

daemon_running() {
  local pid
  [ -f "$PIDFILE" ] || return 1
  pid="$(cat "$PIDFILE")"
  # A pid from before a container restart can belong to anything now: check its name.
  [ -r "/proc/$pid/cmdline" ] && grep -qa tailscaled "/proc/$pid/cmdline"
}

start_daemon() {
  daemon_running && return 0
  mkdir -p "$STATE"
  rm -f "$SOCK"
  # tailscaled reads the proxy from the environment. --statedir is not optional: without
  # it there is nowhere to keep the HTTPS certificate and every TLS handshake fails with
  # "no TailscaleVarRoot".
  export HTTP_PROXY="${HTTP_PROXY:-${HTTPS_PROXY:-}}"
  nohup "$BIN/tailscaled" --tun=userspace-networking --state="$STATE/state.json" \
    --statedir="$STATE" --socket="$SOCK" >"$ROOT/tailscaled.log" 2>&1 &
  echo $! >"$PIDFILE"
  for _ in $(seq 20); do
    [ -S "$SOCK" ] && return 0
    sleep 0.5
  done
  say "tailscaled did not start, see $ROOT/tailscaled.log"
  exit 1
}

backend_state() {
  ts status --json 2>/dev/null |
    python3 -c 'import sys, json; print(json.load(sys.stdin).get("BackendState", ""))' 2>/dev/null || true
}

join_tailnet() {
  # A saved login comes back to Running by itself within a few seconds.
  for _ in $(seq 15); do
    [ "$(backend_state)" = Running ] && return 0
    sleep 1
  done
  if [ -n "${TS_AUTHKEY:-}" ]; then
    ts up --authkey="$TS_AUTHKEY" --hostname="$NAME" --timeout=60s
  else
    say "No TS_AUTHKEY: open the login link below once to add this machine to your tailnet."
    ts up --hostname="$NAME" --timeout=300s || true
  fi
}

publish() {
  if [ "$PUBLIC" = 1 ]; then
    # When Funnel is not yet enabled on the tailnet, the command prints a link and waits.
    local out
    out="$(timeout 30 "$BIN/tailscale" --socket="$SOCK" funnel --bg "$PORT" 2>&1 || true)"
    case "$out" in
      *"not enabled"*) say "$out"; say "Open the link above, then run this again."; return 1 ;;
    esac
  else
    ts serve --bg --tcp "$PORT" "tcp://localhost:$PORT" >/dev/null
  fi
}

dns_name() {
  ts status --json 2>/dev/null |
    python3 -c 'import sys, json; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))'
}

report() {
  local host
  host="$(dns_name)"
  if [ "$PUBLIC" = 1 ]; then
    echo "https://$host/"
  else
    echo "http://$host:$PORT/  (only from a device on your tailnet)"
  fi
  if ! curl -fs -o /dev/null "http://localhost:$PORT/"; then
    say "Nothing answers on localhost:$PORT yet: start Depictio (depictio local up --no-open)."
  fi
}

case "${1:-}" in
  up)
    install_tailscale
    start_daemon
    join_tailnet
    publish
    report
    ;;
  status)
    daemon_running || { say "tailscaled is not running (scripts/dev_tunnel.sh up)"; exit 1; }
    echo "state: $(backend_state)"
    report
    ts funnel status 2>&1 | grep -v '^$' || true
    ;;
  down)
    if daemon_running; then
      ts funnel --https=443 off >/dev/null 2>&1 || true
      ts serve reset >/dev/null 2>&1 || true
      kill "$(cat "$PIDFILE")" 2>/dev/null || true
      rm -f "$PIDFILE"
    fi
    echo "stopped"
    ;;
  *)
    say "usage: $0 up|status|down"
    exit 2
    ;;
esac
