"""SILVA + PR2 merged taxonomy of nf-core/ampliseq (the TREC AML 2024 rule).

Per ASV: PR2's lineage when PR2 calls it Eukaryota, else SILVA's. The rank
mapping carries PR2's two extra ranks above the Phylum (Supergroup, Division),
so these tests pin which PR2 rank lands in which SILVA slot. On the real TREC
run (127,845 ASVs) the recipe reproduces the hand-made merged folder exactly:
57,520 / 69,852 / 473 ASVs named by PR2 / SILVA / neither, and identical
rel-tables at levels 2 to 6.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest
import yaml

from depictio.cli.cli.utils.templates import _apply_conditionals, _load_yaml
from depictio.models.models.templates import TemplateMetadata
from depictio.recipes import PROJECTS_DIR, execute_recipe
from depictio.recipes.lib.dual_taxonomy import (
    SLOTS,
    SOURCE_COLUMN,
    collapse,
    merge_pr2,
    pr2_level,
)
from depictio.recipes.lib.lineage import asv_sample_columns

RECIPE = "nf-core/ampliseq/merged_taxonomy.py"
TEMPLATE = PROJECTS_DIR / "nf-core" / "ampliseq" / "2.18.0" / "template.yaml"
PR2_COLS = (
    "ID",
    "Domain",
    "Supergroup",
    "Division",
    "Subdivision",
    "Class",
    "Order",
    "Family",
    "Genus",
    "Species",
    "confidence",
)


def _silva() -> pl.DataFrame:
    """SILVA's view: a bacterium, two unresolved eukaryotes, one unassigned ASV."""
    rows = [
        # ID, Kingdom, Phylum, Class, Order, Family, Genus, Species, conf, s1, s2
        ("bac", "Bacteria", "Pseudomonadota", "Gamma", "O", "F", "Vibrio", "", "0.9", "0.4", "0.1"),
        ("dino", "Eukaryota", "", "", "", "", "", "", "0.8", "0.3", "0.2"),
        ("copepod", "Eukaryota", "", "", "", "", "", "", "0.7", "0.2", "0.3"),
        ("plastid", "Eukaryota", "", "", "", "", "", "", "0.6", "0.05", "0.1"),
        ("nobody", "", "", "", "", "", "", "", "", "0.05", "0.3"),
    ]
    cols = ["ID", *SLOTS, "confidence", "sequence", "s1", "s2"]
    return pl.DataFrame([(*r[:9], "ACGT", *r[9:]) for r in rows], schema=cols, orient="row").cast(
        pl.Utf8
    )


def _pr2() -> pl.DataFrame:
    rows = [
        ("bac", "Bacteria", "Pseudomonadota", "", "", "", "", "", "", "", "0.5"),
        (
            "dino",
            "Eukaryota",
            "TSAR",
            "Alveolata",
            "Dinoflagellata",
            "Dinophyceae",
            "Gonyaulacales",
            "Ceratiaceae",
            "Tripos",
            "Tripos_furca",
            "0.96",
        ),
        (
            "copepod",
            "Eukaryota",
            "Obazoa",
            "Opisthokonta",
            "Metazoa",
            "Arthropoda",
            "Crustacea",
            "Maxillopoda",
            "Calanus",
            "Calanus_finmarchicus",
            "0.99",
        ),
        (
            "plastid",
            "Eukaryota:plas",
            "Archaeplastida",
            "Chlorophyta",
            "",
            "",
            "",
            "",
            "",
            "",
            "0.4",
        ),
        ("nobody", "", "", "", "", "", "", "", "", "", ""),
    ]
    return pl.DataFrame(rows, schema=list(PR2_COLS), orient="row").cast(pl.Utf8)


def _by_id(df: pl.DataFrame) -> dict[str, dict]:
    return {row["ID"]: row for row in df.iter_rows(named=True)}


