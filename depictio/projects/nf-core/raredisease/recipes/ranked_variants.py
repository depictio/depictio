"""nf-core/raredisease ranked small variants: one row per variant, from the GENMOD-ranked VCFs.

The step a clinical geneticist works from. raredisease annotates the joint
callset with VEP, scores every variant in the context of the family's pedigree
with GENMOD (inheritance models plus a rank score), and publishes two VCFs per
family under ``rank_and_filter/``: ``<family>_snv_ranked_research.vcf.gz`` (every
annotated variant) and ``<family>_snv_ranked_clinical.vcf.gz`` (the subset that
passes the clinical gene panel and filters). The clinical file is a subset of
the research one, so each variant appears once here: ``is_clinical`` marks the
ones the clinical file holds, and a variant only the clinical file holds (a run
that skipped the research output) is kept as well.

What is read from each record:

* ``RankScore`` (``family:score``) and ``RankScoreNormalized``: GENMOD's score
  for the family; absent for a variant the scoring did not reach, so null;
* ``RankScoreMinMax`` (``family:min:max``): the bounds the rank model gives the family,
  the sum of its category scores at their lowest and highest, which is what a score is
  read against; kept as ``rank_score_min`` and ``rank_score_max`` on every row;
* ``RankResult``: the ten rank-model components (allele frequency, protein
  prediction, gene intolerance, inheritance, consequence, conservation, call
  quality, deleteriousness, clinical significance, splicing), in the order
  GENMOD's rank model lists them;
* ``GeneticModels`` (``family:AD|AD_dn|AR_hom|AR_comp|...``): the inheritance
  models the genotypes fit. ``model_class`` folds them onto one label by the
  strictest first (compound heterozygous, recessive, dominant, X-linked) and
  ``de_novo`` is true when any fitted model is a ``_dn`` one;
* ``CSQ`` (VEP): the entry the call is read on is the most severe consequence
  over all transcripts, a canonical transcript winning a tie, an Ensembl one
  winning the next. The CSQ field names are read from the VCF header, so the
  column order of a different VEP configuration does not matter;
* ``Annotation`` (the gene symbols GENMOD attached), ``most_severe_pli``,
  ``CADD``, ``GNOMADAF`` and ``GNOMADAF_popmax``;
* the sample columns, as ``calls``: ``sample|GT|DP|GQ|VAF`` for every sample
  carrying the alternate allele, joined by ``;`` (the ``ranked_genotypes``
  recipe unpacks it), and as ``genotypes``: ``sample|GT`` for every sample of the
  VCF, carrier or not, so a figure can tell a reference genotype from a missing one.

Sources:
    raw  every ``rank_and_filter/*_snv_ranked_*.vcf.gz``, one VCF line per row

Rows come out best first (highest rank score, unscored last, ties in genome order), so a
table reading the collection opens in rank order.

Output schema (a field a record does not carry is null):
    variant_key : Utf8        chrom:pos:ref:alt, alleles cut at 20 characters
    chrom, pos, end, ref, alt, variant_type (SNP / MNP / INDEL / SV)
    variant_set : Utf8        Clinical, or Research only
    is_clinical : Boolean
    qual : Float64, filter_status : Utf8
    rank_score : Float64      GENMOD rank score of the family
    rank_score_norm : Float64 the same, scaled to 0..1 by the model's bounds
    rank_score_min, rank_score_max : Float64   the model's bounds for the family
    genetic_models : Utf8     fitted models, comma-separated
    model_class : Utf8        Compound heterozygous / Recessive / Dominant / X-linked / No model fits
    de_novo : Boolean
    gene : Utf8               first gene symbol, ``genes`` lists all
    genes : Utf8
    consequence : Utf8        most severe VEP term
    impact : Utf8             HIGH / MODERATE / LOW / MODIFIER of that entry
    hgvs_c, hgvs_p : Utf8     of that entry, transcript prefix removed
    sift, polyphen : Utf8     of that entry, as VEP writes them
    pli : Float64             probability of LoF intolerance of the gene
    cadd : Float64
    gnomad_af, gnomad_af_popmax : Float64
    score_allele_frequency, score_protein, score_gene_intolerance, score_inheritance,
    score_consequence, score_conservation, score_call_quality, score_deleteriousness,
    score_clinical, score_splicing : Int64     the ten RankResult components
    n_carriers : Int64        samples carrying the alternate allele
    carriers : Utf8           their ids, comma-separated
    calls : Utf8              sample|GT|DP|GQ|VAF of the carriers, ``;``-separated
    genotypes : Utf8          sample|GT of every sample of the VCF, ``;``-separated
    call_label : Utf8         gene and protein (or coding) change, for the browser
"""

