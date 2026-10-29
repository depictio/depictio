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
    // CLI configuration (CLI.yaml), or [] for $DEPICTIO_CLI_CONFIG_PATH /
    // ~/.depictio/CLI.yaml. DEPICTIO_CLI_TOKEN and DEPICTIO_CLI_API_BASE_URL
    // override the token and URL of whichever file is read; they do not replace it.
    path cli_config

    output:
    tuple val(meta), path("${prefix}.depictio.json"), emit: result
    path "versions.yml"                              , emit: versions

    when:
    task.ext.when == null || task.ext.when

    script:
    def args = task.ext.args ?: ''
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
    def server_args = cli_config ? "--server ${cli_config}" : ''
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

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        depictio: \$(depictio version | sed 's/.*version: //')
    END_VERSIONS
    """

    stub:
    prefix = task.ext.prefix ?: "${meta.id}"
    """
    echo '{"status": "stub"}' > ${prefix}.depictio.json

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        depictio: \$(depictio version | sed 's/.*version: //')
    END_VERSIONS
    """
}
