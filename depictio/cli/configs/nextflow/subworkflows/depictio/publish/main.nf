//
// Publish a finished run to Depictio: the whole results directory, plus the
// run's samplesheet, through the depictio/ingest module. The template is
// detected from the run's pipeline_info/ and its route variables from the
// run's own params.json (each template's `from_params` rules), so nothing here
// is specific to a pipeline. Every setting is an input, as nf-core asks of a
// subworkflow; the pipeline passes its params.depictio_* (see meta.yml).
//
include { DEPICTIO_INGEST } from '../../../modules/depictio/ingest/main'

workflow DEPICTIO_PUBLISH {

    take:
    ch_done         // channel: anything, emitted once the run's outputs are published
                    //          (e.g. MultiQC's report); the ingestion waits for all of it
    outdir          // value:   the pipeline's results directory (params.outdir)
    samplesheet     // value:   the run's --input (path or URL), or null: nf-core does not
                    //          publish it, and the templates read it from input/
    template        // value:   a template id, or null to detect it from pipeline_info/
    project_config  // value:   a project YAML for a pipeline with no template, or null
    dashboards      // value:   dashboard YAML path(s) to import as well, or null
    cli_config      // value:   a CLI.yaml to send the run to that instance, or null for
                    //          an artifact

    main:
    def dashboard_files = dashboards
        ? (dashboards instanceof List ? dashboards : [dashboards]).collect { d -> file(d, checkIfExists: true) }
        : []

    ch_run = ch_done
        .collect()
        .map { _done ->
            def files = [file(outdir.toString(), type: 'dir', checkIfExists: true)]
            def relpaths = ['.']
            if (samplesheet) {
                def sheet = file(samplesheet.toString(), checkIfExists: true)
                def ext = sheet.extension in ['csv', 'tsv'] ? sheet.extension : 'csv'
                files << sheet
                relpaths << "input/samplesheet.${ext}".toString()
            }
            [[id: workflow.runName], files, relpaths]
        }

    DEPICTIO_INGEST(
        ch_run,
        template ?: '',
        project_config ? file(project_config, checkIfExists: true) : [],
        dashboard_files,
        cli_config ? file(cli_config, checkIfExists: true) : [],
    )

    emit:
    artifact = DEPICTIO_INGEST.out.artifact // channel: [ val(meta), path(<run>_depictio) ]
    result   = DEPICTIO_INGEST.out.result   // channel: [ val(meta), path(<run>.depictio.json) ]
    versions = DEPICTIO_INGEST.out.versions // channel: path(versions.yml)
}
