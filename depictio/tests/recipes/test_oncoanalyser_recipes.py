"""nf-core/oncoanalyser recipes on small synthetic outputs.

oncoanalyser publishes every table under ``<group_id>/<tool>/`` and names it after
the sample, so each recipe globs its files recursively and takes the sample from
the file name. These tests pin what the dashboard joins and filters on: the
sample keys (dots kept whole), the sample hub, PURPLE's fit and QC verdict, the
copy-number calls, the driver catalog merge, the PAVE impact of a somatic call,
the protein change in the residue contract, the per-gene selector of the protein
tab, LINX's clustered SVs and fusions, and the hmftools tables of the other tools.
"""

from __future__ import annotations

import gzip
from pathlib import Path

import polars as pl
import pytest

from depictio.recipes import execute_recipe, load_recipe, validate_schema

TUMOR = "T1.tumor_dna"
NORMAL = "T1.normal_dna"


def _write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if rel.endswith(".gz"):
        with gzip.open(path, "wt") as fh:
            fh.write(text)
    else:
        path.write_text(text)
    return path


def _tsv(header: list[str], rows: list[list[object]]) -> str:
    return "\n".join("\t".join(str(v) for v in line) for line in [header, *rows]) + "\n"


# ---------------------------------------------------------------------------
# Sample hub
# ---------------------------------------------------------------------------

SHEET = (
    "group_id,subject_id,sample_id,sample_type,sequence_type,filetype,info,filepath\n"
    "G1,S1,T1.normal_dna,normal,dna,fastq,lane:1,/data/n_1.fastq.gz\n"
    "G1,S1,T1.normal_dna,normal,dna,fastq,lane:2,/data/n_2.fastq.gz\n"
    "G1,S1,T1.tumor_dna,tumor,dna,bam,,/data/t.bam\n"
    "G1,S1,T1.tumor_rna,tumor,rna,fastq,lane:1,/data/r.fastq.gz\n"
)


def test_samples_collapse_lanes_and_derive_the_class(tmp_path: Path) -> None:
    _write(tmp_path, "input/samplesheet.csv", SHEET)
    out = execute_recipe("nf-core/oncoanalyser/samples.py", tmp_path, pipeline_version="3.0.0")
    assert out.height == 3
    rows = {r["sample_id"]: r for r in out.iter_rows(named=True)}
    assert rows[NORMAL]["input_files"] == 2
    assert rows[NORMAL]["sample_class"] == "normal_dna"
    assert rows[TUMOR]["filetypes"] == "bam"
    assert rows["T1.tumor_rna"]["sample_class"] == "tumor_rna"
    # Per-lane columns say nothing about the sample.
    assert "filepath" not in out.columns
    assert "info" not in out.columns
    # The tumor DNA comes before the normal of its group.
    assert out["sample_id"].to_list()[0] == TUMOR


def test_samples_reads_a_tab_separated_sheet(tmp_path: Path) -> None:
    _write(tmp_path, "input/samplesheet.csv", SHEET.replace(",", "\t"))
    out = execute_recipe("nf-core/oncoanalyser/samples.py", tmp_path, pipeline_version="3.0.0")
    assert out.height == 3
    assert set(out["group_id"]) == {"G1"}


def test_samples_names_the_missing_columns(tmp_path: Path) -> None:
    _write(tmp_path, "input/samplesheet.csv", "group_id,sample_id\nG1,S1\n")
    with pytest.raises(ValueError, match="missing required column"):
        execute_recipe("nf-core/oncoanalyser/samples.py", tmp_path, pipeline_version="3.0.0")


# ---------------------------------------------------------------------------
# PURPLE
# ---------------------------------------------------------------------------

PURITY_COLS = [
    "purity", "normFactor", "score", "diploidProportion", "ploidy", "gender", "status",
    "polyclonalProportion", "minPurity", "maxPurity", "minPloidy", "maxPloidy",
    "wholeGenomeDuplication", "msIndelsPerMb", "msStatus", "tml", "tmlStatus", "tmbPerMb",
    "tmbStatus", "svTumorMutationalBurden", "runMode",
]  # fmt: skip


def _purple_run(root: Path, sample: str = TUMOR) -> None:
    row = [
        "0.8000", "0.7", "1.2", "0.1", "3.1000", "FEMALE", "SOMATIC", "0.05", "0.7", "0.9", "2.9",
        "3.3", "true", "0.0965", "MSS", "349", "HIGH", "14.84", "HIGH", "1295", "TUMOR_GERMLINE",
    ]  # fmt: skip
    _write(root, f"G1/purple/{sample}.purple.purity.tsv", _tsv(PURITY_COLS, [row]))
    qc = [
        ("QCStatus", "PASS"), ("Method", "SOMATIC"), ("CopyNumberSegments", "120"),
        ("UnsupportedCopyNumberSegments", "2"), ("DeletedGenes", "7"), ("Contamination", "0.0100"),
        ("GermlineAberrations", "NONE"), ("AmberMeanDepth", "89"), ("LohPercent", "0.5243"),
        ("TincLevel", "0.0000"), ("Purity", "0.8"),
    ]  # fmt: skip
    _write(root, f"G1/purple/{sample}.purple.qc", "".join(f"{k}\t{v}\n" for k, v in qc))


