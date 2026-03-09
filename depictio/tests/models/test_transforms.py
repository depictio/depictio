"""
Tests for the recipe/transform Pydantic models (depictio/models/models/transforms.py).

Covers:
- RecipeSource validation (ref, format, path, dc_ref, read_kwargs)
- SourceOverride validation
- TransformConfig validation (recipe path format)
"""

import pytest

from depictio.models.models.transforms import RecipeSource, SourceOverride, TransformConfig


class TestRecipeSource:
    """Tests for RecipeSource model."""

    def test_valid_csv_source(self) -> None:
        """CSV source with path creates successfully."""
        source = RecipeSource(ref="data", path="output/data.csv", format="CSV")
        assert source.ref == "data"
        assert source.format == "csv"  # normalized to lowercase
        assert source.path == "output/data.csv"

    def test_valid_tsv_source(self) -> None:
        """TSV format is accepted and normalized."""
        source = RecipeSource(ref="meta", path="meta.tsv", format="TSV")
        assert source.format == "tsv"

    def test_valid_parquet_source(self) -> None:
        """Parquet format is accepted."""
        source = RecipeSource(ref="table", path="data.parquet", format="parquet")
        assert source.format == "parquet"

    def test_dc_ref_source(self) -> None:
        """Source with dc_ref and no path is valid."""
        source = RecipeSource(ref="metadata", dc_ref="metadata")
        assert source.dc_ref == "metadata"
        assert source.path is None

    def test_source_with_read_kwargs(self) -> None:
        """read_kwargs are stored correctly."""
        source = RecipeSource(
            ref="data", path="data.tsv", format="tsv", read_kwargs={"skip_rows": 1}
        )
        assert source.read_kwargs == {"skip_rows": 1}

    def test_empty_ref_raises(self) -> None:
        """Empty ref raises ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            RecipeSource(ref="", path="data.csv")

    def test_invalid_format_raises(self) -> None:
        """Unsupported format raises ValueError."""
        with pytest.raises(ValueError, match="format must be one of"):
            RecipeSource(ref="data", path="data.json", format="json")

    def test_extra_fields_forbidden(self) -> None:
        """Extra fields are rejected."""
        with pytest.raises(Exception):
            RecipeSource.model_validate(
                {"ref": "data", "path": "data.csv", "unknown_field": "value"}
            )

    def test_default_format_is_csv(self) -> None:
        """Default format is CSV."""
        source = RecipeSource(ref="data", path="data.csv")
        assert source.format.lower() == "csv"


class TestSourceOverride:
    """Tests for SourceOverride model."""

    def test_valid_override(self) -> None:
        """Valid override with path."""
        override = SourceOverride(path="alternate/data.csv")
        assert override.path == "alternate/data.csv"

    def test_extra_fields_forbidden(self) -> None:
        """Extra fields are rejected."""
        with pytest.raises(Exception):
            SourceOverride.model_validate({"path": "data.csv", "extra": "bad"})


class TestTransformConfig:
    """Tests for TransformConfig model."""

    def test_valid_config(self) -> None:
        """Valid recipe path accepted."""
        config = TransformConfig(recipe="nf-core/ampliseq/alpha_diversity.py")
        assert config.recipe == "nf-core/ampliseq/alpha_diversity.py"

    def test_empty_recipe_raises(self) -> None:
        """Empty recipe path raises ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            TransformConfig(recipe="")

    def test_recipe_must_be_py_file(self) -> None:
        """Recipe must end with .py."""
        with pytest.raises(ValueError, match="must be a .py file"):
            TransformConfig(recipe="nf-core/ampliseq/alpha_diversity")

    def test_config_with_overrides(self) -> None:
        """TransformConfig with source overrides."""
        config = TransformConfig(
            recipe="nf-core/ampliseq/alpha_diversity.py",
            source_overrides={"faith_pd": SourceOverride(path="custom/faith.tsv")},
        )
        assert config.source_overrides is not None
        assert "faith_pd" in config.source_overrides

    def test_config_without_overrides(self) -> None:
        """TransformConfig without overrides defaults to None."""
        config = TransformConfig(recipe="nf-core/ampliseq/alpha_diversity.py")
        assert config.source_overrides is None

    def test_extra_fields_forbidden(self) -> None:
        """Extra fields are rejected."""
        with pytest.raises(Exception):
            TransformConfig.model_validate({"recipe": "test.py", "extra": "bad"})
