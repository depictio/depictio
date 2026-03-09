"""
Tests for the recipe loader/executor system (depictio/recipes/__init__.py).

Covers:
- Recipe discovery (list_recipes)
- Recipe loading and validation (load_recipe)
- Source file reading (_read_source_file)
- Source resolution (resolve_sources)
- Schema validation (validate_schema)
- Full pipeline execution (execute_recipe)
"""

import tempfile
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import polars as pl
import pytest

from depictio.models.models.transforms import RecipeSource
from depictio.recipes import (
    RecipeError,
    _read_source_file,
    execute_recipe,
    list_recipes,
    load_recipe,
    resolve_sources,
    validate_schema,
)


class TestListRecipes:
    """Tests for recipe discovery."""

    def test_list_recipes_returns_sorted_list(self) -> None:
        """list_recipes returns a sorted list of recipe paths."""
        recipes = list_recipes()
        assert isinstance(recipes, list)
        assert recipes == sorted(recipes)

    def test_list_recipes_excludes_init_files(self) -> None:
        """__init__.py files are excluded from recipe list."""
        recipes = list_recipes()
        assert not any("__init__" in r for r in recipes)

    def test_list_recipes_contains_known_recipes(self) -> None:
        """Known ampliseq recipes are present in the list."""
        recipes = list_recipes()
        expected = [
            "nf-core/ampliseq/alpha_diversity.py",
            "nf-core/ampliseq/alpha_rarefaction.py",
            "nf-core/ampliseq/ancombc.py",
            "nf-core/ampliseq/taxonomy_composition.py",
            "nf-core/ampliseq/taxonomy_rel_abundance.py",
        ]
        for recipe in expected:
            assert recipe in recipes, f"Missing recipe: {recipe}"


class TestLoadRecipe:
    """Tests for recipe module loading and validation."""

    def test_load_known_recipe(self) -> None:
        """Loading a known recipe returns a module with required attributes."""
        module = load_recipe("nf-core/ampliseq/alpha_rarefaction.py")
        assert hasattr(module, "SOURCES")
        assert hasattr(module, "EXPECTED_SCHEMA")
        assert callable(module.transform)

    def test_load_recipe_sources_are_recipe_source_instances(self) -> None:
        """SOURCES must be a list of RecipeSource instances."""
        module = load_recipe("nf-core/ampliseq/alpha_rarefaction.py")
        assert isinstance(module.SOURCES, list)
        assert len(module.SOURCES) > 0
        for s in module.SOURCES:
            assert isinstance(s, RecipeSource)

    def test_load_recipe_not_found(self) -> None:
        """Loading a nonexistent recipe raises RecipeError."""
        with pytest.raises(RecipeError, match="not found"):
            load_recipe("nonexistent/recipe.py")

    def test_load_all_bundled_recipes(self) -> None:
        """Every bundled recipe loads successfully and has valid attributes."""
        recipes = list_recipes()
        for recipe_name in recipes:
            module = load_recipe(recipe_name)
            assert hasattr(module, "SOURCES")
            assert hasattr(module, "EXPECTED_SCHEMA")
            assert callable(module.transform)
            assert isinstance(module.SOURCES, list)
            assert len(module.SOURCES) > 0
            assert isinstance(module.EXPECTED_SCHEMA, dict)
            assert len(module.EXPECTED_SCHEMA) > 0


class TestReadSourceFile:
    """Tests for _read_source_file helper."""

    def test_read_csv(self) -> None:
        """Read a CSV file into a DataFrame."""
        with tempfile.NamedTemporaryFile(suffix=".csv", mode="w", delete=False) as f:
            f.write("a,b\n1,2\n3,4\n")
            f.flush()
            source = RecipeSource(ref="test", format="csv")
            df = _read_source_file(Path(f.name), source)
            assert df.shape == (2, 2)
            assert df.columns == ["a", "b"]

    def test_read_tsv(self) -> None:
        """Read a TSV file into a DataFrame."""
        with tempfile.NamedTemporaryFile(suffix=".tsv", mode="w", delete=False) as f:
            f.write("x\ty\n10\t20\n30\t40\n")
            f.flush()
            source = RecipeSource(ref="test", format="tsv")
            df = _read_source_file(Path(f.name), source)
            assert df.shape == (2, 2)
            assert df.columns == ["x", "y"]

    def test_read_with_kwargs(self) -> None:
        """read_kwargs are passed through to polars."""
        with tempfile.NamedTemporaryFile(suffix=".tsv", mode="w", delete=False) as f:
            f.write("# comment line\nx\ty\n10\t20\n")
            f.flush()
            source = RecipeSource(ref="test", format="tsv", read_kwargs={"skip_rows": 1})
            df = _read_source_file(Path(f.name), source)
            assert "x" in df.columns
            assert df.shape[0] == 1

    def test_read_unsupported_format(self) -> None:
        """Unsupported format raises RecipeError."""
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            f.write("{}")
            f.flush()
            source = RecipeSource.__new__(RecipeSource)
            object.__setattr__(source, "ref", "test")
            object.__setattr__(source, "format", "json")
            object.__setattr__(source, "read_kwargs", None)
            with pytest.raises(RecipeError, match="Unsupported format"):
                _read_source_file(Path(f.name), source)