def test_purity_joins_the_fit_and_the_qc_verdict(tmp_path: Path) -> None:
    _purple_run(tmp_path)
    out = execute_recipe("purple/purity.py", tmp_path)
    assert out.height == 1
    row = out.row(0, named=True)
    # Dots in the sample id stay in it: the id is the file name before `.purple.`.
    assert row["sample"] == TUMOR
    assert row["purity"] == pytest.approx(0.8)
    assert row["ploidy"] == pytest.approx(3.1)
    assert row["fit_status"] == "SOMATIC"
    assert row["whole_genome_duplication"] is True
    assert row["tml"] == 349
    assert row["sv_tmb"] == 1295
    assert row["qc_status"] == "PASS"
    assert row["cn_segments"] == 120
    assert row["deleted_genes"] == 7
    assert row["loh_fraction"] == pytest.approx(0.5243)


def test_purity_keeps_one_row_per_tumor(tmp_path: Path) -> None:
    _purple_run(tmp_path, "T1.tumor_dna")
    _purple_run(tmp_path, "T2.tumor_dna")
    out = execute_recipe("purple/purity.py", tmp_path)
    assert out["sample"].to_list() == ["T1.tumor_dna", "T2.tumor_dna"]


def test_cnv_segments_land_on_the_canonical_profile(tmp_path: Path) -> None:
    cols = ["chromosome", "start", "end", "copyNumber", "baf", "depthWindowCount",
            "minorAlleleCopyNumber", "majorAlleleCopyNumber"]  # fmt: skip
    rows = [
        ["chr1", 1, 1000, "2.0", "0.5", 10, "1.0", "1.0"],
        ["chr1", 1001, 2000, "4.3", "1.0", 5, "0.0", "4.3"],
        ["chr2", 1, 500, "0.0", "0.0", 3, "0.0", "0.0"],
    ]
    _write(tmp_path, f"G1/purple/{TUMOR}.purple.cnv.somatic.tsv", _tsv(cols, rows))
    out = execute_recipe("purple/cnv_segments.py", tmp_path)
    assert out.height == 3
    by_start = {(r["chrom"], r["start"]): r for r in out.iter_rows(named=True)}
    diploid = by_start[("chr1", 1)]
    assert diploid["sample"] == TUMOR
    assert diploid["log2"] == pytest.approx(0.0)
    assert diploid["copy_number"] == 2
    gain = by_start[("chr1", 1001)]
    assert gain["log2"] == pytest.approx(1.1, abs=0.01)
    assert gain["copy_number"] == 4
    assert gain["minor_copy_number"] == 0.0
    assert gain["major_copy_number"] == pytest.approx(4.3)
    assert gain["label"] == "4.3 = 4.3 + 0.0"
    # A homozygous deletion has no finite log2: it is clamped, not dropped.
    assert by_start[("chr2", 1)]["log2"] is not None


GENE_COLS = ["chromosome", "start", "end", "gene", "minCopyNumber", "maxCopyNumber",
             "somaticRegions", "transcriptId", "isCanonical", "chromosomeBand",
             "minMinorAlleleCopyNumber", "relativeMinCopyNumber", "reportedStatus",
             "driverType"]  # fmt: skip


def _gene(gene: str, lo: float, hi: float, minor: float, rel: float, canonical: str = "true"):
    return ["chr1", 1, 100, gene, lo, hi, 1, f"ENST_{gene}", canonical, "p1", minor, rel, "NONE",
            "UNKNOWN"]  # fmt: skip


def test_gene_copy_number_calls_follow_the_purple_cut_offs(tmp_path: Path) -> None:
    # Ploidy 2: the gene minimum over 6 is an amplification, a maximum over 6 a partial one.
    rows = [
        _gene("AMPG", 9.0, 9.0, 1.0, 4.5),
        _gene("PAMPG", 2.0, 8.0, 1.0, 1.0),
        _gene("DELG", 0.1, 0.2, 0.0, 0.05),
        _gene("PDELG", 0.2, 2.0, 0.0, 0.1),
        _gene("LOHG", 1.8, 1.8, 0.1, 0.9),
        _gene("NEUTG", 2.0, 2.0, 1.0, 1.0),
        _gene("NEUTG", 2.0, 2.0, 1.0, 1.0, canonical="false"),
    ]
    _write(tmp_path, f"G1/purple/{TUMOR}.purple.cnv.gene.tsv", _tsv(GENE_COLS, rows))
    out = execute_recipe("purple/gene_copy_number.py", tmp_path)
    events = dict(zip(out["gene"], out["cn_event"], strict=True))
    assert events == {
        "AMPG": "AMP",
        "PAMPG": "PARTIAL_AMP",
        "DELG": "DEL",
        "PDELG": "PARTIAL_DEL",
        "LOHG": "LOH",
        "NEUTG": "NEUTRAL",
    }
    # Only the canonical transcript is kept: one row per gene.
    assert out.height == 6
    assert out["sample"].unique().to_list() == [TUMOR]


