"""nf-core/raredisease family checks: one row per ordered pair of samples of a family.

The question a trio or family analysis has to settle before any variant means
anything: are these the people the pedigree says? This recipe reads the genotypes of
the joint callset (``call_snv/genome/<family>_snv.vcf.gz``) and, for every pair of
samples, counts on the autosomal sites both samples are called at with at least one
read (a joint caller writes homozygous reference for a sample with no reads, which is
missing data, not a genotype):

* ``ibs0``: sites where one is homozygous reference and the other homozygous alternate
  (opposite homozygotes). A parent and a child almost never differ that way, so a high
  count between a declared parent and child points at a sample swap;
* ``identical_pct``: sites with the same genotype;
* ``relatedness``: ``(shared hets - 2 x ibs0) / sqrt(hets_a x hets_b)``, the estimate
  peddy reports (about 0.5 for parent-child and full siblings, about 0 for unrelated
  samples, 1 for the same person).

The declared relation comes from the pedigree file (``pedigree/*.ped``): ``Parent-child``
when one sample is the other's father or mother, ``Siblings`` when they share a parent,
``Unrelated`` otherwise. ``check_status`` is decided on ``ibs0_pct`` and only for a declared
parent and child: ``Consistent`` at or under 1 percent, ``Check`` above it, ``Too few
sites`` under 50 shared sites (a shallow callset cannot decide), ``Not checked`` for any
other relation. The relatedness estimate is reported but not judged: it assumes sites
chosen without regard to the samples and read deep enough to call heterozygotes, which a
joint callset's variable sites at low depth do not give. Every pair appears in both
directions, so a filter on either sample finds it.

Sources:
    raw  ``call_snv/genome/*_snv.vcf.gz``, one VCF line per row
    ped  ``pedigree/*.ped`` (optional): family, sample, father, mother, sex, phenotype

Output schema:
    sample : Utf8, partner : Utf8
    relation : Utf8            Parent-child / Siblings / Unrelated / Not declared
    shared_sites : Int64       autosomal sites both samples are called at
    ibs0 : Int64               opposite-homozygote sites
    ibs0_pct : Float64         of the shared sites, percent
    identical_pct : Float64    sites with the same genotype, percent
    relatedness : Float64      peddy-style estimate, null without shared heterozygous sites
    check_status : Utf8        Consistent / Check / Too few sites / Not checked
"""

from __future__ import annotations

import itertools

import polars as pl

from depictio.models.models.transforms import RecipeSource

_RAW = {
    "separator": "\x1e",
    "has_header": False,
    "new_columns": ["raw_line"],
    "quote_char": None,
    "infer_schema_length": 0,
}

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="raw",
        glob_pattern="call_snv/genome/*_snv.vcf.gz",
        format="csv",
        read_kwargs=dict(_RAW),
        source_path="source_path",
        input_schema={"raw_line": pl.Utf8, "source_path": pl.Utf8},
    ),
    RecipeSource(
        ref="ped",
        glob_pattern="pedigree/*.ped",
        format="tsv",
        read_kwargs={
            "has_header": False,
            "new_columns": ["family_id", "sample_id", "father", "mother", "sex", "phenotype"],
            "infer_schema_length": 0,
        },
        input_schema={"sample_id": pl.Utf8, "father": pl.Utf8, "mother": pl.Utf8},
        optional=True,
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "sample": pl.Utf8,
    "partner": pl.Utf8,
    "relation": pl.Utf8,
    "shared_sites": pl.Int64,
    "ibs0": pl.Int64,
    "ibs0_pct": pl.Float64,
    "identical_pct": pl.Float64,
    "relatedness": pl.Float64,
    "check_status": pl.Utf8,
}

_AUTOSOME = r"^(?:chr)?(?:[1-9]|1[0-9]|2[0-2])\t"
MIN_SITES = 50
MIN_DEPTH = 1
MAX_PARENT_CHILD_IBS0_PCT = 1.0