from __future__ import annotations

import re
import urllib.parse

import polars as pl

from depictio.models.models.transforms import RecipeSource

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="raw",
        glob_pattern="rank_and_filter/*_snv_ranked_*.vcf.gz",
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
    )
]

_COMPONENTS = [
    "score_allele_frequency",
    "score_protein",
    "score_gene_intolerance",
    "score_inheritance",
    "score_consequence",
    "score_conservation",
    "score_call_quality",
    "score_deleteriousness",
    "score_clinical",
    "score_splicing",
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "variant_key": pl.Utf8,
    "chrom": pl.Utf8,
    "pos": pl.Int64,
    "end": pl.Int64,
    "ref": pl.Utf8,
    "alt": pl.Utf8,
    "variant_type": pl.Utf8,
    "variant_set": pl.Utf8,
    "is_clinical": pl.Boolean,
    "qual": pl.Float64,
    "filter_status": pl.Utf8,
    "rank_score": pl.Float64,
    "rank_score_norm": pl.Float64,
    "rank_score_min": pl.Float64,
    "rank_score_max": pl.Float64,
    "genetic_models": pl.Utf8,
    "model_class": pl.Utf8,
    "de_novo": pl.Boolean,
    "gene": pl.Utf8,
    "genes": pl.Utf8,
    "consequence": pl.Utf8,
    "impact": pl.Utf8,
    "hgvs_c": pl.Utf8,
    "hgvs_p": pl.Utf8,
    "sift": pl.Utf8,
    "polyphen": pl.Utf8,
    "pli": pl.Float64,
    "cadd": pl.Float64,
    "gnomad_af": pl.Float64,
    "gnomad_af_popmax": pl.Float64,
    **dict.fromkeys(_COMPONENTS, pl.Int64),
    "n_carriers": pl.Int64,
    "carriers": pl.Utf8,
    "calls": pl.Utf8,
    "genotypes": pl.Utf8,
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


def _first_number(*values: str | None) -> float | None:
    """The first of ``values`` that parses as a number (zero counts)."""
    for value in values:
        number = _number(value)
        if number is not None:
            return number
    return None


def _family_value(value: str | None) -> str | None:
    """``family:value`` -> value (the last ``:`` part); ``.`` and absent are null."""
    if not value or value == ".":
        return None
    return value.split(",")[0].rsplit(":", 1)[-1]


def _score_bounds(value: str | None) -> tuple[float | None, float | None]:
    """``family:min:max`` -> (min, max); ``(None, None)`` when the field is absent or unreadable."""
    if not value or value == ".":
        return None, None
    parts = value.split(",")[0].rsplit(":", 2)
    if len(parts) != 3:
        return None, None
    return _number(parts[1]), _number(parts[2])


def _genotypes(names: list[str], cells: list[str], fmt: str) -> str | None:
    """``sample|GT`` of every sample, ``;``-joined; None when the record has no GT."""
    keys = fmt.split(":")
    if "GT" not in keys:
        return None
    at = keys.index("GT")
    out = []
    for name, cell in zip(names, cells, strict=False):
        parts = cell.split(":")
        out.append(f"{name}|{parts[at] if at < len(parts) else '.'}")
    return ";".join(out) or None


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


def _clean_hgvs(value: str) -> str | None:
    """``ENST00000286827.3:c.-421-26872C>T`` -> ``c.-421-26872C>T``."""
    if not value:
        return None
    return urllib.parse.unquote(value.split(":", 1)[-1]) or None


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


def _calls(names: list[str], cells: list[str], fmt: str) -> list[tuple[str, str, str, str, str]]:
    """(sample, GT, DP, GQ, VAF) of every sample carrying an alternate allele."""
    keys = fmt.split(":")
    at = {k: keys.index(k) for k in ("GT", "DP", "AD", "GQ") if k in keys}
    out = []
    for name, cell in zip(names, cells, strict=False):
        parts = cell.split(":")

        def get(key: str, parts: list[str] = parts) -> str:
            i = at.get(key)
            return parts[i] if i is not None and i < len(parts) else ""

        gt = get("GT")
        if not re.search(r"[1-9]", gt):
            continue
        ad = [_number(x) for x in get("AD").split(",")] if get("AD") else []
        vaf = ""
        if len(ad) >= 2 and ad[0] is not None and ad[1] is not None and ad[0] + ad[1] > 0:
            vaf = f"{ad[1] / (ad[0] + ad[1]):.3f}"
        out.append((name, gt, get("DP"), get("GQ"), vaf))
    return out


def _rows(lines: pl.Series, variant_set: str) -> list[dict]:
    header = lines.filter(lines.str.starts_with("#")).to_list()
    chrom_line = next((h for h in header if h.startswith("#CHROM")), None)
    if chrom_line is None:
        return []
    names = chrom_line.split("\t")[9:]
    csq_names = _csq_fields(header)
    rows = []
    for line in lines.filter(~lines.str.starts_with("#")).to_list():
        c = line.split("\t")
        if len(c) < 8:
            continue
        chrom, pos, ref, alt = c[0], int(c[1]), c[3], c[4].split(",")[0]
        info = _info(c[7])
        entry = _primary_entry(info.get("CSQ", ""), csq_names)
        term = _most_severe_term(entry.get("Consequence", ""))
        symbols = [s for s in info.get("Annotation", "").split(",") if s and s != "."]
        gene = symbols[0] if symbols else (entry.get("SYMBOL") or None)
        models = [
            m
            for m in (info.get("GeneticModels") or "").split(":", 1)[-1].split("|")
            if m and m != "."
        ]
        result = (info.get("RankResult") or "").split("|")
        calls = _calls(names, c[9:], c[8]) if len(c) > 9 else []
        score_min, score_max = _score_bounds(info.get("RankScoreMinMax"))
        key = f"{chrom}:{pos}:{ref[:_KEY_ALLELE_CHARS]}:{alt[:_KEY_ALLELE_CHARS]}"
        hgvs_p = _clean_hgvs(entry.get("HGVSp", ""))
        hgvs_c = _clean_hgvs(entry.get("HGVSc", ""))
        row = {
            "variant_key": key,
            "chrom": chrom,
            "pos": pos,
            "end": pos + len(ref) - 1,
            "ref": ref,
            "alt": alt,
            "variant_type": _variant_type(ref, alt),
            "variant_set": variant_set,
            "qual": _number(c[5]),
            "filter_status": c[6],
            "rank_score": _number(_family_value(info.get("RankScore"))),
            "rank_score_norm": _number(_family_value(info.get("RankScoreNormalized"))),
            "rank_score_min": score_min,
            "rank_score_max": score_max,
            "genetic_models": ", ".join(models) or None,
            "model_class": _model_class(models),
            "de_novo": any(m.endswith("_dn") for m in models),
            "gene": gene,
            "genes": ", ".join(symbols) or gene,
            "consequence": term,
            "impact": entry.get("IMPACT") or None,
            "hgvs_c": hgvs_c,
            "hgvs_p": hgvs_p,
            "sift": entry.get("SIFT") or None,
            "polyphen": entry.get("PolyPhen") or None,
            "pli": _first_number(info.get("most_severe_pli"), entry.get("pLI_gene_value")),
            "cadd": _number(info.get("CADD")),
            "gnomad_af": _number(info.get("GNOMADAF")),
            "gnomad_af_popmax": _number(info.get("GNOMADAF_popmax")),
            "n_carriers": len(calls),
            "carriers": ", ".join(call[0] for call in calls) or None,
            "calls": ";".join("|".join(call) for call in calls) or None,
            "genotypes": _genotypes(names, c[9:], c[8]) if len(c) > 9 else None,
            "call_label": f"{gene} {hgvs_p or hgvs_c or f'{chrom}:{pos}'}" if gene else key,
        }
        for i, name in enumerate(_COMPONENTS):
            row[name] = (
                int(float(result[i]))
                if i < len(result) and _number(result[i]) is not None
                else None
            )
        rows.append(row)
    return rows


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """One row per ranked variant, the clinical subset flagged."""
    raw = sources["raw"]
    parsed: dict[str, list[dict]] = {}
    for path in raw["source_path"].unique(maintain_order=True).to_list():
        kind = "clinical" if re.search(r"_snv_ranked_clinical\.vcf", path) else "research"
        lines = raw.filter(pl.col("source_path") == path)["raw_line"].drop_nulls()
        parsed.setdefault(kind, []).extend(_rows(lines, kind))
    clinical = {r["variant_key"] for r in parsed.get("clinical", [])}
    merged = {r["variant_key"]: r for r in parsed.get("clinical", [])}
    merged.update({r["variant_key"]: r for r in parsed.get("research", [])})
    if not merged:
        raise ValueError("raredisease ranked_variants: no ranked VCF record under rank_and_filter/")
    for key, row in merged.items():
        row["is_clinical"] = key in clinical
        row["variant_set"] = "Clinical" if key in clinical else "Research only"
    frame = pl.DataFrame(list(merged.values()), schema=OUTPUT_SCHEMA, strict=False)
    # Best first: the Ranked tab's table opens in rank order, and ties keep genome order.
    return frame.sort(
        ["rank_score", "chrom", "pos", "variant_key"],
        descending=[True, False, False, False],
        nulls_last=True,
    )
