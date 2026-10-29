"""Genome-browser track manifest: one row per track file the run published.

nf-core/sarek writes its own resume points as CSVs under ``csv/`` (the same
manifests the ``samples`` hub reads), so the manifest is spelled out from them
rather than globbed: ``csv/variantcalled.csv`` lists which caller ran on which
sample, and ``csv/recalibrated.csv`` / ``csv/markduplicates*.csv`` list the
samples that have an alignment file. For each sample the manifest holds one row
per caller VCF and one row for its CRAM, each keyed on the sample.

Each file has a few homes. The first one the run holds is used:
- variants: the snpEff-annotated twin first (``annotation/<caller>/<S>/``: its
  ``ANN`` field colours the browser's calls by impact), else the caller's own
  VCF (``variant_calling/<caller>/<S>/``). A filtered VCF (HaplotypeCaller,
  FreeBayes) comes before the unfiltered one;
- alignments: ``preprocessing/recalibrated/<S>/<S>.recal.cram`` when the run
  recalibrated base qualities, else ``preprocessing/markduplicates/<S>/<S>.md.cram``.

Row order is what the browser opens on (``initial_tracks`` shows the first
rows): the light VCFs first, one block per sample (the small-variant callers,
then the structural-variant callers), and the CRAMs, which are gigabytes each,
close the manifest. The leading rows are a caller comparison with the reads under
it, though: every small-variant caller of the first sample, then that sample's
CRAM, so the browser opens on what the callers agree on and the evidence for it,
not on the first N rows of one block.

Germline runs only: a somatic pair (``<tumour>_vs_<normal>``) names its caller
rows after the pair, not a sample, and is left out as it is on the hub. A CRAM
and a bgzipped VCF cannot be read without their index (``.crai``, ``.tbi``),
so a file whose index is missing is left out of an upload.

Two ways the files are read:
- ``TRACKS_URI`` is set (the template turns it into ``remote_base_uri``): every
  expected row is kept and read in place under that results folder, on the
  first layout of each file (annotated VCF, recalibrated CRAM). The folder must
  hold the annotation (snpEff) output the dashboard's other tabs read;
- otherwise the rows whose file and index are present under DATA_ROOT are kept
  and the CLI uploads them at ingestion (all rows are kept when none is
  present, so a tables-only run still lists what the pipeline publishes).

Output schema:
    track_id : Utf8     `<sample_id>.<caller>` or `<sample_id>.alignments`, unique per file
    sample_id : Utf8    the sample (links to the `samples` hub)
    caller : Utf8       the variant caller; null on an alignment row
    kind : Utf8         variants / sv / alignments
    format : Utf8       vcf / cram
    uri : Utf8          path relative to the results folder
    name : Utf8         track label shown in the browser
    category : Utf8     track-selector folder
    order : Int64       row order the browser opens with (``order_column``)
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

_CSV_KWARGS = {"infer_schema_length": 0}

# Manifests that list the samples with an alignment file, most complete first.
_DESIGN_REFS = ("recalibrated", "markduplicates", "markduplicates_no_table")

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    *(
        RecipeSource(
            ref=ref,
            path=f"csv/{ref}.csv",
            format="CSV",
            input_schema={"sample": pl.Utf8},
            read_kwargs=_CSV_KWARGS,
            optional=True,
        )
        for ref in _DESIGN_REFS
    ),
    RecipeSource(
        ref="variantcalled",
        path="csv/variantcalled.csv",
        format="CSV",
        input_schema={"sample": pl.Utf8, "variantcaller": pl.Utf8},
        read_kwargs=_CSV_KWARGS,
        optional=True,
    ),
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "track_id": pl.Utf8,
    "sample_id": pl.Utf8,
    "caller": pl.Utf8,
    "kind": pl.Utf8,
    "format": pl.Utf8,
    "uri": pl.Utf8,
    "name": pl.Utf8,
    "category": pl.Utf8,
    "order": pl.Int64,
}

# Callers in the order the browser opens them: the small-variant callers, then
# the structural-variant callers, then any other by name.
_CALLER_ORDER = ("haplotypecaller", "deepvariant", "strelka", "freebayes", "manta", "tiddit")
_SV_CALLERS = frozenset({"manta", "tiddit"})

# caller -> the file names it writes, preferred first (a filtered VCF before the raw one).
_VCF_NAMES = {
    "deepvariant": ("{s}.deepvariant.vcf.gz",),
    "haplotypecaller": ("{s}.haplotypecaller.filtered.vcf.gz", "{s}.haplotypecaller.vcf.gz"),
    "freebayes": ("{s}.freebayes.filtered.vcf.gz", "{s}.freebayes.vcf.gz"),
    "manta": ("{s}.manta.diploid_sv.vcf.gz",),
    "strelka": ("{s}.strelka.variants.vcf.gz",),
    "tiddit": ("{s}.tiddit.vcf.gz",),
}

# A somatic caller names its row after the pair, not a sample.
_PAIR_MARK = "_vs_"


def _vcf_candidates(sample_id: str, caller: str) -> list[str]:
    """Paths a caller's VCF may have: the snpEff twin of each name, then the names."""
    names = [n.format(s=sample_id) for n in _VCF_NAMES.get(caller, ("{s}." + caller + ".vcf.gz",))]
    annotated = [
        f"annotation/{caller}/{sample_id}/{n[: -len('.vcf.gz')]}_snpEff.ann.vcf.gz" for n in names
    ]
    plain = [f"variant_calling/{caller}/{sample_id}/{n}" for n in names]
    return [*annotated, *plain]


