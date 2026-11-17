"""nf-core/raredisease mitochondrial variants: one row per variant and sample with a call.

The mitochondrial branch calls with Mutect2 in mitochondrial mode (one VCF per
family), annotates it with VEP, vcfanno (gnomAD mitochondrial frequencies, MitoTip
tRNA scores) and GENMOD, and publishes it under ``rank_and_filter/`` as
``<family>_mt_ranked_research.vcf.gz`` and ``<family>_mt_ranked_clinical.vcf.gz``
(the clinical one is the subset passing the clinical filters). Each variant
appears once here; ``is_clinical`` marks the clinical subset.

The number that matters on a mitochondrial call is its heteroplasmy: the share of
the sample's mtDNA copies carrying the variant, Mutect2's per-sample ``AF``. A
sample counts as called when its ``AF`` is a number above zero (a sample the
caller did not reach writes ``./.`` and ``.``). ``heteroplasmy_class`` follows
gnomAD's mitochondrial thresholds: homoplasmic at 0.95 or above, heteroplasmic
from 0.10, low level below.

Sources:
    raw  every ``rank_and_filter/*_mt_ranked_*.vcf.gz``, one VCF line per row

Output schema (a field a record does not carry is null):
    variant_key : Utf8        chrom:pos:ref:alt
    sample : Utf8
    chrom, pos, end, ref, alt, variant_type, filter_status
    gt : Utf8                 the sample's genotype as written
    heteroplasmy : Float64    Mutect2 AF, 0 to 1
    heteroplasmy_class : Utf8 Homoplasmic / Heteroplasmic / Low level
    dp : Int64                sample depth at the variant
    alt_depth : Int64         reads supporting the alternate allele
    gene : Utf8               the gene or tRNA, null in an intergenic or control-region call
    consequence : Utf8        most severe VEP term
    impact : Utf8
    rank_score : Float64      GENMOD rank score of the family
    model_class : Utf8        Compound heterozygous / Recessive / Dominant / X-linked / No model fits
    mitotip_score : Float64   MitoTip raw score of a tRNA variant
    mitotip_prediction : Utf8 MitoTip interpretation
    gnomad_mt_het : Float64   gnomAD mitochondrial frequency, heteroplasmic carriers
    gnomad_mt_hom : Float64   gnomAD mitochondrial frequency, homoplasmic carriers
    is_clinical : Boolean
    call_label : Utf8         gene and position, for the browser
"""

from __future__ import annotations

import re

import polars as pl

from depictio.models.models.transforms import RecipeSource

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="raw",
        glob_pattern="rank_and_filter/*_mt_ranked_*.vcf.gz",
        format="csv",
        # One full VCF line per row: no separator, quote or header can occur in it.
        read_kwargs={
            "separator": "\x1e",
            "has_header": False,
            "new_columns": ["raw_line"],
            "quote_char": None,
            "infer_schema_length": 0,
        },
        source_path="source_path",
        input_schema={"raw_line": pl.Utf8, "source_path": pl.Utf8},
        # A run without the mitochondrial analysis publishes none of these files.
        optional=True,
    )
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "variant_key": pl.Utf8,
    "sample": pl.Utf8,
    "chrom": pl.Utf8,
    "pos": pl.Int64,
    "end": pl.Int64,
    "ref": pl.Utf8,
    "alt": pl.Utf8,
    "variant_type": pl.Utf8,
    "filter_status": pl.Utf8,
    "gt": pl.Utf8,
    "heteroplasmy": pl.Float64,
    "heteroplasmy_class": pl.Utf8,
    "dp": pl.Int64,
    "alt_depth": pl.Int64,
    "gene": pl.Utf8,
    "consequence": pl.Utf8,
    "impact": pl.Utf8,
    "rank_score": pl.Float64,
    "model_class": pl.Utf8,
    "mitotip_score": pl.Float64,
    "mitotip_prediction": pl.Utf8,
    "gnomad_mt_het": pl.Float64,
    "gnomad_mt_hom": pl.Float64,
    "is_clinical": pl.Boolean,
    "call_label": pl.Utf8,
}

