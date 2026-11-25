"""The ANCOM-BC recipe completes what the pipeline ran: every pair of levels, for each
run, and the merged taxonomy (params ``pairwise`` / ``group_col``).

The pipeline's slices are written here from the same fit the recipe makes, so the
recipe's check that it reproduces them has something real to agree with.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import numpy as np
import pandas as pd
import polars as pl
import pytest

pytest.importorskip("skbio")

from depictio.recipes import resolve_sources  # noqa: E402
from depictio.recipes.lib import ancombc as lib  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
SLICES = ("lfc", "p_val", "q_val", "w", "se")
DIR = "qiime2/ancombc/differentials/Category-locality-level-2"
LEVELS = ("Athens", "Barcelona", "Naples")


def _load(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ANCOMBC = _load(REPO / "catalog" / "qiime2" / "ancombc.py")
MA = _load(REPO / "projects" / "nf-core" / "ampliseq" / "recipes" / "ma_canonical.py")


def _counts(prefix: str, seed: int, taxa: int = 12, per_level: int = 10):
    rng = np.random.default_rng(seed)
    rows, groups = [], []
    for k, level in enumerate(LEVELS):
        for _ in range(per_level):
            mean = rng.uniform(20, 200, size=taxa)
            mean[0] *= 4**k
            rows.append(rng.poisson(mean))
            groups.append(level)
    index = [f"S{i}" for i in range(len(rows))]
    counts = pd.DataFrame(rows, index=index, columns=[f"{prefix};P{i}" for i in range(taxa)])
    return counts, pd.Series(groups, index=index)


def _write_run(root: Path, prefix: str, seed: int, slice_dir: str = DIR, level: int = 2) -> None:
    """A run as ampliseq writes it: the barplot, and the slices against Athens."""
    counts, groups = _counts(prefix, seed)
    barplot = root / "qiime2" / "barplot" / f"level-{level}.csv"
    barplot.parent.mkdir(parents=True, exist_ok=True)
    counts.assign(locality=groups).rename_axis("index").to_csv(barplot)
    fitted = lib.fit(counts, groups, "Athens")
    (root / slice_dir).mkdir(parents=True, exist_ok=True)
    for name in SLICES:
        wide = fitted.pivot(on="level", index="id", values=name).rename(
            {level: f"locality{level}" for level in LEVELS[1:]}
        )
        wide.insert_column(1, pl.lit(1.0).alias("(Intercept)")).write_csv(
            root / slice_dir / f"{name}_slice.csv"
        )


def _sources(root: Path, extra: dict[str, str] | None = None) -> dict:
    overrides = {name: f"{DIR}/{name}_slice*.csv" for name in SLICES}
    overrides["counts"] = "qiime2/barplot/level-2.csv"
    return resolve_sources(ANCOMBC, root, {**overrides, **(extra or {})})


PARAMS = {"pairwise": True, "group_col": "locality"}


def test_the_missing_pair_is_added(tmp_path: Path) -> None:
    _write_run(tmp_path, "Bacteria", seed=1)
    pipeline = ANCOMBC.transform(_sources(tmp_path))

    out = ANCOMBC.transform(_sources(tmp_path), params=PARAMS)

    assert sorted(out["contrast"].unique()) == [
        "localityBarcelona", "localityNaples", "localityNaples_vs_Barcelona",
    ]  # fmt: skip
    # The pipeline's own rows are kept as they are.
    kept = out.filter(pl.col("contrast") != "localityNaples_vs_Barcelona").sort("contrast", "id")
    assert kept.equals(pipeline.sort("contrast", "id"))
    added = out.filter(pl.col("contrast") == "localityNaples_vs_Barcelona")
    assert added.height == 12 and added["Phylum"].null_count() == 0


def test_without_pairwise_nothing_is_computed(tmp_path: Path) -> None:
    _write_run(tmp_path, "Bacteria", seed=1)

    out = ANCOMBC.transform(_sources(tmp_path), params={"group_col": "locality"})

    assert "localityNaples_vs_Barcelona" not in out["contrast"].to_list()


def test_each_run_gets_its_pairs(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DEPICTIO_CONTEXT", "cli")  # the second run sits outside the root
    alt_dir = "qiime2/ancombc/differentials/Category-locality-level-4"
    _write_run(tmp_path / "silva", "Bacteria", seed=1)
    _write_run(tmp_path / "pr2", "Eukaryota;TSAR;Alveolata", seed=2, slice_dir=alt_dir, level=4)
    pr2 = tmp_path / "pr2"
    extra = {f"{n}_alt": str(pr2 / alt_dir / f"{n}_slice.csv") for n in SLICES}
    extra["alt_counts"] = str(pr2 / "qiime2" / "barplot" / "level-4.csv")

    out = ANCOMBC.transform(
        _sources(tmp_path / "silva", extra), params={**PARAMS, "label": "silva", "alt_label": "pr2"}
    )

    per_label = out.group_by("taxonomy", "contrast").len().sort("taxonomy", "contrast")
    assert per_label.to_dicts() == [
        {"taxonomy": t, "contrast": c, "len": 12}
        for t in ("pr2", "silva")
        for c in ("localityBarcelona", "localityNaples", "localityNaples_vs_Barcelona")
    ]


def test_the_merged_taxonomy_gets_every_pair(tmp_path: Path) -> None:
    _write_run(tmp_path, "Bacteria", seed=1)
    counts, _ = _counts("x", seed=5, taxa=6)
    asvs = [f"asv{i}" for i in range(6)]
    table = tmp_path / "qiime2" / "abundance_tables" / "feature-table.tsv"
    table.parent.mkdir(parents=True)
    body = pd.DataFrame(counts.T.to_numpy(), index=asvs, columns=counts.index)
    table.write_text(
        "# Constructed from biom file\n" + body.rename_axis("#OTU ID").to_csv(sep="\t")
    )
    sources = _sources(tmp_path, {"feature_table": "qiime2/abundance_tables/feature-table.tsv"})
    sources["merged_taxonomy"] = pl.DataFrame(
        {
            "ID": asvs,
            "Kingdom": ["Eukaryota", "Eukaryota", "Bacteria", "Bacteria", "Bacteria", None],
            "Phylum": ["Arthropoda", "Mollusca", "Pseudomonadota", "Pseudomonadota", None, "x"],
        }
    )

    out = ANCOMBC.transform(sources, params={**PARAMS, "label": "silva"})

    merged = out.filter(pl.col("taxonomy") == "merged")
    assert sorted(merged["contrast"].unique()) == [
        "localityBarcelona", "localityNaples", "localityNaples_vs_Barcelona",
    ]  # fmt: skip
    assert sorted(merged["id"].unique()) == [
        "Bacteria;Pseudomonadota", "Eukaryota;Arthropoda", "Eukaryota;Mollusca",
    ]  # fmt: skip
    # With a merged taxonomy next to it, the run's own rows are labelled.
    assert out.filter(pl.col("taxonomy") == "silva").height == 36


def test_ma_takes_the_merged_abundance_from_the_collapsed_counts(tmp_path: Path) -> None:
    table = tmp_path / "feature-table.tsv"
    table.write_text("# Constructed from biom file\n#OTU ID\tS0\tS1\na\t9\t0\nb\t90\t99\n")
    resolved = resolve_sources(MA, tmp_path, {"feature_table": str(table)})
    ancombc = pl.DataFrame(
        {
            "id": ["Eukaryota;Arthropoda", "Eukaryota;Mollusca"],
            "lfc": [1.0, 2.0],
            "q_val": [0.01, 0.02],
            "Phylum": ["Arthropoda", "Mollusca"],
            "contrast": ["localityNaples"] * 2,
            "taxonomy": ["merged"] * 2,
        }
    )

    out = MA.transform(
        {
            "ancombc": ancombc,
            "composition": pl.DataFrame({"taxonomy": ["Bacteria;x"], "count": [1.0]}),
            "labelled_barplots": None,
            "alt_barplot": None,
            "feature_table": resolved["feature_table"],
            "merged_taxonomy": pl.DataFrame(
                {
                    "ID": ["a", "b"],
                    "Kingdom": ["Eukaryota"] * 2,
                    "Phylum": ["Arthropoda", "Mollusca"],
                }
            ),
        }
    ).sort("feature_id")

    assert out["avg_log_intensity"][0] == 1.0  # log10(9 + 1); the zero is left out
    assert abs(out["avg_log_intensity"][1] - (np.log10(91) + 2.0) / 2) < 1e-9
