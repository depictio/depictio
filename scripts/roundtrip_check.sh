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

META1=$(echo "$DASH1_JSON" | "$PYTHON" -c "import sys,json; print(len(json.load(sys.stdin).get('stored_metadata',[])))")
META2=$(echo "$DASH2_JSON" | "$PYTHON" -c "import sys,json; print(len(json.load(sys.stdin).get('stored_metadata',[])))")
echo "Dashboard 1: $META1 components in DB"
echo "Dashboard 2: $META2 components in DB"
[ "$META1" = "$META2" ] || { echo "ERROR: component count mismatch ($META1 vs $META2)"; exit 1; }

LAYOUT1=$(echo "$DASH1_JSON" | "$PYTHON" -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('left_panel_layout_data',[])) + len(d.get('right_panel_layout_data',[])))")
LAYOUT2=$(echo "$DASH2_JSON" | "$PYTHON" -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('left_panel_layout_data',[])) + len(d.get('right_panel_layout_data',[])))")
echo "Dashboard 1: $LAYOUT1 layout items in DB"
echo "Dashboard 2: $LAYOUT2 layout items in DB"
[ "$LAYOUT1" = "$LAYOUT2" ] || { echo "ERROR: layout item count mismatch ($LAYOUT1 vs $LAYOUT2)"; exit 1; }
[ "$META1" = "$LAYOUT1" ] || { echo "ERROR: Dashboard 1 — $META1 components but $LAYOUT1 layout items"; exit 1; }
[ "$META2" = "$LAYOUT2" ] || { echo "ERROR: Dashboard 2 — $META2 components but $LAYOUT2 layout items"; exit 1; }

echo "✓ DB structure verified — $META1 components, $LAYOUT1 layout items in both dashboards"
