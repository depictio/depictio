// Runs the depictio/ingest module, artifact mode, on the results of a finished
// nf-core run, as docs/nextflow-module.md shows for an nf-core pipeline: the
// results directory, plus the samplesheet at input/samplesheet.csv, template
// detected from pipeline_info/. For the allinone-nfcore-rnaseq job in
// .github/workflows/build-images.yaml:
//   nextflow run module_nfcore.nf -profile docker --results <outdir> --samplesheet <csv>
include { DEPICTIO_INGEST } from '../../../depictio/cli/configs/nextflow/modules/depictio/ingest/main'

workflow {
    DEPICTIO_INGEST(
        channel.of([
            [id: 'run'],
            [file(params.results, type: 'dir', checkIfExists: true), file(params.samplesheet, checkIfExists: true)],
            ['.', 'input/samplesheet.csv'],
        ]),
        '',
        [],
        [],
        [],
    )
}