DRIVER_COLS = ["chromosome", "chromosomeBand", "gene", "transcript", "isCanonical", "driver",
               "category", "likelihoodMethod", "reportedStatus", "driverLikelihood", "missense",
               "nonsense", "splice", "inframe", "frameshift", "biallelic", "minCopyNumber",
               "maxCopyNumber"]  # fmt: skip


def _driver(gene: str, driver: str, status: str = "REPORTED", likelihood: str = "1.0000"):
    return ["chr1", "p1", gene, f"ENST_{gene}", "true", driver, "TSG", "DNDS", status, likelihood,
            1, 0, 0, 0, 0, "true", "2.0", "2.0"]  # fmt: skip


def test_drivers_merge_purple_and_linx_without_doubling(tmp_path: Path) -> None:
    purple = [
        _driver("G1", "MUTATION"),
        _driver("G2", "LOH", status="NOT_REPORTED", likelihood="0.5"),
    ]
    linx = [
        _driver("G1", "MUTATION"),  # PURPLE already lists it
        _driver("G3", "DISRUPTION"),  # LINX's own structural driver
    ]
    germline = [_driver("G4", "GERMLINE_MUTATION")]
    base = f"G1/purple/{TUMOR}.purple.driver.catalog"
    _write(tmp_path, f"{base}.somatic.tsv", _tsv(DRIVER_COLS, purple))
    _write(tmp_path, f"{base}.germline.tsv", _tsv(DRIVER_COLS, germline))
    _write(tmp_path, f"G1/linx/{TUMOR}.linx.driver.catalog.tsv", _tsv(DRIVER_COLS, linx))
    out = execute_recipe("purple/drivers.py", tmp_path)
    rows = {(r["gene"], r["driver"]): r for r in out.iter_rows(named=True)}
    assert set(rows) == {
        ("G1", "MUTATION"),
        ("G2", "LOH"),
        ("G3", "DISRUPTION"),
        ("G4", "GERMLINE_MUTATION"),
    }
    assert rows[("G1", "MUTATION")]["source_tool"] == "PURPLE"
    assert rows[("G3", "DISRUPTION")]["source_tool"] == "LINX"
    assert rows[("G4", "GERMLINE_MUTATION")]["origin"] == "germline"
    assert rows[("G2", "LOH")]["reported"] is False
    assert rows[("G2", "LOH")]["report_status"] == "NOT_REPORTED"
    assert rows[("G1", "MUTATION")]["driver_id"] == f"{TUMOR}|G1|MUTATION"
    # Reported drivers first.
    assert out["reported"].to_list()[0] is True


VCF_HEADER = (
    "##fileformat=VCFv4.2\n"
    '##INFO=<ID=IMPACT,Number=.,Type=String,Description="x">\n'
    f"#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\t{NORMAL}\t{TUMOR}\n"
)


def _vcf_line(chrom: str, pos: int, ref: str, alt: str, flt: str, info: str, tumor: str) -> str:
    return "\t".join(
        [chrom, str(pos), ".", ref, alt, "200", flt, info, "GT:AD:AF:DP", "0/0:30,0:0.00:30", tumor]
    )


SOMATIC_VCF = (
    VCF_HEADER
    + "\n".join(
        [
            _vcf_line(
                "chr7",
                140453136,
                "A",
                "T",
                "PASS",
                "BIALLELIC;HOTSPOT;REPORTED;TIER=HOTSPOT;PURPLE_AF=0.9400;PURPLE_CN=3.1;"
                "PURPLE_VCN=2.9;PURPLE_MACN=1.1;SUBCL=0.01;TNC=GAT;"
                "IMPACT=BRAF,ENST00000288602,missense_variant,MISSENSE,false,c.1799T>A,"
                "p.Val600Glu,,MISSENSE,1",
                "0/1:40,60:0.60:100",
            ),
            _vcf_line(
                "chr1",
                100,
                "AC",
                "A",
                "PASS",
                "TIER=PANEL;PURPLE_AF=0.3000;IMPACT=GENE1,ENST1,frameshift_variant,"
                "NONSENSE_OR_FRAMESHIFT,false,c.10del,p.Thr4fs,,NONSENSE_OR_FRAMESHIFT,1",
                "0/1:70,30:0.30:100",
            ),
            _vcf_line(
                "chr2",
                5,
                "G",
                "A",
                "PON",
                "TIER=LOW_CONFIDENCE;IMPACT=,,,NONE,false,,,,NONE,1",
                "0/1:70,30:0.30:100",
            ),
            _vcf_line(
                "chr3",
                50,
                "CA",
                "TG",
                "PASS",
                "TIER=HIGH_CONFIDENCE;PURPLE_AF=0.5000",
                "0/1:50,50:0.50:100",
            ),
        ]
    )
    + "\n"
)


def _somatic_calls(tmp_path: Path) -> pl.DataFrame:
    _write(tmp_path, f"G1/purple/{TUMOR}.purple.somatic.vcf.gz", SOMATIC_VCF)
    return execute_recipe("purple/somatic_variants.py", tmp_path)


