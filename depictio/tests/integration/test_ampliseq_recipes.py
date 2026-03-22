"""
Integration tests for the nf-core/ampliseq recipe system.

These tests load real ampliseq recipe modules from disk and exercise their
transform() functions against synthetic data that mirrors the actual ampliseq
output file formats (shapes, column names, dtypes).

They complement the pure unit tests in depictio/tests/unit/ and
depictio/tests/cli/utils/ which use only in-memory synthetic data and never
depend on any specific pipeline.

Requires the ampliseq recipes to be present in depictio/projects/nf-core/ampliseq/.
"""

import polars as pl

from depictio.recipes import list_recipes, load_recipe

# ---------------------------------------------------------------------------
# Ampliseq recipe discovery
# ---------------------------------------------------------------------------

AMPLISEQ_RECIPES = [
    "nf-core/ampliseq/alpha_diversity.py",
    "nf-core/ampliseq/alpha_rarefaction.py",
    "nf-core/ampliseq/ancombc.py",
    "nf-core/ampliseq/taxonomy_composition.py",
    "nf-core/ampliseq/taxonomy_rel_abundance.py",
]

AMPLISEQ_VERSIONS = ["2.14.0", "2.16.0"]


class TestAmpliseqRecipeDiscovery:
    """Verify ampliseq recipes are discoverable and loadable."""

    def test_all_ampliseq_recipes_listed(self) -> None:
        """All known ampliseq shared recipes appear in list_recipes()."""
        recipes = list_recipes()
        for recipe in AMPLISEQ_RECIPES:
            assert recipe in recipes, f"Missing recipe: {recipe}"

    def test_version_overrides_not_listed(self) -> None:
        """Version-specific overrides (2.14.0, 2.16.0) are not in list_recipes()."""
        recipes = list_recipes()
        for version in AMPLISEQ_VERSIONS:
            assert not any(f"/{version}/" in r for r in recipes)

    def test_all_ampliseq_recipes_load(self) -> None:
        """Every bundled ampliseq recipe loads with valid SOURCES, EXPECTED_SCHEMA, transform."""
        for recipe_name in AMPLISEQ_RECIPES:
            module = load_recipe(recipe_name)
            assert hasattr(module, "SOURCES"), f"{recipe_name}: missing SOURCES"
            assert hasattr(module, "EXPECTED_SCHEMA"), f"{recipe_name}: missing EXPECTED_SCHEMA"
            assert callable(module.transform), f"{recipe_name}: transform not callable"
            assert isinstance(module.SOURCES, list) and len(module.SOURCES) > 0
            assert isinstance(module.EXPECTED_SCHEMA, dict) and len(module.EXPECTED_SCHEMA) > 0

    def test_version_override_loads_for_taxonomy_rel_abundance(self) -> None:
        """v2.14.0 has an override for taxonomy_rel_abundance."""
        module_v14 = load_recipe("nf-core/ampliseq/taxonomy_rel_abundance.py", "2.14.0")
        module_shared = load_recipe("nf-core/ampliseq/taxonomy_rel_abundance.py")
        assert callable(module_v14.transform)
        assert callable(module_shared.transform)

    def test_version_fallback_for_alpha_diversity(self) -> None:
        """alpha_diversity has no version override; versioned load falls back to shared."""
        module_versioned = load_recipe("nf-core/ampliseq/alpha_diversity.py", "2.14.0")
        module_shared = load_recipe("nf-core/ampliseq/alpha_diversity.py")
        assert module_versioned.SOURCES == module_shared.SOURCES

    def test_locate_ampliseq_template(self) -> None:
        """nf-core/ampliseq/2.16.0 template.yaml is discoverable."""
        from depictio.cli.cli.utils.templates import locate_template

        path = locate_template("nf-core/ampliseq/2.16.0")
        assert path.is_file()
        assert path.name in ("template.yaml", "project.yaml")


# ---------------------------------------------------------------------------
# Alpha diversity recipe
# ---------------------------------------------------------------------------


