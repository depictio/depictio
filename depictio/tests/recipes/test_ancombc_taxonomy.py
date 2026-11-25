"""ANCOM-BC against two reference databases, side by side.

``qiime2/ancombc.py`` reads its five slices by glob. A sibling named
``<slice>.<label>.csv`` carries its rows under ``taxonomy = <label>``; the file
ampliseq writes has no label and leaves the column empty. ``ma_canonical`` takes
the abundance of a labelled taxon from the barplot of its own label.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import polars as pl

from depictio.recipes import resolve_sources

REPO = Path(__file__).resolve().parents[2]
SLICES = ("lfc", "p_val", "q_val", "w", "se")
DIR = "qiime2/ancombc/differentials/Category-locality-level-2"


def _load(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ANCOMBC = _load(REPO / "catalog" / "qiime2" / "ancombc.py")
MA = _load(REPO / "projects" / "nf-core" / "ampliseq" / "recipes" / "ma_canonical.py")


def _slice(root: Path, name: str, label: str | None, ids: list[str]) -> None:
    suffix = f".{label}" if label else ""
    path = root / DIR / f"{name}_slice{suffix}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = "\n".join(f"{i},1.0,{n + 1}.5" for n, i in enumerate(ids))
    path.write_text(f"id,(Intercept),localityNaples\n{rows}\n")


def _overrides() -> dict[str, str]:
    return {name: f"{DIR}/{name}_slice*.csv" for name in SLICES}


def _run(root: Path) -> pl.DataFrame:
    return ANCOMBC.transform(resolve_sources(ANCOMBC, root, _overrides()))


def test_an_unlabelled_run_leaves_taxonomy_empty(tmp_path: Path) -> None:
    for name in SLICES:
        _slice(tmp_path, name, None, ["Bacteria;Pseudomonadota", "Eukaryota;"])
    out = _run(tmp_path)
    assert out.height == 2
    assert out["taxonomy"].null_count() == 2


def test_labelled_slices_are_kept_apart(tmp_path: Path) -> None:
    # The same lineage in both analyses is two rows, not one: they are two tests.
    for name in SLICES:
        _slice(tmp_path, name, "silva", ["Bacteria;Pseudomonadota", "Eukaryota;"])
        _slice(tmp_path, name, "pr2", ["Bacteria;Pseudomonadota", "Eukaryota;Gyrista"])
    out = _run(tmp_path)
    assert out.height == 4
    counts = out.group_by("taxonomy").len().sort("taxonomy")
    assert counts.to_dicts() == [
        {"taxonomy": "pr2", "len": 2},
        {"taxonomy": "silva", "len": 2},
    ]
    # Each row kept the statistics of its own file.
    assert out["lfc"].null_count() == 0
    assert out["q_val"].null_count() == 0
    assert set(out.columns) == set(ANCOMBC.OUTPUT_SCHEMA)


def _barplot(root: Path, label: str | None, taxa: dict[str, list[int]]) -> None:
    suffix = f".{label}" if label else ""
    path = root / "qiime2" / "barplot" / f"level-2{suffix}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    header = "index," + ",".join(taxa) + ",locality"
    rows = [
        f"S{n}," + ",".join(str(counts[n]) for counts in taxa.values()) + ",Naples"
        for n in range(2)
    ]
    path.write_text("\n".join([header, *rows]) + "\n")


def test_ma_takes_a_labelled_taxon_abundance_from_its_own_barplot(tmp_path: Path) -> None:
    _barplot(tmp_path, "pr2", {"Eukaryota;Gyrista": [9, 99]})
    labelled = resolve_sources(MA, tmp_path, {"labelled_barplots": "qiime2/barplot/level-2.*.csv"})
    ancombc = pl.DataFrame(
        {
            "id": ["Bacteria;Pseudomonadota", "Eukaryota;Gyrista"],
            "lfc": [1.0, 2.0],
            "q_val": [0.01, 0.02],
            "Phylum": ["Pseudomonadota", "Gyrista"],
            "contrast": ["localityNaples"] * 2,
            "taxonomy": ["silva", "pr2"],
        }
    )
    composition = pl.DataFrame({"taxonomy": ["Bacteria;Pseudomonadota"], "count": [9.0]})
    out = MA.transform(
        {
            "ancombc": ancombc,
            "composition": composition,
            "labelled_barplots": labelled["labelled_barplots"],
        }
    ).sort("feature_id")
    assert out["feature_id"].to_list() == ["Bacteria;Pseudomonadota", "Eukaryota;Gyrista"]
    assert out["taxonomy"].to_list() == ["silva", "pr2"]
    # SILVA from the default composition: log10(9 + 1); PR2 from its own barplot.
    assert out["avg_log_intensity"][0] == 1.0
    assert abs(out["avg_log_intensity"][1] - (1.0 + 2.0) / 2) < 1e-9


def test_ma_is_unchanged_without_labelled_barplots() -> None:
    ancombc = pl.DataFrame(
        {"id": ["A;B"], "lfc": [1.0], "q_val": [0.01], "Phylum": ["B"], "contrast": ["c"]}
    )
    composition = pl.DataFrame({"taxonomy": ["A;B"], "count": [99.0]})
    out = MA.transform({"ancombc": ancombc, "composition": composition, "labelled_barplots": None})
    assert out["avg_log_intensity"].to_list() == [2.0]
    assert "taxonomy" not in out.columns


# A second ampliseq run of the same reads (the template's PR2_RESULTS) lives in its
# own results folder. A glob cannot leave the data root, so its five slices are
# plain optional paths: ``<slice>_alt`` sources, labelled ``alt_label``, while the
# DATA_ROOT run's unlabelled slices take ``label``.

ALT_DIR = "qiime2/ancombc/differentials/Category-locality-level-4"


def _alt_slices(root: Path, ids: list[str]) -> dict[str, str]:
    """The second run's slices, written as ampliseq names them, by absolute path."""
    paths = {}
    for name in SLICES:
        path = root / ALT_DIR / f"{name}_slice.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = "\n".join(f"{i},1.0,{n + 7}.5" for n, i in enumerate(ids))
        path.write_text(f"id,(Intercept),localityNaples\n{rows}\n")
        paths[f"{name}_alt"] = str(path)
    return paths


