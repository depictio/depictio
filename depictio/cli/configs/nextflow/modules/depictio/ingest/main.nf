process DEPICTIO_INGEST {
    tag "${meta.id}"
    label 'process_single'

    conda "${moduleDir}/environment.yml"
    container "ghcr.io/depictio/depictio-cli:1.19.3"
    // The image's ENTRYPOINT is the CLI itself, so `docker run <image> /bin/bash
    // .command.run` would hand bash to the CLI as a subcommand. Singularity and
    // Apptainer `exec` ignore the entrypoint already.
    containerOptions "${workflow.containerEngine in ['docker', 'podman'] ? '--entrypoint ""' : ''}"

    input:
    // `files` is either the pipeline's results directory, or the files a
    // template reads. `relpaths` gives each file the path it is published
    // under, relative to the results directory (e.g. `multiqc/multiqc_data`).
    // Leave it empty to ingest one directory as is, or to lay files out flat.
    tuple val(meta), path(files, stageAs: 'staged/??/*'), val(relpaths)
    // A bundled template id (`nf-core/rnaseq/3.26.0`, `nf-core/rnaseq/latest`).
    // Empty: the CLI detects the pipeline from the run's pipeline_info/ and picks
    // the closest bundled version, unless `project_config` is given.
    val template
    // Optional project YAML, for a pipeline Depictio ships no template for.
    path project_config
    // Optional dashboard YAMLs to import with the project.
    path dashboards
    // [] (the default): build an artifact, a single-user depictio holding the
    // run, which the task starts, fills, stops and emits; nothing outlives it.
    // A CLI.yaml instead sends the run to that existing instance (not the default,
    // may change). DEPICTIO_CLI_TOKEN overrides the token of the file.
    path cli_config

    output:
    tuple val(meta), path("${prefix}_depictio"), emit: artifact, optional: true
    tuple val(meta), path("${prefix}.depictio.json"), emit: result
    path "versions.yml"                              , emit: versions

    when:
    task.ext.when == null || task.ext.when

    script:
    def args = task.ext.args ?: ''
    // Options of `depictio local up`, e.g. '--port 8123' for the API port.
    def args2 = task.ext.args2 ?: ''
    prefix = task.ext.prefix ?: "${meta.id}"
    // Single-quoted for the shell. Staged paths need none: Nextflow escapes them.
    def quote = { value -> "'" + value.toString().replace("'", "'\\''") + "'" }
    def inputs = files instanceof List ? files : [files]
    def rels = relpaths ? (relpaths instanceof List ? relpaths : [relpaths]) : []
    if (rels && rels.size() != inputs.size()) {
        error "DEPICTIO_INGEST: ${inputs.size()} files but ${rels.size()} relpaths, they must pair up one to one"
    }
    def outside = rels.find { r -> r.toString().startsWith('/') || r.toString().tokenize('/').contains('..') }
    if (outside != null) {
        error "DEPICTIO_INGEST: relpath '${outside}' leaves the results directory; give a path relative to it"
    }
    if (!rels) {
        // One directory is the data root itself; anything else is laid out flat.
        rels = inputs.size() == 1 ? ['.'] : inputs.collect { f -> f.name }
    }
    def layout = [inputs, rels].transpose().collect { f, r -> "stage_into ${f} ${quote.call(r)}" }.join('\n    ')

    def project_args = ''
    if (project_config) {
        project_args = "--project-config-path ${project_config}"
    } else if (template) {
        project_args = "--template ${quote.call(template)}"
    }
    def dashboard_list = dashboards instanceof List ? dashboards : (dashboards ? [dashboards] : [])
    def dashboard_args = dashboard_list.collect { d -> "--dashboard ${d}" }.join(' ')
    def artifact = !cli_config
    def server_args = artifact ? '--server local' : "--server ${cli_config}"
    def artifact_dir = quote.call("${prefix}_depictio")
    // The stack's home is in the work directory, so it never touches
    // ~/.depictio/local, and its ports are picked free, so it runs beside any other
    // stack. It is stopped on every exit, so nothing outlives the task.
    def start_stack = !artifact ? '' : """
    export DEPICTIO_LOCAL_HOME="\$PWD/stack"
    trap 'depictio local down >/dev/null 2>&1 || true' EXIT
    depictio local up --no-open --examples none ${args2}
    """
    // Stopped first, so MongoDB and SeaweedFS flush, then only what reopening the
    // artifact reads is kept: no binaries, logs, caches or Redis queue. The
    // preallocated journal file is 100 MB of nothing.
    def keep_stack = !artifact ? '' : """
    depictio local down
    trap - EXIT
    mkdir -p ${artifact_dir}
    for kept in .depictio-local-home secrets.json ports.json keys cli mongo s3; do
        mv "stack/\$kept" ${artifact_dir}/
    done
    rm -f ${artifact_dir}/mongo/journal/WiredTigerPreplog.*
    # The binaries and logs left are close to 1 GB; a failed task keeps them.
    rm -rf stack
    """
    def result_json = quote.call("${prefix}.depictio.json")
    """
    # Rebuild the published layout the template's scan patterns expect. The
    # scan does not descend into symlinked directories, so directories are
    # recreated for real with their files linked (-L also unfolds the symlinked
    # directories of a publishDir mode 'symlink' tree). Links point at the staged
    # path, which the container mounts, not at its resolved target. A later entry
    # wins over an earlier one at the same path.
    stage_into() {
        local src="\$PWD/\$1" dst="data_root/\$2"
        if [ ! -e "\$src" ]; then
            echo "DEPICTIO_INGEST: input '\$1' does not exist" >&2
            exit 1
        fi
        if [ -d "\$src" ]; then
            if [ -L "\$dst" ] || [ -f "\$dst" ]; then rm -f "\$dst"; fi
            mkdir -p "\$dst"
            cp -rsfL "\$src/." "\$dst/"
        else
            if [ "\$2" = . ]; then dst="data_root/\$(basename "\$1")"; fi
            rm -rf "\$dst"
            mkdir -p "\$(dirname "\$dst")"
            ln -s "\$src" "\$dst"
        fi
    }
    mkdir -p data_root
    ${layout}

    ${start_stack}
    # Expanded in a project YAML's locations ({DEPICTIO_DATA_ROOT}).
    export DEPICTIO_DATA_ROOT="\$PWD/data_root"
    depictio \\
        ingest "\$PWD/data_root" \\
        ${project_args} \\
        ${dashboard_args} \\
        ${server_args} \\
        --triggered-by nextflow \\
        --result-json ${result_json} \\
        ${args}
    ${keep_stack}

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        depictio: \$(depictio version | sed 's/.*version: //')
    END_VERSIONS
    """

    stub:
    prefix = task.ext.prefix ?: "${meta.id}"
    def stub_artifact = cli_config ? '' : "mkdir -p '${prefix}_depictio/mongo' '${prefix}_depictio/s3' && touch '${prefix}_depictio/.depictio-local-home'"
    """
    ${stub_artifact}
    echo '{"status": "stub"}' > ${prefix}.depictio.json

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        depictio: \$(depictio version | sed 's/.*version: //')
    END_VERSIONS
    """
}
