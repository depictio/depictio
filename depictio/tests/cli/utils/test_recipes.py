"""
Tests for the recipe loader/executor system (depictio/recipes/__init__.py).

Tests here use only synthetic fixture data (in-memory or temp-dir recipes) and
never depend on any specific pipeline (ampliseq, etc.) existing on disk.

Covers:
- Recipe discovery (list_recipes)
- Recipe loading and validation (load_recipe)
- Source file reading (_read_source_file)
- Source resolution (resolve_sources)
- Schema validation (validate_schema)
- Full pipeline execution (execute_recipe)
- Structural validation of every bundled recipe on disk (TestBundledRecipes)
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

# ---------------------------------------------------------------------------
# Helpers shared across test classes
# ---------------------------------------------------------------------------

_MINIMAL_RECIPE = (
    "import polars as pl\n"
    "from depictio.models.models.transforms import RecipeSource\n"
    "\n"
    "SOURCES = [RecipeSource(ref='input', path='data.csv', format='csv')]\n"
    "EXPECTED_SCHEMA = {'value': pl.Int64}\n"
    "\n"
    "def transform(sources):\n"
    "    return sources['input'].select('value')\n"
)


def _make_fake_projects_dir(tmpdir: str, recipe_name: str, code: str) -> Path:
    """Create a minimal fake projects dir with a shared recipe at pipeline/recipes/name."""
    projects_dir = Path(tmpdir) / "projects"
    *pipeline_parts, name = recipe_name.split("/")
    pipeline = "/".join(pipeline_parts)
    recipe_dir = projects_dir / pipeline / "recipes"
    recipe_dir.mkdir(parents=True)
    (recipe_dir / name).write_text(code)
    return projects_dir


class TestListRecipes:
    """Tests for recipe discovery using a synthetic projects directory."""

    def _make_projects(self, tmpdir: str) -> Path:
        """Create a minimal fake projects dir with two synthetic recipes."""
        projects_dir = Path(tmpdir) / "projects"
        for pipeline, name in [("vendor/alpha", "transform.py"), ("vendor/beta", "compute.py")]:
            recipe_dir = projects_dir / pipeline / "recipes"
            recipe_dir.mkdir(parents=True)
            (recipe_dir / name).write_text(_MINIMAL_RECIPE)
        return projects_dir

    def test_list_recipes_returns_sorted_list(self) -> None:
        """list_recipes returns a sorted list of recipe paths."""
        import depictio.recipes as recipes_mod

        with tempfile.TemporaryDirectory() as tmpdir:
            original = recipes_mod.PROJECTS_DIR
            try:
                recipes_mod.PROJECTS_DIR = self._make_projects(tmpdir)
                recipes = list_recipes()
                assert isinstance(recipes, list)
                assert recipes == sorted(recipes)
            finally:
                recipes_mod.PROJECTS_DIR = original

    def test_list_recipes_excludes_init_files(self) -> None:
        """__init__.py files are excluded from recipe list."""
        import depictio.recipes as recipes_mod

        with tempfile.TemporaryDirectory() as tmpdir:
            projects_dir = self._make_projects(tmpdir)
            # Plant a __init__.py in the recipes dir; it must be excluded
            init_path = projects_dir / "vendor" / "alpha" / "recipes" / "__init__.py"
            init_path.write_text("")

            original = recipes_mod.PROJECTS_DIR
            try:
                recipes_mod.PROJECTS_DIR = projects_dir
                recipes = list_recipes()
                assert not any("__init__" in r for r in recipes)
            finally:
                recipes_mod.PROJECTS_DIR = original

    def test_list_recipes_contains_synthetic_recipes(self) -> None:
        """Synthetic recipe files are present in the discovered list."""
        import depictio.recipes as recipes_mod

        with tempfile.TemporaryDirectory() as tmpdir:
            original = recipes_mod.PROJECTS_DIR
            try:
                recipes_mod.PROJECTS_DIR = self._make_projects(tmpdir)
                recipes = list_recipes()
                assert "vendor/alpha/transform.py" in recipes
                assert "vendor/beta/compute.py" in recipes
            finally:
                recipes_mod.PROJECTS_DIR = original

    def test_list_recipes_excludes_version_overrides(self) -> None:
        """Version-specific override recipes are not listed."""
        import depictio.recipes as recipes_mod

        with tempfile.TemporaryDirectory() as tmpdir:
            projects_dir = self._make_projects(tmpdir)
            # Plant a version override that should be excluded
            version_dir = projects_dir / "vendor" / "alpha" / "1.0.0"
            override_dir = version_dir / "recipes"
            override_dir.mkdir(parents=True)
            (version_dir / "template.yaml").write_text("template_id: vendor/alpha/1.0.0\n")
            (override_dir / "transform.py").write_text(_MINIMAL_RECIPE)

            original = recipes_mod.PROJECTS_DIR
            try:
                recipes_mod.PROJECTS_DIR = projects_dir
                recipes = list_recipes()
                assert not any("/1.0.0/" in r for r in recipes)
            finally:
                recipes_mod.PROJECTS_DIR = original

    def test_list_recipes_empty_projects_dir(self) -> None:
        """Empty projects dir returns empty list."""
        import depictio.recipes as recipes_mod

        with tempfile.TemporaryDirectory() as tmpdir:
            projects_dir = Path(tmpdir) / "projects"
            projects_dir.mkdir()
            original = recipes_mod.PROJECTS_DIR
            try:
                recipes_mod.PROJECTS_DIR = projects_dir
                assert list_recipes() == []
            finally:
                recipes_mod.PROJECTS_DIR = original


class TestLoadRecipe:
    """Tests for recipe module loading and validation using synthetic recipes."""

    def test_load_known_recipe(self) -> None:
        """Loading a known synthetic recipe returns a module with required attributes."""
        import depictio.recipes as recipes_mod

        with tempfile.TemporaryDirectory() as tmpdir:
            projects_dir = _make_fake_projects_dir(
                tmpdir, "vendor/pipe/transform.py", _MINIMAL_RECIPE
            )
            original = recipes_mod.PROJECTS_DIR
            try:
                recipes_mod.PROJECTS_DIR = projects_dir
                module = load_recipe("vendor/pipe/transform.py")
                assert hasattr(module, "SOURCES")
                assert hasattr(module, "EXPECTED_SCHEMA")
                assert callable(module.transform)
            finally:
                recipes_mod.PROJECTS_DIR = original

    def test_load_recipe_sources_are_recipe_source_instances(self) -> None:
        """SOURCES must be a list of RecipeSource instances."""
        import depictio.recipes as recipes_mod

        with tempfile.TemporaryDirectory() as tmpdir:
            projects_dir = _make_fake_projects_dir(
                tmpdir, "vendor/pipe/transform.py", _MINIMAL_RECIPE
            )
            original = recipes_mod.PROJECTS_DIR
            try:
                recipes_mod.PROJECTS_DIR = projects_dir
                module = load_recipe("vendor/pipe/transform.py")
                assert isinstance(module.SOURCES, list)
                assert len(module.SOURCES) > 0
                for s in module.SOURCES:
                    assert isinstance(s, RecipeSource)
            finally:
                recipes_mod.PROJECTS_DIR = original

    def test_load_recipe_not_found(self) -> None:
        """Loading a nonexistent recipe raises RecipeError."""
        with pytest.raises(RecipeError, match="not found"):
            load_recipe("nonexistent/recipe.py")

    def test_load_all_synthetic_recipes(self) -> None:
        """All synthetic recipes load successfully and have valid attributes."""
        import depictio.recipes as recipes_mod

        recipes_code = {
            "vendor/alpha/transform.py": _MINIMAL_RECIPE,
            "vendor/beta/compute.py": (
                "import polars as pl\n"
                "from depictio.models.models.transforms import RecipeSource\n"
                "\n"
                "SOURCES = [RecipeSource(ref='tbl', path='table.tsv', format='tsv')]\n"
                "EXPECTED_SCHEMA = {'name': pl.Utf8, 'count': pl.Int64}\n"
                "\n"
                "def transform(sources):\n"
                "    return sources['tbl']\n"
            ),
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            projects_dir = Path(tmpdir) / "projects"
            for recipe_name, code in recipes_code.items():
                *pipeline_parts, name = recipe_name.split("/")
                pipeline = "/".join(pipeline_parts)
                recipe_dir = projects_dir / pipeline / "recipes"
                recipe_dir.mkdir(parents=True)
                (recipe_dir / name).write_text(code)

            original = recipes_mod.PROJECTS_DIR
            try:
                recipes_mod.PROJECTS_DIR = projects_dir
                for recipe_name in list_recipes():
                    module = load_recipe(recipe_name)
                    assert hasattr(module, "SOURCES")
                    assert hasattr(module, "EXPECTED_SCHEMA")
                    assert callable(module.transform)
                    assert isinstance(module.SOURCES, list)
                    assert len(module.SOURCES) > 0
                    assert isinstance(module.EXPECTED_SCHEMA, dict)
                    assert len(module.EXPECTED_SCHEMA) > 0
            finally:
                recipes_mod.PROJECTS_DIR = original

    def test_load_recipe_version_override(self) -> None:
        """Version-specific override is loaded when version is provided and override exists."""
        import depictio.recipes as recipes_mod

        shared_code = (
            "import polars as pl\n"
            "from depictio.models.models.transforms import RecipeSource\n"
            "SOURCES = [RecipeSource(ref='d', path='data.csv', format='csv')]\n"
            "EXPECTED_SCHEMA = {'shared_col': pl.Int64}\n"
            "def transform(s): return s['d'].rename({'value': 'shared_col'})\n"
        )
        override_code = (
            "import polars as pl\n"
            "from depictio.models.models.transforms import RecipeSource\n"
            "SOURCES = [RecipeSource(ref='d', path='data.csv', format='csv')]\n"
            "EXPECTED_SCHEMA = {'versioned_col': pl.Int64}\n"
            "def transform(s): return s['d'].rename({'value': 'versioned_col'})\n"
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            projects_dir = Path(tmpdir) / "projects"
            shared_dir = projects_dir / "vendor" / "pipe" / "recipes"
            shared_dir.mkdir(parents=True)
            (shared_dir / "recipe.py").write_text(shared_code)

            version_dir = projects_dir / "vendor" / "pipe" / "1.0.0"
            override_dir = version_dir / "recipes"
            override_dir.mkdir(parents=True)
            (version_dir / "template.yaml").write_text("template_id: vendor/pipe/1.0.0\n")
            (override_dir / "recipe.py").write_text(override_code)

            original = recipes_mod.PROJECTS_DIR
            try:
                recipes_mod.PROJECTS_DIR = projects_dir
                module_versioned = load_recipe("vendor/pipe/recipe.py", "1.0.0")
                module_shared = load_recipe("vendor/pipe/recipe.py")
                assert callable(module_versioned.transform)
                assert callable(module_shared.transform)
                # They are different modules (different EXPECTED_SCHEMA keys)
                assert set(module_versioned.EXPECTED_SCHEMA.keys()) != set(
                    module_shared.EXPECTED_SCHEMA.keys()
                )
            finally:
                recipes_mod.PROJECTS_DIR = original

    def test_load_recipe_version_fallback_to_shared(self) -> None:
        """When no version override exists, shared recipe is used."""
        import depictio.recipes as recipes_mod

        with tempfile.TemporaryDirectory() as tmpdir:
            projects_dir = _make_fake_projects_dir(tmpdir, "vendor/pipe/recipe.py", _MINIMAL_RECIPE)
            # Version dir exists but no override for recipe.py
            version_dir = projects_dir / "vendor" / "pipe" / "2.0.0"
            override_dir = version_dir / "recipes"
            override_dir.mkdir(parents=True)
            (version_dir / "template.yaml").write_text("template_id: vendor/pipe/2.0.0\n")

            original = recipes_mod.PROJECTS_DIR
            try:
                recipes_mod.PROJECTS_DIR = projects_dir
                module_versioned = load_recipe("vendor/pipe/recipe.py", "2.0.0")
                module_shared = load_recipe("vendor/pipe/recipe.py")
                assert module_versioned.SOURCES == module_shared.SOURCES
            finally:
                recipes_mod.PROJECTS_DIR = original


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
            module = self._make_module([RecipeSource(ref="meta", dc_ref="other_dc")])
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
            object.__setattr__(source, "glob_pattern", None)

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

    def test_optional_schema_absent_passes(self) -> None:
        """Optional column absent from result: no error."""
        df = pl.DataFrame({"x": [1]})
        validate_schema(df, {"x": pl.Int64}, "test_recipe", optional_schema={"opt_col": pl.Utf8})

    def test_optional_schema_present_correct_type_passes(self) -> None:
        """Optional column present with correct type: no error."""
        df = pl.DataFrame({"x": [1], "opt_col": ["value"]})
        validate_schema(df, {"x": pl.Int64}, "test_recipe", optional_schema={"opt_col": pl.Utf8})

    def test_optional_schema_present_wrong_type_raises(self) -> None:
        """Optional column present with wrong type: RecipeError."""
        df = pl.DataFrame({"x": [1], "opt_col": [99]})
        with pytest.raises(RecipeError, match="optional column 'opt_col'"):
            validate_schema(
                df, {"x": pl.Int64}, "test_recipe", optional_schema={"opt_col": pl.Utf8}
            )

    def test_optional_schema_none_is_noop(self) -> None:
        """optional_schema=None behaves the same as no optional_schema."""
        df = pl.DataFrame({"x": [1]})
        validate_schema(df, {"x": pl.Int64}, "test_recipe", optional_schema=None)


class TestExecuteRecipe:
    """Tests for the full execute_recipe pipeline."""

    def test_execute_with_synthetic_data(self) -> None:
        """Execute a simple recipe against synthetic CSV data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            projects_dir = _make_fake_projects_dir(tmpdir, "mypipe/simple.py", _MINIMAL_RECIPE)
            data_file = Path(tmpdir) / "data.csv"
            data_file.write_text("value,extra\n1,a\n2,b\n")

            import depictio.recipes as recipes_mod

            original_dir = recipes_mod.PROJECTS_DIR
            try:
                recipes_mod.PROJECTS_DIR = projects_dir
                result = execute_recipe("mypipe/simple.py", tmpdir)
                assert result.shape == (2, 1)
                assert result.columns == ["value"]
            finally:
                recipes_mod.PROJECTS_DIR = original_dir

    def test_execute_recipe_transform_returns_non_dataframe(self) -> None:
        """transform() returning non-DataFrame raises RecipeError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            projects_dir = _make_fake_projects_dir(
                tmpdir,
                "mypipe/bad.py",
                "import polars as pl\n"
                "from depictio.models.models.transforms import RecipeSource\n"
                "\n"
                "SOURCES = [RecipeSource(ref='input', path='data.csv', format='csv')]\n"
                "EXPECTED_SCHEMA = {'value': pl.Int64}\n"
                "\n"
                "def transform(sources):\n"
                "    return {'not': 'a dataframe'}\n",
            )

            data_file = Path(tmpdir) / "data.csv"
            data_file.write_text("value\n1\n")

            import depictio.recipes as recipes_mod

            original_dir = recipes_mod.PROJECTS_DIR
            try:
                recipes_mod.PROJECTS_DIR = projects_dir
                with pytest.raises(RecipeError, match="must return pl.DataFrame"):
                    execute_recipe("mypipe/bad.py", tmpdir)
            finally:
                recipes_mod.PROJECTS_DIR = original_dir

    def test_execute_with_extra_sources(self) -> None:
        """dc_ref sources can be injected via extra_sources."""
        with tempfile.TemporaryDirectory() as tmpdir:
            projects_dir = _make_fake_projects_dir(
                tmpdir,
                "mypipe/joined.py",
                "import polars as pl\n"
                "from depictio.models.models.transforms import RecipeSource\n"
                "\n"
                "SOURCES = [\n"
                "    RecipeSource(ref='main', path='data.csv', format='csv'),\n"
                "    RecipeSource(ref='meta', dc_ref='other_dc'),\n"
                "]\n"
                "EXPECTED_SCHEMA = {'id': pl.Utf8, 'label': pl.Utf8}\n"
                "\n"
                "def transform(sources):\n"
                "    return sources['main'].join(sources['meta'], on='id')\n",
            )

            data_file = Path(tmpdir) / "data.csv"
            data_file.write_text("id\nA\nB\n")
            meta_df = pl.DataFrame({"id": ["A", "B"], "label": ["alpha", "beta"]})

            import depictio.recipes as recipes_mod

            original_dir = recipes_mod.PROJECTS_DIR
            try:
                recipes_mod.PROJECTS_DIR = projects_dir
                result = execute_recipe("mypipe/joined.py", tmpdir, extra_sources={"meta": meta_df})
                assert result.shape == (2, 2)
                assert "label" in result.columns
            finally:
                recipes_mod.PROJECTS_DIR = original_dir

    def test_execute_unresolved_dc_ref_raises(self) -> None:
        """Missing dc_ref source without extra_sources raises RecipeError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            projects_dir = _make_fake_projects_dir(
                tmpdir,
                "mypipe/needs_meta.py",
                "import polars as pl\n"
                "from depictio.models.models.transforms import RecipeSource\n"
                "\n"
                "SOURCES = [\n"
                "    RecipeSource(ref='main', path='data.csv', format='csv'),\n"
                "    RecipeSource(ref='meta', dc_ref='other_dc'),\n"
                "]\n"
                "EXPECTED_SCHEMA = {'id': pl.Utf8}\n"
                "\n"
                "def transform(sources):\n"
                "    return sources['main']\n",
            )

            data_file = Path(tmpdir) / "data.csv"
            data_file.write_text("id\nA\n")

            import depictio.recipes as recipes_mod

            original_dir = recipes_mod.PROJECTS_DIR
            try:
                recipes_mod.PROJECTS_DIR = projects_dir
                with pytest.raises(RecipeError, match="not resolved"):
                    execute_recipe("mypipe/needs_meta.py", tmpdir)
            finally:
                recipes_mod.PROJECTS_DIR = original_dir

    def test_execute_optional_dc_ref_passes_none(self) -> None:
        """Optional dc_ref not provided via extra_sources: None passed to transform."""
        with tempfile.TemporaryDirectory() as tmpdir:
            projects_dir = _make_fake_projects_dir(
                tmpdir,
                "mypipe/optional_meta.py",
                "import polars as pl\n"
                "from depictio.models.models.transforms import RecipeSource\n"
                "\n"
                "SOURCES = [\n"
                "    RecipeSource(ref='main', path='data.csv', format='csv'),\n"
                "    RecipeSource(ref='meta', dc_ref='other_dc', optional=True),\n"
                "]\n"
                "EXPECTED_SCHEMA = {'id': pl.Utf8}\n"
                "\n"
                "def transform(sources):\n"
                "    assert sources['meta'] is None\n"
                "    return sources['main'].select('id')\n",
            )

            data_file = Path(tmpdir) / "data.csv"
            data_file.write_text("id\nA\nB\n")

            import depictio.recipes as recipes_mod

            original_dir = recipes_mod.PROJECTS_DIR
            try:
                recipes_mod.PROJECTS_DIR = projects_dir
                result = execute_recipe("mypipe/optional_meta.py", tmpdir)
                assert list(result["id"]) == ["A", "B"]
            finally:
                recipes_mod.PROJECTS_DIR = original_dir

    def test_execute_with_version_override(self) -> None:
        """Version-specific override recipe is used when it exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            projects_dir = Path(tmpdir) / "projects"
            # Shared recipe returns column "shared_col"
            shared_dir = projects_dir / "mypipe" / "recipes"
            shared_dir.mkdir(parents=True)
            (shared_dir / "recipe.py").write_text(
                "import polars as pl\n"
                "from depictio.models.models.transforms import RecipeSource\n"
                "SOURCES = [RecipeSource(ref='d', path='data.csv', format='csv')]\n"
                "EXPECTED_SCHEMA = {'shared_col': pl.Int64}\n"
                "def transform(s): return s['d'].rename({'value': 'shared_col'})\n"
            )
            # Version override returns column "versioned_col"
            version_dir = projects_dir / "mypipe" / "1.0.0"
            version_recipes_dir = version_dir / "recipes"
            version_recipes_dir.mkdir(parents=True)
            (version_dir / "template.yaml").write_text("template_id: mypipe/1.0.0\n")
            (version_recipes_dir / "recipe.py").write_text(
                "import polars as pl\n"
                "from depictio.models.models.transforms import RecipeSource\n"
                "SOURCES = [RecipeSource(ref='d', path='data.csv', format='csv')]\n"
                "EXPECTED_SCHEMA = {'versioned_col': pl.Int64}\n"
                "def transform(s): return s['d'].rename({'value': 'versioned_col'})\n"
            )

            data_file = Path(tmpdir) / "data.csv"
            data_file.write_text("value\n42\n")

            import depictio.recipes as recipes_mod

            original_dir = recipes_mod.PROJECTS_DIR
            try:
                recipes_mod.PROJECTS_DIR = projects_dir
                # Without version → shared
                result_shared = execute_recipe("mypipe/recipe.py", tmpdir)
                assert "shared_col" in result_shared.columns
                # With version → override
                result_versioned = execute_recipe(
                    "mypipe/recipe.py", tmpdir, pipeline_version="1.0.0"
                )
                assert "versioned_col" in result_versioned.columns
            finally:
                recipes_mod.PROJECTS_DIR = original_dir


@pytest.mark.parametrize("recipe_name", list_recipes())
def test_bundled_recipe_structure(recipe_name: str) -> None:
    """Every bundled recipe on disk has SOURCES, EXPECTED_SCHEMA, and a callable transform."""
    module = load_recipe(recipe_name)
    assert hasattr(module, "SOURCES"), f"{recipe_name}: missing SOURCES"
    assert hasattr(module, "EXPECTED_SCHEMA"), f"{recipe_name}: missing EXPECTED_SCHEMA"
    assert callable(module.transform), f"{recipe_name}: transform not callable"
    assert isinstance(module.SOURCES, list) and len(module.SOURCES) > 0
    assert isinstance(module.EXPECTED_SCHEMA, dict) and len(module.EXPECTED_SCHEMA) > 0
    for src in module.SOURCES:
        assert isinstance(src, RecipeSource), (
            f"{recipe_name}: SOURCES must contain RecipeSource instances"
        )