class TestRule:
    def test_each_asv_takes_the_database_that_names_it(self):
        merged = _by_id(merge_pr2(_silva(), _pr2()))

        assert {k: v[SOURCE_COLUMN] for k, v in merged.items()} == {
            "bac": "silva",
            "dino": "pr2",
            "copepod": "pr2",
            "plastid": "pr2",
            "nobody": "fallback",
        }
        assert merged["bac"]["Phylum"] == "Pseudomonadota"
        assert merged["bac"]["Genus"] == "Vibrio"
        assert merged["bac"]["confidence"] == pytest.approx(0.9)

    def test_pr2_ranks_shift_two_slots_up(self):
        """Phylum is PR2's 4th rank (Subdivision), not its 2nd (Supergroup)."""
        dino = _by_id(merge_pr2(_silva(), _pr2()))["dino"]

        assert [dino[s] for s in SLOTS] == [
            "Eukaryota",
            "Dinoflagellata",
            "Dinophyceae",
            "Gonyaulacales",
            "Ceratiaceae",
            "Tripos",
            "Tripos_furca",
        ]
        assert dino["confidence"] == pytest.approx(0.96)

    def test_metazoa_read_one_rank_deeper(self):
        copepod = _by_id(merge_pr2(_silva(), _pr2()))["copepod"]

        assert [copepod[s] for s in SLOTS] == [
            "Eukaryota",
            "Arthropoda",
            "Crustacea",
            "Maxillopoda",
            "Calanus",
            "Calanus_finmarchicus",
            None,
        ]

    def test_organelles_keep_their_kingdom_and_blanks_are_null(self):
        plastid = _by_id(merge_pr2(_silva(), _pr2()))["plastid"]

        assert plastid["Kingdom"] == "Eukaryota:plas"
        assert plastid["Phylum"] is None

    @pytest.mark.parametrize(
        ("rank", "phylum"), [("Division", "Alveolata"), ("Class", "Dinophyceae")]
    )
    def test_the_phylum_rank_is_a_choice(self, rank, phylum):
        dino = _by_id(merge_pr2(_silva(), _pr2(), rank))["dino"]

        assert dino["Phylum"] == phylum

    def test_an_asv_pr2_lacks_keeps_silva(self):
        merged = _by_id(merge_pr2(_silva(), _pr2().filter(pl.col("ID") != "bac")))

        assert merged["bac"][SOURCE_COLUMN] == "silva"
        assert merged["bac"]["Phylum"] == "Pseudomonadota"

    def test_other_columns_and_rows_are_untouched(self):
        silva = _silva()
        merged = merge_pr2(silva, _pr2())

        assert merged.height == silva.height
        assert merged["s1"].to_list() == silva["s1"].to_list()
        assert SOURCE_COLUMN not in asv_sample_columns(merged)

    def test_bad_inputs_are_refused(self):
        with pytest.raises(ValueError, match="euk_phylum_rank"):
            merge_pr2(_silva(), _pr2(), "Supergroup")
        with pytest.raises(ValueError, match="PR2"):
            merge_pr2(_silva(), _silva())

    def test_pr2_level_of_the_merged_phylum(self):
        assert pr2_level("Subdivision") == 4
        assert pr2_level("Division") == 3


class TestCollapse:
    def test_rel_table_shape_with_blank_ranks_kept(self):
        merged = merge_pr2(_silva(), _pr2())

        table = collapse(merged, ["s1", "s2"], 2)

        assert table.columns == ["#OTU ID", "s1", "s2"]
        rows = {r[0]: r[1:] for r in table.iter_rows()}
        assert set(rows) == {
            ";",
            "Bacteria;Pseudomonadota",
            "Eukaryota;Arthropoda",
            "Eukaryota;Dinoflagellata",
            "Eukaryota:plas;",
        }
        assert rows["Eukaryota;Dinoflagellata"] == pytest.approx((0.3, 0.2))
        assert table["#OTU ID"].to_list() == sorted(table["#OTU ID"].to_list())

    def test_every_sample_still_sums_to_its_total(self):
        merged = merge_pr2(_silva(), _pr2())
        for level in range(1, 8):
            table = collapse(merged, ["s1", "s2"], level)
            assert table["s1"].sum() == pytest.approx(1.0)
            assert table["s2"].sum() == pytest.approx(1.0)


def _write_run(root: Path, table: pl.DataFrame) -> None:
    rel = root / "qiime2" / "rel_abundance_tables"
    rel.mkdir(parents=True)
    table.write_csv(rel / "rel-table-ASV_with-DADA2-tax.tsv", separator="\t")


class TestRecipe:
    def test_reads_both_runs_and_drops_the_sequences(self, tmp_path, monkeypatch):
        """The PR2 run sits outside DATA_ROOT, which the CLI reads as it is.

        A server reads it only from a folder its data policy allows.
        """
        monkeypatch.setenv("DEPICTIO_CONTEXT", "cli")
        _write_run(tmp_path / "silva", _silva())
        pr2 = _pr2().with_columns(pl.lit("ACGT").alias("sequence"), pl.lit("0.1").alias("s1"))
        _write_run(tmp_path / "pr2", pr2)
        pr2_table = tmp_path / "pr2" / "qiime2" / "rel_abundance_tables"

        out = execute_recipe(
            RECIPE,
            tmp_path / "silva",
            overrides={"pr2_tax": str(pr2_table / "rel-table-ASV_with-DADA2-tax.tsv")},
        )

        assert out.columns == ["ID", SOURCE_COLUMN, *SLOTS, "confidence", "s1", "s2"]
        assert out.schema["s1"] == pl.Float64
        assert dict(zip(out["ID"], out["Phylum"], strict=True))["dino"] == "Dinoflagellata"

    def test_euk_phylum_rank_param_and_unresolved_placeholder(self, tmp_path):
        frames = {"asv_tax": _silva(), "pr2_tax": _pr2().select(PR2_COLS)}

        division = execute_recipe(
            RECIPE, tmp_path, sources=frames, params={"euk_phylum_rank": "Division"}
        )
        default = execute_recipe(
            RECIPE, tmp_path, sources=frames, params={"euk_phylum_rank": "{EUK_PHYLUM_RANK}"}
        )

        assert dict(zip(division["ID"], division["Phylum"], strict=True))["dino"] == "Alveolata"
        assert dict(zip(default["ID"], default["Phylum"], strict=True))["dino"] == "Dinoflagellata"