def _cram_candidates(sample_id: str, stage: str | None) -> list[str]:
    recal = f"preprocessing/recalibrated/{sample_id}/{sample_id}.recal.cram"
    marked = f"preprocessing/markduplicates/{sample_id}/{sample_id}.md.cram"
    return [recal, marked] if stage == "recalibrated" else [marked, recal]


def _index_of(path: str) -> str:
    return path + (".crai" if path.endswith(".cram") else ".tbi")


def _column(df: pl.DataFrame | None, name: str) -> list[str]:
    if df is None or name not in df.columns:
        return []
    return [str(v).strip() for v in df[name].to_list() if v is not None and str(v).strip()]


def transform(sources: dict[str, pl.DataFrame | None], context=None) -> pl.DataFrame:
    """Spell out the expected track files of every sample and caller of the manifests."""
    stage: dict[str, str] = {}  # sample -> the first design manifest that lists it
    for ref in _DESIGN_REFS:
        for sample_id in _column(sources.get(ref), "sample"):
            stage.setdefault(sample_id, ref)

    called = sources.get("variantcalled")
    callers: dict[str, list[str]] = {}  # sample -> callers, in the manifest's order
    if called is not None and {"sample", "variantcaller"} <= set(called.columns):
        for sample_id, caller in zip(
            called["sample"].to_list(), called["variantcaller"].to_list(), strict=True
        ):
            sample_id, caller = str(sample_id or "").strip(), str(caller or "").strip().lower()
            if sample_id and caller and _PAIR_MARK not in sample_id:
                if caller not in callers.setdefault(sample_id, []):
                    callers[sample_id].append(caller)

    samples = sorted({*stage, *callers})
    if not samples:
        raise ValueError(
            "sarek tracks: no csv/recalibrated.csv, csv/markduplicates*.csv or "
            "csv/variantcalled.csv under the data root; sarek writes at least one of them"
        )

    def rank(caller: str) -> tuple[int, str]:
        known = _CALLER_ORDER.index(caller) if caller in _CALLER_ORDER else len(_CALLER_ORDER)
        return (known, caller)

    in_place = context is None or context.reads_in_place

    def present(path: str) -> bool:
        """The file and its index are under the data root (an upload needs both)."""
        return context is not None and context.exists(path) and context.exists(_index_of(path))

    def uri_for(candidates: list[str]) -> str:
        """The first candidate the run holds; the first one when none (or in place)."""
        if in_place:
            return candidates[0]
        return next((p for p in candidates if present(p)), candidates[0])

    variants: list[dict] = []
    alignments: list[dict] = []
    for sample_id in samples:
        for caller in sorted(callers.get(sample_id, []), key=rank):
            sv = caller in _SV_CALLERS
            variants.append(
                {
                    "track_id": f"{sample_id}.{caller}",
                    "sample_id": sample_id,
                    "caller": caller,
                    "kind": "sv" if sv else "variants",
                    "format": "vcf",
                    "uri": uri_for(_vcf_candidates(sample_id, caller)),
                    "name": f"{sample_id} {caller}",
                    "category": "Structural variants" if sv else "Small variants",
                }
            )
        if sample_id in stage:
            alignments.append(
                {
                    "track_id": f"{sample_id}.alignments",
                    "sample_id": sample_id,
                    "caller": None,
                    "kind": "alignments",
                    "format": "cram",
                    "uri": uri_for(_cram_candidates(sample_id, stage[sample_id])),
                    "name": f"{sample_id} reads",
                    "category": "Alignments",
                }
            )

    rows = [*variants, *alignments]
    if not in_place and any(present(r["uri"]) for r in rows):
        rows = [r for r in rows if present(r["uri"])]
    # Every small-variant caller of the first sample leads, then its CRAM: a caller
    # comparison with the reads under it (a row dropped above leaves the next in line).
    first = next((r["sample_id"] for r in rows if r["kind"] == "variants"), None)
    lead = [r for r in rows if r["sample_id"] == first and r["kind"] == "variants"]
    lead += [r for r in rows if r["sample_id"] == first and r["kind"] == "alignments"]
    lead_ids = {row["track_id"] for row in lead}
    rows = [*lead, *(r for r in rows if r["track_id"] not in lead_ids)]
    # Ingestion reorders rows (clustering on link columns): keep the intended
    # order explicit, the browser opens on the first `initial_tracks`.
    for i, row in enumerate(rows, start=1):
        row["order"] = i
    return pl.DataFrame(rows, schema=OUTPUT_SCHEMA)
