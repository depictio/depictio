#!/usr/bin/env python3
"""
Generate multiple MultiQC parquet reports in a run-oriented structure.

Default mode produces 10 sequencing runs (run_01 .. run_10), each with 3-5
paired-end FASTQ samples and a corresponding multiqc.parquet file generated
by MultiQC 1.31, plus four companion TSV tables keyed on the canonical
``sample_id``:

  * ``sample_metadata.tsv`` — run/tissue/condition/sex/species/batch/read_length.
  * ``sample_locations.tsv`` — decimal-degree lat/lon + city/country/region;
    drives the Depictio geomap component.
  * ``sample_assays.tsv`` — assay type, library kit, sequencing platform, run
    date, instrument ID.
  * ``sample_phenotypes.tsv`` — age, BMI, smoker status, disease stage,
    diagnosis year (synthetic-control samples are left empty).

The ``--scenarios bad`` mode produces a separate ``data/bad/`` tree with five
two-run scenarios designed to exercise (or pass) the
``validate_multiqc_reports_uniform`` guard in
``depictio/api/v1/endpoints/multiqc_endpoints/uniformity.py``:

  * ``ok_pair/`` — structurally identical, validator passes.
  * ``modules_mismatch/`` — run A is fastqc-only; run B adds a samtools-stats
    log so its module set is a superset → 422 ``kind=modules``.
  * ``plots_mismatch/`` — run A is fastqc-full; run B omits the adapter-content
    sub-section so its plot key set is a subset → 422 ``kind=plots``.
  * ``samples_overlap/`` — runs share a sample name → 422 ``kind=samples``.
  * ``version_mismatch/`` — run B's ``multiqc_version`` parquet column is
    rewritten post-write to a different major.minor → 422 ``kind=version``.

Fixtures land under ``./data/bad/<scenario>/run_a|b/multiqc_data/multiqc.parquet``
— gitignored, drag/drop-friendly for manual upload testing in Depictio.

Usage:
    python generate_multi_run_reports.py [--output-dir ./data] [--seed 42]
    python generate_multi_run_reports.py --scenarios bad
    python generate_multi_run_reports.py --scenarios all
"""

from __future__ import annotations

import argparse
import csv
import math
import os
import random
import shutil
import tempfile
from pathlib import Path

import multiqc
from multiqc.core.update_config import ClConfig

# ---------------------------------------------------------------------------
# Sample definitions per run
# ---------------------------------------------------------------------------

RUN_SAMPLES: dict[str, list[str]] = {
    "run_01": ["NA12878", "NA12891", "NA12892"],
    "run_02": ["HG001", "HG002", "HG003", "HG004"],
    "run_03": ["GM12878", "GM18507", "GM19240", "K562", "HeLa"],
    "run_04": ["PATIENT_001", "PATIENT_002", "PATIENT_003"],
    "run_05": ["PATIENT_010", "PATIENT_011", "PATIENT_012", "PATIENT_013"],
    "run_06": ["DONOR_A", "DONOR_B", "DONOR_C", "DONOR_D", "DONOR_E"],
    "run_07": ["PROJ_WGS_S1", "PROJ_WGS_S2", "PROJ_WGS_S3"],
    "run_08": ["RNASEQ_LIB01", "RNASEQ_LIB02", "RNASEQ_LIB03", "RNASEQ_LIB04"],
    "run_09": ["EXOME_A1", "EXOME_A2", "EXOME_B1", "EXOME_B2", "EXOME_B3"],
    "run_10": ["CTRL_POS", "CTRL_NEG", "LIBRARY_QC1", "LIBRARY_QC2"],
}

# Per-run sequencing characteristics
RUN_PROFILES: dict[str, dict] = {
    "run_01": {"read_length": 150, "depth_range": (20_000_000, 40_000_000), "gc_center": 42},
    "run_02": {"read_length": 150, "depth_range": (25_000_000, 50_000_000), "gc_center": 44},
    "run_03": {"read_length": 150, "depth_range": (15_000_000, 35_000_000), "gc_center": 46},
    "run_04": {"read_length": 150, "depth_range": (10_000_000, 30_000_000), "gc_center": 43},
    "run_05": {"read_length": 100, "depth_range": (5_000_000, 15_000_000), "gc_center": 48},
    "run_06": {"read_length": 150, "depth_range": (30_000_000, 60_000_000), "gc_center": 41},
    "run_07": {"read_length": 150, "depth_range": (40_000_000, 80_000_000), "gc_center": 45},
    "run_08": {"read_length": 100, "depth_range": (8_000_000, 20_000_000), "gc_center": 50},
    "run_09": {"read_length": 150, "depth_range": (20_000_000, 45_000_000), "gc_center": 44},
    "run_10": {"read_length": 150, "depth_range": (1_000_000, 5_000_000), "gc_center": 47},
}

