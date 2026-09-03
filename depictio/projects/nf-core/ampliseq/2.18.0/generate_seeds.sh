#!/usr/bin/env bash
# Populate the ampliseq .db_seeds/ dashboards by running a local depictio
# CLI ingest against the template, then exporting the resulting Mongo
# dashboard documents. Mirror of the viralrecon generate_seeds.sh.
#
# Inputs:
#   $1: path to an ampliseq 2.18.0 test-data run (containing input/,
#       multiqc/, qiime2/). Defaults to
#       ~/Data/ampliseq/ampliseq-2.18.0-testdata.
#
#       In practice pass THIS DIRECTORY: the committed input/samplesheet.csv,
#       multiqc/ parquet and qiime2/tree.nwk that the reference seeds bind to
#       live here, not in the download_test_data.sh output (which ships the
#       megatest Samplesheet_full.tsv under a different name and no tree):
#         bash generate_seeds.sh "$(dirname "$0")"
#
# Prerequisites:
#   - Local depictio stack running (API + MongoDB) via docker compose.
#   - depictio CLI venv (or `python -m depictio.cli`) available, with a CLI
#     config carrying an admin token for that stack. Defaults to
#     ~/.depictio/CLI.yaml; override with DEPICTIO_CLI_CONFIG.
#   - Test data generated with depictio/projects/nf-core/ampliseq/2.18.0/
#     download_test_data.sh (only needed once), and the canonical seed TSVs
#     materialised with generate_canonical_seeds.py.
#
# Output:
#   - depictio/projects/nf-core/ampliseq/2.18.0/.db_seeds/dashboard_*.json
#     for the 8 ampliseq dashboards (multiqc + alpha_diversity + community +
#     differential + ordination + phylogeny, from the nf-core template, plus
#     sampling_campaign + environment from the reference-only demo layer).
#
# The template YAML under dashboards/ is the SOURCE OF TRUTH: `use:` catalog
# bindings and `*_tag` references are resolved into viz_kind + oids during the
# `depictio run` import, and this script bakes that resolved form into the
# seeds. After exporting, run remap_seeds_to_static_ids.py so the DC ids match
# the static reference-init ids (otherwise tiles 404 on a fresh deploy).
set -euo pipefail

DATA_ROOT="${1:-${HOME}/Data/ampliseq/ampliseq-2.18.0-testdata}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SEEDS_DIR="${SCRIPT_DIR}/.db_seeds"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../.." && pwd)"
# The CLI's own default. Point DEPICTIO_CLI_CONFIG at an instance-specific
# config to target a worktree stack — both steps below read it, or step 1 would
# silently ingest into whatever stack ~/.depictio/CLI.yaml happens to name.
CLI_CONFIG="${DEPICTIO_CLI_CONFIG:-${HOME}/.depictio/CLI.yaml}"
API_URL="${DEPICTIO_API_URL:-http://localhost:8058}"

if [ ! -d "$DATA_ROOT" ]; then
    echo "ERROR: ampliseq test-data not found at $DATA_ROOT" >&2
    echo "Generate it via: $SCRIPT_DIR/download_test_data.sh $DATA_ROOT" >&2
    exit 1
fi

mkdir -p "$SEEDS_DIR"

# 1. Run the depictio CLI ingest against the template (must be invoked via
#    `python -m depictio.cli` so the rich-display / polars monkey-patch is
#    applied; see CLAUDE.md note on cli_rich_info_monkeypatch). METADATA_FILE
#    is what flips the template to the full 6-dashboard variant (the
#    `if_var_present: METADATA_FILE` conditional in template.yaml).
cd "$REPO_ROOT"
# `--overwrite` is required on any re-run: without it the dashboard import hits
# `_import_multi_tab_dashboard`'s existing-family guard and returns 409.
python -m depictio.cli run \
    --CLI-config-path "$CLI_CONFIG" \
    --template "nf-core/ampliseq/2.18.0" \
    --data-root "$DATA_ROOT" \
    --var SAMPLESHEET_FILE="$DATA_ROOT/input/samplesheet.csv" \
    --var METADATA_FILE="$DATA_ROOT/input/Metadata_full.tsv" \
    --update-config \
    --overwrite

# 1b. Layer the reference-only demo dashboard on top of the family the template
#     just imported. `reference_extended.yaml` is generated from base.yaml by
#     build_reference_dashboard.py; it adds the sampling map, the date range,
#     the CTD filters and the two demo tabs, all of which bind columns only this
#     dataset's metadata carries. It is imported here rather than listed in
#     `template.dashboards`, so `depictio run --template nf-core/ampliseq/2.18.0`
#     against a real run still only ever gets base.yaml.
#
#     Regenerating it first is what keeps it from drifting away from base.yaml;
#     test_ampliseq_reference_dashboard.py fails when this step is skipped.
python "$SCRIPT_DIR/build_reference_dashboard.py"
python -m depictio.cli dashboard import \
    "$SCRIPT_DIR/dashboards/reference_extended.yaml" \
    --config "$CLI_CONFIG" \
    --api "$API_URL" \
    --project "646b0f3c1e4a2d7f8e5b8ca2" \
    --overwrite

# 2. Export the 8 ampliseq dashboards from Mongo into .db_seeds/. The
#    dashboard_ids below come from db_init_reference_datasets.STATIC_IDS
#    ("ampliseq" → "dashboards") and the template's dashboards/ YAML.
PROJECT_ID="646b0f3c1e4a2d7f8e5b8ca2"

# Keyed by TAB TITLE, not by dashboard id: `_import_multi_tab_dashboard` mints a
# fresh ObjectId for any tab it does not already find by title, so an id-keyed
# export silently misses every newly added tab. `remap_seeds_to_static_ids.py`
# below is what pins the ids back afterwards.
#
# A tab-separated list rather than an associative array: `declare -A` needs bash
# 4, and macOS still ships 3.2 as /bin/bash, where it parses as an indexed array
# and the first title's leading word explodes as an unbound variable.
DASH_FILES="
nf-core/ampliseq	dashboard_multiqc.json
Alpha Diversity	dashboard_alpha_diversity.json
Community & Diversity	dashboard_community.json
Differential Abundance	dashboard_differential.json
Ordination & Clustering	dashboard_ordination.json
Phylogeny	dashboard_phylogeny.json
Sampling Campaign	dashboard_sampling_campaign.json
Environment (CTD)	dashboard_environment.json
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
            port=$(grep -E '^DEPICTIO_MONGODB_PORT=' "$env_file" | tail -1 | cut -d= -f2 | tr -d "\"' ")
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

# 3. Remap the freshly-exported DC ids (auto-generated by the ingest) back to
#    the static reference-init ids so the seeds render on a fresh deploy.
echo ""
echo "Remapping DC ids to static reference ids…"
python "$SCRIPT_DIR/remap_seeds_to_static_ids.py"

echo ""
echo "Seeds exported + remapped in $SEEDS_DIR"
echo "The 8 ampliseq dashboards are already registered in"
echo "  depictio/api/v1/db_init.py (dashboards_config) — no further wiring needed."