class TestAlphaDiversityRecipe:
    """Tests for alpha_diversity transform with ampliseq-shaped synthetic data."""

    def _faith_pd_df(self, extra_cols: dict | None = None) -> pl.DataFrame:
        """Minimal faith_pd_vector/metadata.tsv (with optional embedded metadata)."""
        data = {
            "id": ["#q2:types", "sample1", "sample2", "sample3"],
            "faith_pd": ["categorical", "3.14", "2.71", "1.41"],
        }
        if extra_cols:
            for col, values in extra_cols.items():
                data[col] = values
        return pl.DataFrame(data)

    def test_transform_minimal(self) -> None:
        """Without embedded metadata: returns sample + faith_pd only."""
        module = load_recipe("nf-core/ampliseq/alpha_diversity.py")
        df = self._faith_pd_df()
        result = module.transform({"faith_pd": df})
        assert "sample" in result.columns
        assert "faith_pd" in result.columns
        assert "#q2:types" not in result["sample"].to_list()
        assert result["faith_pd"].dtype == pl.Float64

    def test_transform_with_embedded_metadata(self) -> None:
        """With QIIME2-embedded habitat column: sample + faith_pd + habitat returned."""
        module = load_recipe("nf-core/ampliseq/alpha_diversity.py")
        df = self._faith_pd_df(
            extra_cols={"habitat": ["categorical", "river", "groundwater", "river"]}
        )
        result = module.transform({"faith_pd": df})
        assert "sample" in result.columns
        assert "faith_pd" in result.columns
        assert "habitat" in result.columns
        assert "#q2:types" not in result["sample"].to_list()


# ---------------------------------------------------------------------------
# Alpha rarefaction recipe
# ---------------------------------------------------------------------------


class TestAlphaRarefactionRecipe:
    """Tests for alpha_rarefaction transform with ampliseq-shaped synthetic data."""

    def _rarefaction_df(self) -> pl.DataFrame:
        """Minimal faith_pd.csv with depth-*_iter-* column names."""
        return pl.DataFrame(
            {
                "sample-id": ["sample1", "sample2"],
                "depth-100_iter-1": [1.1, 2.2],
                "depth-100_iter-2": [1.3, 2.4],
                "depth-500_iter-1": [3.1, 4.2],
            }
        )

    def test_transform_produces_long_format(self) -> None:
        """transform produces long format with sample, depth, iter, faith_pd."""
        module = load_recipe("nf-core/ampliseq/alpha_rarefaction.py")
        result = module.transform({"faith_pd_csv": self._rarefaction_df()})
        assert set(result.columns) == {"sample", "depth", "iter", "faith_pd"}
        # 2 samples × 3 depth-iter combos = 6 rows
        assert result.shape[0] == 6

    def test_schema_valid(self) -> None:
        """Output matches EXPECTED_SCHEMA."""
        from depictio.recipes import validate_schema

        module = load_recipe("nf-core/ampliseq/alpha_rarefaction.py")
        result = module.transform({"faith_pd_csv": self._rarefaction_df()})
        validate_schema(result, module.EXPECTED_SCHEMA, "alpha_rarefaction")


# ---------------------------------------------------------------------------
# AnCOM-BC recipe
# ---------------------------------------------------------------------------


class TestAncomBCRecipe:
    """Tests for ancombc transform with ampliseq-shaped synthetic data."""

    def _slice_df(self, value_col: str) -> pl.DataFrame:
        """Minimal ANCOM-BC slice CSV."""
        return pl.DataFrame(
            {
                "id": ["k__Bacteria;p__Firmicutes", "k__Bacteria;p__Proteobacteria"],
                "(Intercept)": [0.1, 0.2],
                "habitatriver": [1.5, -0.8],
            }
        )

    def test_transform_produces_expected_columns(self) -> None:
        """transform returns all EXPECTED_SCHEMA columns."""
        module = load_recipe("nf-core/ampliseq/ancombc.py")
        sources = {name: self._slice_df(name) for name in ["lfc", "p_val", "q_val", "w", "se"]}
        result = module.transform(sources)
        for col in module.EXPECTED_SCHEMA:
            assert col in result.columns, f"Missing column: {col}"

    def test_schema_valid(self) -> None:
        """Output matches EXPECTED_SCHEMA."""
        from depictio.recipes import validate_schema

        module = load_recipe("nf-core/ampliseq/ancombc.py")
        sources = {name: self._slice_df(name) for name in ["lfc", "p_val", "q_val", "w", "se"]}
        result = module.transform(sources)
        validate_schema(result, module.EXPECTED_SCHEMA, "ancombc")

    def test_significant_column_is_boolean(self) -> None:
        """'significant' column (q_val < 0.05) is Boolean."""
        module = load_recipe("nf-core/ampliseq/ancombc.py")
        sources = {name: self._slice_df(name) for name in ["lfc", "p_val", "q_val", "w", "se"]}
        result = module.transform(sources)
        assert result["significant"].dtype == pl.Boolean


# ---------------------------------------------------------------------------
# Taxonomy composition recipe
# ---------------------------------------------------------------------------


