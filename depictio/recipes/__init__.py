"""Recipe loader and executor with 4 automatic validation checkpoints."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import polars as pl

from depictio.models.models.transforms import RecipeSource

RECIPES_DIR = Path(__file__).parent


class RecipeError(Exception):
    """Raised when a recipe fails validation."""


# ---------------------------------------------------------------------------
# Checkpoint 1: Load recipe module
# ---------------------------------------------------------------------------


def load_recipe(recipe_name: str) -> ModuleType:
    """Load a recipe Python module by name (e.g. 'nf-core/ampliseq/alpha_diversity.py').

    Validates that the module has SOURCES, EXPECTED_SCHEMA, and a callable transform().
    """
    recipe_path = RECIPES_DIR / recipe_name
    if not recipe_path.exists():
        raise RecipeError(f"Recipe not found: {recipe_path}")

    spec = importlib.util.spec_from_file_location(
        f"depictio.recipes.{recipe_name.replace('/', '.')}", recipe_path
    )
    if spec is None or spec.loader is None:
        raise RecipeError(f"Could not load recipe module: {recipe_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # Validate required attributes
    if not hasattr(module, "SOURCES"):
        raise RecipeError(f"Recipe {recipe_name} missing SOURCES")
    if not hasattr(module, "EXPECTED_SCHEMA"):
        raise RecipeError(f"Recipe {recipe_name} missing EXPECTED_SCHEMA")
    if not callable(getattr(module, "transform", None)):
        raise RecipeError(f"Recipe {recipe_name} missing callable transform()")

    sources = module.SOURCES
    if not isinstance(sources, list) or len(sources) == 0:
        raise RecipeError(f"Recipe {recipe_name} SOURCES must be a non-empty list")
    for s in sources:
        if not isinstance(s, RecipeSource):
            raise RecipeError(f"Recipe {recipe_name} SOURCES must contain RecipeSource instances")

    return module


# ---------------------------------------------------------------------------
# Checkpoint 2: Resolve sources (read files into DataFrames)
# ---------------------------------------------------------------------------


def _read_source_file(file_path: Path, source: RecipeSource) -> pl.DataFrame:
    """Read a single source file into a DataFrame."""
    kwargs = source.read_kwargs or {}

    if source.format == "csv":
        return pl.read_csv(file_path, **kwargs)
    elif source.format == "tsv":
        return pl.read_csv(file_path, separator="\t", **kwargs)
    elif source.format == "parquet":
        return pl.read_parquet(file_path, **kwargs)
    else:
        raise RecipeError(f"Unsupported format: {source.format}")


def resolve_sources(
    module: ModuleType,
    data_dir: str | Path,
    overrides: dict[str, str] | None = None,
) -> dict[str, pl.DataFrame]:
    """Resolve all recipe sources by reading files from data_dir.

    Args:
        module: Loaded recipe module.
        data_dir: Root directory containing workflow output files.
        overrides: Optional dict mapping source ref -> override path.

    Returns:
        Dict mapping source ref names to DataFrames.
    """
    data_dir = Path(data_dir)
    sources: dict[str, pl.DataFrame] = {}

    for source in module.SOURCES:
        if source.dc_ref is not None:
            # dc_ref sources are resolved externally (e.g. from another DC)
            # Skip here — caller must inject these
            continue

        # Determine file path (apply override if present)
        rel_path = source.path
        if overrides and source.ref in overrides:
            rel_path = overrides[source.ref]

        if rel_path is None:
            raise RecipeError(f"Source '{source.ref}' has no path and no dc_ref")

        file_path = data_dir / rel_path
        if not file_path.exists():
            raise RecipeError(f"Source '{source.ref}': file not found: {file_path}")

        df = _read_source_file(file_path, source)
        if df.is_empty():
            raise RecipeError(f"Source '{source.ref}' loaded 0 rows from {file_path}")

        sources[source.ref] = df

    return sources


# ---------------------------------------------------------------------------
# Checkpoint 3 & 4: Execute transform and validate output
# ---------------------------------------------------------------------------


def validate_schema(result: pl.DataFrame, expected_schema: dict, recipe_name: str) -> None:
    """Validate that the result DataFrame matches the expected schema."""
    for col_name, expected_type in expected_schema.items():
        if col_name not in result.columns:
            raise RecipeError(
                f"Recipe {recipe_name}: missing output column '{col_name}'. "
                f"Got columns: {result.columns}"
            )
        actual_type = result[col_name].dtype
        if actual_type != expected_type:
            raise RecipeError(
                f"Recipe {recipe_name}: column '{col_name}' expected {expected_type}, "
                f"got {actual_type}"
            )


def execute_recipe(
    recipe_name: str,
    data_dir: str | Path,
    overrides: dict[str, str] | None = None,
    extra_sources: dict[str, pl.DataFrame] | None = None,
) -> pl.DataFrame:
    """Full pipeline: load → resolve → transform → validate.

    Args:
        recipe_name: Recipe path relative to recipes dir (e.g. 'nf-core/ampliseq/alpha_diversity.py').
        data_dir: Root directory containing workflow output files.
        overrides: Optional source path overrides.
        extra_sources: Optional pre-loaded DataFrames for dc_ref sources.

    Returns:
        Validated output DataFrame.
    """
    # Checkpoint 1: load
    module = load_recipe(recipe_name)

    # Checkpoint 2: resolve
    sources = resolve_sources(module, data_dir, overrides)

    # Inject dc_ref sources
    if extra_sources:
        sources.update(extra_sources)

    # Check all sources are resolved
    for source in module.SOURCES:
        if source.ref not in sources:
            raise RecipeError(
                f"Source '{source.ref}' not resolved. "
                f"If it uses dc_ref, provide it via extra_sources."
            )

    # Checkpoint 3: transform
    result = module.transform(sources)
    if not isinstance(result, pl.DataFrame):
        raise RecipeError(
            f"Recipe {recipe_name}: transform() must return pl.DataFrame, "
            f"got {type(result).__name__}"
        )
    if result.is_empty():
        raise RecipeError(f"Recipe {recipe_name}: transform() produced empty DataFrame")

    # Checkpoint 4: schema validation
    validate_schema(result, module.EXPECTED_SCHEMA, recipe_name)

    return result


# ---------------------------------------------------------------------------
# Discovery helpers
# ---------------------------------------------------------------------------


def list_recipes() -> list[str]:
    """List all available recipe names."""
    recipes = []
    for py_file in RECIPES_DIR.rglob("*.py"):
        if py_file.name == "__init__.py":
            continue
        rel = py_file.relative_to(RECIPES_DIR)
        recipes.append(str(rel))
    return sorted(recipes)