def _dosages(lines: pl.Series, names: list[str]) -> pl.DataFrame:
    """One column per sample: alternate-allele count of its genotype, null when missing."""
    body = lines.filter(~lines.str.starts_with("#")).to_frame("raw_line")
    body = body.filter(pl.col("raw_line").str.contains(_AUTOSOME))
    fields = pl.col("raw_line").str.split("\t")
    keys = fields.list.get(8, null_on_oob=True).str.split(":")
    dp_at = keys.list.eval(pl.element() == "DP").list.arg_max()
    exprs = []
    for i, name in enumerate(names):
        cell = fields.list.get(9 + i, null_on_oob=True).str.split(":")
        alleles = cell.list.get(0).str.replace_all("|", "/", literal=True).str.split("/")
        depth = cell.list.get(dp_at, null_on_oob=True).cast(pl.Int64, strict=False)
        dosage = alleles.list.eval(pl.element().ne("0").cast(pl.Int8)).list.sum()
        # A joint caller writes 0/0 for a sample with no reads at the site: that is
        # missing, not homozygous reference.
        unusable = alleles.list.contains(".") | ~(depth >= MIN_DEPTH).fill_null(False)
        exprs.append(pl.when(unusable).then(None).otherwise(dosage).alias(name))
    return body.select(exprs)


def _relations(ped: pl.DataFrame | None) -> dict[frozenset[str], str]:
    """Declared relation of each pair the pedigree names."""
    if ped is None:
        return {}
    rows = [
        (r["sample_id"], r["father"], r["mother"])
        for r in ped.filter(~pl.col("family_id").str.starts_with("#")).iter_rows(named=True)
    ]
    parents = {s: {p for p in (f, m) if p and p != "0"} for s, f, m in rows}
    relations: dict[frozenset[str], str] = {}
    for a, b in itertools.combinations(parents, 2):
        if b in parents[a] or a in parents[b]:
            relations[frozenset((a, b))] = "Parent-child"
        elif parents[a] & parents[b]:
            relations[frozenset((a, b))] = "Siblings"
        else:
            relations[frozenset((a, b))] = "Unrelated"
    return relations


def _pair(dosage: pl.DataFrame, a: str, b: str) -> dict[str, float | int | None]:
    both = dosage.select(pl.col(a).alias("a"), pl.col(b).alias("b")).drop_nulls()
    n = both.height
    if n == 0:
        return {"shared": 0}
    stats = both.select(
        ((pl.col("a") == 0) & (pl.col("b") >= 2) | (pl.col("a") >= 2) & (pl.col("b") == 0))
        .sum()
        .alias("ibs0"),
        (pl.col("a") == pl.col("b")).sum().alias("same"),
        ((pl.col("a") == 1) & (pl.col("b") == 1)).sum().alias("shared_hets"),
        (pl.col("a") == 1).sum().alias("hets_a"),
        (pl.col("b") == 1).sum().alias("hets_b"),
    ).row(0, named=True)
    denominator = (stats["hets_a"] * stats["hets_b"]) ** 0.5
    relatedness = (
        (stats["shared_hets"] - 2 * stats["ibs0"]) / denominator if denominator > 0 else None
    )
    return {"shared": n, "relatedness": relatedness, **stats}


def transform(sources: dict[str, pl.DataFrame | None]) -> pl.DataFrame:
    """One row per ordered pair of samples of each family callset."""
    raw = sources["raw"]
    relations = _relations(sources.get("ped"))
    rows = []
    for path in raw["source_path"].unique(maintain_order=True).to_list():
        lines = raw.filter(pl.col("source_path") == path)["raw_line"].drop_nulls()
        header = lines.filter(lines.str.starts_with("#CHROM"))
        if header.is_empty():
            continue
        names = header[0].split("\t")[9:]
        dosage = _dosages(lines, names)
        for a, b in itertools.combinations(names, 2):
            m = _pair(dosage, a, b)
            relation = relations.get(
                frozenset((a, b)), "Unrelated" if relations else "Not declared"
            )
            shared = int(m["shared"])
            relatedness = m.get("relatedness")
            ibs0_pct = (m["ibs0"] * 100.0 / shared) if shared else None
            if relation != "Parent-child":
                status = "Not checked"
            elif shared < MIN_SITES or ibs0_pct is None:
                status = "Too few sites"
            else:
                status = "Consistent" if ibs0_pct <= MAX_PARENT_CHILD_IBS0_PCT else "Check"
            row = {
                "relation": relation,
                "shared_sites": shared,
                "ibs0": m.get("ibs0"),
                "ibs0_pct": ibs0_pct,
                "identical_pct": (m["same"] * 100.0 / shared) if shared else None,
                "relatedness": None if relatedness is None else round(relatedness, 4),
                "check_status": status,
            }
            rows.append({"sample": a, "partner": b, **row})
            rows.append({"sample": b, "partner": a, **row})
    if not rows:
        raise ValueError("raredisease family_checks: no family callset with two or more samples")
    frame = pl.DataFrame(rows, schema=OUTPUT_SCHEMA, strict=False)
    return frame.with_columns(pl.col("ibs0_pct", "identical_pct").round(3)).sort(
        ["sample", "partner"]
    )
