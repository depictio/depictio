"""Genome-browser track manifest: one row per track file the run published.

nf-core/oncoanalyser publishes every output under ``<group_id>/<tool>/``, one
group per tumor, and names the files after the sample of the samplesheet (the
file the ``samples`` hub reads), so the manifest is spelled out from that sheet
rather than globbed. For each group with a tumor DNA sample ``T`` (and, when
the group has one, a normal DNA sample ``N``):

- PURPLE's VCFs, under ``<group>/purple/``: the purity-adjusted somatic small
  variants (``T.purple.somatic.vcf.gz``), the somatic SVs (``T.purple.sv.vcf.gz``)
  and, with a normal, the germline small variants and SVs
  (``T.purple.germline.vcf.gz``, ``T.purple.sv.germline.vcf.gz``);
- the REDUX alignments, under ``<group>/alignments/<sample>/``
  (``<sample>.redux.bam``), the tumor's and the normal's. They are 80 to 170 GB
  on a WGS run, so they are read by range and come last.

The tumor RNA alignment is not listed: no tab reads it.

Every row of a group is keyed on the tumor's sample id (``sample_id``), the key
every collection of this template links on, so picking a tumor opens its VCFs
and both of its alignments. ``source_sample`` names the sample a file belongs
to (the normal's own id on the normal's alignment).

Row order is what the browser opens on (``initial_tracks`` shows the first
rows): one block per group, its somatic variants, somatic SVs, germline variants
and germline SVs, then the alignments of every group, tumor before normal.

Two ways the files are read:
- ``TRACKS_URI`` is set (the template turns it into ``remote_base_uri``): every
  expected row is kept and read in place under that results folder;
- otherwise the rows whose file and index (``.tbi``, ``.bai``) are present under
  DATA_ROOT are kept and the CLI uploads them at ingestion (all rows are kept
  when none is present, so a tables-only run still lists what the pipeline
  publishes).

Output schema:
    track_id : Utf8       `<sample_id>.<kind>`, unique per file
    sample_id : Utf8      the group's tumor DNA sample (links to `samples`)
    group_id : Utf8       the analysis group the file is published under
    source_sample : Utf8  the sample the file belongs to
    kind : Utf8           somatic / sv / germline / sv_germline / tumor_reads / normal_reads
    format : Utf8         vcf / bam
    uri : Utf8            path relative to the results folder
    name : Utf8           track label shown in the browser
    color : Utf8          per-kind colour
    category : Utf8       track-selector folder
    order : Int64         row order the browser opens with (``order_column``)
"""

from __future__ import annotations

import io
import re

import polars as pl

from depictio.models.models.transforms import RecipeSource

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    # Same file as the `samples` hub reads. No input_schema: a tab-separated sheet read as
    # comma-separated is one column and is re-split by _fix_delimiter.
    RecipeSource(
        ref="samplesheet",
        path="input/samplesheet.csv",
        format="csv",
        read_kwargs={"infer_schema_length": 0},
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "track_id": pl.Utf8,
    "sample_id": pl.Utf8,
    "group_id": pl.Utf8,
    "source_sample": pl.Utf8,
    "kind": pl.Utf8,
    "format": pl.Utf8,
    "uri": pl.Utf8,
    "name": pl.Utf8,
    "color": pl.Utf8,
    "category": pl.Utf8,
    "order": pl.Int64,
}

_REQUIRED = ("group_id", "sample_id", "sample_type", "sequence_type")

# kind -> (format, path template, category, name, colour). `{g}` is the group, `{t}` the
# tumor DNA sample, `{n}` the normal DNA sample, `{s}` the sample the file belongs to.
_SOMATIC = (
    "somatic",
    "vcf",
    "{g}/purple/{t}.purple.somatic.vcf.gz",
    "Small variants",
    "{t} somatic",
    "rgb(213,94,0)",
)
_SV = (
    "sv",
    "vcf",
    "{g}/purple/{t}.purple.sv.vcf.gz",
    "Structural variants",
    "{t} somatic SV",
    "rgb(230,159,0)",
)
_GERMLINE = (
    "germline",
    "vcf",
    "{g}/purple/{t}.purple.germline.vcf.gz",
    "Small variants",
    "{t} germline",
    "rgb(0,114,178)",
)
_SV_GERMLINE = (
    "sv_germline",
    "vcf",
    "{g}/purple/{t}.purple.sv.germline.vcf.gz",
    "Structural variants",
    "{t} germline SV",
    "rgb(86,180,233)",
)
_TUMOR_READS = (
    "tumor_reads",
    "bam",
    "{g}/alignments/{s}/{s}.redux.bam",
    "Alignments",
    "{s} tumor reads",
    "rgb(204,121,167)",
)
_NORMAL_READS = (
    "normal_reads",
    "bam",
    "{g}/alignments/{s}/{s}.redux.bam",
    "Alignments",
    "{s} normal reads",
    "rgb(140,140,140)",
)


