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
def star(sample: str) -> dict[str, str]:
    total = _vary(sample, 90_000, 130_000)
    unique = int(total * 0.87)
    multi = int(total * 0.06)
    too_many = int(total * 0.01)
    too_short = total - unique - multi - too_many
    body = f"""                                 Started job on |\tJun 02 07:13:20
                             Started mapping on |\tJun 02 07:16:56
                                    Finished on |\tJun 02 07:16:59
       Mapping speed, Million of reads per hour |\t14.43

                          Number of input reads |\t{total}
                      Average input read length |\t200
                                    UNIQUE READS:
                   Uniquely mapped reads number |\t{unique}
                        Uniquely mapped reads % |\t{100 * unique / total:.2f}%
                          Average mapped length |\t199.93
                       Number of splices: Total |\t{unique // 2}
            Number of splices: Annotated (sjdb) |\t{unique // 2 - 20}
                       Number of splices: GT/AG |\t{unique // 2 - 40}
                       Number of splices: GC/AG |\t2
                       Number of splices: AT/AC |\t0
                  Number of splices: Non-canonical |\t38
                      Mismatch rate per base, % |\t0.14%
                         Deletion rate per base |\t0.00%
                        Deletion average length |\t1.30
                        Insertion rate per base |\t0.00%
                       Insertion average length |\t1.15
                                    MULTI-MAPPING READS:
        Number of reads mapped to multiple loci |\t{multi}
             % of reads mapped to multiple loci |\t{100 * multi / total:.2f}%
        Number of reads mapped to too many loci |\t{too_many}
             % of reads mapped to too many loci |\t{100 * too_many / total:.2f}%
                                  UNMAPPED READS:
  Number of reads unmapped: too many mismatches |\t0
       % of reads unmapped: too many mismatches |\t0.00%
            Number of reads unmapped: too short |\t{too_short}
                 % of reads unmapped: too short |\t{100 * too_short / total:.2f}%
                Number of reads unmapped: other |\t0
                     % of reads unmapped: other |\t0.00%
                                  CHIMERIC READS:
                       Number of chimeric reads |\t0
                            % of chimeric reads |\t0.00%
"""
    # ReadsPerGene.out.tab is what drives STAR's "Gene Counts" bar plot; the four
    # header rows are the assignment summary MultiQC reads, the gene rows below
    # only need to exist.
    gene_counts = "\n".join(
        [
            f"N_unmapped\t{too_short}\t{too_short}\t{too_short}",
            f"N_multimapping\t{multi}\t{multi}\t{multi}",
            "N_noFeature\t900\t4200\t4300",
            "N_ambiguous\t300\t120\t130",
        ]
        + [f"ENSG0000000{idx:04d}\t{100 + idx}\t{50 + idx}\t{50 + idx}" for idx in range(20)]
    )
    return {
        f"{sample}.Log.final.out": body,
        f"{sample}.ReadsPerGene.out.tab": gene_counts + "\n",
    }