SAMPLE_METADATA: dict[str, dict[str, str]] = {
    "NA12878": {"tissue": "blood", "condition": "control", "sex": "F", "species": "human"},
    "NA12891": {"tissue": "blood", "condition": "case", "sex": "M", "species": "human"},
    "NA12892": {"tissue": "blood", "condition": "case", "sex": "F", "species": "human"},
    "HG001": {"tissue": "fibroblast", "condition": "control", "sex": "M", "species": "human"},
    "HG002": {"tissue": "fibroblast", "condition": "case", "sex": "M", "species": "human"},
    "HG003": {"tissue": "fibroblast", "condition": "case", "sex": "F", "species": "human"},
    "HG004": {"tissue": "fibroblast", "condition": "control", "sex": "F", "species": "human"},
    "GM12878": {"tissue": "lymphoblastoid", "condition": "control", "sex": "F", "species": "human"},
    "GM18507": {"tissue": "lymphoblastoid", "condition": "case", "sex": "M", "species": "human"},
    "GM19240": {"tissue": "lymphoblastoid", "condition": "case", "sex": "F", "species": "human"},
    "K562": {"tissue": "leukemia", "condition": "case", "sex": "F", "species": "human"},
    "HeLa": {"tissue": "cervical", "condition": "case", "sex": "F", "species": "human"},
    "PATIENT_001": {"tissue": "tumor", "condition": "case", "sex": "M", "species": "human"},
    "PATIENT_002": {"tissue": "tumor", "condition": "case", "sex": "F", "species": "human"},
    "PATIENT_003": {"tissue": "normal", "condition": "control", "sex": "M", "species": "human"},
    "PATIENT_010": {"tissue": "tumor", "condition": "case", "sex": "F", "species": "human"},
    "PATIENT_011": {"tissue": "tumor", "condition": "case", "sex": "M", "species": "human"},
    "PATIENT_012": {"tissue": "normal", "condition": "control", "sex": "F", "species": "human"},
    "PATIENT_013": {"tissue": "normal", "condition": "control", "sex": "M", "species": "human"},
    "DONOR_A": {"tissue": "blood", "condition": "control", "sex": "F", "species": "human"},
    "DONOR_B": {"tissue": "blood", "condition": "case", "sex": "M", "species": "human"},
    "DONOR_C": {"tissue": "blood", "condition": "case", "sex": "F", "species": "human"},
    "DONOR_D": {"tissue": "blood", "condition": "control", "sex": "M", "species": "human"},
    "DONOR_E": {"tissue": "blood", "condition": "case", "sex": "F", "species": "human"},
    "PROJ_WGS_S1": {"tissue": "brain", "condition": "case", "sex": "M", "species": "human"},
    "PROJ_WGS_S2": {"tissue": "brain", "condition": "control", "sex": "F", "species": "human"},
    "PROJ_WGS_S3": {"tissue": "brain", "condition": "case", "sex": "M", "species": "human"},
    "RNASEQ_LIB01": {"tissue": "liver", "condition": "case", "sex": "F", "species": "human"},
    "RNASEQ_LIB02": {"tissue": "liver", "condition": "control", "sex": "M", "species": "human"},
    "RNASEQ_LIB03": {"tissue": "liver", "condition": "case", "sex": "F", "species": "human"},
    "RNASEQ_LIB04": {"tissue": "liver", "condition": "control", "sex": "M", "species": "human"},
    "EXOME_A1": {"tissue": "skin", "condition": "case", "sex": "M", "species": "human"},
    "EXOME_A2": {"tissue": "skin", "condition": "control", "sex": "F", "species": "human"},
    "EXOME_B1": {"tissue": "skin", "condition": "case", "sex": "M", "species": "human"},
    "EXOME_B2": {"tissue": "skin", "condition": "control", "sex": "F", "species": "human"},
    "EXOME_B3": {"tissue": "skin", "condition": "case", "sex": "M", "species": "human"},
    "CTRL_POS": {
        "tissue": "control",
        "condition": "positive_ctrl",
        "sex": "NA",
        "species": "synthetic",
    },
    "CTRL_NEG": {
        "tissue": "control",
        "condition": "negative_ctrl",
        "sex": "NA",
        "species": "synthetic",
    },
    "LIBRARY_QC1": {
        "tissue": "control",
        "condition": "library_qc",
        "sex": "NA",
        "species": "synthetic",
    },
    "LIBRARY_QC2": {
        "tissue": "control",
        "condition": "library_qc",
        "sex": "NA",
        "species": "synthetic",
    },
}


# ---------------------------------------------------------------------------
# TSV metadata generation
# ---------------------------------------------------------------------------


def generate_metadata_tsv(output_dir: Path, rng: random.Random) -> Path:
    """Generate a sample metadata TSV with all samples across all runs.

    Returns the path to the written TSV file.
    """
    tsv_path = output_dir / "sample_metadata.tsv"
    fieldnames = [
        "sample_id",
        "run",
        "tissue",
        "condition",
        "sex",
        "species",
        "batch",
        "read_length",
    ]

    batch_idx = 0
    rows: list[dict[str, str]] = []
    for run_name in sorted(RUN_SAMPLES):
        samples = RUN_SAMPLES[run_name]
        profile = RUN_PROFILES[run_name]
        batch_idx += 1
        for sample in samples:
            meta = SAMPLE_METADATA[sample]
            rows.append(
                {
                    "sample_id": sample,
                    "run": run_name,
                    "tissue": meta["tissue"],
                    "condition": meta["condition"],
                    "sex": meta["sex"],
                    "species": meta["species"],
                    "batch": f"batch_{batch_idx}",
                    "read_length": str(profile["read_length"]),
                }
            )

    rng.shuffle(rows)

    with open(tsv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)

    return tsv_path


