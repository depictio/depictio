#!/usr/bin/env bash
# Stream test driver for the adapt_feedb_ms realtime dashboard.
# Each "tick" appends one row to phenobase.csv, re-runs depictio-cli to
# rewrite the delta table, and POSTs to /events/test-trigger so the
# WebSocket subscribers receive a `data_collection_updated` event with
# row_delta + new_ids in the payload.
#
# Modes:
#   reset                       Wipe CSV down to 2 seed rows, run CLI.
#   bump [N]                    Append N rows (default 1) once, no pause
#                               between them. Auto-generates rows past the
#                               predefined ROWS array — runs forever-safe.
#   stream [delay] [max]        Append rows one at a time with `delay`s in
#                               between. Stops after `max` rows (default
#                               unbounded — Ctrl+C to stop). `delay` defaults
#                               to 3s.
#   status                      Print current CSV row count + latest WS
#                               payload digest.
#
# Watch the dashboard at:
#   http://localhost:8055/dashboard-beta/69f899234da0b143a8538e0e

set -euo pipefail

MODE="${1:-reset}"

WORKTREE="/Users/tweber/Gits/workspaces/depictio-workspace/depictio-worktrees/viralrecon-template-dashboard"
CSV="$WORKTREE/depictio/projects/test/adapt_feedb_ms/phenobase.csv"
CLI_CONFIG="$WORKTREE/depictio/.depictio/test_user_config.yaml"
PROJECT_CONFIG="$WORKTREE/depictio/projects/test/adapt_feedb_ms/project.yaml"
DC_ID="750a1b2c3d4e5f6a7b8c9d10"
DASHBOARD_ID="69f899234da0b143a8538e0e"
API_URL="http://localhost:8055"

HEADER="index_index,coord_counter,acquisition_timestamp,features_area,features_eccentricity,features_solidity,features_intensity_mean-0,features_intensity_mean-1,features_intensity_mean-2,bounding_box_x0,bounding_box_y0,classifications_taxa,patches_patches_2d_rgb_path"

# Predefined "nice" seed rows. Used by `reset` and consumed first by
# `stream`/`bump`. Past row 8 we generate synthetic rows so the test can run
# forever without hitting an "all rows already in CSV" wall.
ROWS=(
  "1,0,2026-05-04T12:00:00Z,1234.5,0.42,0.95,128.3,140.1,98.4,100,200,1,cell_001.png"
  "2,0,2026-05-04T12:00:00Z,987.2,0.71,0.82,95.5,110.2,180.6,150,250,2,cell_002.png"
  "3,1,2026-05-04T12:00:05Z,1456.7,0.38,0.97,135.1,145.3,102.9,120,210,1,cell_003.png"
  "4,1,2026-05-04T12:00:05Z,789.4,0.78,0.79,88.2,105.7,195.1,160,260,2,cell_004.png"
  "5,2,2026-05-04T12:00:10Z,1378.9,0.45,0.93,132.6,142.8,99.1,110,205,1,cell_005.png"
  "6,2,2026-05-04T12:00:10Z,1023.6,0.69,0.85,99.8,113.5,178.4,155,255,2,cell_006.png"
  "7,3,2026-05-04T12:00:15Z,1289.3,0.41,0.96,130.7,143.2,101.5,115,208,1,cell_007.png"
  "8,3,2026-05-04T12:00:15Z,945.1,0.74,0.81,92.6,108.9,184.2,158,258,2,cell_008.png"
)

SEED_COUNT=2

# ---------------------------------------------------------------------------

# Return the next row to append. If the predefined ROWS array still has an
# entry past the current data-row count, return that. Otherwise synthesise
# one with a unique index_index, jittered features, and a recycled image.
next_row() {
  local data_rows="$1"           # current count of data rows in CSV
  local idx=$(( data_rows + 1 )) # next index_index value (1-based)
  if [ "$idx" -le "${#ROWS[@]}" ]; then
    echo "${ROWS[$((idx - 1))]}"
    return
  fi

  # Synthetic row. Use bash $RANDOM for a quick spread; not statistically
  # meaningful — we just need every row to be visibly different.
  local coord=$(( idx / 2 ))
  local ts; ts="$(date -u +%FT%TZ)"
  local area=$(( 800 + RANDOM % 900 ))
  # Two-decimal floats via printf — bash has no float math.
  local ecc;     ecc=$(printf '0.%02d'  $(( 30 + RANDOM % 50 )))
  local sol;     sol=$(printf '0.%02d'  $(( 75 + RANDOM % 22 )))
  local mean0=$(( 80 + RANDOM % 80 ))
  local mean1=$(( 100 + RANDOM % 60 ))
  local mean2=$(( 90 + RANDOM % 110 ))
  local bx=$(( 100 + RANDOM % 60 ))
  local by=$(( 200 + RANDOM % 60 ))
  local taxa=$(( 1 + RANDOM % 2 ))
  # Recycle the existing 8 sample PNGs so the gallery has thumbnails to load.
  local img_idx=$(( 1 + RANDOM % 8 ))
  local img; img=$(printf 'cell_%03d.png' "$img_idx")
  echo "${idx},${coord},${ts},${area}.0,${ecc},${sol},${mean0}.0,${mean1}.0,${mean2}.0,${bx},${by},${taxa},${img}"
}