def picard(sample: str) -> dict[str, str]:
    pairs = _vary(sample, 40_000, 60_000)
    dup_pairs = int(pairs * 0.10)
    dedup = f"""## htsjdk.samtools.metrics.StringHeader
# MarkDuplicates --INPUT {sample}.bam --OUTPUT {sample}.md.bam --METRICS_FILE {sample}.bam.metrics
## htsjdk.samtools.metrics.StringHeader
# Started on: Tue Jun 02 07:19:44 GMT 2026

## METRICS CLASS\tpicard.sam.DuplicationMetrics
LIBRARY\tUNPAIRED_READS_EXAMINED\tREAD_PAIRS_EXAMINED\tSECONDARY_OR_SUPPLEMENTARY_RDS\tUNMAPPED_READS\tUNPAIRED_READ_DUPLICATES\tREAD_PAIR_DUPLICATES\tREAD_PAIR_OPTICAL_DUPLICATES\tPERCENT_DUPLICATION\tESTIMATED_LIBRARY_SIZE
Unknown Library\t0\t{pairs}\t2565\t202\t0\t{dup_pairs}\t0\t{dup_pairs / pairs:.6f}\t55357

## HISTOGRAM\tjava.lang.Double
BIN\tCoverageMult\tall_sets\tnon_optical_sets
1.0\t1\t{pairs - dup_pairs}\t{pairs - dup_pairs}
2.0\t1.806275\t838\t838
3.0\t2.456356\t96\t96
4.0\t2.980500\t33\t33
5.0\t3.403104\t6\t6
"""
    insert_hist = "\n".join(
        f"{size}\t{max(1, 400 - abs(size - 320) * 3)}" for size in range(180, 460, 10)
    )
    insert = f"""## htsjdk.samtools.metrics.StringHeader
# CollectInsertSizeMetrics --INPUT {sample}.bam --OUTPUT {sample}_collectinsertsize.txt
## htsjdk.samtools.metrics.StringHeader
# Started on: Tue Jun 02 07:19:42 GMT 2026

## METRICS CLASS\tpicard.analysis.InsertSizeMetrics
MEDIAN_INSERT_SIZE\tMODE_INSERT_SIZE\tMEDIAN_ABSOLUTE_DEVIATION\tMIN_INSERT_SIZE\tMAX_INSERT_SIZE\tMEAN_INSERT_SIZE\tSTANDARD_DEVIATION\tREAD_PAIRS\tPAIR_ORIENTATION\tWIDTH_OF_10_PERCENT\tWIDTH_OF_20_PERCENT\tWIDTH_OF_30_PERCENT\tWIDTH_OF_40_PERCENT\tWIDTH_OF_50_PERCENT\tWIDTH_OF_60_PERCENT\tWIDTH_OF_70_PERCENT\tWIDTH_OF_80_PERCENT\tWIDTH_OF_90_PERCENT\tWIDTH_OF_95_PERCENT\tWIDTH_OF_99_PERCENT\tSAMPLE\tLIBRARY\tREAD_GROUP
320\t318\t42\t180\t460\t321.400000\t45.100000\t{pairs}\tFR\t21\t41\t61\t81\t101\t121\t141\t161\t181\t201\t221\t\t\t

## HISTOGRAM\tjava.lang.Integer
insert_size\tAll_Reads.fr_count
{insert_hist}
"""
    coverage_hist = "\n".join(
        f"{pos}\t{0.35 + 0.65 * (1 - abs(pos - 50) / 50):.6f}" for pos in range(0, 101)
    )
    rnaseq = f"""## htsjdk.samtools.metrics.StringHeader
# CollectRnaSeqMetrics --INPUT {sample}.bam --OUTPUT {sample}.rna_metrics
## htsjdk.samtools.metrics.StringHeader
# Started on: Tue Jun 02 07:19:43 GMT 2026

## METRICS CLASS\tpicard.analysis.RnaSeqMetrics
PF_BASES\tPF_ALIGNED_BASES\tRIBOSOMAL_BASES\tCODING_BASES\tUTR_BASES\tINTRONIC_BASES\tINTERGENIC_BASES\tIGNORED_READS\tCORRECT_STRAND_READS\tINCORRECT_STRAND_READS\tNUM_R1_TRANSCRIPT_STRAND_READS\tNUM_R2_TRANSCRIPT_STRAND_READS\tNUM_UNEXPLAINED_READS\tPCT_R1_TRANSCRIPT_STRAND_READS\tPCT_R2_TRANSCRIPT_STRAND_READS\tPCT_RIBOSOMAL_BASES\tPCT_CODING_BASES\tPCT_UTR_BASES\tPCT_INTRONIC_BASES\tPCT_INTERGENIC_BASES\tPCT_MRNA_BASES\tPCT_USABLE_BASES\tPCT_CORRECT_STRAND_READS\tMEDIAN_CV_COVERAGE\tMEDIAN_5PRIME_BIAS\tMEDIAN_3PRIME_BIAS\tMEDIAN_5PRIME_TO_3PRIME_BIAS\tSAMPLE\tLIBRARY\tREAD_GROUP
2443249\t2381339\t0\t2318486\t42917\t14137\t5799\t0\t0\t0\t223\t9936\t787\t0.021951\t0.978049\t0\t0.973606\t0.018022\t0.005937\t0.002435\t0.991628\t0.966501\t0\t1.365731\t0.9\t0.95\t0.95\t\t\t

## HISTOGRAM\tjava.lang.Integer
normalized_position\tAll_Reads.normalized_coverage
{coverage_hist}
"""
    return {
        f"{sample}.bam.metrics": dedup,
        f"{sample}_collectinsertsize.txt": insert,
        f"{sample}.rna_metrics": rnaseq,
    }


