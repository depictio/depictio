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
  FreeBayes) comes before the unfiltered one. A file the root does not hold
  (read in place, or a tables-only run) takes the annotated path only when the
  run annotated with snpEff, else the caller's own, so a run without snpEff
  does not list tracks that 404;
- alignments: ``preprocessing/recalibrated/<S>/<S>.recal.cram`` when the run
  recalibrated base qualities, else ``preprocessing/markduplicates/<S>/<S>.md.cram``.

Row order is what the browser opens on when it does not pick by category
(``initial_tracks`` shows the first rows; the template picks by ``category``
instead): the light VCFs first, one block per sample (the small-variant callers,
then the structural-variant callers), and the CRAMs, which are gigabytes each,
close the manifest. The leading rows are a caller comparison with the reads under
it, though: every small-variant caller of the first sample, then that sample's
CRAM, so the browser opens on what the callers agree on and the evidence for it,
not on the first N rows of one block.

A somatic callset (a tumour/normal pair, ``<tumour>_vs_<normal>``, or a tumour
called on its own) names its files after the unit, not a sample. Its VCFs are listed
too, in the ``Somatic variants`` category, keyed on the *tumour* sample so the hub's
sample filters reach them. The file names come from the ``vcf`` column of
``variantcalled.csv`` (its basename only: the folder is rebuilt under the results
folder, the manifest's absolute paths belong to the machine that ran the pipeline), so a
caller that writes several files for a pair (Strelka's SNVs and indels) gets a row each.
A paired callset beside the CRAMs of its tumour and its normal is what the browser shows
for a pair. A CRAM and a bgzipped VCF cannot be read without their index (``.crai``,
``.tbi``), so a file whose index is missing is left out of an upload.

Two ways the files are read:
- ``TRACKS_URI`` is set (the template turns it into ``remote_base_uri``): every
  expected row is kept and read in place under that results folder, on the
  first layout of each file the root holds, else (annotated VCF when the run
  annotated with snpEff, recalibrated CRAM). The folder must hold the files at
  the layout the data root shows;
- otherwise the rows whose file and index are present under DATA_ROOT are kept
  and the CLI uploads them at ingestion (all rows are kept when none is
  present, so a tables-only run still lists what the pipeline publishes).

Output schema:
    track_id : Utf8     `<sample_id>.<caller>` or `<sample_id>.alignments`, unique per file
                        (`<unit>.<caller>[.<qualifier>]` for a somatic callset)
    sample_id : Utf8    the sample (links to the `samples` hub); a pair's is its tumour
    caller : Utf8       the variant caller; null on an alignment row
    kind : Utf8         variants / sv / somatic / alignments
    format : Utf8       vcf / cram
    uri : Utf8          path relative to the results folder
    name : Utf8         track label shown in the browser
    category : Utf8     track-selector folder
    order : Int64       row order the browser opens with (``order_column``)
"""

from __future__ import annotations

import json

import polars as pl

from depictio.models.models.transforms import RecipeSource
from depictio.recipes.lib.sarek_units import PAIR_SEP, split_pair

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
_PAIR_MARK = PAIR_SEP

# What a pair's caller writes when the manifest does not name the file (the manifest
# lists them; this is the fallback of a run whose variantcalled.csv lacks the column).
_SOMATIC_NAMES = {
    "mutect2": ("{u}.mutect2.filtered.vcf.gz",),
    "strelka": ("{u}.strelka.somatic_snvs.vcf.gz", "{u}.strelka.somatic_indels.vcf.gz"),
}
_VCF_SUFFIX = ".vcf.gz"


def _somatic_candidates(unit: str, caller: str, basename: str) -> list[str]:
    """Paths of a somatic callset's VCF: the snpEff twin first, then the caller's own."""
    stem = basename[: -len(_VCF_SUFFIX)] if basename.endswith(_VCF_SUFFIX) else basename
    return [
        f"annotation/{caller}/{unit}/{stem}_snpEff.ann.vcf.gz",
        f"variant_calling/{caller}/{unit}/{basename}",
    ]


def _somatic_track(unit: str, caller: str, basename: str, tumour: str, normal: str | None) -> dict:
    """The manifest row (without ``uri`` and ``order``) of one somatic VCF."""
    stem = basename[: -len(_VCF_SUFFIX)] if basename.endswith(_VCF_SUFFIX) else basename
    qualifiers = [q for q in stem.split(".")[2:] if q != "filtered"]
    label = f"{tumour} vs {normal}" if normal else tumour
    detail = " ".join(q.replace("somatic_", "").replace("_", " ") for q in qualifiers)
    return {
        "track_id": ".".join([unit, caller, *qualifiers]),
        "sample_id": tumour,
        "caller": caller,
        "kind": "somatic",
        "format": "vcf",
        "name": " ".join(filter(None, [label, caller, detail])),
        "category": "Somatic variants",
    }


def _vcf_candidates(sample_id: str, caller: str) -> list[str]:
    """Paths a caller's VCF may have: the snpEff twin of each name, then the names."""
    names = [n.format(s=sample_id) for n in _VCF_NAMES.get(caller, ("{s}." + caller + ".vcf.gz",))]
    annotated = [
        f"annotation/{caller}/{sample_id}/{n[: -len('.vcf.gz')]}_snpEff.ann.vcf.gz" for n in names
    ]
    plain = [f"variant_calling/{caller}/{sample_id}/{n}" for n in names]
    return [*annotated, *plain]


def _snpeff_ran(context) -> bool:
    """Whether the run annotated its calls with snpEff, as far as the data root can tell.

    Its annotated VCFs under ``annotation/`` say yes; calls under ``variant_calling/``
    with no annotated twin say no; a tables-only root has neither, so the run's own
    ``--tools`` (``pipeline_info/params*.json``) decides. Unknown: yes, the layout the
    manifest listed before it looked.
    """
    if context is None:
        return True
    if context.glob("annotation/*/*/*_snpEff.ann.vcf.gz"):
        return True
    if context.glob("variant_calling/*/*/*.vcf.gz"):
        return False
    for rel in reversed(context.glob("pipeline_info/params*.json")):
        try:
            tools = json.loads(context.root.read_bytes(rel)).get("tools")
        except (OSError, ValueError, AttributeError):
            continue
        if isinstance(tools, str):
            return "snpeff" in {t.strip().lower() for t in tools.split(",")}
    return True


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

    status: dict[str, int] = {}  # sample -> 0 normal / 1 tumour, from the design manifests
    for ref in _DESIGN_REFS:
        df = sources.get(ref)
        if df is not None and {"sample", "status"} <= set(df.columns):
            for sample_id, value in zip(
                df["sample"].to_list(), df["status"].to_list(), strict=True
            ):
                try:
                    status.setdefault(str(sample_id).strip(), int(value))
                except (TypeError, ValueError):
                    continue

    called = sources.get("variantcalled")
    callers: dict[str, list[str]] = {}  # sample -> callers, in the manifest's order
    # (unit, caller, file name) of the calls that are somatic: a pair's, or a tumour's own.
    somatic: dict[tuple[str, str, str], None] = {}
    if called is not None and {"sample", "variantcaller"} <= set(called.columns):
        vcfs = called["vcf"].to_list() if "vcf" in called.columns else [None] * called.height
        for sample_id, caller, vcf in zip(
            called["sample"].to_list(), called["variantcaller"].to_list(), vcfs, strict=True
        ):
            sample_id, caller = str(sample_id or "").strip(), str(caller or "").strip().lower()
            if not (sample_id and caller):
                continue
            tumour, _ = split_pair(sample_id)
            if _PAIR_MARK in sample_id or status.get(sample_id) == 1:
                names = [str(vcf).strip().rsplit("/", 1)[-1]] if vcf and str(vcf).strip() else []
                names = names or [
                    n.format(u=sample_id)
                    for n in _SOMATIC_NAMES.get(caller, ("{u}." + caller + ".vcf.gz",))
                ]
                for name in names:
                    somatic[(sample_id, caller, name)] = None
                callers.setdefault(tumour, [])
            elif caller not in callers.setdefault(sample_id, []):
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

    snpeff: list[bool] = []  # looked up once, and only when a file is not held

    def uri_for(candidates: list[str]) -> str:
        """The first candidate the root holds; else the first the run is expected to write."""
        held = next((p for p in candidates if present(p)), None)
        if held:
            return held
        if not snpeff:
            snpeff.append(_snpeff_ran(context))
        if snpeff[0]:
            return candidates[0]
        return next((p for p in candidates if not p.startswith("annotation/")), candidates[0])

    variants: list[dict] = []
    somatic_rows: list[dict] = []
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
    for unit, caller, basename in sorted(somatic):
        tumour, normal = split_pair(unit)
        row = _somatic_track(unit, caller, basename, tumour, normal)
        row["uri"] = uri_for(_somatic_candidates(unit, caller, basename))
        somatic_rows.append(row)

    rows = [*variants, *somatic_rows, *alignments]
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
