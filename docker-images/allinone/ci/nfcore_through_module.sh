#!/usr/bin/env bash
# CI helper for .github/workflows/build-images.yaml: an nf-core run through the
# depictio/ingest module (artifact mode) in the all-in-one image, then a reopen
# of the artifact with the image's own `serve`. Run from an empty directory.
#
#   nfcore_through_module.sh pipeline <name> <version>
#       nextflow run nf-core/<name> -r <version> -profile test,docker
#       -> nfcore-results/ and its samplesheet nfcore-samplesheet.<ext>, read
#          from the run's own params.json (`input`), as a pipeline would hand it
#   nfcore_through_module.sh module <docker|apptainer> <image> <expected template id>
#       the module on nfcore-results/ -> module-results/depictio/run_depictio
#   nfcore_through_module.sh reopen <docker|apptainer> <image>
#       serve the artifact, check every dashboard the ingestion created is there
set -euo pipefail

FIXTURES="$(cd "$(dirname "$0")" && pwd)"
API=http://127.0.0.1:8058/depictio/api/v1
RESULT=module-results/depictio/run.depictio.json
ARTIFACT=module-results/depictio/run_depictio

fail() { echo "::error::$*"; exit 1; }

pipeline() {
    local name=$1 version=$2
    # Older pipelines predate Nextflow's strict syntax.
    NXF_SYNTAX_PARSER=v1 nextflow run "nf-core/$name" -r "$version" -profile test,docker \
        --outdir "$PWD/nfcore-results" -work-dir "$PWD/nfcore-work"
    # The pipeline's work directory is GBs the rest of the job does not need.
    rm -rf nfcore-work
    local params input ext
    # The newest, should the directory hold an earlier attempt's too.
    params=$(find nfcore-results/pipeline_info -maxdepth 1 -name 'params_*.json' 2>/dev/null \
        | sort | tail -1) || true
    [ -n "$params" ] || fail "nf-core/$name wrote no pipeline_info/params_*.json"
    input=$(jq -r '.input // empty' "$params")
    [ -n "$input" ] || fail "no input in $params"
    ext=${input##*.}
    case "$ext" in csv|tsv) ;; *) ext=csv ;; esac
    case "$input" in
        http://*|https://*) curl -fsSL -o "nfcore-samplesheet.$ext" "$input" ;;
        *) cp "$input" "nfcore-samplesheet.$ext" ;;
    esac
    du -sh nfcore-results
}

module() {
    local engine=$1 image=$2 expected=$3 sheet
    sheet=$(find . -maxdepth 1 -name 'nfcore-samplesheet.*' | head -1)
    nextflow run "$FIXTURES/module_nfcore.nf" -profile "$engine" \
        --results "$PWD/nfcore-results" --samplesheet "$PWD/$sheet" \
        --outdir "$PWD/module-results" --image "$image" -work-dir "$PWD/module-work" \
        || { tail -80 module-work/*/*/.command.log 2>/dev/null; fail "the module failed"; }
    jq . "$RESULT"
    [ "$(jq -r .status "$RESULT")" = success ] || fail "ingestion status $(jq -r .status "$RESULT")"
    local template
    template=$(jq -r .template_id "$RESULT")
    [ "$template" = "$expected" ] || fail "template $template, expected $expected"
    [ "$(jq '.dashboards | length' "$RESULT")" -ge 1 ] || fail "the template's dashboards were not created"
    test -f "$ARTIFACT/.depictio-local-home" || fail "no artifact"
    [ ! -e "$ARTIFACT/env" ] || fail "the artifact holds downloaded services (env/)"
    if grep -l "from conda-forge" module-work/*/*/.command.log; then
        fail "the task downloaded the services"
    fi
    if find module-work ! -user "$(id -u)" | grep -q .; then
        find module-work ! -user "$(id -u)" | head
        fail "the task wrote files as another user"
    fi
    du -sh "$ARTIFACT"
}

reopen() {
    local engine=$1 image=$2 pid=""
    local art="$PWD/$ARTIFACT"
    if [ "$engine" = docker ]; then
        docker run -d --name reopen -u "$(id -u):$(id -g)" -p 127.0.0.1:8058:8058 \
            -e DEPICTIO_TELEMETRY_ENABLED=false -v "$art:/data" "$image"
    else
        # As the docs say: an isolated /tmp and HOME, the artifact on /data.
        apptainer run --containall --bind "$art:/data" \
            --env DEPICTIO_PORT=8058 --env DEPICTIO_TELEMETRY_ENABLED=false \
            "$image" > reopen.log 2>&1 &
        pid=$!
    fi
    local up=""
    for _ in $(seq 1 120); do
        if curl -fsS -o /dev/null http://127.0.0.1:8058/health 2>/dev/null; then up=1; break; fi
        sleep 5
    done
    if [ -z "$up" ]; then
        if [ "$engine" = docker ]; then docker logs reopen || true; else cat reopen.log || true; fi
        fail "the artifact never served"
    fi
    local token listed
    token=$(sed -n 's/^ *access_token: *//p' "$art/cli/admin_config.yaml" | head -1 | tr -d "\"'")
    listed=$(curl -fsS -H "Authorization: Bearer $token" "$API/dashboards/list")
    echo "reopened dashboards: $(jq -c '[.[] | .title]' <<< "$listed")"
    local id
    for id in $(jq -r '.dashboards[].id' "$RESULT"); do
        jq -e --arg id "$id" 'any(.[]; (.dashboard_id // .id // ._id) == $id)' <<< "$listed" >/dev/null \
            || fail "dashboard $id missing after the reopen"
    done
    curl -fsS -o /dev/null -w "dashboards page: %{http_code}\n" http://127.0.0.1:8058/dashboards
    if [ "$engine" = docker ]; then
        docker stop -t 60 reopen
        [ "$(docker inspect --format '{{.State.ExitCode}}' reopen)" = 0 ] || fail "unclean stop"
        docker logs reopen | tail -20
        docker rm reopen
    else
        kill -TERM "$pid"
        local code=0
        wait "$pid" || code=$?
        tail -20 reopen.log
        [ "$code" = 0 ] || fail "unclean stop (exit $code)"
    fi
    [ ! -s "$art/mongo/mongod.lock" ] || fail "mongod left its lock behind"
}

"$@"
