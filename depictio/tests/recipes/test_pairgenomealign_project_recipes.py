"""The nf-core/pairgenomealign genome hub (``nf-core/pairgenomealign/genomes.py``).

The hub is a pipeline recipe, not a catalog one: it joins the per-pair and
per-assembly collections the catalog tools produce, and the optional design table,
into the one row per query genome every tab filters through. The tools' own recipes
are tested in ``test_pairgenomealign_recipes.py``; here they only feed the hub.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from depictio.recipes import execute_recipe, load_recipe

T = "T1_target"
PAIRS = {"Q1": f"{T}___Q1", "Q2": f"{T}___Q2"}

MATRIX = """# format: matrix
# blocks: 10
# columns_analyzed: 1000
# P_acgt: 0.1
# K80_acgt: 0.12
\tA\tC\tG\tT\tN\t-
A\t200\t5\t20\t5\t0\t10
C\t5\t200\t5\t20\t0\t10
G\t20\t5\t200\t5\t0\t10
T\t5\t20\t5\t200\t0\t10
N\t0\t0\t0\t0\t0\t0
-\t4\t4\t4\t4\t0\t0
"""

ASSEMBLY_JSON = """{
    "total_contig": 12,
    "total_contig_length": 5000,
    "n50_contig_length": 900,
    "contig_percent_c": "20.50",
    "contig_percent_g": "21.00",
    "contig_percent_n": "0.10"
}
"""


@pytest.fixture()
def frames(tmp_path: Path) -> dict[str, pl.DataFrame]:
    """The collections the hub reads, built by the catalog recipes from a tiny run."""
    aln = tmp_path / "alignment"
    aln.mkdir()
    header = "Sample\tTotalAlignmentLength\tPercentIdentity\tPercentIdentityNoGaps\tTargetSequences\tTargetLength\tQuerySequences\tQueryLength\n"
    for i, pair in enumerate(PAIRS.values(), 1):
        (aln / f"{pair}.o2o.tsv").write_text(
            header + f"{pair}\t{500 * i}\t{90 - i}\t{95 - i}\t2\t1000\t3\t2000\n"
        )
        (aln / f"{pair}.o2o.matrix.txt").write_text(MATRIX)
    (tmp_path / "assemblyscan").mkdir()
    (tmp_path / "assemblyscan" / "Q1.json").write_text(ASSEMBLY_JSON)
    (tmp_path / "cutn").mkdir()
    (tmp_path / "cutn" / "Q1.bed").write_text("s1\t10\t110\ns1\t500\t600\ns2\t0\t10000\n")
    (tmp_path / "cutn" / "Q2.bed").write_text("")  # a gap-free assembly
    return {
        "last_split_identity": execute_recipe("last/split_identity.py", tmp_path),
        "last_split_matrix": execute_recipe("last/split_matrix.py", tmp_path),
        "assemblyscan_stats": execute_recipe("assemblyscan/stats.py", tmp_path),
        "seqtk_cutn_gaps": execute_recipe("seqtk/cutn_gaps.py", tmp_path),
        "metadata": pl.DataFrame({"sample": ["Q1", "Q2"], "clade": ["a", "b"]}),
    }


def _hub(frames: dict[str, pl.DataFrame | None], root: Path | None = None):
    """The recipe's module and its output, run through the loader's five checkpoints.

    ``frames`` is keyed by data-collection tag, as the ingest hands the dc_ref
    sources over; a missing optional one reads as absent.
    """
    module = load_recipe("nf-core/pairgenomealign/genomes.py")
    extra = {s.ref: frames[s.dc_ref] for s in module.SOURCES if frames.get(s.dc_ref) is not None}
    out = execute_recipe(
        "nf-core/pairgenomealign/genomes.py", root or Path("."), extra_sources=extra
    )
    return module, out


def test_hub_fills_gap_free_genomes_and_joins_the_design(frames: dict[str, pl.DataFrame]) -> None:
    _, hub = _hub(frames)
    assert hub["genome"].to_list() == ["Q1", "Q2"]
    assert hub["gaps"].to_list() == [3, 0]
    assert hub["clade"].to_list() == ["a", "b"]
    assert hub["n50"].to_list() == [900, None]
    # The design column follows the genome id; the run-constant keys come last.
    assert hub.columns[:2] == ["genome", "clade"]
    assert hub.columns[-2:] == ["target", "pair"]


def test_hub_survives_every_optional_source_being_absent(frames: dict[str, pl.DataFrame]) -> None:
    module, bare = _hub({"last_split_identity": frames["last_split_identity"]})
    assert bare.columns == list(module.OUTPUT_SCHEMA)
    assert bare["gaps"].null_count() == 2
    assert bare["n50"].null_count() == 2


def test_hub_design_column_cannot_replace_a_measure(frames: dict[str, pl.DataFrame]) -> None:
    frames["metadata"] = pl.DataFrame({"sample": ["Q1", "Q2"], "clade": ["a", "b"], "n50": [1, 2]})
    _, hub = _hub(frames)
    assert hub["n50"].to_list() == [900, None]
