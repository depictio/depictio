//
// Publish a finished nf-core run to Depictio: the whole results directory, plus
// the run's samplesheet, through the depictio/ingest module. The template is
// detected from the run's pipeline_info/ and its route variables from the
// run's own params.json (each template's `from_params` rules), so nothing here
// is specific to a pipeline. Settings come from params.depictio_* (see
// nextflow.config next to this file).
//
include { DEPICTIO_INGEST } from '../../../modules/depictio/ingest/main'

workflow DEPICTIO_PUBLISH {

    take:
    ch_done      // channel: anything, emitted once the run's outputs are published
                 //          (e.g. MultiQC's report); the ingestion waits for all of it
    outdir       // value:   the pipeline's results directory (params.outdir)
    samplesheet  // value:   the run's --input (path or URL), or null: nf-core does not
                 //          publish it, and the templates read it from input/

    main:
    // The defaults are in nextflow.config, next to this file.
    def dashboards = params.depictio_dashboards
        ? (params.depictio_dashboards instanceof List ? params.depictio_dashboards : [params.depictio_dashboards])
            .collect { d -> file(d, checkIfExists: true) }
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
            [[id: params.depictio_id ?: workflow.runName], files, relpaths]
        }

    DEPICTIO_INGEST(
        ch_run,
        params.depictio_template ?: '',
        params.depictio_project_config ? file(params.depictio_project_config, checkIfExists: true) : [],
        dashboards,
        params.depictio_cli_config ? file(params.depictio_cli_config, checkIfExists: true) : [],
    )

    emit:
    artifact = DEPICTIO_INGEST.out.artifact // channel: [ val(meta), path(<id>_depictio) ]
    result   = DEPICTIO_INGEST.out.result   // channel: [ val(meta), path(<id>.depictio.json) ]
    versions = DEPICTIO_INGEST.out.versions // channel: path(versions.yml)
}
