"""nf-core/proteinannotator recipes on lines of a real megatest run.

Two small proteins (``P1``, a 30 residue chain with hmmsearch domains, and ``P2``,
unannotated) and one whose FASTA header id carries pipes
(``GI|225038609|EFDID|719595|FULL``, annotated by InterProScan only). The tool
recipes read the files line by line, the way the template scans them
(``raw_line`` plus ``source_path``), and the summary recipes join their results,
so each test pins one step and the last pins that the proteins still join.
"""

from __future__ import annotations

import polars as pl
import pytest

from depictio.models.models.data_collections_types.indexed_file import sample_from_path
from depictio.recipes import load_recipe, validate_schema, validate_sources
from depictio.recipes.lib.protein_annotation import (
    DATABASES,
    covered_positions,
    protein_entity,
    protein_entity_expr,
)

PIPED = "GI|225038609|EFDID|719595|FULL"
CLEAN = "GI_225038609_EFDID_719595_FULL"

#: hmmsearch --domtblout data lines (two Pfam hits of one protein on its HMMs, one of them
#: below HMMER's inclusion threshold), as the files space-align them.
DOMTBL = {
    "domain_annotation/pfam/S1.domtbl.gz": [
        "P1                   -             30 Fam_A                PF00001.1    90   5.9e-55  172.1   0.5   1   1   6.7e-55   6.7e-55  172.0   0.5     3    80     4    28     2    30 0.94 first protein|",
        "P1                   -             30 Fam_B                PF00002.2    87   8.8e-06   12.2   0.0   1   1   1.3e-01   1.3e-01   11.6   0.0    40    81    10    20     9    22 0.89 first protein|",
    ],
    "domain_annotation/funfam/S1.domtbl.gz": [
        "P1                   -             30 1.10.1-FF-000001     -            50   2.0e-10   25.7   6.6   1   1   5.2e-10   5.2e-10   25.7   6.6    17    30    12    25    10    28 0.81 first protein|",
    ],
}

#: InterProScan TSV lines: 15 tab-separated fields, ``-`` for an empty one.
INTERPRO = {
    "functional_annotation/interproscan/S2/S2.tsv": [
        "\t".join(
            [
                PIPED,
                "079fff43",
                "40",
                "SFLD",
                "SFLDS00057",
                "Glutaminase",
                "5",
                "35",
                "0.0",
                "T",
                "08-05-2026",
                "-",
                "-",
                "-",
                "-",
            ]
        )
    ],
}

FASTA = {
    "qc/S1/S1.fasta": [
        ">P1 first protein",
        "MKVLAAGIVGLLLAQ",
        "PSTHYNWRDECFGKA*",
        ">P2 second",
        "MKTAYIAKQR",
    ],
    "qc/S2/S2.fasta": [f">{PIPED}", "MDKLLWNKKEISVSERISMKRIVMINTGGTFSSQRG"],
}

SS2 = {
    "s4pred/S1/ss2/P1.ss2": [
        "# PSIPRED VFORMAT (S4PRED V1.2.4)",
        "",
        *(
            f"{i:>4} {aa} {state}   {pc:.3f}  {ph:.3f}  {pe:.3f}"
            for i, (aa, state, pc, ph, pe) in enumerate(
                [
                    ("M", "C", 0.9, 0.1, 0.0),
                    ("K", "H", 0.2, 0.7, 0.1),
                    ("V", "H", 0.1, 0.8, 0.1),
                    ("L", "E", 0.1, 0.1, 0.8),
                ],
                start=1,
            )
        ),
    ],
    f"s4pred/S2/ss2/{PIPED}.ss2": [
        "# PSIPRED VFORMAT (S4PRED V1.2.4)",
        "",
        "   1 M C   0.950  0.050  0.000",
        "   2 D H   0.100  0.850  0.050",
    ],
}


def lines(files: dict[str, list[str]], **extra: object) -> pl.DataFrame:
    """A text scan: one line per row in ``raw_line``, the file in ``source_path``."""
    rows = [
        {"raw_line": line if line.strip() else None, "source_path": path, **extra}
        for path, content in files.items()
        for line in content
    ]
    return pl.DataFrame(rows, schema={"raw_line": pl.Utf8, "source_path": pl.Utf8})


def run(recipe: str, sources: dict[str, pl.DataFrame | None]) -> pl.DataFrame:
    """The checks the CLI runs around a recipe: input schema, transform, output schema."""
    module = load_recipe(recipe)
    validate_sources(module, sources, recipe)
    out = module.transform(sources)
    validate_schema(
        out, module.OUTPUT_SCHEMA, recipe, getattr(module, "OPTIONAL_OUTPUT_SCHEMA", None)
    )
    return out