# ---------------------------------------------------------------------------
# Companion table generation (locations / assays / phenotypes)
# ---------------------------------------------------------------------------

# Small global city pool used to assign each sample a plausible-looking origin.
# Coordinates are decimal degrees (WGS84). Synthetic lab-control samples
# (CTRL_POS/CTRL_NEG/LIBRARY_QC*) all share the EMBL Heidelberg coordinate so
# they cluster on the geomap rather than scattering randomly.
_CITY_POOL: list[tuple[str, str, str, float, float]] = [
    # (city, country, region, lat, lon)
    ("Heidelberg", "Germany", "Europe", 49.4094, 8.6943),
    ("Cambridge", "United Kingdom", "Europe", 52.2053, 0.1218),
    ("Paris", "France", "Europe", 48.8566, 2.3522),
    ("Barcelona", "Spain", "Europe", 41.3851, 2.1734),
    ("Stockholm", "Sweden", "Europe", 59.3293, 18.0686),
    ("Boston", "United States", "North America", 42.3601, -71.0589),
    ("San Francisco", "United States", "North America", 37.7749, -122.4194),
    ("Baltimore", "United States", "North America", 39.2904, -76.6122),
    ("Toronto", "Canada", "North America", 43.6532, -79.3832),
    ("Tokyo", "Japan", "Asia", 35.6762, 139.6503),
    ("Singapore", "Singapore", "Asia", 1.3521, 103.8198),
    ("Sydney", "Australia", "Oceania", -33.8688, 151.2093),
    ("Cape Town", "South Africa", "Africa", -33.9249, 18.4241),
    ("São Paulo", "Brazil", "South America", -23.5505, -46.6333),
]
_LAB_HEIDELBERG = _CITY_POOL[0]  # EMBL Heidelberg, used for synthetic controls.

_ASSAY_PLATFORMS = [
    ("Illumina NovaSeq 6000", "NEB Ultra II DNA"),
    ("Illumina NovaSeq X Plus", "Twist Comprehensive Exome"),
    ("Illumina HiSeq 4000", "TruSeq Stranded mRNA"),
    ("Element AVITI", "NEBNext UltraExpress DNA"),
    ("Illumina NextSeq 2000", "TruSeq DNA PCR-Free"),
]

_SMOKER_STATUSES = ["never", "former", "current", "unknown"]


def _sample_origin(sample: str) -> tuple[str, str, str, float, float]:
    """Deterministically pick a city for ``sample``. Synthetic controls always
    land at the Heidelberg lab coordinate.
    """
    meta = SAMPLE_METADATA.get(sample, {})
    if meta.get("species") == "synthetic":
        return _LAB_HEIDELBERG
    # Hash the sample name into a stable pool index — same sample always lands
    # in the same city across re-runs, which makes the geomap reproducible.
    idx = (sum(ord(c) for c in sample) * 31) % len(_CITY_POOL)
    return _CITY_POOL[idx]


def _assay_for_sample(sample: str) -> str:
    """Infer assay type from the canonical sample-name prefix.

    The dev cohort encodes intent in the name (``PROJ_WGS_*``, ``RNASEQ_LIB*``,
    ``EXOME_*``, etc.). Falls back to ``wgs`` for unannotated names so the
    column is never empty.
    """
    name = sample.upper()
    if name.startswith("PROJ_WGS_"):
        return "wgs"
    if name.startswith("RNASEQ_"):
        return "rnaseq"
    if name.startswith("EXOME_"):
        return "exome"
    if name.startswith("PATIENT_"):
        return "wes"
    if name in {"CTRL_POS", "CTRL_NEG"} or name.startswith("LIBRARY_QC"):
        return "library_qc"
    return "wgs"


