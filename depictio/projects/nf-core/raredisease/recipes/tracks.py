"""Genome-browser track manifest: one row per track file the run published.

raredisease publishes the files a clinical geneticist wants next to the variant
table, and this manifest lists them for the browser (JBrowse range-reads each one
through its index for the region in view, so nothing is loaded whole):

* the ranked VCFs of each family (``rank_and_filter/<family>_snv_ranked_clinical.vcf.gz``
  and ``..._research.vcf.gz``), the mobile element VCF
  (``call_mobile_elements/<family>_mobile_elements.vcf.gz``) and the repeat expansion VCF
  (``repeat_expansions/<family>_repeat_expansion_stranger.vcf.gz``): family-level, so their
  ``sample`` is null and their ``family_id`` is the family;
* per sample, its duplicate-marked alignment (``alignment/<S>_sorted_md.bam``), the TIDDIT
  coverage track (``qc_bam/<S>_tidditcov.bw``) and the rhocall autozygosity track
  (``annotate_snv/genome/<S>_rhocallviz/<S>_rhocallviz.bw``).

The families and their samples come from the pedigree (``pedigree/*.ped``); a run read from
a folder is also listed by what it holds, so a sample without a pedigree row still appears
when there is a single family. Row order is what the browser opens on (``initial_tracks``
shows the first rows). The leading rows are what a variant is read against: the research
ranked VCF (it holds every ranked variant, the clinical subset included, so the best-ranked
calls show wherever they sit; the clinical VCF only when the run has no research one), the
alignment of the proband and its coverage track, then the alignment of every
other member of the family, the proband's parents first (a de novo call is read against them).
The proband is the first affected sample with a declared parent (else the first affected
sample, else the first sample of the pedigree). The other VCFs follow, then the remaining
coverage and autozygosity tracks. Alignments are tens of megabytes each, and the browser
fetches only the window in view. A sample's track names carry its role (``<sample> (proband)
reads``), so the browser says whose reads a row shows.

Two ways the files are read:
- ``TRACKS_URI`` is set (the template turns it into ``remote_base_uri``): every expected row
  is kept and read in place under that results folder, nothing is listed;
- otherwise the rows whose file and index are present under DATA_ROOT are kept and the CLI
  uploads them at ingestion (all rows are kept when none is present, so a tables-only run
  still lists what the pipeline publishes). A bgzipped VCF needs its ``.tbi`` and an alignment
  its ``.bai``; a bigWig needs none.

Output schema:
    track_id : Utf8     `<family>.<track>` or `<sample>.<track>`, unique per file
    sample : Utf8       the sample (links to the `samples` hub); null on a family-level file
    family_id : Utf8    the family (links to the `samples` hub)
    format : Utf8       vcf / bam / bigwig
    uri : Utf8          path relative to the results folder
    name : Utf8         track label shown in the browser
    category : Utf8     track-selector folder
    order : Int64       row order the browser opens with (``order_column``)
"""

from __future__ import annotations

import re

import polars as pl

from depictio.models.models.transforms import RecipeSource

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="ped",
        glob_pattern="pedigree/*.ped",
        format="tsv",
        read_kwargs={
            "has_header": False,
            "new_columns": ["family_id", "sample_id", "father", "mother", "sex", "phenotype"],
            "infer_schema_length": 0,
        },
        input_schema={
            "family_id": pl.Utf8,
            "sample_id": pl.Utf8,
            "father": pl.Utf8,
            "mother": pl.Utf8,
            "phenotype": pl.Utf8,
        },
        optional=True,
    )
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "track_id": pl.Utf8,
    "sample": pl.Utf8,
    "family_id": pl.Utf8,
    "format": pl.Utf8,
    "uri": pl.Utf8,
    "name": pl.Utf8,
    "category": pl.Utf8,
    "order": pl.Int64,
}

# Family-level VCFs, in the order the browser opens them: (key, glob, file name, label, folder).
_FAMILY_TRACKS = (
    (
        "ranked_clinical",
        "rank_and_filter/*_snv_ranked_clinical.vcf.gz",
        "rank_and_filter/{f}_snv_ranked_clinical.vcf.gz",
        "Ranked variants, clinical",
        "Ranked variants",
    ),
    (
        "ranked_research",
        "rank_and_filter/*_snv_ranked_research.vcf.gz",
        "rank_and_filter/{f}_snv_ranked_research.vcf.gz",
        "Ranked variants, research",
        "Ranked variants",
    ),
    (
        "mobile_elements",
        "call_mobile_elements/*_mobile_elements.vcf.gz",
        "call_mobile_elements/{f}_mobile_elements.vcf.gz",
        "Mobile elements",
        "Structural",
    ),
    (
        "repeat_expansions",
        "repeat_expansions/*_repeat_expansion_stranger.vcf.gz",
        "repeat_expansions/{f}_repeat_expansion_stranger.vcf.gz",
        "Repeat expansions",
        "Structural",
    ),
)
# Per-sample files: (key, format, file name, label, folder), alignments first.
_SAMPLE_TRACKS = (
    ("alignment", "bam", "alignment/{s}_sorted_md.bam", "{s} reads", "Alignments"),
    ("coverage", "bigwig", "qc_bam/{s}_tidditcov.bw", "{s} coverage", "Coverage"),
    (
        "autozygosity",
        "bigwig",
        "annotate_snv/genome/{s}_rhocallviz/{s}_rhocallviz.bw",
        "{s} autozygosity",
        "Autozygosity",
    ),
)
_BAM = re.compile(r"^alignment/(?P<s>.+)_sorted_md\.bam$")


def _declared(parent: str | None) -> bool:
    """A PED parent cell that names somebody (0, -9, ``.`` and empty mean nobody)."""
    return parent not in (None, "", "0", "-9", ".")


