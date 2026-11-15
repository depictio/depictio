// Runs the depictio/ingest module in its send-to-an-instance mode (cli_config):
// the iris table into an instance that is already running, no artifact. For
// allinone-image-check in .github/workflows/build-images.yaml:
//   nextflow run module_cli_config.nf -profile docker,hostnet --iris <csv> --cli_config <CLI.yaml>
include { DEPICTIO_INGEST } from '../../../depictio/cli/configs/nextflow/modules/depictio/ingest/main'

workflow {
    DEPICTIO_INGEST(
        channel.of([ [id: 'iris'], file(params.iris, checkIfExists: true), [] ]),
        '',
        file("${projectDir}/iris_project.yaml", checkIfExists: true),
        [],
        file(params.cli_config, checkIfExists: true),
    )
}
