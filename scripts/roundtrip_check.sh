#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WORKTREE="$(cd "$SCRIPT_DIR/.." && pwd)"

# Allow env var overrides so CI can pass its own paths
CLI="${CLI:-$WORKTREE/depictio/cli/.venv/bin/depictio-cli}"
PYTHON="${PYTHON:-$WORKTREE/depictio/cli/.venv/bin/python}"
CONFIG="${CONFIG:-$WORKTREE/depictio/.depictio/admin_config.yaml}"
IRIS_ID="${IRIS_ID:-6824cb3b89d2b72169309737}"
TMP="$WORKTREE/scripts/_roundtrip_tmp"

mkdir -p "$TMP"

# Helper: extract a count from dashboard JSON using a jq-style Python expression.
# Usage: json_count "$JSON_STRING" "python expression returning int"
json_count() {
  echo "$1" | "$PYTHON" -c "
import sys, json
d = json.load(sys.stdin)
print($2)
"
}

# Helper: assert two values are equal, exit 1 with message on mismatch.
assert_eq() {
  if [ "$1" != "$2" ]; then
    echo "ERROR: $3 ($1 vs $2)"
    exit 1
  fi
}

echo "=== Step 1: export original dashboard ==="
"$CLI" dashboard export "$IRIS_ID" --config "$CONFIG" --output "$TMP/yaml1.yaml"

echo "=== Step 2: patch title + strip dashboard_id ==="
"$PYTHON" -c "
import yaml, uuid
p = '$TMP/yaml1.yaml'
d = yaml.safe_load(open(p))
d['title'] = 'roundtrip-test-' + uuid.uuid4().hex[:8]
d.pop('dashboard_id', None)
open('$TMP/modified.yaml', 'w').write(
    yaml.dump(d, allow_unicode=True, sort_keys=False, default_flow_style=False, indent=4)
)
print('Modified title:', d['title'])
"

echo "=== Step 3: import modified YAML ==="
IMPORT_OUT=$("$CLI" dashboard import "$TMP/modified.yaml" --config "$CONFIG" 2>&1)
echo "$IMPORT_OUT"

# Extract 24-char hex ObjectId from output
NEW_ID=$(echo "$IMPORT_OUT" | grep -oE '[0-9a-f]{24}' | head -1)
echo "New dashboard_id: $NEW_ID"

if [ -z "$NEW_ID" ]; then
  echo "ERROR: could not extract dashboard_id from import output"
  exit 1
fi

echo "=== Step 4: export new dashboard ==="
"$CLI" dashboard export "$NEW_ID" --config "$CONFIG" --output "$TMP/yaml2.yaml"

echo "=== Step 5: compare YAMLs ==="
"$PYTHON" "$SCRIPT_DIR/roundtrip_compare.py" "$TMP/yaml1.yaml" "$TMP/yaml2.yaml"

echo "=== Step 6: compare DB JSON via API ==="
API_BASE=$(grep 'api_base_url' "$CONFIG" | awk '{print $2}')
JWT_TOKEN=$(grep 'access_token' "$CONFIG" | awk '{print $2}' | tr -d "'\"")

DASH1_JSON=$(curl -sf -H "Authorization: Bearer $JWT_TOKEN" "$API_BASE/depictio/api/v1/dashboards/get/$IRIS_ID")
DASH2_JSON=$(curl -sf -H "Authorization: Bearer $JWT_TOKEN" "$API_BASE/depictio/api/v1/dashboards/get/$NEW_ID")

META1=$(json_count "$DASH1_JSON" "len(d.get('stored_metadata', []))")
META2=$(json_count "$DASH2_JSON" "len(d.get('stored_metadata', []))")
echo "Dashboard 1: $META1 components in DB"
echo "Dashboard 2: $META2 components in DB"
assert_eq "$META1" "$META2" "component count mismatch"

LAYOUT1=$(json_count "$DASH1_JSON" "len(d.get('left_panel_layout_data', [])) + len(d.get('right_panel_layout_data', []))")
LAYOUT2=$(json_count "$DASH2_JSON" "len(d.get('left_panel_layout_data', [])) + len(d.get('right_panel_layout_data', []))")
echo "Dashboard 1: $LAYOUT1 layout items in DB"
echo "Dashboard 2: $LAYOUT2 layout items in DB"
assert_eq "$LAYOUT1" "$LAYOUT2" "layout item count mismatch"
assert_eq "$META1" "$LAYOUT1" "Dashboard 1: $META1 components but $LAYOUT1 layout items"
assert_eq "$META2" "$LAYOUT2" "Dashboard 2: $META2 components but $LAYOUT2 layout items"

echo "OK: DB structure verified -- $META1 components, $LAYOUT1 layout items in both dashboards"