class TestConsumers:
    """With the merged DC present, the taxonomy recipes read it, not SILVA's tables."""

    @pytest.fixture
    def merged(self) -> pl.DataFrame:
        silva = _silva().drop("sequence")
        return merge_pr2(silva, _pr2()).with_columns(pl.col(["s1", "s2"]).cast(pl.Float64))

    def test_phylum_relative_abundance(self, tmp_path, merged):
        silva_rel2 = collapse(_silva(), ["s1", "s2"], 2)

        out = execute_recipe(
            "nf-core/ampliseq/taxonomy_rel_abundance.py",
            tmp_path,
            sources={"rel_table": silva_rel2},
            extra_sources={"merged_taxonomy": merged, "metadata": None},
        )

        assert "Dinoflagellata" in set(out["Phylum"])
        assert "Eukaryota;" not in set(out["taxonomy"])

    def test_stacked_taxonomy(self, tmp_path, merged):
        silva = {
            ref: collapse(_silva(), ["s1", "s2"], level)
            for level, ref in enumerate(["phylum", "class_", "order", "family", "genus"], 2)
        }

        out = execute_recipe(
            "qiime2/stacked_taxonomy_canonical.py",
            tmp_path,
            sources=silva,
            extra_sources={"merged_taxonomy": merged, "metadata": None},
        )

        genus = set(out.filter(pl.col("rank") == "Genus")["taxon"])
        assert {"Tripos", "Calanus_finmarchicus", "Vibrio"} <= genus

    @pytest.mark.parametrize(
        ("recipe", "extra"),
        [
            ("nf-core/ampliseq/tree_metadata_canonical.py", {"taxonomy": None}),
            ("nf-core/ampliseq/sunburst_canonical.py", {"genus": None}),
            ("nf-core/ampliseq/sankey_canonical.py", {"genus": None}),
        ],
    )
    def test_asv_table_readers(self, tmp_path, merged, recipe, extra):
        out = execute_recipe(
            recipe,
            tmp_path,
            sources={"asv_tax": _silva(), **extra},
            extra_sources={"merged_taxonomy": merged, "metadata": None},
        )

        assert "Dinoflagellata" in set(out["Phylum"])


class TestTemplate:
    def _resolved(self, variables: dict[str, str]) -> list[dict]:
        metadata = TemplateMetadata(**_load_yaml(str(TEMPLATE))["template"])
        config = yaml.safe_load(TEMPLATE.read_text())
        config.pop("template")
        result, _, _ = _apply_conditionals(
            config, metadata.conditional, set(variables), TEMPLATE.parent, variables
        )
        return result["workflows"][0]["data_collections"]

    def test_without_pr2_results_there_is_no_merged_dc(self):
        tags = [dc["data_collection_tag"] for dc in self._resolved({"DATA_ROOT": "/silva"})]

        assert "merged_taxonomy" not in tags

    def test_pr2_results_points_the_merge_at_the_second_run(self):
        dcs = self._resolved({"DATA_ROOT": "/silva", "PR2_RESULTS": "/pr2"})
        (merged,) = [dc for dc in dcs if dc["data_collection_tag"] == "merged_taxonomy"]

        override = merged["config"]["transform"]["source_overrides"]["pr2_tax"]
        assert (
            override["path"] == "/pr2/qiime2/rel_abundance_tables/rel-table-ASV_with-DADA2-tax.tsv"
        )

    def test_merged_dc_is_declared_before_every_reader(self):
        """dc_ref inputs are read from Delta: the provider must be ingested first."""
        from depictio.recipes import load_recipe

        dcs = self._resolved({"DATA_ROOT": "/silva", "PR2_RESULTS": "/pr2"})
        tags = [dc["data_collection_tag"] for dc in dcs]
        readers = [
            dc["data_collection_tag"]
            for dc in dcs
            if (transform := dc["config"].get("transform"))
            and any(s.dc_ref == "merged_taxonomy" for s in load_recipe(transform["recipe"]).SOURCES)
        ]

        assert set(readers) == {
            "taxonomy_rel_abundance",
            "stacked_taxonomy_canonical",
            "sunburst_canonical",
            "sankey_canonical",
            "phylogenetic_tree_metadata_canonical",
        }
        assert all(tags.index("merged_taxonomy") < tags.index(t) for t in readers)