class TestTaxonomyCompositionRecipe:
    """Tests for taxonomy_composition transform with ampliseq-shaped synthetic data."""

    def _barplot_df(self, include_habitat: bool = True) -> pl.DataFrame:
        """Minimal barplot level-2.csv."""
        data = {
            "index": ["sample1", "sample2"],
            "k__Bacteria;p__Firmicutes": [100.0, 200.0],
            "k__Bacteria;p__Proteobacteria": [50.0, 75.0],
        }
        if include_habitat:
            data["habitat"] = ["river", "groundwater"]
        return pl.DataFrame(data)

    def test_transform_long_format(self) -> None:
        """transform melts to long format with sample, taxonomy, count, habitat."""
        module = load_recipe("nf-core/ampliseq/taxonomy_composition.py")
        result = module.transform({"barplot_csv": self._barplot_df()})
        assert set(result.columns) == {"sample", "taxonomy", "count", "habitat"}
        # 2 samples × 2 taxonomy cols = 4 rows (none are zero)
        assert result.shape[0] == 4

    def test_transform_without_habitat(self) -> None:
        """Without habitat column in CSV: null habitat column is added."""
        module = load_recipe("nf-core/ampliseq/taxonomy_composition.py")
        result = module.transform({"barplot_csv": self._barplot_df(include_habitat=False)})
        assert "habitat" in result.columns
        assert result["habitat"].is_null().all()

    def test_schema_valid(self) -> None:
        """Output matches EXPECTED_SCHEMA."""
        from depictio.recipes import validate_schema

        module = load_recipe("nf-core/ampliseq/taxonomy_composition.py")
        result = module.transform({"barplot_csv": self._barplot_df()})
        validate_schema(result, module.EXPECTED_SCHEMA, "taxonomy_composition")


# ---------------------------------------------------------------------------
# Taxonomy relative abundance recipe
# ---------------------------------------------------------------------------


class TestTaxonomyRelAbundanceRecipe:
    """Tests for taxonomy_rel_abundance transform with ampliseq-shaped synthetic data."""

    def _rel_table_df(self) -> pl.DataFrame:
        """Minimal rel-table-2.tsv (after skip_rows=1)."""
        return pl.DataFrame(
            {
                "#OTU ID": ["k__Bacteria;p__Firmicutes", "k__Bacteria;p__Proteobacteria"],
                "sample1": [0.6, 0.4],
                "sample2": [0.3, 0.7],
            }
        )

    def test_transform_without_metadata(self) -> None:
        """Without metadata source: returns core columns only."""
        module = load_recipe("nf-core/ampliseq/taxonomy_rel_abundance.py")
        result = module.transform({"rel_table": self._rel_table_df(), "metadata": None})
        assert set(result.columns) == {"sample", "taxonomy", "rel_abundance", "Kingdom", "Phylum"}

    def test_transform_with_metadata(self) -> None:
        """With metadata source: all metadata columns appended generically."""
        module = load_recipe("nf-core/ampliseq/taxonomy_rel_abundance.py")
        metadata = pl.DataFrame(
            {
                "ID": ["sample1", "sample2"],
                "habitat": ["river", "groundwater"],
                "site_id": ["A", "B"],
            }
        )
        result = module.transform({"rel_table": self._rel_table_df(), "metadata": metadata})
        assert "habitat" in result.columns
        assert "site_id" in result.columns
        # Core columns still present
        for col in ["sample", "taxonomy", "rel_abundance", "Kingdom", "Phylum"]:
            assert col in result.columns

    def test_schema_valid(self) -> None:
        """Output matches EXPECTED_SCHEMA (core columns checked, metadata cols ignored)."""
        from depictio.recipes import validate_schema

        module = load_recipe("nf-core/ampliseq/taxonomy_rel_abundance.py")
        result = module.transform({"rel_table": self._rel_table_df(), "metadata": None})
        validate_schema(result, module.EXPECTED_SCHEMA, "taxonomy_rel_abundance")

    def test_zero_abundance_rows_filtered(self) -> None:
        """Rows with rel_abundance == 0 or null are filtered out."""
        module = load_recipe("nf-core/ampliseq/taxonomy_rel_abundance.py")
        df = pl.DataFrame(
            {
                "#OTU ID": ["k__Bacteria;p__Firmicutes"],
                "sample1": [0.0],
                "sample2": [0.5],
            }
        )
        result = module.transform({"rel_table": df, "metadata": None})
        assert (result["rel_abundance"] > 0).all()
