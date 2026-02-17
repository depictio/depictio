#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WORKTREE="$(cd "$SCRIPT_DIR/.." && pwd)"
CLI="$WORKTREE/depictio/cli/.venv/bin/depictio-cli"
PYTHON="$WORKTREE/depictio/cli/.venv/bin/python"
CONFIG="$WORKTREE/depictio/.depictio/admin_config.yaml"
IRIS_ID="6824cb3b89d2b72169309737"
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

echo "=== Step 5: compare ==="
"$PYTHON" "$SCRIPT_DIR/roundtrip_compare.py" "$TMP/yaml1.yaml" "$TMP/yaml2.yaml"
