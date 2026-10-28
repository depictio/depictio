process DEPICTIO_INGEST {
    tag "${meta.id}"
    label 'process_single'

    conda "${moduleDir}/environment.yml"
    container "ghcr.io/depictio/depictio-cli:1.19.2"
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
    // Empty: derived from the pipeline's manifest, unless `project_config` is given.
    val template
    // Optional project YAML, for a pipeline Depictio ships no template for.
    path project_config
    // Optional dashboard YAMLs to import with the project.
    path dashboards
    // Optional CLI configuration (CLI.yaml). Without it the CLI reads
    // DEPICTIO_CLI_TOKEN / DEPICTIO_CLI_API_BASE_URL, or ~/.depictio/CLI.yaml.
    path cli_config

    output:
    tuple val(meta), path("${prefix}.depictio.json"), emit: result
    path "versions.yml"                              , emit: versions

    when:
    task.ext.when == null || task.ext.when

    script:
    def args = task.ext.args ?: ''
    prefix = task.ext.prefix ?: "${meta.id}"
    def inputs = files instanceof List ? files : [files]
    def rels = relpaths ? (relpaths instanceof List ? relpaths : [relpaths]) : []
    if (rels && rels.size() != inputs.size()) {
        error "DEPICTIO_INGEST: ${inputs.size()} files but ${rels.size()} relpaths, they must pair up one to one"
    }
    if (!rels) {
        // One directory is the data root itself; anything else is laid out flat.
        rels = inputs.size() == 1 ? ['.'] : inputs.collect { f -> f.name }
    }
    def layout = [inputs, rels].transpose().collect { f, r -> "stage_into '${f}' '${r}'" }.join('\n    ')

    def project_args = ''
    if (project_config) {
        project_args = "--project-config-path ${project_config}"
    } else if (template) {
        project_args = "--template ${template}"
    } else if (workflow.manifest.name) {
        project_args = "--pipeline-id ${workflow.manifest.name}/${workflow.manifest.version ?: 'latest'}"
    }
    def dashboard_list = dashboards instanceof List ? dashboards : (dashboards ? [dashboards] : [])
    def dashboard_args = dashboard_list.collect { d -> "--dashboard ${d}" }.join(' ')
    def server_args = cli_config ? "--server ${cli_config}" : ''
    """
    # Rebuild the published layout the template's scan patterns expect. The
    # scan does not descend into symlinked directories, so directories are
    # recreated for real with their files linked, never linked whole.
    stage_into() {
        local src dst
        src=\$(readlink -f "\$1")
        dst="data_root/\$2"
        if [ -d "\$src" ]; then
            mkdir -p "\$dst"
            cp -rs "\$src/." "\$dst/"
        else
            mkdir -p "\$(dirname "\$dst")"
            ln -s "\$src" "\$dst"
        fi
    }
    mkdir -p data_root
    ${layout}

    export DEPICTIO_DATA_ROOT="\$PWD/data_root"
    depictio \\
        ingest "\$PWD/data_root" \\
        ${project_args} \\
        ${dashboard_args} \\
        ${server_args} \\
        --triggered-by nextflow \\
        --result-json ${prefix}.depictio.json \\
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
