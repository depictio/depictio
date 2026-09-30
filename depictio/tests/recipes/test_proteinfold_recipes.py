"""nf-core/proteinfold recipes on a synthetic two-engine output tree.

The tree mimics the pipeline's layout (an engine with a mode level, one
without, a complex and a monomer, 0- and 1-based model numbering, an empty
ipTM file) so every recipe runs through the same glob sources the CLI reads.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType

import polars as pl
import pytest
import yaml

from depictio.models.models.data_collections_types.indexed_file import sample_from_path
from depictio.recipes import resolve_sources
from depictio.recipes.lib.msa import AF_RESTYPE_ALPHABET, HHBLITS_ALPHABET
from depictio.recipes.lib.proteinfold import (
    STRUCTURE_SAMPLE_REGEX,
    locate_structure,
    locate_target_file,
    structure_entity,
)

REPO = Path(__file__).resolve().parents[3]
CATALOG = REPO / "depictio" / "catalog" / "proteinfold"
TEMPLATE = REPO / "depictio" / "projects" / "nf-core" / "proteinfold" / "2.1.0" / "template.yaml"
HUB = REPO / "depictio" / "projects" / "nf-core" / "proteinfold" / "recipes" / "targets.py"
STRUCTURES = HUB.parent / "structures.py"


def _load(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pdb(chains: dict[str, str], bfactor: float) -> str:
    three = {"M": "MET", "K": "LYS", "A": "ALA", "G": "GLY", "L": "LEU"}
    lines, serial = [], 1
    for chain, seq in chains.items():
        for i, aa in enumerate(seq, start=1):
            lines.append(
                f"ATOM  {serial:5d}  CA  {three[aa]} {chain}{i:4d}    "
                f"{0.0:8.3f}{0.0:8.3f}{0.0:8.3f}{1.0:6.2f}{bfactor:6.2f}           C  "
            )
            serial += 1
        lines.append("TER")
    return "\n".join([*lines, "END", ""])


@pytest.fixture()
def run_dir(tmp_path: Path) -> Path:
    def write(rel: str, text: str) -> None:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    # AlphaFold2 (standard mode): a two-chain target, models numbered from 0,
    # its MSA in AlphaFold's residue-type order (multimer).
    af = "alphafold2/standard"
    write(f"{af}/top_ranked_structures/CPX.pdb", _pdb({"A": "MKA", "B": "GL"}, 80.0))
    write(
        f"{af}/CPX/CPX_plddt.tsv",
        "Positions\trank_0\trank_1\n" + "".join(f"{i}\t{90 - i}\t{40 + i}\n" for i in range(5)),
    )
    write(f"{af}/CPX/CPX_ptm.tsv", "0\t0.8\n1\t0.5\n")
    write(f"{af}/CPX/CPX_iptm.tsv", "0\t0.7\n1\t0.3\n")
    write(f"{af}/CPX/CPX_chainwise_iptm.tsv", "\t0\t1\nA:B\t0.7\tn/a\n")
    af_codes = "\t".join(str(AF_RESTYPE_ALPHABET.index(c)) for c in "MKAGL")
    write(f"{af}/CPX/CPX_alphafold2_msa.tsv", af_codes + "\n")
    write(
        f"{af}/CPX/paes/CPX_0_pae.tsv",
        "".join("\t".join(str(float(abs(i - j))) for j in range(5)) + "\n" for i in range(5)),
    )
    write(f"{af}/CPX/paes/CPX_1_pae.tsv", "9\t9\t9\t9\t9\n" * 5)
    # ColabFold: a monomer, models numbered from 1, pLDDT stored 0-1 in the PDB,
    # an empty ipTM file, an HHblits-coded MSA with one hit.
    write("colabfold/top_ranked_structures/MONO.pdb", _pdb({"A": "MKAG"}, 0.6))
    write(
        "colabfold/MONO/MONO_plddt.tsv",
        "Positions\trank_1\trank_2\n" + "".join(f"{i}\t60\t30\n" for i in range(4)),
    )
    write("colabfold/MONO/MONO_ptm.tsv", "1\t0.6\n2\t0.4\n")
    write("colabfold/MONO/MONO_iptm.tsv", "")
    hh = lambda seq: "\t".join(str(HHBLITS_ALPHABET.index(c)) for c in seq)  # noqa: E731
    write("colabfold/MONO/MONO_colabfold_msa.tsv", hh("MKAG") + "\n" + hh("MR-G") + "\n")
    write("input/samplesheet.csv", "id,fasta,batch\nCPX,cpx.fasta,b1\nMONO,mono.fasta,b2\n")
    return tmp_path


def _run(name: str, run_dir: Path, extra: dict[str, pl.DataFrame] | None = None) -> pl.DataFrame:
    local = {"targets": HUB, "structures": STRUCTURES}
    module = _load(local.get(name, CATALOG / f"{name}.py"))
    sources = resolve_sources(module, run_dir)
    sources.update(extra or {})
    out = module.transform(sources)
    for column, dtype in module.EXPECTED_SCHEMA.items():
        assert out.schema[column] == dtype, (name, column)
    return out


def _scores_scan(run_dir: Path) -> pl.DataFrame:
    """The proteinfold_scores_raw scan, read as the CLI reads it."""
    doc = yaml.safe_load(TEMPLATE.read_text())
    dc = next(
        d
        for d in doc["workflows"][0]["data_collections"]
        if d["data_collection_tag"] == "proteinfold_scores_raw"
    )
    pattern = re.compile(dc["config"]["scan"]["scan_parameters"]["regex_config"]["pattern"])
    kwargs = dc["config"]["dc_specific_properties"]["polars_kwargs"]
    frames = [
        pl.scan_csv(p, **kwargs).collect()
        for p in sorted(run_dir.rglob("*.tsv"))
        if pattern.match(p.name)
    ]
    return pl.concat([f for f in frames if f.height], how="diagonal_relaxed")


ENTITY_CPX = "alphafold2__CPX"
ENTITY_MONO = "colabfold__MONO"


def test_template_sample_regex_is_the_recipes_regex() -> None:
    doc = yaml.safe_load(TEMPLATE.read_text())
    dc = next(
        d
        for d in doc["workflows"][0]["data_collections"]
        if d["data_collection_tag"] == "proteinfold_structures"
    )
    assert dc["config"]["dc_specific_properties"]["sample_regex"] == STRUCTURE_SAMPLE_REGEX


def test_entity_matches_the_indexed_file_id_from_any_root() -> None:
    for root in ("", "/data/runs/megatest/"):
        path = f"{root}alphafold2/split_msa_prediction/top_ranked_structures/T.pdb"
        loc = locate_structure(path)
        assert (loc.engine_dir, loc.mode, loc.target) == ("alphafold2", "split_msa_prediction", "T")
        assert loc.engine == "alphafold2 (split msa prediction)"
        assert sample_from_path(path, STRUCTURE_SAMPLE_REGEX) == loc.entity
        assert loc.entity == "alphafold2__split_msa_prediction__T"
    # The default mode stays out of the id; engines and modes never collide.
    assert structure_entity("alphafold2", "standard", "T") == "alphafold2__T"
    assert structure_entity("colabfold", "", "T") == "colabfold__T"
    loc = locate_target_file("/x/esmfold/T/paes/T_0_pae.tsv")
    assert (loc.engine, loc.target, loc.entity) == (
        "esmfold",
        "T",
        structure_entity("esmfold", "", "T"),
    )


def test_residues_read_structure_numbering_and_rescale(run_dir: Path) -> None:
    out = _run("residues", run_dir)
    cpx = out.filter(pl.col("entity") == ENTITY_CPX)
    assert cpx.select("chain", "position").rows() == [
        ("A", 1),
        ("A", 2),
        ("A", 3),
        ("B", 1),
        ("B", 2),
    ]
    mono = out.filter(pl.col("entity") == ENTITY_MONO)
    assert mono["value"].unique().to_list() == [60.0]
    # Band labels spelled as the protein tiles' pLDDT legend spells them.
    assert mono["category"].unique().to_list() == ["Low"]
    assert set(out["category"]) <= {"Very high", "Confident", "Low", "Very low"}
    assert set(out["confidently_placed"].unique()) == {0.0, 100.0}


def test_engine_plddt_splits_complex_chains(run_dir: Path) -> None:
    out = _run("engine_plddt", run_dir)
    assert set(out["series"]) == {
        "CPX alphafold2 chain A",
        "CPX alphafold2 chain B",
        "MONO colabfold",
    }
    # No engine column: an engine filter on the residue table must not narrow the curves.
    assert "engine" not in out.columns


def test_models_rank_from_one_and_join_scores(run_dir: Path) -> None:
    out = _run("models", run_dir, {"scores": _scores_scan(run_dir)})
    rows = {(r["entity"], r["model_rank"]): r for r in out.to_dicts()}
    assert rows[(ENTITY_CPX, 1)]["ptm"] == 0.8
    assert rows[(ENTITY_CPX, 1)]["iptm"] == 0.7
    assert rows[(ENTITY_CPX, 1)]["is_top"] is True
    assert rows[(ENTITY_MONO, 1)]["ptm"] == 0.6
    assert rows[(ENTITY_MONO, 1)]["iptm"] is None
    assert rows[(ENTITY_MONO, 2)]["mean_plddt"] == 30.0
    assert rows[(ENTITY_MONO, 1)]["structure"] == "colabfold / MONO"
    # Without the optional score scan the scores are null, not an error.
    bare = _run("models", run_dir, {"scores": None})
    assert bare["ptm"].null_count() == bare.height


def test_plddt_ranks_top_curve_with_model_band(run_dir: Path) -> None:
    out = _run("plddt_ranks", run_dir)
    # One row per structure and residue, not per model.
    assert out.group_by("entity", "residue_index").len()["len"].max() == 1
    assert out["residue_index"].min() == 1
    mono = out.filter(pl.col("entity") == ENTITY_MONO).row(0, named=True)
    assert (mono["n_models"], mono["plddt"], mono["plddt_min"], mono["plddt_max"]) == (
        2,
        60.0,
        30.0,
        60.0,
    )
    # The complex's top model (rank_0) is 90 - i; the other is 40 + i.
    cpx = out.filter((pl.col("entity") == ENTITY_CPX) & (pl.col("residue_index") == 1)).row(
        0, named=True
    )
    assert (cpx["plddt"], cpx["plddt_min"], cpx["plddt_max"]) == (90.0, 40.0, 90.0)


def test_msa_decodes_each_file_in_its_own_alphabet(run_dir: Path) -> None:
    out = _run("msa", run_dir)
    query = dict(out.filter(pl.col("rank") == 0).select("msa_id", "aligned_sequence").rows())
    assert query == {ENTITY_CPX: "MKAGL", ENTITY_MONO: "MKAG"}
    # The complex's query row carries its chain layout, in the chains' own numbering.
    layouts = dict(out.filter(pl.col("rank") == 0).select("msa_id", "chains").rows())
    assert layouts == {ENTITY_CPX: "A:1-3,B:1-2", ENTITY_MONO: None}
    assert out.filter(pl.col("rank") > 0)["chains"].null_count() == out.height - 2
    hit = out.filter(pl.col("seq_id") == "hit_1").row(0, named=True)
    assert (hit["identity"], hit["coverage"]) == (2 / 3, 0.75)


def test_pae_keeps_the_top_model(run_dir: Path) -> None:
    out = _run("pae", run_dir)
    assert out["entity"].unique().to_list() == [ENTITY_CPX]
    assert out.height == 5
    assert out.filter(pl.col("bin") == 1)["b01"].item() == 0.0
    assert out["b06"].null_count() == 5
    # Row 1 of |i - j| over 5 residues: (0 + 1 + 2 + 3 + 4) / 5.
    assert out.filter(pl.col("bin") == 1)["mean_pae"].item() == 2.0


def test_targets_hub_keeps_sheet_columns_and_derives_assembly(run_dir: Path) -> None:
    out = _run("targets", run_dir)
    rows = {r["target"]: r for r in out.to_dicts()}
    assert rows["CPX"]["assembly"] == "complex"
    assert rows["CPX"]["sequence"] == "MKA:GL"
    assert rows["MONO"]["assembly"] == "single chain"
    assert rows["MONO"]["batch"] == "b2"
    assert rows["MONO"]["n_engines"] == 1


def test_chain_layout_refuses_what_would_not_line_up() -> None:
    from depictio.recipes.lib.msa import chain_layout_from_residues

    residues = pl.DataFrame({"chain": ["A", "A", "B", "B"], "position": [1, 2, 3, 4]})
    # ESMFold numbers the second chain on from the first: kept as is.
    assert chain_layout_from_residues(residues, 4) == "A:1-2,B:3-4"
    # A reference of another length, or a gap in a chain's numbering: no layout.
    assert chain_layout_from_residues(residues, 5) is None
    gapped = pl.DataFrame({"chain": ["A", "A", "B"], "position": [1, 3, 1]})
    assert chain_layout_from_residues(gapped) is None
    assert chain_layout_from_residues(residues.filter(pl.col("chain") == "A")) is None


def test_structures_one_row_per_uploaded_pdb(run_dir: Path) -> None:
    out = _run("structures", run_dir, {"scores": _scores_scan(run_dir)})
    rows = {r["entity"]: r for r in out.to_dicts()}
    # One row per top-ranked PDB, keyed like the structures collection keys it.
    assert set(rows) == {ENTITY_CPX, ENTITY_MONO}
    cpx, mono = rows[ENTITY_CPX], rows[ENTITY_MONO]
    assert (cpx["n_chains"], cpx["n_residues"], cpx["n_models"]) == (2, 5, 2)
    assert (cpx["ptm"], cpx["iptm"]) == (0.8, 0.7)
    assert cpx["structure"] == "alphafold2 / CPX"
    # Confidence comes from the PDB (B-factor 0-1 rescaled), not the model tables.
    assert (mono["mean_plddt"], mono["confident_pct"], mono["very_low_pct"]) == (60.0, 0.0, 0.0)
    assert (mono["ptm"], mono["iptm"]) == (0.6, None)
    # Without the optional score scan the scores are null, not an error.
    bare = _run("structures", run_dir, {"scores": None})
    assert bare["ptm"].null_count() == bare.height
