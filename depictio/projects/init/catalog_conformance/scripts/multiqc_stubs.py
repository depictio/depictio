"""Parser-valid stub logs for every MultiQC section the catalog declares.

The catalog offers thirteen MultiQC outputs, twelve of which are a *section* of
one report (`bcftools`, `bowtie2`, ... — see `depictio/catalog/multiqc/*.yaml`).
Offering them at all requires a `multiqc.parquet`, and the only ones in the repo
belong to the two nf-core reference projects this conformance project exists to
be independent of — viralrecon's is also 24 MB.

So the report is synthesised: one small stub per module, in the exact shape
MultiQC's own search patterns key on (`multiqc/search_patterns.yaml`), written
into a temp dir that MultiQC is then run over. Nothing here tries to be
biologically meaningful; it has to parse, name a sample, and carry enough of a
metric for the module to produce a plot.

Each builder returns `{relative filename: contents}`. `STUB_BUILDERS` maps the
catalog's `section` value to its builder, so a new MultiQC output in the catalog
surfaces as a missing key rather than as a silently absent section.
"""

from __future__ import annotations

import json

# Deterministic per-sample numbers: this file is committed output, so a rerun
# must not produce a different parquet.
SAMPLES = ("CONF_A", "CONF_B", "CONF_C")


def _vary(sample: str, lo: int, hi: int) -> int:
    """A stable value in [lo, hi] derived from the sample name."""
    return lo + (sum(sample.encode()) % max(1, hi - lo + 1))


def fastqc(sample: str) -> dict[str, str]:
    total = _vary(sample, 90_000, 120_000)
    gc = _vary(sample, 40, 52)
    per_base = "\n".join(
        f"{pos}\t{34.5 - pos * 0.02:.1f}\t35.0\t33.0\t36.0\t32.0\t37.0" for pos in range(1, 51)
    )
    per_seq = "\n".join(f"{q}\t{max(0, 1000 - abs(q - 36) * 120)}" for q in range(20, 41))
    body = f"""##FastQC\t0.12.1
>>Basic Statistics\tpass
#Measure\tValue
Filename\t{sample}.fastq.gz
File type\tConventional base calls
Encoding\tSanger / Illumina 1.9
Total Sequences\t{total}
Sequences flagged as poor quality\t0
Sequence length\t50
%GC\t{gc}
>>END_MODULE
>>Per base sequence quality\tpass
#Base\tMean\tMedian\tLower Quartile\tUpper Quartile\t10th Percentile\t90th Percentile
{per_base}
>>END_MODULE
>>Per sequence quality scores\tpass
#Quality\tCount
{per_seq}
>>END_MODULE
"""
    return {f"{sample}_fastqc/fastqc_data.txt": body}


def cutadapt(sample: str) -> dict[str, str]:
    with_adapters = _vary(sample, 18_000, 30_000)
    lengths = "\n".join(
        f"{n}\t{max(1, 900 - n * 7)}\t312.5\t0\t{max(1, 900 - n * 7)}" for n in range(3, 40)
    )
    body = f"""This is cutadapt 4.6 with Python 3.12.9
Command line parameters: -a AGATCGGAAGAGC -o {sample}.trimmed.fastq.gz {sample}.fastq.gz
Processing single-end reads on 1 core ...
Finished in 1.000 s (10.000 us/read; 6.00 M reads/minute).

=== Summary ===

Total reads processed:                 100,000
Reads with adapters:                    {with_adapters:,} ({with_adapters / 1000:.1f}%)
Reads written (passing filters):       100,000 (100.0%)

Total basepairs processed:     5,000,000 bp
Total written (filtered):      4,700,000 bp (94.0%)

=== Adapter 1 ===

Sequence: AGATCGGAAGAGC; Type: regular 3'; Length: 13; Trimmed: {with_adapters} times

Overview of removed sequences
length\tcount\texpect\tmax.err\terror counts
{lengths}
"""
    return {f"{sample}_cutadapt.log": body}


def bowtie2(sample: str) -> dict[str, str]:
    total = _vary(sample, 90_000, 120_000)
    unpaired = int(total * 0.06)
    exactly_one = int(total * 0.78)
    multi = total - unpaired - exactly_one
    overall = 100.0 * (exactly_one + multi) / total
    body = f"""{total} reads; of these:
  {total} (100.00%) were paired; of these:
    {unpaired} ({100.0 * unpaired / total:.2f}%) aligned concordantly 0 times
    {exactly_one} ({100.0 * exactly_one / total:.2f}%) aligned concordantly exactly 1 time
    {multi} ({100.0 * multi / total:.2f}%) aligned concordantly >1 times
{overall:.2f}% overall alignment rate
"""
    return {f"{sample}.bowtie2.log": body}


