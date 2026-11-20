// Runs the depictio/ingest module on the iris table, for the all-in-one image
// checks in .github/workflows/build-images.yaml:
//   nextflow run module_iris.nf -profile docker --iris <csv> --outdir <dir>
//       the default (artifact) mode
//   nextflow run module_iris.nf -profile docker,hostnet --iris <csv> --cli_config <CLI.yaml>
//       sent to an instance that is already running, no artifact
// (profiles and publishing in nextflow.config, next to it)
include { DEPICTIO_INGEST } from '../../../depictio/cli/configs/nextflow/modules/depictio/ingest/main'

workflow {
    DEPICTIO_INGEST(
        channel.of([ [id: 'iris'], file(params.iris, checkIfExists: true), [] ]),
        '',
        file("${projectDir}/iris_project.yaml", checkIfExists: true),
        [],
        params.cli_config ? file(params.cli_config, checkIfExists: true) : [],
    )
}
