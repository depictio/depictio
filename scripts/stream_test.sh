#!/bin/bash
# Stream test: two modes - reset (seed 3 rows) and stream (add rows one-by-one).
#
# Usage:
#   ./scripts/stream_test.sh reset          # Seed CSV with 3 rows, run CLI
#   ./scripts/stream_test.sh stream         # Add remaining rows one-by-one
#   ./scripts/stream_test.sh stream 5       # Same but 5s delay between rows

set -e

MODE="${1:-reset}"
DELAY="${2:-3}"

# Paths
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CSV="$REPO_ROOT/depictio/projects/test/image_demo/images_data.csv"
CLI="$REPO_ROOT/depictio/cli/.venv/bin/depictio-cli"
CLI_CONFIG="$REPO_ROOT/depictio/.depictio/admin_config.yaml"
PROJECT_CONFIG="$REPO_ROOT/depictio/projects/test/image_demo/project.yaml"
DC_ID="650a1b2c3d4e5f6a7b8c9d10"
API_URL="http://localhost:8137"

HEADER="sample_id,image_path,category,quality_score"

# All rows
ROWS=(
  "S001,sample_001.png,A,0.95"
  "S002,sample_002.png,A,0.87"
  "S003,sample_003.png,B,0.92"
  "S004,sample_004.png,B,0.78"
  "S005,sample_005.png,A,0.89"
  "S006,sample_006.png,C,0.94"
  "S007,sample_007.png,C,0.81"
  "S008,sample_008.png,B,0.96"
  "S009,sample_009.png,A,0.73"
)

SEED_COUNT=3  # rows to start with in reset mode

run_cli() {
  "$CLI" run \
    --CLI-config-path "$CLI_CONFIG" \
    --project-config-path "$PROJECT_CONFIG" \
    --update-config \
    --overwrite \
    --skip-s3-check \
    --skip-join 2>&1 | tail -5
}

trigger_ws() {
  curl -s -X POST "$API_URL/depictio/api/v1/events/test-trigger/$DC_ID" | python3 -m json.tool 2>/dev/null || true
}

case "$MODE" in
  reset)
    echo "=== RESET: Seeding CSV with $SEED_COUNT rows ==="
    echo "$HEADER" > "$CSV"
    for i in $(seq 0 $((SEED_COUNT - 1))); do
      echo "${ROWS[$i]}" >> "$CSV"
    done
    cat "$CSV"
    echo ""
    echo "--- Running CLI ---"
    run_cli
    echo ""
    echo "Done. Open dashboard, then run: ./scripts/stream_test.sh stream"
    ;;

  stream)
    # Count current data rows in CSV
    CURRENT=$(( $(wc -l < "$CSV" | tr -d ' ') - 1 ))
    REMAINING=$(( ${#ROWS[@]} - CURRENT ))

    if [ "$REMAINING" -le 0 ]; then
      echo "All ${#ROWS[@]} rows already in CSV. Run 'reset' first."
      exit 0
    fi

    echo "=== STREAM: Adding $REMAINING rows (current: $CURRENT) ==="
    echo ""

    for i in $(seq "$CURRENT" $(( ${#ROWS[@]} - 1 ))); do
      ROW_NUM=$((i + 1))
      echo "[$ROW_NUM/${#ROWS[@]}] Adding: ${ROWS[$i]}"
      echo "${ROWS[$i]}" >> "$CSV"

      run_cli
      trigger_ws

      if [ "$ROW_NUM" -lt "${#ROWS[@]}" ]; then
        echo "    Waiting ${DELAY}s..."
        sleep "$DELAY"
      fi
      echo ""
    done

    echo "=== DONE: All ${#ROWS[@]} rows in CSV ==="
    ;;

  *)
    echo "Usage: $0 {reset|stream} [delay_seconds]"
    exit 1
    ;;
esac