def fasta_scan() -> pl.DataFrame:
    """The FASTA scan with the per-file line number the template adds."""
    return pl.concat(
        [
            lines({path: content}).with_row_index("line_no").cast({"line_no": pl.Int64})
            for path, content in FASTA.items()
        ]
    )


@pytest.fixture(scope="module")
def tools() -> dict[str, pl.DataFrame]:
    """Every tool recipe run once."""
    return {
        "hmmer": run("hmmer/hmmsearch_domtbl.py", {"raw": lines(DOMTBL)}),
        "interproscan": run("interproscan/matches.py", {"raw": lines(INTERPRO)}),
        "s4pred": run("s4pred/secondary_structure.py", {"raw": lines(SS2)}),
        "seqkit": run("seqkit/sequences.py", {"raw": fasta_scan()}),
    }


# ---------------------------------------------------------------------------
# One protein id everywhere
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "identifier",
    [PIPED, "sp|P12345|NAME_HUMAN", "tr|A0A|A0A_X desc", "plain_id.1", "a b", "|x|", "..y.."],
)
def test_protein_entity_is_the_sample_id_of_a_structure_file(identifier: str) -> None:
    # A structure kept for the protein is an indexed_file object named after it; its id is
    # what sample_from_path makes of the file name, so the two must be the same string.
    assert protein_entity(identifier) == sample_from_path(f"{identifier}.pdb")
    expr = pl.DataFrame({"x": [identifier]}).select(protein_entity_expr("x"))["x"].item()
    assert expr == protein_entity(identifier)
    assert protein_entity(protein_entity(identifier)) == protein_entity(identifier)


def test_safe_ids_are_unchanged_and_an_id_with_nothing_left_is_kept() -> None:
    assert protein_entity("T1024") == "T1024"
    assert protein_entity("mgnifams_create_1/1-118".replace("/", "_")) == "mgnifams_create_1_1-118"
    assert protein_entity("|||") == "|||"


def test_every_per_protein_table_spells_the_id_the_same(tools) -> None:
    piped = {
        name: set(frame.filter(pl.col("sample") == "S2")["entity"])
        for name, frame in tools.items()
        if name != "hmmer"
    }
    assert piped == {name: {CLEAN} for name in piped}
    assert tools["seqkit"].filter(pl.col("sample") == "S2")["sequence_id"].to_list() == [PIPED]


# ---------------------------------------------------------------------------
# The tool recipes
# ---------------------------------------------------------------------------


def test_hmmsearch_domtbl_splits_the_fixed_fields(tools) -> None:
    hits = {(r["source"], r["label"]): r for r in tools["hmmer"].to_dicts()}
    assert set(hits) == {("pfam", "Fam_A"), ("pfam", "Fam_B"), ("funfam", "1.10.1-FF-000001")}
    a = hits[("pfam", "Fam_A")]
    # envelope on the protein, alignment, HMM span and the independent E-value
    assert (a["entity"], a["sample"], a["accession"], a["protein_length"]) == (
        "P1",
        "S1",
        "PF00001.1",
        30,
    )
    assert (a["start"], a["end"], a["ali_from"], a["ali_to"]) == (2, 30, 4, 28)
    assert (a["hmm_from"], a["hmm_to"], a["hmm_length"]) == (3, 80, 90)
    assert (a["i_evalue"], a["dom_score"]) == (6.7e-55, 172.0)
    assert a["hmm_coverage"] == pytest.approx(78 / 90)
    assert hits[("funfam", "1.10.1-FF-000001")]["accession"] is None  # '-' is null
    assert a["description"] == "first protein|"


def test_interproscan_matches_use_the_domain_columns(tools) -> None:
    row = tools["interproscan"].row(0, named=True)
    assert (row["source"], row["label"], row["start"], row["end"]) == ("SFLD", "SFLDS00057", 5, 35)
    assert (row["evalue"], row["protein_length"]) == (0.0, 40)
    assert row["interpro_accession"] is None and row["go_terms"] is None
    # A sample with no match writes an empty file, which is no rows rather than an error.
    empty = run("interproscan/matches.py", {"raw": lines({"interproscan/S3/S3.tsv": []})})
    assert empty.is_empty()


def test_secondary_structure_is_parse_ss2_with_the_sample_of_the_directory(tools) -> None:
    ss = tools["s4pred"].filter(pl.col("entity") == "P1").sort("position")
    assert set(ss["sample"]) == {"S1"}
    assert ss["category"].to_list() == ["Coil", "Helix", "Helix", "Strand"]
    # value is the probability of the called state
    assert ss["value"].to_list() == [0.9, 0.7, 0.8, 0.8]
    assert set(tools["s4pred"].columns) == set(
        load_recipe("s4pred/secondary_structure.py").OUTPUT_SCHEMA
    )