def kraken(sample: str) -> dict[str, str]:
    unclassified = _vary(sample, 2, 9)
    root = 100 - unclassified
    body = f"""{unclassified:6.2f}\t{unclassified * 100}\t{unclassified * 100}\tU\t0\tunclassified
{root:6.2f}\t{root * 100}\t120\tR\t1\troot
 {root - 5:6.2f}\t{(root - 5) * 100}\t340\tD\t2\t  Bacteria
 {root - 20:6.2f}\t{(root - 20) * 100}\t210\tP\t1224\t    Pseudomonadota
 {root - 40:6.2f}\t{(root - 40) * 100}\t180\tG\t561\t      Escherichia
"""
    return {f"{sample}.kraken2.report.txt": body}


def bcftools(sample: str) -> dict[str, str]:
    snps = _vary(sample, 120, 260)
    indels = _vary(sample, 8, 30)
    body = f"""# This file was produced by bcftools stats (1.19+htslib-1.19) and can be plotted using plot-vcfstats.
# The command line was: bcftools stats {sample}.vcf.gz
#
# Definition of sets:
# ID\t[2]id\t[3]tab-separated file names
ID\t0\t{sample}.vcf.gz
# SN, Summary numbers:
SN\t0\tnumber of samples:\t1
SN\t0\tnumber of records:\t{snps + indels}
SN\t0\tnumber of SNPs:\t{snps}
SN\t0\tnumber of indels:\t{indels}
SN\t0\tnumber of MNPs:\t0
SN\t0\tnumber of others:\t0
SN\t0\tnumber of multiallelic sites:\t0
# TSTV, transitions/transversions:
# TSTV\t[2]id\t[3]ts\t[4]tv\t[5]ts/tv\t[6]ts (1st ALT)\t[7]tv (1st ALT)\t[8]ts/tv (1st ALT)
TSTV\t0\t{int(snps * 0.65)}\t{int(snps * 0.35)}\t1.86\t{int(snps * 0.65)}\t{int(snps * 0.35)}\t1.86
"""
    return {f"{sample}.bcftools_stats.txt": body}


def quast(sample: str) -> dict[str, str]:
    contigs = _vary(sample, 3, 14)
    length = _vary(sample, 29_000, 29_900)
    body = f"""Assembly\t{sample}
# contigs (>= 0 bp)\t{contigs}
# contigs (>= 1000 bp)\t{max(1, contigs - 2)}
Total length (>= 0 bp)\t{length}
Total length (>= 1000 bp)\t{length - 400}
# contigs\t{contigs}
Largest contig\t{length - 1200}
Total length\t{length}
GC (%)\t37.9
N50\t{length - 1500}
N75\t{length - 3000}
L50\t1
L75\t1
# N's per 100 kbp\t{_vary(sample, 20, 900)}
"""
    return {f"{sample}_quast/report.tsv": body}


def snpeff(sample: str) -> dict[str, str]:
    total = _vary(sample, 120, 260)
    body = f"""# Summary table

Name , Value
SnpEff_version , SnpEff 5.2 (build 2023-09-29)
Command_line_arguments , SnpEff -c snpeff.config MN908947.3 {sample}.vcf
Number_of_lines_of_input_file , {total}
Number_of_variants_before_filter , {total}
Number_of_known_variants , 0
Number_of_effects , {total * 2}
Genome_total_length , 29903
Change_rate , 1

# Effects by impact
Type , Count , Percent
HIGH , {int(total * 0.05)} , 5.0%
LOW , {int(total * 0.35)} , 35.0%
MODERATE , {int(total * 0.55)} , 55.0%
MODIFIER , {int(total * 0.05)} , 5.0%

# Effects by functional class
Type , Count , Percent
MISSENSE , {int(total * 0.55)} , 55.0%
NONSENSE , {int(total * 0.02)} , 2.0%
SILENT , {int(total * 0.43)} , 43.0%

# Count by effects
Type , Count , Percent
downstream_gene_variant , {int(total * 0.10)} , 10.0%
missense_variant , {int(total * 0.55)} , 55.0%
synonymous_variant , {int(total * 0.35)} , 35.0%

# Count by genomic region
Type , Count , Percent
DOWNSTREAM , {int(total * 0.10)} , 10.0%
EXON , {int(total * 0.85)} , 85.0%
UPSTREAM , {int(total * 0.05)} , 5.0%
"""
    return {f"{sample}.snpEff_summary.csv": body}