def _roles(rows: list[dict]) -> dict[str, str]:
    """Sample -> its role in the family (proband, father, mother), for the track labels."""
    proband = _proband(rows)
    row = next((r for r in rows if r["sample_id"] == proband), {})
    roles = {proband: "proband"} if proband else {}
    for parent, role in ((row.get("father"), "father"), (row.get("mother"), "mother")):
        if _declared(parent):
            roles.setdefault(parent, role)
    return roles


def _proband(rows: list[dict]) -> str | None:
    """The first affected sample with a declared parent, else the first affected, else the first."""
    affected = [r for r in rows if str(r.get("phenotype")) == "2"]
    for row in affected:
        if _declared(row.get("father")) or _declared(row.get("mother")):
            return row["sample_id"]
    if affected:
        return affected[0]["sample_id"]
    return rows[0]["sample_id"] if rows else None


def _index_of(path: str) -> str | None:
    if path.endswith(".vcf.gz"):
        return path + ".tbi"
    if path.endswith(".bam"):
        return path + ".bai"
    return None  # a bigWig carries its own index


def transform(sources: dict[str, pl.DataFrame | None], context=None) -> pl.DataFrame:
    """Spell out the expected track files of every family and sample."""
    families: dict[str, list[str]] = {}  # family -> samples, pedigree order
    ped_rows: dict[str, list[dict]] = {}  # family -> its pedigree rows
    ped = sources.get("ped")
    if ped is not None:
        for row in ped.filter(~pl.col("family_id").str.starts_with("#")).iter_rows(named=True):
            samples = families.setdefault(row["family_id"], [])
            if row["sample_id"] not in samples:
                samples.append(row["sample_id"])
                ped_rows.setdefault(row["family_id"], []).append(row)

    in_place = context is None or context.reads_in_place
    if context is not None and not in_place:
        # Families the ranked VCFs name, samples the alignments name.
        for _key, pattern, name, _label, _folder in _FAMILY_TRACKS:
            suffix = name.split("{f}", 1)[1]
            for path in context.glob(pattern):
                family = path.rsplit("/", 1)[-1][: -len(suffix)] if path.endswith(suffix) else ""
                if family:
                    families.setdefault(family, [])
        known = {s for samples in families.values() for s in samples}
        loose = [m["s"] for p in context.glob("alignment/*_sorted_md.bam") if (m := _BAM.match(p))]
        loose = [s for s in loose if s not in known]
        if loose and len(families) == 1:
            families[next(iter(families))].extend(sorted(loose))
    if not families:
        raise ValueError(
            "raredisease tracks: no pedigree/*.ped and no ranked VCF under the data root; "
            "raredisease writes both"
        )

    def present(path: str) -> bool:
        """The file and its index are under the data root (an upload needs both)."""
        if context is None or not context.exists(path):
            return False
        index = _index_of(path)
        return index is None or context.exists(index)

    light: list[dict] = []
    heavy: list[dict] = []
    for family, samples in families.items():
        for key, _pattern, name, label, folder in _FAMILY_TRACKS:
            light.append(
                {
                    "track_id": f"{family}.{key}",
                    "sample": None,
                    "family_id": family,
                    "format": "vcf",
                    "uri": name.format(f=family),
                    "name": label,
                    "category": folder,
                }
            )
        roles = _roles(ped_rows.get(family, []))
        for sample in samples:
            # "<sample> reads (proband)": the role is what a reader looks for.
            who = f"{sample} ({roles[sample]})" if sample in roles else sample
            for key, fmt, name, label, folder in _SAMPLE_TRACKS:
                heavy.append(
                    {
                        "track_id": f"{sample}.{key}",
                        "sample": sample,
                        "family_id": family,
                        "format": fmt,
                        "uri": name.format(s=sample),
                        "name": label.format(s=who),
                        "category": folder,
                    }
                )
    # Alignments before the signal tracks (a stable sort keeps the sample order).
    folder_rank = {"Alignments": 0, "Coverage": 1, "Autozygosity": 2}
    heavy.sort(key=lambda r: folder_rank[r["category"]])
    rows = [*light, *heavy]
    if not in_place and any(present(r["uri"]) for r in rows):
        rows = [r for r in rows if present(r["uri"])]
    # What a variant is read against opens first: the research VCF (every ranked variant), the
    # proband's alignment and coverage, then the alignment of the rest of the family, the
    # proband's parents first (the browser shows the first `initial_tracks` rows, 5 for a trio).
    by_id = {r["track_id"]: r for r in rows}
    lead_ids: list[str] = []
    for family, samples in families.items():
        proband = _proband(ped_rows.get(family, [])) or (samples[0] if samples else None)
        lead_ids.append(
            f"{family}.ranked_research"
            if f"{family}.ranked_research" in by_id
            else f"{family}.ranked_clinical"
        )
        if proband:
            lead_ids += [f"{proband}.alignment", f"{proband}.coverage"]
            row = next((r for r in ped_rows.get(family, []) if r["sample_id"] == proband), {})
            parents = [p for p in (row.get("father"), row.get("mother")) if _declared(p)]
            others = [s for s in samples if s != proband]
            others.sort(key=lambda s: s not in parents)  # stable: parents first
            lead_ids += [f"{s}.alignment" for s in others]
    lead_order = [i for i in dict.fromkeys(lead_ids) if i in by_id]
    rows = [by_id[i] for i in lead_order] + [r for r in rows if r["track_id"] not in lead_order]
    # Ingestion reorders rows (clustering on link columns): keep the intended
    # order explicit, the browser opens on the first `initial_tracks`.
    for i, row in enumerate(rows, start=1):
        row["order"] = i
    return pl.DataFrame(rows, schema=OUTPUT_SCHEMA)
