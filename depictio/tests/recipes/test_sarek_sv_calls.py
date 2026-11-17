"""sarek's structural-variant collection: ``sv_to_long`` and the ``sv_calls`` recipe.

The synthetic rows follow the records Manta writes (a deletion with SVLEN, a
breakend pair that names each other with MATEID, an insertion, a duplication);
the last test reads the real Manta VCFs of the megatest run when they are on disk.
"""

from __future__ import annotations

import gzip
from pathlib import Path

import polars as pl
import pytest

from depictio.recipes import load_recipe, validate_schema
from depictio.recipes.lib.vcf import SV_COLUMNS, sv_to_long, vcf_to_long

VERSION = "3.10.0"
MEGATEST = Path.home() / "Data/depictio-nfcore/sarek/3.10.0/megatest"
MANTA_75M = MEGATEST / "variant_calling/manta/NA12878_75M/NA12878_75M.manta.diploid_sv.vcf.gz"

MANTA = "variant_calling/manta/S1/S1.manta.diploid_sv.vcf.gz"
CANDIDATE = "variant_calling/manta/S1/S1.manta.candidate_sv.vcf.gz"
HAPLOTYPECALLER = "variant_calling/haplotypecaller/S1/S1.haplotypecaller.filtered.vcf.gz"


def _line(*fields: str) -> str:
    return "\t".join(fields)


def _raw(rows: list[tuple[str, str]]) -> pl.DataFrame:
    return pl.DataFrame(
        {"raw_line": [line for line, _ in rows], "source_path": [path for _, path in rows]},
        schema={"raw_line": pl.Utf8, "source_path": pl.Utf8},
    )


def _manta_rows(path: str = MANTA) -> list[tuple[str, str]]:
    return [
        (
            _line(
                "chr1",
                "1000",
                "MantaDEL:1:0:0:0:0:0",
                "A",
                "<DEL>",
                "300",
                "PASS",
                "END=1500;SVTYPE=DEL;SVLEN=-500",
                "GT",
                "0/1",
            ),
            path,
        ),
        (
            _line(
                "chr1",
                "5000",
                "MantaBND:2:0:1:0:0:0:0",
                "T",
                "T]chr2:700]",
                "120",
                "MaxMQ0Frac",
                "SVTYPE=BND;MATEID=MantaBND:2:0:1:0:0:0:1;IMPRECISE",
                "GT",
                "0/1",
            ),
            path,
        ),
        (
            _line(
                "chr2",
                "700",
                "MantaBND:2:0:1:0:0:0:1",
                "G",
                "G]chr1:5000]",
                "120",
                "MaxMQ0Frac",
                "SVTYPE=BND;MATEID=MantaBND:2:0:1:0:0:0:0;IMPRECISE",
                "GT",
                "0/1",
            ),
            path,
        ),
        (
            _line(
                "chr3",
                "200",
                "MantaINS:3:0:0:0:0:0",
                "C",
                "<INS>",
                ".",
                "PASS",
                "END=200;SVTYPE=INS;SVLEN=80",
                "GT",
                "1/1",
            ),
            path,
        ),
        (
            _line(
                "chr3",
                "900",
                "MantaDUP:4:0:0:0:0:0",
                "T",
                "<DUP:TANDEM>",
                "55",
                "PASS",
                "END=1900;SVTYPE=DUP;SVLEN=1000",
                "GT",
                "0/1",
            ),
            path,
        ),
    ]


def test_sv_to_long_parses_the_manta_records() -> None:
    df = sv_to_long(_raw(_manta_rows()))
    assert df.columns == SV_COLUMNS
    by_type = {row["svtype"]: row for row in df.to_dicts() if row["chrom"] != "chr2"}
    deletion = by_type["DEL"]
    assert (deletion["sample"], deletion["caller"]) == ("S1", "manta")
    assert (deletion["pos"], deletion["end"]) == (1000, 1500)
    assert (deletion["svlen"], deletion["size_bp"]) == (-500, 500)
    assert deletion["is_pass"] is True
    assert deletion["imprecise"] is False
    assert deletion["qual"] == 300.0
    # An insertion ends where it starts; a "." QUAL is null, not zero.
    assert by_type["INS"]["end"] == 200
    assert by_type["INS"]["qual"] is None
    assert (by_type["DUP"]["end"], by_type["DUP"]["size_bp"]) == (1900, 1000)