def _fix_delimiter(df: pl.DataFrame) -> pl.DataFrame:
    """Re-split a tab-separated sheet that was read with the comma separator."""
    if df.width == 1 and "\t" in df.columns[0]:
        text = "\n".join([df.columns[0]] + [str(v) for v in df[df.columns[0]].to_list()])
        return pl.read_csv(io.StringIO(text), separator="\t", infer_schema_length=0)
    return df


def _sanitise(name: str) -> str:
    return re.sub(r"[^0-9A-Za-z]+", "_", name.strip()).strip("_") or "column"


def _index_of(path: str) -> str:
    return path + (".bai" if path.endswith(".bam") else ".tbi")


def transform(sources: dict[str, pl.DataFrame], context=None) -> pl.DataFrame:
    """Spell out the expected track files of every analysis group of the samplesheet."""
    sheet = _fix_delimiter(sources["samplesheet"])
    sheet = sheet.select(
        [pl.col(c).cast(pl.Utf8).str.strip_chars().alias(_sanitise(c)) for c in sheet.columns]
    )
    missing = [c for c in _REQUIRED if c not in sheet.columns]
    if missing:
        raise ValueError(
            f"oncoanalyser tracks: samplesheet lacks column(s) {missing}; got {sheet.columns}"
        )

    # group -> {"tumor": sample id, "normal": sample id}, DNA samples only.
    groups: dict[str, dict[str, str]] = {}
    for row in sheet.iter_rows(named=True):
        group, sample = row["group_id"], row["sample_id"]
        if not group or not sample or (row["sequence_type"] or "").lower() != "dna":
            continue
        role = (row["sample_type"] or "").lower()
        if role in ("tumor", "normal"):
            groups.setdefault(group, {}).setdefault(role, sample)
    groups = {g: roles for g, roles in sorted(groups.items()) if "tumor" in roles}
    if not groups:
        raise ValueError(
            "oncoanalyser tracks: the samplesheet has no group with a tumor DNA sample"
        )

    def row_for(spec: tuple[str, ...], group: str, tumor: str, sample: str) -> dict:
        kind, fmt, template, category, name, color = spec
        fields = {"g": group, "t": tumor, "s": sample}
        return {
            "track_id": f"{tumor}.{kind}",
            "sample_id": tumor,
            "group_id": group,
            "source_sample": sample,
            "kind": kind,
            "format": fmt,
            "uri": template.format(**fields),
            "name": name.format(**fields),
            "color": color,
            "category": category,
        }

    rows: list[dict] = []
    for group, roles in groups.items():
        tumor = roles["tumor"]
        specs = [_SOMATIC, _SV] + ([_GERMLINE, _SV_GERMLINE] if "normal" in roles else [])
        rows += [row_for(spec, group, tumor, tumor) for spec in specs]
    for group, roles in groups.items():
        tumor = roles["tumor"]
        rows.append(row_for(_TUMOR_READS, group, tumor, tumor))
        if "normal" in roles:
            rows.append(row_for(_NORMAL_READS, group, tumor, roles["normal"]))

    def present(path: str) -> bool:
        """The file and its index are under the data root (an upload needs both)."""
        return context is not None and context.exists(path) and context.exists(_index_of(path))

    if context is not None and not context.reads_in_place and any(present(r["uri"]) for r in rows):
        rows = [r for r in rows if present(r["uri"])]
    # Ingestion reorders rows (clustering on link columns): keep the intended
    # order explicit, the browser opens on the first `initial_tracks`.
    for i, row in enumerate(rows, start=1):
        row["order"] = i
    return pl.DataFrame(rows, schema=OUTPUT_SCHEMA)
