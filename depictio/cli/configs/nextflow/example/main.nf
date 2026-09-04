#!/usr/bin/env nextflow

/*
 * Pipeline used to demonstrate the Depictio onComplete trigger.
 *
 * It fabricates the two output shapes a real QC pipeline produces, so the
 * bundled dashboard can show what Depictio actually does with them:
 *
 *   qc/measurements.tsv          per-sample metrics (a read-attrition funnel,
 *                                a quality score, a pass/warn/fail verdict)
 *   coverage/genome_coverage.bed windowed depth in mosdepth's column layout,
 *                                which a catalog recipe reshapes into a
 *                                coverage track
 *
 * No bioinformatics tool is involved and none of the numbers mean anything.
 * They are shaped, not simulated: the point is the ingestion path, not the
 * biology.
 */

process MEASURE {

    tag "${sample}"

    input:
    tuple val(sample), val(group), val(seed)

    output:
    path "${sample}.metrics.tsv"

    script:
    """
    awk -v s='${sample}' -v g='${group}' -v seed=${seed} 'BEGIN {
        total = 400000 + seed * 12345
        mapped = int(total * (0.72 + (seed % 7) / 40.0))
        dedup  = int(mapped * (0.80 + (seed % 5) / 50.0))
        qual   = 24.0 + (seed % 11)
        value  = dedup / 1000.0
        status = (qual < 27 ? "fail" : (qual < 30 ? "warn" : "pass"))
        printf "%s\\t%s\\t%d\\t%d\\t%d\\t%.1f\\t%.2f\\t%s\\n", s, g, total, mapped, dedup, qual, value, status
    }' > '${sample}.metrics.tsv'
    """
}

process COVERAGE {

    tag "${sample}"

    input:
    tuple val(sample), val(group), val(seed)

    output:
    path "${sample}.coverage.bed"

    script:
    """
    awk -v s='${sample}' -v seed=${seed} 'BEGIN {
        for (i = 0; i < 60; i++) {
            start = i * 200
            depth = 40 + seed * 3 + 25 * sin(i / 6.0) + (i % 5)
            if (i > 40 && i < 47) depth = depth / 4        # a dropout, so the track has something to show
            printf "chr_demo\\t%d\\t%d\\t%.1f\\t%s\\n", start, start + 200, depth, s
        }
    }' > '${sample}.coverage.bed'
    """
}

process MERGE_METRICS {

    publishDir "${params.outdir}/qc", mode: 'copy'

    input:
    path parts

    output:
    path 'measurements.tsv'

    script:
    """
    printf 'sample\\tgroup\\treads_total\\treads_mapped\\treads_dedup\\tmean_quality\\tvalue\\tstatus\\n' > measurements.tsv
    cat ${parts} | sort >> measurements.tsv
    """
}

process MERGE_COVERAGE {

    publishDir "${params.outdir}/coverage", mode: 'copy'

    input:
    path parts

    output:
    path 'genome_coverage.bed'

    script:
    """
    printf 'chrom\\tstart\\tend\\tcoverage\\tsample\\n' > genome_coverage.bed
    cat ${parts} | sort -k5,5 -k2,2n >> genome_coverage.bed
    """
}

workflow {

    samples = Channel.of(
        ['sample_A', 'control', 1],
        ['sample_B', 'control', 2],
        ['sample_C', 'control', 3],
        ['sample_D', 'treated', 4],
        ['sample_E', 'treated', 5],
        ['sample_F', 'treated', 6],
        ['sample_G', 'treated', 7],
        ['sample_H', 'control', 8]
    )

    MEASURE(samples)
    COVERAGE(samples)

    MERGE_METRICS(MEASURE.out.collect())
    MERGE_COVERAGE(COVERAGE.out.collect())
}
