#!/usr/bin/env nextflow

// Minimal demo pipeline used to exercise the Depictio trigger (depictio.config)
// without depending on a real nf-core pipeline. It writes a tiny TSV table into
// the publish directory, which the generic depictio_project.yaml then ingests.

nextflow.enable.dsl = 2

process WRITE_TABLE {
    publishDir "${params.outdir}", mode: 'copy'

    output:
    path 'measurements.tsv'

    script:
    """
    printf 'sample\\tcondition\\tvalue\\n' > measurements.tsv
    printf 'A\\tctrl\\t1.2\\n'            >> measurements.tsv
    printf 'B\\tctrl\\t0.9\\n'            >> measurements.tsv
    printf 'C\\ttreated\\t2.4\\n'         >> measurements.tsv
    """
}

workflow {
    WRITE_TABLE()
}