def dupradar(sample: str) -> dict[str, str]:
    """dupRadar has no MultiQC module — nf-core/rnaseq ships it as custom content.

    So the section is whatever the `#id:` header says, and the header block is
    the entire contract: MultiQC reads it as YAML, then the two headerless
    columns below it as the x/y of one line per file.
    """
    intercept = _vary(sample, 12, 34)
    rows = "\n".join(
        f"{10 ** (-2 + n / 20.0):.6f}\t{min(99.0, intercept + 78.0 * (n / 120.0) ** 1.6):.4f}"
        for n in range(121)
    )
    return {
        f"{sample}_duprateExpDensCurve_mqc.txt": f"""#id: dupradar
#section_name: 'dupRadar'
#section_href: 'bioconductor.org/packages/release/bioc/html/dupRadar.html'
#description: "provides duplication rate quality control for RNA-Seq datasets.
#  Highly expressed genes can be expected to have a lot of duplicate reads, but
#  high numbers of duplicates at low read counts can indicate low library
#  complexity with technical duplication."
#plot_type: 'linegraph'
#anchor: 'dupradar'
#pconfig:
#    title: 'DupRadar General Linear Model'
#    xlog: True
#    xlab: 'expression (reads/kbp)'
#    ylab: '% duplicate reads'
#    ymin: 0
#    ymax: 100
{rows}
"""
    }


def featurecounts(sample: str) -> dict[str, str]:
    """featureCounts' `*.summary` sidecar — the filename suffix *is* the search
    pattern, and the sample name comes from the `Status` header's column, not
    from the file.
    """
    assigned = _vary(sample, 900_000, 1_200_000)
    rows = [
        ("Assigned", assigned),
        ("Unassigned_Unmapped", int(assigned * 0.01)),
        ("Unassigned_Read_Type", 0),
        ("Unassigned_Singleton", 0),
        ("Unassigned_MappingQuality", 0),
        ("Unassigned_Chimera", 0),
        ("Unassigned_FragmentLength", 0),
        ("Unassigned_Duplicate", 0),
        ("Unassigned_MultiMapping", int(assigned * 0.08)),
        ("Unassigned_Secondary", 0),
        ("Unassigned_NonSplit", 0),
        ("Unassigned_NoFeatures", int(assigned * 0.06)),
        ("Unassigned_Overlapping_Length", 0),
        ("Unassigned_Ambiguity", int(assigned * 0.02)),
    ]
    body = "\n".join([f"Status\t{sample}.markdup.sorted.bam"] + [f"{k}\t{v}" for k, v in rows])
    return {f"{sample}.featureCounts.txt.summary": body + "\n"}


def qualimap(sample: str) -> dict[str, str]:
    """Qualimap RNAseq: the two files behind genomic origin and gene-body coverage.

    `rnaseq_qc_results.txt` names its own sample through the `bam file =` line,
    while the coverage profile is named from the *grandparent* directory of the
    file — hence the `raw_data_qualimapReport/` level, which is where Qualimap
    puts it.
    """
    aligned = _vary(sample, 900_000, 1_200_000)
    exonic = int(aligned * 0.86)
    intronic = int(aligned * 0.08)
    intergenic = aligned - exonic - intronic
    results = f""">>>>>>> Input

    bam file = {sample}.markdup.sorted.bam
    gff file = genome.gtf
    counting algorithm = uniquely-mapped-reads
    protocol = strand-specific-reverse

>>>>>>> Reads alignment

    reads aligned  = {aligned}
    total alignments = {int(aligned * 1.02)}
    secondary alignments = 0
    non-unique alignments = {int(aligned * 0.02)}
    aligned to genes  = {exonic}
    ambiguous alignments = {int(aligned * 0.01)}
    no feature assigned = {intronic + intergenic}
    not aligned = 0

>>>>>>> Reads genomic origin

    exonic =  {exonic} ({100.0 * exonic / aligned:.2f}%)
    intronic = {intronic} ({100.0 * intronic / aligned:.2f}%)
    intergenic = {intergenic} ({100.0 * intergenic / aligned:.2f}%)
    overlapping exon = {int(aligned * 0.03)} ({3.0:.2f}%)

>>>>>>> Transcript coverage profile

    5' bias = {_vary(sample, 60, 90) / 100.0:.2f}
    3' bias = {_vary(sample, 70, 95) / 100.0:.2f}
    5'-3' bias = {_vary(sample, 90, 130) / 100.0:.2f}
"""
    depth = _vary(sample, 900, 1_400)
    coverage = "\n".join(
        f"{pos}.0\t{depth * (0.45 + 0.55 * (1.0 - abs(pos - 55) / 100.0)):.4f}"
        for pos in range(0, 100)
    )
    return {
        f"qualimap/{sample}/rnaseq_qc_results.txt": results,
        f"qualimap/{sample}/raw_data_qualimapReport/coverage_profile_along_genes_(total).txt": (
            "#Transcript position\tCoverage\n" + coverage + "\n"
        ),
    }