def test_a_second_run_is_read_under_its_own_label(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DEPICTIO_CONTEXT", "cli")  # the second run sits outside the root
    for name in SLICES:
        _slice(tmp_path / "silva", name, None, ["Bacteria;Pseudomonadota", "Eukaryota;"])
    alt = _alt_slices(
        tmp_path / "pr2",
        ["Eukaryota;Obazoa;Opisthokonta;Metazoa", "Eukaryota;TSAR;Alveolata;Dinoflagellata"],
    )
    sources = resolve_sources(ANCOMBC, tmp_path / "silva", {**_overrides(), **alt})

    out = ANCOMBC.transform(sources, params={"label": "silva", "alt_label": "pr2"})

    by_label = {t: sorted(out.filter(pl.col("taxonomy") == t)["id"]) for t in ("silva", "pr2")}
    assert by_label["silva"] == ["Bacteria;Pseudomonadota", "Eukaryota;"]
    assert by_label["pr2"] == [
        "Eukaryota;Obazoa;Opisthokonta;Metazoa",
        "Eukaryota;TSAR;Alveolata;Dinoflagellata",
    ]
    assert out.height == 4
    # PR2 read at its own Phylum depth: the leaf is the phylum, the root the domain.
    pr2 = out.filter(pl.col("taxonomy") == "pr2").sort("id")
    assert pr2["Phylum"].to_list() == ["Metazoa", "Dinoflagellata"]
    assert pr2["Kingdom"].to_list() == ["Eukaryota", "Eukaryota"]
    assert pr2["lfc"].to_list() == [7.5, 8.5]


def test_without_a_second_run_the_label_changes_nothing(tmp_path: Path) -> None:
    """Every other template reads one run: its rows stay unlabelled."""
    for name in SLICES:
        _slice(tmp_path, name, None, ["Bacteria;Pseudomonadota"])
    sources = resolve_sources(ANCOMBC, tmp_path, _overrides())

    assert all(sources[f"{name}_alt"] is None for name in SLICES)
    out = ANCOMBC.transform(sources, params={"label": "silva", "alt_label": "pr2"})
    assert out["taxonomy"].null_count() == 1


def test_an_unresolved_label_falls_back_to_the_database_names(tmp_path: Path, monkeypatch) -> None:
    """Unresolved {VAR} params are dropped: the second run still gets a label."""
    monkeypatch.setenv("DEPICTIO_CONTEXT", "cli")
    for name in SLICES:
        _slice(tmp_path / "silva", name, None, ["Bacteria;Pseudomonadota"])
    alt = _alt_slices(tmp_path / "pr2", ["Eukaryota;TSAR;Alveolata;Dinoflagellata"])
    sources = resolve_sources(ANCOMBC, tmp_path / "silva", {**_overrides(), **alt})

    out = ANCOMBC.transform(sources, params={})

    assert sorted(out["taxonomy"].to_list()) == ["pr2", "silva"]


def test_ma_reads_the_second_runs_barplot_for_its_rows(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DEPICTIO_CONTEXT", "cli")
    barplot = tmp_path / "pr2" / "qiime2" / "barplot" / "level-4.csv"
    barplot.parent.mkdir(parents=True)
    barplot.write_text(
        "index,Eukaryota;TSAR;Alveolata;Dinoflagellata,locality\nS0,9,Naples\nS1,99,Naples\n"
    )
    resolved = resolve_sources(MA, tmp_path, {"alt_barplot": str(barplot)})
    ancombc = pl.DataFrame(
        {
            "id": ["Bacteria;Pseudomonadota", "Eukaryota;TSAR;Alveolata;Dinoflagellata"],
            "lfc": [1.0, 2.0],
            "q_val": [0.01, 0.02],
            "Phylum": ["Pseudomonadota", "Dinoflagellata"],
            "contrast": ["localityNaples"] * 2,
            "taxonomy": ["silva", "pr2"],
        }
    )
    composition = pl.DataFrame({"taxonomy": ["Bacteria;Pseudomonadota"], "count": [9.0]})

    out = MA.transform(
        {
            "ancombc": ancombc,
            "composition": composition,
            "labelled_barplots": None,
            "alt_barplot": resolved["alt_barplot"],
        },
        params={"alt_label": "pr2"},
    ).sort("feature_id")

    assert out["taxonomy"].to_list() == ["silva", "pr2"]
    assert out["avg_log_intensity"][0] == 1.0
    assert abs(out["avg_log_intensity"][1] - (1.0 + 2.0) / 2) < 1e-9
