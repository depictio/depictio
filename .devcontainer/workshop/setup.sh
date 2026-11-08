#!/usr/bin/env bash
# Prepares the workshop codespace: copies the nf-core/ampliseq 2.18.0 run below the
# home folder, where the web UI's "From a run folder" can read it, and ingests it
# once so that its dashboard is ready for the first exercise.
set -euo pipefail

RUN_DIR="$HOME/ampliseq_run"

cp -r depictio/projects/nf-core/ampliseq/2.18.0 "$RUN_DIR"

"$HOME/.local/bin/depictio" local up --no-open --port 8058
"$HOME/.local/bin/depictio" ingest "$RUN_DIR"