def rseqc(sample: str) -> dict[str, str]:
    """One file per RSeQC script the catalog's description names.

    Most of these are recognised by content rather than by filename, and the
    strings are load-bearing to the byte: `read_distribution` keys on the whole
    `Group  Total_bases  Tag_count  Tags/Kb` header row, and
    `junction_annotation` on `Total splicing  Events:` with its double space.
    """
    total = _vary(sample, 90_000, 130_000)
    unique = int(total * 0.87)
    # bam_stat: `read_2` is read unconditionally to decide single vs paired end,
    # so dropping the line is a KeyError that takes every RSeQC section down.
    bam_stat = f"""#Output (all numbers are read count)
#==================================================
Total records:                          {total}

QC failed:                              0
Optical/PCR duplicate:                  0
Non primary hits                        {int(total * 0.04)}
Unmapped reads:                         {total - unique - int(total * 0.04)}
mapq < mapq_cut (non-unique):           {int(total * 0.05)}

mapq >= mapq_cut (unique):              {unique}
Read-1:                                 {unique // 2}
Read-2:                                 {unique - unique // 2}
Reads map to '+':                       {unique // 2}
Reads map to '-':                       {unique - unique // 2}
Non-splice reads:                       {int(unique * 0.72)}
Splice reads:                           {unique - int(unique * 0.72)}
Reads mapped in proper pairs:           {int(unique * 0.96)}
Proper-paired reads map to different chrom:     0
"""
    tags = int(total * 1.1)
    assigned = int(tags * 0.86)
    groups = [
        ("CDS_Exons", 33_302_033, int(assigned * 0.58)),
        ("5'UTR_Exons", 21_717_577, int(assigned * 0.04)),
        ("3'UTR_Exons", 15_347_371, int(assigned * 0.22)),
        ("Introns", 1_132_917_579, int(assigned * 0.10)),
        ("TSS_up_1kb", 17_827_098, int(assigned * 0.01)),
        ("TSS_up_5kb", 81_971_725, int(assigned * 0.01)),
        ("TSS_up_10kb", 149_730_983, int(assigned * 0.01)),
        ("TES_down_1kb", 18_011_614, int(assigned * 0.01)),
        ("TES_down_5kb", 78_700_757, int(assigned * 0.01)),
        ("TES_down_10kb", 141_014_195, int(assigned * 0.01)),
    ]
    group_rows = "\n".join(
        f"{name:<20}{bases:<20}{count:<20}{1000.0 * count / bases:.2f}"
        for name, bases, count in groups
    )
    read_distribution = f"""Total Reads                   {total}
Total Tags                    {tags}
Total Assigned Tags           {assigned}
=====================================================================
Group               Total_bases         Tag_count           Tags/Kb
{group_rows}
=====================================================================
"""
    peak = _vary(sample, 60, 110)
    inner_distance = "\n".join(
        f"{lo}\t{lo + 5}\t{max(0, 900 - abs(lo + 2 - peak) * 9)}" for lo in range(-250, 250, 5)
    )
    events = _vary(sample, 40_000, 60_000)
    junctions = _vary(sample, 20_000, 30_000)
    junction_annotation = f"""Total splicing  Events:\t{events}
Known Splicing Events:\t{int(events * 0.94)}
Partial Novel Splicing Events:\t{int(events * 0.04)}
Novel Splicing Events:\t{events - int(events * 0.94) - int(events * 0.04)}

Total splicing  Junctions:\t{junctions}
Known Splicing Junctions:\t{int(junctions * 0.88)}
Partial Novel Splicing Junctions:\t{int(junctions * 0.08)}
Novel Splicing Junctions:\t{junctions - int(junctions * 0.88) - int(junctions * 0.08)}
"""

    x_pct = list(range(5, 105, 5))

    # junctionSaturation_plot.r is parsed with `^([xyzw])=c\(([\d,]+)\)$`: bare
    # integers only, so no decimals and no spaces after the commas.
    def _saturation(scale: float) -> str:
        return ",".join(str(int(junctions * scale * (1.0 - (1.0 - p / 100.0) ** 2))) for p in x_pct)

    junction_saturation = f"""pdf('{sample}.junctionSaturation_plot.pdf')
x=c({",".join(str(p) for p in x_pct)})
y=c({_saturation(0.88)})
z=c({_saturation(1.0)})
w=c({_saturation(0.12)})
m=max(y,z,w)
plot(x,z/1000,xlab='percent of total reads',ylab='Number of splicing junctions (x1000)',type='o',col='blue')
dev.off()
"""
    antisense = _vary(sample, 9_400, 9_800) / 10_000.0
    failed = _vary(sample, 100, 300) / 10_000.0
    infer_experiment = f"""

This is PairEnd Data
Fraction of reads failed to determine: {failed:.4f}
Fraction of reads explained by "1++,1--,2+-,2-+": {1.0 - antisense - failed:.4f}
Fraction of reads explained by "1+-,1-+,2++,2--": {antisense:.4f}
"""
    return {
        f"{sample}.bam_stat.txt": bam_stat,
        f"{sample}.read_distribution.txt": read_distribution,
        f"{sample}.inner_distance_freq.txt": inner_distance + "\n",
        f"{sample}.junction_annotation.log": junction_annotation,
        f"{sample}.junctionSaturation_plot.r": junction_saturation,
        f"{sample}.infer_experiment.txt": infer_experiment,
    }


