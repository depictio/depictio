#!/usr/bin/env bash
# Populate the viralrecon .db_seeds/ dashboards by running a local depictio
# CLI ingest, then exporting the resulting Mongo dashboard documents.
#
# Inputs:
#   $1: path to a viralrecon test-data run (containing multiqc/, variants/,
#       fastqc/, fastp/, kraken2/, pipeline_info/). Defaults to
#       ~/Data/viralrecon/viralrecon-testdata.
#
#       In practice pass THIS DIRECTORY: run_1/ here carries the committed
#       multiqc parquet, variants/ and pipeline_info/ that the reference seeds
#       bind to:
#         bash generate_seeds.sh "$(dirname "$0")"
#
# Prerequisites:
#   - Local depictio stack running (API + MongoDB) via docker compose.
#   - depictio CLI venv (or `python -m depictio.cli`) available, with a CLI
#     config carrying an admin token for that stack. Defaults to
#     ~/.depictio/CLI.yaml; override with DEPICTIO_CLI_CONFIG.
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
# The CLI's own default. Point DEPICTIO_CLI_CONFIG at an instance-specific
# config to target a worktree stack, or the ingest below lands in whatever
# stack ~/.depictio/CLI.yaml happens to name.
CLI_CONFIG="${DEPICTIO_CLI_CONFIG:-${HOME}/.depictio/CLI.yaml}"

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
# `--overwrite` is required on any re-run: without it the dashboard import
# hits `_import_multi_tab_dashboard`'s existing-family guard and returns 409.
python -m depictio.cli run \
    --CLI-config-path "$CLI_CONFIG" \
    --template "nf-core/viralrecon/3.0.0" \
    --data-root "$DATA_ROOT" \
    --update-config \
    --overwrite

# 2. Export the 5 viralrecon dashboards from Mongo into .db_seeds/. The
#    dashboard_ids below come from db_init_reference_datasets.STATIC_IDS
#    and ``dashboards/base.yaml``.
PROJECT_ID="746b0f3c1e4a2d7f8e5b9ca2"

# Keyed by TAB TITLE, not by dashboard id: `_import_multi_tab_dashboard` mints a
# fresh ObjectId for any tab it does not already find by title, so an id-keyed
# export silently misses every newly added tab. `remap_seeds_to_static_ids.py`
# below is what pins the ids back afterwards.
#
# A tab-separated list rather than an associative array: `declare -A` needs bash
# 4, and macOS still ships 3.2 as /bin/bash, where it parses as an indexed array
# and the first title's leading word explodes as an unbound variable.
DASH_FILES="
nf-core/viralrecon	dashboard_multiqc.json
Coverage & Depth	dashboard_coverage_depth.json
Lineage & Clustering	dashboard_lineage_clustering.json
Variants	dashboard_variants.json
Sample QC	dashboard_sample_qc.json
"

# Resolve the Mongo URL. Precedence: an explicit DEPICTIO_MONGODB_URL, then the
# host port declared by the instance's env file (a worktree stack does not run
# on the default 27018), then the compose default. `db.dashboards` is the real
# collection name — `settings_models.py` declares
# `dashboards_collection: str = Field(default="dashboards")`, and the previous
# `db.dashboards_collection` silently queried a collection that does not exist.
resolve_mongo_url() {
    if [ -n "${DEPICTIO_MONGODB_URL:-}" ]; then
        echo "$DEPICTIO_MONGODB_URL"
        return
    fi
    local port=""
    for env_file in "${REPO_ROOT}/.env.instance" "${REPO_ROOT}/.env" "${REPO_ROOT}/docker-compose/.env"; do
        if [ -f "$env_file" ]; then
            port=$(grep -E '^DEPICTIO_MONGODB_PORT=' "$env_file" | tail -1 | cut -d= -f2 | tr -d '"'"'"' ')
            [ -n "$port" ] && break
        fi
    done
    echo "mongodb://localhost:${port:-27018}/depictioDB"
}
MONGO_URL="$(resolve_mongo_url)"

printf '%s\n' "$DASH_FILES" | while IFS=$'\t' read -r title file; do
    [ -n "$title" ] || continue
    out_file="${SEEDS_DIR}/${file}"
    # JSON-quote the title so `&`, quotes and non-ASCII survive into the JS.
    title_json=$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$title")
    echo "Exporting ${title} → $out_file"
    mongosh --quiet "$MONGO_URL" --eval "
        const doc = db.dashboards.findOne({
            project_id: ObjectId('${PROJECT_ID}'),
            title: ${title_json},
        });
        if (!doc) {
            print('ERROR: dashboard ${title_json} not found in Mongo');
            quit(1);
        }
        // EJSON, not printjson: printjson emits a JS object literal with
        // unquoted keys and ObjectId(...) calls, which no JSON parser reads —
        // including the remap step three lines below.
        print(EJSON.stringify(doc, null, 2));
    " > "$out_file"
    if grep -q '^ERROR:' "$out_file"; then
        cat "$out_file" >&2
        rm -f "$out_file"
        exit 1
    fi
done

# 3. Remap the freshly-exported DC and dashboard ids (auto-generated by the
#    ingest) back to the static reference ids, or the seeds 404 on a fresh
#    deploy. Not optional — the import does not honour the YAML's ids.
echo ""
echo "Remapping ids to static reference ids…"
python "$SCRIPT_DIR/remap_seeds_to_static_ids.py"

echo ""
echo "Seeds exported + remapped in $SEEDS_DIR"
echo "The 5 viralrecon dashboards are already registered in"
echo "  depictio/api/v1/db_init.py (dashboards_config) — no further wiring needed."
