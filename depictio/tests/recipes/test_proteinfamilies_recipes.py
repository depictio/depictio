"""nf-core/proteinfamilies recipes on a small inline family run.

One family of four match states and three members (a representative that
starts at residue 5 of a longer protein, a full-length member and a fragment),
written the way the pipeline writes it: the ``hmmbuild`` HMM, the ``hmmalign``
Stockholm alignment, the FAMSA aligned FASTA, the member roster, the family
metadata table, the clustering distribution and a CMAPLE tree. Every recipe runs
through the input check, ``transform()`` and the output check, on raw scans
shaped like the ones the template declares (one file line per row in ``raw``).
"""

from __future__ import annotations

import polars as pl
import pytest

from depictio.recipes import load_recipe, validate_schema, validate_sources
from depictio.recipes.lib.hmm import HmmModel, format_hmm
from depictio.recipes.lib.protein_families import (
    parse_hmm,
    representative_positions,
    representatives,
)

LETTERS = tuple("ACDEFGHIKLMNPQRSTVWY")
FAMILY = "run1_1"
SAMPLE = "run1"
REP = "rep/5-9"

#: The family alignment hmmalign wrote: 5 columns, 4 of them match states (RF 'x');
#: the representative has an insert residue in the third column and its row name
#: carries the range of the longer protein it was cut from.
STOCKHOLM = f"""\
# STOCKHOLM 1.0

#=GC RF  xx.xx
{REP}    ACgDE
full     AC.DE
frag     --.DE
none     --.--
//
"""

#: The same family as FAMSA aligned it: representative first.
ALIGNED_FASTA = """\
>rep/5-9
ACGDE
>full
AC-DE
>frag
--GDE
"""

NEWICK = "((a:0.1,b:0.2):0.05,c:0.3);\n"


def _dist(top: str) -> list[float]:
    rest = 0.2 / (len(LETTERS) - 1)
    return [0.8 if letter == top else rest for letter in LETTERS]


def _hmm(name: str = FAMILY, nseq: int = 7, letters: str = "ACDE") -> str:
    model = HmmModel(
        name=name,
        length=4,
        alphabet=LETTERS,
        match_emissions=[_dist(letter) for letter in letters],
        insert_emissions=[_dist("G")] * 5,
        transitions=[[0.9, 0.05, 0.05, 0.6, 0.4, 1.0, 0.0]] * 5,
        consensus=list(letters),
        rf=["x"] * 4,
        nseq=nseq,
        effn=2.5,
    )
    return format_hmm(model)


def raw(files: dict[str, str]) -> pl.DataFrame:
    """A text scan: one line per row in ``raw`` (blank lines are nulls), the file in ``source_path``."""
    rows = [
        {"raw": line if line.strip() else None, "source_path": path}
        for path, text in files.items()
        for line in text.splitlines()
    ]
    return pl.DataFrame(rows, schema={"raw": pl.Utf8, "source_path": pl.Utf8})


def table(columns: dict[str, list[str]], path: str) -> pl.DataFrame:
    """A header-read CSV scan: every column text, the file in ``source_path``."""
    n = len(next(iter(columns.values())))
    return pl.DataFrame({**columns, "source_path": [path] * n})


def run(recipe: str, sources: dict[str, pl.DataFrame | None]) -> pl.DataFrame:
    """The checks the CLI runs around a recipe: input schema, transform, output schema."""
    module = load_recipe(recipe)
    validate_sources(module, sources, recipe)
    out = module.transform(sources)
    validate_schema(
        out, module.OUTPUT_SCHEMA, recipe, getattr(module, "OPTIONAL_OUTPUT_SCHEMA", None)
    )
    return out


@pytest.fixture
def hmms() -> pl.DataFrame:
    return raw({f"hmm/filtered/{SAMPLE}/{FAMILY}.hmm.gz": _hmm()})


@pytest.fixture
def stockholm() -> pl.DataFrame:
    return raw({f"full_msa/raw/hmmer_hmmalign/{SAMPLE}/{FAMILY}.sto.gz": STOCKHOLM})