def salmon(sample: str) -> dict[str, str]:
    """Salmon writes a directory per sample; MultiQC keys on the directory names.

    `meta_info.json` is only read when its parent directory is `aux_info` or
    `aux`, `flenDist.txt` only when its parent is `libParams`, and both take the
    sample name from the directory above that — so the layout here is the
    parser, not decoration.
    """
    total = _vary(sample, 100_000, 130_000)
    mapped = int(total * 0.83)
    meta = {
        "salmon_version": "1.10.1",
        "samp_type": "none",
        "opt_type": "vb",
        "quant_errors": [],
        "num_libraries": 1,
        "library_types": ["ISR"],
        "frag_dist_length": 1001,
        "seq_bias_correct": False,
        "gc_bias_correct": False,
        "num_bias_bins": 4096,
        "mapping_type": "mapping",
        "num_targets": 21_500,
        "num_bootstraps": 0,
        "num_processed": total,
        "num_mapped": mapped,
        "num_decoy_fragments": 0,
        "num_dovetail_fragments": 0,
        "num_fragments_filtered_vm": 0,
        "num_alignments_below_threshold_for_mapped_fragments_vm": 0,
        "percent_mapped": round(100.0 * mapped / total, 4),
        "call": "quant",
        "start_time": "Tue Jun  2 07:20:00 2026",
        "end_time": "Tue Jun  2 07:21:00 2026",
    }
    lfc = {
        "read_files": f"[ {sample}_R1.fastq.gz, {sample}_R2.fastq.gz ]",
        "expected_format": "ISR",
        "compatible_fragment_ratio": round(_vary(sample, 88, 97) / 100.0, 4),
        "num_compatible_fragments": mapped,
        "num_assigned_fragments": mapped,
        "num_frags_with_concordant_consistent_mappings": mapped,
        "num_frags_with_inconsistent_or_orphan_mappings": int(total * 0.02),
        "strand_mapping_bias": round(_vary(sample, 40, 60) / 100.0, 4),
        "MSF": 0,
        "OSF": 0,
        "ISF": int(mapped * 0.02),
        "MSR": 0,
        "OSR": 0,
        "ISR": int(mapped * 0.96),
        "SF": int(mapped * 0.01),
        "SR": int(mapped * 0.01),
    }
    peak = _vary(sample, 180, 240)
    # flenDist.txt is one whitespace-separated row of densities, indexed by
    # fragment length; MultiQC numbers the buckets by position, not by a header.
    fld = " ".join(
        f"{max(0.0, 1.0 - abs(length - peak) / 120.0) / 240.0:.8f}" for length in range(1001)
    )
    return {
        f"{sample}/aux_info/meta_info.json": json.dumps(meta, indent=2),
        f"{sample}/lib_format_counts.json": json.dumps(lfc, indent=2),
        f"{sample}/libParams/flenDist.txt": fld + "\n",
    }


def _kraken_report(sample: str, tool: str) -> str:
    """A six-column Kraken report, the format `bracken` and `centrifuge` share.

    MultiQC 1.35 has no Bracken and no Centrifuge module: nf-core/taxprofiler
    runs the `kraken` module three times, split by `module_order` +
    `path_filters`, so both tools land here as a Kraken report rather than as
    their own native table (`*.bracken.tsv` / `*.centrifuge.report.txt` are not
    read by MultiQC at all). The `R`/`root` row is mandatory: `kraken.py` indexes
    it unconditionally and a report without it takes the module down.
    """
    unclassified = _vary(sample + tool, 3, 11)
    root = 100 - unclassified
    total = _vary(sample + tool, 400_000, 460_000)

    def cnt(pct: float) -> int:
        return int(total * pct / 100)

    rows = [
        (unclassified, cnt(unclassified), cnt(unclassified), "U", 0, "unclassified"),
        (root, cnt(root), 0, "R", 1, "root"),
        (root - 2, cnt(root - 2), 0, "D", 2, "  Bacteria"),
        (root - 20, cnt(root - 20), 0, "P", 1239, "    Bacillota"),
        (root - 30, cnt(root - 30), 0, "C", 91061, "      Bacilli"),
        (root - 40, cnt(root - 40), 0, "O", 1385, "        Bacillales"),
        (root - 50, cnt(root - 50), 0, "F", 90964, "          Staphylococcaceae"),
        (root - 55, cnt(root - 55), 0, "G", 1279, "            Staphylococcus"),
        (
            root - 60,
            cnt(root - 60),
            cnt(root - 60),
            "S",
            1280,
            "              Staphylococcus aureus",
        ),
        (
            root - 70,
            cnt(root - 70),
            cnt(root - 70),
            "S",
            1282,
            "              Staphylococcus epidermidis",
        ),
        (root - 78, cnt(root - 78), 0, "P", 1224, "    Pseudomonadota"),
        (root - 82, cnt(root - 82), 0, "G", 561, "            Escherichia"),
        (root - 85, cnt(root - 85), cnt(root - 85), "S", 562, "              Escherichia coli"),
    ]
    return (
        "\n".join(
            f"{pct:6.2f}\t{rooted}\t{direct}\t{rank}\t{taxid}\t{taxon}"
            for pct, rooted, direct, rank, taxid, taxon in rows
        )
        + "\n"
    )