def test_somatic_variants_keep_pass_calls_with_their_impact(tmp_path: Path) -> None:
    out = _somatic_calls(tmp_path)
    # The PON call is dropped.
    assert out.height == 3
    rows = {r["variant_key"]: r for r in out.iter_rows(named=True)}
    braf = rows["chr7:140453136:A:T"]
    assert braf["sample"] == TUMOR
    assert braf["variant_type"] == "SNV"
    assert braf["gene"] == "BRAF"
    assert braf["coding_effect"] == "MISSENSE"
    assert braf["hgvs_p"] == "p.Val600Glu"
    # The tumor is the last sample column.
    assert braf["tumor_af"] == pytest.approx(0.6)
    assert braf["tumor_depth"] == 100
    assert braf["tumor_alt_reads"] == 60
    assert braf["purple_af"] == pytest.approx(0.94)
    assert braf["variant_copy_number"] == pytest.approx(2.9)
    assert braf["biallelic"] and braf["hotspot"] and braf["reported"]
    assert braf["tier"] == "HOTSPOT"
    assert rows["chr1:100:AC:A"]["variant_type"] == "INDEL"
    assert rows["chr3:50:CA:TG"]["variant_type"] == "MNV"
    # No IMPACT: no gene, and the flags default to false.
    assert rows["chr3:50:CA:TG"]["gene"] is None
    assert rows["chr3:50:CA:TG"]["hotspot"] is False


def test_protein_changes_split_the_hgvs_protein_change(tmp_path: Path) -> None:
    calls = _somatic_calls(tmp_path)
    extra = pl.DataFrame(
        {
            c: [calls[c][0]] * 3
            if c not in ("gene", "hgvs_p", "coding_effect", "variant_key")
            else None
            for c in calls.columns
        },
        schema=calls.schema,
    ).with_columns(
        pl.Series("gene", ["GA", "GB", "GC"]),
        pl.Series("hgvs_p", ["p.Glu1608=", "p.Arg5Ter", "p.?"]),
        pl.Series("coding_effect", ["SYNONYMOUS", "NONSENSE_OR_FRAMESHIFT", "SPLICE"]),
        pl.Series("variant_key", ["a", "b", "c"]),
    )
    out = execute_recipe(
        "purple/protein_changes.py",
        tmp_path,
        extra_sources={"variants": pl.concat([calls, extra])},
    )
    rows = {r["entity"]: r for r in out.iter_rows(named=True)}
    # The splice call with no residue and the call with no protein change are dropped.
    assert set(rows) == {"BRAF", "GENE1", "GA", "GB"}
    braf = rows["BRAF"]
    assert (braf["position"], braf["ref_aa"], braf["alt_aa"]) == (600, "V", "E")
    assert braf["label"] == "p.V600E"
    assert braf["category"] == "MISSENSE"
    assert braf["value"] == pytest.approx(0.94)
    # A frameshift names no new residue.
    gene1 = rows["GENE1"]
    assert gene1["position"] == 4
    assert gene1["ref_aa"] == "T"
    assert gene1["alt_aa"] is None
    # A synonymous change keeps the reference residue, a stop is `*`.
    assert (rows["GA"]["ref_aa"], rows["GA"]["alt_aa"]) == ("E", "E")
    assert rows["GA"]["label"] == "p.E1608="
    assert rows["GB"]["alt_aa"] == "*"


def _changes() -> pl.DataFrame:
    rows = [
        ("GENE1", "T1", "MISSENSE", 0.40, True),
        ("GENE1", "T1", "NONSENSE_OR_FRAMESHIFT", 0.35, False),
        ("GENE2", "T1", "SYNONYMOUS", 0.10, None),
        ("GENE1", "T2", "MISSENSE", 0.20, False),
    ]
    return pl.DataFrame(
        rows,
        schema={
            "entity": pl.Utf8,
            "sample": pl.Utf8,
            "category": pl.Utf8,
            "value": pl.Float64,
            "hotspot": pl.Boolean,
        },
        orient="row",
    )


def _drivers() -> pl.DataFrame:
    rows = [
        ("GENE1", "T1", "MUTATION", "somatic", "TSG", 0.9, True),
        ("GENE1", "T1", "LOH", "somatic", "TSG", 1.0, True),
        ("GENE1", "T1", "GERMLINE_MUTATION", "germline", "TSG", 1.0, True),
        ("GENE2", "T1", "AMP", "somatic", "ONCO", 1.0, False),
    ]
    return pl.DataFrame(
        rows,
        schema={
            "gene": pl.Utf8,
            "sample": pl.Utf8,
            "driver": pl.Utf8,
            "origin": pl.Utf8,
            "category": pl.Utf8,
            "driver_likelihood": pl.Float64,
            "reported": pl.Boolean,
        },
        orient="row",
    )


def _protein_genes(sources: dict[str, pl.DataFrame | None]) -> pl.DataFrame:
    module = load_recipe("nf-core/oncoanalyser/protein_genes.py", "3.0.0")
    out = module.transform(sources)
    validate_schema(out, module.OUTPUT_SCHEMA, "protein_genes", module.OPTIONAL_OUTPUT_SCHEMA)
    return out


