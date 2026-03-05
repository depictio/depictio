"""Tests for the recipe/transform system."""

import polars as pl
import pytest

from depictio.models.models.transforms import RecipeSource, TransformConfig
from depictio.recipes import (
    RecipeError,
    list_recipes,
    load_recipe,
    validate_schema,
)

# ---------------------------------------------------------------------------
# RecipeSource model tests
# ---------------------------------------------------------------------------


class TestRecipeSource:
    def test_valid_source(self):
        s = RecipeSource(ref="my_source", path="data/file.csv", format="CSV")
        assert s.ref == "my_source"
        assert s.format == "csv"  # normalized to lowercase

    def test_tsv_format(self):
        s = RecipeSource(ref="x", path="f.tsv", format="TSV")
        assert s.format == "tsv"

    def test_invalid_format(self):
        with pytest.raises(ValueError, match="format must be one of"):
            RecipeSource(ref="x", path="f.txt", format="excel")

    def test_empty_ref(self):
        with pytest.raises(ValueError, match="ref cannot be empty"):
            RecipeSource(ref="", path="f.csv")

    def test_dc_ref_source(self):
        s = RecipeSource(ref="metadata", dc_ref="metadata")
        assert s.dc_ref == "metadata"
        assert s.path is None


class TestTransformConfig:
    def test_valid_config(self):
        c = TransformConfig(recipe="nf-core/ampliseq/alpha_diversity.py")
        assert c.recipe == "nf-core/ampliseq/alpha_diversity.py"

    def test_empty_recipe(self):
        with pytest.raises(ValueError, match="recipe path cannot be empty"):
            TransformConfig(recipe="")

    def test_non_py_recipe(self):
        with pytest.raises(ValueError, match="recipe must be a .py file"):
            TransformConfig(recipe="my_recipe.yaml")


# ---------------------------------------------------------------------------
# Recipe loader tests
# ---------------------------------------------------------------------------


class TestRecipeLoader:
    def test_load_alpha_diversity(self):
        module = load_recipe("nf-core/ampliseq/alpha_diversity.py")
        assert hasattr(module, "SOURCES")
        assert hasattr(module, "EXPECTED_SCHEMA")
        assert callable(module.transform)
        assert len(module.SOURCES) == 1
        assert module.SOURCES[0].ref == "faith_pd"

    def test_load_ancombc(self):
        module = load_recipe("nf-core/ampliseq/ancombc.py")
        assert len(module.SOURCES) == 5

    def test_load_taxonomy(self):
        module = load_recipe("nf-core/ampliseq/taxonomy_rel_abundance.py")
        assert len(module.SOURCES) == 2
        # One source uses dc_ref
        dc_ref_sources = [s for s in module.SOURCES if s.dc_ref is not None]
        assert len(dc_ref_sources) == 1

    def test_load_nonexistent(self):
        with pytest.raises(RecipeError, match="Recipe not found"):
            load_recipe("nonexistent/recipe.py")

    def test_list_recipes(self):
        recipes = list_recipes()
        assert len(recipes) >= 3
        assert "nf-core/ampliseq/alpha_diversity.py" in recipes
        assert "nf-core/ampliseq/ancombc.py" in recipes
        assert "nf-core/ampliseq/taxonomy_rel_abundance.py" in recipes


# ---------------------------------------------------------------------------
# Recipe execution tests with synthetic data
# ---------------------------------------------------------------------------


class TestAlphaDiversityRecipe:
    def test_transform(self):
        module = load_recipe("nf-core/ampliseq/alpha_diversity.py")
        # Synthetic data matching raw Faith PD vector format
        df = pl.DataFrame(
            {
                "id": ["#q2:types", "sample1", "sample2", "sample3"],
                "faith_pd": ["numeric", "12.5", "8.3", "15.1"],
                "habitat": ["categorical", "soil", "water", "soil"],
            }
        )
        result = module.transform({"faith_pd": df})
        assert result.columns == ["sample", "habitat", "faith_pd"]
        assert result.height == 3  # #q2:types row filtered out
        assert result["faith_pd"].dtype == pl.Float64
        validate_schema(result, module.EXPECTED_SCHEMA, "alpha_diversity")


class TestAncomBCRecipe:
    def test_transform(self):
        module = load_recipe("nf-core/ampliseq/ancombc.py")
        # Synthetic ANCOM-BC data (2 taxa, 1 contrast)
        taxa = ["Bacteria;Firmicutes;Bacilli", "Bacteria;Proteobacteria;Gamma"]
        for name in ["lfc", "p_val", "q_val", "w", "se"]:
            vals = {
                "lfc": [1.5, -0.8],
                "p_val": [0.01, 0.2],
                "q_val": [0.03, 0.4],
                "w": [2.1, -0.5],
                "se": [0.3, 0.6],
            }
            globals()[f"df_{name}"] = pl.DataFrame(
                {
                    "id": taxa,
                    "(Intercept)": [0.0, 0.0],
                    "habitat_soil": vals[name],
                }
            )

        sources = {name: globals()[f"df_{name}"] for name in ["lfc", "p_val", "q_val", "w", "se"]}
        result = module.transform(sources)
        assert result.height == 2  # 2 taxa x 1 contrast
        assert "Kingdom" in result.columns
        assert "significant" in result.columns
        assert result["significant"].dtype == pl.Boolean
        validate_schema(result, module.EXPECTED_SCHEMA, "ancombc")


class TestSchemaValidation:
    def test_missing_column(self):
        df = pl.DataFrame({"a": [1]})
        with pytest.raises(RecipeError, match="missing output column 'b'"):
            validate_schema(df, {"b": pl.Int64}, "test")

    def test_wrong_type(self):
        df = pl.DataFrame({"a": ["hello"]})
        with pytest.raises(RecipeError, match="expected Int64"):
            validate_schema(df, {"a": pl.Int64}, "test")

    def test_valid_schema(self):
        df = pl.DataFrame({"a": [1], "b": ["x"]})
        validate_schema(df, {"a": pl.Int64, "b": pl.Utf8}, "test")  # should not raise