def bracken(sample: str) -> dict[str, str]:
    return {f"{sample}.bracken.kraken2.report.txt": _kraken_report(sample, "bracken")}


def centrifuge(sample: str) -> dict[str, str]:
    return {f"{sample}.centrifuge.txt": _kraken_report(sample, "centrifuge")}


def kaiju(sample: str) -> dict[str, str]:
    """kaiju2table output. The `cannot be assigned to a ... species` row is load-bearing.

    It is the only place `kaiju.py` reads the taxonomic rank from, and a file
    whose rank stays `None` is dropped whole, so a stub without that row and the
    matching `unclassified` row produces no module at all.
    """
    total = _vary(sample, 400_000, 460_000)
    shift = _vary(sample, 0, 4) / 2.0
    rows = [
        ("Staphylococcus aureus", "1280", 21.5 + shift),
        ("Escherichia coli", "562", 17.25 + shift),
        ("Bacillus subtilis", "1423", 12.75 + shift),
        ("Pseudomonas aeruginosa", "287", 8.5 + shift),
        ("Listeria monocytogenes", "1639", 6.25 + shift),
        ("Salmonella enterica", "28901", 4.0 + shift),
        ("cannot be assigned to a (non-viral) species", "NA", float(_vary(sample, 4, 9))),
        ("unclassified", "NA", float(_vary(sample, 10, 16))),
    ]
    body = "\n".join(
        ["file\tpercent\treads\ttaxon_id\ttaxon_name"]
        + [
            f"{sample}.kaiju.tsv\t{pct:f}\t{int(total * pct / 100)}\t{taxid}\t{name}"
            for name, taxid, pct in rows
        ]
    )
    return {f"{sample}.kaijutable.txt": body + "\n"}


def metaphlan(sample: str) -> dict[str, str]:
    reads = _vary(sample, 400_000, 460_000)
    bacteria = 60.0 + _vary(sample, 0, 8)
    archaea = 100.0 - bacteria
    lineages = (
        ("k__Bacteria", "2", bacteria),
        ("k__Archaea", "2157", archaea),
        ("k__Bacteria|p__Bacillota", "2|1239", bacteria * 0.62),
        ("k__Bacteria|p__Pseudomonadota", "2|1224", bacteria * 0.38),
        ("k__Bacteria|p__Bacillota|c__Bacilli", "2|1239|91061", bacteria * 0.62),
        ("k__Bacteria|p__Bacillota|c__Bacilli|o__Bacillales", "2|1239|91061|1385", bacteria * 0.62),
        (
            "k__Bacteria|p__Bacillota|c__Bacilli|o__Bacillales|f__Staphylococcaceae",
            "2|1239|91061|1385|90964",
            bacteria * 0.62,
        ),
        (
            "k__Bacteria|p__Bacillota|c__Bacilli|o__Bacillales|f__Staphylococcaceae|g__Staphylococcus",
            "2|1239|91061|1385|90964|1279",
            bacteria * 0.62,
        ),
        (
            "k__Bacteria|p__Bacillota|c__Bacilli|o__Bacillales|f__Staphylococcaceae|"
            "g__Staphylococcus|s__Staphylococcus_aureus",
            "2|1239|91061|1385|90964|1279|1280",
            bacteria * 0.40,
        ),
        (
            "k__Bacteria|p__Bacillota|c__Bacilli|o__Bacillales|f__Staphylococcaceae|"
            "g__Staphylococcus|s__Staphylococcus_epidermidis",
            "2|1239|91061|1385|90964|1279|1282",
            bacteria * 0.22,
        ),
        ("k__Archaea|p__Euryarchaeota", "2157|28890", archaea),
        ("k__Archaea|p__Euryarchaeota|c__Methanobacteria", "2157|28890|183925", archaea),
    )
    rows = "\n".join(f"{clade}\t{taxid}\t{pct:.5f}\t" for clade, taxid, pct in lineages)
    body = f"""#mpa_v31_CHOCOPhlAn_201901
#/usr/local/bin/metaphlan --input_type fastq {sample}.fastq.gz --index mpa_v31_CHOCOPhlAn_201901
#{reads} reads processed
#SampleID\tMetaphlan_Analysis
#clade_name\tNCBI_tax_id\trelative_abundance\tadditional_species
{rows}
"""
    return {f"{sample}.metaphlan_profile.txt": body}


