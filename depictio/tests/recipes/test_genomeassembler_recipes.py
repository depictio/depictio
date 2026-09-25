"""The nf-core/genomeassembler pipeline recipes on synthetic QC outputs.

Every QC output is named `<sample>_<stage>`; `assemblies.py` joins the QC blocks
on that name, `stage_steps.py` expands each sample into assembly-to-scaffold
routes and `sample_status.py` keeps samplesheet rows that no QC tool reached.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from depictio.recipes import execute_recipe

SHEET = pl.DataFrame(
    {
        "sample": ["s1", "s2", "s3"],
        "strategy": ["ont", "ont", "hifi"],
        "assembler": ["flye", "flye", ""],
        "assembler_ont": ["", "", "flye"],
        "assembler_hifi": ["", "", "hifiasm"],
        "scaffold_links": ["true", "false", "false"],
        "scaffold_ragtag": ["TRUE", "false", "false"],
    }
)


def _idxstats(label: str, lengths: list[int]) -> pl.DataFrame:
    n = len(lengths) + 1
    return pl.DataFrame(
        {
            "sequence": [f"c{i}" for i in range(len(lengths))] + ["*"],
            "length": [str(v) for v in lengths] + ["0"],
            "mapped": ["0"] * n,
            "unmapped": ["0"] * n,
            "source_path": [f"{label.split('_')[0]}/QC/alignments/{label}.idxstats"] * n,
        }
    )


def _merqury(rows: dict[str, float]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "assembly_id": list(rows),
            "qv": list(rows.values()),
            "error_rate": [10 ** (-q / 10) for q in rows.values()],
            "kmer_completeness": [95.0] * len(rows),
        }
    )


def _assemblies(tmp_path: Path) -> pl.DataFrame:
    idx = pl.concat(
        [
            _idxstats("s1_assembly", [4000, 3000, 2000, 1000]),
            _idxstats("s1_links", [7000, 2000, 1000]),
            _idxstats("s1_ragtag", [10000]),
        ]
    )
    merqury = _merqury({"s1_assembly": 30.0, "s1_links": 30.0, "s1_ragtag": 30.5})
    busco = pl.DataFrame(
        {
            "assembly_id": ["s1_assembly", "s1_assembly"],
            "lineage": ["broad_odb10", "specific_odb10"],
            "complete_pct": [90.0, 80.0],
            "single_pct": [88.0, 78.0],
            "duplicated_pct": [2.0, 2.0],
            "fragmented_pct": [5.0, 10.0],
            "missing_pct": [5.0, 10.0],
            "n_markers": [255, 4596],
        }
    )
    return execute_recipe(
        "nf-core/genomeassembler/assemblies.py",
        tmp_path,
        extra_sources={
            "samplesheet": SHEET,
            "idxstats": idx,
            "merqury": merqury,
            "busco": busco,
        },
    )


def test_assemblies_joins_qc_blocks_on_the_sample_stage_name(tmp_path: Path) -> None:
    out = _assemblies(tmp_path)
    rows = {r["assembly_id"]: r for r in out.iter_rows(named=True)}

    assert list(rows) == ["s1_assembly", "s1_links", "s1_ragtag"]
    raw = rows["s1_assembly"]
    # 10 kbp over four sequences: the 3 kbp one reaches half, the unmapped `*` row is dropped.
    assert (raw["total_length"], raw["n_sequences"], raw["n50"], raw["l50"]) == (10000, 4, 3000, 2)
    assert raw["stage_class"] == "assembly" and raw["stage_rank"] == 0
    assert rows["s1_ragtag"]["stage_class"] == "scaffold"
    # The lineage with the most markers wins.
    assert raw["busco_lineage"] == "specific_odb10"
    assert raw["qc_tools"] == "samtools, merqury, busco" and raw["n_qc_tools"] == 3
    assert rows["s1_links"]["busco_complete"] is None
    assert raw["assembler_used"] == "flye"
    assert raw["scaffolders"] == "links, ragtag"
    assert raw["strategy"] == "ont"


def test_stage_steps_is_one_route_per_scaffolder(tmp_path: Path) -> None:
    assemblies = _assemblies(tmp_path)
    out = execute_recipe(
        "nf-core/genomeassembler/stage_steps.py",
        tmp_path,
        extra_sources={"assemblies": assemblies},
    )

    assert sorted(out["route"].unique().to_list()) == ["s1 to links", "s1 to ragtag"]
    ragtag = out.filter(pl.col("route") == "s1 to ragtag").sort("stage_rank")
    assert ragtag["stage"].to_list() == ["assembly", "ragtag"]
    assert ragtag["qv_gain"].to_list() == [0.0, 0.5]
    assert ragtag["n50_fold"].to_list()[-1] == pytest.approx(10000 / 3000)


def test_sample_status_keeps_samples_without_qc(tmp_path: Path) -> None:
    assemblies = _assemblies(tmp_path)
    out = execute_recipe(
        "nf-core/genomeassembler/sample_status.py",
        tmp_path,
        extra_sources={"samplesheet": SHEET, "assemblies": assemblies},
    )
    rows = {r["sample"]: r for r in out.iter_rows(named=True)}

    assert rows["s1"]["qc_status"] == "Assembly QC published"
    assert rows["s1"]["n_assemblies_assessed"] == 3
    assert rows["s1"]["best_n50"] == 10000
    assert rows["s2"]["qc_status"] == "No assembly QC"
    assert rows["s2"]["n_assemblies_assessed"] == 0
    assert rows["s3"]["assembler_used"] == "flye (ONT) + hifiasm (HiFi)"
    assert rows["s3"]["scaffolders"] is None


def test_nx_curve_matches_n50_at_fifty(tmp_path: Path) -> None:
    out = execute_recipe(
        "nf-core/genomeassembler/nx_curve.py",
        tmp_path,
        extra_sources={"idxstats": _idxstats("s1_assembly", [4000, 3000, 2000, 1000])},
    )
    row = {r["nx"]: r for r in out.iter_rows(named=True)}

    assert out.height == 101
    assert row[50.0]["sequence_length"] == 3000
    assert row[0.0]["sequence_length"] == 4000
    assert row[100.0]["sequence_length"] == 1000
    assert out["sample"].unique().to_list() == ["s1"]
