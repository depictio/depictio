#!/usr/bin/env nextflow

/*
 * Minimal pipeline used to demonstrate the Depictio onComplete trigger.
 *
 * It produces one file, `measurements.tsv`, in params.outdir. That is all the
 * bundled depictio_project.yaml expects to find.
 */

process MEASURE {

    tag "${sample}"

    input:
    tuple val(sample), val(value)

    output:
    path "${sample}.tsv"

    script:
    """
    printf '%s\\t%s\\n' '${sample}' '${value}' > '${sample}.tsv'
    """
}

process MERGE {

    publishDir params.outdir, mode: 'copy'

    input:
    path parts

    output:
    path 'measurements.tsv'

    script:
    """
    printf 'sample\\tvalue\\n' > measurements.tsv
    cat ${parts} | sort >> measurements.tsv
    """
}

workflow {

    samples = Channel.of(
        ['sample_A', 12.4],
        ['sample_B', 9.8],
        ['sample_C', 15.1],
        ['sample_D', 11.2]
    )

    MEASURE(samples)
    MERGE(MEASURE.out.collect())
}
