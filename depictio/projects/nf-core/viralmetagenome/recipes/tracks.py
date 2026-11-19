"""Genome-browser track manifest of nf-core/viralmetagenome: one row per track file.

Every genome of a viralmetagenome run is its own reference: a constraint
reference, a pool reference Mash picked, or the sample's own de novo consensus
the reads were mapped back to. ``genomic_tracks`` takes one assembly per
collection, so the browser reads them all from one indexed multi-FASTA of every
mapping reference of the run (``MAPPING_REFERENCES_FASTA``, the template turns
it into the collection's custom assembly), each genome a sequence of it. The
template drops this collection, and the browser with it, when that variable is
not set.

For each genome of the hub, the files the run published for its final mapping
(the ``variants/`` tree holds the variant-calling round only), when present:

* alignments: the deduplicated BAM (``variants/mapping-info/deduplicate/bam/``),
  else the mapper's own (``bwamem2/bam/``, ``bowtie2/bam/``), with its ``.bai``;
  the browser shows the soft clips of the reads, where a genome end was cut;
* depth: mosdepth's per-base depth (``*.per-base.bed.gz`` with its ``.csi``);
* variants: iVar's plain-text VCF (``variants/ivar/<sample>/*.vcf``), read whole,
  or a bgzipped VCF whose index was published. The pipeline publishes the
  ``.tbi`` of iVar's sorted VCF but not the VCF, and bcftools' VCFs without an
  index, so a bcftools run has no variant track; the Variants tab still reads
  its calls.

A file is matched to a genome by its name, ``[<prefix>-]<sample>_<reference>...``,
the way the variant and coverage collections key it.

Sources:
    genomes  ``genomes``, the genome hub

Output schema:
    track_id : Utf8     ``<genome_id>.<kind>``
    sample, genome_id : Utf8
    kind : Utf8         alignments / depth / variants
    format : Utf8       bam / bedgraph / vcf
    uri : Utf8          path relative to DATA_ROOT
    index_uri : Utf8    its index, relative to DATA_ROOT; null for a file read whole
    name : Utf8         track label
    category : Utf8     track-selector folder
    order : Int64       the order the browser opens the tracks in
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.viralmetagenome import split_mapping_name, strip_global_prefix

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="genomes",
        dc_ref="genomes",
        input_schema={"genome_id": pl.Utf8, "sample": pl.Utf8, "reference": pl.Utf8},
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "track_id": pl.Utf8,
    "sample": pl.Utf8,
    "genome_id": pl.Utf8,
    "kind": pl.Utf8,
    "format": pl.Utf8,
    "uri": pl.Utf8,
    "index_uri": pl.Utf8,
    "name": pl.Utf8,
    "category": pl.Utf8,
    "order": pl.Int64,
}

# kind -> (format, candidates in order of preference: (glob with `{s}` the
#          sample, index suffixes tried in order, empty for a file read whole),
#          category, label)
_KINDS: tuple[tuple[str, str, tuple[tuple[str, tuple[str, ...]], ...], str, str], ...] = (
    (
        "depth",
        "bedgraph",
        (("variants/mapping-info/metrics/mosdepth/{s}/*.per-base.bed.gz", (".csi", ".tbi")),),
        "Depth",
        "depth",
    ),
    (
        "variants",
        "vcf",
        (
            # A bgzipped VCF needs its index; none of the pipeline's has one
            # published today (the .tbi next to iVar's calls is the sorted
            # VCF's, which is not), so this is for a run that adds them.
            ("variants/*/{s}/*.vcf.gz", (".tbi", ".csi")),
            # iVar's plain-text VCF, small enough to be read whole. Its
            # `_all_hap.vcf` twin repeats every call per haplotype.
            ("variants/*/{s}/*.vcf", ()),
        ),
        "Variants",
        "variants",
    ),
    (
        "alignments",
        "bam",
        (
            ("variants/mapping-info/deduplicate/bam/{s}/*.bam", (".bai",)),
            ("variants/mapping-info/bwamem2/bam/{s}/*.bam", (".bai",)),
            ("variants/mapping-info/bowtie2/bam/{s}/*.bam", (".bai",)),
        ),
        "Reads",
        "reads",
    ),
)
_SKIP_SUFFIXES = ("_all_hap.vcf",)


#: The tools' own name suffixes, stripped from the end one at a time; a dot
#: inside a reference (``MN908947.3``) or a sample name stays.
_TOOL_SUFFIX = re.compile(
    r"\.(?:bam|cram|vcf|gz|bed|per-base|dedup|deduplicated|umi_deduplicated|markdup|"
    r"sorted|sort|filtered|norm|org)$"
)


def file_genome(path: str, sample: str) -> str | None:
    """The reference a published file of ``sample`` is named after, else None."""
    stem = strip_global_prefix(PurePosixPath(path).name)
    while (shorter := _TOOL_SUFFIX.sub("", stem)) != stem:
        stem = shorter
    if not stem.startswith(sample):
        return None
    reference, _route, _step = split_mapping_name(stem, sample)
    return reference


def transform(sources: dict[str, pl.DataFrame], context=None) -> pl.DataFrame:
    if context is None:
        raise ValueError("viralmetagenome tracks: needs the run folder to list its files")
    genomes = (
        sources["genomes"]
        .select("genome_id", "sample", "reference")
        .drop_nulls()
        .unique(subset="genome_id")
        .sort("genome_id")
    )
    by_sample: dict[str, dict[str, str]] = {}
    for row in genomes.iter_rows(named=True):
        by_sample.setdefault(row["sample"], {})[row["reference"]] = row["genome_id"]

    rows: list[dict] = []
    for sample, refs in sorted(by_sample.items()):
        for kind, fmt, candidates, category, label in _KINDS:
            found: dict[str, tuple[str, str | None]] = {}
            for pattern, index_suffixes in candidates:
                for path in context.glob(pattern.format(s=sample)):
                    if path.endswith(_SKIP_SUFFIXES):
                        continue
                    ref = file_genome(path, sample)
                    if ref not in refs or refs[ref] in found:
                        continue
                    index = next(
                        (path + x for x in index_suffixes if context.exists(path + x)), None
                    )
                    if index_suffixes and index is None:
                        continue
                    found[refs[ref]] = (path, index)
                if found:
                    # The first layout that holds the files wins: a deduplicated
                    # BAM is never doubled by the mapper's own.
                    break
            for gid, (path, index) in sorted(found.items()):
                rows.append(
                    {
                        "track_id": f"{gid}.{kind}",
                        "sample": sample,
                        "genome_id": gid,
                        "kind": kind,
                        "format": fmt,
                        "uri": path,
                        "index_uri": index,
                        "name": f"{gid} {label}",
                        "category": category,
                    }
                )
    if not rows:
        raise ValueError("viralmetagenome tracks: the run holds no indexed track file")
    # One block per genome: its depth and variants, light, then its reads.
    kind_order = {k[0]: i for i, k in enumerate(_KINDS)}
    rows.sort(key=lambda r: (r["genome_id"], kind_order[r["kind"]]))
    for i, row in enumerate(rows, start=1):
        row["order"] = i
    return pl.DataFrame(rows, schema=OUTPUT_SCHEMA)