def nanoq(sample: str) -> dict[str, str]:
    reads = _vary(sample, 600_000, 640_000)
    mean_len = _vary(sample, 4_600, 5_200)
    length_rows = "\n".join(
        f"> {threshold:<9} {int(reads * frac):<17} {100.0 * frac:04.1f}%"
        for threshold, frac in (
            (200, 1.0),
            (500, 1.0),
            (1000, 0.999),
            (2000, 0.85),
            (5000, 0.45),
            (10000, 0.05),
            (30000, 0.001),
            (50000, 0.0),
        )
    )
    quality_rows = "\n".join(
        f"> {threshold:<3} {int(reads * frac):<13} {100.0 * frac:04.1f}%"
        for threshold, frac in (
            (5, 1.0),
            (7, 1.0),
            (10, 0.78),
            (12, 0.09),
            (15, 0.0),
            (20, 0.0),
        )
    )
    body = f"""Nanoq Read Summary
====================

Number of reads:      {reads}
Number of bases:      {reads * mean_len}
N50 read length:      {mean_len + 1_200}
Longest read:         {mean_len * 9}
Shortest read:        1000
Mean read length:     {mean_len}
Median read length:   {mean_len - 300}
Mean read quality:    {_vary(sample, 100, 130) / 10:.2f}
Median read quality:  {_vary(sample, 105, 135) / 10:.2f}


Read length thresholds (bp)

{length_rows}


Read quality thresholds (Q)

{quality_rows}
"""
    return {f"{sample}_filtered.stats": body}


def nonpareil(sample: str) -> dict[str, str]:
    """`NonpareilCurves.R --json` output, one file for the whole run.

    Emitted once, like `summary`: nf-core/taxprofiler collects every sample's
    curve into a single `nonpareil_all_samples.json`, and the module takes its
    sample names from the JSON keys, not from the filename. The `.npo` table
    (`nonpareil_all_samples.tsv`) is not what MultiQC reads.
    """
    if sample != SAMPLES[0]:
        return {}
    payload = {}
    for s in SAMPLES:
        kappa = _vary(s, 55, 65) / 100.0
        coverage = _vary(s, 58, 68) / 100.0
        effort = _vary(s, 80, 140) * 1_000_000.0
        x_adj = [effort * 2**e / 512 for e in range(10)]
        y_cov = [round(coverage * (1 - 2 ** -(e + 1)), 6) for e in range(10)]
        x_model = [effort * 2**e / 512 for e in range(14)]
        y_model = [round(min(0.99, coverage * (1 - 2 ** -(e + 1)) * 1.05), 6) for e in range(14)]
        payload[s] = {
            "label": s,
            "LRstar": round(effort * 22.5, 3),
            "version": "3.5.5",
            "kappa": kappa,
            "C": coverage,
            "consistent": 1,
            "star": 95,
            "has.model": True,
            "modelR": _vary(s, 990, 999) / 1000.0,
            "diversity": _vary(s, 170, 185) / 10.0,
            "L": 150.0,
            "AL": 150.0,
            "R": _vary(s, 600_000, 640_000),
            "LR": effort,
            "overlap": 50.0,
            "log.sample": 1.1,
            "x.adj": x_adj,
            "y.cov": y_cov,
            "y.sd": [0.01] * 10,
            "y.p25": [round(v * 0.95, 6) for v in y_cov],
            "y.p75": [round(v * 1.02, 6) for v in y_cov],
            "x.model": x_model,
            "y.model": y_model,
        }
    return {"nonpareil_all_samples.json": json.dumps(payload)}


