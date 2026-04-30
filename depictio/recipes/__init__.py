"""Recipe loader and executor with 4 automatic validation checkpoints."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import polars as pl

from depictio.models.models.transforms import RecipeSource

# Recipes live inside the projects directory, co-located with the templates that use them.
# Shared (pipeline-level) recipes:  projects/{pipeline}/recipes/{name}.py
# Version overrides:                 projects/{pipeline}/{version}/recipes/{name}.py
PROJECTS_DIR = Path(__file__).parent.parent / "projects"


class RecipeError(Exception):
    """Raised when a recipe fails validation."""


# ---------------------------------------------------------------------------
# Path resolution: versioned-then-shared fallback
# ---------------------------------------------------------------------------


def resolve_recipe_path(recipe_ref: str, pipeline_version: str | None = None) -> Path:
    """Resolve the filesystem path for a recipe using versioned-then-shared fallback.

    Args:
        recipe_ref: Pipeline-qualified recipe name, e.g. 'nf-core/ampliseq/alpha_diversity.py'.
        pipeline_version: Optional pipeline version, e.g. '2.16.0'. When provided, a
            version-specific override is tried first before falling back to the shared recipe.

    Resolution order:
        1. PROJECTS_DIR/{pipeline}/{version}/recipes/{name}  — version override (if version given)
        2. PROJECTS_DIR/{pipeline}/recipes/{name}            — shared fallback
    """
    *pipeline_parts, name = recipe_ref.split("/")
    pipeline = "/".join(pipeline_parts)

    if pipeline_version:
        versioned = PROJECTS_DIR / pipeline / pipeline_version / "recipes" / name
        if versioned.exists():
            return versioned

    shared = PROJECTS_DIR / pipeline / "recipes" / name
    if shared.exists():
        return shared

    if pipeline_version:
        raise RecipeError(
            f"Recipe not found: {recipe_ref} "
            f"(tried version '{pipeline_version}' override and shared)"
        )
    raise RecipeError(f"Recipe not found: {recipe_ref}")


# ---------------------------------------------------------------------------
# Checkpoint 1: Load recipe module
# ---------------------------------------------------------------------------


def load_recipe(recipe_name: str, pipeline_version: str | None = None) -> ModuleType:
    """Load a recipe Python module by name.

    Args:
        recipe_name: Pipeline-qualified recipe name (e.g. 'nf-core/ampliseq/alpha_diversity.py').
        pipeline_version: Optional pipeline version for version-specific recipe lookup.

    Validates that the module has SOURCES, EXPECTED_SCHEMA, and a callable transform().
    """
    recipe_path = resolve_recipe_path(recipe_name, pipeline_version)

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


def _resolve_glob_source(data_dir: Path, source: RecipeSource) -> pl.DataFrame:
    """Glob for multiple files and concatenate into a single DataFrame."""
    pattern = source.glob_pattern
    if pattern is None:
        raise RecipeError(f"Source '{source.ref}' has no glob_pattern")

    matched_files = sorted(data_dir.glob(pattern))
    if not matched_files:
        raise RecipeError(f"Source '{source.ref}': no files matched glob '{pattern}' in {data_dir}")

    frames: list[pl.DataFrame] = []
    for file_path in matched_files:
        df = _read_source_file(file_path, source)
        if not df.is_empty():
            frames.append(df)

    if not frames:
        raise RecipeError(
            f"Source '{source.ref}': all {len(matched_files)} matched files were empty"
        )

    return pl.concat(frames, how="diagonal_relaxed")


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

        # Glob-based source: match multiple files and concatenate
        if source.glob_pattern is not None:
            sources[source.ref] = _resolve_glob_source(data_dir, source)
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


def validate_schema(
    result: pl.DataFrame,
    expected_schema: dict,
    recipe_name: str,
    optional_schema: dict | None = None,
) -> None:
    """Validate that the result DataFrame matches the expected schema.

    Args:
        result: Output DataFrame from transform().
        expected_schema: Dict of column_name → polars dtype. All must be present.
        recipe_name: Recipe name used in error messages.
        optional_schema: Dict of column_name → polars dtype. Validated only if present.
    """
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
    if optional_schema:
        for col_name, expected_type in optional_schema.items():
            if col_name in result.columns:
                actual_type = result[col_name].dtype
                if actual_type != expected_type:
                    raise RecipeError(
                        f"Recipe {recipe_name}: optional column '{col_name}' expected "
                        f"{expected_type}, got {actual_type}"
                    )


def execute_recipe(
    recipe_name: str,
    data_dir: str | Path,
    overrides: dict[str, str] | None = None,
    extra_sources: dict[str, pl.DataFrame] | None = None,
    pipeline_version: str | None = None,
) -> pl.DataFrame:
    """Full pipeline: load → resolve → transform → validate.

    Args:
        recipe_name: Pipeline-qualified recipe name (e.g. 'nf-core/ampliseq/alpha_diversity.py').
        data_dir: Root directory containing workflow output files.
        overrides: Optional source path overrides.
        extra_sources: Optional pre-loaded DataFrames for dc_ref sources.
        pipeline_version: Optional pipeline version for version-specific recipe lookup.

    Returns:
        Validated output DataFrame.
    """
    # Checkpoint 1: load
    module = load_recipe(recipe_name, pipeline_version)

    # Checkpoint 2: resolve
    sources = resolve_sources(module, data_dir, overrides)

    # Inject dc_ref sources
    if extra_sources:
        sources.update(extra_sources)

    # Check all sources are resolved; optional missing dc_ref sources are injected as None
    for source in module.SOURCES:
        if source.ref not in sources:
            if source.dc_ref is not None and source.optional:
                sources[source.ref] = None  # type: ignore[assignment]
            else:
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

    # Checkpoint 4: schema validation (required + optional columns)
    validate_schema(
        result,
        module.EXPECTED_SCHEMA,
        recipe_name,
        getattr(module, "OPTIONAL_SCHEMA", None),
    )

    return result


# ---------------------------------------------------------------------------
# Discovery helpers
# ---------------------------------------------------------------------------


def list_recipes() -> list[str]:
    """List all available shared recipe names.

    Returns pipeline-qualified names (e.g. 'nf-core/ampliseq/alpha_diversity.py').
    Version-specific overrides are not listed — they are applied automatically
    based on pipeline version context during execution.
    """
    recipes = []
    for py_file in PROJECTS_DIR.rglob("recipes/*.py"):
        if py_file.name == "__init__.py":
            continue
        # Version overrides live inside a directory that has a template.yaml.
        # Shared recipes live at the pipeline level (no template.yaml in parent).
        version_dir = py_file.parent.parent  # dir containing the "recipes/" folder
        if (version_dir / "template.yaml").exists():
            continue  # skip version-specific overrides
        pipeline_dir = version_dir
        recipe_ref = str(pipeline_dir.relative_to(PROJECTS_DIR) / py_file.name)
        recipes.append(recipe_ref)
    return sorted(recipes)