def test_sequences_group_a_record_and_drop_the_stop(tools) -> None:
    seqs = {r["entity"]: r for r in tools["seqkit"].to_dicts()}
    assert set(seqs) == {"P1", "P2", CLEAN}
    assert (
        seqs["P1"]["sequence"] == "MKVLAAGIVGLLLAQPSTHYNWRDECFGKA"
    )  # lines joined, trailing '*' dropped
    assert (seqs["P1"]["length"], seqs["P1"]["description"], seqs["P1"]["sample"]) == (
        30,
        "first protein",
        "S1",
    )
    assert seqs[CLEAN]["description"] is None and seqs[CLEAN]["sample"] == "S2"


def test_seqfu_stats_split_the_sample_and_stage_of_the_file_name() -> None:
    header = "File\t#Seq\tTotal bp\tAvg\tN50\tN75\tN90\tauN\tMin\tMax"
    frames = []
    for path, n in (("qc/S1/S1_before.tsv", 3), ("qc/S1/S1_after.tsv", 2), ("seqfu/S9.tsv", 1)):
        cells = (
            header.split("\t"),
            f"x.fasta\t{n}\t{n * 10}\t10.00\t10\t10\t10\t10.00\t10\t10".split("\t"),
        )
        frames.append(
            pl.DataFrame(dict(zip(*cells, strict=True))).with_columns(source_path=pl.lit(path))
        )
    out = run("seqfu/stats.py", {"raw": pl.concat(frames)})
    got = {(r["sample"], r["stage"]): r["sequences"] for r in out.to_dicts()}
    assert got == {("S1", "before"): 3, ("S1", "after"): 2, ("S9", "stats"): 1}


# ---------------------------------------------------------------------------
# The summary recipes
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def domains(tools) -> pl.DataFrame:
    return run(
        "proteinannotator/domains.py",
        {"hmmer": tools["hmmer"], "interproscan": tools["interproscan"]},
    )


def test_domains_stack_both_tools_and_keep_the_hmm_span(domains) -> None:
    rows = {r["domain_id"]: r for r in domains.to_dicts()}
    # Fam_B passes no inclusion threshold (0.13 > 0.01) and is left out.
    assert sorted(r["label"] for r in rows.values()) == ["1.10.1-FF-000001", "Fam_A", "SFLDS00057"]
    a = rows["P1:pfam:Fam_A:2:30"]
    assert (a["database"], a["evalue"], a["span"], a["hmm_from"], a["hmm_to"], a["hmm_length"]) == (
        "pfam", 6.7e-55, 29, 3, 80, 90,
    )  # fmt: skip
    ipr = rows[f"{CLEAN}:interproscan:SFLDS00057:5:35"]
    # A signature match is no span of an HMM: null there, and the E-value stays in `evalue`.
    assert (ipr["hmm_from"], ipr["hmm_to"], ipr["hmm_length"]) == (None, None, None)
    assert ipr["database"] == "interproscan" and ipr["evalue"] == 0.0 and ipr["span"] == 31


def test_domains_bind_the_domain_architecture_kind(domains) -> None:
    # Every column the kind reads under its default name is there; the E-value is `evalue`
    # (the kind's default is `i_evalue`, which a template sets with `evalue_col: evalue`).
    defaults = {
        "entity_col": "entity", "start_col": "start", "end_col": "end", "label_col": "label",
        "protein_length_col": "protein_length", "hmm_from_col": "hmm_from",
        "hmm_to_col": "hmm_to", "hmm_length_col": "hmm_length",
        "hmm_coverage_col": "hmm_coverage", "source_col": "source",
        "description_col": "description", "accession_col": "accession",
    }  # fmt: skip
    from depictio.models.components.advanced_viz.configs import DomainArchitectureConfig

    config = DomainArchitectureConfig()
    for field, column in defaults.items():
        assert getattr(config, field) == column
        assert column in domains.columns
    assert "evalue" in domains.columns


def test_residues_join_structure_and_domains_for_every_protein(tools, domains) -> None:
    out = run(
        "proteinannotator/residues.py",
        {"sequences": tools["seqkit"], "structure": tools["s4pred"], "domains": domains},
    )
    p1 = out.filter(pl.col("entity") == "P1").sort("position")
    assert p1.height == 30
    # The first four residues carry the S4PRED state; the rest of the chain has none.
    assert p1["category"].to_list()[:4] == ["Coil", "Helix", "Helix", "Strand"]
    assert p1["category"].null_count() == 26
    # Position 20 is covered by Fam_A (2-30) and the FunFam (17-30).
    here = p1.filter(pl.col("position") == 20).row(0, named=True)
    assert (here["domain"], here["domain_database"], here["domains_here"]) == ("Fam_A", "pfam", 2)
    # The pipe id still lands on its own rows: sequence, structure and domain share the entity.
    piped = out.filter(pl.col("entity") == CLEAN).sort("position")
    assert piped.height == 36
    assert piped["category"].to_list()[:2] == ["Coil", "Helix"]
    assert piped.filter(pl.col("position") == 10)["domain"].item() == "SFLDS00057"
    assert set(piped["sequence"]) == {"MDKLLWNKKEISVSERISMKRIVMINTGGTFSSQRG"}


