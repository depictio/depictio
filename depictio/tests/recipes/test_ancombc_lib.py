"""ANCOM-BC at ingest (recipes/lib/ancombc.py): the pairs a pipeline did not run.

The agreement with QIIME2's own ANCOM-BC (R ANCOMBC, ``conserve`` on) was checked on a
real ampliseq run, where every estimate, standard error and q-value matched; no run is
small enough to commit. These tests hold the parts that make that agreement possible.
"""

import numpy as np
import pandas as pd
import polars as pl
import pytest

pytest.importorskip("skbio")

from depictio.recipes.lib import ancombc as lib  # noqa: E402


def _counts(levels=("Athens", "Barcelona", "Naples"), per_level=12, taxa=15, seed=3):
    """Samples x taxa counts; ``T0`` is ten times as abundant in the last level."""
    rng = np.random.default_rng(seed)
    rows, groups = [], []
    for k, level in enumerate(levels):
        for s in range(per_level):
            mean = rng.uniform(20, 200, size=taxa)
            if k == len(levels) - 1:
                mean[0] *= 10
            rows.append(rng.poisson(mean))
            groups.append(level)
    index = [f"S{i}" for i in range(len(rows))]
    counts = pd.DataFrame(rows, index=index, columns=[f"Bacteria;T{i}" for i in range(taxa)])
    return counts, pd.Series(groups, index=index, name="locality")


class TestPairs:
    def test_only_the_missing_pair_is_computed(self):
        counts, groups = _counts()

        out = lib.pairs(counts, groups, "locality", skip=["localityBarcelona", "localityNaples"])

        assert out["contrast"].unique().to_list() == ["localityNaples_vs_Barcelona"]
        assert out.height == counts.shape[1]
        top = out.filter(pl.col("id") == "Bacteria;T0").row(0, named=True)
        assert top["lfc"] > 1.5 and top["q_val"] < 0.05

    def test_more_sites_give_every_pair(self):
        counts, groups = _counts(levels=("A", "B", "C", "D"))

        out = lib.pairs(counts, groups, "g")

        assert sorted(out["contrast"].unique()) == [
            "gB", "gC", "gC_vs_B", "gD", "gD_vs_B", "gD_vs_C",
        ]  # fmt: skip

    def test_the_pipelines_reference_names_its_pairs(self):
        """ampliseq run with --ancombc_formula_reflvl: its plain names are against that level."""
        counts, groups = _counts()

        out = lib.pairs(counts, groups, "locality", base="Barcelona")

        assert sorted(out["contrast"].unique()) == [
            "localityAthens", "localityNaples", "localityNaples_vs_Athens",
        ]  # fmt: skip

    def test_base_is_read_from_the_pipelines_contrasts(self):
        levels = ["Athens", "Barcelona", "Naples"]

        assert lib.base_of(["localityBarcelona", "localityNaples"], "locality", levels) == "Athens"
        assert lib.base_of(["localityAthens", "localityNaples"], "locality", levels) == "Barcelona"
        assert lib.base_of([], "locality", levels) is None


class TestFit:
    def test_conserve_widens_every_error_by_one_constant(self):
        counts, groups = _counts()

        on = lib.fit(counts, groups, "Athens").sort("level", "id")
        off = lib.fit(counts, groups, "Athens", conserve=False).sort("level", "id")

        assert on["lfc"].to_list() == off["lfc"].to_list()
        for level in ("Barcelona", "Naples"):
            gap = (
                on.filter(pl.col("level") == level)["se"]
                - off.filter(pl.col("level") == level)["se"]
            )
            assert gap.min() > 0
            assert gap.max() - gap.min() < 1e-12

    def test_conserve_off_is_scikit_bios_ancombc(self):
        from skbio.stats.composition import ancombc

        counts, groups = _counts()
        ours = lib.fit(counts, groups, "Athens", conserve=False).filter(pl.col("level") == "Naples")
        theirs = ancombc(
            counts + 1, pd.DataFrame({"locality": groups.astype(object)}), "locality"
        ).result.xs("locality[T.Naples]", level="Covariate")

        ours = ours.sort("id")
        assert np.allclose(ours["se"].to_numpy(), theirs.loc[ours["id"].to_list(), "SE"].to_numpy())
        assert np.allclose(ours["q_val"].to_numpy(), theirs.loc[ours["id"].to_list(), "qvalue"])

    def test_rare_taxa_and_unlabelled_samples_are_left_out(self):
        counts, groups = _counts()
        counts["Bacteria;rare"] = 0
        counts.iloc[0, -1] = 5  # present in 1 of 36 samples, under the 10% cut
        groups.iloc[1] = None

        out = lib.fit(counts, groups, "Athens")

        assert "Bacteria;rare" not in out["id"].to_list()


def test_collapse_sums_asvs_per_merged_phylum():
    table = pl.DataFrame(
        {"#OTU ID": ["a", "b", "c", "d"], "S1": [1.0, 2.0, 4.0, 8.0], "S2": [0.0, 1.0, 0.0, 3.0]}
    )
    lineages = pl.DataFrame(
        {
            "ID": ["a", "b", "c", "d"],
            "Kingdom": ["Eukaryota", "Eukaryota", "Bacteria", None],
            "Phylum": ["Arthropoda", "Arthropoda", None, "x"],
        }
    )

    out = lib.collapse(table, lineages)

    assert out.columns.tolist() == ["Eukaryota;Arthropoda"]
    assert out.loc["S1"].tolist() == [3.0] and out.loc["S2"].tolist() == [1.0]
