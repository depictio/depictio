// A finished nf-core run published through the depictio/publish subworkflow
// (the depictio/ingest module in artifact mode), as docs/nextflow-module.md
// shows for a pipeline: the results directory and the run's samplesheet, the
// template detected from pipeline_info/ and its routes from params.json. For
// the nf-core jobs of .github/workflows/build-images.yaml:
//   nextflow run module_nfcore.nf -profile docker --results <outdir> --samplesheet <file> --depictio_id run
include { DEPICTIO_PUBLISH } from '../../../depictio/cli/configs/nextflow/subworkflows/depictio/publish/main'

workflow {
    DEPICTIO_PUBLISH(channel.of('done'), params.results, params.samplesheet)
}
