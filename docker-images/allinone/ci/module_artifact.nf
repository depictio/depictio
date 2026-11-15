// Runs the depictio/ingest module in its default (artifact) mode on the iris
// table, for the all-in-one image check in .github/workflows/build-images.yaml:
//   nextflow run module_artifact.nf -profile docker --iris <csv> --outdir <dir>
// (profiles and publishing in nextflow.config, next to it)
include { DEPICTIO_INGEST } from '../../../depictio/cli/configs/nextflow/modules/depictio/ingest/main'

workflow {
    DEPICTIO_INGEST(
        channel.of([ [id: 'iris'], file(params.iris, checkIfExists: true), [] ]),
        '',
        file("${projectDir}/iris_project.yaml", checkIfExists: true),
        [],
        [],
    )
}