def test_protein_genes_fold_per_tumor_and_gene() -> None:
    out = _protein_genes({"changes": _changes(), "drivers": _drivers()})
    rows = {(r["entity"], r["sample"]): r for r in out.iter_rows(named=True)}
    assert set(rows) == {("GENE1", "T1"), ("GENE2", "T1"), ("GENE1", "T2")}

    g1 = rows[("GENE1", "T1")]
    assert g1["changes"] == 2
    assert g1["hotspots"] == 1
    assert g1["max_af"] == 0.40
    assert g1["worst_effect"] == "NONSENSE_OR_FRAMESHIFT"
    # The MUTATION row's likelihood, not the LOH one; germline rows ignored.
    assert g1["driver_likelihood"] == 0.9
    assert g1["gene_role"] == "TSG"
    assert g1["driver_types"] == "LOH, MUTATION"
    assert g1["reported"] is True

    # A driver without a MUTATION row keeps the gene at likelihood 0.
    g2 = rows[("GENE2", "T1")]
    assert g2["driver_likelihood"] == 0.0
    assert g2["gene_role"] == "ONCO"
    assert g2["reported"] is False

    # Not in the catalog for that tumor.
    other = rows[("GENE1", "T2")]
    assert other["driver_likelihood"] == 0.0
    assert other["gene_role"] == "unlisted"
    assert other["driver_types"] == ""

    # Driver candidates first.
    assert out.row(0, named=True)["entity"] == "GENE1"
    assert out.row(0, named=True)["sample"] == "T1"


def test_protein_genes_without_a_driver_catalog() -> None:
    out = _protein_genes({"changes": _changes(), "drivers": None})
    assert out.height == 3
    assert out["driver_likelihood"].to_list() == [0.0, 0.0, 0.0]
    assert set(out["gene_role"].to_list()) == {"unlisted"}


# ---------------------------------------------------------------------------
# LINX
# ---------------------------------------------------------------------------

SV_COLS = ["vcfIdStart", "vcfIdEnd", "svId", "coordsStart", "coordsEnd", "type", "clusterId",
           "fragileSiteStart", "fragileSiteEnd", "isFoldback", "lineTypeStart", "lineTypeEnd",
           "junctionCopyNumberMin", "junctionCopyNumberMax", "geneStart", "geneEnd"]  # fmt: skip


def _linx_svs(root: Path) -> None:
    rows = [
        [1, 2, 0, "chr1:100:-1", "chr1:900:1", "DEL", 7, "false", "false", "false", "NONE", "NONE",
         "0.5", "1.5", "AAA", "", ],
        [3, 4, 1, "chr1:5000:1", "chr2:70:-1", "BND", 8, "true", "false", "false", "NONE", "LINE",
         "1.0", "1.0", "", "BBB"],
        [5, 5, 2, "chr3:42:1", "", "SGL", 9, "false", "false", "false", "NONE", "NONE", "2", "2",
         "", ""],
    ]  # fmt: skip
    _write(root, f"G1/linx/somatic_annotations/{TUMOR}.linx.svs.tsv", _tsv(SV_COLS, rows))
    clusters = [[7, "SIMPLE", "false", "DEL", 1, "DEL"], [8, "COMPLEX", "false", "COMPLEX", 3, ""],
                [9, "INCOMPLETE", "false", "SGL", 1, "SGL"]]  # fmt: skip
    _write(
        root,
        f"G1/linx/somatic_annotations/{TUMOR}.linx.clusters.tsv",
        _tsv(
            ["clusterId", "category", "synthetic", "resolvedType", "clusterCount", "clusterDesc"],
            clusters,
        ),
    )


def test_linx_svs_split_breakends_and_join_the_cluster(tmp_path: Path) -> None:
    _linx_svs(tmp_path)
    out = execute_recipe("linx/svs.py", tmp_path)
    rows = {r["sv_id"]: r for r in out.iter_rows(named=True)}
    deletion = rows[0]
    assert deletion["sample"] == TUMOR
    assert (deletion["chrom_a"], deletion["pos_a"], deletion["orient_a"]) == ("chr1", 100, -1)
    assert (deletion["chrom_b"], deletion["pos_b"], deletion["orient_b"]) == ("chr1", 900, 1)
    assert deletion["length"] == 800
    assert deletion["junction_copy_number"] == pytest.approx(1.0)
    assert deletion["resolved_type"] == "DEL"
    assert deletion["cluster_category"] == "SIMPLE"
    assert deletion["sv_key"] == f"{TUMOR}|0"
    assert deletion["label"] == "DEL #0"
    translocation = rows[1]
    assert translocation["length"] is None
    assert translocation["fragile_site"] is True
    assert translocation["line_element"] is True
    assert translocation["cluster_sv_count"] == 3
    # A single breakend has no partner locus, so a chord diagram skips it.
    assert rows[2]["chrom_b"] is None
    assert rows[2]["pos_b"] is None