def test_proteins_count_hits_per_database_and_keep_unannotated_ones(tools, domains) -> None:
    out = run(
        "proteinannotator/proteins.py",
        {"sequences": tools["seqkit"], "domains": domains, "structure": tools["s4pred"]},
    )
    rows = {r["entity"]: r for r in out.to_dicts()}
    assert set(rows) == {"P1", "P2", CLEAN}
    p1, p2, piped = rows["P1"], rows["P2"], rows[CLEAN]
    assert (p1["domain_hits"], p1["databases_hit"], p1["pfam_hits"], p1["funfam_hits"]) == (
        2,
        2,
        1,
        1,
    )
    assert p1["top_domain"] == "Fam_A" and p1["annotation_status"] == "annotated"
    assert p1["annotated_residues"] == 29 and p1["annotated_pct"] == pytest.approx(29 / 30 * 100)
    assert (p2["domain_hits"], p2["annotation_status"], p2["top_domain"]) == (
        0,
        "unannotated",
        None,
    )
    assert piped["interproscan_hits"] == 1 and piped["annotated_residues"] == 31
    assert p1["helix_pct"] == 50.0 and p2["helix_pct"] is None


def test_sample_summary_pivots_before_and_after_and_adds_the_annotation_rates(
    tools, domains
) -> None:
    stats = pl.DataFrame(
        {
            "sample": ["S1", "S1", "S2"],
            "stage": ["before", "after", "after"],
            "file": ["a", "b", "c"],
            "sequences": [3, 2, 1],
            "total_length": [50, 39, 36],
            "mean_length": [16.7, 19.5, 36.0],
            "n50": [29, 29, 36],
            "n75": [29, 29, 36],
            "n90": [10, 10, 36],
            "aun": [1.0, 1.0, 1.0],
            "min_length": [10, 10, 36],
            "max_length": [29, 29, 36],
        }
    )
    proteins = run(
        "proteinannotator/proteins.py",
        {"sequences": tools["seqkit"], "domains": domains, "structure": tools["s4pred"]},
    )
    out = run("proteinannotator/sample_summary.py", {"stats": stats, "proteins": proteins})
    rows = {r["sample_id"]: r for r in out.to_dicts()}
    assert (
        rows["S1"]["input_sequences"],
        rows["S1"]["kept_sequences"],
        rows["S1"]["removed_sequences"],
    ) == (3, 2, 1)
    assert rows["S1"]["annotated_proteins"] == 1 and rows["S1"]["annotated_protein_pct"] == 50.0
    assert rows["S2"]["input_sequences"] == 1 and rows["S2"]["removed_sequences"] == 0
    bare = run("proteinannotator/sample_summary.py", {"stats": stats, "proteins": None})
    assert bare["annotated_proteins"].null_count() == 2


def test_database_matrices_have_a_column_per_database_even_when_skipped(tools, domains) -> None:
    for recipe in ("proteinannotator/database_coverage.py", "proteinannotator/database_sets.py"):
        out = run(recipe, {"sequences": tools["seqkit"], "domains": domains})
        assert all(db in out.columns for db in DATABASES)
        none = run(recipe, {"sequences": tools["seqkit"], "domains": None})
        assert none.height == 3
        assert all(none[db].sum() == 0 for db in DATABASES)
    sets = run(
        "proteinannotator/database_sets.py", {"sequences": tools["seqkit"], "domains": domains}
    )
    p1 = sets.filter(pl.col("entity") == "P1").row(0, named=True)
    assert (p1["pfam"], p1["funfam"], p1["nmpfams"], p1["interproscan"]) == (1, 1, 0, 0)
    coverage = run(
        "proteinannotator/database_coverage.py", {"sequences": tools["seqkit"], "domains": domains}
    )
    assert coverage.filter(pl.col("entity") == "P1")["pfam"].item() == pytest.approx(29 / 30)


def test_covered_positions_count_overlaps_once() -> None:
    spans = pl.DataFrame({"entity": ["a", "a", "b"], "start": [1, 3, 5], "end": [4, 6, 5]})
    covered = covered_positions(spans)
    assert covered.group_by("entity").len().sort("entity")["len"].to_list() == [6, 1]