@pytest.fixture
def meta() -> pl.DataFrame:
    return table(
        {
            "Family Id": [FAMILY],
            "Size": ["3"],
            "Representative Length": ["5"],
            "Representative Id": [REP],
            "Sequence": ["ACGDE"],
        },
        f"family_reps/{SAMPLE}/{SAMPLE}_meta_mqc.csv",
    )


@pytest.fixture
def aligned() -> pl.DataFrame:
    return raw({f"full_msa/filtered/famsa_align/{SAMPLE}/{FAMILY}.aln": ALIGNED_FASTA})


# ---------------------------------------------------------------------------
# hmmer/hmm_profile
# ---------------------------------------------------------------------------


def test_profile_maps_states_onto_the_representative_from_one(hmms, stockholm, meta) -> None:
    out = run("hmmer/hmm_profile.py", {"hmms": hmms, "alignments": stockholm, "family_meta": meta})
    assert set(out["entity"]) == {FAMILY}
    assert set(out["sample"]) == {SAMPLE}
    assert out.height == 4 * len(LETTERS)
    states = out.unique("hmm_position").sort("hmm_position")
    # A1 C2 g3 D4 E5 on the representative: the insert residue is counted, and the
    # /5-9 of the row name does not shift the numbering off the sequence itself.
    assert states["position"].to_list() == [1, 2, 4, 5]
    assert states["consensus"].to_list() == ["A", "C", "D", "E"]
    top = (
        out.filter(pl.col("hmm_position") == 1).sort("emission", descending=True).row(0, named=True)
    )
    assert (top["hmm_letter"], round(top["emission"], 3)) == ("A", 0.8)


def test_profile_without_a_known_reference_has_no_positions(hmms, stockholm, meta) -> None:
    for sources in (
        {"hmms": hmms, "alignments": None, "family_meta": meta},  # no alignment
        {"hmms": hmms, "alignments": stockholm, "family_meta": None},  # representative unknown
        {"hmms": hmms, "alignments": None, "family_meta": None},
    ):
        out = run("hmmer/hmm_profile.py", sources)
        assert out.height == 4 * len(LETTERS)
        assert out["position"].null_count() == out.height
    # A representative that is not a row of the alignment leaves the logo without a link too.
    wrong = meta.with_columns(pl.lit("elsewhere").alias("Representative Id"))
    out = run("hmmer/hmm_profile.py", {"hmms": hmms, "alignments": stockholm, "family_meta": wrong})
    assert out["position"].null_count() == out.height


def test_profile_reads_each_family_once_and_skips_broken_files() -> None:
    files = {
        # The filtered model wins over a raw one of the same name, whatever the scan order.
        f"hmm/raw/mmseqs/{SAMPLE}/{FAMILY}.hmm.gz": _hmm(letters="WWWW"),
        f"hmm/filtered/{SAMPLE}/{FAMILY}.hmm.gz": _hmm(nseq=7),
        f"hmm/filtered/{SAMPLE}/broken.hmm.gz": "HMMER3/f\nNAME broken\n",
        f"update_families/hmm/{SAMPLE}/other.hmm.gz": _hmm(name="other"),
    }
    out = run("hmmer/hmm_profile.py", {"hmms": raw(files), "alignments": None, "family_meta": None})
    assert sorted(set(out["entity"])) == ["other", FAMILY]
    mine = out.filter(pl.col("entity") == FAMILY)
    assert mine.height == 4 * len(LETTERS)
    assert set(
        mine.filter(pl.col("hmm_position") == 1).filter(pl.col("emission") > 0.5)["hmm_letter"]
    ) == {"A"}
    # An empty scan is an empty table with the schema, not an error.
    empty = run("hmmer/hmm_profile.py", {"hmms": raw({}), "alignments": None, "family_meta": None})
    assert empty.is_empty()


# ---------------------------------------------------------------------------
# hmmer/hmmalign_hits
# ---------------------------------------------------------------------------