# VEP consequence terms, most severe first (Ensembl's ranking); an unknown term sorts last.
_SEVERITY = [
    "transcript_ablation",
    "splice_acceptor_variant",
    "splice_donor_variant",
    "stop_gained",
    "frameshift_variant",
    "stop_lost",
    "start_lost",
    "transcript_amplification",
    "feature_elongation",
    "feature_truncation",
    "inframe_insertion",
    "inframe_deletion",
    "missense_variant",
    "protein_altering_variant",
    "splice_donor_5th_base_variant",
    "splice_region_variant",
    "splice_donor_region_variant",
    "splice_polypyrimidine_tract_variant",
    "incomplete_terminal_codon_variant",
    "start_retained_variant",
    "stop_retained_variant",
    "synonymous_variant",
    "coding_sequence_variant",
    "mature_miRNA_variant",
    "5_prime_UTR_variant",
    "3_prime_UTR_variant",
    "non_coding_transcript_exon_variant",
    "intron_variant",
    "NMD_transcript_variant",
    "non_coding_transcript_variant",
    "coding_transcript_variant",
    "upstream_gene_variant",
    "downstream_gene_variant",
    "TFBS_ablation",
    "TFBS_amplification",
    "TF_binding_site_variant",
    "regulatory_region_ablation",
    "regulatory_region_amplification",
    "regulatory_region_variant",
    "intergenic_variant",
    "sequence_variant",
]
_SEVERITY_RANK = {term: i for i, term in enumerate(_SEVERITY)}
_KEY_ALLELE_CHARS = 20


def _info(info: str) -> dict[str, str]:
    """INFO as a dict; a flag has the value ``""``."""
    out: dict[str, str] = {}
    for item in info.split(";"):
        key, _, value = item.partition("=")
        if key:
            out[key] = value
    return out


def _number(value: str | None, *, first: bool = True) -> float | None:
    if value is None or value in ("", "."):
        return None
    if first:
        value = value.split(",")[0]
    try:
        number = float(value)
    except ValueError:
        return None
    return number if number == number and abs(number) != float("inf") else None


def _family_value(value: str | None) -> str | None:
    """``family:value`` -> value (the last ``:`` part); ``.`` and absent are null."""
    if not value or value == ".":
        return None
    return value.split(",")[0].rsplit(":", 1)[-1]


def _variant_type(ref: str, alt: str) -> str:
    if alt.startswith("<") or "[" in alt or "]" in alt:
        return "SV"
    if len(ref) == 1 and len(alt) == 1:
        return "SNP"
    return "MNP" if len(ref) == len(alt) else "INDEL"


def _csq_fields(header_lines: list[str]) -> list[str]:
    """The CSQ sub-field names, from the ``##INFO=<ID=CSQ`` header line."""
    for line in header_lines:
        if line.startswith("##INFO=<ID=CSQ,"):
            match = re.search(r"Format: ([^\"]+)", line)
            if match:
                return match.group(1).strip().split("|")
    return []


def _primary_entry(csq: str, names: list[str]) -> dict[str, str]:
    """The CSQ entry a call is read on: most severe, then canonical, then Ensembl."""
    if not csq or not names:
        return {}
    best: tuple[tuple[int, int, int], dict[str, str]] | None = None
    for entry in csq.split(","):
        cells = entry.split("|")
        fields = dict(zip(names, cells, strict=False))
        terms = [t for t in fields.get("Consequence", "").split("&") if t]
        rank = min((_SEVERITY_RANK.get(t, len(_SEVERITY)) for t in terms), default=len(_SEVERITY))
        key = (
            rank,
            0 if fields.get("CANONICAL") == "YES" else 1,
            0 if fields.get("SOURCE", "Ensembl") == "Ensembl" else 1,
        )
        if best is None or key < best[0]:
            best = (key, fields)
    return best[1] if best else {}


def _most_severe_term(consequence: str) -> str | None:
    terms = [t for t in consequence.split("&") if t]
    if not terms:
        return None
    return min(terms, key=lambda t: _SEVERITY_RANK.get(t, len(_SEVERITY)))


def _model_class(models: list[str]) -> str:
    if any(m.startswith("AR_comp") for m in models):
        return "Compound heterozygous"
    if any(m.startswith("AR_hom") for m in models):
        return "Recessive"
    if any(m.startswith("AD") for m in models):
        return "Dominant"
    if any(m.startswith("X") for m in models):
        return "X-linked"
    return "No model fits"


def _heteroplasmy_class(fraction: float) -> str:
    if fraction >= 0.95:
        return "Homoplasmic"
    return "Heteroplasmic" if fraction >= 0.10 else "Low level"


