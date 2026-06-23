#!/usr/bin/env bash
# Populate the variantbenchmarking .db_seeds/ dashboards by running a local depictio
# CLI ingest, then exporting the resulting Mongo dashboard documents.
#
# Inputs:
#   $1: path to a variantbenchmarking test-data run (containing small/, indel/).
#       Defaults to ~/Data/variantbenchmarking/variantbenchmarking-testdata.
#
# Prerequisites:
#   - Local depictio stack running (API + MongoDB) via docker compose.
#   - depictio CLI venv (or `python -m depictio.cli`) available with the
#     admin token in ~/.depictio/CLI_config.yaml.
#   - Test data generated with download_test_data.sh (only needed once).
#
# Output:
#   - depictio/projects/nf-core/variantbenchmarking/1.4.0/.db_seeds/dashboard_*.json
#     for the 4 variantbenchmarking dashboards (overview + germline + somatic + sv_cnv).
set -euo pipefail

DATA_ROOT="${1:-${HOME}/Data/variantbenchmarking/variantbenchmarking-testdata}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SEEDS_DIR="${SCRIPT_DIR}/.db_seeds"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../.." && pwd)"

if [ ! -d "$DATA_ROOT" ]; then
    echo "ERROR: variantbenchmarking test-data not found at $DATA_ROOT" >&2
    echo "Generate it via: $SCRIPT_DIR/download_test_data.sh $DATA_ROOT" >&2
    exit 1
fi

mkdir -p "$SEEDS_DIR"

# 1. Run the depictio CLI ingest against the template (must be invoked via
#    `python -m depictio.cli` so the rich-display / polars monkey-patch is applied).
cd "$REPO_ROOT"
python -m depictio.cli run \
    --template "nf-core/variantbenchmarking/1.4.0" \
    --data-root "$DATA_ROOT"

# 2. Export the 4 variantbenchmarking dashboards from Mongo into .db_seeds/. The
#    dashboard_ids below come from db_init_reference_datasets.STATIC_IDS
#    and ``dashboards/base.yaml``.
declare -A DASH_FILES=(
    ["846b0f3c1e4a2d7f8e5bba01"]="dashboard_overview.json"
    ["846b0f3c1e4a2d7f8e5bba20"]="dashboard_germline.json"
    ["846b0f3c1e4a2d7f8e5bba21"]="dashboard_somatic.json"
    ["846b0f3c1e4a2d7f8e5bba22"]="dashboard_sv_cnv.json"
)

MONGO_URL="${DEPICTIO_MONGODB_URL:-mongodb://localhost:27018/depictioDB}"

for dashboard_id in "${!DASH_FILES[@]}"; do
    out_file="${SEEDS_DIR}/${DASH_FILES[$dashboard_id]}"
    echo "Exporting $dashboard_id → $out_file"
    mongosh --quiet "$MONGO_URL" --eval "
        const doc = db.dashboards_collection.findOne({_id: ObjectId('${dashboard_id}')});
        if (!doc) {
            print('ERROR: dashboard ${dashboard_id} not found in Mongo');
            quit(1);
        }
        printjson(doc);
    " > "$out_file"
done

# 3. Activate the seeds on fresh boot (currently a manual relay step — see
#    VALIDATION_REPORT.md "Relay / activation" for the exact db_init.py snippet):
#      - add "variantbenchmarking" to all_datasets in db_init_reference_datasets.py
#      - add the 4 dashboard entries to dashboards_config in db_init.py
#      - add a "variantbenchmarking" prefix branch to _dataset_of_dashboard in db_init.py
echo ""
echo "Seeds exported to $SEEDS_DIR"
echo "Next step: see VALIDATION_REPORT.md 'Relay / activation' to wire the seeds into db_init."