run_cli() {
  ( cd "$WORKTREE" && /opt/homebrew/bin/uv run --no-sync python -m depictio.cli run \
      --CLI-config-path "$CLI_CONFIG" \
      --project-config-path "$PROJECT_CONFIG" \
      --update-config \
      --rescan-folders \
      --overwrite \
      --skip-dashboard-import \
      --skip-s3-check \
      --skip-join 2>&1 | tail -1 )
}

# Trigger + format the response into one digestible line:
#   v51  Δ+1 (10→11)  rows=11  new=[11]  conns=1
trigger_ws() {
  curl -s -X POST "$API_URL/depictio/api/v1/events/test-trigger/$DC_ID" \
    | python3 -c "
import json, sys
r = json.load(sys.stdin)
p = r.get('payload', {}) or {}
v = p.get('aggregation_version')
delta = p.get('row_delta')
prev = p.get('prev_row_count')
rows = p.get('row_count')
new = p.get('new_ids_sample') or []
total_new = p.get('new_ids_total')
conns = r.get('connections')
delta_str = ''
if delta is not None and delta != 0:
    sign = '+' if delta > 0 else ''
    if prev is not None and rows is not None:
        delta_str = f'  Δ{sign}{delta} ({prev}→{rows})'
    else:
        delta_str = f'  Δ{sign}{delta}'
new_str = ''
if new:
    extra = ''
    if total_new and total_new > len(new):
        extra = f' +{total_new - len(new)}'
    new_str = f'  new={list(new)}{extra}'
print(f\"  [ws] v{v}{delta_str}  rows={rows}{new_str}  conns={conns}\")
" || echo "  [ws] failed (is the API up?)"
}

current_data_rows() {
  # CSV row count minus header. Empty file → -1, so floor at 0.
  local total
  total=$(wc -l < "$CSV" | tr -d ' ')
  if [ "$total" -le 0 ]; then echo 0; else echo $((total - 1)); fi
}

append_one() {
  local data_rows; data_rows=$(current_data_rows)
  local row; row=$(next_row "$data_rows")
  echo "$row" >> "$CSV"
  printf '  + %s\n' "$row"
}

bump_n() {
  local n="${1:-1}"
  if ! [[ "$n" =~ ^[0-9]+$ ]] || [ "$n" -lt 1 ]; then
    echo "bump: count must be a positive integer (got '$n')" >&2
    exit 2
  fi
  local i
  for i in $(seq 1 "$n"); do
    local before; before=$(current_data_rows)
    echo "[$i/$n] CSV had ${before} data rows"
    append_one
    run_cli
    trigger_ws
    echo ""
  done
}

# ---------------------------------------------------------------------------

case "$MODE" in
  reset)
    echo "=== RESET: seeding CSV with $SEED_COUNT rows ==="
    echo "$HEADER" > "$CSV"
    for i in $(seq 0 $((SEED_COUNT - 1))); do
      echo "${ROWS[$i]}" >> "$CSV"
    done
    echo "--- Running CLI ---"
    run_cli
    echo ""
    echo "Done — $(current_data_rows) data row(s) in CSV."
    echo "Next:"
    echo "  $0 bump          # add 1 row + WS trigger"
    echo "  $0 bump 5        # add 5 rows back-to-back"
    echo "  $0 stream 2      # one row every 2 s, until Ctrl+C"
    ;;

  bump)
    bump_n "${2:-1}"
    ;;

  stream)
    DELAY="${2:-3}"
    MAX="${3:-0}"  # 0 = unbounded
    case "$DELAY" in
      ''|*[!0-9]*) echo "stream: delay must be a non-negative integer (got '$DELAY')" >&2; exit 2 ;;
    esac
    case "$MAX" in
      ''|*[!0-9]*) echo "stream: max must be a non-negative integer (got '$MAX')" >&2; exit 2 ;;
    esac
    if [ "$MAX" -eq 0 ]; then
      echo "=== STREAM: appending one row every ${DELAY}s — Ctrl+C to stop ==="
    else
      echo "=== STREAM: appending up to $MAX rows, ${DELAY}s between ticks ==="
    fi

    tick=0
    while true; do
      tick=$((tick + 1))
      before=$(current_data_rows)
      printf '[tick %d] CSV has %d data row(s) — appending\n' "$tick" "$before"
      append_one
      run_cli
      trigger_ws
      if [ "$MAX" -gt 0 ] && [ "$tick" -ge "$MAX" ]; then
        echo "=== DONE: added $tick row(s) ==="
        break
      fi
      sleep "$DELAY"
    done
    ;;

  status)
    rows=$(current_data_rows)
    echo "CSV: $CSV"
    echo "Data rows: $rows"
    echo "Dashboard: $API_URL/dashboard-beta/$DASHBOARD_ID"
    echo "Last DC: $DC_ID"
    echo ""
    echo "Latest payload (test-trigger, no append):"
    trigger_ws
    ;;

  *)
    cat <<EOF >&2
Usage:
  $0 reset                  Seed CSV with $SEED_COUNT rows + run CLI.
  $0 bump [N]               Append N rows (default 1), one CLI run + WS event each.
  $0 stream [delay] [max]   Loop: append, run CLI, fire WS event, sleep delay
                            (default 3 s). max=0 = unbounded (Ctrl+C to stop).
  $0 status                 Print current row count + ping the WS trigger.
EOF
    exit 1
    ;;
esac