def generate_locations_tsv(output_dir: Path, rng: random.Random) -> Path:
    """Write ``sample_locations.tsv`` — one row per canonical sample with
    decimal-degree lat/lon, city, country, region, collection date. This is
    the table the Depictio geomap component joins against.
    """
    tsv_path = output_dir / "sample_locations.tsv"
    fieldnames = [
        "sample_id",
        "latitude",
        "longitude",
        "city",
        "country",
        "region",
        "collection_date",
    ]
    base_year = 2022
    rows: list[dict[str, str]] = []
    for sample in sorted({s for samples in RUN_SAMPLES.values() for s in samples}):
        city, country, region, lat, lon = _sample_origin(sample)
        # Jitter so multiple samples from the same city don't overlap perfectly
        # on the map. ±0.05° ≈ ±5.5km at the equator.
        jitter_lat = lat + rng.uniform(-0.05, 0.05)
        jitter_lon = lon + rng.uniform(-0.05, 0.05)
        month = rng.randint(1, 12)
        day = rng.randint(1, 28)
        rows.append(
            {
                "sample_id": sample,
                "latitude": f"{jitter_lat:.5f}",
                "longitude": f"{jitter_lon:.5f}",
                "city": city,
                "country": country,
                "region": region,
                "collection_date": f"{base_year + rng.randint(0, 3)}-{month:02d}-{day:02d}",
            }
        )

    with open(tsv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    return tsv_path


def generate_assays_tsv(output_dir: Path, rng: random.Random) -> Path:
    """Write ``sample_assays.tsv`` — sequencing/library metadata per sample,
    joinable on ``sample_id`` with the locations table and the MultiQC reports.
    """
    tsv_path = output_dir / "sample_assays.tsv"
    fieldnames = [
        "sample_id",
        "assay_type",
        "library_kit",
        "sequencing_platform",
        "sequencing_run_date",
        "instrument_id",
    ]
    rows: list[dict[str, str]] = []
    for sample in sorted({s for samples in RUN_SAMPLES.values() for s in samples}):
        platform, kit = _ASSAY_PLATFORMS[(sum(ord(c) for c in sample) * 13) % len(_ASSAY_PLATFORMS)]
        month = rng.randint(1, 12)
        day = rng.randint(1, 28)
        rows.append(
            {
                "sample_id": sample,
                "assay_type": _assay_for_sample(sample),
                "library_kit": kit,
                "sequencing_platform": platform,
                "sequencing_run_date": f"2024-{month:02d}-{day:02d}",
                "instrument_id": f"INST_{rng.randint(1, 8):02d}",
            }
        )

    with open(tsv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    return tsv_path


def generate_phenotypes_tsv(output_dir: Path, rng: random.Random) -> Path:
    """Write ``sample_phenotypes.tsv`` — clinical/demographic features per
    sample. Synthetic-control samples get empty values for the human-only
    columns so downstream joins surface them as nulls rather than fake data.
    """
    tsv_path = output_dir / "sample_phenotypes.tsv"
    fieldnames = [
        "sample_id",
        "age_years",
        "bmi",
        "smoker_status",
        "disease_stage",
        "diagnosis_year",
    ]
    rows: list[dict[str, str]] = []
    for sample in sorted({s for samples in RUN_SAMPLES.values() for s in samples}):
        meta = SAMPLE_METADATA.get(sample, {})
        if meta.get("species") == "synthetic":
            rows.append(
                {
                    "sample_id": sample,
                    "age_years": "",
                    "bmi": "",
                    "smoker_status": "",
                    "disease_stage": "",
                    "diagnosis_year": "",
                }
            )
            continue
        age = rng.randint(18, 82)
        bmi = rng.uniform(18.5, 35.0)
        stage = (
            ""
            if meta.get("condition") in {"control", "positive_ctrl", "negative_ctrl", "library_qc"}
            else rng.choice(["I", "II", "III", "IV"])
        )
        rows.append(
            {
                "sample_id": sample,
                "age_years": str(age),
                "bmi": f"{bmi:.1f}",
                "smoker_status": rng.choice(_SMOKER_STATUSES),
                "disease_stage": stage,
                "diagnosis_year": (str(2024 - rng.randint(0, 12)) if stage else ""),
            }
        )

    with open(tsv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    return tsv_path


# ---------------------------------------------------------------------------
# FastQC data generation
# ---------------------------------------------------------------------------


def _generate_quality_per_base(read_length: int, is_r2: bool) -> str:
    """Generate Per base sequence quality module data."""
    lines = [">>Per base sequence quality\tpass"]
    lines.append(
        "#Base\tMean\tMedian\tLower Quartile\tUpper Quartile\t10th Percentile\t90th Percentile"
    )

    base_quality = 35.0 if not is_r2 else 33.0
    for pos in range(1, read_length + 1):
        # Quality drops slightly at the start and more toward the end
        if pos <= 5:
            decay = (5 - pos) * 0.4
        elif pos > read_length * 0.8:
            decay = (pos - read_length * 0.8) / (read_length * 0.2) * 6.0
        else:
            decay = 0.0
        mean_q = base_quality - decay + random.gauss(0, 0.3)
        mean_q = max(20.0, min(40.0, mean_q))
        median_q = mean_q + random.uniform(0, 1)
        lq = mean_q - random.uniform(1.5, 3.0)
        uq = mean_q + random.uniform(0.5, 2.0)
        p10 = mean_q - random.uniform(3.0, 6.0)
        p90 = mean_q + random.uniform(1.0, 3.0)
        lines.append(
            f"{pos}\t{mean_q:.1f}\t{median_q:.1f}\t{lq:.1f}\t{uq:.1f}\t{p10:.1f}\t{p90:.1f}"
        )

    lines.append(">>END_MODULE")
    return "\n".join(lines)


def _generate_quality_per_seq() -> str:
    """Generate Per sequence quality scores module data."""
    lines = [">>Per sequence quality scores\tpass"]
    lines.append("#Quality\tCount")
    # Bell curve peaking around Q36
    for q in range(2, 41):
        count = max(0.0, math.exp(-0.5 * ((q - 36) / 3.0) ** 2) * 50000)
        count += random.uniform(0, count * 0.05)
        lines.append(f"{q}\t{count:.1f}")
    lines.append(">>END_MODULE")
    return "\n".join(lines)


def _generate_base_content(read_length: int) -> str:
    """Generate Per base sequence content module data."""
    lines = [">>Per base sequence content\tpass"]
    lines.append("#Base\tG\tA\tT\tC")
    for pos in range(1, read_length + 1):
        # Slight bias in first few bases (typical Illumina)
        bias = max(0, (10 - pos) * 0.3)
        g = 25.0 + random.gauss(0, 0.3) + bias * 0.5
        a = 25.0 + random.gauss(0, 0.3) - bias * 0.3
        t = 25.0 + random.gauss(0, 0.3) - bias * 0.1
        c = 100.0 - g - a - t
        lines.append(f"{pos}\t{g:.1f}\t{a:.1f}\t{t:.1f}\t{c:.1f}")
    lines.append(">>END_MODULE")
    return "\n".join(lines)


def _generate_gc_content(gc_center: int) -> str:
    """Generate Per sequence GC content module data."""
    lines = [">>Per sequence GC content\tpass"]
    lines.append("#GC Content\tCount")
    for gc in range(0, 101):
        count = max(0.0, math.exp(-0.5 * ((gc - gc_center) / 8.0) ** 2) * 30000)
        count += random.uniform(0, max(1.0, count * 0.02))
        lines.append(f"{gc}\t{count:.1f}")
    lines.append(">>END_MODULE")
    return "\n".join(lines)


def _generate_seq_length_dist(read_length: int) -> str:
    """Generate Sequence Length Distribution module data."""
    lines = [">>Sequence Length Distribution\tpass"]
    lines.append("#Length\tCount")
    lines.append(f"{read_length}\t{random.randint(1000000, 50000000)}.0")
    lines.append(">>END_MODULE")
    return "\n".join(lines)


def _generate_duplication(dedup_pct: float) -> str:
    """Generate Sequence Duplication Levels module data."""
    lines = [">>Sequence Duplication Levels\tpass"]
    lines.append(f"#Total Deduplicated Percentage\t{dedup_pct:.1f}")
    lines.append("#Duplication Level\tPercentage of deduplicated\tPercentage of total")
    remaining = 100.0
    for level in [
        1,
        2,
        3,
        4,
        5,
        6,
        7,
        8,
        9,
        10,
        ">10",
        ">50",
        ">100",
        ">500",
        ">1k",
        ">5k",
        ">10k+",
    ]:
        if level == 1:
            pct_dedup = dedup_pct
        elif isinstance(level, int) and level <= 5:
            pct_dedup = random.uniform(1.0, (100 - dedup_pct) / 3)
        else:
            pct_dedup = random.uniform(0.0, 2.0)
        pct_dedup = min(pct_dedup, remaining)
        remaining -= pct_dedup
        pct_total = pct_dedup * (int(level) if isinstance(level, int) else 100) / 100
        lines.append(f"{level}\t{pct_dedup:.2f}\t{pct_total:.2f}")
    lines.append(">>END_MODULE")
    return "\n".join(lines)


def _generate_adapter_content(read_length: int) -> str:
    """Generate Adapter Content module data."""
    lines = [">>Adapter Content\tpass"]
    lines.append(
        "#Position\tIllumina Universal Adapter\tIllumina Small RNA 3' Adapter"
        "\tIllumina Small RNA 5' Adapter\tNextera Transposase Sequence"
    )
    for pos in range(1, read_length + 1):
        # Adapter contamination increases toward end of read
        frac = pos / read_length
        univ = frac**3 * random.uniform(0.5, 2.0)
        small3 = frac**4 * random.uniform(0.0, 0.3)
        small5 = frac**4 * random.uniform(0.0, 0.1)
        nextera = frac**3 * random.uniform(0.0, 0.5)
        lines.append(f"{pos}\t{univ:.4f}\t{small3:.4f}\t{small5:.4f}\t{nextera:.4f}")
    lines.append(">>END_MODULE")
    return "\n".join(lines)


# Names accepted by the ``skip`` argument of ``_make_fastqc_sections``. These
# correspond to optional FastQC sub-modules — omitting one shrinks the plot
# key set in the resulting MultiQC parquet, which is exactly what the
# ``plots_mismatch`` bad-scenario fixture relies on.
FASTQC_SECTION_NAMES = frozenset(
    {
        "quality_per_base",
        "quality_per_seq",
        "base_content",
        "gc_content",
        "seq_length_dist",
        "duplication",
        "adapter",
    }
)


def _make_fastqc_sections(
    read_length: int,
    gc_pct: int,
    is_r2: bool,
    dedup_pct: float,
    *,
    skip: frozenset[str] | set[str] = frozenset(),
) -> list[str]:
    """Build the ordered list of FastQC sub-section strings, honouring ``skip``.

    Section names match :data:`FASTQC_SECTION_NAMES`. Anything in ``skip`` is
    omitted from the returned list — used by the ``plots_mismatch`` fixture to
    drop e.g. the adapter content section.
    """
    sections: list[str] = []
    if "quality_per_base" not in skip:
        sections.append(_generate_quality_per_base(read_length, is_r2))
    if "quality_per_seq" not in skip:
        sections.append(_generate_quality_per_seq())
    if "base_content" not in skip:
        sections.append(_generate_base_content(read_length))
    if "gc_content" not in skip:
        sections.append(_generate_gc_content(gc_pct))
    if "seq_length_dist" not in skip:
        sections.append(_generate_seq_length_dist(read_length))
    if "duplication" not in skip:
        sections.append(_generate_duplication(dedup_pct))
    if "adapter" not in skip:
        sections.append(_generate_adapter_content(read_length))
    return sections


def generate_fastqc_data(
    sample_name: str,
    read: int,
    total_sequences: int,
    read_length: int,
    gc_pct: int,
    *,
    skip_sections: frozenset[str] | set[str] = frozenset(),
) -> str:
    """Generate a complete fastqc_data.txt for one FASTQ file.

    ``skip_sections`` is an optional set of FastQC sub-section names to omit
    from the output (see :data:`FASTQC_SECTION_NAMES`). Default behaviour
    matches the original — every section is emitted.
    """
    is_r2 = read == 2
    filename = f"{sample_name}_R{read}.fastq.gz"
    dedup_pct = random.uniform(70.0, 95.0)

    basic_stats = (
        f"##FastQC\t0.12.1\n"
        f">>Basic Statistics\tpass\n"
        f"#Measure\tValue\n"
        f"Filename\t{filename}\n"
        f"File type\tConventional base calls\n"
        f"Encoding\tSanger / Illumina 1.9\n"
        f"Total Sequences\t{total_sequences}\n"
        f"Sequences flagged as poor quality\t{random.randint(0, int(total_sequences * 0.001))}\n"
        f"Sequence length\t{read_length}\n"
        f"%GC\t{gc_pct}\n"
        f">>END_MODULE"
    )

    sections = [basic_stats]
    sections.extend(
        _make_fastqc_sections(read_length, gc_pct, is_r2, dedup_pct, skip=skip_sections)
    )
    return "\n".join(sections) + "\n"


# ---------------------------------------------------------------------------
# Run generation
# ---------------------------------------------------------------------------


def generate_run(
    run_name: str,
    samples: list[str],
    profile: dict,
    output_dir: Path,
    rng: random.Random,
) -> Path:
    """Generate FastQC data for a run and produce a MultiQC parquet."""
    return _generate_run_with_overrides(run_name, samples, profile, output_dir, rng)


def _generate_run_with_overrides(
    run_name: str,
    samples: list[str],
    profile: dict,
    output_dir: Path,
    rng: random.Random,
    *,
    skip_fastqc_sections: frozenset[str] | set[str] = frozenset(),
    extra_module_files: dict[str, str] | None = None,
    version_override: str | None = None,
) -> Path:
    """Generate FastQC data for a run and produce a MultiQC parquet.

    ``skip_fastqc_sections`` is forwarded to :func:`generate_fastqc_data` so a
    sub-set of FastQC plot keys can be omitted (drives the ``plots_mismatch``
    bad scenario).

    ``extra_module_files`` is a mapping of relative filename → text content to
    drop into the MultiQC input directory alongside the FastQC outputs. Used to
    inject e.g. a samtools-stats log so MultiQC picks up a second top-level
    module (drives the ``modules_mismatch`` bad scenario).

    ``version_override`` rewrites the ``multiqc_version`` column of the emitted
    parquet to a fake value (drives the ``version_mismatch`` bad scenario:
    locally we only have one MultiQC release installed, so we can't legitimately
    produce two parquets with different writer versions — we forge it here).
    """
    read_length: int = profile["read_length"]
    depth_lo, depth_hi = profile["depth_range"]
    gc_center: int = profile["gc_center"]

    tmp_input = tempfile.mkdtemp(prefix=f"mqc_input_{run_name}_")

    try:
        for sample in samples:
            total_seqs = rng.randint(depth_lo, depth_hi)
            gc_pct = gc_center + rng.randint(-3, 3)

            for read_num in (1, 2):
                fastqc_dir = os.path.join(tmp_input, f"{sample}_R{read_num}_fastqc")
                os.makedirs(fastqc_dir)
                data = generate_fastqc_data(
                    sample,
                    read_num,
                    total_seqs,
                    read_length,
                    gc_pct,
                    skip_sections=skip_fastqc_sections,
                )
                with open(os.path.join(fastqc_dir, "fastqc_data.txt"), "w") as f:
                    f.write(data)

        for rel_name, content in (extra_module_files or {}).items():
            extra_path = Path(tmp_input) / rel_name
            extra_path.parent.mkdir(parents=True, exist_ok=True)
            extra_path.write_text(content)

        run_output = output_dir / run_name
        run_output.mkdir(parents=True, exist_ok=True)

        multiqc.reset()
        cfg = ClConfig(
            output_dir=str(run_output),
            force=True,
            quiet=True,
            make_report=False,
            no_megaqc_upload=True,
        )
        multiqc.run(tmp_input, cfg=cfg)

        parquet_path = run_output / "multiqc_data" / "multiqc.parquet"

        if version_override is not None:
            _rewrite_parquet_version(parquet_path, version_override)

        return parquet_path

    finally:
        shutil.rmtree(tmp_input, ignore_errors=True)


def _rewrite_parquet_version(parquet_path: Path, new_version: str) -> None:
    """Overwrite every non-null entry in the ``multiqc_version`` column.

    MultiQC stores its writer version in a dedicated parquet column (one row
    per anchor, populated only on the header row in current releases). Rewriting
    that column lets us simulate cross-version uploads without needing two
    different MultiQC installs side by side.
    """
    import polars as pl

    df = pl.read_parquet(parquet_path)
    df = df.with_columns(
        pl.when(pl.col("multiqc_version").is_not_null())
        .then(pl.lit(new_version))
        .otherwise(pl.col("multiqc_version"))
        .alias("multiqc_version")
    )
    df.write_parquet(parquet_path)


# ---------------------------------------------------------------------------
# Samtools stats stub (for modules_mismatch scenario)
# ---------------------------------------------------------------------------


def _generate_samtools_stats_stub(sample: str, rng: random.Random) -> str:
    """Build a minimal but parser-valid ``samtools stats`` text output.

    MultiQC's detector keys on ``# This file was produced by samtools stats``
    (see ``multiqc/search_patterns.yaml``) and the stats parser only requires a
    handful of ``SN<tab>field:<tab>value`` lines to register the sample. We
    emit a realistic-looking subset; values are randomized per sample so the
    bargraphs render varied bars when the fixture is loaded into Depictio.
    """
    total = rng.randint(10_000_000, 40_000_000)
    mapped = int(total * rng.uniform(0.85, 0.99))
    duplicates = int(mapped * rng.uniform(0.05, 0.20))
    properly_paired = int(mapped * rng.uniform(0.80, 0.98))
    error_rate = rng.uniform(0.001, 0.01)
    insert_mean = rng.uniform(300.0, 500.0)
    insert_sd = rng.uniform(50.0, 90.0)

    lines = [
        "# This file was produced by samtools stats (1.17+htslib-1.17) "
        "and can be plotted using plot-bamstats",
        f"# This file was generated for sample: {sample}",
        "# CHK, Checksum\t[2]Read Names\t[3]Sequences\t[4]Qualities",
        f"SN\traw total sequences:\t{total}",
        "SN\tfiltered sequences:\t0",
        f"SN\tsequences:\t{total}",
        "SN\tis sorted:\t1",
        f"SN\t1st fragments:\t{total // 2}",
        f"SN\tlast fragments:\t{total // 2}",
        f"SN\treads mapped:\t{mapped}",
        f"SN\treads mapped and paired:\t{properly_paired}",
        f"SN\treads unmapped:\t{total - mapped}",
        f"SN\treads properly paired:\t{properly_paired}",
        f"SN\treads paired:\t{total}",
        f"SN\treads duplicated:\t{duplicates}",
        f"SN\treads MQ0:\t{int(mapped * 0.01)}",
        "SN\treads QC failed:\t0",
        "SN\tnon-primary alignments:\t0",
        f"SN\ttotal length:\t{total * 150}",
        f"SN\tbases mapped:\t{mapped * 150}",
        f"SN\tbases mapped (cigar):\t{mapped * 148}",
        "SN\tbases trimmed:\t0",
        f"SN\tbases duplicated:\t{duplicates * 150}",
        f"SN\tmismatches:\t{int(mapped * 150 * error_rate)}",
        f"SN\terror rate:\t{error_rate:.6e}",
        "SN\taverage length:\t150",
        "SN\tmaximum length:\t150",
        "SN\taverage quality:\t36.0",
        f"SN\tinsert size average:\t{insert_mean:.1f}",
        f"SN\tinsert size standard deviation:\t{insert_sd:.1f}",
        f"SN\tinward oriented pairs:\t{properly_paired // 2}",
        f"SN\toutward oriented pairs:\t{int(properly_paired * 0.001)}",
        "SN\tpairs with other orientation:\t0",
        f"SN\tpairs on different chromosomes:\t{int(properly_paired * 0.005)}",
    ]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Bad-scenario fixtures (failing-uniformity-check artefacts)
# ---------------------------------------------------------------------------


_BAD_PROFILE = {"read_length": 150, "depth_range": (1_000_000, 5_000_000), "gc_center": 44}


def generate_bad_scenarios(output_dir: Path, rng: random.Random) -> dict[str, Path]:
    """Produce five two-run scenarios under ``<output_dir>/bad/``.

    Returns a mapping ``{scenario_name: scenario_dir}`` covering one passing
    case (``ok_pair``) and four that trip ``validate_multiqc_reports_uniform``
    (``modules_mismatch``, ``plots_mismatch``, ``samples_overlap``,
    ``version_mismatch``). Each scenario writes
    ``<scenario>/run_a/multiqc_data/multiqc.parquet`` and ``run_b/…``.

    ``version_mismatch`` rewrites the ``multiqc_version`` column of run_b's
    parquet so the file genuinely encodes a different major.minor than run_a.
    That makes the scenario drag-droppable into the UI for end-to-end 422
    verification, not just an in-test mutation.
    """
    bad_root = output_dir / "bad"
    bad_root.mkdir(parents=True, exist_ok=True)
    scenarios: dict[str, Path] = {}

    def _run(scenario: str, run_name: str, samples: list[str], **overrides) -> None:
        scenario_dir = bad_root / scenario
        _generate_run_with_overrides(
            run_name=run_name,
            samples=samples,
            profile=_BAD_PROFILE,
            output_dir=scenario_dir,
            rng=rng,
            **overrides,
        )
        scenarios[scenario] = scenario_dir

    # 1. ok_pair — structurally identical, validator passes.
    _run("ok_pair", "run_a", ["OK_A1", "OK_A2"])
    _run("ok_pair", "run_b", ["OK_B1", "OK_B2"])

    # 2. modules_mismatch — run_b adds a samtools-stats log so its module
    # set is a strict superset of run_a's.
    _run("modules_mismatch", "run_a", ["MOD_A1", "MOD_A2"])
    samtools_files = {
        f"{sample}.stats.txt": _generate_samtools_stats_stub(sample, rng)
        for sample in ["MOD_B1", "MOD_B2"]
    }
    _run(
        "modules_mismatch",
        "run_b",
        ["MOD_B1", "MOD_B2"],
        extra_module_files=samtools_files,
    )

    # 3. plots_mismatch — same modules (fastqc only) but run_b omits the
    # adapter-content sub-section so its plot key set is a strict subset.
    _run("plots_mismatch", "run_a", ["PLT_A1", "PLT_A2"])
    _run(
        "plots_mismatch",
        "run_b",
        ["PLT_B1", "PLT_B2"],
        skip_fastqc_sections=frozenset({"adapter"}),
    )

    # 4. samples_overlap — two runs share a sample name.
    _run("samples_overlap", "run_a", ["NA12878", "NA12891"])
    _run("samples_overlap", "run_b", ["NA12878", "NA12892"])

    # 5. version_mismatch — run_b's parquet has its multiqc_version column
    # rewritten to a different major.minor, so the validator's version check
    # fires from real on-disk data (no in-test override needed).
    _run("version_mismatch", "run_a", ["VER_A1", "VER_A2"])
    _run("version_mismatch", "run_b", ["VER_B1", "VER_B2"], version_override="1.21")

    return scenarios


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _run_good_scenarios(output_dir: Path, rng: random.Random) -> None:
    """Generate the 10 baseline runs + metadata TSV under ``output_dir``."""
    print(f"Generating 10 MultiQC runs in {output_dir}\n")
    print(f"{'Run':<12} {'Samples':>8} {'Paired FQs':>11} {'Parquet Size':>13}")
    print("-" * 48)

    for run_name in sorted(RUN_SAMPLES):
        samples = RUN_SAMPLES[run_name]
        profile = RUN_PROFILES[run_name]

        parquet_path = generate_run(run_name, samples, profile, output_dir, rng)

        if parquet_path.exists():
            size_kb = parquet_path.stat().st_size / 1024
            print(f"{run_name:<12} {len(samples):>8} {len(samples) * 2:>11} {size_kb:>10.1f} KB")
        else:
            print(f"{run_name:<12} {len(samples):>8} {len(samples) * 2:>11}   FAILED")

    print(f"\nDone. Parquet files at: {output_dir}/run_*/multiqc_data/multiqc.parquet")

    tsv_path = generate_metadata_tsv(output_dir, rng)
    print(f"\nMetadata TSV: {tsv_path} ({sum(1 for _ in open(tsv_path)) - 1} samples)")

    # Companion tables — share sample_id with the MultiQC reports and the
    # metadata TSV. ``sample_locations.tsv`` drives the geomap component;
    # ``sample_assays.tsv`` adds sequencing/library dimensions; ``sample_phenotypes.tsv``
    # carries numeric clinical features for joining with QC stats.
    locations_path = generate_locations_tsv(output_dir, rng)
    assays_path = generate_assays_tsv(output_dir, rng)
    phenotypes_path = generate_phenotypes_tsv(output_dir, rng)
    print(f"Locations TSV (geomap): {locations_path}")
    print(f"Assays TSV: {assays_path}")
    print(f"Phenotypes TSV: {phenotypes_path}")

    try:
        import polars as pl

        print("\n--- Verification ---")
        for run_name in sorted(RUN_SAMPLES):
            pq = output_dir / run_name / "multiqc_data" / "multiqc.parquet"
            if pq.exists():
                df = pl.read_parquet(pq)
                sample_col = df.filter(pl.col("sample").is_not_null())["sample"].unique().to_list()
                print(f"{run_name}: {df.shape[0]} rows, samples: {sorted(sample_col)}")
    except ImportError:
        pass


def _run_bad_scenarios(output_dir: Path, rng: random.Random) -> None:
    """Generate the five uniformity-check fixtures under ``output_dir/bad/``."""
    print(f"Generating bad scenarios in {output_dir}/bad\n")
    scenarios = generate_bad_scenarios(output_dir, rng)

    print(f"{'Scenario':<22} {'Runs':>5} {'Parquets present':>18}")
    print("-" * 50)
    for name, scenario_dir in scenarios.items():
        parquets = sorted(scenario_dir.glob("run_*/multiqc_data/multiqc.parquet"))
        print(f"{name:<22} {len(list(scenario_dir.glob('run_*'))):>5} {len(parquets):>18}")

    print(f"\nDone. Bad-scenario fixtures at: {output_dir}/bad/<scenario>/run_*/multiqc_data/")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate multi-run MultiQC parquet reports")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).parent / "data",
        help="Output directory for run data (default: ./data)",
    )
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility")
    parser.add_argument(
        "--scenarios",
        choices=["good", "bad", "all"],
        default="good",
        help=(
            "Which fixtures to generate: 'good' (default, 10 baseline runs), "
            "'bad' (uniformity-check failures), or 'all' (both)."
        ),
    )
    args = parser.parse_args()

    rng = random.Random(args.seed)
    random.seed(args.seed)

    output_dir: Path = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.scenarios in ("good", "all"):
        _run_good_scenarios(output_dir, rng)
    if args.scenarios in ("bad", "all"):
        _run_bad_scenarios(output_dir, rng)


if __name__ == "__main__":
    main()
