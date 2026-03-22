"""Pure unit tests for the recipe/transform system.

Tests here use only synthetic in-memory data and never load real recipe modules
from disk. Pipeline-specific tests (ampliseq, etc.) belong in
depictio/tests/integration/.
"""

import polars as pl
import pytest

from depictio.models.models.transforms import RecipeSource, TransformConfig
from depictio.recipes import RecipeError, validate_schema


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
        s = RecipeSource(ref="joined", dc_ref="other_dc")
        assert s.dc_ref == "other_dc"
        assert s.path is None

    def test_optional_default_false(self):
        s = RecipeSource(ref="data", path="data.csv")
        assert s.optional is False

    def test_optional_dc_ref_source(self):
        s = RecipeSource(ref="joined", dc_ref="other_dc", optional=True)
        assert s.optional is True


class TestTransformConfig:
    def test_valid_config(self):
        c = TransformConfig(recipe="vendor/pipeline/transform.py")
        assert c.recipe == "vendor/pipeline/transform.py"

    def test_empty_recipe(self):
        with pytest.raises(ValueError, match="recipe path cannot be empty"):
            TransformConfig(recipe="")

    def test_non_py_recipe(self):
        with pytest.raises(ValueError, match="recipe must be a .py file"):
            TransformConfig(recipe="my_recipe.yaml")


# ---------------------------------------------------------------------------
# Schema validation unit tests
# ---------------------------------------------------------------------------


class TestValidateSchema:
    def test_missing_required_column(self):
        df = pl.DataFrame({"a": [1]})
        with pytest.raises(RecipeError, match="missing output column 'b'"):
            validate_schema(df, {"b": pl.Int64}, "test_recipe")

    def test_wrong_dtype(self):
        df = pl.DataFrame({"a": ["hello"]})
        with pytest.raises(RecipeError, match="expected Int64"):
            validate_schema(df, {"a": pl.Int64}, "test_recipe")

    def test_valid_schema_passes(self):
        df = pl.DataFrame({"a": [1], "b": ["x"]})
        validate_schema(df, {"a": pl.Int64, "b": pl.Utf8}, "test_recipe")

    def test_extra_columns_ignored(self):
        """Columns not in expected_schema are not checked (not an error)."""
        df = pl.DataFrame({"a": [1], "extra": ["ignored"]})
        validate_schema(df, {"a": pl.Int64}, "test_recipe")

    def test_optional_schema_absent_col_passes(self):
        """Optional column absent from result: validation passes."""
        df = pl.DataFrame({"a": [1]})
        validate_schema(df, {"a": pl.Int64}, "test_recipe", optional_schema={"opt_col": pl.Utf8})

    def test_optional_schema_present_correct_type(self):
        """Optional column present with correct type: validation passes."""
        df = pl.DataFrame({"a": [1], "opt_col": ["value"]})
        validate_schema(df, {"a": pl.Int64}, "test_recipe", optional_schema={"opt_col": pl.Utf8})

    def test_optional_schema_present_wrong_type_raises(self):
        """Optional column present with wrong type: RecipeError raised."""
        df = pl.DataFrame({"a": [1], "opt_col": [42]})
        with pytest.raises(RecipeError, match="optional column 'opt_col'"):
            validate_schema(df, {"a": pl.Int64}, "test_recipe", optional_schema={"opt_col": pl.Utf8})

    def test_optional_schema_none_is_noop(self):
        """optional_schema=None behaves the same as no optional_schema."""
        df = pl.DataFrame({"a": [1]})
        validate_schema(df, {"a": pl.Int64}, "test_recipe", optional_schema=None)