def _rows(lines: pl.Series) -> list[dict]:
    header = lines.filter(lines.str.starts_with("#")).to_list()
    chrom_line = next((h for h in header if h.startswith("#CHROM")), None)
    if chrom_line is None:
        return []
    names = chrom_line.split("\t")[9:]
    csq_names = _csq_fields(header)
    rows = []
    for line in lines.filter(~lines.str.starts_with("#")).to_list():
        c = line.split("\t")
        if len(c) < 10:
            continue
        chrom, pos, ref, alt = c[0], int(c[1]), c[3], c[4].split(",")[0]
        info = _info(c[7])
        entry = _primary_entry(info.get("CSQ", ""), csq_names)
        symbols = [s for s in info.get("Annotation", "").split(",") if s and s != "."]
        gene = symbols[0] if symbols else (entry.get("SYMBOL") or None)
        models = [
            m
            for m in (info.get("GeneticModels") or "").split(":", 1)[-1].split("|")
            if m and m != "."
        ]
        keys = c[8].split(":")
        key = f"{chrom}:{pos}:{ref[:_KEY_ALLELE_CHARS]}:{alt[:_KEY_ALLELE_CHARS]}"
        shared = {
            "variant_key": key,
            "chrom": chrom,
            "pos": pos,
            "end": pos + len(ref) - 1,
            "ref": ref,
            "alt": alt,
            "variant_type": _variant_type(ref, alt),
            "filter_status": c[6],
            "gene": gene,
            "consequence": _most_severe_term(entry.get("Consequence", "")),
            "impact": entry.get("IMPACT") or None,
            "rank_score": _number(_family_value(info.get("RankScore"))),
            "model_class": _model_class(models),
            "mitotip_score": _number(info.get("mitotip_score")),
            "mitotip_prediction": info.get("mitotip_trna_prediction") or None,
            "gnomad_mt_het": _number(info.get("GNOMAD_MTAF_het")),
            "gnomad_mt_hom": _number(info.get("GNOMAD_MTAF_hom")),
            "call_label": f"{gene} m.{pos}" if gene else f"m.{pos}{ref[:3]}>{alt[:3]}",
        }
        for name, cell in zip(names, c[9:], strict=False):
            parts = cell.split(":")

            def get(k: str, parts: list[str] = parts) -> str:
                return parts[keys.index(k)] if k in keys and keys.index(k) < len(parts) else ""

            fraction = _number(get("AF"))
            if fraction is None or fraction <= 0:
                continue
            ad = [_number(x, first=False) for x in get("AD").split(",")] if get("AD") else []
            dp = _number(get("DP"))
            rows.append(
                {
                    **shared,
                    "sample": name,
                    "gt": get("GT") or None,
                    "heteroplasmy": fraction,
                    "heteroplasmy_class": _heteroplasmy_class(fraction),
                    "dp": None if dp is None else int(dp),
                    "alt_depth": int(ad[1]) if len(ad) > 1 and ad[1] is not None else None,
                }
            )
    return rows


def transform(sources: dict[str, pl.DataFrame | None]) -> pl.DataFrame:
    """One row per mitochondrial variant and sample with a heteroplasmy."""
    raw = sources.get("raw")
    if raw is None:
        raise ValueError("raredisease mt_variants: no rank_and_filter/*_mt_ranked_*.vcf.gz")
    parsed: dict[str, list[dict]] = {"clinical": [], "research": []}
    for path in raw["source_path"].unique(maintain_order=True).to_list():
        kind = "clinical" if re.search(r"_mt_ranked_clinical\.vcf", path) else "research"
        lines = raw.filter(pl.col("source_path") == path)["raw_line"].drop_nulls()
        parsed[kind].extend(_rows(lines))
    clinical = {r["variant_key"] for r in parsed["clinical"]}
    merged = {(r["variant_key"], r["sample"]): r for r in parsed["clinical"]}
    merged.update({(r["variant_key"], r["sample"]): r for r in parsed["research"]})
    if not merged:
        raise ValueError("raredisease mt_variants: no sample carries a mitochondrial variant")
    for row in merged.values():
        row["is_clinical"] = row["variant_key"] in clinical
    frame = pl.DataFrame(list(merged.values()), schema=OUTPUT_SCHEMA, strict=False)
    return frame.sort(["pos", "variant_key", "sample"])