def fastp(sample: str) -> dict[str, str]:
    before = _vary(sample, 100_000, 130_000)
    after = int(before * 0.96)
    payload = {
        "summary": {
            "fastp_version": "0.23.4",
            "sequencing": "paired end (50 cycles + 50 cycles)",
            "before_filtering": {
                "total_reads": before,
                "total_bases": before * 50,
                "q20_bases": int(before * 50 * 0.97),
                "q30_bases": int(before * 50 * 0.93),
                "q20_rate": 0.97,
                "q30_rate": 0.93,
                "read1_mean_length": 50,
                "read2_mean_length": 50,
                "gc_content": 0.41,
            },
            "after_filtering": {
                "total_reads": after,
                "total_bases": after * 50,
                "q20_bases": int(after * 50 * 0.98),
                "q30_bases": int(after * 50 * 0.95),
                "q20_rate": 0.98,
                "q30_rate": 0.95,
                "read1_mean_length": 50,
                "read2_mean_length": 50,
                "gc_content": 0.41,
            },
        },
        "filtering_result": {
            "passed_filter_reads": after,
            "low_quality_reads": before - after,
            "too_many_N_reads": 0,
            "too_short_reads": 0,
            "too_long_reads": 0,
        },
        "duplication": {"rate": 0.04},
        "insert_size": {"peak": 180},
        "command": f"fastp -i {sample}_R1.fastq.gz -I {sample}_R2.fastq.gz",
    }
    return {f"{sample}.fastp.json": json.dumps(payload, indent=2)}


def mosdepth(sample: str) -> dict[str, str]:
    mean = _vary(sample, 180, 460)
    summary = f"""chrom\tlength\tbases\tmean\tmin\tmax
MN908947.3\t29903\t{29903 * mean}\t{mean}.00\t0\t{mean * 3}
total\t29903\t{29903 * mean}\t{mean}.00\t0\t{mean * 3}
"""
    dist_rows = []
    for depth in range(0, 60):
        frac = max(0.0, 1.0 - depth / 60.0)
        dist_rows.append(f"MN908947.3\t{depth}\t{frac:.2f}")
        dist_rows.append(f"total\t{depth}\t{frac:.2f}")
    return {
        f"{sample}.mosdepth.summary.txt": summary,
        f"{sample}.mosdepth.global.dist.txt": "\n".join(dist_rows) + "\n",
    }


def samtools(sample: str) -> dict[str, str]:
    total = _vary(sample, 90_000, 130_000)
    mapped = int(total * 0.94)
    body = f"""# This file was produced by samtools stats (1.19+htslib-1.19) and can be plotted using plot-bamstats
# This file contains statistics for all reads.
# The command line was:  stats {sample}.bam
CHK\t7ba3a1f2\t2c0d1c98\t9b2c11ee
SN\traw total sequences:\t{total}
SN\tfiltered sequences:\t0
SN\tsequences:\t{total}
SN\tis sorted:\t1
SN\t1st fragments:\t{total // 2}
SN\tlast fragments:\t{total // 2}
SN\treads mapped:\t{mapped}
SN\treads mapped and paired:\t{mapped}
SN\treads unmapped:\t{total - mapped}
SN\treads properly paired:\t{int(mapped * 0.98)}
SN\treads duplicated:\t{int(total * 0.03)}
SN\treads MQ0:\t120
SN\ttotal length:\t{total * 50}
SN\tbases mapped:\t{mapped * 50}
SN\tbases mapped (cigar):\t{mapped * 49}
SN\tmismatches:\t{_vary(sample, 900, 2600)}
SN\terror rate:\t1.5e-03
SN\taverage length:\t50
SN\tmaximum length:\t50
SN\taverage quality:\t36.0
SN\tinsert size average:\t180.0
SN\tinsert size standard deviation:\t40.0
SN\tpairs on different chromosomes:\t0
"""
    return {f"{sample}.stats": body}