def test_hits_are_the_stretch_of_the_model_each_member_covers(stockholm) -> None:
    out = run("hmmer/hmmalign_hits.py", {"alignments": stockholm})
    rows = {r["entity"]: r for r in out.to_dicts()}
    # A row with no residue on the model has no hit.
    assert set(rows) == {REP, "full", "frag"}
    assert {r["label"] for r in rows.values()} == {FAMILY}
    assert {r["sample"] for r in rows.values()} == {SAMPLE}
    rep, full, frag = rows[REP], rows["full"], rows["frag"]
    # Residues are counted from 1 along the member's own sequence, inserts included.
    assert (rep["hmm_from"], rep["hmm_to"], rep["ali_from"], rep["ali_to"]) == (1, 4, 1, 5)
    assert (rep["protein_length"], rep["hmm_length"], rep["hmm_coverage"]) == (5, 4, 1.0)
    assert (full["ali_from"], full["ali_to"], full["protein_length"]) == (1, 4, 4)
    # The fragment covers the last two of four states: the hits lane draws half the model.
    assert (frag["hmm_from"], frag["hmm_to"], frag["ali_from"], frag["ali_to"]) == (3, 4, 1, 2)
    assert frag["hmm_coverage"] == 0.5
    # An alignment carries no search statistics.
    assert out["i_evalue"].null_count() == out.height
    assert out["dom_score"].null_count() == out.height


def test_hits_skip_what_is_not_an_alignment() -> None:
    files = {
        f"full_msa/raw/hmmer_hmmalign/{SAMPLE}/ragged.sto.gz": "# STOCKHOLM 1.0\na ACD\nb AC\n//\n"
    }
    assert run("hmmer/hmmalign_hits.py", {"alignments": raw(files)}).is_empty()


# ---------------------------------------------------------------------------
# lib/protein_families
# ---------------------------------------------------------------------------


def test_parse_hmm_reads_the_header_of_the_first_model_with_the_hmm_lib() -> None:
    header = parse_hmm(_hmm())
    assert header == {"name": FAMILY, "length": 4, "nseq": 7, "effn": 2.5}
    with pytest.raises(ValueError):
        parse_hmm("NAME x\nLENG 3\n")


def test_representative_positions_number_the_sequence_from_one() -> None:
    assert representative_positions(STOCKHOLM, REP, 4) == [1, 2, 4, 5]
    assert representative_positions(STOCKHOLM, "full", 4) == [1, 2, 3, 4]
    assert representative_positions(STOCKHOLM, "frag", 4) == [None, None, 1, 2]
    with pytest.raises(ValueError, match="match columns"):
        representative_positions(STOCKHOLM, REP, 5)


def test_representatives_are_keyed_by_sample_and_family(meta) -> None:
    update = table(
        {"Family Id": ["old_1"], "Representative Id": ["seq9"]},
        "update_families/family_reps/run2/run2_meta_mqc.csv",
    )
    assert representatives(pl.concat([meta, update], how="diagonal")) == {
        (SAMPLE, FAMILY): REP,
        ("run2", "old_1"): "seq9",
    }
    assert representatives(None) == {}
    assert representatives(pl.DataFrame({"x": ["1"]})) == {}


# ---------------------------------------------------------------------------
# famsa and cmaple
# ---------------------------------------------------------------------------


def test_alignment_ranks_the_representative_first(aligned) -> None:
    out = run("famsa/alignment.py", {"alignments": aligned})
    rows = {r["seq_id"]: r for r in out.to_dicts()}
    assert [r["rank"] for r in out.sort("rank").to_dicts()] == [0, 1, 2]
    assert set(out["msa_id"]) == {FAMILY} and set(out["sample"]) == {SAMPLE}
    assert rows["rep/5-9"]["rank"] == 0 and rows["rep/5-9"]["identity"] == 1.0
    assert rows["frag"]["coverage"] == 0.6  # three of the representative's five residues
    assert rows["full"]["coverage"] == 0.8


def test_conservation_is_numbered_along_the_representative(aligned) -> None:
    out = run("famsa/conservation.py", {"alignments": aligned}).sort("position")
    assert out["position"].to_list() == [1, 2, 3, 4, 5]
    assert "".join(out["residue"]) == "ACGDE"
    assert set(out["sequence"]) == {"ACGDE"} and set(out["n_members"]) == {3}
    # D and E are invariant and gap-free; A and C lack the fragment's residue; G has a gap too.
    assert out["category"].to_list() == [
        "intermediate",
        "intermediate",
        "intermediate",
        "conserved",
        "conserved",
    ]
    assert out["value"].to_list()[3:] == [1.0, 1.0]