FUSION_COLS = ["fivePrimeBreakendId", "threePrimeBreakendId", "name", "reported", "reportedType",
               "reportableReasons", "phased", "likelihood", "fivePrimeCoords", "threePrimeCoords",
               "chainLength", "chainLinks", "chainTerminated", "domainsKept", "domainsLost",
               "skippedExonsUp", "skippedExonsDown", "fusedExonUp", "fusedExonDown"]  # fmt: skip
BREAKEND_COLS = ["id", "svId", "gene", "transcriptId", "regionType", "totalExonCount"]


def _linx_fusions(root: Path) -> None:
    fusions = [
        [10, 11, "GA_GB", "true", "KNOWN_PAIR", "OK", "INFRAME", "HIGH", "chr1:1:-1", "chr2:2:1",
         1, 1, "false", "kinase", "", 0, 0, 3, 2],
        [12, 13, "GC_GD", "false", "NONE", "NOT_KNOWN", "OUT_OF_FRAME", "NA", "chr3:1:-1",
         "chr4:2:1", 0, 0, "false", "", "", 0, 0, 1, 1],
    ]  # fmt: skip
    breakends = [[10, 1, "GA", "ENST_GA", "INTRONIC", 10], [11, 1, "GB", "ENST_GB", "INTRONIC", 8],
                 [12, 2, "GC", "ENST_GC", "INTRONIC", 5], [13, 2, "GD", "ENST_GD", "INTRONIC", 6]]  # fmt: skip
    base = f"G1/linx/somatic_annotations/{TUMOR}.linx"
    _write(root, f"{base}.fusion.tsv", _tsv(FUSION_COLS, fusions))
    _write(root, f"{base}.breakend.tsv", _tsv(BREAKEND_COLS, breakends))


def test_linx_fusions_resolve_both_partners(tmp_path: Path) -> None:
    _linx_fusions(tmp_path)
    out = execute_recipe("linx/fusions.py", tmp_path)
    assert out["fusion"].to_list() == ["GA_GB", "GC_GD"]  # reported first
    first = out.row(0, named=True)
    assert first["fusion_id"] == f"{TUMOR}|10|11"
    assert (first["gene_up"], first["gene_down"]) == ("GA", "GB")
    assert first["reported"] is True
    assert (first["exons_up_total"], first["exons_down_total"]) == (10, 8)
    assert (first["fused_exon_up"], first["fused_exon_down"]) == (3, 2)
    assert first["domains_kept"] == "kinase"
    assert out.row(1, named=True)["domains_kept"] is None


def test_fusion_structure_draws_kept_and_lost_exons(tmp_path: Path) -> None:
    _linx_fusions(tmp_path)
    fusions = execute_recipe("linx/fusions.py", tmp_path)
    out = execute_recipe("linx/fusion_structure.py", tmp_path, extra_sources={"fusions": fusions})
    ga = out.filter(pl.col("fusion") == "GA_GB").sort("start")
    kept = ga.filter(pl.col("retained") == 1.0)
    # The 5' partner keeps exons 1..3 (0 to 3); the 3' partner keeps 2..8 from the breakpoint on.
    spans = {(r["partner"], r["start"], r["end"]) for r in kept.iter_rows(named=True)}
    assert ("5' GA", 0.0, 3.0) in spans
    assert ("3' GB", 3.0, 10.0) in spans
    assert set(ga["breakpoint"]) == {3.0}
    lost = ga.filter(pl.col("retained") == 0.0)
    # The 5' exons 4..10 are lost after the breakpoint, the 3' exon 1 before it.
    assert ("5' GA", 3.0, 10.0) in {
        (r["partner"], r["start"], r["end"]) for r in lost.iter_rows(named=True)
    }
    assert out["fusion_id"].n_unique() == 2


# ---------------------------------------------------------------------------
# CUPPA, SIGS, LILAC, Neo, QSEE, BamTools
# ---------------------------------------------------------------------------


def _cuppa(root: Path) -> None:
    cols = ["sample_id", "data_type", "clf_group", "clf_name", "feat_name", "feat_value",
            "cancer_type", "data_value", "rank", "rank_group"]  # fmt: skip
    rows = [
        [TUMOR, "prob", "combined", "combined", "", "", "Lung", "0.7", 1, 1],
        [TUMOR, "prob", "combined", "combined", "", "", "Breast", "0.2", 2, 2],
        [TUMOR, "prob", "dna", "snv96", "", "", "Lung", "0.5", 1, 1],
        [TUMOR, "prob", "dna", "snv96", "", "", "Breast", "0.4", 2, 2],
        [TUMOR, "feat_contrib", "dna", "snv96", "SNV_A", "0.1", "Lung", "0.01", "", ""],
    ]
    _write(root, f"G1/cuppa/{TUMOR}.cuppa.vis_data.tsv", _tsv(cols, rows))


def test_cuppa_predictions_keep_only_probability_rows(tmp_path: Path) -> None:
    _cuppa(tmp_path)
    out = execute_recipe("cuppa/predictions.py", tmp_path)
    assert out.height == 4
    top = out.filter(pl.col("is_top"))
    assert set(zip(top["classifier"], top["cancer_type"], strict=True)) == {
        ("combined", "Lung"),
        ("snv96", "Lung"),
    }
    assert out.filter(pl.col("classifier") == "combined")["probability"].sum() == pytest.approx(0.9)