def ivar(sample: str) -> dict[str, str]:
    trimmed = _vary(sample, 80_000, 110_000)
    # Per-primer counts are not optional: `primer_heatmap()` runs unconditionally
    # and indexes `final_data[0]`, so a log without them takes the whole module
    # down with an IndexError rather than just losing the heatmap.
    primer_counts = "\n".join(
        f"nCoV-2019_{n}_{side}\t{_vary(sample + str(n), 400, 3000)}"
        for n in range(1, 13)
        for side in ("LEFT", "RIGHT")
    )
    body = f"""Found 98 primers in BED file
Number of references in file: 1
MN908947.3
Using Region: MN908947.3

Processed 10% reads ...
Processed 100% reads ...

Trimmed primers from {100.0 * trimmed / 120000:.2f}% ({trimmed}) of reads.
{_vary(sample, 200, 900)} ({_vary(sample, 1, 3)}%) reads were quality trimmed below the minimum length of 30 bp and were not written to file.
{_vary(sample, 100, 700)} ({_vary(sample, 1, 2)}%) reads started outside of primer regions. Since the -e flag was given, these reads were written to file.

{primer_counts}
"""
    return {f"{sample}.ivar_trim.log": body}


def summary(sample: str) -> dict[str, str]:
    """nf-core custom content, the one MultiQC "module" with no third-party tool.

    Emitted once for the whole run rather than per sample: the file *is* the
    per-sample table. The anchor MultiQC derives from the filename is
    `summary_conformance_metrics`, which normalises to `summary` — the section
    the catalog's `multiqc/summary.yaml` declares.
    """
    if sample != SAMPLES[0]:
        return {}
    header = "Sample,Input reads,Trimmed reads,Mapped reads,Coverage median,Variants"
    rows = [
        f"{s},{_vary(s, 100_000, 130_000)},{_vary(s, 95_000, 125_000)},"
        f"{_vary(s, 90_000, 120_000)},{_vary(s, 180, 460)},{_vary(s, 120, 260)}"
        for s in SAMPLES
    ]
    preamble = (
        "# id: 'summary_conformance_metrics'\n# section_name: 'Run summary'\n# plot_type: 'table'\n"
    )
    return {
        "summary_conformance_metrics_mqc.csv": preamble + header + "\n" + "\n".join(rows) + "\n"
    }


def happy(sample: str) -> dict[str, str]:
    """hap.py `*.summary.csv` — MultiQC keys on the `Type,Filter,TRUTH` header.

    One row per variant type × filter; the numbers are recomputed so recall,
    precision and F1 agree with the TP / FN / FP counts they sit next to.
    """
    header = (
        "Type,Filter,TRUTH.TOTAL,TRUTH.TP,TRUTH.FN,QUERY.TOTAL,QUERY.FP,QUERY.UNK,"
        "FP.gt,FP.al,METRIC.Recall,METRIC.Precision,METRIC.Frac_NA,METRIC.F1_Score,"
        "TRUTH.TOTAL.TiTv_ratio,QUERY.TOTAL.TiTv_ratio,"
        "TRUTH.TOTAL.het_hom_ratio,QUERY.TOTAL.het_hom_ratio"
    )
    rows = [header]
    for vtype, total, unk in (
        ("INDEL", _vary(sample, 3_500, 4_200), 3_000),
        ("SNP", _vary(sample, 20_000, 24_000), 9_000),
    ):
        tp = total - _vary(sample, 120, 400)
        fn = total - tp
        fp = _vary(sample, 1, 60)
        query_total = tp + fp + unk
        recall = tp / total
        precision = tp / (tp + fp)
        f1 = 2 * precision * recall / (precision + recall)
        for flt in ("ALL", "PASS"):
            rows.append(
                f"{vtype},{flt},{total},{tp},{fn},{query_total},{fp},{unk},0,0,"
                f"{recall:.6f},{precision:.6f},{unk / query_total:.6f},{f1:.6f},"
                f"{'' if vtype == 'INDEL' else '2.05'},{'' if vtype == 'INDEL' else '2.03'},1.71,1.69"
            )
    return {f"{sample}.summary.csv": "\n".join(rows) + "\n"}