class TestResolveSources:
    """Tests for source resolution."""

    def _make_module(self, sources: list[RecipeSource], schema: dict | None = None) -> ModuleType:
        """Create a fake recipe module with given SOURCES."""
        module = MagicMock(spec=ModuleType)
        module.SOURCES = sources
        module.EXPECTED_SCHEMA = schema or {}
        return module

    def test_resolve_csv_source(self) -> None:
        """Resolve a single CSV source from data directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "data.csv"
            csv_path.write_text("col1,col2\n1,2\n")

            module = self._make_module([RecipeSource(ref="data", path="data.csv", format="csv")])
            sources = resolve_sources(module, tmpdir)
            assert "data" in sources
            assert sources["data"].shape == (1, 2)

    def test_resolve_skips_dc_ref_sources(self) -> None:
        """Sources with dc_ref are skipped (must be injected externally)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            module = self._make_module([RecipeSource(ref="meta", dc_ref="metadata")])
            sources = resolve_sources(module, tmpdir)
            assert "meta" not in sources

    def test_resolve_missing_file_raises(self) -> None:
        """Missing source file raises RecipeError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            module = self._make_module([RecipeSource(ref="data", path="missing.csv", format="csv")])
            with pytest.raises(RecipeError, match="file not found"):
                resolve_sources(module, tmpdir)

    def test_resolve_empty_file_raises(self) -> None:
        """Source file with 0 rows raises RecipeError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "empty.csv"
            csv_path.write_text("col1,col2\n")

            module = self._make_module([RecipeSource(ref="data", path="empty.csv", format="csv")])
            with pytest.raises(RecipeError, match="0 rows"):
                resolve_sources(module, tmpdir)

    def test_resolve_with_overrides(self) -> None:
        """Source path overrides are applied."""
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "actual.csv"
            csv_path.write_text("a,b\n1,2\n")

            module = self._make_module(
                [RecipeSource(ref="data", path="original.csv", format="csv")]
            )
            sources = resolve_sources(module, tmpdir, overrides={"data": "actual.csv"})
            assert "data" in sources

    def test_resolve_no_path_no_dc_ref_raises(self) -> None:
        """Source with neither path nor dc_ref raises RecipeError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source = RecipeSource.__new__(RecipeSource)
            object.__setattr__(source, "ref", "broken")
            object.__setattr__(source, "path", None)
            object.__setattr__(source, "dc_ref", None)
            object.__setattr__(source, "format", "csv")
            object.__setattr__(source, "read_kwargs", None)

            module = self._make_module([source])
            with pytest.raises(RecipeError, match="no path and no dc_ref"):
                resolve_sources(module, tmpdir)


class TestValidateSchema:
    """Tests for output schema validation."""

    def test_valid_schema(self) -> None:
        """DataFrame matching expected schema passes validation."""
        df = pl.DataFrame({"x": [1, 2], "y": ["a", "b"]})
        validate_schema(df, {"x": pl.Int64, "y": pl.Utf8}, "test_recipe")

    def test_missing_column(self) -> None:
        """Missing column in output raises RecipeError."""
        df = pl.DataFrame({"x": [1, 2]})
        with pytest.raises(RecipeError, match="missing output column 'y'"):
            validate_schema(df, {"x": pl.Int64, "y": pl.Utf8}, "test_recipe")

    def test_wrong_dtype(self) -> None:
        """Column with wrong dtype raises RecipeError."""
        df = pl.DataFrame({"x": ["not_int"]})
        with pytest.raises(RecipeError, match="expected Int64"):
            validate_schema(df, {"x": pl.Int64}, "test_recipe")


class TestExecuteRecipe:
    """Tests for the full execute_recipe pipeline."""

    def test_execute_with_synthetic_data(self) -> None:
        """Execute a simple recipe against synthetic CSV data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a minimal recipe module file
            recipe_dir = Path(tmpdir) / "test_recipes"
            recipe_dir.mkdir()
            recipe_file = recipe_dir / "simple.py"
            recipe_file.write_text(
                "import polars as pl\n"
                "from depictio.models.models.transforms import RecipeSource\n"
                "\n"
                "SOURCES = [RecipeSource(ref='input', path='data.csv', format='csv')]\n"
                "EXPECTED_SCHEMA = {'value': pl.Int64}\n"
                "\n"
                "def transform(sources):\n"
                "    return sources['input'].select('value')\n"
            )

            # Create data file
            data_file = Path(tmpdir) / "data.csv"
            data_file.write_text("value,extra\n1,a\n2,b\n")

            # Monkey-patch RECIPES_DIR temporarily
            import depictio.recipes as recipes_mod

            original_dir = recipes_mod.RECIPES_DIR
            try:
                recipes_mod.RECIPES_DIR = recipe_dir
                result = execute_recipe("simple.py", tmpdir)
                assert result.shape == (2, 1)
                assert result.columns == ["value"]
            finally:
                recipes_mod.RECIPES_DIR = original_dir

    def test_execute_recipe_transform_returns_non_dataframe(self) -> None:
        """transform() returning non-DataFrame raises RecipeError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recipe_dir = Path(tmpdir) / "test_recipes"
            recipe_dir.mkdir()
            recipe_file = recipe_dir / "bad.py"
            recipe_file.write_text(
                "import polars as pl\n"
                "from depictio.models.models.transforms import RecipeSource\n"
                "\n"
                "SOURCES = [RecipeSource(ref='input', path='data.csv', format='csv')]\n"
                "EXPECTED_SCHEMA = {'value': pl.Int64}\n"
                "\n"
                "def transform(sources):\n"
                "    return {'not': 'a dataframe'}\n"
            )

            data_file = Path(tmpdir) / "data.csv"
            data_file.write_text("value\n1\n")

            import depictio.recipes as recipes_mod

            original_dir = recipes_mod.RECIPES_DIR
            try:
                recipes_mod.RECIPES_DIR = recipe_dir
                with pytest.raises(RecipeError, match="must return pl.DataFrame"):
                    execute_recipe("bad.py", tmpdir)
            finally:
                recipes_mod.RECIPES_DIR = original_dir

    def test_execute_with_extra_sources(self) -> None:
        """dc_ref sources can be injected via extra_sources."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recipe_dir = Path(tmpdir) / "test_recipes"
            recipe_dir.mkdir()
            recipe_file = recipe_dir / "joined.py"
            recipe_file.write_text(
                "import polars as pl\n"
                "from depictio.models.models.transforms import RecipeSource\n"
                "\n"
                "SOURCES = [\n"
                "    RecipeSource(ref='main', path='data.csv', format='csv'),\n"
                "    RecipeSource(ref='meta', dc_ref='metadata'),\n"
                "]\n"
                "EXPECTED_SCHEMA = {'id': pl.Utf8, 'label': pl.Utf8}\n"
                "\n"
                "def transform(sources):\n"
                "    return sources['main'].join(sources['meta'], on='id')\n"
            )

            data_file = Path(tmpdir) / "data.csv"
            data_file.write_text("id\nA\nB\n")

            meta_df = pl.DataFrame({"id": ["A", "B"], "label": ["alpha", "beta"]})

            import depictio.recipes as recipes_mod

            original_dir = recipes_mod.RECIPES_DIR
            try:
                recipes_mod.RECIPES_DIR = recipe_dir
                result = execute_recipe("joined.py", tmpdir, extra_sources={"meta": meta_df})
                assert result.shape == (2, 2)
                assert "label" in result.columns
            finally:
                recipes_mod.RECIPES_DIR = original_dir

    def test_execute_unresolved_dc_ref_raises(self) -> None:
        """Missing dc_ref source without extra_sources raises RecipeError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recipe_dir = Path(tmpdir) / "test_recipes"
            recipe_dir.mkdir()
            recipe_file = recipe_dir / "needs_meta.py"
            recipe_file.write_text(
                "import polars as pl\n"
                "from depictio.models.models.transforms import RecipeSource\n"
                "\n"
                "SOURCES = [\n"
                "    RecipeSource(ref='main', path='data.csv', format='csv'),\n"
                "    RecipeSource(ref='meta', dc_ref='metadata'),\n"
                "]\n"
                "EXPECTED_SCHEMA = {'id': pl.Utf8}\n"
                "\n"
                "def transform(sources):\n"
                "    return sources['main']\n"
            )

            data_file = Path(tmpdir) / "data.csv"
            data_file.write_text("id\nA\n")

            import depictio.recipes as recipes_mod

            original_dir = recipes_mod.RECIPES_DIR
            try:
                recipes_mod.RECIPES_DIR = recipe_dir
                with pytest.raises(RecipeError, match="not resolved"):
                    execute_recipe("needs_meta.py", tmpdir)
            finally:
                recipes_mod.RECIPES_DIR = original_dir