# MultiQC 1.35 ships no Bracken and no Centrifuge module: both write a
# Kraken-style report, and nf-core/taxprofiler runs the `kraken` module three
# times behind `path_filters` so each tool gets its own anchor. Without this the
# three stubs collapse into one `kraken` section and both catalog sections are
# missing from the report.
#
# The third entry is not optional. Naming `kraken` in `module_order` at all
# replaces its default run, so the plain Kraken section disappears unless it is
# listed too, and since Bracken's file also ends `.kraken2.report.txt` it has to
# be excluded by path rather than left to the search pattern.
_KRAKEN_MODULE_ORDER = [
    {
        "kraken": {
            "name": "Bracken",
            "anchor": "bracken",
            "info": "Estimates species abundances by re-distributing reads in the taxonomic tree.",
            "path_filters": ["*.bracken.kraken2.report.txt"],
        }
    },
    {
        "kraken": {
            "name": "Centrifuge",
            "anchor": "centrifuge",
            "info": "Rapid, memory-efficient classification of DNA sequences from microbial samples.",
            "path_filters": ["*.centrifuge.txt"],
        }
    },
    {
        "kraken": {
            "path_filters": ["*.kraken2.report.txt"],
            "path_filters_exclude": ["*.bracken.kraken2.report.txt"],
        }
    },
]


def module_order_for(sections: list[str]) -> list[dict] | None:
    """The `module_order` these sections need, or None when the default will do.

    Only requested when a Kraken-derived alias is in play: the override replaces
    the plain `kraken` run, so applying it unconditionally would change how an
    unrelated report is built.
    """
    return _KRAKEN_MODULE_ORDER if {"bracken", "centrifuge"} & set(sections) else None


def deeptools(sample: str) -> dict[str, str]:
    """deepTools `plotFingerprint --outRawCounts --outQualityMetrics`.

    Both files are recognised by their first line and both name their samples
    from inside the file rather than from the filename, so the quoted column
    header is what puts `{sample}` in the report.
    """
    bins = 200
    # The counts are skewed on purpose: MultiQC sorts them and plots the
    # normalised cumulative sum, so a flat vector would draw the diagonal that
    # means "no enrichment" for every sample.
    enrichment = _vary(sample, 20, 45) / 10.0
    counts = "\n".join(
        str(int(1 + (rank / bins) ** enrichment * 4_000)) for rank in range(1, bins + 1)
    )
    raw = f"#plotFingerprint --outRawCounts\n'{sample}'\n{counts}\n"
    metrics = f"""Sample\tAUC\tSynthetic AUC\tX-intercept\tSynthetic X-intercept\tElbow Point\tSynthetic Elbow Point
{sample}\t{_vary(sample, 40, 70) / 100.0:.6f}\t0.500000\t{_vary(sample, 10, 40) / 100.0:.6f}\t0.000000\t{_vary(sample, 50, 80) / 100.0:.6f}\t0.500000
"""
    return {
        f"{sample}.plotFingerprint.raw.txt": raw,
        f"{sample}.plotFingerprint.qcmetrics.txt": metrics,
    }


def preseq(sample: str) -> dict[str, str]:
    """`preseq lc_extrap` output. The header row is the search pattern *and* the
    unit switch: `TOTAL_READS` is parsed as reads, `TOTAL_BASES` as base pairs,
    and anything else raises and drops the file.
    """
    total = _vary(sample, 2_000_000, 3_000_000)
    complexity = _vary(sample, 55, 85) / 100.0
    rows = []
    for step in range(0, 41):
        reads = float(step) * total
        distinct = total * complexity * (1.0 - 2.718281828 ** -(reads / (total * complexity)))
        rows.append(f"{reads:.1f}\t{distinct:.1f}\t{distinct * 0.98:.1f}\t{distinct * 1.02:.1f}")
    body = "TOTAL_READS\tEXPECTED_DISTINCT\tLOWER_0.95CI\tUPPER_0.95CI\n" + "\n".join(rows)
    return {f"{sample}.lc_extrap.txt": body + "\n"}


STUB_BUILDERS = {
    "bcftools": bcftools,
    "bowtie2": bowtie2,
    "bracken": bracken,
    "centrifuge": centrifuge,
    "cutadapt": cutadapt,
    "deeptools": deeptools,
    "dupradar": dupradar,
    "fastp": fastp,
    "fastqc": fastqc,
    "featurecounts": featurecounts,
    "happy": happy,
    "ivar": ivar,
    "kaiju": kaiju,
    "kraken": kraken,
    "metaphlan": metaphlan,
    "mosdepth": mosdepth,
    "nanoq": nanoq,
    "nonpareil": nonpareil,
    "picard": picard,
    "preseq": preseq,
    "qualimap": qualimap,
    "quast": quast,
    "rseqc": rseqc,
    "salmon": salmon,
    "samtools": samtools,
    "snpeff": snpeff,
    "sompy": sompy,
    "star": star,
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