def test_tree_layout_stacks_segments_with_null_separators() -> None:
    trees = raw({f"phylogeny/cmaple/{SAMPLE}/{FAMILY}.treefile": NEWICK})
    out = run("cmaple/tree_layout.py", {"trees": trees}).sort("draw_order")
    assert set(out["family"]) == {FAMILY} and set(out["n_tips"]) == {3}
    # Six segments (four edges and two forks), each two points and a separator.
    assert out.height == 18
    assert out["x"].null_count() == 6 and out["y"].null_count() == 6
    tips = {r["node"]: r["x"] for r in out.filter(pl.col("is_tip")).to_dicts()}
    assert tips == pytest.approx({"a": 0.15, "b": 0.25, "c": 0.3})


# ---------------------------------------------------------------------------
# proteinfamilies
# ---------------------------------------------------------------------------


def test_cluster_size_distribution_reads_sizes_and_shares() -> None:
    dist = table(
        {
            "Id": ["a", "b", "c"],
            "Cluster Size": ["1", "2", "5"],
            "Number of Clusters": ["10", "4", "1"],
        },
        f"mmseqs/initial_clustering/{SAMPLE}_clustering_distribution_mqc.csv",
    )
    out = run("proteinfamilies/cluster_size_distribution.py", {"distribution": dist})
    assert set(out["sample"]) == {SAMPLE}
    assert out["cluster_size"].to_list() == [1, 2, 5]
    assert out["n_sequences"].to_list() == [10, 8, 5]  # size times clusters
    assert out["sequence_share"].to_list() == [0.435, 0.348, 0.217]


def test_family_members_join_the_alignment_and_mark_the_origin(aligned) -> None:
    members = pl.concat(
        [
            table(
                {"family_id": [FAMILY] * 3, "member_id": [REP, "full", "frag"]},
                f"family_reps/{SAMPLE}/{SAMPLE}.tsv",
            ),
            table(
                {"family_id": ["old_1", "old_1"], "member_id": ["x", "x"]},
                "update_families/family_reps/run2/run2.tsv",
            ),
        ]
    )
    out = run("proteinfamilies/family_members.py", {"members": members, "alignments": aligned})
    rows = {(r["family"], r["member_id"]): r for r in out.to_dicts()}
    assert set(rows) == {(FAMILY, REP), (FAMILY, "full"), (FAMILY, "frag"), ("old_1", "x")}
    assert rows[(FAMILY, REP)]["is_representative"] and rows[(FAMILY, REP)]["identity"] == 1.0
    assert rows[(FAMILY, "frag")]["length"] == 3 and rows[(FAMILY, "frag")]["coverage"] == 0.6
    assert (
        rows[("old_1", "x")]["origin"] == "updated"
        and rows[("old_1", "x")]["in_alignment"] is False
    )
    assert rows[(FAMILY, "full")]["origin"] == "new"
    # Without the optional alignment scan the roster stands alone.
    bare = run("proteinfamilies/family_members.py", {"members": members, "alignments": None})
    assert bare["identity"].null_count() == bare.height


def test_family_metadata_folds_in_the_model_and_the_alignment(meta, hmms, aligned) -> None:
    out = run(
        "proteinfamilies/family_metadata.py",
        {"family_meta": meta, "hmms": hmms, "alignments": aligned},
    )
    row = out.row(0, named=True)
    assert (row["family"], row["sample"], row["origin"], row["size"]) == (FAMILY, SAMPLE, "new", 3)
    assert (row["representative_id"], row["representative_length"]) == (REP, 5)
    # From the HMM header: seed 7 of the family's 3 members leaves nothing recruited.
    assert (row["seed_size"], row["model_length"], row["effective_sequences"]) == (7, 4, 2.5)
    assert row["recruited"] == 0
    assert (row["aligned_members"], row["alignment_columns"]) == (3, 5)
    assert row["mean_identity"] == 1.0 and 0 < row["mean_conservation"] < 1
    bare = run(
        "proteinfamilies/family_metadata.py",
        {"family_meta": meta, "hmms": None, "alignments": None},
    )
    assert bare["seed_size"].null_count() == 1 and bare["aligned_members"].null_count() == 1