def sompy(sample: str) -> dict[str, str]:
    """som.py `*.stats.csv` — MultiQC keys on `,sompyversion,sompycmd` in the header.

    Three rows (`records`, `indels`, `SNVs`) the module splits into its
    combined / indel / SNV tables; `records` is the sum of the other two.
    """
    header = (
        ",type,total.truth,total.query,tp,fp,fn,unk,ambi,recall,recall_lower,"
        "recall_upper,recall2,precision,precision_lower,precision_upper,na,ambiguous,"
        "fp.region.size,fp.rate,sompyversion,sompycmd"
    )
    rows = [header]
    counts = {
        "indels": (_vary(sample, 1_400, 1_700), _vary(sample, 40, 400), _vary(sample, 10, 120)),
        "SNVs": (_vary(sample, 3_000, 3_600), _vary(sample, 2_200, 3_200), _vary(sample, 20, 300)),
    }
    counts["records"] = tuple(sum(c[i] for c in counts.values()) for i in range(3))
    for idx, vtype in enumerate(("records", "indels", "SNVs")):
        total, tp, fp = counts[vtype]
        fn = total - tp
        recall = tp / total
        precision = tp / (tp + fp)
        rows.append(
            f"{idx},{vtype},{total},{tp + fp},{tp},{fp},{fn},0,0,{recall:.6f},"
            f"{max(recall - 0.02, 0):.6f},{min(recall + 0.02, 1):.6f},{recall:.6f},"
            f"{precision:.6f},{max(precision - 0.03, 0):.6f},{min(precision + 0.03, 1):.6f},"
            f"0,0,2900000000,{fp / 2900:.6f},0.3.15,som.py {sample}.vcf.gz"
        )
    return {f"{sample}.stats.csv": "\n".join(rows) + "\n"}


def truvari(sample: str) -> dict[str, str]:
    """truvari bench `log.txt` — MultiQC keys on a `truvari … bench` line and the
    `Stats:` JSON block; the sample name is the directory holding the log.
    """
    base = _vary(sample, 9_000, 11_000)
    tp_base = base - _vary(sample, 400, 1_500)
    fn = base - tp_base
    fp = _vary(sample, 200, 900)
    tp_comp = tp_base - _vary(sample, 0, 25)
    precision = tp_comp / (tp_comp + fp)
    recall = tp_base / base
    f1 = 2 * precision * recall / (precision + recall)
    tp_gt = tp_comp - _vary(sample, 50, 300)
    body = f"""2026-04-22 10:00:00,000 [INFO] Truvari v4.3.1
2026-04-22 10:00:00,001 [INFO] Command /usr/bin/truvari bench -b truth.vcf.gz -c {sample}.vcf.gz -o {sample}
2026-04-22 10:00:00,002 [INFO] Params:
2026-04-22 10:00:41,000 [INFO] Stats: {{
    "TP-base": {tp_base},
    "TP-comp": {tp_comp},
    "FP": {fp},
    "FN": {fn},
    "precision": {precision:.6f},
    "recall": {recall:.6f},
    "f1": {f1:.6f},
    "base cnt": {base},
    "comp cnt": {tp_comp + fp},
    "TP-comp_TP-gt": {tp_gt},
    "TP-comp_FP-gt": {tp_comp - tp_gt},
    "TP-base_TP-gt": {tp_gt},
    "TP-base_FP-gt": {tp_base - tp_gt},
    "gt_concordance": {tp_gt / tp_comp:.6f}
}}
2026-04-22 10:00:41,100 [INFO] Finished bench
"""
    return {f"truvari_bench/{sample}/log.txt": body}


# Catalog `section` value → stub builder. Keyed on the catalog's own vocabulary
# so a new MultiQC output shows up as a KeyError in the generator, not as a
# section that silently never appears in the report.
STUB_BUILDERS = {
    "bcftools": bcftools,
    "bowtie2": bowtie2,
    "cutadapt": cutadapt,
    "fastp": fastp,
    "fastqc": fastqc,
    "happy": happy,
    "ivar": ivar,
    "kraken": kraken,
    "mosdepth": mosdepth,
    "quast": quast,
    "samtools": samtools,
    "snpeff": snpeff,
    "sompy": sompy,
    "summary": summary,
    "truvari": truvari,
}


def build_inputs(sections: list[str]) -> dict[str, str]:
    """Every stub file needed to make `sections` appear in one MultiQC report."""
    files: dict[str, str] = {}
    for section in sections:
        builder = STUB_BUILDERS[section]
        for sample in SAMPLES:
            files.update(builder(sample))
    return files