def test_a_breakend_pair_counts_as_one_event() -> None:
    df = sv_to_long(_raw(_manta_rows()))
    bnd = df.filter(pl.col("svtype") == "BND").sort("chrom")
    assert bnd.height == 2
    assert bnd["primary"].to_list() == [True, False]
    first = bnd.row(0, named=True)
    assert (first["mate_chrom"], first["mate_pos"]) == ("chr2", 700)
    # A breakend has two loci, so no end and no length, and it failed a filter.
    assert first["end"] is None and first["size_bp"] is None
    assert first["is_pass"] is False and first["imprecise"] is True
    assert df.filter(pl.col("primary")).height == 4


def test_small_variant_rows_are_unchanged_by_the_sv_columns() -> None:
    raw = _raw(
        [
            (
                _line("chr1", "10", ".", "A", "G", "50", "PASS", "DP=30", "GT", "0/1"),
                HAPLOTYPECALLER,
            )
        ]
    )
    out = vcf_to_long(raw)
    assert out.height == 1
    assert out["variant_type"].to_list() == ["SNP"]
    assert out["pos"].to_list() == [10]


def _recipe(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    module = load_recipe("nf-core/sarek/sv_calls.py", VERSION)
    out = module.transform(sources)
    validate_schema(
        out, module.OUTPUT_SCHEMA, "sv_calls", getattr(module, "OPTIONAL_OUTPUT_SCHEMA", None)
    )
    return out


def test_the_recipe_keeps_the_sv_callsets_only() -> None:
    small = (
        _line("chr1", "10", ".", "A", "G", "50", "PASS", "DP=30", "GT", "0/1"),
        HAPLOTYPECALLER,
    )
    raw = _raw(_manta_rows() + _manta_rows(CANDIDATE) + [small])
    out = _recipe({"raw": raw})
    assert out.height == 5
    assert set(out["caller"].to_list()) == {"manta"}
    assert out["sample"].unique().to_list() == ["S1"]


def test_one_chord_link_per_event_none_for_an_insertion() -> None:
    out = _recipe({"raw": _raw(_manta_rows())})
    linked = out.filter(pl.col("link_pos").is_not_null())
    # Every primary record but an insertion: the far end of the event.
    expected = out.filter(pl.col("primary") & (pl.col("svtype") != "INS"))
    assert linked.height == expected.height
    bnd = linked.filter(pl.col("svtype") == "BND")
    assert bnd["link_chrom"].to_list() == bnd["mate_chrom"].to_list()
    other = linked.filter(pl.col("svtype") != "BND")
    assert other["link_pos"].to_list() == other["end"].to_list()
    assert other["link_chrom"].to_list() == other["chrom"].to_list()


def test_a_run_without_an_sv_caller_raises_so_the_optional_collection_is_skipped() -> None:
    small = (
        _line("chr1", "10", ".", "A", "G", "50", "PASS", "DP=30", "GT", "0/1"),
        HAPLOTYPECALLER,
    )
    with pytest.raises(ValueError, match="no VCF of a structural-variant caller"):
        _recipe({"raw": _raw([small])})


@pytest.mark.skipif(not MANTA_75M.exists(), reason="megatest run not on disk")
def test_megatest_manta_75m_counts() -> None:
    with gzip.open(MANTA_75M, "rt") as handle:
        lines = [line.rstrip("\n") for line in handle if not line.startswith("#")]
    raw = _raw(
        [
            (line, "variant_calling/manta/NA12878_75M/NA12878_75M.manta.diploid_sv.vcf.gz")
            for line in lines
        ]
    )
    out = _recipe({"raw": raw})
    counts = out.group_by("svtype").len().sort("svtype")
    assert dict(zip(counts["svtype"], counts["len"], strict=True)) == {
        "BND": 18,
        "DEL": 25,
        "DUP": 8,
        "INS": 6,
    }
    assert out.filter(pl.col("svtype") == "BND")["primary"].sum() == 9