def test_cuppa_matrix_has_one_column_per_classifier(tmp_path: Path) -> None:
    _cuppa(tmp_path)
    out = execute_recipe("cuppa/classifier_matrix.py", tmp_path)
    assert out.height == 2
    assert {"combined", "snv96"} <= set(out.columns)
    lung = out.filter(pl.col("cancer_type") == "Lung").row(0, named=True)
    assert lung["combined"] == pytest.approx(0.7)
    assert lung["snv96"] == pytest.approx(0.5)
    # One tumor: the row label is the cancer type alone.
    assert lung["row_label"] == "Lung"
    assert out["combined"].to_list()[0] == pytest.approx(0.7)  # most likely first


def test_sigs_allocation_keeps_the_unexplained_share(tmp_path: Path) -> None:
    # SIGS writes the share as a 0 to 1 fraction under `percent`.
    rows = [["Sig3", 600.0, 0.6], ["MISALLOC", 400.0, 0.4]]
    _write(
        tmp_path,
        f"G1/sigs/{TUMOR}.sig.allocation.tsv",
        _tsv(["signature", "allocation", "percent"], rows),
    )
    out = execute_recipe("sigs/allocation.py", tmp_path)
    assert out["signature"].to_list() == ["Sig3", "MISALLOC"]
    assert out["sample"].unique().to_list() == [TUMOR]
    assert out["allocation"].sum() == pytest.approx(1000.0)
    assert out["fraction"].to_list() == pytest.approx([0.6, 0.4])
    assert out["percent"].to_list() == pytest.approx([60.0, 40.0])


LILAC_COLS = ["Allele", "Genes", "RefTotal", "RefUnique", "TumorTotal", "RnaTotal",
              "TumorCopyNumber", "SomaticMissense", "SomaticNonsenseOrFrameshift",
              "SomaticSplice", "SomaticInframeIndel", "SomaticSynonymous"]  # fmt: skip


def test_lilac_alleles_flag_loss_and_number_homozygous_copies(tmp_path: Path) -> None:
    rows = [
        ["A*01:01", "MHC_CLASS_1", 50, 20, 40, 0, "0.30", 0, 0, 0, 0, 0],
        ["A*01:01", "MHC_CLASS_1", 50, 20, 40, 0, "1.80", 1, 0, 0, 0, 2],
        ["DPA1*02:01", "HLA_DPA1", 10, 5, 8, 0, "2.0", 0, 0, 0, 0, 0],
    ]
    _write(tmp_path, f"G1/lilac/{TUMOR}.lilac.tsv", _tsv(LILAC_COLS, rows))
    out = execute_recipe("lilac/alleles.py", tmp_path)
    assert out.height == 3
    # A homozygous gene lists the same allele twice: the record key numbers the copies.
    assert out["allele_id"].n_unique() == 3
    lost = out.filter(pl.col("lost_in_tumor"))
    assert lost.height == 1
    assert lost["tumor_copy_number"].item() == pytest.approx(0.3)
    assert "HLA-DPA1" in out["gene"].to_list()
    mutated = out.filter(pl.col("somatic_missense") == 1.0)
    # Synonymous variants do not count as mutations of the allele.
    assert mutated["somatic_mutations"].item() == 1.0


def test_neo_neoepitopes_key_by_tumor_and_id(tmp_path: Path) -> None:
    cols = ["NeId", "VariantType", "VariantInfo", "GeneName", "UpAminoAcids", "NovelAminoAcids",
            "DownAminoAcids", "PeptideCount", "RnaFrags", "RnaDepth", "ExpectedTpm",
            "EffectiveTpm", "VariantCopyNumber", "CopyNumber", "SubclonalLikelihood"]  # fmt: skip
    rows = [[0, "MISSENSE", "chr1:1:A:T", "GENE1", "KL", "V", "RS", 12, 20, 100, "3.5", "2.5", "1.2",
             "2.0", "0.0"], [1, "FRAMESHIFT", "chr2:2:AC:A", "GENE2", "", "WWW", "", 4, 0, 0, "0",
             "0", "0.9", "2.0", "0.1"]]  # fmt: skip
    _write(tmp_path, f"G1/neo/scorer/{TUMOR}.neo.neoepitope.tsv", _tsv(cols, rows))
    out = execute_recipe("neo/neoepitopes.py", tmp_path)
    rows_by_id = {r["neoepitope_id"]: r for r in out.iter_rows(named=True)}
    assert set(rows_by_id) == {f"{TUMOR}|0", f"{TUMOR}|1"}
    first = rows_by_id[f"{TUMOR}|0"]
    assert first["peptides"] == 12
    assert first["effective_tpm"] == pytest.approx(2.5)
    # An empty flank is missing, not an empty string.
    assert rows_by_id[f"{TUMOR}|1"]["up_amino_acids"] is None


