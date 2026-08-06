#!/usr/bin/env bash
# Populate the viralrecon .db_seeds/ dashboards by running a local depictio
# CLI ingest, then exporting the resulting Mongo dashboard documents.
#
# Inputs:
#   $1: path to a viralrecon test-data run (containing multiqc/, variants/,
#       fastqc/, fastp/, kraken2/, pipeline_info/). Defaults to
#       ~/Data/viralrecon/viralrecon-testdata.
#
# Prerequisites:
#   - Local depictio stack running (API + MongoDB) via docker compose.
#   - depictio CLI venv (or `python -m depictio.cli`) available with the
#     admin token in ~/.depictio/CLI_config.yaml.
#   - Test data generated with depictio/projects/nf-core/viralrecon/3.0.0/
#     download_test_data.sh (only needed once).
#
# Output:
#   - depictio/projects/nf-core/viralrecon/3.0.0/.db_seeds/dashboard_*.json
#     for the 5 viralrecon dashboards (multiqc + coverage_depth +
#     lineage_clustering + variants + sample_qc).
set -euo pipefail

DATA_ROOT="${1:-${HOME}/Data/viralrecon/viralrecon-testdata}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SEEDS_DIR="${SCRIPT_DIR}/.db_seeds"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../.." && pwd)"

if [ ! -d "$DATA_ROOT" ]; then
    echo "ERROR: viralrecon test-data not found at $DATA_ROOT" >&2
    echo "Generate it via: $SCRIPT_DIR/download_test_data.sh $DATA_ROOT" >&2
    exit 1
fi

mkdir -p "$SEEDS_DIR"

# 1. Run the depictio CLI ingest against the template (must be invoked via
#    `python -m depictio.cli` so the rich-display / polars monkey-patch is
#    applied; see CLAUDE.md note on cli_rich_info_monkeypatch).
cd "$REPO_ROOT"
python -m depictio.cli run \
    --template "nf-core/viralrecon/3.0.0" \
    --data-root "$DATA_ROOT"

# 2. Export the 5 viralrecon dashboards from Mongo into .db_seeds/. The
#    dashboard_ids below come from db_init_reference_datasets.STATIC_IDS
#    and ``dashboards/base.yaml``.
#    Project id: 746b0f3c1e4a2d7f8e5b9ca2

declare -A DASH_FILES=(
    ["746b0f3c1e4a2d7f8e5b9ca2"]="dashboard_multiqc.json"
    ["746b0f3c1e4a2d7f8e5b9cb5"]="dashboard_coverage_depth.json"
    ["746b0f3c1e4a2d7f8e5b9cb3"]="dashboard_lineage_clustering.json"
    ["746b0f3c1e4a2d7f8e5b9cb4"]="dashboard_variants.json"
    ["746b0f3c1e4a2d7f8e5b9cc2"]="dashboard_sample_qc.json"
)

MONGO_URL="${DEPICTIO_MONGODB_URL:-mongodb://localhost:27018/depictioDB}"

for dashboard_id in "${!DASH_FILES[@]}"; do
    out_file="${SEEDS_DIR}/${DASH_FILES[$dashboard_id]}"
    # Dump to a temp file alongside the seed and move it into place only once
    # mongosh exits 0. Writing straight to "$out_file" meant a failed lookup
    # printed its error message INTO the committed seed (print() goes to
    # stdout, which the redirect captured), truncating it to one line of error
    # text before `set -e` could fire — the seed was already destroyed.
    tmp_file="$(mktemp "${out_file}.XXXXXX")"
    echo "Exporting $dashboard_id → $out_file"
    if ! mongosh --quiet "$MONGO_URL" --eval "
        // Collection is 'dashboards'. An earlier revision queried
        // 'dashboards_collection' (the Python variable name, not the Mongo
        // collection name), so every lookup returned null.
        const doc = db.dashboards.findOne({_id: ObjectId('${dashboard_id}')});
        if (!doc) {
            print('ERROR: dashboard ${dashboard_id} not found in Mongo');
            quit(1);
        }
        // EJSON.stringify, not printjson: printjson emits mongosh *shell*
        // syntax (unquoted keys, ObjectId('…')), which is not valid JSON and
        // is unreadable by db_init.py and remap_seeds_to_static_ids.py. Relaxed
        // EJSON with indent 2 is the committed seed format.
        print(EJSON.stringify(doc, null, 2, {relaxed: true}));
    " > "$tmp_file"; then
        rm -f "$tmp_file"
        echo "ERROR: export of $dashboard_id failed; $out_file left untouched" >&2
        exit 1
    fi
    # mktemp creates 0600 and mv preserves it; the seeds are committed files.
    chmod 644 "$tmp_file"
    mv "$tmp_file" "$out_file"
done

# 3. Add the new seeds to depictio/api/v1/db_init.py dashboards_config so the
#    next fresh boot auto-loads them. (Currently a manual edit — see plan.)
echo ""
echo "Seeds exported to $SEEDS_DIR"
echo "Next step: add the new dashboard entries to dashboards_config in"
echo "  depictio/api/v1/db_init.py (mirror the ampliseq pattern)."