def test_qsee_status_reads_the_gzipped_verdicts(tmp_path: Path) -> None:
    cols = ["SampleId", "SampleType", "SourceTool", "FeatureType", "FeatureName", "FeatureValue",
            "QcStatus", "FailCondition"]  # fmt: skip
    rows = [
        [TUMOR, "TUMOR", "PURPLE", "SAMPLE", "Purity", "0.8", "PASS", ""],
        [TUMOR, "TUMOR", "BAM_METRICS", "SAMPLE", "MeanCoverage", "25", "WARN", "<30"],
    ]
    _write(tmp_path, f"G1/qsee/{TUMOR}.qsee.status.tsv.gz", _tsv(cols, rows))
    out = execute_recipe("qsee/status.py", tmp_path)
    assert out.height == 2
    warn = out.filter(pl.col("qc_status") == "WARN").row(0, named=True)
    assert warn["check_id"] == f"{TUMOR}|BAM_METRICS|MeanCoverage"
    assert warn["sample_type"] == "tumor"
    assert warn["value"] == 25.0
    assert warn["fail_condition"] == "<30"
    assert out.filter(pl.col("qc_status") == "PASS")["fail_condition"].item() is None


def test_bamtools_summary_names_the_depth_thresholds(tmp_path: Path) -> None:
    cols = ["TotalRegionBases", "TotalReads", "DuplicateReads", "DualStrandReads", "MeanCoverage",
            "StdDevCoverage", "MedianCoverage", "MadCoverage", "LowMapQualPercent",
            "DuplicatePercent", "UnmappedPercent", "LowBaseQualPercent", "OverlappingReadPercent",
            "CappedCoverage", "DepthCoverage_10", "DepthCoverage_20", "DepthCoverage_30",
            "DepthCoverage_60", "DepthCoverage_100"]  # fmt: skip
    row = [3e9, 1e9, 3e7, 0, 40.5, 12.0, 41, 8, 0.01, 0.03, 0.002, 0.004, 0.2, 0.0, 0.99, 0.95,
           0.82, 0.05, 0.0]  # fmt: skip
    _write(
        tmp_path,
        f"G1/bamtools/{NORMAL}/{NORMAL}.bam_metric.summary.tsv",
        _tsv(cols, [row]),
    )
    out = execute_recipe("hmf_bamtools/summary.py", tmp_path)
    assert out.height == 1
    got = out.row(0, named=True)
    assert got["sample"] == NORMAL
    assert got["mean_coverage"] == pytest.approx(40.5)
    assert got["frac_ge_30x"] == pytest.approx(0.82)
    assert got["frac_ge_100x"] == pytest.approx(0.0)
    assert got["total_reads"] == 1_000_000_000
    # A depth BamTools does not report is absent, not a failure.
    assert "frac_ge_1x" not in out.columns


def test_bamtools_coverage_is_cumulative_from_the_right(tmp_path: Path) -> None:
    rows = [[0, 100], [1, 300], [2, 600]]
    _write(
        tmp_path,
        f"G1/bamtools/{TUMOR}/{TUMOR}.bam_metric.coverage.tsv",
        _tsv(["Coverage", "Count"], rows),
    )
    out = execute_recipe("hmf_bamtools/coverage_profile.py", tmp_path).sort("coverage")
    assert out["coverage"].to_list() == [0, 1, 2]
    assert out["fraction"].to_list() == pytest.approx([0.1, 0.3, 0.6])
    assert out["fraction_at_least"].to_list() == pytest.approx([1.0, 0.9, 0.6])


def test_bamtools_fragment_length_is_a_share_of_the_pairs(tmp_path: Path) -> None:
    rows = [[100, 10], [200, 30], [300, 60]]
    _write(
        tmp_path,
        f"G1/bamtools/{TUMOR}/{TUMOR}.bam_metric.frag_length.tsv",
        _tsv(["FragmentLength", "Count"], rows),
    )
    out = execute_recipe("hmf_bamtools/fragment_length.py", tmp_path)
    assert out["sample"].unique().to_list() == [TUMOR]
    assert out["fraction"].sum() == pytest.approx(1.0)
    assert out["pairs"].sum() == 100


TOOL_RECIPES = [
    "purple/purity.py",
    "purple/cnv_segments.py",
    "purple/gene_copy_number.py",
    "purple/drivers.py",
    "purple/somatic_variants.py",
    "purple/protein_changes.py",
    "linx/svs.py",
    "linx/fusions.py",
    "linx/fusion_structure.py",
    "cuppa/predictions.py",
    "cuppa/classifier_matrix.py",
    "sigs/allocation.py",
    "lilac/alleles.py",
    "neo/neoepitopes.py",
    "qsee/status.py",
    "hmf_bamtools/summary.py",
    "hmf_bamtools/coverage_profile.py",
    "hmf_bamtools/fragment_length.py",
]


@pytest.mark.parametrize("ref", [*TOOL_RECIPES, "nf-core/oncoanalyser/protein_genes.py"])
def test_every_source_names_the_columns_it_reads(ref: str) -> None:
    module = load_recipe(ref, "3.0.0" if ref.startswith("nf-core/") else None)
    assert module.SOURCES
    assert all(source.input_schema for source in module.SOURCES), ref
